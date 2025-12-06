import asyncio
import os
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import FSInputFile, Message
from aiogram.fsm.storage.memory import MemoryStorage
from tiktok_worker import TikTokChecker

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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
    """Callback для отправки логов из TikTokChecker"""
    try:
        if bot:
            await bot.send_message(user_id, message_text)
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения: {e}")


async def cmd_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет доступа к этому боту.")
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

    await message.answer(
        "👋 <b>Привет! Я готов к работе.</b>\n\n"
        "<i>Доступные команды:</i>\n"
        "/start_check - Начать проверку\n"
        "/stop - Остановить текущую проверку\n"
        "/upload_proxies - Загрузить прокси\n"
        "/upload_emails - Загрузить почты\n"
        "/get_valid - Выгрузить валидные почты\n"
        "/status - Показать загруженные данные"
    )


async def cmd_upload_proxies(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    user_id = message.from_user.id
    if user_id not in active_checkers:
        active_checkers[user_id] = {"proxies": [], "emails": [], "valid_emails": [], "checker_instance": None}

    await message.answer(
        "📤 <b>Пришлите сообщение или текстовый файл (.txt) с прокси.</b>\n\n"
        "<i>Формат: 1 прокси на строку (user:pass@ip:port или ip:port).</i>"
    )
    await state.set_state(CheckStates.waiting_for_proxies)


async def cmd_upload_emails(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    user_id = message.from_user.id
    if user_id not in active_checkers:
        active_checkers[user_id] = {"proxies": [], "emails": [], "valid_emails": [], "checker_instance": None}

    await message.answer(
        "✉️ <b>Пришлите сообщение или текстовый файл (.txt) с почтами.</b>\n\n"
        "<i>Формат: 1 почта на строку.</i>"
    )
    await state.set_state(CheckStates.waiting_for_emails)


async def handle_proxies_input(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    user_id = message.from_user.id
    items = []

    if message.document and message.document.file_name.endswith(('.txt', '.list')):
        await message.answer("🔄 <b>Обрабатываю файл...</b>")
        file_info = await message.bot.get_file(message.document.file_id)

        os.makedirs(TEMP_DIR, exist_ok=True)
        file_path = os.path.join(TEMP_DIR, f"{user_id}_proxies.txt")

        await message.bot.download_file(file_info.file_path, destination=file_path)

        with open(file_path, 'r', encoding='utf-8') as f:
            items = [line.strip() for line in f if line.strip()]

        os.remove(file_path)

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

    await message.answer(f"✅ Успешно загружено <b>{len(items)}</b> прокси.")
    await state.clear()


async def handle_emails_input(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    user_id = message.from_user.id
    items = []

    if message.document and message.document.file_name.endswith(('.txt', '.list')):
        await message.answer("🔄 <b>Обрабатываю файл...</b>")
        file_info = await message.bot.get_file(message.document.file_id)

        os.makedirs(TEMP_DIR, exist_ok=True)
        file_path = os.path.join(TEMP_DIR, f"{user_id}_emails.txt")

        await message.bot.download_file(file_info.file_path, destination=file_path)

        with open(file_path, 'r', encoding='utf-8') as f:
            items = [line.strip() for line in f if line.strip()]

        os.remove(file_path)

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

    await message.answer(f"✅ Успешно загружено <b>{len(items)}</b> почт.")
    await state.clear()


async def cmd_start_check(message: Message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        return

    if user_id in checker_tasks and not checker_tasks[user_id].done():
        await message.answer("⚠️ <b>Проверка уже запущена!</b> Используйте /stop.")
        return

    data = active_checkers.get(user_id, {"proxies": [], "emails": [], "valid_emails": [], "checker_instance": None})

    if not data["proxies"]:
        await message.answer("❌ <b>Сначала загрузите прокси</b> с помощью /upload_proxies.")
        return
    if not data["emails"]:
        await message.answer("❌ <b>Сначала загрузите почты</b> с помощью /upload_emails.")
        return

    emails_count = len(data["emails"])
    proxies_count = len(data["proxies"])

    await message.answer(
        f"🚀 <b>Запускаю проверку...</b>\n\n"
        f"📧 Почты: <b>{emails_count}</b>\n"
        f"🔗 Прокси: <b>{proxies_count}</b>\n"
        f"⚡ Потоков: <b>{min(proxies_count, 10)}</b>"
    )

    try:
        checker = TikTokChecker(
            proxies=data["proxies"],
            log_callback=send_log_async,
            user_id=user_id
        )

        active_checkers[user_id]["checker_instance"] = checker

        # ПЕРЕДАЕМ message ПЕРВЫМ АРГУМЕНТОМ!
        task = asyncio.create_task(run_checker_task(message, checker, data["emails"], user_id))
        checker_tasks[user_id] = task

    except Exception as ex:
        await message.answer(f"❌ <b>Ошибка при запуске:</b> {str(ex)}")
        active_checkers[user_id]["checker_instance"] = None


async def run_checker_task(message: Message, checker: TikTokChecker, emails: list, user_id: int):
    try:
        await message.answer(
            f"📊 <b>Запускаю проверку {len(emails)} почт...</b>\n"
            f"Используется {min(len(checker.proxy_pool), 10)} потоков"
        )

        valid_emails = await checker.run_checker(emails)

        if user_id in active_checkers:
            active_checkers[user_id]["valid_emails"].extend(valid_emails)

        await message.answer(
            f"🏁 <b>Проверка завершена!</b>\n"
            f"Всего проверено: {checker.checked_count}\n"
            f"Найдено валидных: <b>{len(valid_emails)}</b>"
        )

    except asyncio.CancelledError:
        logger.info(f"Задача проверки для user {user_id} отменена")
        if user_id in active_checkers and active_checkers[user_id]["checker_instance"]:
            checker = active_checkers[user_id]["checker_instance"]
            checker.is_running = False
            await message.answer("🛑 <b>Проверка принудительно остановлена.</b>")
    except Exception as e:
        logger.error(f"Ошибка в checker task: {e}", exc_info=True)
        await message.answer(f"❌ <b>Ошибка в процессе проверки:</b>\n{str(e)[:200]}")
    finally:
        if user_id in active_checkers:
            active_checkers[user_id]["checker_instance"] = None
        if user_id in checker_tasks:
            checker_tasks[user_id] = None


async def cmd_stop(message: Message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        return

    if user_id in checker_tasks and checker_tasks[user_id] and not checker_tasks[user_id].done():
        checker_tasks[user_id].cancel()
        await message.answer("🛑 <b>Останавливаю проверку...</b>")

        try:
            await checker_tasks[user_id]
        except asyncio.CancelledError:
            pass

        await message.answer("✅ <b>Проверка остановлена.</b>")
    else:
        await message.answer("Проверка не была запущена.")


async def cmd_get_valid(message: Message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        return

    data = active_checkers.get(user_id, {"valid_emails": []})
    valid_emails = data.get("valid_emails", [])

    if not valid_emails:
        await message.answer("<b>Нет найденных валидных почт.</b>")
        return

    os.makedirs(TEMP_DIR, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    file_name = f"valid_emails_{user_id}_{timestamp}.txt"
    file_path = os.path.join(TEMP_DIR, file_name)

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(valid_emails))

    document = FSInputFile(file_path)
    await message.answer_document(document)
    await message.answer(f"📤 <b>Отправлено {len(valid_emails)} валидных почт.</b>")

    os.remove(file_path)


async def cmd_status(message: Message):
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

    await message.answer(status_text)


async def on_startup():
    logger.info("Бот запущен")


async def on_shutdown():
    logger.info("Остановка бота...")

    for user_id, task in list(checker_tasks.items()):
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            logger.info(f"Задача для user {user_id} отменена")

    await asyncio.sleep(2)

    for user_id, data in list(active_checkers.items()):
        if data.get("checker_instance"):
            data["checker_instance"].is_running = False

    if bot:
        await bot.session.close()

    logger.info("Бот остановлен")


async def main():
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    dp.message.register(cmd_start, CommandStart())
    dp.message.register(cmd_upload_proxies, Command("upload_proxies"))
    dp.message.register(cmd_upload_emails, Command("upload_emails"))
    dp.message.register(cmd_start_check, Command("start_check"))
    dp.message.register(cmd_stop, Command("stop"))
    dp.message.register(cmd_get_valid, Command("get_valid"))
    dp.message.register(cmd_status, Command("status"))

    dp.message.register(handle_proxies_input, CheckStates.waiting_for_proxies,
                        F.text | F.document)
    dp.message.register(handle_emails_input, CheckStates.waiting_for_emails,
                        F.text | F.document)

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")
    finally:
        await on_shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Бот остановлен пользователем.")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)

# TODO: Создать файл с кнопками и создать кнопки завтра
