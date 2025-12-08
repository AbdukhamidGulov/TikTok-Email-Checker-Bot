"""Инициализация обработчиков"""

from .commands import router as commands_router
from .proxy_handlers import proxy_router as proxy_router
from .email_handlers import email_router as email_router
from .checker_handlers import checker_router as checker_router
from .status_handlers import status_router

# Объединяем все роутеры
all_routers = [
    commands_router,
    proxy_router,
    email_router,
    checker_router,
    status_router
]