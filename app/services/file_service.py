"""
Сервис для работы с файлами
Фоновая индексация Vector Store
"""
import asyncio
import base64
import io
import logging
from typing import Dict, Any, List, Tuple, Optional
from fastapi import UploadFile

from app.database import mongodb
from app.services import yandex_service

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {'txt', 'pdf', 'doc', 'docx', 'md', 'json', 'csv', 'xls', 'xlsx'}
MAX_FILE_SIZE = 30 * 1024 * 1024  # 30 MB
MAX_FILES_PER_UPLOAD = 10


def extract_text_from_file(content: bytes, file_type: str) -> str:
    """Извлечь весь текст из файла"""
    try:
        # Текстовые файлы
        if file_type in ('txt', 'md', 'json', 'csv'):
            return content.decode('utf-8', errors='ignore')

        # PDF
        if file_type == 'pdf':
            try:
                from PyPDF2 import PdfReader
                reader = PdfReader(io.BytesIO(content))
                text_parts = []
                for page in reader.pages:
                    text_parts.append(page.extract_text() or "")
                return "\n".join(text_parts)
            except Exception as e:
                logger.warning(f"PDF extraction failed: {e}")
                return ""

        # DOCX
        if file_type == 'docx':
            try:
                from docx import Document
                doc = Document(io.BytesIO(content))
                text_parts = [p.text for p in doc.paragraphs]
                return "\n".join(text_parts)
            except Exception as e:
                logger.warning(f"DOCX extraction failed: {e}")
                return ""

        # XLSX
        if file_type == 'xlsx':
            try:
                from openpyxl import load_workbook
                wb = load_workbook(io.BytesIO(content), read_only=True)
                text_parts = []
                for sheet in wb.worksheets:
                    for row in sheet.iter_rows(values_only=True):
                        row_text = " | ".join(str(c) for c in row if c)
                        if row_text:
                            text_parts.append(row_text)
                return "\n".join(text_parts)
            except Exception as e:
                logger.warning(f"XLSX extraction failed: {e}")
                return ""

        # DOC, XLS — старые форматы, сложно извлечь
        if file_type in ('doc', 'xls'):
            return f"[Файл формата .{file_type} — превью недоступно]"

        return ""
    except Exception as e:
        logger.error(f"Text extraction error: {e}")
        return ""

# Статус индексации
_indexing_status: Dict[str, Any] = {
    "is_indexing": False,
    "message": "idle",
    "files_count": 0
}


def get_indexing_status() -> Dict[str, Any]:
    """Получить текущий статус индексации"""
    return _indexing_status.copy()


def _set_indexing_status(is_indexing: bool, message: str, files_count: int = 0):
    """Установить статус индексации"""
    global _indexing_status
    _indexing_status = {
        "is_indexing": is_indexing,
        "message": message,
        "files_count": files_count
    }


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


async def rebuild_vector_store_background():
    """Фоновая задача для пересоздания Vector Store"""
    try:
        files = await mongodb.get_all_active_files()
        files_count = len(files)

        _set_indexing_status(True, "indexing", files_count)
        logger.info(f"🔄 Starting background indexing for {files_count} files...")

        await _rebuild_vector_store()

        _set_indexing_status(False, "completed", files_count)
        logger.info(f"✅ Background indexing completed for {files_count} files")

    except Exception as e:
        logger.error(f"❌ Background indexing failed: {e}")
        _set_indexing_status(False, f"error: {str(e)}", 0)


async def upload_files(
    user_id: str,
    files: List[UploadFile],
    metadata: Dict[str, Any] = None
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Загрузить файлы в Yandex Cloud.
    Vector Store создаётся отдельно через фоновую задачу.
    """
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
                errors.append(f"{file.filename}: слишком большой (макс. 30MB)")
                continue

            file_type = get_file_extension(file.filename)

            # Кодируем бинарный контент в base64 для хранения в MongoDB
            binary_content_b64 = base64.b64encode(content).decode('ascii')

            # Извлекаем текст для превью (работает с PDF, DOCX, XLSX и текстовыми файлами)
            text_content = extract_text_from_file(content, file_type)

            # Загружаем в Yandex Cloud
            yandex_file_id = await yandex_service.upload_file_to_yandex(content, file.filename)

            # Сохраняем запись в MongoDB со статусом "uploaded"
            file_record = await mongodb.create_file_record(
                user_id=user_id,
                filename=file.filename,
                file_type=file_type,
                file_size=file_size,
                yandex_file_id=yandex_file_id,
                content=text_content,
                binary_content=binary_content_b64,
                metadata=metadata or {},
                status="uploaded"  # Ещё не в индексе
            )

            uploaded_files.append(file_record)
            logger.info(f"✅ File uploaded: {file.filename}")

        except Exception as e:
            logger.error(f"❌ Error uploading {file.filename}: {e}")
            errors.append(f"{file.filename}: {str(e)}")

    return uploaded_files, errors


async def upload_files_with_indexing(
    user_id: str,
    files: List[UploadFile],
    metadata: Dict[str, Any] = None
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Загрузить файлы И запустить индексацию (синхронно).
    Используется когда нужно дождаться индексации.
    """
    uploaded_files, errors = await upload_files(user_id, files, metadata)

    if uploaded_files:
        try:
            await _rebuild_vector_store()
            # Обновляем статус файлов на "ready"
            for f in uploaded_files:
                await mongodb.update_file_status(f["file_id"], "ready")
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
        if "binary_content" in f:
            del f["binary_content"]

    return files


async def get_user_files(user_id: str) -> List[Dict[str, Any]]:
    """Получить список файлов конкретного пользователя"""
    files = await mongodb.get_user_files(user_id)

    for f in files:
        if "_id" in f:
            del f["_id"]
        if "content" in f:
            del f["content"]
        if "binary_content" in f:
            del f["binary_content"]

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
