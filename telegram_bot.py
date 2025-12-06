from asyncio import create_task, run, sleep, CancelledError
from os import makedirs, remove
from logging import basicConfig, getLogger, INFO, ERROR
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import FSInputFile, Message
from aiogram.fsm.storage.memory import MemoryStorage

from tiktok_worker import TikTokChecker
from keyboards import get_main_keyboard, get_cancel_keyboard, remove_keyboard

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


async def send_log_async(user_id: int, message_text: str):
    try:
        if bot:
            await bot.send_message(user_id, message_text)
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения: {e}")


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
        "Используйте кнопку ниже для отмены:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(CheckStates.waiting_for_emails)


@dp.message(CheckStates.waiting_for_proxies, F.text | F.document)
async def handle_proxies_input(message: Message, state: FSMContext):
    """Обработчик ввода прокси (FSM состояние)"""
    if not is_admin(message.from_user.id):
        return

    user_id = message.from_user.id

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
    """Действия при запуске бота"""
    logger.info("Бот запущен")


async def on_shutdown():
    """Действия при остановке бота"""
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
