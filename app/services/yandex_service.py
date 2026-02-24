"""
Сервис для работы с Yandex Cloud AI.

Ручной RAG: vector_stores.search + completion API.
Отвечает ТОЛЬКО на основе базы знаний.
"""
import asyncio
import logging
import mimetypes
import os
from typing import Optional, List, Dict, Any, Tuple

import httpx
from openai import OpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)

# Клиенты
_openai_client: Optional[OpenAI] = None

# Приветствия и прощания
GREETINGS = {"привет", "здравствуй", "здравствуйте", "добрый день", "доброе утро", "добрый вечер", "хай", "hello", "hi"}
FAREWELLS = {"пока", "до свидания", "прощай", "bye", "goodbye"}
THANKS = {"спасибо", "благодарю", "thanks", "thank you"}

# Системный промпт для развёрнутых ответов
SYSTEM_PROMPT = """Ты профессиональный ассистент-эксперт. Твоя задача — давать РАЗВЁРНУТЫЕ, СТРУКТУРИРОВАННЫЕ и ПОЛЕЗНЫЕ ответы.

ПРАВИЛА ОТВЕТА:

1. ОБЪЁМ И СОДЕРЖАТЕЛЬНОСТЬ:
   - Давай подробные, развёрнутые ответы (минимум 300-500 слов, если тема позволяет)
   - Раскрывай тему полностью, не ограничивайся кратким пересказом
   - Добавляй практические рекомендации, где уместно
   - Выделяй ключевые моменты и риски

2. СТРУКТУРА И ФОРМАТИРОВАНИЕ:
   - Используй заголовки и подзаголовки для разделов
   - Применяй нумерованные списки для последовательностей действий
   - Применяй маркированные списки (•) для перечислений
   - Разделяй текст на логические абзацы
   - Оставляй пустые строки между разделами

3. ФОРМАТ ОТВЕТА:

   **Заголовок темы**

   Вводный абзац с общим описанием.

   **Подзаголовок 1**

   Текст раздела с подробностями.

   Ключевые аспекты:
   • пункт 1
   • пункт 2
   • пункт 3

   **Подзаголовок 2**

   Порядок действий:
   1. Первый шаг
   2. Второй шаг
   3. Третий шаг

   **Рекомендации**

   Практические советы по теме.

4. РАБОТА С ТЕКСТАМИ:
   - Если пользователь просит проверить текст на ошибки (технические, грамматические, стилистические) — выполни проверку полностью
   - Перечисли ВСЕ найденные ошибки с указанием, где они находятся и в чём заключаются
   - Предложи конкретные исправления для каждой ошибки
   - Если пользователь просит написать или переработать текст — выполни запрос, предоставив готовый результат

5. ИСПОЛЬЗОВАНИЕ БАЗЫ ЗНАНИЙ:
   - Если предоставлена база знаний — используй её для ответа
   - Если база знаний пуста или не содержит релевантной информации — отвечай на основе своих знаний
   - НЕ выдумывай факты

БАЗА ЗНАНИЙ:

"""


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
# Обработка приветствий
# ==========================================

# Максимальное количество слов для детекции приветствий/прощаний.
# Сообщения длиннее этого порога считаются содержательными запросами.
_MAX_GREETING_WORDS = 5


def is_greeting(text: str) -> bool:
    text_lower = text.lower().strip()
    if len(text_lower.split()) > _MAX_GREETING_WORDS:
        return False
    return text_lower in GREETINGS


def is_farewell(text: str) -> bool:
    text_lower = text.lower().strip()
    if len(text_lower.split()) > _MAX_GREETING_WORDS:
        return False
    return text_lower in FAREWELLS


def is_thanks(text: str) -> bool:
    text_lower = text.lower().strip()
    if len(text_lower.split()) > _MAX_GREETING_WORDS:
        return False
    return text_lower in THANKS


def get_greeting_response(text: str) -> Optional[str]:
    """Получить ответ на приветствие/прощание/благодарность"""
    if is_greeting(text):
        return "Здравствуйте! Я ассистент по базе знаний. Задайте мне вопрос по загруженным документам, и я дам вам развёрнутый структурированный ответ."
    if is_farewell(text):
        return "До свидания! Буду рад помочь снова."
    if is_thanks(text):
        return "Пожалуйста! Если есть ещё вопросы по базе знаний — спрашивайте."
    return None


# ==========================================
# RAG Pipeline (синхронные версии)
# ==========================================

def _search_index_sync(query: str, max_results: int = 10) -> List[str]:
    """Поиск по vector store"""
    client = get_openai_client()
    settings = get_settings()
    index_id = settings.SEARCH_INDEX_ID

    if not index_id:
        logger.warning("⚠️ SEARCH_INDEX_ID not configured")
        return []

    try:
        results = client.vector_stores.search(index_id, query=query)
        chunks = []

        for r in results:
            if hasattr(r, 'content'):
                for content in r.content:
                    if hasattr(content, 'text') and content.text:
                        chunks.append(content.text)
            elif hasattr(r, 'text') and r.text:
                chunks.append(r.text)

        logger.info(f"🔍 Search found {len(chunks)} chunks")
        return chunks[:max_results]

    except Exception as e:
        logger.error(f"❌ Search error: {e}")
        return []


def _check_relevance_sync(question: str, chunks: List[str]) -> bool:
    """Проверяет релевантность через LLM"""
    if not chunks:
        return False

    settings = get_settings()

    check_prompt = f"""Оцени, содержит ли текст из базы знаний информацию для ответа на вопрос.

ВОПРОС: {question}

ТЕКСТ ИЗ БАЗЫ:
{chunks[0][:500]}

Ответь ОДНИМ словом: ДА или НЕТ"""

    try:
        response = httpx.post(
            "https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
            headers={
                "Authorization": f"Api-Key {settings.YANDEX_API_KEY}",
                "x-folder-id": settings.YANDEX_FOLDER_ID,
                "Content-Type": "application/json"
            },
            json={
                "modelUri": f"gpt://{settings.YANDEX_FOLDER_ID}/yandexgpt-lite/latest",
                "completionOptions": {
                    "stream": False,
                    "temperature": 0.0,
                    "maxTokens": 10
                },
                "messages": [{"role": "user", "text": check_prompt}]
            },
            timeout=30.0
        )

        if response.status_code == 200:
            answer = response.json()["result"]["alternatives"][0]["message"]["text"].strip().upper()
            is_relevant = "ДА" in answer
            logger.info(f"🎯 Relevance check: {is_relevant}")
            return is_relevant

    except Exception as e:
        logger.warning(f"⚠️ Relevance check failed: {e}")

    return True  # По умолчанию считаем релевантным


def _generate_answer_sync(question: str, context: str, history: List[Dict[str, str]]) -> str:
    """Генерация развёрнутого ответа через REST API"""
    settings = get_settings()

    system_text = SYSTEM_PROMPT
    if context:
        system_text += context
    else:
        system_text += "(пусто)"

    messages = [{"role": "system", "text": system_text}]

    # Добавляем историю
    for msg in history:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        messages.append({"role": role, "text": content})

    # Добавляем текущий вопрос
    messages.append({"role": "user", "text": question})

    response = httpx.post(
        "https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
        headers={
            "Authorization": f"Api-Key {settings.YANDEX_API_KEY}",
            "x-folder-id": settings.YANDEX_FOLDER_ID,
            "Content-Type": "application/json"
        },
        json={
            "modelUri": f"gpt://{settings.YANDEX_FOLDER_ID}/yandexgpt/latest",
            "completionOptions": {
                "stream": False,
                "temperature": 0.3,
                "maxTokens": 8000
            },
            "messages": messages
        },
        timeout=120.0
    )

    if response.status_code != 200:
        raise Exception(f"API error {response.status_code}: {response.text}")

    data = response.json()
    answer = data["result"]["alternatives"][0]["message"]["text"]
    logger.info(f"📥 Generated answer: {len(answer)} chars")
    return answer


def _is_direct_task(text: str) -> bool:
    """Определяет, является ли сообщение прямой задачей (проверка текста, написание и т.д.),
    которая не требует поиска по базе знаний."""
    text_lower = text.lower().strip()
    task_keywords = [
        "проверь", "проверить", "исправь", "исправить",
        "перепиши", "переписать", "напиши", "написать",
        "отредактируй", "отредактировать", "переработай", "переработать",
        "сократи", "сократить", "дополни", "дополнить",
        "переведи", "перевести", "улучши", "улучшить",
    ]
    # Проверяем только начало сообщения (первые 100 символов)
    start = text_lower[:100]
    return any(kw in start for kw in task_keywords)


def _rag_pipeline_sync(question: str, history: List[Dict[str, str]]) -> Tuple[str, List[str]]:
    """
    Полный RAG pipeline.
    Возвращает (ответ, список использованных chunks)
    """
    # 1. Проверка на приветствие
    greeting_response = get_greeting_response(question)
    if greeting_response:
        return greeting_response, []

    # 2. Проверка на прямую задачу (проверка/написание текста)
    #    В этом случае отправляем запрос в LLM без поиска по базе знаний
    if _is_direct_task(question):
        logger.info("📝 Direct task detected, skipping knowledge base search")
        answer = _generate_answer_sync(question, "", history)
        return answer, []

    # 3. Поиск по базе знаний
    chunks = _search_index_sync(question, max_results=10)

    if not chunks:
        # Если база знаний пуста — всё равно пробуем ответить через LLM
        logger.info("📭 No chunks found, generating answer without knowledge base")
        answer = _generate_answer_sync(question, "", history)
        return answer, []

    # 4. Проверка релевантности
    if not _check_relevance_sync(question, chunks):
        # Нерелевантные чанки — отвечаем без контекста базы знаний
        logger.info("🔀 Chunks not relevant, generating answer without knowledge base")
        answer = _generate_answer_sync(question, "", history)
        return answer, []

    # 5. Формируем контекст
    context = "\n\n---\n\n".join(chunks)

    # 6. Генерация ответа
    answer = _generate_answer_sync(question, context, history)

    return answer, chunks


def _generate_chat_name_sync(message: str) -> str:
    """Генерация названия чата через LLM"""
    settings = get_settings()

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
- "привет" → приветствие

Сообщение пользователя: {message}

Название чата:"""

    try:
        response = httpx.post(
            "https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
            headers={
                "Authorization": f"Api-Key {settings.YANDEX_API_KEY}",
                "x-folder-id": settings.YANDEX_FOLDER_ID,
                "Content-Type": "application/json"
            },
            json={
                "modelUri": f"gpt://{settings.YANDEX_FOLDER_ID}/yandexgpt-lite/latest",
                "completionOptions": {
                    "stream": False,
                    "temperature": 0.3,
                    "maxTokens": 50
                },
                "messages": [{"role": "user", "text": prompt}]
            },
            timeout=30.0
        )

        if response.status_code == 200:
            chat_name = response.json()["result"]["alternatives"][0]["message"]["text"].strip()
            chat_name = chat_name.strip('"\'«»')

            if not chat_name or len(chat_name) > 100:
                chat_name = message[:50] if len(message) > 50 else message

            logger.info(f"✅ Generated chat name: {chat_name}")
            return chat_name

    except Exception as e:
        logger.warning(f"⚠️ Failed to generate chat name: {e}")

    return f"Чат: {message[:30]}..." if len(message) > 30 else f"Чат: {message}"


# ==========================================
# Файловые операции (OpenAI-совместимый API)
# ==========================================

def _upload_file_and_add_to_index_sync(file_content: bytes, filename: str) -> str:
    """Загрузка файла в storage и добавление в индекс"""
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
    """Удаление файла из индекса и storage"""
    client = get_openai_client()
    settings = get_settings()
    index_id = settings.SEARCH_INDEX_ID

    if not index_id:
        logger.warning("⚠️ SEARCH_INDEX_ID not configured, skipping index removal")
    else:
        try:
            client.vector_stores.files.delete(file_id, vector_store_id=index_id)
            logger.info(f"🗑️ File removed from index: {file_id}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to remove file from index: {e}")

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
# Асинхронные обёртки (публичный API)
# ==========================================

# RAG операции
async def rag_pipeline(question: str, history: List[Dict[str, str]]) -> Tuple[str, List[str]]:
    """Полный RAG pipeline: поиск + проверка релевантности + генерация"""
    return await asyncio.to_thread(_rag_pipeline_sync, question, history)


async def generate_chat_name(message: str) -> str:
    """Генерирует красивое название чата"""
    return await asyncio.to_thread(_generate_chat_name_sync, message)


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
