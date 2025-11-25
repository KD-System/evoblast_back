"""
Конфигурация приложения
"""
import os
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Настройки приложения"""
    
    # Project
    PROJECT_NAME: str = "evoblast"
    DEBUG: bool = False
    
    # MongoDB
    MONGODB_URL: str = "mongodb://mongodb:27017"
    MONGODB_DATABASE: str = "evoblast_db"
    
    # Yandex Cloud
    YANDEX_FOLDER_ID: str = ""
    YANDEX_API_KEY: str = ""
    VECTOR_STORE_ID: str = ""
    
    # Assistant settings
    ASSISTANT_INSTRUCTION: str = """Ты - полезный помощник компании.

Правила работы:
1. Если вопрос касается компании, её продуктов, цен или контактов - используй базу знаний
2. На общие вопросы отвечай своими знаниями
3. Отвечай кратко и по делу
4. Всегда будь вежливым и профессиональным
"""
    
    class Config:
        env_file = ".env"
        extra = "allow"


@lru_cache()
def get_settings() -> Settings:
    """Получить настройки (с кэшированием)"""
    return Settings()
