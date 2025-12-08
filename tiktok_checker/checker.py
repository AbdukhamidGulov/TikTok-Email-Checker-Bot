from __future__ import annotations
from asyncio import Semaphore, create_task, sleep, gather, wait_for, TimeoutError as AsyncTimeoutError, Queue
from typing import List, Optional, Callable, Awaitable
from random import uniform

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

from database import update_email_status
from .proxy import ProxyModel
from .browser_utils import launch_browser_context
from config import MAX_CONCURRENCY, REQUEST_TIMEOUT

# Используем новую, более прямую ссылку
URL_MAIN = "https://www.tiktok.com/login/email/forget-password"


class TikTokChecker:
    def __init__(self, proxies: List[str], log_callback: Callable[[int, str], Awaitable[None]], user_id: int):
        self.emails_queue: Queue[str] = Queue()
        self.proxy_pool = [ProxyModel(p) for p in proxies]
        self.log_callback = log_callback
        self.user_id = user_id

        self.valid_emails: List[str] = []
        self.failed_emails: List[str] = []

        self.total_emails = 0
        self.checked_count = 0
        self.is_running = True

        self.semaphore = Semaphore(min(MAX_CONCURRENCY, max(1, len(proxies))))

    async def log(self, message: str):
        try:
            await self.log_callback(self.user_id, message)
        except Exception:
            pass

    def get_proxy(self) -> Optional[ProxyModel]:
        candidates = [p for p in self.proxy_pool if p.is_available()]
        if not candidates:
            return None
        return sorted(candidates, key=lambda p: p.error_count)[0]

    async def process_email_on_page(self, page, email: str, proxy: ProxyModel) -> bool:
        """
        Проверяет один email на уже открытой странице (Шаги 7-9).
        Возвращает True, если нужно закрыть браузер и перезапуститься (критическая ошибка/rate limit).
        """

        await self.log(f"→ <code>{email}</code>: проверка через {proxy.host}")

        try:
            # --- 7. ВВОД EMAIL ---
            try:
                inp = page.locator('input[name="email"]')

                # ОЧИЩАЕМ поле перед вводом нового email (fill("") работает, даже если поле пустое)
                await inp.fill("")
                await inp.click()
                await page.keyboard.type(email, delay=uniform(50, 100))
            except:
                await self.log(f"⚠️ {email}: Поле ввода email не найдено")
                self.failed_emails.append(email)
                return False

            await sleep(uniform(1, 1.5))

            # --- СТАБИЛИЗАЦИЯ (TAB для прокрутки/фокуса) ---
            # Перемещаем фокус из поля email, чтобы открыть кнопку "Отправить код"
            await page.keyboard.press("Tab")
            await sleep(uniform(0.5, 1))

            # --- 8. ОТПРАВИТЬ / SEND CODE ---
            await self.log(f"→ <code>{email}</code>: Пытаюсь нажать кнопку 'Отправить код'")
            SEND_BUTTON_SELECTOR = 'button:has-text("Отправить код"), button:has-text("Send code")'

            try:
                # Ждем, пока кнопка станет видимой и кликабельной
                await page.wait_for_selector(SEND_BUTTON_SELECTOR, state='visible', timeout=15000)
                await page.locator(SEND_BUTTON_SELECTOR).click()
            except PlaywrightTimeoutError:
                await self.log(f"⚠️ {email}: Кнопка 'Отправить код' не найдена (Таймаут)")
                self.failed_emails.append(email)
                return False
            except Exception as e:
                await self.log(f"⚠️ {email}: Ошибка клика по кнопке 'Отправить код' ({type(e).__name__})")
                self.failed_emails.append(email)
                return False

            await self.log(f"→ <code>{email}</code>: Нажата кнопка 'Отправить код'")
            await sleep(4)

            # --- 9. АНАЛИЗ РЕЗУЛЬТАТА ---
            html = (await page.content()).lower()

            limit_errors = ["too many", "слишком много", "rate limit"]
            if any(x in html for x in limit_errors):
                proxy.error_count += 1
                proxy.cooldown(15)
                await self.log(f"⚠️ {email}: Лимит запросов (rate limit)")
                return True

            not_found = [
                "не зарегистрирован", "not registered", "does not exist",
                "isn't registered yet", "адрес эл. почты не зарегистрирован",
                "email address isn't registered yet"
            ]

            if any(x in html for x in not_found):
                proxy.success_count += 1
                await self.log(f"❌ <code>{email}</code>: не зарегистрирован")
                await update_email_status(self.user_id, email, 'invalid')
            else:
                self.valid_emails.append(email)
                proxy.success_count += 1
                await self.log(f"✅ <code>{email}</code>: ВАЛИД!")
                await update_email_status(self.user_id, email, 'valid')

            return False

        except Exception as e:
            await self.log(f"⚠️ Критическая ошибка {email}: {type(e).__name__}")
            self.failed_emails.append(email)
            return True  # Требуется перезапуск браузера

        finally:
            # После проверки *не* перезагружаем страницу, а просто ожидаем,
            # что форма вернется в исходное состояние (поле ввода и кнопка).
            await sleep(uniform(1, 2))

    async def check_email(self, proxy: ProxyModel):
        proxy_str = proxy.proxy_string
        server = proxy.host + (f":{proxy.port}" if proxy.port else "")

        browser = None
        context = None

        try:
            async with async_playwright() as pw:
                # --- 1. ЗАПУСК БРАУЗЕРА ---
                await self.log(f"→ 🔄 Запуск браузера через {server}")
                browser, context, page = await launch_browser_context(pw, proxy_str, headless=False)  # TODO: True
                page.set_default_timeout(REQUEST_TIMEOUT)

                # --- 2. ПЕРВЫЙ ЗАХОД НА САЙТ (Один раз) ---
                await page.goto(URL_MAIN, wait_until="domcontentloaded", timeout=60000)

                # --- 3. ОБРАБОТКА COOKIE (Один раз) ---
                COOKIE_DENY_SELECTOR = 'button:has-text("Отклонить использование дополнительных файлов cookie"), button:has-text("Deny additional cookies")'
                try:
                    await page.wait_for_selector(COOKIE_DENY_SELECTOR, state='visible', timeout=5000)
                    await page.locator(COOKIE_DENY_SELECTOR).click()
                    await self.log(f"→ <code>{server}</code>: Отклонены дополнительные файлы cookie.")
                except:
                    pass

                await sleep(uniform(1, 2))

                # --- 4. ЦИКЛ ОБРАБОТКИ EMAIL ---
                while self.is_running:
                    try:
                        email = await wait_for(self.emails_queue.get(), timeout=0.1)
                    except AsyncTimeoutError:
                        break

                    # Выполняем проверку
                    should_restart = await self.process_email_on_page(page, email, proxy)
                    self.emails_queue.task_done()
                    self.checked_count += 1

                    if should_restart:
                        self.emails_queue.put_nowait(email)
                        break

                await self.log(f"→ ✅ Поток через {server} завершил сессию.")

        except PlaywrightTimeoutError as e:
            proxy.error_count += 1
            proxy.cooldown(5)
            await self.log(f"❌ Критический таймаут {server}: {type(e).__name__}. Перезапуск...")

        except Exception as e:
            proxy.error_count += 1
            proxy.cooldown(2)
            await self.log(f"❌ Критическая ошибка {server}: {type(e).__name__}. Перезапуск...")

        finally:
            if context:
                try:
                    await context.close()
                except:
                    pass
            if browser:
                try:
                    await browser.close()
                except:
                    pass

    async def worker(self):
        while self.is_running:
            try:
                email_peek = await wait_for(self.emails_queue.get(), timeout=2)
                self.emails_queue.put_nowait(email_peek)
            except AsyncTimeoutError:
                continue

            if not self.is_running:
                break

            proxy = None
            wait_time = 0

            while not proxy and self.is_running and wait_time < 10:
                proxy = self.get_proxy()
                if not proxy:
                    if wait_time % 2 == 0:
                        await self.log(f"⏳ Нет прокси, жду ({wait_time * 10} сек)")
                    await sleep(10)
                    wait_time += 1

            if not proxy:
                await self.log("🚫 Все прокси недоступны")
                break

            async with self.semaphore:
                await self.check_email(proxy)

            if self.checked_count % 5 == 0 and self.total_emails:
                progress = (self.checked_count / self.total_emails) * 100
                await self.log(f"📊 Прогресс: {self.checked_count}/{self.total_emails} ({progress:.1f}%)")

    async def run_checker(self, emails: List[str]):
        if not self.proxy_pool:
            await self.log("❌ Нет прокси!")
            return []

        if not emails:
            await self.log("❌ Нет email!")
            return []

        self.total_emails = len(emails)

        for e in emails:
            await self.emails_queue.put(e)

        workers_count = min(len([p for p in self.proxy_pool if not p.is_banned]), MAX_CONCURRENCY)
        if workers_count == 0:
            await self.log("❌ Все прокси нерабочие!")
            return []

        await self.log(f"🚀 Начинаю проверку {len(emails)} email через {workers_count} потоков")

        workers = [create_task(self.worker()) for _ in range(workers_count)]

        await self.emails_queue.join()

        self.is_running = False
        for _ in range(workers_count):
            await self.emails_queue.put(None)

        await gather(*workers, return_exceptions=True)

        good = len(self.valid_emails)
        bad = len(self.failed_emails)

        await self.log(
            f"✅ <b>Готово!</b>\n"
            f"Всего: {self.total_emails}\n"
            f"Проверено: {self.checked_count}\n"
            f"Валид: {good}\n"
            f"Ошибок/Невалид: {bad}\n"
        )

        return self.valid_emails
