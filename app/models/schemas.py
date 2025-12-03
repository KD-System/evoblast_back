"""
Pydantic модели для валидации данных
"""
from datetime import datetime
from typing import Optional, List, Any, Dict
from pydantic import BaseModel, Field
from enum import Enum


class FileStatus(str, Enum):
    """Статусы файла"""
    PENDING = "pending"
    PROCESSING = "processing"
    UPLOADED = "uploaded"      # Загружен в Yandex, но не в индексе
    READY = "ready"            # В индексе, готов к использованию
    ERROR = "error"
    DELETED = "deleted"


# === Chat Models ===

class MainThreadRequest(BaseModel):
    user_id: str = Field(..., example="user@example.com")
    thread_id: Optional[str] = Field(None)
    message: str = Field(..., example="Привет!")
    meta: Optional[Dict[str, Any]] = Field(default={})


class MainThreadResponse(BaseModel):
    message: str
    thread_id: str
    new_chat_created: bool = False


class ChatThreadInfo(BaseModel):
    uid: str
    user_id: str
    chat_name: str
    thread_id: str
    assistant_id: str
    vectorstore_id: str
    created_at: datetime
    updated_at: datetime


class UserChatsResponse(BaseModel):
    user_id: str
    chats: List[ChatThreadInfo]
    total: int


class MessageInfo(BaseModel):
    uuid: str
    user_id: str
    thread_id: str
    message_id: int
    role: str
    content: str
    created_at: datetime
    updated_at: datetime
    meta: Dict[str, Any] = {}


class ChatHistoryResponse(BaseModel):
    thread_id: str
    messages: List[MessageInfo]
    total: int


# === File Models ===

class FileInfo(BaseModel):
    file_id: str
    user_id: str
    filename: str
    file_type: str
    file_size: int
    status: FileStatus
    metadata: Dict[str, Any] = {}
    created_at: datetime
    updated_at: datetime
    vectorstore_file_id: Optional[str] = None


class FileListResponse(BaseModel):
    user_id: str
    files: List[FileInfo]
    total: int


class FileUploadResponse(BaseModel):
    message: str
    files: List[FileInfo]
    total_uploaded: int


class FileDeleteResponse(BaseModel):
    message: str
    file_id: str
    deleted: bool


class FilesDeleteAllResponse(BaseModel):
    message: str
    user_id: str
    deleted_count: int


# === Health ===

class HealthResponse(BaseModel):
    status: str
    project: str
    timestamp: datetime
    mongodb_connected: bool
    yandex_configured: bool


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
    timestamp: datetime
