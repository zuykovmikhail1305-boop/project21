"""Tests for RAG API Pydantic schemas."""

import pytest
from pydantic import ValidationError

from app.schemas.rag import (
    RAGSearchRequest,
    RAGSearchResponse,
    RAGAnswerRequest,
    RAGAnswerResponse,
    RAGHydeRequest,
    RAGHydeResponse,
    RAGIndexRequest,
    RAGIndexResponse,
)


class TestRAGSearchRequest:
    """RAGSearchRequest schema tests."""

    def test_valid_request(self):
        req = RAGSearchRequest(query="test query", user_groups=[1, 2])
        assert req.query == "test query"
        assert req.user_groups == [1, 2]
        assert req.top_k == 20  # default
        assert req.history is None

    def test_minimal_request(self):
        req = RAGSearchRequest(query="test")
        assert req.query == "test"
        assert req.user_groups == []
        assert req.top_k == 20

    def test_with_history(self):
        req = RAGSearchRequest(
            query="test",
            history=[{"role": "user", "content": "hello"}],
        )
        assert len(req.history) == 1
        assert req.history[0]["role"] == "user"

    def test_custom_top_k(self):
        req = RAGSearchRequest(query="test", top_k=10)
        assert req.top_k == 10

    def test_invalid_top_k_zero(self):
        with pytest.raises(ValidationError):
            RAGSearchRequest(query="test", top_k=0)

    def test_invalid_top_k_negative(self):
        with pytest.raises(ValidationError):
            RAGSearchRequest(query="test", top_k=-1)

    def test_invalid_top_k_too_large(self):
        with pytest.raises(ValidationError):
            RAGSearchRequest(query="test", top_k=200)

    def test_empty_query_allowed(self):
        """Пустая строка query допустима (Pydantic не валидирует min_length по умолчанию)."""
        req = RAGSearchRequest(query="")
        assert req.query == ""


class TestRAGSearchResponse:
    """RAGSearchResponse schema tests."""

    def test_empty_response(self):
        resp = RAGSearchResponse()
        assert resp.chunks == []
        assert resp.total == 0

    def test_with_chunks(self):
        resp = RAGSearchResponse(
            chunks=[{"id": "1", "content": "test", "score": 0.9}],
            total=1,
        )
        assert len(resp.chunks) == 1
        assert resp.total == 1


class TestRAGAnswerRequest:
    """RAGAnswerRequest schema tests."""

    def test_valid_request(self):
        req = RAGAnswerRequest(query="test question")
        assert req.query == "test question"
        assert req.top_k == 5  # default
        assert req.user_groups == []

    def test_custom_top_k(self):
        req = RAGAnswerRequest(query="test", top_k=10)
        assert req.top_k == 10

    def test_invalid_top_k(self):
        with pytest.raises(ValidationError):
            RAGAnswerRequest(query="test", top_k=0)


class TestRAGAnswerResponse:
    """RAGAnswerResponse schema tests."""

    def test_empty_response(self):
        resp = RAGAnswerResponse()
        assert resp.answer == ""
        assert resp.confidence == 0.0
        assert resp.citations == []
        assert resp.chunks == []

    def test_full_response(self):
        resp = RAGAnswerResponse(
            answer="Test answer",
            confidence=0.95,
            citations=[{"document_id": 1, "chunk_index": 0, "score": 0.9}],
            chunks=[{"id": "1", "content": "test"}],
        )
        assert resp.answer == "Test answer"
        assert resp.confidence == 0.95
        assert len(resp.citations) == 1
        assert len(resp.chunks) == 1


class TestRAGHydeRequest:
    """RAGHydeRequest schema tests."""

    def test_valid_request(self):
        req = RAGHydeRequest(query="test")
        assert req.query == "test"
        assert req.split_chunks is True
        assert req.max_chunks == 5

    def test_custom_params(self):
        req = RAGHydeRequest(query="test", split_chunks=False, max_chunks=3)
        assert req.split_chunks is False
        assert req.max_chunks == 3

    def test_invalid_max_chunks(self):
        with pytest.raises(ValidationError):
            RAGHydeRequest(query="test", max_chunks=0)

    def test_max_chunks_too_large(self):
        with pytest.raises(ValidationError):
            RAGHydeRequest(query="test", max_chunks=50)


class TestRAGHydeResponse:
    """RAGHydeResponse schema tests."""

    def test_empty_response(self):
        resp = RAGHydeResponse()
        assert resp.chunks == []

    def test_with_chunks(self):
        resp = RAGHydeResponse(chunks=["chunk1", "chunk2"])
        assert len(resp.chunks) == 2


class TestRAGIndexRequest:
    """RAGIndexRequest schema tests."""

    def test_valid_request(self):
        req = RAGIndexRequest(file_path="/path/to/doc.pdf")
        assert req.file_path == "/path/to/doc.pdf"
        assert req.document_id is None

    def test_with_document_id(self):
        req = RAGIndexRequest(file_path="/path/to/doc.pdf", document_id=42)
        assert req.document_id == 42

    def test_empty_file_path_allowed(self):
        """Пустая строка file_path допустима (Pydantic не валидирует min_length по умолчанию)."""
        req = RAGIndexRequest(file_path="")
        assert req.file_path == ""


class TestRAGIndexResponse:
    """RAGIndexResponse schema tests."""

    def test_ok_response(self):
        resp = RAGIndexResponse(status="ok", points_count=10, message="Success")
        assert resp.status == "ok"
        assert resp.points_count == 10
        assert resp.message == "Success"

    def test_error_response(self):
        resp = RAGIndexResponse(status="error", points_count=0, message="Failed")
        assert resp.status == "error"
        assert resp.points_count == 0