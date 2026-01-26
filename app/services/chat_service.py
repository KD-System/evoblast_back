"""
Сервис бизнес-логики чата.

Использует ручной RAG: история из MongoDB + поиск + генерация.
"""
import logging
import uuid
from typing import Dict, Any, List, Tuple

from app.config import get_settings
from app.database import mongodb
from app.services import yandex_service

logger = logging.getLogger(__name__)


def generate_thread_id() -> str:
    """Генерирует уникальный thread_id"""
    return f"thread_{uuid.uuid4().hex[:16]}"


async def get_history_for_rag(thread_id: str, limit: int = 20) -> List[Dict[str, str]]:
    """
    Получить историю чата для RAG pipeline.
    Формат: [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
    """
    messages = await mongodb.get_chat_history(thread_id)

    history = []
    for msg in messages[-limit:]:  # Берём последние N сообщений
        history.append({
            "role": msg.get("role", "user"),
            "content": msg.get("content", "")
        })

    return history


async def process_message(
    user_id: str,
    message: str,
    thread_id: str = None,
    meta: Dict[str, Any] = None
) -> Tuple[str, str, bool]:
    """
    Обработать сообщение пользователя через ручной RAG.

    Args:
        user_id: ID пользователя
        message: Текст сообщения
        thread_id: ID существующего чата (None для нового)
        meta: Дополнительные метаданные

    Returns:
        Tuple[str, str, bool]: (ответ, thread_id, new_chat_created)
    """
    settings = get_settings()
    new_chat_created = False

    if thread_id:
        # Проверяем, существует ли чат в базе
        chat_thread = await mongodb.get_chat_thread(thread_id)

        if not chat_thread:
            logger.warning(f"Thread {thread_id} not found in database, creating new")
            thread_id = None

    if not thread_id:
        # Создаём новый чат (локально, без Yandex)
        logger.info(f"Creating new chat for user: {user_id}")

        thread_id = generate_thread_id()

        # Генерируем красивое название чата
        chat_name = await yandex_service.generate_chat_name(message)

        # Сохраняем в базу
        await mongodb.create_chat_thread(
            user_id=user_id,
            thread_id=thread_id,
            assistant_id="local_rag",  # Больше не используем Yandex Assistants
            vectorstore_id=settings.SEARCH_INDEX_ID or "",
            chat_name=chat_name
        )

        new_chat_created = True
        history = []  # Новый чат - история пустая
    else:
        # Получаем историю существующего чата
        history = await get_history_for_rag(thread_id)

    # Сохраняем сообщение пользователя
    await mongodb.add_message(
        user_id=user_id,
        thread_id=thread_id,
        role="user",
        content=message,
        meta=meta
    )

    # Используем ручной RAG pipeline
    answer, chunks = await yandex_service.rag_pipeline(
        question=message,
        history=history
    )

    # Сохраняем ответ ассистента
    await mongodb.add_message(
        user_id=user_id,
        thread_id=thread_id,
        role="assistant",
        content=answer,
        meta={"chunks_used": len(chunks)}
    )

    logger.info(f"✅ Message processed for user: {user_id}, thread: {thread_id}, chunks: {len(chunks)}")

    return answer, thread_id, new_chat_created


async def get_user_chats(user_id: str) -> List[Dict[str, Any]]:
    """
    Получить список чатов пользователя

    Args:
        user_id: ID пользователя

    Returns:
        Список чатов
    """
    chats = await mongodb.get_user_chats(user_id)

    # Преобразуем ObjectId в строку (если есть)
    for chat in chats:
        if "_id" in chat:
            del chat["_id"]

    return chats


async def get_chat_history(thread_id: str) -> List[Dict[str, Any]]:
    """
    Получить историю сообщений чата

    Args:
        thread_id: ID чата

    Returns:
        Список сообщений
    """
    messages = await mongodb.get_chat_history(thread_id)

    # Преобразуем ObjectId в строку (если есть)
    for msg in messages:
        if "_id" in msg:
            del msg["_id"]

    return messages


async def delete_chat(thread_id: str) -> bool:
    """
    Удалить чат

    Args:
        thread_id: ID чата

    Returns:
        True если удалён успешно
    """
    return await mongodb.delete_chat_thread(thread_id)
