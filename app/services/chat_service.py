"""
Сервис бизнес-логики чата
"""
import logging
from typing import Dict, Any, List, Tuple

from app.config import get_settings
from app.database import mongodb
from app.services import yandex_service

logger = logging.getLogger(__name__)


async def process_message(
    user_id: str,
    message: str,
    thread_id: str = None,
    meta: Dict[str, Any] = None
) -> Tuple[str, str, bool]:
    """
    Обработать сообщение пользователя
    
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
        # Создаём новый чат
        logger.info(f"Creating new chat for user: {user_id}")
        
        thread_id, assistant_id = yandex_service.create_new_chat()
        
        # Сохраняем в базу
        await mongodb.create_chat_thread(
            user_id=user_id,
            thread_id=thread_id,
            assistant_id=assistant_id,
            vectorstore_id=settings.VECTOR_STORE_ID,
            chat_name=f"Чат: {message[:30]}..." if len(message) > 30 else f"Чат: {message}"
        )
        
        new_chat_created = True
    else:
        # Получаем информацию о существующем чате
        chat_thread = await mongodb.get_chat_thread(thread_id)
        assistant_id = chat_thread["assistant_id"]
    
    # Сохраняем сообщение пользователя
    await mongodb.add_message(
        user_id=user_id,
        thread_id=thread_id,
        role="user",
        content=message,
        meta=meta
    )
    
    # Отправляем сообщение ассистенту и получаем ответ
    answer, citations = yandex_service.send_message_and_get_response(
        thread_id=thread_id,
        assistant_id=assistant_id,
        message=message
    )
    
    # Сохраняем ответ ассистента
    await mongodb.add_message(
        user_id=user_id,
        thread_id=thread_id,
        role="assistant",
        content=answer,
        meta={"citations": citations}
    )
    
    logger.info(f"✅ Message processed for user: {user_id}, thread: {thread_id}")
    
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
