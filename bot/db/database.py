# bot/db/database.py - ФИНАЛЬНАЯ исправленная версия БЕЗ пула соединений
import mysql.connector
from mysql.connector import Error
import os
from datetime import datetime
from bot.config import load_config
import threading
import time

config = load_config()

# Кэш для часто используемых данных
question_count_cache = {}
user_stats_cache = {}
subscription_check_cache = {}
cache_lock = threading.Lock()

# Время жизни кэша (в секундах)
CACHE_TTL = 300  # 5 минут


def cleanup_old_cache():
    """Очищает устаревшие записи в кэшах"""
    current_time = time.time()
    with cache_lock:
        # Очищаем question_count_cache
        for topic in list(question_count_cache.keys()):
            if current_time - question_count_cache[topic]['timestamp'] > CACHE_TTL:
                del question_count_cache[topic]

        # Очищаем user_stats_cache
        for user_id in list(user_stats_cache.keys()):
            if current_time - user_stats_cache[user_id]['timestamp'] > CACHE_TTL:
                del user_stats_cache[user_id]

        # Очищаем subscription_check_cache
        for user_id in list(subscription_check_cache.keys()):
            if current_time - subscription_check_cache[user_id]['timestamp'] > CACHE_TTL:
                del subscription_check_cache[user_id]


def db_connect():
    """Простое подключение к MySQL без пула"""
    try:
        connection = mysql.connector.connect(
            host=config.DB_HOST,
            database=config.DB_NAME,
            user=config.DB_USER,
            password=config.DB_PASSWORD,
            port=config.DB_PORT,
            autocommit=True
        )
        return connection
    except Error as e:
        print(f"❌ Ошибка подключения к MySQL: {e}")
        return None


def execute_query(query, params=None, fetch_one=False, fetch_all=False, many=False):
    """Универсальная функция выполнения запросов"""
    conn = db_connect()
    if not conn:
        return None

    try:
        cursor = conn.cursor()

        if many and params:
            cursor.executemany(query, params)
        else:
            cursor.execute(query, params or ())

        if fetch_one:
            result = cursor.fetchone()
        elif fetch_all:
            result = cursor.fetchall()
        else:
            result = None

        if not many:  # Для executemany autocommit не работает
            conn.commit()
        return result
    except Error as e:
        print(f"❌ Ошибка выполнения запроса: {e}")
        if conn:
            conn.rollback()
        return None
    finally:
        if 'cursor' in locals() and cursor:
            cursor.close()
        if conn:
            conn.close()


def create_tables():
    """Создает таблицы в MySQL"""
    conn = db_connect()
    if not conn:
        print("❌ Не удалось подключиться к базе данных")
        return

    cursor = conn.cursor()

    try:
        # Объединяем все CREATE TABLE в один мультизапрос
        create_tables_query = '''
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username VARCHAR(255),
            total_correct INT DEFAULT 0,
            current_topic VARCHAR(50) DEFAULT 'typography',
            current_topic_progress INT DEFAULT 0,
            completed_topics TEXT,
            role VARCHAR(20) DEFAULT 'user',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB;

        CREATE TABLE IF NOT EXISTS questions (
            question_id INT AUTO_INCREMENT PRIMARY KEY,
            category VARCHAR(50) NOT NULL,
            question_text TEXT NOT NULL,
            image_path TEXT,
            option_a TEXT,
            option_b TEXT,
            option_c TEXT,
            option_d TEXT,
            buttons_count INT NOT NULL,
            correct_option CHAR(1) NOT NULL,
            explanation TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB;

        CREATE TABLE IF NOT EXISTS daily_progress (
            user_id BIGINT,
            date DATE,
            questions_asked INT DEFAULT 0,
            PRIMARY KEY (user_id, date),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB;

        CREATE TABLE IF NOT EXISTS user_answered_questions (
            user_id BIGINT,
            question_id INT,
            PRIMARY KEY (user_id, question_id),
            answered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_user_id (user_id),
            INDEX idx_question_id (question_id)
        ) ENGINE=InnoDB;
        '''

        for result in cursor.execute(create_tables_query, multi=True):
            pass

        print("✅ Таблицы базы данных проверены/созданы")

    except Error as e:
        print(f"❌ Ошибка создания таблиц: {e}")
    finally:
        cursor.close()
        conn.close()


def add_user(user_id, username):
    """Добавляет пользователя с batch обработкой"""
    execute_query(
        '''INSERT IGNORE INTO users (user_id, username)
        VALUES (%s, %s)''',
        (user_id, username)
    )


def get_user_stats(user_id):
    """Получает статистику пользователя с кэшированием"""
    current_time = time.time()

    # Проверяем кэш
    with cache_lock:
        if user_id in user_stats_cache:
            if current_time - user_stats_cache[user_id]['timestamp'] < CACHE_TTL:
                return user_stats_cache[user_id]['data']

    # Если нет в кэше или устарело, получаем из БД
    result = execute_query(
        '''SELECT total_correct, current_topic, current_topic_progress,
                  completed_topics, role FROM users WHERE user_id = %s''',
        (user_id,), fetch_one=True
    )

    if result:
        daily_progress = get_user_daily_progress(user_id)
        stats = result + (daily_progress,)

        # Сохраняем в кэш
        with cache_lock:
            user_stats_cache[user_id] = {
                'data': stats,
                'timestamp': current_time
            }

        return stats
    else:
        add_user(user_id, "unknown")
        return (0, 'typography', 0, '', 'user', 0)


def update_user_stats(user_id, correct):
    """Обновляет статистику пользователя и инвалидирует кэш"""
    if correct:
        execute_query(
            'UPDATE users SET total_correct = total_correct + 1 WHERE user_id = %s',
            (user_id,)
        )

    # Инвалидируем кэш
    with cache_lock:
        if user_id in user_stats_cache:
            del user_stats_cache[user_id]


def get_questions_by_topic(user_id, topic, limit=5):
    """Получает вопросы по теме, которые пользователь еще не отвечал"""
    return execute_query(
        '''
        SELECT question_id FROM questions
        WHERE category = %s
        AND question_id NOT IN (
            SELECT question_id FROM user_answered_questions WHERE user_id = %s
        )
        ORDER BY RAND()
        LIMIT %s
        ''',
        (topic, user_id, limit),
        fetch_all=True
    ) or []


def get_question(question_id):
    """Получает вопрос по ID"""
    return execute_query(
        'SELECT * FROM questions WHERE question_id = %s',
        (question_id,),
        fetch_one=True
    )


def get_next_topic(current_topic):
    """Возвращает следующую тему после текущей"""
    topics = ['typography', 'coloristics', 'composition', 'ux_principles', 'ui_patterns']
    try:
        current_index = topics.index(current_topic)
        if current_index + 1 < len(topics):
            return topics[current_index + 1]
        return None
    except ValueError:
        return 'typography'


def update_user_topic_progress(user_id, topic, progress):
    """Обновляет прогресс темы пользователя"""
    execute_query(
        'UPDATE users SET current_topic = %s, current_topic_progress = %s WHERE user_id = %s',
        (topic, progress, user_id)
    )

    # Инвалидируем кэш
    with cache_lock:
        if user_id in user_stats_cache:
            del user_stats_cache[user_id]


def mark_topic_completed(user_id, topic):
    """Помечает тему как завершенную"""
    result = execute_query(
        'SELECT completed_topics FROM users WHERE user_id = %s',
        (user_id,),
        fetch_one=True
    )

    completed_topics = result[0] if result and result[0] else ''

    if completed_topics:
        completed_list = completed_topics.split(',')
        if topic not in completed_list:
            completed_list.append(topic)
            completed_topics = ','.join(completed_list)
    else:
        completed_topics = topic

    execute_query(
        'UPDATE users SET completed_topics = %s WHERE user_id = %s',
        (completed_topics, user_id)
    )

    # Инвалидируем кэш
    with cache_lock:
        if user_id in user_stats_cache:
            del user_stats_cache[user_id]


def get_questions_count_by_topic(topic):
    """Возвращает количество вопросов по теме с кэшированием"""
    current_time = time.time()

    # Проверяем кэш
    with cache_lock:
        if topic in question_count_cache:
            if current_time - question_count_cache[topic]['timestamp'] < CACHE_TTL:
                return question_count_cache[topic]['data']

    # Если нет в кэше или устарело, получаем из БД
    result = execute_query(
        'SELECT COUNT(*) FROM questions WHERE category = %s',
        (topic,),
        fetch_one=True
    )

    count = result[0] if result else 0

    # Сохраняем в кэш
    with cache_lock:
        question_count_cache[topic] = {
            'data': count,
            'timestamp': current_time
        }

    return count


def get_all_users():
    """Возвращает список всех пользователей"""
    result = execute_query('SELECT user_id FROM users', fetch_all=True)
    return [row[0] for row in result] if result else []


def get_user_daily_progress(user_id):
    """Получает прогресс пользователя за сегодня"""
    today = datetime.now().strftime('%Y-%m-%d')
    result = execute_query(
        'SELECT questions_asked FROM daily_progress WHERE user_id = %s AND date = %s',
        (user_id, today),
        fetch_one=True
    )
    return result[0] if result else 0


def update_user_daily_progress(user_id):
    """Обновляет прогресс пользователя за сегодня"""
    today = datetime.now().strftime('%Y-%m-%d')

    result = execute_query(
        'SELECT 1 FROM daily_progress WHERE user_id = %s AND date = %s',
        (user_id, today),
        fetch_one=True
    )

    if result:
        execute_query(
            'UPDATE daily_progress SET questions_asked = questions_asked + 1 WHERE user_id = %s AND date = %s',
            (user_id, today)
        )
    else:
        execute_query(
            'INSERT INTO daily_progress (user_id, date, questions_asked) VALUES (%s, %s, 1)',
            (user_id, today)
        )


def reset_daily_progress_if_needed():
    """Сбрасывает прогресс ТОЛЬКО если наступил новый день"""
    today = datetime.now().strftime('%Y-%m-%d')

    # Удаляем записи за предыдущие дни (кроме сегодняшнего)
    execute_query('DELETE FROM daily_progress WHERE date != %s', (today,))


def add_answered_question(user_id, question_id):
    """Добавляет вопрос в список отвеченных пользователем"""
    execute_query(
        'INSERT IGNORE INTO user_answered_questions (user_id, question_id) VALUES (%s, %s)',
        (user_id, question_id)
    )


def get_user_answered_questions_count(user_id, topic):
    """Получает количество отвеченных вопросов по теме"""
    result = execute_query(
        '''
        SELECT COUNT(*) FROM user_answered_questions uaq
        JOIN questions q ON uaq.question_id = q.question_id
        WHERE uaq.user_id = %s AND q.category = %s
        ''',
        (user_id, topic),
        fetch_one=True
    )
    return result[0] if result else 0


def reset_user_progress(user_id):
    """Сбрасывает прогресс пользователя"""
    # Выполняем все операции в одной транзакции
    execute_query('''UPDATE users
                   SET total_correct = 0,
                       current_topic = 'typography',
                       current_topic_progress = 0,
                       completed_topics = ''
                   WHERE user_id = %s''', (user_id,))

    execute_query('DELETE FROM user_answered_questions WHERE user_id = %s', (user_id,))
    execute_query('DELETE FROM daily_progress WHERE user_id = %s', (user_id,))

    # Инвалидируем кэш
    with cache_lock:
        if user_id in user_stats_cache:
            del user_stats_cache[user_id]


def load_questions_from_fs():
    """Загружает вопросы из файловой системы в MySQL БД"""
    conn = db_connect()
    if not conn:
        print("❌ Не удалось подключиться к базе данных для загрузки вопросов")
        return

    cursor = conn.cursor()

    try:
        # Очищаем старые вопросы перед загрузкой новых
        cursor.execute('DELETE FROM questions')
        print("Старые вопросы удалены из базы данных")

        # Определяем правильный путь к папке questions
        current_dir = os.path.dirname(os.path.abspath(__file__))
        base_dir = os.path.join(current_dir, '..', '..')
        questions_dir = os.path.join(base_dir, 'questions')
        questions_dir = os.path.normpath(questions_dir)
        print(f"Ищем вопросы в: {questions_dir}")

        # Проверяем существование папки
        if not os.path.exists(questions_dir):
            print(f"❌ Папка questions не найдена по пути: {questions_dir}")
            return

        categories = ['typography', 'coloristics', 'composition', 'ux_principles', 'ui_patterns']
        questions_to_insert = []
        total_loaded = 0

        for category in categories:
            category_path = os.path.join(questions_dir, category)
            print(f"Проверяем категорию: {category_path}")

            if os.path.exists(category_path):
                # Ищем все .txt файлы
                txt_files = [f for f in os.listdir(category_path) if f.endswith('.txt')]
                print(f"Найдено .txt файлов в {category}: {len(txt_files)}")

                for file_name in txt_files:
                    try:
                        file_path = os.path.join(category_path, file_name)
                        print(f"Обрабатываем файл: {file_name}")
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read().strip()

                        # Разбираем содержимое файла
                        parts = content.split(';')
                        if len(parts) < 4:
                            print(f"❌ Файл {file_name} имеет неправильный формат (частей: {len(parts)})")
                            continue

                        # Первая часть - вопрос и варианты ответов
                        question_block = parts[0].strip()

                        # Вторая часть - количество кнопок
                        try:
                            buttons_count = int(parts[1].strip())
                        except ValueError:
                            print(f"❌ Ошибка в файле {file_name}: buttons_count должен быть числом")
                            continue

                        # Третья часть - правильный ответ
                        correct_option = parts[2].strip().lower()

                        # Проверяем корректность correct_option
                        if correct_option not in ['a', 'b', 'c', 'd']:
                            print(f"❌ Ошибка в файле {file_name}: correct_option должен быть a, b, c или d")
                            continue

                        # Четвертая часть - объяснение
                        explanation = parts[3].strip()

                        # Ищем изображение с тем же именем
                        base_name = os.path.splitext(file_name)[0]
                        image_path = None

                        # Проверяем все возможные расширения изображений
                        for ext in ['.png', '.jpg', '.jpeg', '.webp']:
                            potential_image = os.path.join(category_path, base_name + ext)
                            if os.path.exists(potential_image):
                                image_path = potential_image
                                print(f"Найдено изображение: {image_path}")
                                break

                        # Добавляем вопрос в список для batch вставки
                        questions_to_insert.append((
                            category, question_block, image_path,
                            None, None, None, None,  # options a-d
                            buttons_count, correct_option, explanation
                        ))

                        total_loaded += 1
                        print(f"✓ Подготовлен вопрос из файла: {file_name}")

                    except Exception as e:
                        print(f"❌ Ошибка загрузки вопроса {file_name}: {e}")
                        import traceback
                        traceback.print_exc()
            else:
                print(f"❌ Папка категории {category} не найдена: {category_path}")

        # Выполняем batch вставку всех вопросов
        if questions_to_insert:
            cursor.executemany('''INSERT INTO questions
                               (category, question_text, image_path, option_a, option_b, option_c, option_d, 
                                buttons_count, correct_option, explanation)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
                               questions_to_insert)

            conn.commit()
            print(f"✅ Вопросы успешно загружены в MySQL! Всего: {total_loaded}")

            # Очищаем кэш счетчиков вопросов
            with cache_lock:
                question_count_cache.clear()

    except Exception as e:
        print(f"❌ Ошибка при загрузке вопросов: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
    finally:
        cursor.close()
        conn.close()


# Функция для периодической очистки кэша
def start_cache_cleanup():
    """Запускает периодическую очистку кэша"""

    def cleanup_loop():
        while True:
            time.sleep(CACHE_TTL)
            cleanup_old_cache()

    cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True)
    cleanup_thread.start()


# Запускаем очистку кэша при импорте
start_cache_cleanup()

# Создаем таблицы при импорте
create_tables()