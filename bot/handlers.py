# bot/handlers.py - полностью оптимизированная версия
from aiogram import types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot.db.database import (
    add_user, get_user_stats, update_user_stats,
    get_questions_by_topic, get_question,
    update_user_topic_progress, mark_topic_completed,
    get_questions_count_by_topic,
    get_user_daily_progress, update_user_daily_progress,
    reset_daily_progress_if_needed,
    get_user_answered_questions_count,
    add_answered_question, get_next_topic,
    get_all_users, reset_user_progress,
    execute_query
)
from bot.config import load_config
import os
import asyncio
from aiogram.types import FSInputFile
from datetime import datetime
import time

# Глобальные словари с ограничением размера и TTL
user_next_questions = {}
user_active_sessions = {}
admin_broadcast_state = {}
user_reset_states = {}
message_delete_tasks = {}
subscription_cache = {}

# Ограничиваем размер кэшей
MAX_CACHE_SIZE = 1000
CACHE_TTL = 300  # 5 минут

config = load_config()


def cleanup_old_cache():
    """Очищает устаревшие записи в кэшах"""
    current_time = time.time()

    # Очищаем кэши
    for cache_dict in [user_next_questions, user_active_sessions,
                       admin_broadcast_state, user_reset_states, subscription_cache]:
        keys_to_remove = []
        for key, value in cache_dict.items():
            if isinstance(value, dict) and 'timestamp' in value:
                if current_time - value['timestamp'] > CACHE_TTL:
                    keys_to_remove.append(key)
            elif current_time - getattr(value, 'timestamp', current_time) > CACHE_TTL:
                keys_to_remove.append(key)

        for key in keys_to_remove:
            del cache_dict[key]

    # Очищаем слишком большие кэши
    for cache_dict in [user_next_questions, user_active_sessions]:
        if len(cache_dict) > MAX_CACHE_SIZE:
            keys_to_remove = list(cache_dict.keys())[:len(cache_dict) - MAX_CACHE_SIZE]
            for key in keys_to_remove:
                del cache_dict[key]


async def delete_message_after(message: types.Message, delay: int):
    """Удаляет сообщение после задержки с отменой предыдущих задач"""
    user_id = message.chat.id
    message_id = message.message_id

    # Отменяем предыдущую задачу удаления для этого сообщения
    task_key = f"{user_id}_{message_id}"
    if task_key in message_delete_tasks:
        message_delete_tasks[task_key].cancel()

    # Создаем новую задачу
    async def delete_task():
        await asyncio.sleep(delay)
        try:
            await message.delete()
        except:
            pass
        finally:
            if task_key in message_delete_tasks:
                del message_delete_tasks[task_key]

    message_delete_tasks[task_key] = asyncio.create_task(delete_task())


async def check_subscription(user_id, bot, force_check=False):
    """Проверяет подписку с кэшированием"""
    current_time = time.time()

    # Если принудительная проверка, игнорируем кэш
    if not force_check:
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

async def ask_for_subscription(message: types.Message):
    """Просит пользователя подписаться на канал"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться на канал", url="https://t.me/matzar_studio")],
        [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_subscription")]
    ])

    await message.answer(
        "⚠️ Для использования бота необходимо подписаться на канал @matzar_studio.\n\n"
        "После подписки нажмите кнопку 'Проверить подписку' ниже.",
        reply_markup=keyboard
    )


async def start_command(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    add_user(user_id, username)
    reset_daily_progress_if_needed()

    # Проверяем, является ли пользователь администратором
    is_admin = str(user_id) == config.ADMIN_ID

    # Получаем имя пользователя для приветствия
    user_first_name = message.from_user.first_name or "друг"

    # Проверяем подписку с кэшированием
    is_subscribed = await check_subscription(user_id, message.bot)

    welcome_text = (
        f"🎨 Привет, {user_first_name}!\n\n"
        "Я помогу вам изучить основы дизайна через ежедневное обучение.\n\n"
    )

    if not is_subscribed:
        welcome_text += (
            "⚠️ Для использования бота необходимо подписаться на канал @matzar_studio.\n\n"
            "После подписки нажмите кнопку 'Проверить подписку' ниже."
        )

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📢 Подписаться на канал", url="https://t.me/matzar_studio")],
            [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_subscription")]
        ])

        await message.answer(welcome_text, reply_markup=keyboard)
        return

    # Если пользователь подписан, показываем полное приветствие
    welcome_text += (
        "Каждый день в 14:00 вы будете получать 5 вопросов по одной из тем:\n"
        "• Типографика\n"
        "• Колористика\n"
        "• UX-принципы\n"
        "• UI-паттерны\n"
        "• Композиция\n\n"
        "Используйте команды:\n"
        "/stats - ваша статистика\n"
        "/today - получить сегодняшние вопросы\n"
        "/reset_progress - сбросить прогресс\n"
    )

    # Добавляем команды для администратора
    if is_admin:
        welcome_text += (
            "\n👑 Команды администратора:\n"
            "/letter - отправить сообщение всем пользователям\n"
            "/out - отменить рассылку\n"
        )

    welcome_text += "\n💡 Не удаляйте сообщения с вопросами - они помогут в обучении!"

    await message.answer(welcome_text)


async def stats_command(message: types.Message):
    # Проверяем подписку с кэшированием
    is_subscribed = await check_subscription(message.from_user.id, message.bot)
    if not is_subscribed:
        await ask_for_subscription(message)
        return

    # Удаляем сообщение пользователя с командой /stats
    try:
        await message.delete()
    except:
        pass

    user_id = message.from_user.id
    stats = get_user_stats(user_id)

    if stats:
        # ИСПРАВЛЕНО: распаковываем 6 значений вместо 5
        total_correct, current_topic, progress, completed_topics, user_role, daily_progress = stats

        # Получаем количество завершенных тем
        completed_count = len(completed_topics.split(',')) if completed_topics else 0

        # Получаем общее количество вопросов в текущей теме
        total_questions = get_questions_count_by_topic(current_topic)

        # ИСПРАВЛЕНИЕ: используем progress вместо answered_questions
        # answered_questions = get_user_answered_questions_count(user_id, current_topic)
        answered_questions = progress  # Это значение из current_topic_progress

        # Рассчитываем процент прогресса по теме
        progress_percent = 0
        if total_questions > 0:
            progress_percent = min(100, int(answered_questions / total_questions * 100))

        # Форматируем название темы для красивого отображения
        topic_names = {
            'typography': 'Типографика',
            'coloristics': 'Колористика',
            'composition': 'Композиция',
            'ux_principles': 'UX-принципы',
            'ui_patterns': 'UI-паттерны',
        }
        current_topic_name = topic_names.get(current_topic, current_topic.capitalize())

        # Форматируем список завершенных тем
        completed_topic_names = []
        if completed_topics:
            for topic in completed_topics.split(','):
                completed_topic_names.append(topic_names.get(topic, topic.capitalize()))

        response = (
            f"📊 Ваша статистика:\n\n"
            f"• Текущая тема: {current_topic_name}\n"
            f"• Прогресс по теме: {progress_percent}% ({answered_questions}/{total_questions})\n"
            f"• Завершено тем: {completed_count}/5\n"
        )

        if completed_topic_names:
            response += f"• Пройденные темы: {', '.join(completed_topic_names)}\n"

        response += f"• Вопросов сегодня: {daily_progress}/5"

    else:
        response = "Статистика недоступна. Используйте /start для начала."

    # Отправляем ответ и планируем его удаление
    stats_msg = await message.answer(response)

    # Определяем время удаления в зависимости от активности сессии
    if user_id in user_active_sessions and user_active_sessions[user_id]:
        # Активная сессия - удаляем через 10 секунд
        asyncio.create_task(delete_message_after(stats_msg, 10))
    else:
        # Неактивная сессия - удаляем через 60 секунд
        asyncio.create_task(delete_message_after(stats_msg, 60))


async def today_command(message: types.Message):
    # Проверяем подписку с кэшированием
    is_subscribed = await check_subscription(message.from_user.id, message.bot)
    if not is_subscribed:
        await ask_for_subscription(message)
        return

    user_id = message.from_user.id

    # Проверяем дневной лимит ПЕРЕД началом сессии
    stats = get_user_stats(user_id)
    if stats:
        total_correct, current_topic, progress, completed_topics, user_role, daily_progress = stats
        if daily_progress >= 5:
            # Удаляем сообщение пользователя с командой /today
            try:
                await message.delete()
            except:
                pass

            msg = await message.answer(
                "❌ Вы уже ответили на 5 вопросов сегодня. Следующие вопросы будут доступны завтра.")
            asyncio.create_task(delete_message_after(msg, 10))
            return

    # Проверяем, есть ли уже активная сессия
    if user_id in user_active_sessions and user_active_sessions[user_id]:
        # Удаляем сообщение пользователя с командой /today
        try:
            await message.delete()
        except:
            pass

        # Отправляем и удаляем сообщение бота о активной сессии
        msg = await message.answer("❌ Вы уже просматриваете сегоднящние вопросы. Завершите текущую сессию!")
        asyncio.create_task(delete_message_after(msg, 10))
        return

    """Отправляет сегодняшние вопросы (до 5)"""
    stats = get_user_stats(user_id)

    if not stats:
        await message.answer("Сначала используйте /start")
        return

    # ИСПРАВЛЕНО: распаковываем 6 значений вместо 5
    total_correct, current_topic, progress, completed_topics, user_role, daily_progress = stats

    # Двойная проверка дневного лимита
    if daily_progress >= 5:
        # Удаляем сообщение пользователя с командой /today
        try:
            await message.delete()
        except:
            pass

        # Отправляем и удаляем сообщение бота о лимите
        msg = await message.answer("❌ Вы уже ответили на 5 вопросов сегодня. Следующие вопросы будут доступны завтра.")
        asyncio.create_task(delete_message_after(msg, 10))
        return

    # Помечаем сессию как активную
    user_active_sessions[user_id] = True

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
            await message.answer(f"🎉 Тема завершена! Переходим к следующей теме: {next_topic}")
        else:
            # Все темы завершены
            await message.answer("🎉 Поздравляем! Вы завершили все темы!")
            # Снимаем отметку об активной сессии
            user_active_sessions[user_id] = False
            return

    # Проверяем, есть ли вопросы в теме
    topic_questions_count = get_questions_count_by_topic(current_topic)
    if topic_questions_count == 0:
        await message.answer(f"❌ Вопросы по теме '{current_topic}' не найдены.\n\nАдминистратор добавит вопросы скоро.")
        # Снимаем отметку об активной сессии
        user_active_sessions[user_id] = False
        return

    # Получаем вопросы для текущей темы (только те, на которые еще не ответили)
    # ИСПРАВЛЕНО: извлекаем ID из кортежей
    questions_needed = 5 - daily_progress  # Только нужное количество
    question_ids_result = get_questions_by_topic(user_id, current_topic, questions_needed)
    question_ids = [row[0] for row in question_ids_result] if question_ids_result else []

    if not question_ids:
        # Нет новых вопросов в текущей теме
        next_topic = get_next_topic(current_topic)
        if next_topic:
            # Переходим к следующей теме
            update_user_topic_progress(user_id, next_topic, 0)
            current_topic = next_topic
            await message.answer(f"🎉 В текущей теме нет новых вопросов! Переходим к следующей теме: {next_topic}")

            # Получаем вопросы для новой темы
            question_ids_result = get_questions_by_topic(user_id, current_topic, questions_needed)
            question_ids = [row[0] for row in question_ids_result] if question_ids_result else []

            if not question_ids:
                await message.answer(f"❌ В теме '{current_topic}' тоже нет вопросов.")
                # Снимаем отметку об активной сессии
                user_active_sessions[user_id] = False
                return
        else:
            await message.answer("🎉 Поздравляем! Вы завершили все темы!")
            # Снимаем отметку об активной сессии
            user_active_sessions[user_id] = False
            return

    # Сохраняем следующие вопросы для пользователя
    user_next_questions[user_id] = question_ids

    # Отправляем первый вопрос
    await send_next_question(message, user_id)


async def letter_command(message: types.Message):
    """Команда для отправки сообщения всем пользователям (только для администратора)"""
    user_id = message.from_user.id

    # Удаляем сообщение с командой /letter сразу
    try:
        await message.delete()
    except:
        pass

    # Проверяем, является ли пользователь администратором
    if str(user_id) != config.ADMIN_ID:
        msg = await message.answer("❌ У вас нет прав для выполнения этой команды.")
        asyncio.create_task(delete_message_after(msg, 60))
        return

    # Устанавливаем состояние рассылки
    admin_broadcast_state[user_id] = True
    msg = await message.answer(
        "✉️ Режим рассылки активирован. Отправьте сообщение, которое будет отправлено всем пользователям.\n\n"
        "Используйте /out для отмены."
    )
    asyncio.create_task(delete_message_after(msg, 60))


async def out_command(message: types.Message):
    """Команда для отмены рассылки (только для администратора)"""
    user_id = message.from_user.id

    # Удаляем сообщение с командой /out сразу
    try:
        await message.delete()
    except:
        pass

    # Проверяем, является ли пользователь администратором
    if str(user_id) != config.ADMIN_ID:
        msg = await message.answer("❌ У вас нет прав для выполнения этой команды.")
        asyncio.create_task(delete_message_after(msg, 60))
        return

    # Отключаем состояние рассылки
    if user_id in admin_broadcast_state:
        del admin_broadcast_state[user_id]

    msg = await message.answer("❌ Режим рассылки отменен.")
    asyncio.create_task(delete_message_after(msg, 60))


async def handle_broadcast_message(message: types.Message):
    """Обрабатывает сообщение для рассылки"""
    user_id = message.from_user.id

    # Проверяем, находится ли администратор в режиме рассылки
    if user_id not in admin_broadcast_state or not admin_broadcast_state[user_id]:
        return False

    # Отключаем состояние рассылки
    del admin_broadcast_state[user_id]

    # Получаем всех пользователей
    users = get_all_users()
    total_users = len(users)
    successful = 0
    failed = 0

    # Отправляем сообщение о начале рассылки
    progress_msg = await message.answer(f"✉️ Начинаю рассылку сообщения для {total_users} пользователей...")

    # Функция для отправки сообщения пользователю
    async def send_to_user(user_id):
        try:
            # Используем copy_message для копирования исходного сообщения
            await message.bot.copy_message(
                chat_id=user_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id
            )
            return True
        except Exception as e:
            print(f"Ошибка отправки сообщения пользователю {user_id}: {e}")
            return False

    # Отправляем сообщение всем пользователям с ограничением скорости
    for i, user_id in enumerate(users):
        if await send_to_user(user_id):
            successful += 1
        else:
            failed += 1

        # Обновляем прогресс каждые 10 отправок и делаем небольшую паузу
        if (i + 1) % 10 == 0:
            try:
                await progress_msg.edit_text(
                    f"✉️ Рассылка в процессе...\n"
                    f"Успешно: {successful}\n"
                    f"Не удалось: {failed}\n"
                    f"Осталось: {total_users - i - 1}"
                )
                await asyncio.sleep(0.1)  # Небольшая пауза
            except:
                pass

    # Отправляем финальный отчет
    await progress_msg.edit_text(
        f"✅ Рассылка завершена!\n"
        f"Всего пользователей: {total_users}\n"
        f"Успешно: {successful}\n"
        f"Не удалось: {failed}"
    )

    return True


async def end_questions_session(message, user_id):
    """Завершает сессию вопросов с финальным сообщением"""
    # Очищаем оставшиеся вопросы
    if user_id in user_next_questions:
        del user_next_questions[user_id]

    # Снимаем отметку об активной сессии
    user_active_sessions[user_id] = False

    final_msg = await message.answer(
        "🎉 Вы ответили на все 5 вопросов сегодня!\n\n"
        "Завтра вас ждут новые вопросы. Не забывайте заглядывать!"
    )
    asyncio.create_task(delete_message_after(final_msg, 10))


async def send_next_question(message, user_id):
    """Отправляет следующий вопрос пользователю с проверкой дневного лимита"""
    # Проверяем дневной лимит ПЕРЕД отправкой вопроса
    stats = get_user_stats(user_id)
    if not stats:
        user_active_sessions[user_id] = False
        return

    total_correct, current_topic, progress, completed_topics, user_role, daily_progress = stats

    # СТРОГО проверяем лимит - если уже 5 вопросов сегодня, завершаем сессию
    if daily_progress >= 5:
        await end_questions_session(message, user_id)
        return

    # Если нет сохраненных вопросов, получаем новые
    if user_id not in user_next_questions or not user_next_questions[user_id]:
        stats = get_user_stats(user_id)
        if not stats:
            user_active_sessions[user_id] = False
            return

        total_correct, current_topic, progress, completed_topics, user_role, daily_progress = stats

        # Проверяем дневной лимит ЕЩЕ РАЗ перед получением новых вопросов
        if daily_progress >= 5:
            await end_questions_session(message, user_id)
            return

        # Получаем РОВНО столько вопросов, сколько осталось до лимита
        questions_needed = 5 - daily_progress
        question_ids_result = get_questions_by_topic(user_id, current_topic, questions_needed)
        question_ids = [row[0] for row in question_ids_result] if question_ids_result else []

        if not question_ids:
            await end_questions_session(message, user_id)
            return

        user_next_questions[user_id] = question_ids

    # Берем следующий вопрос
    question_id = user_next_questions[user_id].pop(0)
    question_data = get_question(question_id)

    if question_data:
        # Обновляем статистику перед отправкой вопроса
        stats = get_user_stats(user_id)
        if stats:
            total_correct, current_topic, progress, completed_topics, user_role, daily_progress = stats
            topic_names = {
                'typography': 'Типографика',
                'coloristics': 'Колористика',
                'composition': 'Композиция',
                'ux_principles': 'UX-принципы',
                'ui_patterns': 'UI-паттерны',
            }
            topic_name = topic_names.get(current_topic, current_topic.capitalize())
            await send_question(message, question_data, f"// {topic_name}")
    else:
        await message.answer("❌ Не удалось загрузить вопрос. Попробуйте позже.")
        user_active_sessions[user_id] = False


async def send_question(message, question_data, caption):
    """Отправляет один вопрос"""
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
            msg = await message.answer_photo(
                photo=photo,
                caption=full_question_text,
                reply_markup=keyboard
            )
        else:
            msg = await message.answer(full_question_text, reply_markup=keyboard)
    except Exception as e:
        print(f"Ошибка при отправке вопроса: {e}")
        msg = await message.answer(full_question_text, reply_markup=keyboard)

    return msg


async def handle_answer(callback_query: types.CallbackQuery):
    # Сразу отвечаем на callback, чтобы избежать ошибки "query is too old"
    await callback_query.answer()

    user_id = callback_query.from_user.id
    data = callback_query.data.split('_')
    question_id = int(data[1])
    user_answer = data[2]

    # Проверяем дневной лимит перед обработкой ответа
    stats = get_user_stats(user_id)
    if stats:
        total_correct, current_topic, progress, completed_topics, user_role, daily_progress = stats
        if daily_progress >= 5:
            # Лимит достигнут, завершаем сессию
            await end_questions_session(callback_query.message, user_id)
            return

    # Отключаем все кнопки в сообщении
    try:
        if callback_query.message.photo:
            await callback_query.message.edit_reply_markup(reply_markup=None)
        else:
            await callback_query.message.edit_reply_markup(reply_markup=None)
    except:
        pass  # Игнорируем ошибки, если сообщение уже было изменено

    question_data = get_question(question_id)
    if not question_data:
        return

    (question_id, category, question_block, image_path,
     option_a, option_b, option_c, option_d,
     buttons_count, correct_option, explanation, created_at) = question_data

    is_correct = user_answer == correct_option

    # Добавляем вопрос в отвеченные
    add_answered_question(user_id, question_id)

    # Обновляем статистику
    if is_correct:
        update_user_stats(user_id, True)
        response = f"✅ Правильно\n\n{explanation}"
    else:
        response = f"❌ Неправильно \nПравильный ответ: {correct_option.lower()})\n\n{explanation}"

    # ОБНОВЛЯЕМ ПРОГРЕСС ПО ТЕМЕ
    # Получаем текущую тему пользователя
    stats = get_user_stats(user_id)
    if stats:
        total_correct, current_topic, progress, completed_topics, user_role, daily_progress = stats
        # Увеличиваем прогресс по теме на 1
        new_progress = progress + 1
        execute_query(
            'UPDATE users SET current_topic_progress = %s WHERE user_id = %s',
            (new_progress, user_id)
        )

    # Обновляем дневной прогресс
    if not update_user_daily_progress(user_id):
        # Лимит достигнут, завершаем сессию
        await end_questions_session(callback_query.message, user_id)
        return

    # Отправляем ответ как отдельное сообщение
    result_message = await callback_query.message.answer(response)

    # Проверяем, завершена ли текущая тема ПОСЛЕ объяснения
    stats = get_user_stats(user_id)
    topic_completed = False
    if stats:
        # ИСПРАВЛЕНО: распаковываем 6 значений вместо 5
        total_correct, current_topic, progress, completed_topics, user_role, daily_progress = stats
        total_questions = get_questions_count_by_topic(current_topic)
        answered_questions = get_user_answered_questions_count(user_id, current_topic)

        # Если тема завершена, помечаем ее как завершенную
        if answered_questions >= total_questions:
            mark_topic_completed(user_id, current_topic)
            topic_completed = True

    # Отправляем анимированный таймер
    timer_msg = await callback_query.message.answer("⏳ Следующий вопрос через 10 секунд...")

    # Анимируем таймер (обновляем каждую секунду)
    for seconds_left in range(9, 0, -1):
        await asyncio.sleep(1)
        try:
            await timer_msg.edit_text(f"⏳ Следующий вопрос через {seconds_left} секунд...")
        except:
            break  # Если сообщение было удалено, прерываем цикл

    # Удаляем таймер
    await timer_msg.delete()

    # Убираем кнопки из исходного сообщения (если еще не убрали)
    try:
        # Получаем текст исходного сообщения
        original_text = callback_query.message.caption if callback_query.message.photo else callback_query.message.text

        # Редактируем сообщение, убирая клавиатуру (если еще не убрали)
        if callback_query.message.photo:
            await callback_query.message.edit_caption(caption=original_text, reply_markup=None)
        else:
            await callback_query.message.edit_text(text=original_text, reply_markup=None)
    except:
        pass  # Игнорируем ошибки редактирования

    # Удаляем только временную часть сообщения с результатом через 0 секунд
    await asyncio.sleep(0)
    try:
        # Оставляем только объяснение, удаляя первую часть сообщения
        await result_message.edit_text(explanation)
    except:
        # Если не получилось отредактировать, просто удаляем всё сообщение
        await result_message.delete()

    # Если тема завершена, отправляем сообщение о переходе ПОСЛЕ объяснения
    if topic_completed:
        next_topic = get_next_topic(current_topic)
        if next_topic:
            update_user_topic_progress(user_id, next_topic, 0)
            # Уведомляем пользователя о переходе
            topic_names = {
                'typography': 'Типографика',
                'coloristics': 'Колористика',
                'composition': 'Композиция',
                'ux_principles': 'UX-принципы',
                'ui_patterns': 'UI-паттерны',
            }
            next_topic_name = topic_names.get(next_topic, next_topic.capitalize())
            await callback_query.message.answer(
                f"🎉 Тема завершена! Переходим к следующей теме: {next_topic_name}"
            )
        else:
            await callback_query.message.answer("🎉 Поздравляем! Вы завершили все темы!")
            return

    # Отправляем следующий вопрос
    await send_next_question(callback_query.message, user_id)


async def check_subscription_callback(callback_query: types.CallbackQuery):
    """Обрабатывает проверку подписки с принудительным обновлением кэша"""
    user_id = callback_query.from_user.id

    # Принудительно очищаем кэш для этого пользователя
    if user_id in subscription_cache:
        del subscription_cache[user_id]

    # Делаем свежую проверку подписки
    is_subscribed = await check_subscription(user_id, callback_query.bot, force_check=True)

    if is_subscribed:
        # Удаляем сообщение с просьбой подписаться
        try:
            await callback_query.message.delete()
        except:
            pass

        # Приветствуем пользователя
        await callback_query.message.answer(
            "✅ Спасибо за подписку! Теперь вы можете использовать все функции бота.\n\n"
            "Используйте /start для начала работы."
        )
    else:
        # Если пользователь все еще не подписан
        await callback_query.answer(
            "Вы еще не подписались на канал. Пожалуйста, подпишитесь и попробуйте снова.",
            show_alert=True
        )


async def reset_progress_command(message: types.Message):
    # Проверяем подписку с кэшированием
    is_subscribed = await check_subscription(message.from_user.id, message.bot)
    if not is_subscribed:
        await ask_for_subscription(message)
        return

    user_id = message.from_user.id

    # Удаляем сообщение с командой
    try:
        await message.delete()
    except:
        pass

    # Создаем клавиатуру с подтверждением
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"reset_confirm_{user_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"reset_cancel_{user_id}")]
    ])

    # Отправляем сообщение с подтверждением
    msg = await message.answer(
        "⚠️ Вы уверены, что хотите сбросить весь прогресс?\n\n"
        "Это действие нельзя отменить! Вы потеряете:\n"
        "• Все правильные ответы\n"
        "• Прогресс по текущей теме\n"
        "• Пройденные темы\n"
        "• Историю ответов",
        reply_markup=keyboard
    )

    # Сохраняем ID сообщения для возможного удаления
    user_reset_states[user_id] = msg.message_id


async def handle_reset_confirmation(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data.split('_')
    action = data[1]
    target_user_id = int(data[2])

    # Проверяем, что пользователь подтверждает свой собственный сброс
    if user_id != target_user_id:
        await callback_query.answer("❌ Вы не можете подтвердить сброс для другого пользователя.", show_alert=True)
        return

    await callback_query.answer()

    if action == "confirm":
        # Выполняем сброс прогресса
        reset_user_progress(user_id)

        # Удаляем сообщение с подтверждением
        if user_id in user_reset_states:
            try:
                await callback_query.bot.delete_message(chat_id=user_id, message_id=user_reset_states[user_id])
            except:
                pass
            del user_reset_states[user_id]

        # Отправляем подтверждение сброса
        confirmation_msg = await callback_query.message.answer(
            "✅ Прогресс успешно сброшен!\n\n"
            "Теперь вы начинаете с начала обучения."
        )

        # Удаляем сообщение через 5 секунд
        asyncio.create_task(delete_message_after(confirmation_msg, 5))

    elif action == "cancel":
        # Отменяем сброс
        if user_id in user_reset_states:
            try:
                await callback_query.bot.delete_message(chat_id=user_id, message_id=user_reset_states[user_id])
            except:
                pass
            del user_reset_states[user_id]

        # Отправляем сообщение об отмене
        cancel_msg = await callback_query.message.answer("❌ Сброс прогресса отменен.")

        # Удаляем сообщение через 5 секунд
        asyncio.create_task(delete_message_after(cancel_msg, 5))

    # Удаляем исходное сообщение с кнопками
    try:
        await callback_query.message.delete()
    except:
        pass


def cleanup_old_cache():
    """Очищает устаревшие записи в кэшах handlers"""
    current_time = time.time()

    # Очищаем кэши
    for cache_dict in [user_next_questions, user_active_sessions,
                       admin_broadcast_state, user_reset_states, subscription_cache]:
        keys_to_remove = []
        for key, value in cache_dict.items():
            if isinstance(value, dict) and 'timestamp' in value:
                if current_time - value['timestamp'] > CACHE_TTL:
                    keys_to_remove.append(key)
            elif current_time - getattr(value, 'timestamp', current_time) > CACHE_TTL:
                keys_to_remove.append(key)

        for key in keys_to_remove:
            del cache_dict[key]

    # Очищаем слишком большие кэши
    for cache_dict in [user_next_questions, user_active_sessions]:
        if len(cache_dict) > MAX_CACHE_SIZE:
            keys_to_remove = list(cache_dict.keys())[:len(cache_dict) - MAX_CACHE_SIZE]
            for key in keys_to_remove:
                del cache_dict[key]


def register_handlers(dp):
    dp.message.register(start_command, Command('start'))
    dp.message.register(stats_command, Command('stats'))
    dp.message.register(today_command, Command('today'))
    dp.message.register(reset_progress_command, Command('reset_progress'))
    dp.message.register(letter_command, Command('letter'))
    dp.message.register(out_command, Command('out'))
    dp.callback_query.register(handle_answer, F.data.startswith('answer_'))
    dp.callback_query.register(check_subscription_callback, F.data == "check_subscription")
    dp.callback_query.register(handle_reset_confirmation, F.data.startswith('reset_'))

    # Добавляем обработчик для сообщений (должен быть последним)
    dp.message.register(handle_broadcast_message, F.chat.type == "private")
