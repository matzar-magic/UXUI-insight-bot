import logging
import asyncio
import os
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

    # Инициализация базы данных
    from bot.db.database import create_tables, load_questions_from_fs
    create_tables()

    # Загружаем вопросы с подробным выводом
    print("=" * 50)
    print("Начинаем загрузку вопросов...")
    load_questions_from_fs()
    print("Загрузка вопросов завершена")
    print("=" * 50)

    # Проверяем, что изображения существуют
    from bot.db.database import db_connect
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute('SELECT question_id, image_path FROM questions WHERE image_path IS NOT NULL')
    questions_with_images = cursor.fetchall()
    conn.close()

    print(f"Найдено вопросов с изображениями: {len(questions_with_images)}")
    for question_id, image_path in questions_with_images:
        exists = os.path.exists(image_path) if image_path else False
        print(f"Вопрос {question_id}: {image_path} - {'существует' if exists else 'не существует'}")

    print("=" * 50)

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
