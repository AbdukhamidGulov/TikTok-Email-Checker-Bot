"""Обработчики для работы с email"""

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from os import makedirs, remove

from config import TEMP_DIR
from states import CheckStates
from keyboards import get_main_keyboard, get_cancel_keyboard
from utils import is_admin, active_checkers
import logging

router = Router()
logger = logging.getLogger(__name__)


@router.message(F.text == "✉️ Загрузить почты")
async def handle_upload_emails(message: Message, state: FSMContext):
    """Обработчик кнопки загрузки почт"""
    if not is_admin(message.from_user.id):
        return

    user_id = message.from_user.id
    if user_id not in active_checkers:
        active_checkers[user_id] = {"proxies": [], "emails": [], "valid_emails": [], "checker_instance": None}

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
    """Обработчик ввода почт (FSM состояние)"""
    if not is_admin(message.from_user.id):
        return

    user_id = message.from_user.id

    # Проверка на отмену
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Загрузка почт отменена.", reply_markup=get_main_keyboard())
        return

    items = []

    if message.document and message.document.file_name.endswith(('.txt', '.list')):
        await message.answer("🔄 <b>Обрабатываю файл...</b>")
        file_info = await message.bot.get_file(message.document.file_id)

        makedirs(TEMP_DIR, exist_ok=True)
        file_path = f"{TEMP_DIR}/{user_id}_emails.txt"

        await message.bot.download_file(file_info.file_path, destination=file_path)

        with open(file_path, 'r', encoding='utf-8') as f:
            items = [line.strip() for line in f if line.strip()]

        remove(file_path)

    elif message.text:
        items = [line.strip() for line in message.text.split('\n') if line.strip()]

    else:
        await message.answer("❌ <b>Ожидается текстовый файл (.txt) ИЛИ список почт в сообщении.</b>")
        return

    if not items:
        await message.answer("❌ <b>Введенные данные пусты.</b>")
        await state.clear()
        return

    if user_id not in active_checkers:
        active_checkers[user_id] = {"proxies": [], "emails": [], "valid_emails": [], "checker_instance": None}

    active_checkers[user_id]["emails"] = items
    logger.info(f"Сохранено {len(items)} почт для user {user_id}")

    await message.answer(f"✅ Успешно загружено <b>{len(items)}</b> почт.", reply_markup=get_main_keyboard())
    await state.clear()
