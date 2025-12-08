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
from utils import is_admin, checker_tasks, format_proxy_list
from database import add_proxies, get_active_proxies, clear_data
from logging import getLogger

router = Router()
logger = getLogger(__name__)


@router.message(F.text == "🗑️ Управление прокси")
async def handle_proxy_management(message: Message, state: FSMContext):
    """Меню управления прокси"""
    if not is_admin(message.from_user.id):
        return

    await state.clear()
    user_id = message.from_user.id

    # БД: Получаем список
    proxies = await get_active_proxies(user_id)
    proxies_count = len(proxies)

    await message.answer(
        f"⚙️ <b>Управление прокси</b>\n\n"
        f"В базе загружено: <b>{proxies_count}</b>\n\n"
        f"Выберите действие:",
        reply_markup=get_proxy_management_keyboard()
    )


@router.message(F.text == "👁️ Показать прокси")
async def handle_show_proxies(message: Message):
    """Показать список прокси"""
    if not is_admin(message.from_user.id):
        return

    user_id = message.from_user.id
    # БД: Получаем список
    proxies = await get_active_proxies(user_id)

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
    # БД: Получаем список для проверки кол-ва
    proxies = await get_active_proxies(user_id)

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
    proxies = await get_active_proxies(user_id)

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
    proxies = await get_active_proxies(user_id)

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

    if user_id in checker_tasks and checker_tasks[user_id] and not checker_tasks[user_id].done():
        await message.answer(
            "⚠️ <b>Нельзя удалить прокси во время проверки!</b>",
            reply_markup=get_proxy_management_keyboard()
        )
        return

    # БД: Очистка таблицы proxies
    await clear_data(user_id, "proxies")

    await message.answer(
        f"✅ <b>База прокси очищена.</b>",
        reply_markup=get_proxy_management_keyboard()
    )


@router.message(F.text == "🔄 Обновить список")
async def handle_refresh_list(message: Message):
    """Обновить список прокси"""
    if not is_admin(message.from_user.id):
        return
    # Просто переадресуем на показ
    await handle_show_proxies(message)


@router.message(CheckStates.waiting_for_proxy_number)
async def handle_proxy_number_input(message: Message, state: FSMContext):
    """Удаление одного прокси (обновление БД)"""
    if not is_admin(message.from_user.id):
        return

    user_id = message.from_user.id
    if message.text == "◀️ Назад":
        await state.clear()
        await message.answer("🔙 Назад...", reply_markup=get_delete_proxy_keyboard())
        return

    # Получаем актуальный список из БД
    proxies = await get_active_proxies(user_id)

    try:
        proxy_num = int(message.text.strip())
        if proxy_num < 1 or proxy_num > len(proxies):
            await message.answer(f"❌ Номер должен быть от 1 до {len(proxies)}.")
            return

        deleted_proxy = proxies.pop(proxy_num - 1)

        # БД: Перезаписываем список (Удаляем всё -> Записываем новый список)
        await clear_data(user_id, "proxies")
        if proxies:
            await add_proxies(user_id, proxies)

        await state.clear()
        await message.answer(
            f"✅ <b>Удален:</b> <code>{deleted_proxy}</code>\n"
            f"Осталось: <b>{len(proxies)}</b>",
            reply_markup=get_proxy_management_keyboard()
        )

    except ValueError:
        await message.answer("❌ Введите число.")


@router.message(CheckStates.waiting_for_proxy_numbers)
async def handle_proxy_numbers_input(message: Message, state: FSMContext):
    """Удаление нескольких прокси (обновление БД)"""
    if not is_admin(message.from_user.id):
        return

    user_id = message.from_user.id
    if message.text == "◀️ Назад":
        await state.clear()
        await message.answer("🔙 Назад...", reply_markup=get_delete_proxy_keyboard())
        return

    proxies = await get_active_proxies(user_id)
    if not proxies:
        await state.clear()
        return

    try:
        input_text = message.text.strip()
        indices_to_delete = set()

        # Парсинг ввода (1,2,5 или 1-5)
        if ',' in input_text:
            parts = input_text.split(',')
            for part in parts:
                if '-' in part:
                    s, e = map(int, part.split('-'))
                    indices_to_delete.update(range(s, e + 1))
                else:
                    indices_to_delete.add(int(part))
        elif '-' in input_text:
            s, e = map(int, input_text.split('-'))
            indices_to_delete.update(range(s, e + 1))
        else:
            indices_to_delete.add(int(input_text))

        # Удаление
        new_proxies = []
        deleted_count = 0

        # Индексы ввода 1-based, конвертируем в 0-based
        indices_to_delete = {i - 1 for i in indices_to_delete}

        for idx, p in enumerate(proxies):
            if idx in indices_to_delete:
                deleted_count += 1
            else:
                new_proxies.append(p)

        if deleted_count == 0:
            await message.answer("❌ Ничего не удалено (неверные номера).")
            return

        # БД: Перезапись
        await clear_data(user_id, "proxies")
        if new_proxies:
            await add_proxies(user_id, new_proxies)

        await state.clear()
        await message.answer(
            f"✅ <b>Удалено {deleted_count} прокси.</b>\n"
            f"Осталось: <b>{len(new_proxies)}</b>",
            reply_markup=get_proxy_management_keyboard()
        )

    except Exception:
        await message.answer("❌ Ошибка формата. Пример: 1,3,5 или 1-10")


@router.message(F.text == "📤 Загрузить прокси")
async def handle_upload_proxies(message: Message, state: FSMContext):
    """Обработчик кнопки загрузки прокси"""
    if not is_admin(message.from_user.id):
        return

    await message.answer(
        "📤 <b>Загрузка прокси</b>\n\n"
        "Отправьте .txt файл или список сообщением.\n"
        "Формат: <code>ip:port:user:pass</code>",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(CheckStates.waiting_for_proxies)


@router.message(CheckStates.waiting_for_proxies, F.text | F.document)
async def handle_proxies_input(message: Message, state: FSMContext):
    """Ввод прокси -> Сохранение в БД"""
    if not is_admin(message.from_user.id):
        return

    user_id = message.from_user.id
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=get_main_keyboard())
        return

    items = []
    if message.document:
        # Логика скачивания файла (как и раньше)
        file_info = await message.bot.get_file(message.document.file_id)
        makedirs(TEMP_DIR, exist_ok=True)
        file_path = f"{TEMP_DIR}/{user_id}_proxies.txt"
        await message.bot.download_file(file_info.file_path, destination=file_path)
        with open(file_path, 'r', encoding='utf-8') as f:
            items = [line.strip() for line in f if line.strip()]
        remove(file_path)
    elif message.text:
        items = [line.strip() for line in message.text.split('\n') if line.strip()]

    if not items:
        await message.answer("❌ Пусто.")
        return

    # БД: Добавляем прокси
    await add_proxies(user_id, items)

    await message.answer(f"✅ Добавлено <b>{len(items)}</b> прокси в базу.", reply_markup=get_main_keyboard())
    await state.clear()
