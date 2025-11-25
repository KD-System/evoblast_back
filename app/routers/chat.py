"""
Роутер для эндпоинтов чата
"""
import logging
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query

from app.models.schemas import (
    MainThreadRequest,
    MainThreadResponse,
    UserChatsResponse,
    ChatHistoryResponse,
    ChatThreadInfo,
    MessageInfo,
)
from app.services import chat_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/evoblast", tags=["Chat"])


@router.post(
    "/mainthread",
    response_model=MainThreadResponse,
    summary="Отправить сообщение в чат",
    description="""
    Главный эндпоинт для работы с чатом.
    
    **Для нового чата:** отправьте без `thread_id`
    
    **Для продолжения чата:** укажите `thread_id`
    """
)
async def main_thread(request: MainThreadRequest):
    """
    Отправить сообщение и получить ответ от ассистента
    """
    logger.info(f"📨 Main thread request from user: {request.user_id}")
    
    try:
        answer, thread_id, new_chat_created = await chat_service.process_message(
            user_id=request.user_id,
            message=request.message,
            thread_id=request.thread_id,
            meta=request.meta
        )
        
        return MainThreadResponse(
            message=answer,
            thread_id=thread_id,
            new_chat_created=new_chat_created
        )
        
    except Exception as e:
        logger.error(f"❌ Error in main_thread: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process message: {str(e)}"
        )


@router.get(
    "/chats",
    response_model=UserChatsResponse,
    summary="Получить список чатов пользователя",
    description="Возвращает список всех чатов пользователя, отсортированных по дате создания (новые первые)"
)
async def get_user_chats(
    user_id: str = Query(..., description="ID пользователя", example="user@example.com")
):
    """
    Получить список чатов пользователя
    """
    logger.info(f"📋 Getting chats for user: {user_id}")
    
    try:
        chats = await chat_service.get_user_chats(user_id)
        
        # Преобразуем в модели
        chat_infos = [
            ChatThreadInfo(
                uid=chat["uid"],
                user_id=chat["user_id"],
                chat_name=chat["chat_name"],
                thread_id=chat["thread_id"],
                assistant_id=chat["assistant_id"],
                vectorstore_id=chat["vectorstore_id"],
                created_at=chat["created_at"],
                updated_at=chat["updated_at"]
            )
            for chat in chats
        ]
        
        return UserChatsResponse(
            user_id=user_id,
            chats=chat_infos,
            total=len(chat_infos)
        )
        
    except Exception as e:
        logger.error(f"❌ Error getting user chats: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get user chats: {str(e)}"
        )


@router.get(
    "/history",
    response_model=ChatHistoryResponse,
    summary="Получить историю сообщений чата",
    description="Возвращает все сообщения чата в хронологическом порядке"
)
async def get_chat_history(
    thread_id: str = Query(..., description="ID чата", example="fvtxxxxxxxxxx")
):
    """
    Получить историю сообщений чата
    """
    logger.info(f"📜 Getting history for thread: {thread_id}")
    
    try:
        messages = await chat_service.get_chat_history(thread_id)
        
        # Преобразуем в модели
        message_infos = [
            MessageInfo(
                uuid=msg["uuid"],
                user_id=msg["user_id"],
                thread_id=msg["thread_id"],
                message_id=msg["message_id"],
                role=msg["role"],
                content=msg["content"],
                created_at=msg["created_at"],
                updated_at=msg["updated_at"],
                meta=msg.get("meta", {})
            )
            for msg in messages
        ]
        
        return ChatHistoryResponse(
            thread_id=thread_id,
            messages=message_infos,
            total=len(message_infos)
        )
        
    except Exception as e:
        logger.error(f"❌ Error getting chat history: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get chat history: {str(e)}"
        )


@router.delete(
    "/chat",
    summary="Удалить чат",
    description="Удаляет чат и всю его историю сообщений"
)
async def delete_chat(
    thread_id: str = Query(..., description="ID чата для удаления")
):
    """
    Удалить чат
    """
    logger.info(f"🗑️ Deleting chat: {thread_id}")
    
    try:
        deleted = await chat_service.delete_chat(thread_id)
        
        if deleted:
            return {"message": "Chat deleted successfully", "thread_id": thread_id}
        else:
            raise HTTPException(
                status_code=404,
                detail=f"Chat not found: {thread_id}"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error deleting chat: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete chat: {str(e)}"
        )
