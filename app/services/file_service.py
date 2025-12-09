"""
Сервис для работы с файлами
Автоматически пересоздаёт Vector Store при изменениях
"""
import logging
from typing import Dict, Any, List, Tuple, Optional
from fastapi import UploadFile

from app.database import mongodb
from app.services import yandex_service

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {'txt', 'pdf', 'doc', 'docx', 'md', 'json', 'csv', 'xls', 'xlsx'}
MAX_FILE_SIZE = 30 * 1024 * 1024  # 30 MB
MAX_FILES_PER_UPLOAD = 10


def get_file_extension(filename: str) -> str:
    if '.' in filename:
        return filename.rsplit('.', 1)[1].lower()
    return ''


def is_allowed_file(filename: str) -> bool:
    return get_file_extension(filename) in ALLOWED_EXTENSIONS


async def _rebuild_vector_store() -> Optional[str]:
    """
    Пересоздать Vector Store со всеми активными файлами.
    Если файлов нет — удаляет Vector Store и сбрасывает ID.
    """
    old_vector_store_id = await mongodb.get_current_vector_store_id()
    
    # Получаем ВСЕ активные файлы (без фильтра по user_id)
    files = await mongodb.get_all_active_files()
    
    # Собираем Yandex file IDs
    yandex_file_ids = [f["yandex_file_id"] for f in files if f.get("yandex_file_id")]
    
    # Если файлов нет — удаляем старый Vector Store и сбрасываем ID
    if not yandex_file_ids:
        logger.warning("⚠️ No files to index, clearing Vector Store")

        if old_vector_store_id:
            await yandex_service.delete_vector_store(old_vector_store_id)

        await mongodb.set_current_vector_store_id("")
        yandex_service.set_vector_store_id("")

        return None

    # Создаём новый Vector Store
    new_vector_store_id = await yandex_service.create_vector_store(yandex_file_ids)
    
    # Сохраняем в MongoDB
    await mongodb.set_current_vector_store_id(new_vector_store_id)
    
    # Обновляем кэш
    yandex_service.set_vector_store_id(new_vector_store_id)
    
    # Удаляем старый Vector Store
    if old_vector_store_id and old_vector_store_id != new_vector_store_id:
        await yandex_service.delete_vector_store(old_vector_store_id)
    
    logger.info(f"✅ Vector Store rebuilt: {new_vector_store_id}")
    return new_vector_store_id


async def upload_files(
    user_id: str,
    files: List[UploadFile],
    metadata: Dict[str, Any] = None
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Загрузить файлы и автоматически пересоздать Vector Store"""
    if len(files) > MAX_FILES_PER_UPLOAD:
        raise ValueError(f"Максимум {MAX_FILES_PER_UPLOAD} файлов за раз")
    
    uploaded_files = []
    errors = []
    
    for file in files:
        try:
            if not is_allowed_file(file.filename):
                errors.append(f"{file.filename}: неподдерживаемый тип")
                continue
            
            content = await file.read()
            file_size = len(content)
            
            if file_size > MAX_FILE_SIZE:
                errors.append(f"{file.filename}: слишком большой (макс. 10MB)")
                continue
            
            file_type = get_file_extension(file.filename)
            
            try:
                text_content = content.decode('utf-8')
            except:
                text_content = ""
            
            yandex_file_id = await yandex_service.upload_file_to_yandex(content, file.filename)
            
            file_record = await mongodb.create_file_record(
                user_id=user_id,
                filename=file.filename,
                file_type=file_type,
                file_size=file_size,
                yandex_file_id=yandex_file_id,
                content=text_content[:10000],
                metadata=metadata or {},
                status="ready"
            )
            
            uploaded_files.append(file_record)
            logger.info(f"✅ File uploaded: {file.filename}")
            
        except Exception as e:
            logger.error(f"❌ Error uploading {file.filename}: {e}")
            errors.append(f"{file.filename}: {str(e)}")
    
    if uploaded_files:
        try:
            await _rebuild_vector_store()
        except Exception as e:
            logger.error(f"❌ Failed to rebuild Vector Store: {e}")
            errors.append(f"Ошибка индексации: {str(e)}")
    
    return uploaded_files, errors


async def get_all_files() -> List[Dict[str, Any]]:
    """Получить список ВСЕХ файлов (для всех пользователей)"""
    files = await mongodb.get_all_active_files()
    
    for f in files:
        if "_id" in f:
            del f["_id"]
        if "content" in f:
            del f["content"]
    
    return files


async def get_user_files(user_id: str) -> List[Dict[str, Any]]:
    """Получить список файлов конкретного пользователя"""
    files = await mongodb.get_user_files(user_id)
    
    for f in files:
        if "_id" in f:
            del f["_id"]
        if "content" in f:
            del f["content"]
    
    return files


async def get_file(file_id: str) -> Dict[str, Any]:
    """Получить файл по ID"""
    file = await mongodb.get_file_by_id(file_id)
    
    if not file:
        raise ValueError(f"Файл не найден: {file_id}")
    
    if "_id" in file:
        del file["_id"]
    
    return file


async def delete_file(file_id: str) -> bool:
    """Удалить файл и автоматически пересоздать Vector Store"""
    file = await mongodb.delete_file_record(file_id)
    
    if not file:
        raise ValueError(f"Файл не найден: {file_id}")
    
    if file.get("yandex_file_id"):
        await yandex_service.delete_file_from_yandex(file["yandex_file_id"])
    
    try:
        await _rebuild_vector_store()
    except Exception as e:
        logger.error(f"❌ Failed to rebuild Vector Store: {e}")
    
    logger.info(f"🗑️ File deleted: {file_id}")
    return True


async def delete_all_files() -> int:
    """Удалить ВСЕ файлы и очистить Vector Store"""
    files = await mongodb.get_all_active_files()
    
    # Удаляем из Yandex Cloud
    for file in files:
        if file.get("yandex_file_id"):
            try:
                await yandex_service.delete_file_from_yandex(file["yandex_file_id"])
            except:
                pass
    
    # Помечаем все как удалённые в MongoDB
    deleted_count = await mongodb.delete_all_files()
    
    # Пересоздаём (удалим) Vector Store
    try:
        await _rebuild_vector_store()
    except Exception as e:
        logger.error(f"❌ Failed to rebuild Vector Store: {e}")
    
    logger.info(f"🗑️ Deleted all {deleted_count} files")
    return deleted_count


async def get_current_vector_store_id() -> Optional[str]:
    """Получить текущий Vector Store ID"""
    return await mongodb.get_current_vector_store_id()
