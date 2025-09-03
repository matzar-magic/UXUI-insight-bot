import logging
import asyncio
from aiogram import Bot, Dispatcher
from bot.config import load_config  # Правильный импорт
from bot.handlers import register_handlers
from bot.scheduler import setup_scheduler

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    # Загрузка конфигурации
    config = load_config()

    # Создаем объекты бота и диспетчера
    bot = Bot(token=config.TOKEN)
    dp = Dispatcher()

    # Регистрация обработчиков
    register_handlers(dp)

    # Инициализация базы данных (без удаления старых данных)
    from bot.db.database import create_tables, load_questions_from_fs
    create_tables()  # Теперь не удаляет старые данные
    load_questions_from_fs()  # Теперь только добавляет новые вопросы

    # Настройка планировщика для ежедневных вопросов
    scheduler = setup_scheduler(bot)

    # Запуск бота
    logger.info("Бот UXUI_insight_bot запущен и готов к работе.")
    logger.info("Ежедневные вопросы будут отправляться в 14:00")

    try:
        await dp.start_polling(bot)
    finally:
        if scheduler:
            scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
