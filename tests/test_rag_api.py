"""Tests for RAG API endpoints using FastAPI TestClient with mocked dependencies."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient

from app.api.v1.endpoints.rag_processing import router, get_rag_service
from app.services.rag_service import GigaChatRAGService


# ── Mock RAG Service ─────────────────────────────────────────────────────────


class MockRAGService(GigaChatRAGService):
    """Mock RAG service that returns predefined data without real dependencies."""

    def __init__(self):
        # Don't call super().__init__() to avoid initializing real services
        pass

    async def search(self, query, user_groups=None, top_k=20, history=None):
        return [
            {
                "id": "chunk-1",
                "content": f"Test content for: {query}",
                "document_id": 1,
                "chunk_index": 0,
                "score": 0.95,
                "rerank_score": 0.92,
            }
        ]

    async def answer(self, query, user_groups=None, top_k=5, history=None):
        return {
            "answer": f"This is the answer to: {query}",
            "confidence": 0.95,
            "citations": [{"document_id": 1, "chunk_index": 0, "score": 0.92}],
            "chunks": [
                {
                    "id": "chunk-1",
                    "content": f"Test content for: {query}",
                    "document_id": 1,
                    "chunk_index": 0,
                    "score": 0.95,
                }
            ],
        }

    async def generate_hyde(self, query, history=None, split_chunks=True, max_chunks=5):
        return [f"HyDE chunk 1 for: {query}", f"HyDE chunk 2 for: {query}"]

    def index_document(self, file_path, document_id=None, db=None):
        return [{"id": "point-1", "payload": {"content": "test"}}]


# ── Override dependencies ────────────────────────────────────────────────────


def _override_get_rag_service() -> MockRAGService:
    return MockRAGService()


def _override_get_current_user():
    """Mock authenticated user."""
    from app.models.user import User
    user = User(id=1, username="testuser", email="test@test.com", is_active=True)
    return user


def _override_get_current_user_groups():
    """Mock user groups."""
    return [1, 2, 3]


def _override_get_db():
    """Mock DB session."""
    return None


# ── TestClient setup ─────────────────────────────────────────────────────────


@pytest.fixture
def client():
    """Create TestClient with overridden dependencies."""
    from fastapi import FastAPI
    from app.api.deps import get_current_user, get_current_user_groups
    from app.core.config import get_db

    app = FastAPI()
    app.include_router(router)

    app.dependency_overrides[get_rag_service] = _override_get_rag_service
    app.dependency_overrides[get_current_user] = _override_get_current_user
    app.dependency_overrides[get_current_user_groups] = _override_get_current_user_groups
    app.dependency_overrides[get_db] = _override_get_db

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


# ── Tests ────────────────────────────────────────────────────────────────────


class TestRAGSearchEndpoint:
    """POST /api/v1/rag/search tests."""

    def test_successful_search(self, client):
        response = client.post(
            "/rag/search",
            json={"query": "test query", "user_groups": [1, 2]},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["chunks"]) == 1
        assert data["total"] == 1
        assert data["chunks"][0]["content"] == "Test content for: test query"

    def test_search_minimal(self, client):
        response = client.post(
            "/rag/search",
            json={"query": "test"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1

    def test_search_with_history(self, client):
        response = client.post(
            "/rag/search",
            json={
                "query": "test",
                "history": [{"role": "user", "content": "prev"}],
            },
        )
        assert response.status_code == 200

    def test_search_invalid_top_k(self, client):
        response = client.post(
            "/rag/search",
            json={"query": "test", "top_k": 0},
        )
        assert response.status_code == 422  # Validation error

    def test_search_missing_query(self, client):
        response = client.post(
            "/rag/search",
            json={},
        )
        assert response.status_code == 422  # Validation error


class TestRAGAnswerEndpoint:
    """POST /api/v1/rag/answer tests."""

    def test_successful_answer(self, client):
        response = client.post(
            "/rag/answer",
            json={"query": "What is the revenue?"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["answer"] == "This is the answer to: What is the revenue?"
        assert data["confidence"] == 0.95
        assert len(data["citations"]) == 1
        assert len(data["chunks"]) == 1

    def test_answer_with_user_groups(self, client):
        response = client.post(
            "/rag/answer",
            json={"query": "test", "user_groups": [1, 2, 3]},
        )
        assert response.status_code == 200

    def test_answer_with_history(self, client):
        response = client.post(
            "/rag/answer",
            json={
                "query": "test",
                "history": [{"role": "user", "content": "prev question"}],
            },
        )
        assert response.status_code == 200

    def test_answer_invalid_top_k(self, client):
        response = client.post(
            "/rag/answer",
            json={"query": "test", "top_k": 0},
        )
        assert response.status_code == 422


class TestRAGHydeEndpoint:
    """POST /api/v1/rag/hyde tests."""

    def test_successful_hyde(self, client):
        response = client.post(
            "/rag/hyde",
            json={"query": "test query"},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["chunks"]) == 2
        assert "HyDE chunk 1" in data["chunks"][0]

    def test_hyde_custom_params(self, client):
        response = client.post(
            "/rag/hyde",
            json={"query": "test", "split_chunks": False, "max_chunks": 3},
        )
        assert response.status_code == 200

    def test_hyde_with_history(self, client):
        response = client.post(
            "/rag/hyde",
            json={
                "query": "test",
                "history": [{"role": "user", "content": "prev"}],
            },
        )
        assert response.status_code == 200


class TestRAGIndexEndpoint:
    """POST /api/v1/rag/index tests."""

    def test_successful_index(self, client):
        response = client.post(
            "/rag/index",
            json={"file_path": "/path/to/doc.pdf", "document_id": 42},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["points_count"] == 1

    def test_index_without_document_id(self, client):
        response = client.post(
            "/rag/index",
            json={"file_path": "/path/to/doc.pdf"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_index_missing_file_path(self, client):
        response = client.post(
            "/rag/index",
            json={},
        )
        assert response.status_code == 422