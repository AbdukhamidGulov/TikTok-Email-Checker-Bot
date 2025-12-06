"""Клавиатуры бота"""

from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove


def get_main_keyboard():
    """Главное меню"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📤 Загрузить прокси"), KeyboardButton(text="✉️ Загрузить почты")],
            [KeyboardButton(text="🚀 Начать проверку"), KeyboardButton(text="🛑 Остановить")],
            [KeyboardButton(text="📊 Статус"), KeyboardButton(text="📥 Выгрузить валидные")],
            [KeyboardButton(text="🗑️ Управление прокси")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )


def get_proxy_management_keyboard():
    """Меню управления прокси"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👁️ Показать прокси"), KeyboardButton(text="❌ Удалить прокси")],
            [KeyboardButton(text="🔄 Обновить список"), KeyboardButton(text="◀️ Назад")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )


def get_delete_proxy_keyboard():
    """Клавиатура для удаления прокси"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="1️⃣ Удалить по номеру"), KeyboardButton(text="🔢 Удалить несколько")],
            [KeyboardButton(text="🚫 Удалить все"), KeyboardButton(text="◀️ Назад")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )


def get_cancel_keyboard():
    """Клавиатура для отмены"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="❌ Отмена")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )


def get_back_keyboard():
    """Клавиатура для возврата"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="◀️ Назад")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )


def remove_keyboard():
    """Скрыть клавиатуру"""
    return ReplyKeyboardRemove()
