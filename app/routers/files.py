"""
Роутер для работы с файлами.

Файлы загружаются напрямую в фиксированный индекс (SEARCH_INDEX_ID).
"""
import logging
from typing import List
from fastapi import APIRouter, HTTPException, Query, UploadFile, File
from fastapi.responses import Response

from app.models.schemas import (
    FileInfo,
    FileListResponse,
    FileUploadResponse,
    FileDeleteResponse,
    FilesDeleteAllResponse,
    FileStatus,
)
from app.services import file_service, yandex_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/evoblast", tags=["Files"])


def _to_file_info(f: dict) -> FileInfo:
    """Конвертировать dict в FileInfo"""
    status = f.get("status", "ready")
    if status not in [s.value for s in FileStatus]:
        status = "ready"

    return FileInfo(
        file_id=f["file_id"],
        user_id=f["user_id"],
        filename=f["filename"],
        file_type=f["file_type"],
        file_size=f["file_size"],
        status=FileStatus(status),
        metadata=f.get("metadata", {}),
        created_at=f["created_at"],
        updated_at=f["updated_at"],
        vectorstore_file_id=f.get("yandex_file_id")
    )


@router.post(
    "/upload",
    response_model=FileUploadResponse,
    summary="Загрузить файлы",
    description="""
    Загрузка файлов в базу знаний.

    **Ограничения:**
    - Максимум 10 файлов за раз
    - Максимальный размер: 30MB
    - Форматы: txt, pdf, doc, docx, md, json, csv, xls, xlsx

    Файлы загружаются напрямую в индекс (SEARCH_INDEX_ID).
    """
)
async def upload_files(
    user_id: str = Query(..., description="ID пользователя (кто загружает)"),
    files: List[UploadFile] = File(..., description="Файлы (макс. 10)")
):
    logger.info(f"📤 Upload from user: {user_id}, files: {len(files)}")

    try:
        uploaded_files, errors = await file_service.upload_files(
            user_id=user_id,
            files=files
        )

        file_infos = [_to_file_info(f) for f in uploaded_files]

        message = f"✅ Загружено и проиндексировано: {len(uploaded_files)}"
        if errors:
            message += f" ⚠️ Ошибки: {'; '.join(errors)}"

        return FileUploadResponse(
            message=message,
            files=file_infos,
            total_uploaded=len(uploaded_files)
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"❌ Upload error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/files",
    response_model=FileListResponse,
    summary="Список всех файлов",
    description="Возвращает ВСЕ загруженные файлы (видны всем пользователям)"
)
async def get_files():
    """Получить список ВСЕХ файлов"""
    try:
        files = await file_service.get_all_files()
        file_infos = [_to_file_info(f) for f in files]

        return FileListResponse(
            user_id="all",
            files=file_infos,
            total=len(file_infos)
        )

    except Exception as e:
        logger.error(f"❌ Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/files/my",
    response_model=FileListResponse,
    summary="Мои файлы",
    description="Возвращает файлы, загруженные конкретным пользователем"
)
async def get_my_files(
    user_id: str = Query(..., description="ID пользователя")
):
    """Получить файлы конкретного пользователя"""
    try:
        files = await file_service.get_user_files(user_id)
        file_infos = [_to_file_info(f) for f in files]

        return FileListResponse(
            user_id=user_id,
            files=file_infos,
            total=len(file_infos)
        )

    except Exception as e:
        logger.error(f"❌ Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/file/{file_id}", summary="Информация о файле")
async def get_file(file_id: str):
    try:
        return await file_service.get_file(file_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/download/{file_id}", summary="Скачать файл")
async def download_file(file_id: str):
    """Скачать файл из GridFS"""
    from urllib.parse import quote
    from app.database import mongodb

    try:
        # Получаем информацию о файле из БД
        file_info = await file_service.get_file(file_id)
        filename = file_info.get("filename", "file")

        # Скачиваем из GridFS
        content = await mongodb.gridfs_download(file_id)

        if not content:
            raise HTTPException(status_code=404, detail="Контент файла не найден")

        # Определяем MIME-тип
        file_type = file_info.get("file_type", "").lower()
        mime_types = {
            "pdf": "application/pdf",
            "doc": "application/msword",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "xls": "application/vnd.ms-excel",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "txt": "text/plain",
            "md": "text/markdown",
            "json": "application/json",
            "csv": "text/csv",
        }
        media_type = mime_types.get(file_type, "application/octet-stream")

        # Кодируем имя файла для заголовка (поддержка кириллицы)
        encoded_filename = quote(filename)

        return Response(
            content=content,
            media_type=media_type,
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"
            }
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"❌ Download error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete(
    "/file/{file_id}",
    response_model=FileDeleteResponse,
    summary="Удалить файл",
    description="Удаляет файл из индекса и базы данных"
)
async def delete_file(file_id: str):
    logger.info(f"🗑️ Deleting file: {file_id}")

    try:
        deleted = await file_service.delete_file(file_id)

        return FileDeleteResponse(
            message="✅ Файл удалён из индекса",
            file_id=file_id,
            deleted=deleted
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete(
    "/files/all",
    response_model=FilesDeleteAllResponse,
    summary="Удалить ВСЕ файлы",
    description="Удаляет ВСЕ файлы из индекса и базы данных"
)
async def delete_all_files():
    """Удалить ВСЕ файлы"""
    logger.info(f"🗑️ Deleting ALL files")

    try:
        deleted_count = await file_service.delete_all_files()

        return FilesDeleteAllResponse(
            message=f"✅ Удалено файлов: {deleted_count}",
            user_id="all",
            deleted_count=deleted_count
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/index-info",
    summary="Информация об индексе",
    description="Получить информацию о поисковом индексе (SEARCH_INDEX_ID)"
)
async def get_index_info():
    """Получить информацию об индексе"""
    index_id = yandex_service.get_search_index_id()

    if not index_id:
        return {
            "error": "SEARCH_INDEX_ID not configured",
            "has_knowledge_base": False
        }

    info = await file_service.get_index_info()
    info["has_knowledge_base"] = True

    return info


@router.get(
    "/index-files",
    summary="Файлы в индексе",
    description="Получить список файлов, загруженных в поисковый индекс Yandex Cloud"
)
async def get_index_files(
    limit: int = Query(default=100, le=100, description="Максимум файлов")
):
    """Получить список файлов в индексе"""
    index_id = yandex_service.get_search_index_id()

    if not index_id:
        return {
            "error": "SEARCH_INDEX_ID not configured",
            "files": []
        }

    files = await file_service.list_index_files(limit)

    return {
        "index_id": index_id,
        "files": files,
        "total": len(files)
    }
