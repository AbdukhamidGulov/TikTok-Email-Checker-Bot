from playwright.async_api import Page


async def launch_browser_context(playwright, proxy_str: str, headless: bool = True):
    """Запуск браузера + контекста + страницы с поддержкой строки прокси ip:port:user:pass"""

    proxy_cfg = parse_proxy_string(proxy_str)

    browser = await playwright.chromium.launch(
        headless=headless,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ],
        timeout=60000,
    )

    context = await browser.new_context(
        proxy=proxy_cfg,
        locale="ru-RU",
        viewport={"width": 1280, "height": 800},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    )

    page = await context.new_page()
    return browser, context, page


async def get_browser_ip(page: Page) -> str:
    """Возвращает строку с IP, который видит внешний сайт.
    Использует api.ipify.org
    """
    try:
        await page.goto("https://api.ipify.org?format=json", wait_until="domcontentloaded", timeout=15000)
        text = await page.text_content("body")
        if not text:
            return "Не получили ответ от ipify"
        return text.strip()
    except Exception as e:
        return f"Ошибка получения IP: {e}"


def parse_proxy_string(proxy_str: str) -> dict:
    """
    Принимает строку формата:
        130.254.41.31:5308:user310321:biw0cv

    Возвращает dict для Playwright:
        {
            "server": "http://130.254.41.31:5308",
            "username": "user310321",
            "password": "biw0cv"
        }
    """

    try:
        ip, port, username, password = proxy_str.strip().split(":")
    except ValueError:
        raise ValueError(
            f"Неверный формат прокси '{proxy_str}'. Ожидаю ip:port:user:pass"
        )

    return {
        "server": f"http://{ip}:{port}",
        "username": username,
        "password": password,
    }
