# CorpAI Intelligence

**CorpAI Intelligence** — мультиагентная RAG-система для интеллектуального поиска, анализа и саммаризации корпоративных документов. Система построена на архитектуре **Agentic RAG** с использованием **LangGraph** для оркестрации агентов, **Qdrant** для векторного поиска и **FastAPI** для бэкенда.

---

## Содержание

- [Архитектура системы](#архитектура-системы)
- [Схема базы данных](#схема-базы-данных)
- [Оркестрация агентов](#оркестрация-агентов)
- [Технологический стек](#технологический-стек)
- [Структура проекта](#структура-проекта)
- [Быстрый старт](#быстрый-старт)
- [API Endpoints](#api-endpoints)
- [Безопасность и ACL](#безопасность-и-acl)

---

## Архитектура системы

Система состоит из четырёх ключевых слоёв:

```mermaid
graph TB
    subgraph Frontend
        UI[Web UI / Chat Interface<br/>Jinja2 Templates + HTMX]
    end

    subgraph API["API Layer FastAPI"]
        REST[REST API v1]
        SSE[SSE Streaming]
        AUTH[Auth JWT / SberID]
    end

    subgraph Agents["Multi-Agent Orchestration LangGraph"]
        ROUTER[Router Agent<br/>Semantic Routing]
        SEARCH[Search and RAG Agent<br/>Hybrid Search + LLM]
        SUMM[Summarizer Agent<br/>Document Summarization]
        ANALYTICS[Analytics Agent<br/>Tagging and Analysis]
        ORCH[Orchestrator<br/>State Graph]
    end

    subgraph ETL["ETL Pipeline"]
        PARSER[Document Parser<br/>PDF / DOCX / XLSX / TXT]
        CHUNKER[Text Chunker<br/>Smart Split + Overlap]
        EMBED[Embedder<br/>sentence-transformers]
        DEDUP[Deduplicator<br/>SimHash]
    end

    subgraph Storage["Data Layer"]
        PG[(PostgreSQL<br/>Metadata + Chat History)]
        QDRANT[(Qdrant<br/>Vector Store)]
        S3[(MinIO / S3<br/>File Storage)]
    end

    subgraph LLM["LLM Providers"]
        OPENAI[OpenAI-compatible<br/>Dev / Mock]
        GIGACHAT[GigaChat API<br/>Production]
    end

    UI --> REST
    UI --> SSE
    REST --> AUTH
    REST --> ORCH
    SSE --> ORCH
    ORCH --> ROUTER
    ROUTER --> SEARCH
    ROUTER --> SUMM
    ROUTER --> ANALYTICS
    SEARCH --> QDRANT
    SEARCH --> OPENAI
    SEARCH --> GIGACHAT
    SUMM --> OPENAI
    SUMM --> GIGACHAT
    ANALYTICS --> OPENAI
    ANALYTICS --> GIGACHAT
    ORCH --> PG
    REST --> ETL
    ETL --> PARSER
    PARSER --> CHUNKER
    CHUNKER --> EMBED
    CHUNKER --> DEDUP
    EMBED --> QDRANT
    EMBED --> PG
    REST --> S3
    REST --> PG
```

### Описание слоёв

| Слой | Компоненты | Назначение |
|------|-----------|------------|
| **Frontend** | Jinja2 Templates, HTMX | Веб-интерфейс чата, дашборд, управление документами |
| **API Layer** | FastAPI, JWT Auth, SSE | REST API + Server-Sent Events для стриминга ответов |
| **Multi-Agent** | LangGraph, 4 агента | Оркестрация: роутинг, поиск, саммари, аналитика |
| **ETL Pipeline** | Парсеры, Чанкер, Эмбеддер | Обработка документов: парсинг → чанкинг → эмбеддинги |
| **Data Layer** | PostgreSQL, Qdrant, MinIO | Реляционные данные, векторный поиск, файловое хранилище |
| **LLM Providers** | OpenAI / GigaChat | Генерация ответов и структурированных выводов |

---

## Схема базы данных

### Реляционная БД (PostgreSQL)

```mermaid
erDiagram
    users ||--o{ chat_sessions : "has"
    users ||--o{ documents : "uploads"
    users }o--o{ user_groups : "member of"
    user_groups ||--o{ user_groups : "parent of"

    chat_sessions ||--o{ chat_messages : "contains"
    documents ||--o{ document_chunks : "contains"
    documents ||--o{ document_group_permissions : "has ACL"
    user_groups ||--o{ document_group_permissions : "targets"

    folders ||--o{ folders : "parent of"
    folders ||--o{ documents : "contains"

    users {
        int id PK
        string email UK
        string username
        string hashed_password
        boolean is_active
        datetime created_at
        datetime updated_at
    }

    user_groups {
        int id PK
        string name UK
        string description
        int parent_id FK
        int priority
    }

    user_group_membership {
        int user_id FK
        int group_id FK
    }

    folders {
        int id PK
        string name
        int parent_id FK
        datetime created_at
    }

    documents {
        int id PK
        string filename
        string filepath
        string mime_type
        bigint file_size
        enum status
        string error_message
        string storage_path
        int uploaded_by FK
        int folder_id FK
        datetime created_at
        datetime updated_at
    }

    document_chunks {
        int id PK
        int document_id FK
        int chunk_index
        text content
        string chunk_type
        json metadata
        int token_count
        string vector_id
        datetime created_at
    }

    document_group_permissions {
        int id PK
        int document_id FK
        int group_id FK
        string permission
        boolean is_deny
    }

    chat_sessions {
        int id PK
        int user_id FK
        string title
        enum status
        json agent_state
        datetime created_at
        datetime updated_at
    }

    chat_messages {
        int id PK
        int session_id FK
        string role
        text content
        json citations
        json validation_result
        int token_count
        datetime created_at
    }
```

### Векторная БД (Qdrant)

Коллекция `document_chunks`:

| Поле | Тип | Назначение |
|------|-----|------------|
| `vector` | float[384] | Эмбеддинг чанка (all-MiniLM-L6-v2) |
| `payload.document_id` | int | ID документа в PostgreSQL |
| `payload.chunk_index` | int | Порядковый номер чанка |
| `payload.content` | text | Текст чанка |
| `payload.chunk_type` | string | text / table / list |
| `payload.metadata` | json | page_number, bbox, source |
| `payload.allowed_groups` | list[int] | ACL: ID групп с доступом |

---

## Оркестрация агентов

```mermaid
flowchart TD
    START([User Query]) --> ROUTER[Router Agent<br/>Semantic Routing]

    ROUTER --> DECIDE{Route Decision}
    DECIDE -->|search| SEARCH[Search and RAG Agent<br/>Vector Search + LLM]
    DECIDE -->|summarize| SUMM[Summarizer Agent<br/>Text Compression]
    DECIDE -->|analyze| ANALYTICS[Analytics Agent<br/>Tags + Topics]
    DECIDE -->|general| FINALIZE

    SEARCH --> FINALIZE[Finalize<br/>Format Response]
    SUMM --> FINALIZE
    ANALYTICS --> FINALIZE

    FINALIZE --> END([Response to User])

    subgraph Search_Flow["Search Flow Details"]
        SEARCH --> EMBED[Embed Query]
        EMBED --> QSEARCH[Qdrant Search<br/>with ACL Filter]
        QSEARCH --> RERANK[Reranker<br/>Cross-Encoder]
        RERANK --> LLM_CALL[LLM: Generate Answer<br/>with Citations]
    end

    subgraph ACL["ACL Pre-filtering"]
        direction LR
        USER_GROUPS[User Groups<br/>from JWT] --> FILTER[Build Qdrant Filter<br/>allowed_groups IN user_groups]
        FILTER --> QSEARCH
    end
```

### Агенты

| Агент | Назначение | Вход | Выход |
|-------|-----------|------|-------|
| **Router Agent** | Семантический роутинг запроса | Текст запроса | Маршрут: search / summarize / analyze / general |
| **Search and RAG Agent** | Поиск по документам + генерация ответа | Запрос + группы доступа | Ответ с цитированием источников |
| **Summarizer Agent** | Сжатие больших объёмов текста | Текст документа | Саммари + ключевые тезисы |
| **Analytics Agent** | Аналитика: теги, связи, тип документа | Текст документа | Теги, темы, тип, сложность |

### ETL Pipeline (обработка документов)

```mermaid
flowchart LR
    UPLOAD[Upload Document] --> PARSE[Parse<br/>PDF / DOCX / XLSX / TXT]
    PARSE --> CHUNK[Chunk<br/>Smart Split + Overlap]
    CHUNK --> DEDUP[Deduplicate<br/>SimHash]
    CHUNK --> EMBED[Embed<br/>sentence-transformers]
    EMBED --> QDRANT[Save to Qdrant<br/>+ ACL metadata]
    EMBED --> PG[Save to PostgreSQL<br/>chunk records]
    DEDUP --> PG
    PARSE --> PG
```

---

## Технологический стек

| Компонент | Технология | Назначение |
|-----------|-----------|------------|
| **Backend Framework** | FastAPI + Python 3.12 | REST API + SSE streaming |
| **Agent Orchestration** | LangGraph + LangChain | Multi-agent state graph |
| **Vector Database** | Qdrant | Semantic search + hybrid search |
| **Relational Database** | PostgreSQL 16 + SQLAlchemy | Metadata, chat history, ACL |
| **File Storage** | MinIO (S3-compatible) | Document file storage |
| **Embeddings** | sentence-transformers (all-MiniLM-L6-v2) | Text vectorization |
| **Reranking** | Cross-Encoder (ms-marco-MiniLM-L-6-v2) | Precision re-ranking |
| **LLM** | OpenAI-compatible / GigaChat API | Answer generation |
| **Validation** | Cross-Encoder NLI (deberta-v3) | Fact-checking answers |
| **Frontend** | Jinja2 + HTMX + Tailwind CSS | Web UI |
| **Containerization** | Docker + Docker Compose | Infrastructure |

---

## Структура проекта

```
project21/
├── main.py                          # FastAPI app entry point
├── pyproject.toml                   # Python dependencies
├── docker-compose.yml               # PostgreSQL + Qdrant + MinIO
├── Dockerfile                       # App container
├── requirements.txt
├── README.md
│
├── app/
│   ├── routes.py                    # HTML page routes (Jinja2)
│   │
│   ├── core/
│   │   ├── config.py                # App config, DB engine, settings
│   │   ├── dependencies.py          # DI: Qdrant, LLM, Embedder
│   │   └── security.py              # JWT security utilities
│   │
│   ├── models/
│   │   ├── user.py                  # User, UserGroup, user_group_membership
│   │   ├── document.py              # Folder, Document, DocumentChunk, ACL
│   │   └── chat.py                  # ChatSession, ChatMessage
│   │
│   ├── schemas/
│   │   ├── user.py                  # Pydantic: User, Group, Token
│   │   ├── document.py              # Pydantic: Document, Chunk, Folder
│   │   └── chat.py                  # Pydantic: Session, Message, Request
│   │
│   ├── crud/
│   │   ├── crud_user.py             # User CRUD operations
│   │   └── crud_document.py         # Document, Chunk, ACL CRUD
│   │
│   ├── api/
│   │   ├── deps.py                  # FastAPI deps: auth, user groups
│   │   └── v1/
│   │       ├── api.py               # Router aggregation
│   │       └── endpoints/
│   │           ├── auth.py          # POST /auth/login, /register
│   │           ├── users.py         # GET /users/me, /users
│   │           ├── documents.py     # CRUD documents + folders
│   │           └── chat.py          # Chat sessions + SSE streaming
│   │
│   ├── agents/
│   │   ├── orchestrator.py          # LangGraph state graph
│   │   ├── router_agent.py          # Semantic router
│   │   ├── search_rag_agent.py      # Search + RAG
│   │   ├── summarizer_agent.py      # Document summarization
│   │   └── analytics_agent.py       # Tagging + analysis
│   │
│   ├── services/
│   │   ├── parser.py                # PDF / DOCX / XLSX / TXT parsers
│   │   ├── chunker.py               # Text chunking with overlap
│   │   ├── embedder.py              # sentence-transformers embeddings
│   │   ├── vector_store.py          # Qdrant search + ACL filtering
│   │   ├── reranker.py              # Cross-encoder reranking
│   │   ├── deduplicator.py          # SimHash deduplication
│   │   ├── storage.py               # File storage abstraction (Mock S3)
│   │   ├── etl_pipeline.py          # Full ETL: parse → chunk → embed → save
│   │   ├── acl.py                   # ACL: group hierarchy, pre-filtering
│   │   ├── validation.py            # NLI fact-checking
│   │   ├── citation.py              # Citation formatting
│   │   ├── llm_provider.py          # Abstract LLM + OpenAI client
│   │   └── gigachat_provider.py     # GigaChat OAuth2 client
│   │
│   └── templates/                   # Jinja2 HTML templates
│       ├── base.html
│       ├── chat.html
│       ├── dashboard.html
│       ├── documents.html
│       └── main.html
│
├── static/                          # Static assets (CSS, JS)
├── tests/                           # Test suite
├── plans/                           # Architecture plans
└── uploads/                         # Uploaded documents (local dev)
```

---

## Быстрый старт

### 1. Запуск инфраструктуры (Docker)

```bash
docker compose up -d
```

Запускает:
- **PostgreSQL 16** на порту `5432`
- **Qdrant** на порту `6333` (gRPC: `6334`)
- **MinIO** на порту `9000` (console: `9001`)

### 2. Установка зависимостей

```bash
pip install -r requirements.txt
# или через uv:
uv sync
```

### 3. Настройка окружения

Создайте `.env` файл:

```env
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/project21
QDRANT_HOST=localhost
QDRANT_PORT=6333
OPENAI_API_KEY=sk-your-key
OPENAI_API_BASE=http://localhost:8000/v1
OPENAI_MODEL=gpt-4o-mini
LLM_PROVIDER=openai
```

Для GigaChat:

```env
LLM_PROVIDER=gigachat
GIGACHAT_CLIENT_ID=your-client-id
GIGACHAT_CLIENT_SECRET=your-client-secret
```

### 4. Запуск приложения

```bash
python main.py
# или через uvicorn:
uvicorn main:fastapi_app --reload
```

Приложение будет доступно по адресу: `http://localhost:8000`

---

## API Endpoints

### Аутентификация

| Метод | Путь | Назначение |
|-------|------|------------|
| POST | `/api/v1/auth/login` | Вход в систему |
| POST | `/api/v1/auth/register` | Регистрация |

### Пользователи

| Метод | Путь | Назначение |
|-------|------|------------|
| GET | `/api/v1/users/me` | Текущий пользователь |
| GET | `/api/v1/users/` | Список пользователей |

### Документы

| Метод | Путь | Назначение |
|-------|------|------------|
| GET | `/api/v1/documents/` | Список документов |
| GET | `/api/v1/documents/{id}` | Детали документа |
| POST | `/api/v1/documents/upload` | Загрузка документа |
| DELETE | `/api/v1/documents/{id}` | Удаление документа |
| GET | `/api/v1/documents/folders/list` | Список папок |
| POST | `/api/v1/documents/folders` | Создание папки |

### Чат

| Метод | Путь | Назначение |
|-------|------|------------|
| GET | `/api/v1/chat/sessions` | Список сессий |
| POST | `/api/v1/chat/sessions` | Создать сессию |
| GET | `/api/v1/chat/sessions/{id}/messages` | История сообщений |
| DELETE | `/api/v1/chat/sessions/{id}` | Архивация сессии |
| POST | `/api/v1/chat/stream` | Стриминг ответа (SSE) |
| POST | `/api/v1/chat/chat` | Синхронный ответ |

### Веб-страницы

| Путь | Назначение |
|------|------------|
| `/` | Редирект на `/chat` |
| `/chat` | Интерфейс чата |
| `/documents` | Управление документами |
| `/dashboard` | Дашборд со статистикой |

---

## Безопасность и ACL

Система реализует **динамический ACL** (Access Control List) для разграничения доступа к документам:

```mermaid
flowchart LR
    USER[User] --> JWT[JWT Token<br/>user_id + groups]
    JWT --> AUTH[Auth Dependency]
    AUTH --> GROUPS[get_effective_groups<br/>resolve group hierarchy]
    GROUPS --> FILTER[build_qdrant_filter<br/>allowed_groups IN user_groups]
    FILTER --> SEARCH[Qdrant Search<br/>only matching chunks]
    SEARCH --> RESPONSE[Response<br/>filtered by access]
```

### Принципы ACL

1. **Deny-правила** имеют высший приоритет
2. **Allow-правила** разрешают доступ для конкретных групп
3. **Default deny** — если правил нет, доступ запрещён
4. **Наследование групп** — дочерние группы наследуют права родительских
5. **Pre-filtering** — фильтрация на уровне векторного запроса в Qdrant

---

## Лицензия

Проект разработан в рамках корпоративного MVP. Все права защищены.