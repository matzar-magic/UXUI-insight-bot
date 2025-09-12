import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    def __init__(self):
        self.TOKEN = os.getenv('BOT_TOKEN')
        self.CHANNEL_ID = os.getenv('CHANNEL_ID')
        self.ADMIN_ID = os.getenv('ADMIN_ID')

        # MySQL настройки
        self.DB_HOST = os.getenv('DB_HOST')
        self.DB_NAME = os.getenv('DB_NAME')
        self.DB_USER = os.getenv('DB_USER')
        self.DB_PASSWORD = os.getenv('DB_PASSWORD')
        self.DB_PORT = int(os.getenv('DB_PORT', 3306))

        # Проверяем обязательные переменные
        required_vars = {
            'BOT_TOKEN': self.TOKEN,
            'CHANNEL_ID': self.CHANNEL_ID,
            'ADMIN_ID': self.ADMIN_ID,
            'DB_HOST': self.DB_HOST,
            'DB_NAME': self.DB_NAME,
            'DB_USER': self.DB_USER,
            'DB_PASSWORD': self.DB_PASSWORD
        }

        missing_vars = [var for var, value in required_vars.items() if not value]
        if missing_vars:
            raise ValueError(f"Отсутствуют переменные окружения: {', '.join(missing_vars)}")


def load_config():
    return Config()
