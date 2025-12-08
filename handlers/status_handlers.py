"""Обработчики для работы со статусом и выгрузкой данных."""

from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile, CallbackQuery
from os import makedirs, remove
from asyncio import sleep
from datetime import datetime

from keyboards import get_main_keyboard, get_cancel_keyboard
from utils import is_admin, checker_tasks, format_proxy_list
from config import TEMP_DIR
from database import get_stats, get_active_proxies, get_emails_by_status
import logging

status_router = Router()
logger = logging.getLogger(__name__)


# --- Вспомогательные функции ---

def get_status_keyboard():
    """Инлайн клавиатура для запроса детальных данных"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔗 Показать прокси", callback_data="show_proxies"),
                InlineKeyboardButton(text="📊 Детализация по почтам", callback_data="show_email_details")
            ],
            [
                InlineKeyboardButton(text="📥 Выгрузить Валидные (TXT)", callback_data="dump_valid_emails"),
                InlineKeyboardButton(text="📥 Выгрузить Невалидные (TXT)", callback_data="dump_invalid_emails")
            ]
        ]
    )


async def send_email_dump_file(message: Message, user_id: int, status: str, title: str):
    """Создает и отправляет текстовый файл с почтами"""
    emails = await get_emails_by_status(user_id, status)

    if not emails:
        await message.answer(f"❌ В базе нет почт со статусом '{status}'.")
        return

    # Создание временного файла
    makedirs(TEMP_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"{title}_{timestamp}.txt"
    file_path = f"{TEMP_DIR}/{file_name}"

    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(emails))

        # Отправка файла
        file = FSInputFile(file_path)
        await message.answer_document(
            file,
            caption=f"✅ <b>Ваш файл готов:</b> {title} ({len(emails)} шт.)",
            reply_markup=get_main_keyboard()
        )
    except Exception as e:
        logger.error(f"Ошибка при создании/отправке файла: {e}")
        await message.answer("❌ Произошла ошибка при подготовке файла.")
    finally:
        # Удаление временного файла
        try:
            remove(file_path)
        except:
            pass


# --- Основной обработчик статуса (Замена старого кода) ---

@status_router.message(F.text == "📊 Статус")
async def handle_status(message: Message):
    """Обработчик кнопки статуса, получает данные из БД и отображает кнопки деталей"""
    user_id = message.from_user.id
    if not is_admin(user_id):
        return

    # БД: Получаем статистику по почтам (total, valid, pending, invalid)
    stats = await get_stats(user_id)
    if stats is None:
        total, valid, pending, invalid = 0, 0, 0, 0
    else:
        total, valid, pending, invalid = stats

    # БД: Получаем количество активных прокси
    proxies = await get_active_proxies(user_id)
    proxies_count = len(proxies)

    is_running = user_id in checker_tasks and checker_tasks[user_id] and not checker_tasks[user_id].done()
    status_icon = "🟢" if is_running else "🔴"

    # Расчет проверенных (для удобства)
    checked_count = valid + invalid

    status_text = (
        f"📊 <b>ТЕКУЩИЙ СТАТУС</b>\n\n"
        f"• 🔗 Прокси в базе: <b>{proxies_count}</b>\n"
        f"• 📧 Всего почт в базе: <b>{total}</b>\n"
        f"• ⏳ В ожидании: <b>{pending}</b>\n"
        f"• ✅ Проверено: <b>{checked_count}</b> (Валид: <b>{valid}</b> / Невалид: <b>{invalid}</b>)\n"
        f"• ⚙️ Проверка запущена: {status_icon} <b>{'Да' if is_running else 'Нет'}</b>"
    )

    await message.answer(status_text, reply_markup=get_status_keyboard())


# --- Обработчики Inline кнопок ---

@status_router.callback_query(F.data == "show_proxies")
async def callback_show_proxies(callback: CallbackQuery):
    user_id = callback.from_user.id
    proxies = await get_active_proxies(user_id)

    if not proxies:
        text = "❌ Список прокси пуст."
    else:
        text = format_proxy_list(proxies)

    await callback.message.answer(text, reply_markup=get_status_keyboard())
    await callback.answer()  # Скрыть уведомление о нажатии


@status_router.callback_query(F.data == "show_email_details")
async def callback_show_email_details(callback: CallbackQuery):
    user_id = callback.from_user.id
    stats = await get_stats(user_id)

    if stats is None:
        text = "❌ Нет данных о почтах."
    else:
        total, valid, pending, invalid = stats
        text = (
            f"📧 <b>ДЕТАЛИЗАЦИЯ ПОЧТ</b>\n"
            f"• Всего в базе: <b>{total}</b>\n"
            f"• В ожидании: <b>{pending}</b>\n"
            f"• Валид: <b>{valid}</b>\n"
            f"• Невалид: <b>{invalid}</b>"
        )

    await callback.message.answer(text, reply_markup=get_status_keyboard())
    await callback.answer()


@status_router.callback_query(F.data == "dump_valid_emails")
async def callback_dump_valid_emails(callback: CallbackQuery):
    await callback.message.answer("⏳ Готовлю файл с валидными почтами...")
    await send_email_dump_file(callback.message, callback.from_user.id, "valid", "valid_emails")
    await callback.answer()


@status_router.callback_query(F.data == "dump_invalid_emails")
async def callback_dump_invalid_emails(callback: CallbackQuery):
    await callback.message.answer("⏳ Готовлю файл с невалидными почтами...")
    await send_email_dump_file(callback.message, callback.from_user.id, "invalid", "invalid_emails")
    await callback.answer()
