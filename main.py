"""Главный файл запуска бота"""

from asyncio import run, sleep
from logging import basicConfig, getLogger, INFO, ERROR
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
from handlers import all_routers
from utils import checker_tasks, active_checkers

basicConfig(level=INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = getLogger(__name__)


async def on_startup():
    """Действия при запуске бота"""
    logger.info("🚀 Бот запущен")


async def on_shutdown():
    """Действия при остановке бота"""
    logger.info("🛑 Остановка бота...")

    # Останавливаем все активные проверки
    for user_id, task in list(checker_tasks.items()):
        if task and not task.done():
            task.cancel()
            try:
                await task
            except:
                pass
            logger.info(f"Задача для user {user_id} отменена")

    await sleep(2)

    # Останавливаем все чекеры
    for user_id, data in list(active_checkers.items()):
        if data.get("checker_instance"):
            data["checker_instance"].is_running = False

    logger.info("✅ Бот остановлен")


async def main():
    """Главная функция запуска бота"""
    # Инициализация бота
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    # Регистрация обработчиков запуска/остановки
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # Подключение всех роутеров
    for router in all_routers:
        dp.include_router(router)

    try:
        # Запуск бота
        logger.info("🤖 Бот начал работу...")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except Exception as e:
        logger.error(f"❌ Ошибка при запуске бота: {e}")
    finally:
        await on_shutdown()
        await bot.session.close()


if __name__ == "__main__":
    try:
        run(main())
    except KeyboardInterrupt:
        print("\n🛑 Бот остановлен пользователем.")
    except Exception as e:
        logger.error(f"💀 Критическая ошибка: {e}")
