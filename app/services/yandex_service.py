"""
Сервис для работы с Yandex Cloud ML SDK
"""
import logging
import tempfile
import os
from datetime import datetime
from typing import Optional, Tuple, List
from yandex_cloud_ml_sdk import YCloudML
from yandex_cloud_ml_sdk.search_indexes import (
    StaticIndexChunkingStrategy,
    VectorSearchIndexType,
)

from app.config import get_settings

logger = logging.getLogger(__name__)

_sdk: Optional[YCloudML] = None
_current_vector_store_id: Optional[str] = None


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
    return bool(settings.YANDEX_FOLDER_ID and settings.YANDEX_API_KEY)


def get_vector_store_id() -> Optional[str]:
    """Получить текущий Vector Store ID из кэша"""
    global _current_vector_store_id
    return _current_vector_store_id if _current_vector_store_id else None


def set_vector_store_id(vector_store_id: str) -> None:
    """Установить текущий Vector Store ID в кэш"""
    global _current_vector_store_id
    _current_vector_store_id = vector_store_id if vector_store_id else None
    logger.info(f"✅ Vector Store ID set: {_current_vector_store_id}")


def generate_chat_name(message: str) -> str:
    """
    Генерирует красивое название чата на основе первого сообщения.

    Args:
        message: Первое сообщение пользователя

    Returns:
        Красивое название чата
    """
    sdk = get_sdk()

    prompt = f"""Сгенерируй короткое и красивое название для чата на основе сообщения пользователя.

Правила:
- Название должно быть на русском языке
- Максимум 5-6 слов
- Без кавычек и лишних символов
- Отражать суть вопроса/темы
- Начинаться с маленькой буквы

Примеры:
- "как выращивать огурцы" → выращивание огурцов
- "что такое любовь" → рассуждение о любви
- "помоги написать код на python" → помощь с кодом на Python
- "расскажи про квантовую физику" → основы квантовой физики

Сообщение пользователя: {message}

Название чата:"""

    try:
        model = sdk.models.completions("yandexgpt-lite")
        result = model.configure(temperature=0.3).run(prompt)

        chat_name = result.alternatives[0].text.strip()
        # Убираем кавычки если есть
        chat_name = chat_name.strip('"\'«»')

        if not chat_name or len(chat_name) > 100:
            chat_name = message[:50] if len(message) > 50 else message

        logger.info(f"✅ Generated chat name: {chat_name}")
        return chat_name

    except Exception as e:
        logger.warning(f"⚠️ Failed to generate chat name: {e}")
        # Fallback к старой логике
        return f"Чат: {message[:30]}..." if len(message) > 30 else f"Чат: {message}"


def create_new_chat() -> Tuple[str, str]:
    """Создать новый чат (thread + assistant)"""
    sdk = get_sdk()
    settings = get_settings()
    
    vector_store_id = get_vector_store_id()
    
    thread = sdk.threads.create()
    thread_id = thread.id
    
    # Если есть Vector Store — подключаем базу знаний
    if vector_store_id:
        search_tool = sdk.tools.search_index(vector_store_id)
        assistant = sdk.assistants.create(
            model="yandexgpt",
            instruction=settings.ASSISTANT_INSTRUCTION,
            tools=[search_tool],
        )
    else:
        # Без базы знаний
        assistant = sdk.assistants.create(
            model="yandexgpt",
            instruction=settings.ASSISTANT_INSTRUCTION,
        )
    
    assistant_id = assistant.id
    
    logger.info(f"✅ Created new chat: thread={thread_id}, has_kb={bool(vector_store_id)}")
    
    return thread_id, assistant_id


def send_message_and_get_response(
    thread_id: str, 
    assistant_id: str, 
    message: str
) -> Tuple[str, list]:
    """Отправить сообщение и получить ответ"""
    sdk = get_sdk()
    settings = get_settings()
    
    vector_store_id = get_vector_store_id()
    
    thread = sdk.threads.get(thread_id)
    thread.write(message)
    
    # Если есть Vector Store — подключаем базу знаний
    if vector_store_id:
        search_tool = sdk.tools.search_index(vector_store_id)
        assistant = sdk.assistants.create(
            model="yandexgpt",
            instruction=settings.ASSISTANT_INSTRUCTION,
            tools=[search_tool],
        )
    else:
        assistant = sdk.assistants.create(
            model="yandexgpt",
            instruction=settings.ASSISTANT_INSTRUCTION,
        )
    
    run = assistant.run(thread)
    result = run.wait()
    
    answer = result.text or "Извините, не смог сформировать ответ."
    
    citations = []
    if hasattr(result, "citations") and result.citations:
        for citation in result.citations:
            for source in citation.sources:
                if hasattr(source, "file") and hasattr(source.file, "id"):
                    citations.append({"file_id": source.file.id, "type": "file"})
    
    logger.info(f"📥 Got response ({len(answer)} chars), kb={bool(vector_store_id)}")
    
    return answer, citations


# ==========================================
# File Operations
# ==========================================

def upload_file_to_yandex(file_content: bytes, filename: str) -> str:
    """Загрузить файл в Yandex Cloud"""
    sdk = get_sdk()
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{filename}") as tmp_file:
        tmp_file.write(file_content)
        tmp_path = tmp_file.name
    
    try:
        file = sdk.files.upload(
            tmp_path,
            name=filename,
            ttl_days=365,
            expiration_policy="static"
        )
        logger.info(f"📤 File uploaded: {file.id}")
        return file.id
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def delete_file_from_yandex(file_id: str) -> bool:
    """Удалить файл из Yandex Cloud"""
    sdk = get_sdk()
    
    try:
        file = sdk.files.get(file_id)
        file.delete()
        logger.info(f"🗑️ File deleted: {file_id}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to delete file {file_id}: {e}")
        return False


def create_vector_store(yandex_file_ids: List[str]) -> str:
    """Создать новый Vector Store со списком файлов"""
    sdk = get_sdk()
    settings = get_settings()
    
    if not yandex_file_ids:
        raise ValueError("No files to index")
    
    files = []
    for file_id in yandex_file_ids:
        try:
            file = sdk.files.get(file_id)
            files.append(file)
        except Exception as e:
            logger.warning(f"⚠️ File {file_id} not found: {e}")
    
    if not files:
        raise ValueError("No valid files found")
    
    index_name = f"evoblast-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
    
    logger.info(f"🔄 Creating Vector Store: {index_name} with {len(files)} files...")
    
    operation = sdk.search_indexes.create_deferred(
        files=files,
        name=index_name,
        index_type=VectorSearchIndexType(
            doc_embedder_uri=f"emb://{settings.YANDEX_FOLDER_ID}/text-search-doc/latest",
            query_embedder_uri=f"emb://{settings.YANDEX_FOLDER_ID}/text-search-query/latest",
            chunking_strategy=StaticIndexChunkingStrategy(
                max_chunk_size_tokens=700,
                chunk_overlap_tokens=300,
            ),
        ),
        ttl_days=365,
        expiration_policy="static",
    )
    
    search_index = operation.wait()
    
    logger.info(f"✅ Vector Store created: {search_index.id}")
    return search_index.id


def delete_vector_store(index_id: str) -> bool:
    """Удалить Vector Store"""
    sdk = get_sdk()
    
    try:
        search_index = sdk.search_indexes.get(index_id)
        search_index.delete()
        logger.info(f"🗑️ Vector Store deleted: {index_id}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to delete Vector Store {index_id}: {e}")
        return False
