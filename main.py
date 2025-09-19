# main.py - оптимизированная версия
import logging
import asyncio
import os
import aiohttp
import time
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from bot.config import load_config
from bot.handlers import register_handlers
from bot.scheduler import setup_scheduler

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Кэш для проверки интернета
internet_cache = {'last_check': 0, 'available': True, 'cache_time': 30}


async def test_internet_connection():
    """Проверяем доступность интернета с кэшированием"""
    current_time = time.time()

    # Используем кэшированный результат, если проверяли недавно
    if current_time - internet_cache['last_check'] < internet_cache['cache_time']:
        return internet_cache['available']

    test_urls = [
        "https://api.telegram.org",
        "https://google.com",
        "https://cloudflare.com"
    ]

    for url in test_urls:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=5) as response:
                    if response.status == 200:
                        logger.info(f"Интернет доступен через {url}")
                        internet_cache['available'] = True
                        internet_cache['last_check'] = current_time
                        return True
        except Exception:
            continue

    internet_cache['available'] = False
    internet_cache['last_check'] = current_time
    return False


async def create_bot_session():
    """Создает сессию бота с автоматическим выбором прокси"""
    config = load_config()

    # Список прокси для перебора (с приоритетом прямого подключения)
    proxy_options = [
        None,  # Прямое подключение (первый вариант)
        "http://proxy.server:3128",  # Ваш текущий прокси
    ]

    # Перебираем все варианты подключения
    for proxy_url in proxy_options:
        try:
            if proxy_url:
                logger.info(f"Пробуем подключиться через прокси: {proxy_url}")
                session = AiohttpSession(proxy=proxy_url)
            else:
                logger.info("Пробуем прямое подключение")
                session = AiohttpSession()

            bot = Bot(token=config.TOKEN, session=session)

            # Проверяем подключение к Telegram API с коротким таймаутом
            await asyncio.wait_for(bot.get_me(), timeout=5)
            logger.info("✅ Подключение к Telegram API успешно!")
            return bot

        except Exception as e:
            logger.error(f"Ошибка подключения через {proxy_url or 'прямое подключение'}: {e}")
            continue

    # Если ни один способ не сработал
    raise Exception("Не удалось подключиться ни через один из методов")


async def initialize_bot():
    """Инициализирует бота и базу данных"""
    config = load_config()

    # Создаем сессию бота
    bot = await create_bot_session()

    dp = Dispatcher()

    # Регистрация обработчиков
    register_handlers(dp)

    # Инициализация базы данных
    from bot.db.database import create_tables, load_questions_from_fs
    create_tables()
    load_questions_from_fs()

    # Настройка планировщика для ежедневных вопросов
    scheduler = setup_scheduler(bot)

    return bot, dp, scheduler


async def resilient_polling(bot, dp):
    """Запускает polling с автоматическим восстановлением при сбоях"""
    max_retries = 1000
    base_delay = 1
    max_delay = 5

    for attempt in range(max_retries):
        try:
            logger.info(f"Запуск polling (попытка {attempt + 1}/{max_retries})")
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

        except Exception as e:
            delay = min(base_delay + attempt, max_delay)

            logger.error(f"Ошибка polling (попытка {attempt + 1}/{max_retries}): {e}")
            logger.info(f"Повторная попытка через {delay} секунд...")

            # Ждем перед повторной попыткой
            await asyncio.sleep(delay)

            # Проверяем доступность интернета (с кэшированием)
            internet_available = await test_internet_connection()
            if not internet_available:
                logger.warning("Интернет недоступен, ждем восстановления соединения...")
                await asyncio.sleep(2)
                continue

            # Пытаемся пересоздать сессию бота
            try:
                new_bot = await create_bot_session()
                # Обновляем бота в диспетчере
                dp["bot"] = new_bot
                bot = new_bot
                logger.info("Сессия бота успешно обновлена")
            except Exception as bot_error:
                logger.error(f"Не удалось обновить сессию бота: {bot_error}")
                continue


async def main():
    """Основная функция с быстрым восстановлением"""
    logger.info("Запуск автономного бота UXUI_insight_bot")

    while True:
        try:
            # Инициализируем бота
            bot, dp, scheduler = await initialize_bot()

            logger.info("✅ Бот инициализирован и готов к работе")
            logger.info("Ежедневные вопросы будут отправляться в 14:00 по Москве")

            # Запускаем устойчивый polling
            await resilient_polling(bot, dp)

        except Exception as e:
            logger.critical(f"Критическая ошибка в основном цикле: {e}")
            logger.info("Перезапуск бота через 2 секунды...")
            await asyncio.sleep(2)


if __name__ == "__main__":
    # Бесконечный цикл с быстрым перезапуском
    while True:
        try:
            asyncio.run(main())
        except Exception as e:
            logger.critical(f"Фатальная ошибка: {e}")
            logger.info("Полный перезапуск бота через 1 секунду...")
            time.sleep(1)
