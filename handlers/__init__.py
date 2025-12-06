"""Инициализация обработчиков"""

from .commands import router as commands_router
from .proxy_handlers import router as proxy_router
from .email_handlers import router as email_router
from .checker_handlers import router as checker_router

# Объединяем все роутеры
all_routers = [
    commands_router,
    proxy_router,
    email_router,
    checker_router,
]