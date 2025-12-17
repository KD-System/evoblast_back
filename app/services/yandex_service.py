"""
Сервис для работы с Yandex Cloud ML SDK (асинхронная версия)
"""
import asyncio
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


# ==========================================
# Синхронные версии (для asyncio.to_thread)
# ==========================================

def _generate_chat_name_sync(message: str) -> str:
    """Синхронная генерация названия чата"""
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
        chat_name = chat_name.strip('"\'«»')

        if not chat_name or len(chat_name) > 100:
            chat_name = message[:50] if len(message) > 50 else message

        logger.info(f"✅ Generated chat name: {chat_name}")
        return chat_name

    except Exception as e:
        logger.warning(f"⚠️ Failed to generate chat name: {e}")
        return f"Чат: {message[:30]}..." if len(message) > 30 else f"Чат: {message}"


def _create_new_chat_sync() -> Tuple[str, str]:
    """Синхронное создание нового чата"""
    sdk = get_sdk()
    settings = get_settings()

    vector_store_id = get_vector_store_id()

    thread = sdk.threads.create()
    thread_id = thread.id

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

    assistant_id = assistant.id

    logger.info(f"✅ Created new chat: thread={thread_id}, has_kb={bool(vector_store_id)}")

    return thread_id, assistant_id


def _send_message_and_get_response_sync(
    thread_id: str,
    assistant_id: str,
    message: str
) -> Tuple[str, list]:
    """Синхронная отправка сообщения"""
    sdk = get_sdk()
    settings = get_settings()

    vector_store_id = get_vector_store_id()

    thread = sdk.threads.get(thread_id)
    thread.write(message)

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

    answer = (result.text or "Извините, не смог сформировать ответ.").replace("*", "")

    citations = []
    if hasattr(result, "citations") and result.citations:
        for citation in result.citations:
            for source in citation.sources:
                if hasattr(source, "file") and hasattr(source.file, "id"):
                    citations.append({"file_id": source.file.id, "type": "file"})

    logger.info(f"📥 Got response ({len(answer)} chars), kb={bool(vector_store_id)}")

    return answer, citations


def _upload_file_to_yandex_sync(file_content: bytes, filename: str) -> str:
    """Синхронная загрузка файла"""
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


def _delete_file_from_yandex_sync(file_id: str) -> bool:
    """Синхронное удаление файла"""
    sdk = get_sdk()

    try:
        file = sdk.files.get(file_id)
        file.delete()
        logger.info(f"🗑️ File deleted: {file_id}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to delete file {file_id}: {e}")
        return False


def _download_file_from_yandex_sync(file_id: str) -> bytes:
    """Синхронное скачивание файла из Yandex Cloud"""
    sdk = get_sdk()

    try:
        file = sdk.files.get(file_id)
        # Скачиваем во временный файл и читаем
        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            tmp_path = tmp_file.name

        file.download(tmp_path)

        with open(tmp_path, 'rb') as f:
            content = f.read()

        if os.path.exists(tmp_path):
            os.remove(tmp_path)

        logger.info(f"📥 File downloaded: {file_id} ({len(content)} bytes)")
        return content

    except Exception as e:
        logger.error(f"❌ Failed to download file {file_id}: {e}")
        raise


def _create_vector_store_sync(yandex_file_ids: List[str]) -> str:
    """Синхронное создание Vector Store с таймаутом и логированием прогресса"""
    import time

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

    try:
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

        logger.info(f"📋 Operation started: {operation.id}")

        # Ручной polling с логированием прогресса (таймаут 5 минут)
        timeout_seconds = 300
        poll_interval = 10
        elapsed = 0

        while elapsed < timeout_seconds:
            if operation.done:
                break

            logger.info(f"⏳ Vector Store indexing... ({elapsed}s / {timeout_seconds}s)")
            time.sleep(poll_interval)
            elapsed += poll_interval

        if not operation.done:
            logger.error(f"❌ Vector Store creation timed out after {timeout_seconds}s")
            raise TimeoutError(f"Vector Store creation timed out after {timeout_seconds} seconds")

        # Получаем результат
        search_index = operation.result

        if search_index is None:
            # Попробуем получить ошибку
            logger.error(f"❌ Vector Store creation failed: operation completed but no result")
            raise RuntimeError("Vector Store creation failed - no result returned")

        logger.info(f"✅ Vector Store created: {search_index.id}")
        return search_index.id

    except TimeoutError:
        raise
    except Exception as e:
        logger.error(f"❌ Vector Store creation error: {e}", exc_info=True)
        raise


def _delete_vector_store_sync(index_id: str) -> bool:
    """Синхронное удаление Vector Store"""
    sdk = get_sdk()

    try:
        search_index = sdk.search_indexes.get(index_id)
        search_index.delete()
        logger.info(f"🗑️ Vector Store deleted: {index_id}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to delete Vector Store {index_id}: {e}")
        return False


# ==========================================
# Асинхронные обёртки (публичный API)
# ==========================================

async def generate_chat_name(message: str) -> str:
    """Генерирует красивое название чата на основе первого сообщения"""
    return await asyncio.to_thread(_generate_chat_name_sync, message)


async def create_new_chat() -> Tuple[str, str]:
    """Создать новый чат (thread + assistant)"""
    return await asyncio.to_thread(_create_new_chat_sync)


async def send_message_and_get_response(
    thread_id: str,
    assistant_id: str,
    message: str
) -> Tuple[str, list]:
    """Отправить сообщение и получить ответ"""
    return await asyncio.to_thread(
        _send_message_and_get_response_sync,
        thread_id,
        assistant_id,
        message
    )


async def upload_file_to_yandex(file_content: bytes, filename: str) -> str:
    """Загрузить файл в Yandex Cloud"""
    return await asyncio.to_thread(_upload_file_to_yandex_sync, file_content, filename)


async def delete_file_from_yandex(file_id: str) -> bool:
    """Удалить файл из Yandex Cloud"""
    return await asyncio.to_thread(_delete_file_from_yandex_sync, file_id)


async def download_file_from_yandex(file_id: str) -> bytes:
    """Скачать файл из Yandex Cloud"""
    return await asyncio.to_thread(_download_file_from_yandex_sync, file_id)


async def create_vector_store(yandex_file_ids: List[str]) -> str:
    """Создать новый Vector Store со списком файлов"""
    return await asyncio.to_thread(_create_vector_store_sync, yandex_file_ids)


async def delete_vector_store(index_id: str) -> bool:
    """Удалить Vector Store"""
    return await asyncio.to_thread(_delete_vector_store_sync, index_id)
