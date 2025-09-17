import asyncio
from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot.db.database import get_user_stats, get_questions_by_topic, get_question, get_questions_count_by_topic, \
    get_all_users, reset_daily_progress_if_needed, get_user_answered_questions_count, get_next_topic, \
    update_user_topic_progress, mark_topic_completed
from bot.config import load_config
import os
from aiogram.types import FSInputFile
from pytz import timezone

config = load_config()


async def check_subscription(user_id, bot):
    """Проверяет, подписан ли пользователь на канал"""
    try:
        member = await bot.get_chat_member(chat_id=config.CHANNEL_ID, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        print(f"Ошибка при проверке подписки: {e}")
        return False


async def send_admin_notification(bot: Bot):
    """Отправляет уведомление администратору"""
    try:
        await bot.send_message(chat_id=config.ADMIN_ID, text="Всё гуд! ✅")
        print(f"Уведомление отправлено администратору {config.ADMIN_ID}")
    except Exception as e:
        print(f"Ошибка отправки уведомления администратору: {e}")


async def send_question_to_user(bot, user_id, question_data, caption):
    """Отправляет вопрос пользователю по ID"""
    # Распаковываем 12 полей вместо 11
    (question_id, category, question_block, image_path,
     option_a, option_b, option_c, option_d,
     buttons_count, correct_option, explanation, created_at) = question_data  # Добавлено created_at

    # Остальной код без изменений...
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
        await bot.send_message(chat_id=user_id, text=full_question_text, reply_markup=keyboard)


async def send_daily_question(bot: Bot):
    """Отправляет ежедневный вопрос всем пользователям"""
    # Сбрасываем прогресс за предыдущий день
    reset_daily_progress_if_needed()

    users = get_all_users()

    if not users:
        print("Нет пользователей для отправки ежедневного вопроса")
        return

    for user_id in users:
        # Проверяем подписку пользователя
        is_subscribed = await check_subscription(user_id, bot)
        if not is_subscribed:
            print(f"Пользователь {user_id} не подписан на канал, пропускаем")
            continue

        stats = get_user_stats(user_id)

        if not stats:
            continue

        total_correct, current_topic, progress, completed_topics, user_role = stats  # Добавляем user_role

        # Остальной код без изменений...
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
                continue

        # Проверяем, есть ли вопросы в теме
        topic_questions_count = get_questions_count_by_topic(current_topic)
        if topic_questions_count == 0:
            print(f"Нет вопросов по теме {current_topic} для пользователя {user_id}")
            continue

        # Получаем вопросы для текущей темы (только те, на которые еще не ответили)
        question_ids = get_questions_by_topic(user_id, current_topic, 1)

        if not question_ids:
            # Нет новых вопросов в текущей теме
            next_topic = get_next_topic(current_topic)
            if next_topic:
                # Переходим к следующей теме
                update_user_topic_progress(user_id, next_topic, 0)
                current_topic = next_topic

                # Получаем вопросы для новой темы
                question_ids = get_questions_by_topic(user_id, current_topic, 1)

                if not question_ids:
                    print(f"Нет вопросов в теме {current_topic} для пользователя {user_id}")
                    continue
            else:
                print(f"Все темы завершены для пользователя {user_id}")
                continue

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


def setup_scheduler(bot: Bot):
    """Настраивает планировщик для ежедневной отправки вопросов и уведомлений"""
    scheduler = AsyncIOScheduler()

    # Явно указываем московское время
    moscow_tz = timezone('Europe/Moscow')

    # Ежедневные вопросы в 14:00
    scheduler.add_job(
        send_daily_question,
        trigger=CronTrigger(hour=11, minute=00, timezone=moscow_tz),
        args=[bot],
        id='daily_question'
    )

    # Уведомление администратору в 13:00
    scheduler.add_job(
        send_admin_notification,
        trigger=CronTrigger(hour=10, minute=00, timezone=moscow_tz),
        args=[bot],
        id='admin_notification'
    )

    scheduler.start()
    return scheduler
