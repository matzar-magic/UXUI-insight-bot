import os
from dotenv import load_dotenv

# Загружаем переменные окружения из файла .env
load_dotenv()


class Config:
    def __init__(self):
        self.TOKEN = os.getenv('BOT_TOKEN')
        self.CHANNEL_ID = os.getenv('CHANNEL_ID')
        self.ADMIN_ID = os.getenv('ADMIN_ID')  # Добавляем ADMIN_ID

        if not self.TOKEN:
            raise ValueError("Токен бота не найден! Убедитесь, что он указан в .env файле.")

        if not self.CHANNEL_ID:
            raise ValueError("CHANNEL_ID не найден! Убедитесь, что он указан в .env файле.")

        if not self.ADMIN_ID:
            raise ValueError("ADMIN_ID не найден! Убедитесь, что он указан в .env файле.")


def load_config():
    return Config()
