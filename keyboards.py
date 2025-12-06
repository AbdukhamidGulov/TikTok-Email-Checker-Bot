from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove

# Клавиатура для главного меню
def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📤 Загрузить прокси"), KeyboardButton(text="✉️ Загрузить почты")],
            [KeyboardButton(text="🚀 Начать проверку"), KeyboardButton(text="🛑 Остановить")],
            [KeyboardButton(text="📊 Статус"), KeyboardButton(text="📥 Выгрузить валидные")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )

# Клавиатура для отмены загрузки
def get_cancel_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="❌ Отмена")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )

# Пустая клавиатура (скрыть кнопки)
def remove_keyboard():
    return ReplyKeyboardRemove()
