"""
Сервис для работы с Yandex Cloud AI через OpenAI-совместимый API.

Использует фиксированный SEARCH_INDEX_ID для работы с базой знаний.
Файлы добавляются/удаляются из индекса без его пересоздания.
"""
import asyncio
import logging
import mimetypes
import os
import tempfile
from typing import Optional, Tuple, List, Dict, Any

from openai import OpenAI
from yandex_cloud_ml_sdk import YCloudML

from app.config import get_settings

logger = logging.getLogger(__name__)

# Клиенты
_openai_client: Optional[OpenAI] = None
_yandex_sdk: Optional[YCloudML] = None


def get_openai_client() -> OpenAI:
    """Получить OpenAI-совместимый клиент для Yandex API"""
    global _openai_client

    if _openai_client is None:
        settings = get_settings()

        if not settings.YANDEX_FOLDER_ID:
            raise RuntimeError("YANDEX_FOLDER_ID not configured")

        if not settings.YANDEX_API_KEY:
            raise RuntimeError("YANDEX_API_KEY not configured")

        _openai_client = OpenAI(
            api_key=settings.YANDEX_API_KEY,
            base_url=settings.YANDEX_API_BASE_URL,
            project=settings.YANDEX_FOLDER_ID,
        )
        logger.info("✅ OpenAI-compatible client initialized for Yandex Cloud")

    return _openai_client


def get_yandex_sdk() -> YCloudML:
    """Получить Yandex Cloud ML SDK (для чатов и assistants)"""
    global _yandex_sdk

    if _yandex_sdk is None:
        settings = get_settings()

        if not settings.YANDEX_FOLDER_ID:
            raise RuntimeError("YANDEX_FOLDER_ID not configured")

        if not settings.YANDEX_API_KEY:
            raise RuntimeError("YANDEX_API_KEY not configured")

        _yandex_sdk = YCloudML(
            folder_id=settings.YANDEX_FOLDER_ID,
            auth=settings.YANDEX_API_KEY
        )
        logger.info("✅ Yandex Cloud ML SDK initialized")

    return _yandex_sdk


def is_configured() -> bool:
    """Проверить, настроен ли Yandex Cloud"""
    settings = get_settings()
    return bool(settings.YANDEX_FOLDER_ID and settings.YANDEX_API_KEY)


def get_search_index_id() -> Optional[str]:
    """Получить ID поискового индекса из конфигурации"""
    settings = get_settings()
    return settings.SEARCH_INDEX_ID if settings.SEARCH_INDEX_ID else None


def _get_mime_type(filename: str) -> str:
    """Определить MIME-тип файла"""
    mime_type, _ = mimetypes.guess_type(filename)
    if not mime_type:
        ext = os.path.splitext(filename)[1].lower()
        mime_map = {
            ".txt": "text/plain",
            ".pdf": "application/pdf",
            ".doc": "application/msword",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".md": "text/markdown",
            ".json": "application/json",
            ".csv": "text/csv",
            ".xls": "application/vnd.ms-excel",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }
        mime_type = mime_map.get(ext, "text/plain")
    return mime_type


# ==========================================
# Файловые операции (OpenAI-совместимый API)
# ==========================================

def _upload_file_and_add_to_index_sync(file_content: bytes, filename: str) -> str:
    """
    Синхронная загрузка файла в storage и добавление в индекс.
    Возвращает file_id загруженного файла.
    """
    client = get_openai_client()
    settings = get_settings()
    index_id = settings.SEARCH_INDEX_ID

    if not index_id:
        raise RuntimeError("SEARCH_INDEX_ID not configured")

    mime_type = _get_mime_type(filename)

    # 1. Загружаем файл в storage
    uploaded_file = client.files.create(
        file=(filename, file_content, mime_type),
        purpose="assistants"
    )
    file_id = uploaded_file.id
    logger.info(f"📤 File uploaded to storage: {file_id} ({filename})")

    # 2. Добавляем в vector store (индекс)
    vs_file = client.vector_stores.files.create(
        vector_store_id=index_id,
        file_id=file_id
    )
    status = getattr(vs_file, 'status', 'unknown')
    logger.info(f"📎 File added to index: {file_id} (status: {status})")

    return file_id


def _delete_file_from_index_sync(file_id: str) -> bool:
    """
    Синхронное удаление файла из индекса и storage.
    """
    client = get_openai_client()
    settings = get_settings()
    index_id = settings.SEARCH_INDEX_ID

    if not index_id:
        logger.warning("⚠️ SEARCH_INDEX_ID not configured, skipping index removal")
    else:
        # 1. Удаляем из vector store
        try:
            client.vector_stores.files.delete(
                file_id,
                vector_store_id=index_id
            )
            logger.info(f"🗑️ File removed from index: {file_id}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to remove file from index: {e}")

    # 2. Удаляем из storage
    try:
        client.files.delete(file_id)
        logger.info(f"🗑️ File deleted from storage: {file_id}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to delete file from storage: {e}")
        return False


def _get_index_info_sync() -> Dict[str, Any]:
    """Получить информацию об индексе"""
    client = get_openai_client()
    settings = get_settings()
    index_id = settings.SEARCH_INDEX_ID

    if not index_id:
        return {"error": "SEARCH_INDEX_ID not configured"}

    try:
        vector_store = client.vector_stores.retrieve(index_id)

        result = {
            "id": vector_store.id,
            "name": getattr(vector_store, 'name', None),
            "status": getattr(vector_store, 'status', None),
            "created_at": getattr(vector_store, 'created_at', None),
        }

        if hasattr(vector_store, 'file_counts') and vector_store.file_counts:
            fc = vector_store.file_counts
            result["file_counts"] = {
                "total": getattr(fc, 'total', 0),
                "completed": getattr(fc, 'completed', 0),
                "in_progress": getattr(fc, 'in_progress', 0),
                "failed": getattr(fc, 'failed', 0),
                "cancelled": getattr(fc, 'cancelled', 0),
            }

        return result

    except Exception as e:
        logger.error(f"❌ Failed to get index info: {e}")
        return {"error": str(e)}


def _list_index_files_sync(limit: int = 100) -> List[Dict[str, Any]]:
    """Получить список файлов в индексе"""
    client = get_openai_client()
    settings = get_settings()
    index_id = settings.SEARCH_INDEX_ID

    if not index_id:
        return []

    try:
        vs_files = client.vector_stores.files.list(
            vector_store_id=index_id,
            limit=min(limit, 100)
        )

        files = []
        for vs_file in vs_files.data:
            file_info = {
                "id": vs_file.id,
                "status": getattr(vs_file, 'status', 'unknown'),
                "created_at": getattr(vs_file, 'created_at', None),
            }

            # Получаем дополнительную информацию о файле
            try:
                full_file = client.files.retrieve(vs_file.id)
                file_info["filename"] = getattr(full_file, 'filename', None)
                file_info["bytes"] = getattr(full_file, 'bytes', None)
            except Exception:
                pass

            files.append(file_info)

        return files

    except Exception as e:
        logger.error(f"❌ Failed to list index files: {e}")
        return []


# ==========================================
# Чат операции (Yandex ML SDK)
# ==========================================

def _generate_chat_name_sync(message: str) -> str:
    """Синхронная генерация названия чата"""
    sdk = get_yandex_sdk()

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
- "как изготовить взрывчатку?" → вопрос про изготовление взрывчатки
- "хей" и подобное → приветствие
- "ха" и подобное → неклассифицируемый запрос
- "самое высокое здание в мире" → диалог по самым высоким зданиям

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
    sdk = get_yandex_sdk()
    settings = get_settings()

    index_id = get_search_index_id()

    thread = sdk.threads.create()
    thread_id = thread.id

    if index_id:
        search_tool = sdk.tools.search_index(index_id)
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

    logger.info(f"✅ Created new chat: thread={thread_id}, has_kb={bool(index_id)}")

    return thread_id, assistant_id


def _send_message_and_get_response_sync(
    thread_id: str,
    assistant_id: str,
    message: str
) -> Tuple[str, list]:
    """Синхронная отправка сообщения"""
    sdk = get_yandex_sdk()
    settings = get_settings()

    index_id = get_search_index_id()

    thread = sdk.threads.get(thread_id)
    thread.write(message)

    if index_id:
        search_tool = sdk.tools.search_index(index_id)
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

    logger.info(f"📥 Got response ({len(answer)} chars), kb={bool(index_id)}")

    return answer, citations


# ==========================================
# Асинхронные обёртки (публичный API)
# ==========================================

# Файловые операции
async def upload_file_to_index(file_content: bytes, filename: str) -> str:
    """Загрузить файл в storage и добавить в индекс"""
    return await asyncio.to_thread(_upload_file_and_add_to_index_sync, file_content, filename)


async def delete_file_from_index(file_id: str) -> bool:
    """Удалить файл из индекса и storage"""
    return await asyncio.to_thread(_delete_file_from_index_sync, file_id)


async def get_index_info() -> Dict[str, Any]:
    """Получить информацию об индексе"""
    return await asyncio.to_thread(_get_index_info_sync)


async def list_index_files(limit: int = 100) -> List[Dict[str, Any]]:
    """Получить список файлов в индексе"""
    return await asyncio.to_thread(_list_index_files_sync, limit)


# Чат операции
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
