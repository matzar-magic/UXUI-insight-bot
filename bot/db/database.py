import mysql.connector
from mysql.connector import Error
import os
from datetime import datetime
from bot.config import load_config

config = load_config()


def db_connect():
    """Устанавливает соединение с MySQL"""
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
        print(f"Ошибка подключения к MySQL: {e}")
        return None


def create_tables():
    """Создает таблицы в MySQL"""
    conn = db_connect()
    if not conn:
        print("❌ Не удалось подключиться к базе данных")
        return

    cursor = conn.cursor()

    try:
        # Таблица пользователей
        cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                            user_id BIGINT PRIMARY KEY,
                            username VARCHAR(255),
                            total_correct INT DEFAULT 0,
                            current_topic VARCHAR(50) DEFAULT 'typography',
                            current_topic_progress INT DEFAULT 0,
                            completed_topics TEXT,
                            role VARCHAR(20) DEFAULT 'user',
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                        )''')

        # Таблица вопросов
        cursor.execute('''CREATE TABLE IF NOT EXISTS questions (
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
                        )''')

        # Ежедневный прогресс
        cursor.execute('''CREATE TABLE IF NOT EXISTS daily_progress (
                            user_id BIGINT,
                            date DATE,
                            questions_asked INT DEFAULT 0,
                            PRIMARY KEY (user_id, date),
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )''')

        # Отвеченные вопросы
        cursor.execute('''CREATE TABLE IF NOT EXISTS user_answered_questions (
                            user_id BIGINT,
                            question_id INT,
                            PRIMARY KEY (user_id, question_id),
                            answered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )''')

        print("✅ Таблицы базы данных проверены/созданы")

    except Error as e:
        print(f"❌ Ошибка создания таблиц: {e}")
    finally:
        cursor.close()
        conn.close()


def add_user(user_id, username):
    conn = db_connect()
    if not conn:
        return

    cursor = conn.cursor()
    try:
        cursor.execute('''INSERT IGNORE INTO users (user_id, username) 
                       VALUES (%s, %s)''', (user_id, username))
    except Error as e:
        print(f"Ошибка добавления пользователя: {e}")
    finally:
        cursor.close()
        conn.close()


def get_user_stats(user_id):
    conn = db_connect()
    if not conn:
        return (0, 'typography', 0, '', 'user')

    cursor = conn.cursor()
    try:
        cursor.execute(
            '''SELECT total_correct, current_topic, current_topic_progress, 
                      completed_topics, role FROM users WHERE user_id = %s''',
            (user_id,))
        result = cursor.fetchone()
        if result:
            return result
        else:
            add_user(user_id, "unknown")
            return (0, 'typography', 0, '', 'user')
    except Error as e:
        print(f"Ошибка получения статистики: {e}")
        return (0, 'typography', 0, '', 'user')
    finally:
        cursor.close()
        conn.close()


def update_user_stats(user_id, correct):
    conn = db_connect()
    if not conn:
        return

    cursor = conn.cursor()
    try:
        if correct:
            cursor.execute('UPDATE users SET total_correct = total_correct + 1 WHERE user_id = %s',
                           (user_id,))
    except Error as e:
        print(f"Ошибка обновления статистики: {e}")
    finally:
        cursor.close()
        conn.close()


def get_questions_by_topic(user_id, topic, limit=5):
    """Получает вопросы по теме, которые пользователь еще не отвечал"""
    conn = db_connect()
    if not conn:
        return []

    cursor = conn.cursor()
    try:
        cursor.execute('''
            SELECT question_id FROM questions 
            WHERE category = %s 
            AND question_id NOT IN (
                SELECT question_id FROM user_answered_questions WHERE user_id = %s
            )
            ORDER BY RAND() 
            LIMIT %s
        ''', (topic, user_id, limit))
        question_ids = [row[0] for row in cursor.fetchall()]
        return question_ids
    except Error as e:
        print(f"Ошибка получения вопросов по теме: {e}")
        return []
    finally:
        cursor.close()
        conn.close()


def get_question(question_id):
    conn = db_connect()
    if not conn:
        return None

    cursor = conn.cursor()
    try:
        cursor.execute('SELECT * FROM questions WHERE question_id = %s', (question_id,))
        question = cursor.fetchone()
        return question
    except Error as e:
        print(f"Ошибка получения вопроса: {e}")
        return None
    finally:
        cursor.close()
        conn.close()


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
    conn = db_connect()
    if not conn:
        return

    cursor = conn.cursor()
    try:
        cursor.execute('UPDATE users SET current_topic = %s, current_topic_progress = %s WHERE user_id = %s',
                       (topic, progress, user_id))
    except Error as e:
        print(f"Ошибка обновления прогресса темы: {e}")
    finally:
        cursor.close()
        conn.close()


def mark_topic_completed(user_id, topic):
    """Помечает тему как завершенную и обновляет прогресс"""
    conn = db_connect()
    if not conn:
        return

    cursor = conn.cursor()
    try:
        cursor.execute('SELECT completed_topics FROM users WHERE user_id = %s', (user_id,))
        result = cursor.fetchone()
        completed_topics = result[0] if result and result[0] else ''

        if completed_topics:
            completed_list = completed_topics.split(',')
            if topic not in completed_list:
                completed_list.append(topic)
                completed_topics = ','.join(completed_list)
        else:
            completed_topics = topic

        cursor.execute('UPDATE users SET completed_topics = %s WHERE user_id = %s', (completed_topics, user_id))
    except Error as e:
        print(f"Ошибка отметки темы как завершенной: {e}")
    finally:
        cursor.close()
        conn.close()


def get_questions_count_by_topic(topic):
    """Возвращает количество вопросов по теме"""
    conn = db_connect()
    if not conn:
        return 0

    cursor = conn.cursor()
    try:
        cursor.execute('SELECT COUNT(*) FROM questions WHERE category = %s', (topic,))
        count = cursor.fetchone()[0]
        return count
    except Error as e:
        print(f"Ошибка подсчета вопросов: {e}")
        return 0
    finally:
        cursor.close()
        conn.close()


def get_all_users():
    """Возвращает список всех пользователей"""
    conn = db_connect()
    if not conn:
        return []

    cursor = conn.cursor()
    try:
        cursor.execute('SELECT user_id FROM users')
        users = [row[0] for row in cursor.fetchall()]
        return users
    except Error as e:
        print(f"Ошибка получения пользователей: {e}")
        return []
    finally:
        cursor.close()
        conn.close()


def get_user_daily_progress(user_id):
    """Получает прогресс пользователя за сегодня"""
    conn = db_connect()
    if not conn:
        return 0

    cursor = conn.cursor()
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        cursor.execute('SELECT questions_asked FROM daily_progress WHERE user_id = %s AND date = %s', (user_id, today))
        result = cursor.fetchone()
        return result[0] if result else 0
    except Error as e:
        print(f"Ошибка получения дневного прогресса: {e}")
        return 0
    finally:
        cursor.close()
        conn.close()


def update_user_daily_progress(user_id):
    """Обновляет прогресс пользователя за сегодня"""
    conn = db_connect()
    if not conn:
        return

    cursor = conn.cursor()
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        cursor.execute('SELECT 1 FROM daily_progress WHERE user_id = %s AND date = %s', (user_id, today))
        exists = cursor.fetchone()

        if exists:
            cursor.execute(
                'UPDATE daily_progress SET questions_asked = questions_asked + 1 WHERE user_id = %s AND date = %s',
                (user_id, today))
        else:
            cursor.execute('INSERT INTO daily_progress (user_id, date, questions_asked) VALUES (%s, %s, 1)',
                           (user_id, today))
    except Error as e:
        print(f"Ошибка обновления дневного прогресса: {e}")
    finally:
        cursor.close()
        conn.close()


def reset_daily_progress_if_needed():
    """Сбрасывает прогресс если наступил новый день"""
    conn = db_connect()
    if not conn:
        return

    cursor = conn.cursor()
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        cursor.execute('DELETE FROM daily_progress WHERE date != %s', (today,))
    except Error as e:
        print(f"Ошибка сброса дневного прогресса: {e}")
    finally:
        cursor.close()
        conn.close()


def add_answered_question(user_id, question_id):
    """Добавляет вопрос в список отвеченных пользователем"""
    conn = db_connect()
    if not conn:
        return

    cursor = conn.cursor()
    try:
        cursor.execute('INSERT IGNORE INTO user_answered_questions (user_id, question_id) VALUES (%s, %s)',
                       (user_id, question_id))
    except Error as e:
        print(f"Ошибка добавления отвеченного вопроса: {e}")
    finally:
        cursor.close()
        conn.close()


def get_user_answered_questions_count(user_id, topic):
    """Получает количество отвеченных вопросов по теме для пользователя"""
    conn = db_connect()
    if not conn:
        return 0

    cursor = conn.cursor()
    try:
        cursor.execute('''
            SELECT COUNT(*) FROM user_answered_questions uaq
            JOIN questions q ON uaq.question_id = q.question_id
            WHERE uaq.user_id = %s AND q.category = %s
        ''', (user_id, topic))
        count = cursor.fetchone()[0]
        return count
    except Error as e:
        print(f"Ошибка подсчета отвеченных вопросов: {e}")
        return 0
    finally:
        cursor.close()
        conn.close()


def reset_user_progress(user_id):
    """Сбрасывает прогресс пользователя"""
    conn = db_connect()
    if not conn:
        return

    cursor = conn.cursor()
    try:
        cursor.execute('''UPDATE users 
                       SET total_correct = 0, 
                           current_topic = 'typography',
                           current_topic_progress = 0,
                           completed_topics = ''
                       WHERE user_id = %s''', (user_id,))

        cursor.execute('DELETE FROM user_answered_questions WHERE user_id = %s', (user_id,))
        cursor.execute('DELETE FROM daily_progress WHERE user_id = %s', (user_id,))
    except Error as e:
        print(f"Ошибка сброса прогресса пользователя: {e}")
    finally:
        cursor.close()
        conn.close()


def load_questions_from_fs():
    """Загружает вопросы из файловой системы в БД (очищает старые вопросы)"""
    # Эта функция требует значительной переработки для MySQL
    # Пока оставьте ее пустой или удалите, если не используете
    print("Функция load_questions_from_fs требует адаптации для MySQL")
