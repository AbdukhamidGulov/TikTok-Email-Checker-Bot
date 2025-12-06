"""Обработчики для работы с прокси"""

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from os import makedirs, remove

from config import TEMP_DIR
from states import CheckStates
from keyboards import (
    get_main_keyboard, get_cancel_keyboard, get_back_keyboard,
    get_proxy_management_keyboard, get_delete_proxy_keyboard
)
from utils import is_admin, active_checkers, checker_tasks, format_proxy_list
import logging

router = Router()
logger = logging.getLogger(__name__)


@router.message(F.text == "🗑️ Управление прокси")
async def handle_proxy_management(message: Message, state: FSMContext):
    """Меню управления прокси"""
    if not is_admin(message.from_user.id):
        return

    await state.clear()

    user_id = message.from_user.id
    data = active_checkers.get(user_id, {"proxies": []})
    proxies_count = len(data.get("proxies", []))

    await message.answer(
        f"⚙️ <b>Управление прокси</b>\n\n"
        f"Текущее количество: <b>{proxies_count}</b>\n\n"
        f"Выберите действие:",
        reply_markup=get_proxy_management_keyboard()
    )


@router.message(F.text == "👁️ Показать прокси")
async def handle_show_proxies(message: Message):
    """Показать список прокси"""
    if not is_admin(message.from_user.id):
        return

    user_id = message.from_user.id
    data = active_checkers.get(user_id, {"proxies": []})
    proxies = data.get("proxies", [])

    if not proxies:
        await message.answer("❌ Список прокси пуст.", reply_markup=get_proxy_management_keyboard())
        return

    await message.answer(format_proxy_list(proxies), reply_markup=get_proxy_management_keyboard())


@router.message(F.text == "❌ Удалить прокси")
async def handle_delete_proxies_menu(message: Message):
    """Меню удаления прокси"""
    if not is_admin(message.from_user.id):
        return

    user_id = message.from_user.id
    data = active_checkers.get(user_id, {"proxies": []})
    proxies = data.get("proxies", [])

    if not proxies:
        await message.answer("❌ Список прокси пуст.", reply_markup=get_proxy_management_keyboard())
        return

    await message.answer(
        f"🗑️ <b>Удаление прокси</b>\n\n"
        f"Всего прокси: <b>{len(proxies)}</b>\n\n"
        f"Выберите способ удаления:",
        reply_markup=get_delete_proxy_keyboard()
    )


@router.message(F.text == "1️⃣ Удалить по номеру")
async def handle_delete_by_number(message: Message, state: FSMContext):
    """Удалить прокси по номеру"""
    if not is_admin(message.from_user.id):
        return

    user_id = message.from_user.id
    data = active_checkers.get(user_id, {"proxies": []})
    proxies = data.get("proxies", [])

    if not proxies:
        await message.answer("❌ Список прокси пуст.", reply_markup=get_proxy_management_keyboard())
        return

    await message.answer(
        f"{format_proxy_list(proxies)}\n\n"
        f"Введите номер прокси для удаления (1-{len(proxies)}):",
        reply_markup=get_back_keyboard()
    )
    await state.set_state(CheckStates.waiting_for_proxy_number)


@router.message(F.text == "🔢 Удалить несколько")
async def handle_delete_multiple(message: Message, state: FSMContext):
    """Удалить несколько прокси"""
    if not is_admin(message.from_user.id):
        return

    user_id = message.from_user.id
    data = active_checkers.get(user_id, {"proxies": []})
    proxies = data.get("proxies", [])

    if not proxies:
        await message.answer("❌ Список прокси пуст.", reply_markup=get_proxy_management_keyboard())
        return

    await message.answer(
        f"{format_proxy_list(proxies)}\n\n"
        f"Введите номера прокси через запятую (например: 1,3,5) или диапазон (например: 1-3):",
        reply_markup=get_back_keyboard()
    )
    await state.set_state(CheckStates.waiting_for_proxy_numbers)


@router.message(F.text == "🚫 Удалить все")
async def handle_delete_all_proxies(message: Message):
    """Удалить все прокси"""
    if not is_admin(message.from_user.id):
        return

    user_id = message.from_user.id

    # Проверяем, запущена ли проверка
    if user_id in checker_tasks and checker_tasks[user_id] and not checker_tasks[user_id].done():
        await message.answer(
            "⚠️ <b>Нельзя удалить прокси во время проверки!</b>\n"
            "Сначала остановите проверку командой /stop.",
            reply_markup=get_proxy_management_keyboard()
        )
        return

    if user_id not in active_checkers or not active_checkers[user_id]["proxies"]:
        await message.answer("❌ Список прокси и так пуст.", reply_markup=get_proxy_management_keyboard())
        return

    proxies_count = len(active_checkers[user_id]["proxies"])
    active_checkers[user_id]["proxies"] = []

    await message.answer(
        f"✅ <b>Удалено все {proxies_count} прокси.</b>",
        reply_markup=get_proxy_management_keyboard()
    )


@router.message(F.text == "🔄 Обновить список")
async def handle_refresh_list(message: Message):
    """Обновить список прокси"""
    if not is_admin(message.from_user.id):
        return

    user_id = message.from_user.id
    data = active_checkers.get(user_id, {"proxies": []})
    proxies = data.get("proxies", [])

    if not proxies:
        await message.answer("❌ Список прокси пуст.", reply_markup=get_proxy_management_keyboard())
        return

    await message.answer(format_proxy_list(proxies), reply_markup=get_proxy_management_keyboard())


@router.message(CheckStates.waiting_for_proxy_number)
async def handle_proxy_number_input(message: Message, state: FSMContext):
    """Обработка ввода номера прокси для удаления"""
    if not is_admin(message.from_user.id):
        return

    user_id = message.from_user.id
    data = active_checkers.get(user_id, {"proxies": []})
    proxies = data.get("proxies", [])

    if not proxies:
        await message.answer("❌ Список прокси пуст.", reply_markup=get_proxy_management_keyboard())
        await state.clear()
        return

    # Проверка на команду "назад"
    if message.text == "◀️ Назад":
        await state.clear()
        await message.answer("🔙 Возвращаюсь в меню удаления...", reply_markup=get_delete_proxy_keyboard())
        return

    try:
        proxy_num = int(message.text.strip())

        if proxy_num < 1 or proxy_num > len(proxies):
            await message.answer(
                f"❌ Номер должен быть от 1 до {len(proxies)}. Попробуйте снова:",
                reply_markup=get_back_keyboard()
            )
            return

        # Удаляем прокси
        deleted_proxy = proxies.pop(proxy_num - 1)
        active_checkers[user_id]["proxies"] = proxies

        await state.clear()
        await message.answer(
            f"✅ <b>Удален прокси #{proxy_num}:</b>\n"
            f"<code>{deleted_proxy}</code>\n\n"
            f"Осталось прокси: <b>{len(proxies)}</b>",
            reply_markup=get_proxy_management_keyboard()
        )

    except ValueError:
        await message.answer(
            "❌ Пожалуйста, введите правильный номер. Попробуйте снова:",
            reply_markup=get_back_keyboard()
        )


@router.message(CheckStates.waiting_for_proxy_numbers)
async def handle_proxy_numbers_input(message: Message, state: FSMContext):
    """Обработка ввода нескольких номеров прокси для удаления"""
    if not is_admin(message.from_user.id):
        return

    user_id = message.from_user.id
    data = active_checkers.get(user_id, {"proxies": []})
    proxies = data.get("proxies", [])

    if not proxies:
        await message.answer("❌ Список прокси пуст.", reply_markup=get_proxy_management_keyboard())
        await state.clear()
        return

    # Проверка на команду "назад"
    if message.text == "◀️ Назад":
        await state.clear()
        await message.answer("🔙 Возвращаюсь в меню удаления...", reply_markup=get_delete_proxy_keyboard())
        return

    try:
        input_text = message.text.strip()
        indices_to_delete = set()

        # Обработка разных форматов ввода
        if ',' in input_text:
            # Формат: 1,3,5
            parts = input_text.split(',')
            for part in parts:
                part = part.strip()
                if '-' in part:
                    # Поддиапазон внутри запятых: 1-3,5
                    range_parts = part.split('-')
                    if len(range_parts) == 2:
                        start = int(range_parts[0].strip())
                        end = int(range_parts[1].strip())
                        for i in range(start, end + 1):
                            indices_to_delete.add(i)
                else:
                    indices_to_delete.add(int(part))

        elif '-' in input_text:
            # Формат: 1-3
            range_parts = input_text.split('-')
            if len(range_parts) == 2:
                start = int(range_parts[0].strip())
                end = int(range_parts[1].strip())
                for i in range(start, end + 1):
                    indices_to_delete.add(i)
            else:
                raise ValueError("Неправильный формат диапазона")

        else:
            # Просто один номер
            indices_to_delete.add(int(input_text))

        # Проверяем номера
        valid_indices = []
        deleted_proxies = []

        for idx in sorted(indices_to_delete, reverse=True):  # Удаляем с конца
            if 1 <= idx <= len(proxies):
                valid_indices.append(idx)
                deleted_proxies.append(proxies.pop(idx - 1))

        if not valid_indices:
            await message.answer(
                "❌ Нет корректных номеров для удаления. Попробуйте снова:",
                reply_markup=get_back_keyboard()
            )
            return

        # Сохраняем обновленный список
        active_checkers[user_id]["proxies"] = proxies

        await state.clear()

        # Формируем сообщение об удалении
        if len(deleted_proxies) == 1:
            proxy_info = f"Удален прокси #{valid_indices[0]}: <code>{deleted_proxies[0]}</code>"
        else:
            proxy_info = f"Удалено прокси: {', '.join(f'#{i}' for i in sorted(valid_indices))}"

        await message.answer(
            f"✅ <b>Успешно удалено {len(deleted_proxies)} прокси:</b>\n"
            f"{proxy_info}\n\n"
            f"Осталось прокси: <b>{len(proxies)}</b>",
            reply_markup=get_proxy_management_keyboard()
        )

    except (ValueError, Exception) as e:
        await message.answer(
            f"❌ Ошибка в формате ввода.\n"
            f"Используйте: '1,3,5' или '1-3' или просто '2'\n"
            f"Попробуйте снова:",
            reply_markup=get_back_keyboard()
        )


@router.message(F.text == "📤 Загрузить прокси")
async def handle_upload_proxies(message: Message, state: FSMContext):
    """Обработчик кнопки загрузки прокси"""
    if not is_admin(message.from_user.id):
        return

    user_id = message.from_user.id
    if user_id not in active_checkers:
        active_checkers[user_id] = {"proxies": [], "emails": [], "valid_emails": [], "checker_instance": None}

    await message.answer(
        "📤 <b>Загрузка прокси</b>\n\n"
        "Отправьте сообщение или текстовый файл (.txt) с прокси.\n"
        "<i>Формат: 1 прокси на строку (user:pass@ip:port или ip:port).</i>\n\n"
        "Используйте кнопку ниже для отмены:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(CheckStates.waiting_for_proxies)


@router.message(CheckStates.waiting_for_proxies, F.text | F.document)
async def handle_proxies_input(message: Message, state: FSMContext):
    """Обработчик ввода прокси (FSM состояние)"""
    if not is_admin(message.from_user.id):
        return

    user_id = message.from_user.id

    # Проверка на отмену
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Загрузка прокси отменена.", reply_markup=get_main_keyboard())
        return

    items = []

    if message.document and message.document.file_name.endswith(('.txt', '.list')):
        await message.answer("🔄 <b>Обрабатываю файл...</b>")
        file_info = await message.bot.get_file(message.document.file_id)

        makedirs(TEMP_DIR, exist_ok=True)
        file_path = f"{TEMP_DIR}/{user_id}_proxies.txt"

        await message.bot.download_file(file_info.file_path, destination=file_path)

        with open(file_path, 'r', encoding='utf-8') as f:
            items = [line.strip() for line in f if line.strip()]

        remove(file_path)

    elif message.text:
        items = [line.strip() for line in message.text.split('\n') if line.strip()]

    else:
        await message.answer("❌ <b>Ожидается текстовый файл (.txt) ИЛИ список прокси в сообщении.</b>")
        return

    if not items:
        await message.answer("❌ <b>Введенные данные пусты.</b>")
        await state.clear()
        return

    if user_id not in active_checkers:
        active_checkers[user_id] = {"proxies": [], "emails": [], "valid_emails": [], "checker_instance": None}

    active_checkers[user_id]["proxies"] = items
    logger.info(f"Сохранено {len(items)} прокси для user {user_id}")

    await message.answer(f"✅ Успешно загружено <b>{len(items)}</b> прокси.", reply_markup=get_main_keyboard())
    await state.clear()
