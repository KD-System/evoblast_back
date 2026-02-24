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
    
    # JWT Auth
    SECRET_KEY: str = "d1d056b1dd445cd0141908cee6126173ebf80c056f2cf671efa16db794bc3498"
    ALGORITHM: str = "HS256"
    
    # MongoDB
    MONGODB_URL: str = "mongodb://mongodb:27017"
    MONGODB_DATABASE: str = "evoblast_db"
    
    # Yandex Cloud
    YANDEX_FOLDER_ID: str = ""
    YANDEX_API_KEY: str = ""
    SEARCH_INDEX_ID: str = ""  # Фиксированный ID поискового индекса
    YANDEX_API_BASE_URL: str = "https://rest-assistant.api.cloud.yandex.net/v1"
    
    # Assistant settings
    ASSISTANT_INSTRUCTION: str = """Ты - полезный помощник компании.

Правила работы:
1. Если вопрос касается компании, её продуктов, цен или контактов - используй базу знаний
2. На общие вопросы отвечай своими знаниями
3. Давай развёрнутые, подробные ответы — раскрывай тему полностью
4. Всегда будь вежливым и профессиональным
5. Если пользователь просит проверить текст на ошибки (технические, грамматические, стилистические) — выполни проверку, укажи найденные ошибки и предложи исправления
6. Если пользователь просит написать или переработать текст — выполни запрос, предоставив готовый результат

Форматирование ответов:
- Используй [br] для переноса строки
- Используй [br][br] для разделения абзацев (пустая строка)
- Структурируй ответы: заголовки, списки, абзацы
"""
    
    class Config:
        env_file = ".env"
        extra = "allow"


@lru_cache()
def get_settings() -> Settings:
    """Получить настройки (с кэшированием)"""
    return Settings()
