# Evoblast Backend

REST API сервис для чат-бота с базой знаний на основе Yandex Cloud ML SDK.

## Возможности

- Загрузка документов (PDF, DOCX, XLSX, TXT и др.)
- Автоматическая индексация в Vector Store для RAG
- Чат с ИИ-ассистентом на базе YandexGPT
- Ответы на основе загруженных документов

---

## Быстрый старт

### 1. Настройка окружения

Создайте файл `.env`:

```bash
cp .env.example .env
```

Заполните переменные:

```env
# MongoDB
MONGODB_URL=mongodb://mongodb:27017
MONGODB_DATABASE=evoblast_db

# Yandex Cloud (обязательно!)
YANDEX_FOLDER_ID=b1g...          # ID каталога в Yandex Cloud
YANDEX_API_KEY=AQVN...           # API-ключ сервисного аккаунта

# Опционально
SECRET_KEY=your-jwt-secret       # Для JWT-авторизации
DEBUG=false
```

### 2. Запуск

```bash
# Docker Compose
docker compose up -d --build

# Или локально
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 3. Проверка

```bash
curl http://localhost:8000/health
# {"status": "ok"}
```

Swagger UI: http://localhost:8000/docs

---

## API Endpoints

### Файлы

| Метод | Endpoint | Описание |
|-------|----------|----------|
| `POST` | `/api/evoblast/upload` | Загрузить файлы |
| `GET` | `/api/evoblast/files` | Список всех файлов |
| `GET` | `/api/evoblast/files/my` | Мои файлы |
| `GET` | `/api/evoblast/file/{id}` | Информация о файле |
| `GET` | `/api/evoblast/download/{id}` | Скачать файл |
| `DELETE` | `/api/evoblast/file/{id}` | Удалить файл |
| `DELETE` | `/api/evoblast/files/all` | Удалить все файлы |

### Индексация

| Метод | Endpoint | Описание |
|-------|----------|----------|
| `GET` | `/api/evoblast/indexing-status` | Статус индексации |
| `GET` | `/api/evoblast/vector-store` | Текущий Vector Store ID |
| `POST` | `/api/evoblast/reindex` | Запустить индексацию вручную |

### Чат

| Метод | Endpoint | Описание |
|-------|----------|----------|
| `POST` | `/api/evoblast/mainthread` | Отправить сообщение |
| `GET` | `/api/evoblast/chats` | Список чатов пользователя |
| `GET` | `/api/evoblast/history` | История сообщений чата |
| `DELETE` | `/api/evoblast/chat` | Удалить чат |

### Авторизация

| Метод | Endpoint | Описание |
|-------|----------|----------|
| `GET` | `/api/evoblast/user` | Информация о пользователе (из JWT) |

---

## Примеры использования

### Загрузка файла

```bash
curl -X POST "http://localhost:8000/api/evoblast/upload?user_id=admin@example.com" \
  -F "files=@document.pdf"
```

Ответ:
```json
{
  "message": "Загружено: 1. Индексация запущена в фоне.",
  "files": [...],
  "total_uploaded": 1
}
```

### Проверка статуса индексации

```bash
curl "http://localhost:8000/api/evoblast/indexing-status"
```

Ответ:
```json
{
  "is_indexing": false,
  "message": "completed",
  "files_count": 5,
  "vector_store_id": "fvt...",
  "has_knowledge_base": true
}
```

### Отправка сообщения (новый чат)

```bash
curl -X POST "http://localhost:8000/api/evoblast/mainthread" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "admin@example.com",
    "message": "Расскажи о продуктах компании"
  }'
```

Ответ:
```json
{
  "message": "На основе базы знаний, компания предлагает...",
  "thread_id": "fvt...",
  "new_chat_created": true
}
```

### Продолжение чата

```bash
curl -X POST "http://localhost:8000/api/evoblast/mainthread" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "admin@example.com",
    "message": "А какие цены?",
    "thread_id": "fvt..."
  }'
```

### Получение списка чатов

```bash
curl "http://localhost:8000/api/evoblast/chats?user_id=admin@example.com"
```

### История чата

```bash
curl "http://localhost:8000/api/evoblast/history?thread_id=fvt..."
```

---

## Ограничения

### Загрузка файлов
- Максимум **10 файлов** за один запрос
- Максимальный размер файла: **30 MB**
- Поддерживаемые форматы: `txt`, `pdf`, `doc`, `docx`, `md`, `json`, `csv`, `xls`, `xlsx`

### Yandex Cloud
- Максимум **500 файлов** в одном Vector Store
- Индексация может занять **10-60 минут** в зависимости от размера файлов
- Лимиты API: см. [документацию Yandex Cloud](https://cloud.yandex.ru/docs/foundation-models/concepts/limits)

---

## Архитектура

```
┌─────────────┐     ┌─────────────┐     ┌─────────────────┐
│   Frontend  │────▶│   Backend   │────▶│  Yandex Cloud   │
│   (React)   │     │  (FastAPI)  │     │    ML SDK       │
└─────────────┘     └──────┬──────┘     └─────────────────┘
                           │
                    ┌──────▼──────┐
                    │   MongoDB   │
                    │  + GridFS   │
                    └─────────────┘
```

### Компоненты

1. **Backend (FastAPI)** - REST API, бизнес-логика
2. **MongoDB** - хранение метаданных файлов, чатов, сообщений
3. **GridFS** - хранение бинарных файлов
4. **Yandex Cloud ML SDK**:
   - **Files API** - загрузка файлов в облако
   - **Vector Store (SearchIndex)** - индексация для RAG
   - **Assistants API** - чат с YandexGPT

---

## Процесс работы

### Загрузка и индексация

```
1. Пользователь загружает PDF
2. Backend сохраняет в MongoDB + GridFS
3. Файл загружается в Yandex Cloud Files API
4. Запускается фоновая индексация:
   - Создается новый Vector Store со всеми файлами
   - Удаляется старый Vector Store
5. Ассистент получает доступ к базе знаний
```

### Чат с ассистентом

```
1. Пользователь отправляет сообщение
2. Backend создает Thread (если новый чат)
3. Создается Assistant с привязкой к Vector Store
4. YandexGPT ищет релевантные фрагменты в Vector Store
5. Генерируется ответ на основе найденных документов
```

---

## Переменные окружения

| Переменная | Обязательно | Описание |
|------------|-------------|----------|
| `YANDEX_FOLDER_ID` | Да | ID каталога в Yandex Cloud |
| `YANDEX_API_KEY` | Да | API-ключ сервисного аккаунта |
| `MONGODB_URL` | Нет | URL MongoDB (default: `mongodb://mongodb:27017`) |
| `MONGODB_DATABASE` | Нет | Имя базы данных (default: `evoblast_db`) |
| `SECRET_KEY` | Нет | Секрет для JWT (для авторизации) |
| `DEBUG` | Нет | Режим отладки (default: `false`) |

---

## Получение Yandex Cloud credentials

1. Перейдите в [консоль Yandex Cloud](https://console.cloud.yandex.ru/)
2. Создайте сервисный аккаунт с ролями:
   - `ai.assistants.editor`
   - `ai.foundationModels.user`
3. Создайте API-ключ для сервисного аккаунта
4. Скопируйте:
   - **YANDEX_FOLDER_ID** - ID каталога (b1g...)
   - **YANDEX_API_KEY** - API-ключ (AQVN...)

---

## Troubleshooting

### Vector Store долго создается

Yandex Cloud может индексировать файлы до 60 минут. Это нормально для больших PDF.

Проверить статус:
```bash
curl http://localhost:8000/api/evoblast/indexing-status
```

### Ошибка "maximum allowed number of files is 500"

Yandex Cloud ограничивает 500 файлов на один Vector Store. Удалите ненужные файлы.

### Ассистент не видит загруженные документы

1. Проверьте, завершилась ли индексация:
   ```bash
   curl http://localhost:8000/api/evoblast/vector-store
   ```
2. Если `vector_store_id` = `null`, запустите реиндексацию:
   ```bash
   curl -X POST http://localhost:8000/api/evoblast/reindex
   ```

### MongoDB не запускается

Проверьте, что порт 27017 не занят другим процессом:
```bash
docker ps | grep mongo
```

---

## Лицензия

MIT
