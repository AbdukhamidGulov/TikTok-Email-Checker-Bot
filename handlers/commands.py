"""Обработчики команд"""

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from keyboards import get_main_keyboard, remove_keyboard
from utils import is_admin, active_checkers

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """Обработчик команды /start"""
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет доступа к этому боту.", reply_markup=remove_keyboard())
        return

    await state.clear()
    user_id = message.from_user.id

    if user_id not in active_checkers:
        active_checkers[user_id] = {
            "proxies": [],
            "emails": [],
            "valid_emails": [],
            "checker_instance": None
        }

    welcome_text = (
        "👋 <b>Добро пожаловать в TikTok Email Checker Bot!</b>\n\n"
        "Используйте кнопки ниже для управления ботом:"
    )

    await message.answer(welcome_text, reply_markup=get_main_keyboard())


@router.message(F.text == "◀️ Назад")
async def handle_back_to_proxy_menu(message: Message, state: FSMContext):
    """Возврат в меню управления прокси"""
    if not is_admin(message.from_user.id):
        return

    await state.clear()
    await message.answer("🔙 Возвращаюсь в меню управления прокси...",
                         reply_markup=get_main_keyboard())
