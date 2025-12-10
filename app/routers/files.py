"""
Роутер для работы с файлами
"""
import logging
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, UploadFile, File, BackgroundTasks
from fastapi.responses import Response

from app.models.schemas import (
    FileInfo,
    FileListResponse,
    FileUploadResponse,
    FileDeleteResponse,
    FilesDeleteAllResponse,
    FileStatus,
)
from app.services import file_service

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
    Загрузка файлов с **фоновой индексацией**.

    **Ограничения:**
    - Максимум 10 файлов за раз
    - Максимальный размер: 30MB
    - Форматы: txt, pdf, doc, docx, md, json, csv, xls, xlsx

    ✅ Ответ возвращается сразу после загрузки файлов.
    ⏳ Индексация выполняется в фоне (~10-30 сек).
    📊 Статус индексации: GET /api/evoblast/indexing-status
    """
)
async def upload_files(
    background_tasks: BackgroundTasks,
    user_id: str = Query(..., description="ID пользователя (кто загружает)"),
    files: List[UploadFile] = File(..., description="Файлы (макс. 10)")
):
    logger.info(f"📤 Upload from user: {user_id}, files: {len(files)}")

    try:
        # Загружаем файлы (быстро)
        uploaded_files, errors = await file_service.upload_files(
            user_id=user_id,
            files=files
        )

        # Запускаем индексацию в фоне
        if uploaded_files:
            background_tasks.add_task(file_service.rebuild_vector_store_background)

        file_infos = [_to_file_info(f) for f in uploaded_files]

        message = f"✅ Загружено: {len(uploaded_files)}. ⏳ Индексация запущена в фоне."
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
    "/indexing-status",
    summary="Статус индексации",
    description="Проверить статус фоновой индексации файлов"
)
async def get_indexing_status():
    """Получить статус индексации"""
    from app.services import yandex_service

    status = file_service.get_indexing_status()
    vector_store_id = yandex_service.get_vector_store_id()

    return {
        **status,
        "vector_store_id": vector_store_id or None,
        "has_knowledge_base": bool(vector_store_id)
    }


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
    """Скачать файл из Yandex Cloud"""
    from app.services import yandex_service
    from urllib.parse import quote

    try:
        # Получаем информацию о файле из БД
        file_info = await file_service.get_file(file_id)
        yandex_file_id = file_info.get("yandex_file_id")
        filename = file_info.get("filename", "file")

        if not yandex_file_id:
            raise HTTPException(status_code=404, detail="Файл не найден в Yandex Cloud")

        # Скачиваем файл из Yandex Cloud
        content = await yandex_service.download_file_from_yandex(yandex_file_id)

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
    description="Удаляет файл и **автоматически** пересоздаёт Vector Store"
)
async def delete_file(file_id: str):
    logger.info(f"🗑️ Deleting file: {file_id}")

    try:
        deleted = await file_service.delete_file(file_id)

        return FileDeleteResponse(
            message="✅ Файл удалён, индекс обновлён",
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
    description="Удаляет ВСЕ файлы и очищает Vector Store"
)
async def delete_all_files():
    """Удалить ВСЕ файлы"""
    logger.info(f"🗑️ Deleting ALL files")

    try:
        deleted_count = await file_service.delete_all_files()

        return FilesDeleteAllResponse(
            message=f"✅ Удалено файлов: {deleted_count}. Vector Store очищен.",
            user_id="all",
            deleted_count=deleted_count
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/vector-store", summary="Текущий Vector Store ID")
async def get_vector_store():
    """Получить текущий Vector Store ID"""
    from app.services import yandex_service

    vector_store_id = yandex_service.get_vector_store_id()
    db_id = await file_service.get_current_vector_store_id()

    return {
        "current_vector_store_id": vector_store_id or None,
        "db_vector_store_id": db_id or None,
        "has_knowledge_base": bool(vector_store_id)
    }
