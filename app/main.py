"""
Evoblast Backend API
"""
import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.database import mongodb
from app.services import yandex_service
from app.routers import chat_router, files_router, auth_router
from app.models.schemas import HealthResponse

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения"""
    logger.info("🚀 Starting Evoblast Backend...")
    
    try:
        await mongodb.connect_to_mongodb()
        logger.info("✅ MongoDB connected")
    except Exception as e:
        logger.error(f"❌ MongoDB connection failed: {e}")
    
    index_id = yandex_service.get_search_index_id()
    if index_id:
        logger.info(f"✅ Search Index configured: {index_id}")
    else:
        logger.warning("⚠️ SEARCH_INDEX_ID not configured!")
    
    if yandex_service.is_configured():
        logger.info("✅ Yandex Cloud ML configured")
    else:
        logger.warning("⚠️ Yandex Cloud ML not configured!")
    
    yield
    
    logger.info("🛑 Shutting down...")
    await mongodb.close_mongodb_connection()


settings = get_settings()

app = FastAPI(
    title="EVOBLAST API",
    description="""
    🚀 **Evoblast Backend API** с автоматической индексацией
    
    ## Auth
    - **GET /api/evoblast/user** - Информация о пользователе (JWT)
    
    ## Chat
    - **POST /api/evoblast/mainthread** - Отправить сообщение
    - **GET /api/evoblast/chats** - Список чатов
    - **GET /api/evoblast/history** - История чата
    - **DELETE /api/evoblast/chat** - Удалить чат
    
    ## Files
    - **POST /api/evoblast/upload** - Загрузить файлы
    - **GET /api/evoblast/files** - Список всех файлов
    - **GET /api/evoblast/files/my** - Мои файлы
    - **DELETE /api/evoblast/file/{id}** - Удалить файл
    - **DELETE /api/evoblast/files/all** - Удалить все файлы
    """,
    version="3.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://cms-kd-systems.ru",
        "http://localhost:3000",
        "http://158.160.200.70:3000",
        "*"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключаем роутеры
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(files_router)


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    mongodb_connected = await mongodb.is_connected()
    yandex_configured = yandex_service.is_configured()
    
    return HealthResponse(
        status="healthy" if mongodb_connected else "degraded",
        project=settings.PROJECT_NAME,
        timestamp=datetime.utcnow(),
        mongodb_connected=mongodb_connected,
        yandex_configured=yandex_configured
    )


@app.get("/", tags=["Root"])
async def root():
    index_id = yandex_service.get_search_index_id()
    return {
        "service": "Evoblast Backend",
        "version": "3.2.0",
        "search_index_id": index_id,
        "has_knowledge_base": bool(index_id),
        "docs": "/docs"
    }


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"❌ Error: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)}
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
