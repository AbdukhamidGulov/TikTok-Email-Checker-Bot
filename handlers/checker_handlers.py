"""Обработчики для проверки и управления"""

from asyncio import create_task, CancelledError
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, FSInputFile
from datetime import datetime
from os import makedirs, remove

from config import TEMP_DIR
from database import get_active_proxies, get_pending_emails
from tiktok_checker.checker import TikTokChecker
from keyboards import get_main_keyboard, get_proxy_management_keyboard
from utils import is_admin, active_checkers, checker_tasks, send_log_async
from states import CheckStates
import logging

checker_router = Router()
logger = logging.getLogger(__name__)


async def run_checker_task(bot, message: Message, checker: TikTokChecker, emails: list, user_id: int):
    """Фоновая задача для запуска проверки"""
    try:
        await bot.send_message(
            user_id,
            f"📊 <b>Запускаю проверку {len(emails)} почт...</b>\n"
            f"Используется {min(len(checker.proxy_pool), 10)} потоков"
        )

        valid_emails = await checker.run_checker(emails)

        if user_id in active_checkers:
            active_checkers[user_id]["valid_emails"].extend(valid_emails)

        await bot.send_message(
            user_id,
            f"🏁 <b>Проверка завершена!</b>\n"
            f"Всего проверено: {checker.checked_count}\n"
            f"Найдено валидных: <b>{len(valid_emails)}</b>",
            reply_markup=get_main_keyboard(is_running=False)
        )

    except CancelledError:
        logger.info(f"Задача проверки для user {user_id} отменена")
        if user_id in active_checkers and active_checkers[user_id]["checker_instance"]:
            checker = active_checkers[user_id]["checker_instance"]
            checker.is_running = False
            await bot.send_message(user_id, "🛑 <b>Проверка принудительно остановлена.</b>",
                                   reply_markup=get_main_keyboard(is_running=False))
    except Exception as e:
        logger.error(f"Ошибка в checker task: {e}", exc_info=True)
        await bot.send_message(
            user_id,
            f"❌ <b>Ошибка в процессе проверки:</b>\n{str(e)[:200]}", reply_markup=get_main_keyboard(is_running=False)
        )
    finally:
        if user_id in active_checkers:
            active_checkers[user_id]["checker_instance"] = None
        if user_id in checker_tasks:
            checker_tasks[user_id] = None


@checker_router.message(F.text == "🚀 Начать проверку")
async def handle_start_check(message: Message, bot):
    """Обработчик кнопки начала проверки"""
    user_id = message.from_user.id
    if not is_admin(user_id):
        return

    # Проверка: не запущена ли уже задача
    if user_id in checker_tasks and checker_tasks[user_id] is not None and not checker_tasks[user_id].done():
        await message.answer("⚠️ <b>Другая проверка уже запущена!</b> Используйте кнопку '<code>Остановить</code>'.",
                             reply_markup=get_main_keyboard(is_running=True))
        return

    # 1. ЗАГРУЖАЕМ ДАННЫЕ ИЗ БАЗЫ ДАННЫХ
    proxies = await get_active_proxies(user_id)
    emails = await get_pending_emails(user_id)

    # Проверки на наличие данных
    if not proxies:
        await message.answer("❌ <b>Сначала загрузите прокси!</b>", reply_markup=get_main_keyboard(is_running=False))
        return
    if not emails:
        await message.answer("❌ <b>Нет почт для проверки!</b>\n(Либо список пуст, либо все уже проверены)", reply_markup=get_main_keyboard(is_running=False))
        return

    emails_count = len(emails)
    proxies_count = len(proxies)

    await message.answer(
        f"🚀 <b>Запускаю проверку...</b>\n\n"
        f"📧 Осталось проверить: <b>{emails_count}</b>\n"
        f"🔗 Активных прокси: <b>{proxies_count}</b>\n"
        f"⚡ Потоков: <b>{min(proxies_count, 10)}</b>",
        reply_markup=get_main_keyboard(is_running=True)
    )

    try:
        # Создаем чекер, передавая данные из БД
        checker = TikTokChecker(
            proxies=proxies,
            log_callback=lambda uid, msg: send_log_async(bot, uid, msg),
            user_id=user_id
        )

        # Сохраняем ссылку на чекер для остановки
        if user_id not in active_checkers:
            active_checkers[user_id] = {}
        active_checkers[user_id]["checker_instance"] = checker

        # Запускаем задачу
        task = create_task(run_checker_task(bot, message, checker, emails, user_id))
        checker_tasks[user_id] = task

    except Exception as ex:
        logger.error(f"Ошибка запуска: {ex}")
        await message.answer(f"❌ <b>Ошибка при запуске:</b> {str(ex)}", reply_markup=get_main_keyboard(is_running=False))
        if user_id in active_checkers:
            active_checkers[user_id]["checker_instance"] = None


@checker_router.message(F.text == "🛑 Остановить")
async def handle_stop(message: Message):
    """Обработчик кнопки остановки проверки"""
    user_id = message.from_user.id
    if not is_admin(user_id):
        return

    if user_id in checker_tasks and checker_tasks[user_id] and not checker_tasks[user_id].done():
        checker_tasks[user_id].cancel()
        await message.answer("🛑 <b>Останавливаю проверку...</b>", reply_markup=get_main_keyboard())

        try:
            await checker_tasks[user_id]
        except CancelledError:
            pass

        await message.answer("✅ <b>Проверка остановлена.</b>", reply_markup=get_main_keyboard())
    else:
        await message.answer("Проверка не была запущена.", reply_markup=get_main_keyboard())


@checker_router.message(F.text == "📥 Выгрузить валидные")
async def handle_get_valid(message: Message):
    """Обработчик кнопки выгрузки валидных почт"""
    user_id = message.from_user.id
    if not is_admin(user_id):
        return

    data = active_checkers.get(user_id, {"valid_emails": []})
    valid_emails = data.get("valid_emails", [])

    if not valid_emails:
        await message.answer("<b>Нет найденных валидных почт.</b>", reply_markup=get_main_keyboard())
        return

    makedirs(TEMP_DIR, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    file_name = f"valid_emails_{user_id}_{timestamp}.txt"
    file_path = f"{TEMP_DIR}/{file_name}"

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(valid_emails))

    document = FSInputFile(file_path)
    await message.answer_document(document)
    await message.answer(f"📤 <b>Отправлено {len(valid_emails)} валидных почт.</b>", reply_markup=get_main_keyboard())

    remove(file_path)


@checker_router.message(F.text == "❌ Отмена")
async def handle_cancel(message: Message, state: FSMContext):
    """Обработчик кнопки отмены"""
    if not is_admin(message.from_user.id):
        return

    current_state = await state.get_state()

    if current_state == CheckStates.waiting_for_proxies.state:
        await state.clear()
        await message.answer("❌ Загрузка прокси отменена.", reply_markup=get_main_keyboard())
    elif current_state == CheckStates.waiting_for_emails.state:
        await state.clear()
        await message.answer("❌ Загрузка почт отменена.", reply_markup=get_main_keyboard())
    elif current_state == CheckStates.waiting_for_proxy_number.state:
        await state.clear()
        await message.answer("❌ Удаление прокси отменено.", reply_markup=get_proxy_management_keyboard())
    elif current_state == CheckStates.waiting_for_proxy_numbers.state:
        await state.clear()
        await message.answer("❌ Удаление прокси отменено.", reply_markup=get_proxy_management_keyboard())
    else:
        await message.answer("Нечего отменять.", reply_markup=get_main_keyboard())
