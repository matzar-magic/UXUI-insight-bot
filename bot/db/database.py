import sqlite3
import os
import glob
from datetime import datetime


def get_db_path():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(current_dir, '..', '..', 'uxui_insight.db')


def db_connect():
    return sqlite3.connect(get_db_path())


def create_tables():
    conn = db_connect()
    cursor = conn.cursor()

    # Создаем таблицы если они не существуют (без удаления старых)
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        username TEXT,
                        total_correct INTEGER DEFAULT 0,
                        current_topic TEXT DEFAULT 'typography',
                        current_topic_progress INTEGER DEFAULT 0,
                        completed_topics TEXT DEFAULT '')''')

    # Проверяем существование колонки role и добавляем если нужно
    cursor.execute("PRAGMA table_info(users)")
    columns = [column[1] for column in cursor.fetchall()]
    if 'role' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'user'")
        print("Добавлена колонка role в таблицу users")

    # Остальные таблицы без изменений...
    cursor.execute('''CREATE TABLE IF NOT EXISTS questions (
                        question_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        category TEXT NOT NULL,
                        question_text TEXT NOT NULL,
                        image_path TEXT,
                        option_a TEXT,
                        option_b TEXT,
                        option_c TEXT,
                        option_d TEXT,
                        buttons_count INTEGER NOT NULL,
                        correct_option CHAR(1) NOT NULL,
                        explanation TEXT)''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS daily_progress (
                        user_id INTEGER,
                        date TEXT,
                        questions_asked INTEGER DEFAULT 0,
                        PRIMARY KEY (user_id, date))''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS user_answered_questions (
                        user_id INTEGER,
                        question_id INTEGER,
                        PRIMARY KEY (user_id, question_id))''')

    conn.commit()
    conn.close()
    print("Таблицы базы данных проверены/созданы")


def load_questions_from_fs():
    """Загружает вопросы из файловой системы в БД (очищает старые вопросы)"""
    conn = db_connect()
    cursor = conn.cursor()

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
        conn.close()
        return

    categories = ['typography', 'coloristics', 'composition', 'ux_principles', 'ui_patterns']
    total_loaded = 0

    for category in categories:
        category_path = os.path.join(questions_dir, category)
        print(f"Проверяем категорию: {category_path}")

        if os.path.exists(category_path):
            # Ищем все файлы (не только .txt)
            all_files = [f for f in os.listdir(category_path) if os.path.isfile(os.path.join(category_path, f))]
            # Исключаем файлы с известными расширениями изображений
            image_extensions = ['.png', '.jpg', '.jpeg', '.webp']
            question_files = [f for f in all_files if not any(f.endswith(ext) for ext in image_extensions)]

            print(f"Найдено файлов в {category}: {len(question_files)}")

            for file_name in question_files:
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

                    # Первая часть - вопрос и варианты ответов (весь текст до ;)
                    question_block = parts[0].strip()

                    # Остальные части
                    try:
                        buttons_count = int(parts[1].strip())
                    except ValueError:
                        print(f"❌ Ошибка в файле {file_name}: buttons_count должен быть числом")
                        continue

                    correct_option = parts[2].strip().lower()
                    explanation = parts[3].strip()

                    # Проверяем корректность correct_option
                    if correct_option not in ['a', 'b', 'c', 'd']:
                        print(f"❌ Ошибка в файле {file_name}: correct_option должен быть a, b, c или d")
                        continue

                    # Ищем изображение
                    base_name = os.path.splitext(file_path)[0]
                    image_path = None
                    for ext in ['.png', '.jpg', '.jpeg', '.webp']:
                        if os.path.exists(base_name + ext):
                            image_path = base_name + ext
                            break

                    # Сохраняем весь вопросный блок как есть
                    cursor.execute('''INSERT INTO questions 
                                   (category, question_text, image_path, option_a, option_b, option_c, option_d, buttons_count, correct_option, explanation)
                                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                                   (category, question_block, image_path, None, None, None, None,
                                    buttons_count, correct_option, explanation))

                    total_loaded += 1
                    print(f"✓ Загружен вопрос из файла: {file_name}")

                except Exception as e:
                    print(f"❌ Ошибка загрузки вопроса {file_name}: {e}")
                    import traceback
                    traceback.print_exc()
        else:
            print(f"❌ Папка категории {category} не найдена: {category_path}")

    conn.commit()
    conn.close()
    print(f"Вопросы успешно загружены! Всего: {total_loaded}")


def add_user(user_id, username):
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO users (user_id, username, current_topic, role) VALUES (?, ?, ?, ?)',
                   (user_id, username, 'typography', 'user'))
    conn.commit()
    conn.close()


def get_user_stats(user_id):
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT total_correct, current_topic, current_topic_progress, completed_topics, role FROM users WHERE user_id = ?',
        (user_id,))
    result = cursor.fetchone()
    conn.close()

    if result:
        return result
    else:
        # Если пользователя нет, создаем его
        add_user(user_id, "unknown")
        return (0, 'typography', 0, '', 'user')


def update_user_stats(user_id, correct):
    conn = db_connect()
    cursor = conn.cursor()
    if correct:
        cursor.execute('UPDATE users SET total_correct = total_correct + 1 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()


def get_questions_by_topic(user_id, topic, limit=5):
    """Получает вопросы по теме, которые пользователь еще не отвечал"""
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT question_id FROM questions 
        WHERE category = ? 
        AND question_id NOT IN (
            SELECT question_id FROM user_answered_questions WHERE user_id = ?
        )
        ORDER BY RANDOM() 
        LIMIT ?
    ''', (topic, user_id, limit))
    question_ids = [row[0] for row in cursor.fetchall()]
    conn.close()
    return question_ids


def get_question(question_id):
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM questions WHERE question_id = ?', (question_id,))
    question = cursor.fetchone()
    conn.close()
    return question


def get_next_topic(current_topic):
    """Возвращает следующую тему после текущей"""
    topics = ['typography', 'coloristics', 'composition', 'ux_principles', 'ui_patterns']
    try:
        current_index = topics.index(current_topic)
        if current_index + 1 < len(topics):
            return topics[current_index + 1]
        return None  # Все темы пройдены
    except ValueError:
        return 'typography'  # Если темы нет в списке, начинаем сначала


def update_user_topic_progress(user_id, topic, progress):
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET current_topic = ?, current_topic_progress = ? WHERE user_id = ?',
                   (topic, progress, user_id))
    conn.commit()
    conn.close()


def mark_topic_completed(user_id, topic):
    """Помечает тему как завершенную и обновляет прогресс"""
    conn = db_connect()
    cursor = conn.cursor()

    # Получаем текущий список завершенных тем
    cursor.execute('SELECT completed_topics FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    completed_topics = result[0] if result and result[0] else ''

    # Добавляем новую тему, если ее еще нет в списке
    if completed_topics:
        completed_list = completed_topics.split(',')
        if topic not in completed_list:
            completed_list.append(topic)
            completed_topics = ','.join(completed_list)
    else:
        completed_topics = topic

    # Обновляем запись пользователя
    cursor.execute('UPDATE users SET completed_topics = ? WHERE user_id = ?', (completed_topics, user_id))
    conn.commit()
    conn.close()


def get_questions_count_by_topic(topic):
    """Возвращает количество вопросов по теме"""
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM questions WHERE category = ?', (topic,))
    count = cursor.fetchone()[0]
    conn.close()
    return count


def get_all_users():
    """Возвращает список всех пользователей"""
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM users')
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    return users


def get_user_daily_progress(user_id):
    """Получает прогресс пользователя за сегодня"""
    conn = db_connect()
    cursor = conn.cursor()
    today = datetime.now().strftime('%Y-%m-%d')
    cursor.execute('SELECT questions_asked FROM daily_progress WHERE user_id = ? AND date = ?', (user_id, today))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else 0


def update_user_daily_progress(user_id):
    """Обновляет прогресс пользователя за сегодня"""
    conn = db_connect()
    cursor = conn.cursor()
    today = datetime.now().strftime('%Y-%m-%d')

    # Проверяем, есть ли запись на сегодня
    cursor.execute('SELECT 1 FROM daily_progress WHERE user_id = ? AND date = ?', (user_id, today))
    exists = cursor.fetchone()

    if exists:
        cursor.execute('UPDATE daily_progress SET questions_asked = questions_asked + 1 WHERE user_id = ? AND date = ?',
                       (user_id, today))
    else:
        cursor.execute('INSERT INTO daily_progress (user_id, date, questions_asked) VALUES (?, ?, 1)',
                       (user_id, today))

    conn.commit()
    conn.close()


def reset_daily_progress_if_needed():
    """Сбрасывает прогресс если наступил новый день"""
    conn = db_connect()
    cursor = conn.cursor()
    today = datetime.now().strftime('%Y-%m-%d')

    # Удаляем записи старше 1 дня
    cursor.execute('DELETE FROM daily_progress WHERE date != ?', (today,))
    conn.commit()
    conn.close()


def add_answered_question(user_id, question_id):
    """Добавляет вопрос в список отвеченных пользователем"""
    conn = db_connect()
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT OR IGNORE INTO user_answered_questions (user_id, question_id) VALUES (?, ?)',
                       (user_id, question_id))
        conn.commit()
    except:
        pass  # Уже существует
    finally:
        conn.close()


def get_user_answered_questions_count(user_id, topic):
    """Получает количество отвеченных вопросов по теме для пользователя"""
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT COUNT(*) FROM user_answered_questions uaq
        JOIN questions q ON uaq.question_id = q.question_id
        WHERE uaq.user_id = ? AND q.category = ?
    ''', (user_id, topic))
    count = cursor.fetchone()[0]
    conn.close()
    return count
