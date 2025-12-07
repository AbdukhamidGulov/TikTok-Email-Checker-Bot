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
        # Ожидаем формат login:pass@host:port или host:port
        if "@" in self.proxy_string:
            left, right = self.proxy_string.split("@", 1)
            if ":" in left:
                u, p = left.split(":", 1)
                self.username = u
                self.password = p
            host_port = right
        else:
            host_port = self.proxy_string

        if ":" in host_port:
            h, pr = host_port.rsplit(":", 1)
            self.host = h
            self.port = pr
        else:
            self.host = host_port
            self.port = None

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
