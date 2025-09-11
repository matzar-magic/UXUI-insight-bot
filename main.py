import logging
import asyncio
import os
import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from bot.config import load_config
from bot.handlers import register_handlers
from bot.scheduler import setup_scheduler

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_proxy_connection():
    """Тестируем подключение через прокси"""
    test_url = "https://api.telegram.org"
    proxy_url = "http://proxy.server:3128"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(test_url, proxy=proxy_url, timeout=10) as response:
                logger.info(f"Прокси работает, статус: {response.status}")
                return True
    except Exception as e:
        logger.error(f"Ошибка подключения через прокси: {e}")
        return False


async def main():
    # Загрузка конфигурации
    config = load_config()

    # Тестируем подключение через прокси
    proxy_works = await test_proxy_connection()

    if proxy_works:
        # Используем прокси
        proxy_url = "http://proxy.server:3128"
        logger.info(f"Используем прокси: {proxy_url}")
        session = AiohttpSession(proxy=proxy_url)
        bot = Bot(token=config.TOKEN, session=session)
    else:
        # Пробуем прямое подключение
        logger.warning("Прокси недоступен, пробуем прямое подключение")
        bot = Bot(token=config.TOKEN)

    dp = Dispatcher()

    # Регистрация обработчиков
    register_handlers(dp)

    # Инициализация базы данных
    from bot.db.database import create_tables, load_questions_from_fs
    create_tables()
    load_questions_from_fs()

    # Настройка планировщика для ежедневных вопросов
    scheduler = setup_scheduler(bot)

    # Запуск бота с обработкой сетевых ошибок
    max_retries = 3
    for attempt in range(max_retries):
        try:
            logger.info("Бот UXUI_insight_bot запущен и готов к работе.")
            logger.info("Ежедневные вопросы будут отправляться в 14:00")

            await dp.start_polling(bot)
            break
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                logger.error(f"Ошибка подключения (попытка {attempt + 1}/{max_retries}): {e}")
                logger.info(f"Повторная попытка через {wait_time} секунд...")
                await asyncio.sleep(wait_time)

                # При последней попытке пробуем альтернативный метод
                if attempt == max_retries - 2:
                    logger.info("Пробуем альтернативный метод подключения...")
                    # Можно попробовать другие прокси или методы здесь
            else:
                logger.error(f"Не удалось подключиться после {max_retries} попыток")
                # Здесь можно добавить дополнительные методы обработки ошибок
                raise


if __name__ == "__main__":
    asyncio.run(main())
