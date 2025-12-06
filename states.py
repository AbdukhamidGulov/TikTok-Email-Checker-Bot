"""Состояния FSM"""

from aiogram.fsm.state import State, StatesGroup


class CheckStates(StatesGroup):
    waiting_for_proxies = State()
    waiting_for_emails = State()
    waiting_for_proxy_number = State()
    waiting_for_proxy_numbers = State()
