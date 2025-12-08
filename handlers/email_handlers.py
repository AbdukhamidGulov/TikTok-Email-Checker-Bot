"""Обработчики для работы с email"""

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from os import makedirs, remove

from config import TEMP_DIR
from states import CheckStates
from keyboards import get_main_keyboard, get_cancel_keyboard
from utils import is_admin
from database import add_emails
import logging

router = Router()
logger = logging.getLogger(__name__)


@router.message(F.text == "✉️ Загрузить почты")
async def handle_upload_emails(message: Message, state: FSMContext):
    """Обработчик кнопки загрузки почт"""
    if not is_admin(message.from_user.id):
        return

    await message.answer(
        "✉️ <b>Загрузка почт</b>\n\n"
        "Отправьте сообщение или текстовый файл (.txt) с почтами.\n"
        "<i>Формат: 1 почта на строку.</i>\n\n"
        "Используйте кнопку ниже для отмены:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(CheckStates.waiting_for_emails)


@router.message(CheckStates.waiting_for_emails, F.text | F.document)
async def handle_emails_input(message: Message, state: FSMContext):
    """Обработчик ввода почт (сохранение в БД)"""
    if not is_admin(message.from_user.id):
        return

    user_id = message.from_user.id

    # Проверка на отмену
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Загрузка почт отменена.", reply_markup=get_main_keyboard())
        return

    items = []

    # 1. Обработка файла
    if message.document and message.document.file_name.endswith(('.txt', '.list')):
        await message.answer("🔄 <b>Обрабатываю файл...</b>")
        file_info = await message.bot.get_file(message.document.file_id)

        makedirs(TEMP_DIR, exist_ok=True)
        file_path = f"{TEMP_DIR}/{user_id}_emails.txt"

        await message.bot.download_file(file_info.file_path, destination=file_path)

        with open(file_path, 'r', encoding='utf-8') as f:
            # Читаем, чистим от пробелов и пустых строк
            items = [line.strip() for line in f if line.strip() and '@' in line]

        remove(file_path)

    # 2. Обработка текста
    elif message.text:
        items = [line.strip() for line in message.text.split('\n') if line.strip() and '@' in line]

    else:
        await message.answer("❌ <b>Ожидается текстовый файл (.txt) ИЛИ список почт в сообщении.</b>")
        return

    if not items:
        await message.answer("❌ <b>Не найдено корректных почт.</b>")
        await state.clear()
        return

    # 3. СОХРАНЕНИЕ В БД
    try:
        await add_emails(user_id, items)
        logger.info(f"Добавлено {len(items)} почт в БД для user {user_id}")
        await message.answer(f"✅ Успешно добавлено <b>{len(items)}</b> почт в базу.", reply_markup=get_main_keyboard())
    except Exception as e:
        logger.error(f"Ошибка БД: {e}")
        await message.answer("❌ Ошибка при сохранении в базу данных.")

    await state.clear()
