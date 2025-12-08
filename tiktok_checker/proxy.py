from __future__ import annotations
from datetime import datetime, timedelta
from typing import Optional


class ProxyModel:
    """Модель прокси. Ожидает строки вида:
    login:pass@ip:port
    или
    ip:port
    """

    def __init__(self, proxy_string: str):
        self.proxy_string = proxy_string.strip()
        self.is_cooling_down = False
        self.cooldown_until: Optional[datetime] = None
        self.success_count = 0
        self.error_count = 0
        self.is_banned = False
        self.last_error: Optional[str] = None

        # Разобранные поля
        self.username: Optional[str] = None
        self.password: Optional[str] = None
        self.host: Optional[str] = None
        self.port: Optional[str] = None

        self._parse()

    def _parse(self):
        """Разбирает строку формата: ip:port:user:pass или ip:port"""
        parts = self.proxy_string.split(":")

        if len(parts) == 4:
            # Формат: ip:port:user:pass
            self.host = parts[0]
            self.port = parts[1]
            self.username = parts[2]
            self.password = parts[3]
        elif len(parts) == 2:
            # Формат: ip:port
            self.host = parts[0]
            self.port = parts[1]
        else:
            # Неизвестный формат или только IP
            self.host = self.proxy_string
            self.port = None
            self.username = None
            self.password = None

    def cooldown(self, minutes: int):
        self.is_cooling_down = True
        self.cooldown_until = datetime.now() + timedelta(minutes=minutes)

    def ban(self, reason: str):
        self.is_banned = True
        self.cooldown_until = datetime.now() + timedelta(days=1)
        self.last_error = reason

    def is_available(self) -> bool:
        if self.is_banned:
            return False
        if not self.is_cooling_down:
            return True
        if self.cooldown_until and datetime.now() >= self.cooldown_until:
            self.cooldown_until = None
            self.is_cooling_down = False
            return True
        return False

    def to_playwright(self) -> dict:
        """Возвращает dict для playwright context.proxy
        Примеры:
            {"server": "http://1.2.3.4:8000"}
            {"server": "http://1.2.3.4:8000", "username": "u", "password": "p"}
        """
        server = self.host
        if self.port:
            server = f"{server}:{self.port}"
        server = f"http://{server}"

        out = {"server": server}
        if self.username and self.password:
            out["username"] = self.username
            out["password"] = self.password
        return out
