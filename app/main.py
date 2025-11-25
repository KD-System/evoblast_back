"""
Evoblast Backend API
FastAPI приложение с MongoDB и Yandex Cloud ML
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
from app.routers import chat_router
from app.models.schemas import HealthResponse

# === Настройка логирования ===
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# === Lifespan (startup/shutdown) ===
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения"""
    # Startup
    logger.info("🚀 Starting Evoblast Backend...")
    
    try:
        await mongodb.connect_to_mongodb()
        logger.info("✅ MongoDB connected")
    except Exception as e:
        logger.error(f"❌ Failed to connect to MongoDB: {e}")
    
    # Проверяем конфигурацию Yandex
    if yandex_service.is_configured():
        logger.info("✅ Yandex Cloud ML configured")
    else:
        logger.warning("⚠️ Yandex Cloud ML not fully configured!")
    
    yield
    
    # Shutdown
    logger.info("🛑 Shutting down Evoblast Backend...")
    await mongodb.close_mongodb_connection()


# === FastAPI App ===
settings = get_settings()

app = FastAPI(
    title="EVOBLAST API",
    description="""
    🚀 **Evoblast Backend API** с векторным поиском на базе Yandex Cloud ML
    
    ## Функциональность
    
    ### 💬 Chat
    - **POST /api/evoblast/mainthread** - Отправить сообщение в чат
    - **GET /api/evoblast/chats** - Получить список чатов пользователя
    - **GET /api/evoblast/history** - Получить историю сообщений чата
    - **DELETE /api/evoblast/chat** - Удалить чат
    
    ### 🏥 Health
    - **GET /health** - Проверка состояния сервиса
    """,
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)


# === CORS настройки ===
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://cms-kd-systems.ru",
        "http://localhost:3000",
        "http://158.160.200.70:3000",
        "*"  # Для тестирования
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# === Подключаем роутеры ===
app.include_router(chat_router)


# === Health Check ===
@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["Health"],
    summary="Проверка состояния сервиса"
)
async def health_check():
    """🏥 Health check endpoint для мониторинга"""
    mongodb_connected = await mongodb.is_connected()
    yandex_configured = yandex_service.is_configured()
    
    return HealthResponse(
        status="healthy" if mongodb_connected else "degraded",
        project=settings.PROJECT_NAME,
        timestamp=datetime.utcnow(),
        mongodb_connected=mongodb_connected,
        yandex_configured=yandex_configured
    )


# === Root endpoint ===
@app.get("/", tags=["Root"])
async def root():
    """Корневой эндпоинт"""
    return {
        "service": "Evoblast Backend",
        "version": "2.0.0",
        "docs": "/docs",
        "health": "/health"
    }


# === Обработка ошибок ===
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Глобальный обработчик ошибок"""
    logger.error(f"❌ Unhandled exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc) if settings.DEBUG else "An error occurred",
            "timestamp": datetime.utcnow().isoformat()
        }
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
