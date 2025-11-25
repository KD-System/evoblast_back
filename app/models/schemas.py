"""
Pydantic модели для валидации данных
"""
from datetime import datetime
from typing import Optional, List, Any, Dict
from pydantic import BaseModel, Field


# ==========================================
# Request Models
# ==========================================

class MainThreadRequest(BaseModel):
    """Запрос для отправки сообщения в чат"""
    user_id: str = Field(..., description="ID пользователя", example="user@example.com")
    thread_id: Optional[str] = Field(None, description="ID чата (None для нового чата)")
    message: str = Field(..., description="Текст сообщения", example="Привет!")
    meta: Optional[Dict[str, Any]] = Field(default={}, description="Дополнительные данные")


class GetChatHistoryRequest(BaseModel):
    """Запрос для получения истории чата"""
    thread_id: str = Field(..., description="ID чата")


class GetUserChatsRequest(BaseModel):
    """Запрос для получения списка чатов пользователя"""
    user_id: str = Field(..., description="ID пользователя")


# ==========================================
# Response Models
# ==========================================

class MainThreadResponse(BaseModel):
    """Ответ от чата"""
    message: str = Field(..., description="Ответ ассистента")
    thread_id: str = Field(..., description="ID чата")
    new_chat_created: bool = Field(False, description="Был ли создан новый чат")


class ChatThreadInfo(BaseModel):
    """Информация о чате"""
    uid: str
    user_id: str
    chat_name: str
    thread_id: str
    assistant_id: str
    vectorstore_id: str
    created_at: datetime
    updated_at: datetime


class UserChatsResponse(BaseModel):
    """Список чатов пользователя"""
    user_id: str
    chats: List[ChatThreadInfo]
    total: int


class MessageInfo(BaseModel):
    """Информация о сообщении"""
    uuid: str
    user_id: str
    thread_id: str
    message_id: int
    role: str  # "user" или "assistant"
    content: str
    created_at: datetime
    updated_at: datetime
    meta: Dict[str, Any] = {}


class ChatHistoryResponse(BaseModel):
    """История сообщений чата"""
    thread_id: str
    messages: List[MessageInfo]
    total: int


class HealthResponse(BaseModel):
    """Health check ответ"""
    status: str
    project: str
    timestamp: datetime
    mongodb_connected: bool
    yandex_configured: bool


class ErrorResponse(BaseModel):
    """Ответ с ошибкой"""
    error: str
    detail: Optional[str] = None
    timestamp: datetime
