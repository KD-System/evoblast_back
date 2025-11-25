"""
Сервис для работы с Yandex Cloud ML SDK
"""
import logging
from typing import Optional, Tuple
from yandex_cloud_ml_sdk import YCloudML

from app.config import get_settings

logger = logging.getLogger(__name__)

# Глобальный SDK клиент
_sdk: Optional[YCloudML] = None


def get_sdk() -> YCloudML:
    """Получить инициализированный SDK"""
    global _sdk
    
    if _sdk is None:
        settings = get_settings()
        
        if not settings.YANDEX_FOLDER_ID:
            raise RuntimeError("YANDEX_FOLDER_ID not configured")
        
        if not settings.YANDEX_API_KEY:
            raise RuntimeError("YANDEX_API_KEY not configured")
        
        _sdk = YCloudML(
            folder_id=settings.YANDEX_FOLDER_ID,
            auth=settings.YANDEX_API_KEY
        )
        logger.info("✅ Yandex Cloud ML SDK initialized")
    
    return _sdk


def is_configured() -> bool:
    """Проверить, настроен ли Yandex Cloud"""
    settings = get_settings()
    return bool(
        settings.YANDEX_FOLDER_ID and 
        settings.YANDEX_API_KEY and 
        settings.VECTOR_STORE_ID
    )


def create_thread() -> str:
    """Создать новый поток (thread) для беседы"""
    sdk = get_sdk()
    thread = sdk.threads.create()
    logger.info(f"✅ Created new thread: {thread.id}")
    return thread.id


def get_thread(thread_id: str):
    """Получить существующий поток"""
    sdk = get_sdk()
    return sdk.threads.get(thread_id)


def create_assistant() -> str:
    """Создать ассистента с подключённой базой знаний"""
    sdk = get_sdk()
    settings = get_settings()
    
    # Подключаем векторное хранилище
    search_tool = sdk.tools.search_index(settings.VECTOR_STORE_ID)
    
    # Создаём ассистента
    assistant = sdk.assistants.create(
        model="yandexgpt",
        instruction=settings.ASSISTANT_INSTRUCTION,
        tools=[search_tool],
    )
    
    logger.info(f"✅ Created assistant: {assistant.id}")
    return assistant.id


def get_assistant(assistant_id: str):
    """Получить существующего ассистента"""
    sdk = get_sdk()
    return sdk.assistants.get(assistant_id)


def send_message_and_get_response(
    thread_id: str, 
    assistant_id: str, 
    message: str
) -> Tuple[str, list]:
    """
    Отправить сообщение и получить ответ от ассистента
    
    Returns:
        Tuple[str, list]: (ответ, список цитат)
    """
    sdk = get_sdk()
    settings = get_settings()
    
    # Получаем thread
    thread = sdk.threads.get(thread_id)
    
    # Отправляем сообщение
    thread.write(message)
    logger.info(f"📤 Message sent to thread: {thread_id}")
    
    # Получаем или создаём ассистента
    # Примечание: создаём нового ассистента для каждого запроса,
    # чтобы гарантировать актуальные настройки
    search_tool = sdk.tools.search_index(settings.VECTOR_STORE_ID)
    assistant = sdk.assistants.create(
        model="yandexgpt",
        instruction=settings.ASSISTANT_INSTRUCTION,
        tools=[search_tool],
    )
    
    # Запускаем ассистента и ждём ответ
    run = assistant.run(thread)
    result = run.wait()
    
    # Извлекаем ответ
    answer = result.text or "Извините, не смог сформировать ответ."
    
    # Извлекаем цитаты (если есть)
    citations = []
    if hasattr(result, "citations") and result.citations:
        for citation in result.citations:
            for source in citation.sources:
                if hasattr(source, "file") and hasattr(source.file, "id"):
                    citations.append({
                        "file_id": source.file.id,
                        "type": "file"
                    })
    
    logger.info(f"📥 Got response from assistant ({len(answer)} chars, {len(citations)} citations)")
    
    return answer, citations


def create_new_chat() -> Tuple[str, str]:
    """
    Создать новый чат (thread + assistant)
    
    Returns:
        Tuple[str, str]: (thread_id, assistant_id)
    """
    sdk = get_sdk()
    settings = get_settings()
    
    # Создаём поток
    thread = sdk.threads.create()
    thread_id = thread.id
    
    # Создаём ассистента
    search_tool = sdk.tools.search_index(settings.VECTOR_STORE_ID)
    assistant = sdk.assistants.create(
        model="yandexgpt",
        instruction=settings.ASSISTANT_INSTRUCTION,
        tools=[search_tool],
    )
    assistant_id = assistant.id
    
    logger.info(f"✅ Created new chat: thread={thread_id}, assistant={assistant_id}")
    
    return thread_id, assistant_id
