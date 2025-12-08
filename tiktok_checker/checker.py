
from __future__ import annotations
from asyncio import Semaphore, create_task, sleep, gather, wait_for, TimeoutError as AsyncTimeoutError, Queue
from datetime import datetime
from typing import List, Optional, Callable, Awaitable
from random import uniform

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

from .proxy import ProxyModel
from .browser_utils import launch_browser_context, get_browser_ip
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

    async def try_select_click(self, page, selectors: List[str]) -> bool:
        for sel in selectors:
            items = await page.locator(sel).all()
            if items:
                await items[0].click()
                return True
        return False

    async def try_select_fill(self, page, selectors: List[str], value: str) -> bool:
        for sel in selectors:
            items = await page.locator(sel).all()
            if items:
                await items[0].fill(value)
                return True
        return False

    async def check_email(self, email: str, proxy: ProxyModel):
        proxy_str = proxy.proxy_string
        server = proxy.host + (f":{proxy.port}" if proxy.port else "")

        browser = None
        try:
            async with async_playwright() as pw:
                # Передаем строку, как и ожидается
                browser, context, page = await launch_browser_context(pw, proxy_str, headless=True)
                page.set_default_timeout(REQUEST_TIMEOUT)

                await self.log(f"→ <code>{email}</code>: проверка через {server}")

                # Получаем фактический IP
                ip_info = await get_browser_ip(page)
                await self.log(f"🌍 <code>{email}</code>: браузер видит IP: {ip_info}")

                # Переход на сайт TikTok
                try:
                    response = await page.goto(URL_MAIN, wait_until="domcontentloaded")
                    if response and response.status >= 400:
                        raise Exception(f"HTTP {response.status}")
                except PlaywrightTimeoutError:
                    proxy.error_count += 1
                    proxy.cooldown(5)
                    await self.log(f"⏱️ <code>{email}</code>: таймаут через {server}")
                    self.failed_emails.append(email)
                    return
                except Exception:
                    proxy.ban("Прокси недоступен")
                    await self.log(f"🚫 Прокси {server} не работает")
                    self.failed_emails.append(email)
                    return

                await sleep(uniform(1.5, 2.3))

                ok = await self.try_select_click(page, [
                    'button:has-text("Войти")',
                    'button:has-text("Log in")',
                    '[data-e2e="login-button"]'
                ])
                if not ok:
                    # 🔴 УДАЛЁНЬ: proxy.error_count += 1
                    # 🔴 УДАЛЁНЬ: proxy.cooldown(2)

                    # Прокси не виноват, если не найдена кнопка. Логика, связанная с прокси, удалена.
                    await self.log(
                        f"⚠️ {email}: кнопка входа не найдена. Возможно, интерфейс TikTok изменился или это проблема Playwright.")
                    self.failed_emails.append(email)
                    return

                await sleep(uniform(1, 2))

                ok = await self.try_select_click(page, [
                    "text=Забыли пароль?",
                    "text=Forgot password?",
                ])
                if not ok:
                    proxy.error_count += 1
                    proxy.cooldown(2)
                    await self.log(f"⚠️ {email}: forgot password не найден")
                    self.failed_emails.append(email)
                    return

                await sleep(1)

                await self.try_select_click(page, [
                    'text=Email',
                    'text=Reset password by email'
                ])

                await sleep(1)

                ok = await self.try_select_fill(page, [
                    'input[type="email"]',
                    'input[name="email"]',
                ], email)

                if not ok:
                    proxy.error_count += 1
                    proxy.cooldown(2)
                    await self.log(f"⚠️ {email}: поле email не найдено")
                    self.failed_emails.append(email)
                    return

                await sleep(1.2)

                await self.try_select_click(page, [
                    'button[type="submit"]',
                    'button:has-text("Send")',
                    'button:has-text("Отправить")'
                ])

                await sleep(3)

                html = (await page.content()).lower()

                limit_errors = ["too many", "слишком много", "rate limit"]
                if any(x in html for x in limit_errors):
                    proxy.error_count += 1
                    proxy.cooldown(15)
                    await self.log(f"⚠️ {email}: rate limit через {server}")
                    self.failed_emails.append(email)
                    return

                not_found = ["не зарегистрирован", "does not exist", "not registered"]
                if any(x in html for x in not_found):
                    proxy.success_count += 1
                    await self.log(f"❌ <code>{email}</code>: не зарегистрирован")
                    return

                self.valid_emails.append(email)
                proxy.success_count += 1
                await self.log(f"✅ <code>{email}</code>: ВАЛИД!")

        except Exception as e:
            proxy.error_count += 1
            proxy.cooldown(5)
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
                        await self.log(f"⏳ Нет доступных прокси, ожидание ({wait_time * 10} сек)")
                    await sleep(10)
                    wait_time += 1

            if not proxy:
                await self.log("🚫 Все прокси недоступны")
                self.emails_queue.task_done()
                continue

            async with self.semaphore:
                await self.check_email(email, proxy)

            self.emails_queue.task_done()
            self.checked_count += 1

            if self.checked_count % 10 == 0 and self.total_emails:
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
            f"Ошибок: {bad}\n"
        )

        return self.valid_emails
