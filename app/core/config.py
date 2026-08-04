import binascii
import base64
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
import os

load_dotenv('.env')

# === Database ===
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@postgres:5432/project21" # or "sqlite:///./project21.db"
)

engine = None
SessionLocal = None
Base = declarative_base()


def _build_engine():
    global engine, SessionLocal
    if engine is not None and SessionLocal is not None:
        return engine, SessionLocal

    try:
        # SQLite требует connect_args для потокобезопасности
        connect_args = {"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
        engine = create_engine(DATABASE_URL, connect_args=connect_args)
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    except Exception:
        engine = None
        SessionLocal = None

    return engine, SessionLocal


def get_db():
    """FastAPI dependency: get DB session"""
    _, local_session = _build_engine()
    if local_session is None:
        raise RuntimeError("Database is not available. Install database driver or configure DATABASE_URL.")

    db = local_session()
    try:
        yield db
    finally:
        db.close()


# === Qdrant ===
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_NAME", "document_chunks")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "document_chunks")
QDRANT_VECTOR_SIZE = int(os.getenv("QDRANT_VECTOR_SIZE", "384"))  # sentence-transformers/all-MiniLM-L6-v2


# === Mock S3 (MinIO) ===
S3_ENDPOINT = os.getenv("S3_ENDPOINT", "http://localhost:9000")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "minioadmin")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "minioadmin")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "documents")
S3_USE_SSL = os.getenv("S3_USE_SSL", "false").lower() == "true"


# === LLM Provider ===
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")  # "openai" | "gigachat"

# OpenAI-compatible (для разработки)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "sk-mock-key")
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "http://localhost:8000/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# GigaChat (для продакшена)
GIGACHAT_CLIENT_ID = os.getenv("GIGACHAT_CLIENT_ID", "")
# GIGACHAT_CLIENT_SECRET может быть:
#   - готовым Authorization Key (Base64 от client_id:secret) — из личного кабинета
#   - raw secret (если используется старая схема client_id|secret)
# Библиотека gigachat ожидает Authorization Key в формате Base64.
GIGACHAT_CLIENT_SECRET = os.getenv("GIGACHAT_CLIENT_SECRET", "")
GIGACHAT_SCOPE = os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")
# OAuth endpoint единый для всех шлюзов.
# API-шлюз можно переключить через GIGACHAT_API_URL:
#   Новый: https://api.giga.chat/v1
#   Старый: https://gigachat.devices.sberbank.ru/api/v1
GIGACHAT_AUTH_URL = os.getenv("GIGACHAT_AUTH_URL", "https://ngw.devices.sberbank.ru:9443/api/v2/oauth")
GIGACHAT_API_URL = os.getenv("GIGACHAT_API_URL", "https://api.giga.chat/v1")
# Модель GigaChat. На новом API-шлюзе (api.giga.chat) доступны:
#   GigaChat-2, GigaChat-2-Max, GigaChat-2-Pro, GigaChat-3-Ultra
# На старом шлюзе (gigachat.devices.sberbank.ru): GigaChat
GIGACHAT_MODEL = os.getenv("GIGACHAT_MODEL", "GigaChat-2")
# Credentials для SDK: если GIGACHAT_CLIENT_SECRET уже является Base64 (Authorization Key),
# используем его напрямую. Иначе формируем Base64 из client_id|client_secret.
_GIGACHAT_CREDENTIALS_ENV = os.getenv("GIGACHAT_CREDENTIALS", "")
if _GIGACHAT_CREDENTIALS_ENV:
    GIGACHAT_CREDENTIALS = _GIGACHAT_CREDENTIALS_ENV
elif GIGACHAT_CLIENT_SECRET:
    # Проверяем, является ли CLIENT_SECRET уже валидным Base64
    try:
        base64.b64decode(GIGACHAT_CLIENT_SECRET, validate=True)
        # Если декодируется — это готовый Authorization Key
        GIGACHAT_CREDENTIALS = GIGACHAT_CLIENT_SECRET
    except Exception:
        # Иначе это raw secret, формируем Base64 из client_id|secret
        raw = f"{GIGACHAT_CLIENT_ID}|{GIGACHAT_CLIENT_SECRET}"
        GIGACHAT_CREDENTIALS = base64.b64encode(raw.encode()).decode()
else:
    GIGACHAT_CREDENTIALS = ""


# === Embedding ===
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
EMBEDDING_DEVICE = os.getenv("EMBEDDING_DEVICE", "cpu")  # "cpu" | "cuda"


# === Reranker (Cross-Encoder) ===
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")


# === ACL ===
ACL_DEFAULT_DENY = os.getenv("ACL_DEFAULT_DENY", "true").lower() == "true"


# === JWT ===
SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-key-change-in-production")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))


# === Storage (local files for MVP) ===
LOCAL_STORAGE_PATH = os.getenv("LOCAL_STORAGE_PATH", "./storage")

# === Hugging Face Token ===
HF_TOKEN = os.getenv("HF_TOKEN", "")


# === CORS ===
CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:8000,http://127.0.0.1:8000,http://localhost:3000"
).split(",")


# === Sparse Search (BM25) ===
SPARSE_SEARCH_ENABLED = os.getenv("SPARSE_SEARCH_ENABLED", "true").lower() == "true"
SPARSE_VECTOR_NAME = os.getenv("SPARSE_VECTOR_NAME", "bm25")


# === Self API URL (для внутренних HTTP-вызовов к самому себе) ===
SELF_API_URL = os.getenv("SELF_API_URL", "http://localhost:8000/api/v1")


CHUNK_MODEL = os.getenv('CHUNK_MODEL', 'sergeyzh/rubert-tiny-turbo') #
CHUNK_THRESHOLD = os.getenv('CHUNK_THRESHOLD', '75') #

INDEX_PATH = os.getenv('INDEX_PATH', '')
FILE_PATH = os.getenv('FILE_PATH', '/storage')

AGENT_TEMPERATURE = os.getenv('AGENT_TEMPERATURE', '0.1') #
AGENT_MAX_TOKEN = os.getenv('AGENT_MAX_TOKEN', '8192') #

# HyDe Setting
HYDE_TEMPERATURE = os.getenv('HYDE_TEMPERATURE', '0.7') #
HYDE_MAX_TOKEN = os.getenv('HYDE_MAX_TOKEN', '2048') #
MAX_CHUNK_HYDE = os.getenv('MAX_CHUNK_HYDE', '5') #
LIMIT_RRF = os.getenv('LIMIT_RRF', '20') #
NUM_RESULTS = os.getenv('NUM_RESULTS', '20') #
TOP_RERANKED = os.getenv('TOP_RERANKED', '5') #
CROSS_ENC = os.getenv('CROSS_ENC', 'DiTy/cross-encoder-russian-msmarco') #

# === Embedding / Vector Search (RAG services) ===
EMB_MODEL = os.getenv('EMB_MODEL', 'all-MiniLM-L6-v2')
# Алиас для QDRANT_HOST, чтобы существующий RAG-код продолжал работать без смены имени переменной.
QDRANT_BASE = os.getenv('QDRANT_BASE', QDRANT_HOST)
VECTOR_SIZE = int(os.getenv('VECTOR_SIZE', '384'))
SPARSE_MODEL = os.getenv('SPARSE_MODEL', 'Qdrant/bm25')
MODEL_CACHE_DIR = os.getenv('MODEL_CACHE_DIR', '')
FASTEMBED_CACHE_DIR = os.getenv('FASTEMBED_CACHE_DIR', '')
LOCAL_FILES_ONLY = os.getenv('LOCAL_FILES_ONLY', 'false').lower() == 'true'
HF_HUB_OFFLINE = os.getenv('HF_HUB_OFFLINE', 'false').lower() == 'true'
TRANSFORMERS_OFFLINE = os.getenv('TRANSFORMERS_OFFLINE', 'false').lower() == 'true'
QDRANT_API_KEY = os.getenv('QDRANT_API_KEY', '')