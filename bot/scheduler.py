# bot/scheduler.py - полностью оптимизированная версия
import asyncio
from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot.db.database import (
    get_user_stats, get_questions_by_topic, get_question,
    get_questions_count_by_topic, get_all_users,
    reset_daily_progress_if_needed, get_user_answered_questions_count,
    get_next_topic, update_user_topic_progress, mark_topic_completed
)
from bot.config import load_config
import os
from aiogram.types import FSInputFile
from pytz import timezone
import time

config = load_config()

# Кэш для подписок и пользовательских данных
subscription_cache = {}
user_topic_cache = {}
CACHE_TTL = 300  # 5 минут

# Флаг для защиты от множественного запуска рассылки
is_sending_daily_questions = False
is_sending_admin_notification = False
sending_lock = asyncio.Lock()


def cleanup_old_cache():
    """Очищает устаревшие записи в кэшах"""
    current_time = time.time()

    # Очищаем subscription_cache
    for user_id in list(subscription_cache.keys()):
        if current_time - subscription_cache[user_id]['timestamp'] > CACHE_TTL:
            del subscription_cache[user_id]

    # Очищаем user_topic_cache
    for user_id in list(user_topic_cache.keys()):
        if current_time - user_topic_cache[user_id]['timestamp'] > CACHE_TTL:
            del user_topic_cache[user_id]


async def check_subscription(user_id, bot):
    """Проверяет подписку с кэшированием"""
    current_time = time.time()

    # Проверяем кэш
    if user_id in subscription_cache:
        if current_time - subscription_cache[user_id]['timestamp'] < CACHE_TTL:
            return subscription_cache[user_id]['subscribed']

    # Если нет в кэше или устарело, проверяем через API
    try:
        member = await bot.get_chat_member(chat_id=config.CHANNEL_ID, user_id=user_id)
        is_subscribed = member.status in ['member', 'administrator', 'creator']

        # Сохраняем в кэш
        subscription_cache[user_id] = {
            'subscribed': is_subscribed,
            'timestamp': current_time
        }

        return is_subscribed
    except Exception as e:
        print(f"Ошибка при проверке подписки: {e}")
        return False


async def send_question_to_user(bot, user_id, question_data, caption):
    """Отправляет вопрос пользователю по ID"""
    # Распаковываем 12 полей вместо 11
    (question_id, category, question_block, image_path,
     option_a, option_b, option_c, option_d,
     buttons_count, correct_option, explanation, created_at) = question_data

    keyboard_buttons = []
    letters = ['a', 'b', 'c', 'd']

    for i in range(buttons_count):
        if i < len(letters):
            keyboard_buttons.append(
                InlineKeyboardButton(text=letters[i], callback_data=f"answer_{question_id}_{letters[i]}"))

    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    keyboard.inline_keyboard.append(keyboard_buttons)

    full_question_text = f"{caption}\n\n{question_block}"

    try:
        if image_path and os.path.exists(image_path):
            photo = FSInputFile(image_path)
            await bot.send_photo(
                chat_id=user_id,
                photo=photo,
                caption=full_question_text,
                reply_markup=keyboard
            )
        else:
            await bot.send_message(chat_id=user_id, text=full_question_text, reply_markup=keyboard)
    except Exception as e:
        print(f"Ошибка отправки вопроса пользователю {user_id}: {e}")
        # Пытаемся отправить без изображения
        try:
            await bot.send_message(chat_id=user_id, text=full_question_text, reply_markup=keyboard)
        except Exception as e2:
            print(f"Не удалось отправить вопрос пользователю {user_id}: {e2}")


async def send_admin_notification(bot: Bot):
    """Отправляет уведомление администратору с защитой от множественного запуска"""
    global is_sending_admin_notification

    async with sending_lock:
        if is_sending_admin_notification:
            print("⚠️ Уведомление администратору уже отправляется, пропускаем...")
            return

        is_sending_admin_notification = True

    try:
        await bot.send_message(chat_id=config.ADMIN_ID, text="Всё гуд! ✅")
        print(f"Уведомление отправлено администратору {config.ADMIN_ID}")
    except Exception as e:
        print(f"Ошибка отправки уведомления администратору: {e}")
    finally:
        async with sending_lock:
            is_sending_admin_notification = False


async def process_user_questions(bot, user_id, current_topic):
    """Обрабатывает отправку вопросов для одного пользователя"""
    # Проверяем, завершена ли текущая тема
    total_questions = get_questions_count_by_topic(current_topic)
    answered_questions = get_user_answered_questions_count(user_id, current_topic)

    if answered_questions >= total_questions:
        # Текущая тема завершена, переходим к следующей
        next_topic = get_next_topic(current_topic)
        if next_topic:
            # Обновляем тему пользователя
            update_user_topic_progress(user_id, next_topic, 0)
            current_topic = next_topic
            # Отправляем уведомление пользователю
            try:
                await bot.send_message(user_id, f"🎉 Тема завершена! Переходим к следующей теме: {next_topic}")
            except:
                pass
        else:
            # Все темы завершены
            try:
                await bot.send_message(user_id, "🎉 Поздравляем! Вы завершили все темы!")
            except:
                pass
            return None

    # Проверяем, есть ли вопросы в теме
    topic_questions_count = get_questions_count_by_topic(current_topic)
    if topic_questions_count == 0:
        print(f"Нет вопросов по теме {current_topic} для пользователя {user_id}")
        return current_topic

    # Получаем вопросы для текущей темы (только те, на которые еще не ответили)
    # ИСПРАВЛЕНО: извлекаем ID из кортежей
    question_ids_result = get_questions_by_topic(user_id, current_topic, 1)
    question_ids = [row[0] for row in question_ids_result] if question_ids_result else []

    if not question_ids:
        # Нет новых вопросов в текущей теме
        next_topic = get_next_topic(current_topic)
        if next_topic:
            # Переходим к следующей теме
            update_user_topic_progress(user_id, next_topic, 0)
            current_topic = next_topic

            # Получаем вопросы для новой темы
            question_ids_result = get_questions_by_topic(user_id, current_topic, 1)
            question_ids = [row[0] for row in question_ids_result] if question_ids_result else []

            if not question_ids:
                print(f"Нет вопросов в теме {current_topic} для пользователя {user_id}")
                return current_topic
        else:
            print(f"Все темы завершены для пользователя {user_id}")
            return current_topic

    question_data = get_question(question_ids[0])
    if question_data:
        caption = f"// {current_topic.capitalize()}"
        try:
            await send_question_to_user(bot, user_id, question_data, caption)
            print(f"Вопрос отправлен пользователю {user_id}")
        except Exception as e:
            print(f"Ошибка отправки вопроса пользователю {user_id}: {e}")
    else:
        print(f"Не удалось загрузить данные вопроса для пользователя {user_id}")

    return current_topic


async def send_daily_question(bot: Bot):
    """Отправляет ежедневный вопрос всем пользователям с защитой от множественного запуска"""
    global is_sending_daily_questions

    # Проверяем и устанавливаем флаг с блокировкой
    async with sending_lock:
        if is_sending_daily_questions:
            print("⚠️ Рассылка ежедневных вопросов уже выполняется, пропускаем...")
            return

        is_sending_daily_questions = True

    try:
        # Очищаем кэш перед началом
        subscription_cache.clear()
        user_topic_cache.clear()

        # Сбрасываем прогресс за предыдущий день
        reset_daily_progress_if_needed()

        users = get_all_users()

        if not users:
            print("Нет пользователей для отправки ежедневного вопроса")
            return

        # Группируем пользователей по темам для batch обработки
        users_by_topic = {}
        for user_id in users:
            # Используем кэш для тем пользователей
            current_time = time.time()
            if user_id in user_topic_cache:
                if current_time - user_topic_cache[user_id]['timestamp'] < CACHE_TTL:
                    current_topic = user_topic_cache[user_id]['topic']
                else:
                    stats = get_user_stats(user_id)
                    current_topic = stats[1] if stats else 'typography'
                    user_topic_cache[user_id] = {
                        'topic': current_topic,
                        'timestamp': current_time
                    }
            else:
                stats = get_user_stats(user_id)
                current_topic = stats[1] if stats else 'typography'
                user_topic_cache[user_id] = {
                    'topic': current_topic,
                    'timestamp': current_time
                }

            if current_topic not in users_by_topic:
                users_by_topic[current_topic] = []
            users_by_topic[current_topic].append(user_id)

        # Обрабатываем пользователей группами по темам
        processed_users = 0
        skipped_users = 0

        for topic, topic_users in users_by_topic.items():
            # Получаем вопросы для темы один раз
            question_ids = get_questions_by_topic(None, topic, len(topic_users) * 2)

            for user_id in topic_users:
                try:
                    # Проверяем подписку с кэшированием
                    is_subscribed = await check_subscription(user_id, bot)
                    if not is_subscribed:
                        skipped_users += 1
                        continue

                    # Обрабатываем вопросы для пользователя
                    new_topic = await process_user_questions(bot, user_id, topic)

                    # Обновляем кэш, если тема изменилась
                    if new_topic != topic:
                        user_topic_cache[user_id] = {
                            'topic': new_topic,
                            'timestamp': time.time()
                        }

                    processed_users += 1

                    # Небольшая пауза между пользователями для снижения нагрузки
                    if processed_users % 10 == 0:
                        await asyncio.sleep(0.1)

                except Exception as e:
                    print(f"Ошибка обработки пользователя {user_id}: {e}")
                    continue

        # Очищаем кэш после обработки
        subscription_cache.clear()
        user_topic_cache.clear()

        print(f"✅ Ежедневные вопросы отправлены. Обработано: {processed_users}, Пропущено: {skipped_users}")

    except Exception as e:
        print(f"❌ Критическая ошибка при отправке ежедневных вопросов: {e}")
        import traceback
        traceback.print_exc()

    finally:
        # Снимаем флаг независимо от результата
        async with sending_lock:
            is_sending_daily_questions = False


def setup_scheduler(bot: Bot):
    """Настраивает планировщик для ежедневной отправки вопросов"""
    scheduler = AsyncIOScheduler()

    # Явно указываем московское время
    moscow_tz = timezone('Europe/Moscow')

    # Ежедневные вопросы в 14:00 по Омскому времени (или же в 11:00 по МСК)
    scheduler.add_job(
        send_daily_question,
        trigger=CronTrigger(hour=11, minute=0, timezone=moscow_tz),
        args=[bot],
        id='daily_question',
        misfire_grace_time=300  # Разрешаем опоздание до 5 минут
    )

    # Уведомление администратору в 13:00 по Омскому времени (или же в 10:00 по МСК)
    scheduler.add_job(
        send_admin_notification,
        trigger=CronTrigger(hour=10, minute=0, timezone=moscow_tz),
        args=[bot],
        id='admin_notification',
        misfire_grace_time=300
    )

    # Сброс прогресса каждый день в 03:00 по Омскому времени (или же в 00:00 по МСК)
    scheduler.add_job(
        reset_daily_progress_if_needed,
        trigger=CronTrigger(hour=0, minute=0, timezone=moscow_tz),
        id='reset_progress',
        misfire_grace_time=300
    )

    # Очистка кэша каждый час
    scheduler.add_job(
        cleanup_old_cache,
        trigger=CronTrigger(hour='*', minute=0, timezone=moscow_tz),
        id='cache_cleanup'
    )

    scheduler.start()
    print("✅ Планировщик запущен с задачами:")
    for job in scheduler.get_jobs():
        print(f"   - {job.id}: {job.trigger}")

    return scheduler


# Функция для остановки планировщика
def shutdown_scheduler(scheduler):
    """Останавливает планировщик"""
    if scheduler:
        scheduler.shutdown()
        print("✅ Планировщик остановлен")
