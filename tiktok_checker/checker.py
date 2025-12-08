from __future__ import annotations
from asyncio import Semaphore, create_task, sleep, gather, wait_for, TimeoutError as AsyncTimeoutError, Queue
from typing import List, Optional, Callable, Awaitable
from random import uniform

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

from database import update_email_status
from .proxy import ProxyModel
from .browser_utils import launch_browser_context
from config import MAX_CONCURRENCY, REQUEST_TIMEOUT


URL_MAIN = "https://www.tiktok.com/"


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

    async def check_email(self, email: str, proxy: ProxyModel):
        proxy_str = proxy.proxy_string
        server = proxy.host + (f":{proxy.port}" if proxy.port else "")

        browser = None
        try:
            async with async_playwright() as pw:
                browser, context, page = await launch_browser_context(pw, proxy_str, headless=True)
                page.set_default_timeout(REQUEST_TIMEOUT)

                await self.log(f"→ <code>{email}</code>: проверка через {server}")

                # Получаем IP (для диагностики)
                # ip_info = await get_browser_ip(page)
                # await self.log(f"🌍 IP: {ip_info}")

                # --- 1. ЗАХОД НА САЙТ ---
                try:
                    response = await page.goto(URL_MAIN, wait_until="domcontentloaded")
                    if response and response.status >= 400:
                        raise Exception(f"HTTP {response.status}")
                except (PlaywrightTimeoutError, Exception):
                    proxy.error_count += 1
                    proxy.cooldown(5)
                    await self.log(f"⏱️ <code>{email}</code>: сайт не открылся (таймаут/ошибка)")
                    self.failed_emails.append(email)
                    return

                await sleep(uniform(2, 4))

                # --- 2. НАЖИМАЕМ КНОПКУ "ВОЙТИ" (Главная) ---
                login_btn_found = False
                try:
                    # Пробуем селектор
                    btn = page.locator('button[data-e2e="top-login-button"]').first
                    if await btn.is_visible():
                        await btn.click()
                        login_btn_found = True
                    else:
                        # Запасные варианты
                        for sel in ['button:has-text("Войти")', 'button:has-text("Log in")']:
                            if await page.locator(sel).first.is_visible():
                                await page.locator(sel).first.click()
                                login_btn_found = True
                                break
                except:
                    pass

                if not login_btn_found:
                    # Не баним прокси, если просто не нашли кнопку (может лаг интерфейса)
                    await self.log(f"⚠️ {email}: Кнопка 'Войти' не найдена")
                    self.failed_emails.append(email)
                    return

                await sleep(uniform(1.5, 2.5))

                # --- 3. ВЫБИРАЕМ СПОСОБ ВХОДА (Телефон/Почта) ---
                try:
                    await page.locator("xpath=//div[contains(text(), 'Использовать номер телефона')]").first.click()
                except:
                    # Возможно сразу открылось нужное окно, идем дальше
                    pass

                await sleep(uniform(1, 2))

                # --- 4. ПЕРЕКЛЮЧАЕМСЯ НА ПОЧТУ ---
                # Часто открывается вкладка телефона по умолчанию
                try:
                    link = page.get_by_text("Войти через эл. почту")
                    if await link.is_visible():
                        await link.click()
                        await sleep(1)
                except:
                    pass

                # --- 5. ЖМЕМ "ЗАБЫЛИ ПАРОЛЬ?" ---
                try:
                    await page.get_by_text("Забыли пароль?").click()
                except:
                    # Попробуем английский вариант или другой селектор
                    try:
                        await page.get_by_text("Forgot password?").click()
                    except:
                        await self.log(f"⚠️ {email}: Ссылка 'Забыли пароль' не найдена")
                        self.failed_emails.append(email)
                        return

                await sleep(uniform(1, 2))

                # --- 6. ЖМЕМ "СБРОС ПО ПОЧТЕ" ---
                try:
                    await page.get_by_text("Сброс пароля по электронной почте").click()
                except:
                    pass # Иногда это меню не вылезает, если сразу открылось поле ввода

                await sleep(1)

                # --- 7. ВВОД EMAIL ---
                try:
                    inp = page.locator('input[name="email"]')
                    await inp.click()
                    await page.keyboard.type(email, delay=uniform(50, 100))
                except:
                    await self.log(f"⚠️ {email}: Поле ввода email не найдено")
                    self.failed_emails.append(email)
                    return

                await sleep(uniform(1, 1.5))

                # --- 8. ОТПРАВИТЬ ---
                try:
                    # Селектор из теста
                    await page.locator('button[type="submit"]').click()
                except:
                    await self.log(f"⚠️ {email}: Кнопка отправки не найдена")
                    self.failed_emails.append(email)
                    return

                await sleep(4) # Ждем загрузки ответа

                # --- 9. АНАЛИЗ РЕЗУЛЬТАТА ---
                html = (await page.content()).lower()

                limit_errors = ["too many", "слишком много", "rate limit"]
                if any(x in html for x in limit_errors):
                    proxy.error_count += 1
                    proxy.cooldown(15)
                    await self.log(f"⚠️ {email}: Лимит запросов (rate limit)")
                    # Не меняем статус в БД, чтобы перепроверить позже,
                    # или ставим 'error' если хочешь пропустить
                    self.emails_queue.put_nowait(email)  # Возвращаем в очередь
                    return

                not_found = ["не зарегистрирован", "does not exist", "not registered"]
                if any(x in html for x in not_found):
                    proxy.success_count += 1
                    await self.log(f"❌ <code>{email}</code>: не зарегистрирован")
                    # ОБНОВЛЕНИЕ БД
                    await update_email_status(self.user_id, email, 'invalid')
                    return

                # Если ВАЛИД
                self.valid_emails.append(email)
                proxy.success_count += 1
                await self.log(f"✅ <code>{email}</code>: ВАЛИД!")
                # ОБНОВЛЕНИЕ БД
                await update_email_status(self.user_id, email, 'valid')

        except Exception as e:
            # Ошибка самого Playwright или сети
            proxy.error_count += 1
            proxy.cooldown(2)
            await self.log(f"⚠️ Ошибка {email}: {type(e).__name__}")
            self.failed_emails.append(email)

        finally:
            if browser:
                try:
                    await browser.close()
                except:
                    pass

    async def worker(self):
        while self.is_running:
            try:
                email = await wait_for(self.emails_queue.get(), timeout=2)
            except AsyncTimeoutError:
                continue

            if email is None:
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
                self.emails_queue.task_done()
                # Возвращаем email обратно в очередь, так как не смогли проверить
                # self.emails_queue.put_nowait(email) 
                continue

            async with self.semaphore:
                await self.check_email(email, proxy)

            self.emails_queue.task_done()
            self.checked_count += 1

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
