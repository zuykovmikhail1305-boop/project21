# ============================================================
# Stage 1: Builder — install dependencies
# ============================================================
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install system build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libmagic1 \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

# Install uv package manager
RUN pip install --no-cache-dir uv

WORKDIR /app

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock ./

# Install project dependencies (production only)
RUN uv sync --no-dev --frozen --no-cache

# Install gunicorn for production serving
RUN pip install --no-cache-dir gunicorn

# ============================================================
# Stage 2: Runtime — minimal image
# ============================================================
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    NODE_PATH="/usr/local/lib/node_modules"

# Install runtime system dependencies + Node.js + Marp CLI
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libmagic1 \
    libgl1 \
    curl \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g @marp-team/marp-cli \
    && npm cache clean --force

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

# Copy virtual environment and application code from builder
COPY --link --from=builder /app /app
COPY app/ /app/app/
COPY main.py /app/main.py

WORKDIR /app

USER appuser

EXPOSE 8000

CMD ["uvicorn", "main:fastapi_app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]