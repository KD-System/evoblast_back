"""
MongoDB подключение и операции с базой данных
"""
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase, AsyncIOMotorGridFSBucket
import uuid as uuid_lib

from app.config import get_settings

logger = logging.getLogger(__name__)

_client: Optional[AsyncIOMotorClient] = None
_database: Optional[AsyncIOMotorDatabase] = None
_gridfs: Optional[AsyncIOMotorGridFSBucket] = None


async def connect_to_mongodb():
    """Подключение к MongoDB"""
    global _client, _database, _gridfs

    settings = get_settings()

    try:
        _client = AsyncIOMotorClient(settings.MONGODB_URL)
        _database = _client[settings.MONGODB_DATABASE]
        _gridfs = AsyncIOMotorGridFSBucket(_database)

        await _client.admin.command('ping')
        logger.info(f"✅ Connected to MongoDB: {settings.MONGODB_DATABASE}")

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
    
    # Индексы для FILES
    await _database.files.create_index("file_id", unique=True)
    await _database.files.create_index("user_id")
    await _database.files.create_index([("user_id", 1), ("created_at", -1)])
    await _database.files.create_index("yandex_file_id")
    
    logger.info("✅ MongoDB indexes created")


def get_database() -> AsyncIOMotorDatabase:
    """Получить объект базы данных"""
    if _database is None:
        raise RuntimeError("MongoDB not connected")
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
# SETTINGS Operations (для VECTOR_STORE_ID)
# ==========================================

async def get_current_vector_store_id() -> Optional[str]:
    """Получить текущий VECTOR_STORE_ID из БД"""
    db = get_database()
    
    doc = await db.settings.find_one({"key": "vector_store_id"})
    if doc:
        return doc.get("value")
    return None


async def set_current_vector_store_id(vector_store_id: str) -> None:
    """Сохранить текущий VECTOR_STORE_ID в БД"""
    db = get_database()
    
    await db.settings.update_one(
        {"key": "vector_store_id"},
        {
            "$set": {
                "key": "vector_store_id",
                "value": vector_store_id,
                "updated_at": datetime.utcnow()
            }
        },
        upsert=True
    )
    logger.info(f"✅ Vector Store ID updated in DB: {vector_store_id}")


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
    logger.info(f"✅ Created chat thread: {thread_id}")
    
    return document


async def get_chat_thread(thread_id: str) -> Optional[Dict[str, Any]]:
    """Получить информацию о чате"""
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
    
    cursor = db.chat_threads.find({"user_id": user_id}).sort("created_at", -1)
    return await cursor.to_list(length=100)


async def delete_chat_thread(thread_id: str) -> bool:
    """Удалить чат и все его сообщения"""
    db = get_database()
    
    await db.chat_history.delete_many({"thread_id": thread_id})
    result = await db.chat_threads.delete_one({"thread_id": thread_id})
    
    return result.deleted_count > 0


# ==========================================
# CHAT_HISTORY Operations
# ==========================================

async def add_message(
    user_id: str,
    thread_id: str,
    role: str,
    content: str,
    meta: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Добавить сообщение в историю чата"""
    db = get_database()
    
    now = datetime.utcnow()
    
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
    await update_chat_thread(thread_id, {})
    
    return document


async def get_chat_history(thread_id: str) -> List[Dict[str, Any]]:
    """Получить историю сообщений чата"""
    db = get_database()
    
    cursor = db.chat_history.find({"thread_id": thread_id}).sort("message_id", 1)
    return await cursor.to_list(length=1000)


# ==========================================
# FILES Operations
# ==========================================

async def create_file_record(
    user_id: str,
    filename: str,
    file_type: str,
    file_size: int,
    yandex_file_id: str,
    content: str = "",
    binary_content: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    status: str = "ready"
) -> Dict[str, Any]:
    """Создать запись о файле"""
    db = get_database()

    now = datetime.utcnow()

    document = {
        "file_id": str(uuid_lib.uuid4()),
        "user_id": user_id,
        "filename": filename,
        "file_type": file_type,
        "file_size": file_size,
        "yandex_file_id": yandex_file_id,
        "status": status,
        "metadata": metadata or {},
        "created_at": now,
        "updated_at": now,
        "content": content,
        "binary_content": binary_content
    }

    await db.files.insert_one(document)
    logger.info(f"✅ Created file record: {filename}")

    return document


async def get_file_by_id(file_id: str) -> Optional[Dict[str, Any]]:
    """Получить файл по ID"""
    db = get_database()
    return await db.files.find_one({"file_id": file_id})


async def get_user_files(user_id: str) -> List[Dict[str, Any]]:
    """Получить список файлов пользователя"""
    db = get_database()
    
    cursor = db.files.find(
        {"user_id": user_id, "status": {"$ne": "deleted"}}
    ).sort("created_at", -1)
    
    return await cursor.to_list(length=100)


async def get_all_active_files() -> List[Dict[str, Any]]:
    """Получить ВСЕ активные файлы (для переиндексации)"""
    db = get_database()
    
    cursor = db.files.find({"status": {"$ne": "deleted"}})
    return await cursor.to_list(length=1000)


async def delete_file_record(file_id: str) -> Optional[Dict[str, Any]]:
    """Удалить запись о файле и вернуть её данные"""
    db = get_database()
    
    # Сначала получаем файл
    file = await db.files.find_one({"file_id": file_id})
    if not file:
        return None
    
    # Помечаем как удалённый
    await db.files.update_one(
        {"file_id": file_id},
        {"$set": {"status": "deleted", "updated_at": datetime.utcnow()}}
    )
    
    return file


async def update_file_status(file_id: str, status: str) -> bool:
    """Обновить статус файла"""
    db = get_database()

    result = await db.files.update_one(
        {"file_id": file_id},
        {"$set": {"status": status, "updated_at": datetime.utcnow()}}
    )

    return result.modified_count > 0


async def delete_all_user_files(user_id: str) -> List[Dict[str, Any]]:
    """Удалить все файлы пользователя и вернуть их"""
    db = get_database()
    
    # Получаем все файлы
    cursor = db.files.find({"user_id": user_id, "status": {"$ne": "deleted"}})
    files = await cursor.to_list(length=1000)
    
    # Помечаем как удалённые
    await db.files.update_many(
        {"user_id": user_id, "status": {"$ne": "deleted"}},
        {"$set": {"status": "deleted", "updated_at": datetime.utcnow()}}
    )
    
    return files


async def delete_all_files() -> int:
    """Удалить ВСЕ файлы (пометить как deleted)"""
    db = get_database()

    result = await db.files.update_many(
        {"status": {"$ne": "deleted"}},
        {"$set": {"status": "deleted", "updated_at": datetime.utcnow()}}
    )

    return result.modified_count


# ==========================================
# GridFS Operations (для больших файлов)
# ==========================================

def get_gridfs() -> AsyncIOMotorGridFSBucket:
    """Получить GridFS bucket"""
    if _gridfs is None:
        raise RuntimeError("GridFS not initialized")
    return _gridfs


async def gridfs_upload(file_id: str, filename: str, content: bytes) -> str:
    """Загрузить файл в GridFS"""
    fs = get_gridfs()
    grid_id = await fs.upload_from_stream(
        filename,
        content,
        metadata={"file_id": file_id}
    )
    logger.info(f"✅ GridFS upload: {filename} -> {grid_id}")
    return str(grid_id)


async def gridfs_download(file_id: str) -> Optional[bytes]:
    """Скачать файл из GridFS по file_id"""
    fs = get_gridfs()
    db = get_database()

    # Ищем файл по metadata.file_id
    file_doc = await db.fs.files.find_one({"metadata.file_id": file_id})
    if not file_doc:
        return None

    # Скачиваем
    grid_out = await fs.open_download_stream(file_doc["_id"])
    content = await grid_out.read()
    return content


async def gridfs_delete(file_id: str) -> bool:
    """Удалить файл из GridFS по file_id"""
    fs = get_gridfs()
    db = get_database()

    file_doc = await db.fs.files.find_one({"metadata.file_id": file_id})
    if not file_doc:
        return False

    await fs.delete(file_doc["_id"])
    logger.info(f"🗑️ GridFS deleted: {file_id}")
    return True
