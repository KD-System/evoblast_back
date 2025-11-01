import os
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from jose import JWTError, jwt

app = FastAPI()

PROJECT_NAME = os.getenv("PROJECT_NAME", "evoblast")
SECRET_KEY = os.getenv("SECRET_KEY", "d1d056b1dd445cd0141908cee6126173ebf80c056f2cf671efa16db794bc3498")
ALGORITHM = os.getenv("ALGORITHM", "HS256")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://cms-kd-systems.ru",
        "http://localhost:3000",
        "http://158.160.200.70:3000"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def verify_token(request: Request) -> dict:
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Токен не найден")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Невалидный токен: {str(e)}")

@app.get("/health")
async def health_check():
    return {"status": "healthy", "project": PROJECT_NAME, "service": "backend"}

@app.get(f"/api/{PROJECT_NAME}/data")
async def get_data(payload: dict = Depends(verify_token)):
    return {
        "message": f"Данные проекта {PROJECT_NAME}",
        "project": PROJECT_NAME,
        "user": payload.get("sub"),
        "email": payload.get("email"),
        "data": [
            {"id": 1, "title": "Элемент 1", "description": "Описание элемента 1"},
            {"id": 2, "title": "Элемент 2", "description": "Описание элемента 2"},
            {"id": 3, "title": "Элемент 3", "description": "Описание элемента 3"},
        ]
    }

@app.get(f"/api/{PROJECT_NAME}/user")
async def get_user_info(payload: dict = Depends(verify_token)):
    return {
        "user_id": payload.get("sub"),
        "email": payload.get("email"),
        "project": PROJECT_NAME
    }
