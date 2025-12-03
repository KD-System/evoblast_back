"""
Роутер для авторизации (совместимость с фронтендом)
"""
import logging
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Optional
from jose import JWTError, jwt

from app.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/evoblast", tags=["Auth"])

settings = get_settings()


class UserInfo(BaseModel):
    """Информация о пользователе"""
    email: str
    project: str
    user_id: Optional[str] = None


def verify_token(request: Request) -> dict:
    """Проверяет JWT токен из cookie"""
    token = request.cookies.get("access_token")
    
    if not token:
        logger.warning("⚠️ Token not found in cookies")
        raise HTTPException(
            status_code=401, 
            detail="Authentication required. Token not found."
        )
    
    try:
        payload = jwt.decode(
            token, 
            settings.SECRET_KEY, 
            algorithms=[settings.ALGORITHM]
        )
        logger.info(f"✅ Token verified for user: {payload.get('email')}")
        return payload
    except JWTError as e:
        logger.error(f"❌ JWT validation error: {str(e)}")
        raise HTTPException(
            status_code=401, 
            detail="Invalid or expired token"
        )


@router.get("/user", response_model=UserInfo, summary="Получить информацию о пользователе")
async def get_user_info(request: Request):
    """
    👤 Получение информации о текущем пользователе из JWT токена.
    Используется фронтендом для проверки авторизации.
    """
    payload = verify_token(request)
    
    logger.info(f"👤 User info requested by {payload.get('email')}")
    
    return UserInfo(
        email=payload.get("email", ""),
        project=payload.get("project", "evoblast"),
        user_id=payload.get("sub")
    )
