"""
MongoDB подключение и операции с базой данных
"""
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
import uuid as uuid_lib

from app.config import get_settings

logger = logging.getLogger(__name__)

# Глобальные переменные для подключения
_client: Optional[AsyncIOMotorClient] = None
_database: Optional[AsyncIOMotorDatabase] = None


async def connect_to_mongodb():
    """Подключение к MongoDB"""
    global _client, _database
    
    settings = get_settings()
    
    try:
        _client = AsyncIOMotorClient(settings.MONGODB_URL)
        _database = _client[settings.MONGODB_DATABASE]
        
        # Проверяем подключение
        await _client.admin.command('ping')
        logger.info(f"✅ Connected to MongoDB: {settings.MONGODB_DATABASE}")
        
        # Создаём индексы
        await _create_indexes()
        
    except Exception as e:
        logger.error(f"❌ Failed to connect to MongoDB: {e}")
        raise


async def close_mongodb_connection():
    """Закрытие подключения к MongoDB"""
    global _client
    
    if _client:
        _client.close()
        logger.info("🔌 MongoDB connection closed")


async def _create_indexes():
    """Создание индексов для коллекций"""
    global _database
    
    if _database is None:
        return
    
    # Индексы для CHAT_THREADS
    await _database.chat_threads.create_index("user_id")
    await _database.chat_threads.create_index("thread_id", unique=True)
    await _database.chat_threads.create_index([("user_id", 1), ("created_at", -1)])
    
    # Индексы для CHAT_HISTORY
    await _database.chat_history.create_index("thread_id")
    await _database.chat_history.create_index([("thread_id", 1), ("message_id", 1)])
    await _database.chat_history.create_index("user_id")
    
    logger.info("✅ MongoDB indexes created")


def get_database() -> AsyncIOMotorDatabase:
    """Получить объект базы данных"""
    if _database is None:
        raise RuntimeError("MongoDB not connected. Call connect_to_mongodb() first.")
    return _database


async def is_connected() -> bool:
    """Проверить подключение к MongoDB"""
    global _client
    
    if _client is None:
        return False
    
    try:
        await _client.admin.command('ping')
        return True
    except Exception:
        return False


# ==========================================
# CHAT_THREADS Operations
# ==========================================

async def create_chat_thread(
    user_id: str,
    thread_id: str,
    assistant_id: str,
    vectorstore_id: str,
    chat_name: Optional[str] = None
) -> Dict[str, Any]:
    """Создать новую запись о чате"""
    db = get_database()
    
    now = datetime.utcnow()
    
    # Генерируем название чата, если не указано
    if not chat_name:
        chat_name = f"Чат от {now.strftime('%d.%m.%Y %H:%M')}"
    
    document = {
        "uid": str(uuid_lib.uuid4()),
        "user_id": user_id,
        "chat_name": chat_name,
        "thread_id": thread_id,
        "assistant_id": assistant_id,
        "vectorstore_id": vectorstore_id,
        "created_at": now,
        "updated_at": now
    }
    
    await db.chat_threads.insert_one(document)
    logger.info(f"✅ Created chat thread: {thread_id} for user: {user_id}")
    
    return document


async def get_chat_thread(thread_id: str) -> Optional[Dict[str, Any]]:
    """Получить информацию о чате по thread_id"""
    db = get_database()
    return await db.chat_threads.find_one({"thread_id": thread_id})


async def update_chat_thread(thread_id: str, update_data: Dict[str, Any]) -> bool:
    """Обновить информацию о чате"""
    db = get_database()
    
    update_data["updated_at"] = datetime.utcnow()
    
    result = await db.chat_threads.update_one(
        {"thread_id": thread_id},
        {"$set": update_data}
    )
    
    return result.modified_count > 0


async def get_user_chats(user_id: str) -> List[Dict[str, Any]]:
    """Получить список чатов пользователя"""
    db = get_database()
    
    cursor = db.chat_threads.find(
        {"user_id": user_id}
    ).sort("created_at", -1)
    
    chats = await cursor.to_list(length=100)
    return chats


async def delete_chat_thread(thread_id: str) -> bool:
    """Удалить чат и все его сообщения"""
    db = get_database()
    
    # Удаляем сообщения
    await db.chat_history.delete_many({"thread_id": thread_id})
    
    # Удаляем чат
    result = await db.chat_threads.delete_one({"thread_id": thread_id})
    
    return result.deleted_count > 0


# ==========================================
# CHAT_HISTORY Operations
# ==========================================

async def add_message(
    user_id: str,
    thread_id: str,
    role: str,  # "user" или "assistant"
    content: str,
    meta: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Добавить сообщение в историю чата"""
    db = get_database()
    
    now = datetime.utcnow()
    
    # Получаем следующий message_id для этого чата
    last_message = await db.chat_history.find_one(
        {"thread_id": thread_id},
        sort=[("message_id", -1)]
    )
    message_id = (last_message["message_id"] + 1) if last_message else 1
    
    document = {
        "uuid": str(uuid_lib.uuid4()),
        "user_id": user_id,
        "thread_id": thread_id,
        "message_id": message_id,
        "role": role,
        "content": content,
        "created_at": now,
        "updated_at": now,
        "meta": meta or {}
    }
    
    await db.chat_history.insert_one(document)
    
    # Обновляем updated_at в chat_threads
    await update_chat_thread(thread_id, {})
    
    logger.debug(f"📝 Added message #{message_id} to thread: {thread_id}")
    
    return document


async def get_chat_history(thread_id: str) -> List[Dict[str, Any]]:
    """Получить историю сообщений чата"""
    db = get_database()
    
    cursor = db.chat_history.find(
        {"thread_id": thread_id}
    ).sort("message_id", 1)
    
    messages = await cursor.to_list(length=1000)
    return messages


async def get_message_count(thread_id: str) -> int:
    """Получить количество сообщений в чате"""
    db = get_database()
    return await db.chat_history.count_documents({"thread_id": thread_id})
