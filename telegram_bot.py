from asyncio import create_task, run, sleep, CancelledError
from os import makedirs, remove
from logging import basicConfig, getLogger, INFO, ERROR
from datetime import datetime

from aiogram import Bot, Dispatcher, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import FSInputFile, Message
from aiogram.fsm.storage.memory import MemoryStorage

from tiktok_worker import TikTokChecker
from keyboards import (
    get_main_keyboard, get_cancel_keyboard, remove_keyboard,
    get_proxy_management_keyboard, get_delete_proxy_keyboard, get_back_keyboard
)

basicConfig(level=INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = getLogger(__name__)

BOT_TOKEN = "7829490363:AAE0uC5td8ghE-7pbLgsTpZLptEJ-GzDCP0"
ADMIN_IDS = [6755517434, 8058104515]
TEMP_DIR = "temp_files"

storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher(storage=storage)

active_checkers = {}
checker_tasks = {}


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


class CheckStates(StatesGroup):
    waiting_for_proxies = State()
    waiting_for_emails = State()
    waiting_for_proxy_number = State()
    waiting_for_proxy_numbers = State()


async def send_log_async(user_id: int, message_text: str):
    try:
        if bot:
            await bot.send_message(user_id, message_text)
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения: {e}")


def format_proxy_list(proxies: list) -> str:
    """Форматирует список прокси для отображения"""
    if not proxies:
        return "❌ Список прокси пуст."

    result = []
    for i, proxy in enumerate(proxies, 1):
        # Скрываем логин/пароль для безопасности
        if '@' in proxy:
            parts = proxy.split('@')
            server = parts[-1]
            result.append(f"{i}. {server}")
        else:
            result.append(f"{i}. {proxy}")

    return "📋 <b>Список прокси:</b>\n" + "\n".join(result)


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
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


@dp.message(F.text == "🗑️ Управление прокси")
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


@dp.message(F.text == "👁️ Показать прокси")
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


@dp.message(F.text == "❌ Удалить прокси")
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


@dp.message(F.text == "1️⃣ Удалить по номеру")
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


@dp.message(F.text == "🔢 Удалить несколько")
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


@dp.message(F.text == "🚫 Удалить все")
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


@dp.message(F.text == "🔄 Обновить список")
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


@dp.message(CheckStates.waiting_for_proxy_number)
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


@dp.message(CheckStates.waiting_for_proxy_numbers)
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


@dp.message(F.text == "◀️ Назад")
async def handle_back_to_proxy_menu(message: Message, state: FSMContext):
    """Возврат в меню управления прокси"""
    if not is_admin(message.from_user.id):
        return

    await state.clear()
    await message.answer("🔙 Возвращаюсь в меню управления прокси...",
                         reply_markup=get_proxy_management_keyboard())


@dp.message(F.text == "📤 Загрузить прокси")
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


@dp.message(F.text == "✉️ Загрузить почты")
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
        "Используйте кнопку ниже для отмена:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(CheckStates.waiting_for_emails)


@dp.message(CheckStates.waiting_for_proxies, F.text | F.document)
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


@dp.message(CheckStates.waiting_for_emails, F.text | F.document)
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


@dp.message(F.text == "🚀 Начать проверку")
async def handle_start_check(message: Message):
    """Обработчик кнопки начала проверки"""
    user_id = message.from_user.id
    if not is_admin(user_id):
        return

    if user_id in checker_tasks and not checker_tasks[user_id].done():
        await message.answer("⚠️ <b>Проверка уже запущена!</b> Используйте кнопку 'Остановить'.",
                             reply_markup=get_main_keyboard())
        return

    data = active_checkers.get(user_id, {"proxies": [], "emails": [], "valid_emails": [], "checker_instance": None})

    if not data["proxies"]:
        await message.answer("❌ <b>Сначала загрузите прокси!</b>", reply_markup=get_main_keyboard())
        return
    if not data["emails"]:
        await message.answer("❌ <b>Сначала загрузите почты!</b>", reply_markup=get_main_keyboard())
        return

    emails_count = len(data["emails"])
    proxies_count = len(data["proxies"])

    await message.answer(
        f"🚀 <b>Запускаю проверку...</b>\n\n"
        f"📧 Почты: <b>{emails_count}</b>\n"
        f"🔗 Прокси: <b>{proxies_count}</b>\n"
        f"⚡ Потоков: <b>{min(proxies_count, 10)}</b>",
        reply_markup=get_main_keyboard()
    )

    try:
        checker = TikTokChecker(
            proxies=data["proxies"],
            log_callback=send_log_async,
            user_id=user_id
        )

        active_checkers[user_id]["checker_instance"] = checker

        task = create_task(run_checker_task(message, checker, data["emails"], user_id))
        checker_tasks[user_id] = task

    except Exception as ex:
        await message.answer(f"❌ <b>Ошибка при запуске:</b> {str(ex)}", reply_markup=get_main_keyboard())
        active_checkers[user_id]["checker_instance"] = None


@dp.message(F.text == "🛑 Остановить")
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


@dp.message(F.text == "📥 Выгрузить валидные")
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


@dp.message(F.text == "📊 Статус")
async def handle_status(message: Message):
    """Обработчик кнопки статуса"""
    user_id = message.from_user.id
    if not is_admin(user_id):
        return

    data = active_checkers.get(user_id, {"proxies": [], "emails": [], "valid_emails": []})

    proxies_count = len(data.get("proxies", []))
    emails_count = len(data.get("emails", []))
    valid_count = len(data.get("valid_emails", []))

    is_running = user_id in checker_tasks and checker_tasks[user_id] and not checker_tasks[user_id].done()

    status_icon = "🟢" if is_running else "🔴"

    status_text = (
        f"📊 <b>ТЕКУЩИЙ СТАТУС</b>\n\n"
        f"• 🔗 Прокси загружено: <b>{proxies_count}</b>\n"
        f"• 📧 Почтов загружено: <b>{emails_count}</b>\n"
        f"• ✅ Валидных найдено: <b>{valid_count}</b>\n"
        f"• ⚙️ Проверка запущена: {status_icon} <b>{'Да' if is_running else 'Нет'}</b>"
    )

    await message.answer(status_text, reply_markup=get_main_keyboard())


@dp.message(F.text == "❌ Отмена")
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


async def run_checker_task(message: Message, checker: TikTokChecker, emails: list, user_id: int):
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
            f"Найдено валидных: <b>{len(valid_emails)}</b>"
        )

    except CancelledError:
        logger.info(f"Задача проверки для user {user_id} отменена")
        if user_id in active_checkers and active_checkers[user_id]["checker_instance"]:
            checker = active_checkers[user_id]["checker_instance"]
            checker.is_running = False
            await bot.send_message(user_id, "🛑 <b>Проверка принудительно остановлена.</b>")
    except Exception as e:
        logger.error(f"Ошибка в checker task: {e}", exc_info=True)
        await bot.send_message(
            user_id,
            f"❌ <b>Ошибка в процессе проверки:</b>\n{str(e)[:200]}"
        )
    finally:
        if user_id in active_checkers:
            active_checkers[user_id]["checker_instance"] = None
        if user_id in checker_tasks:
            checker_tasks[user_id] = None


async def on_startup():
    logger.info("Бот запущен")


async def on_shutdown():
    logger.info("Остановка бота...")

    for user_id, task in list(checker_tasks.items()):
        if task and not task.done():
            task.cancel()
            try:
                await task
            except CancelledError:
                pass
            logger.info(f"Задача для user {user_id} отменена")

    await sleep(2)

    for user_id, data in list(active_checkers.items()):
        if data.get("checker_instance"):
            data["checker_instance"].is_running = False

    if bot:
        await bot.session.close()

    logger.info("Бот остановлен")


async def main():
    """Главная функция запуска бота"""
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # Команды регистрируются автоматически через декораторы @dp.message
    # Обработчики FSM также зарегистрированы через декораторы

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")
    finally:
        await on_shutdown()


if __name__ == "__main__":
    try:
        run(main())
    except KeyboardInterrupt:
        print("\n🛑 Бот остановлен пользователем.")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
