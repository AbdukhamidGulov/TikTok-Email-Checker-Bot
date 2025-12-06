import asyncio
from playwright.async_api import async_playwright
from random import uniform

# URL главной страницы
URL_MAIN = "https://www.tiktok.com/"


async def check_email(email: str, headless: bool = False):
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"]
        )

        # Ставим русский язык принудительно, чтобы тексты кнопок совпадали
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
            locale="ru-RU"
        )

        page = await context.new_page()

        try:
            print(f"[*] (1/6) Захожу на главную страницу...")
            await page.goto(URL_MAIN, timeout=60000)
            await asyncio.sleep(uniform(2, 4))

            # 1. Нажимаем красную кнопку "Войти"
            print(f"[*] (2/6) Ищу кнопку входа...")
            try:
                await page.get_by_role("button", name="Войти").first.click()
            except:
                # Запасной вариант селектора
                await page.click('button[data-e2e="top-login-button"]')

            await asyncio.sleep(uniform(1, 2))

            # 2. Выбираем "Использовать номер телефона или адрес..."
            # Ищем по частичному совпадению текста, чтобы было надежнее
            print(f"[*] (3/6) Выбираю способ входа...")
            await page.locator("xpath=//div[contains(text(), 'Использовать номер телефона или адрес')]").click()
            await asyncio.sleep(uniform(1, 2))

            # 3. ВАЖНО: Переключаемся на вкладку "Почта / имя пользователя"
            # Обычно по умолчанию открывается телефон, нам нужно нажать ссылку справа сверху формы
            print(f"[*] (4/6) Переключаюсь на вход по почте...")
            # Ищем ссылку "Войти через эл. почту или имя пользователя"
            try:
                await page.get_by_text("Войти через эл. почту или имя").click()
                await asyncio.sleep(uniform(0.5, 1.5))
            except:
                print("[!] Ссылка переключения не найдена, возможно мы уже на нужном экране.")

            # 4. Нажимаем "Забыли пароль?"
            print(f"[*] (5/6) Нажимаю 'Забыли пароль?'...")
            await page.get_by_text("Забыли пароль?").click()
            await asyncio.sleep(uniform(1, 2))

            # 5. Выбираем "Сброс пароля по электронной почте"
            print(f"[*] (6/6) Выбираю сброс по почте...")
            await page.get_by_text("Сброс пароля по электронной почте").click()
            await asyncio.sleep(uniform(1, 2))

            # --- Ввод данных ---
            print(f"[*] Ввожу почту: {email}")
            email_input = page.locator('input[name="email"]')
            await email_input.click()
            await page.keyboard.type(email, delay=uniform(50, 150))

            await asyncio.sleep(uniform(1, 2))

            print("[*] Жму кнопку отправки...")
            await page.locator('button[type="submit"]').click()

            # --- Анализ ---
            print("[*] Анализирую ответ (жду 5 сек)...")
            await asyncio.sleep(5)

            # Делаем скриншот
            screenshot_name = f"result_{email.split('@')[0]}.png"
            await page.screenshot(path=screenshot_name)
            print(f"[i] Скриншот сохранен: {screenshot_name}")

            # Проверка текста
            content = await page.content()
            if "не зарегистрирован" in content or "not registered" in content:
                print(f"[-] Почта {email} НЕ ЗАРЕГИСТРИРОВАНА.")
            else:
                print(f"[+] Почта {email} ВАЛИД (или капча).")

        except Exception as e:
            print(f"[!] Ошибка: {e}")
            await page.screenshot(path="error pic/error_debug.png")
        finally:
            await asyncio.sleep(5)
            await browser.close()


async def main():
    # test_email = "abracadabra_random_12399@gmail.com"
    test_email = "hamidgulov@gmail.com"
    await check_email(test_email, headless=False)


if __name__ == "__main__":
    asyncio.run(main())
