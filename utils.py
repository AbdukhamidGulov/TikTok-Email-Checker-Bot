"""Утилиты и вспомогательные функции"""

from logging import getLogger
from config import ADMIN_IDS

logger = getLogger(__name__)

# Глобальные хранилища данных
active_checkers = {}
checker_tasks = {}


def is_admin(user_id: int) -> bool:
    """Проверка является ли пользователь администратором"""
    return user_id in ADMIN_IDS


def format_proxy_list(proxies: list) -> str:
    """Форматирует список прокси для отображения"""
    if not proxies:
        return "❌ Список прокси пуст."

    result = []
    for i, proxy in enumerate(proxies, 1):
        if '@' in proxy:
            parts = proxy.split('@')
            server = parts[-1]
            result.append(f"{i}. {server}")
        else:
            result.append(f"{i}. {proxy}")

    return "📋 <b>Список прокси:</b>\n" + "\n".join(result)


async def send_log_async(bot, user_id: int, message_text: str):
    """Отправка логов через бота"""
    try:
        if bot:
            await bot.send_message(user_id, message_text)
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения: {e}")
