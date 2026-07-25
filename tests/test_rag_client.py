"""Tests for RAGClient HTTP client using httpx.MockTransport."""

from __future__ import annotations

import json

import pytest
import httpx
from httpx import AsyncClient, Request, Response

from app.services.rag_client import RAGClient


def _mock_response(status_code: int = 200, json_data: dict | None = None, text: str = "") -> Response:
    """Create a mock HTTP response."""
    if json_data is not None:
        text = json.dumps(json_data)
    return Response(status_code=status_code, text=text)


def _body(request: Request) -> dict:
    """Extract JSON body from a request."""
    return json.loads(request.content)


class TestRAGClientInit:
    """RAGClient initialization tests."""

    def test_default_base_url(self):
        client = RAGClient()
        assert client.base_url == "http://localhost:8000/api/v1"
        assert client.token == ""

    def test_custom_base_url(self):
        client = RAGClient(base_url="http://test:9000/api/v1")
        assert client.base_url == "http://test:9000/api/v1"

    def test_custom_token(self):
        client = RAGClient(token="test-token-123")
        assert client.token == "test-token-123"

    def test_headers_with_token(self):
        client = RAGClient(token="test-token")
        headers = client._headers
        assert headers["Authorization"] == "Bearer test-token"
        assert headers["Content-Type"] == "application/json"

    def test_headers_without_token(self):
        client = RAGClient()
        headers = client._headers
        assert "Authorization" not in headers
        assert headers["Content-Type"] == "application/json"

    def test_base_url_strips_trailing_slash(self):
        client = RAGClient(base_url="http://test:8000/api/v1/")
        assert client.base_url == "http://test:8000/api/v1"


class TestRAGClientSearch:
    """RAGClient.search() tests."""

    async def test_successful_search(self):
        """Test successful search returns chunks."""
        async def handler(request: Request) -> Response:
            assert request.url.path == "/api/v1/rag/search"
            assert request.method == "POST"
            body = _body(request)
            assert body["query"] == "test query"
            assert body["user_groups"] == [1, 2]
            return _mock_response(json_data={"chunks": [{"id": "1", "content": "test"}], "total": 1})

        client = RAGClient()
        client._client = AsyncClient(transport=httpx.MockTransport(handler))

        chunks = await client.search(query="test query", user_groups=[1, 2])

        assert len(chunks) == 1
        assert chunks[0]["id"] == "1"
        assert chunks[0]["content"] == "test"

    async def test_search_with_token(self):
        """Test search sends Authorization header."""
        async def handler(request: Request) -> Response:
            assert request.headers["Authorization"] == "Bearer secret-token"
            return _mock_response(json_data={"chunks": [], "total": 0})

        client = RAGClient(token="secret-token")
        client._client = AsyncClient(transport=httpx.MockTransport(handler))

        await client.search(query="test")

    async def test_search_empty_result(self):
        """Test search with empty result."""
        async def handler(request: Request) -> Response:
            return _mock_response(json_data={"chunks": [], "total": 0})

        client = RAGClient()
        client._client = AsyncClient(transport=httpx.MockTransport(handler))

        chunks = await client.search(query="test")

        assert chunks == []

    async def test_search_http_error(self):
        """Test search raises on HTTP error."""
        async def handler(request: Request) -> Response:
            return _mock_response(status_code=500, text="Internal Server Error")

        client = RAGClient()
        client._client = AsyncClient(transport=httpx.MockTransport(handler))

        with pytest.raises(httpx.HTTPStatusError):
            await client.search(query="test")

    async def test_search_payload(self):
        """Test search sends correct JSON payload."""
        async def handler(request: Request) -> Response:
            body = _body(request)
            assert body["query"] == "test query"
            assert body["user_groups"] == [1, 2]
            assert body["top_k"] == 15
            assert body["history"] == [{"role": "user", "content": "hello"}]
            return _mock_response(json_data={"chunks": [], "total": 0})

        client = RAGClient()
        client._client = AsyncClient(transport=httpx.MockTransport(handler))

        await client.search(
            query="test query",
            user_groups=[1, 2],
            top_k=15,
            history=[{"role": "user", "content": "hello"}],
        )


class TestRAGClientAnswer:
    """RAGClient.answer() tests."""

    async def test_successful_answer(self):
        """Test successful answer returns full response."""
        async def handler(request: Request) -> Response:
            assert request.url.path == "/api/v1/rag/answer"
            return _mock_response(json_data={
                "answer": "Test answer",
                "confidence": 0.95,
                "citations": [{"document_id": 1, "chunk_index": 0, "score": 0.9}],
                "chunks": [{"id": "1", "content": "test"}],
            })

        client = RAGClient()
        client._client = AsyncClient(transport=httpx.MockTransport(handler))

        result = await client.answer(query="test question")

        assert result["answer"] == "Test answer"
        assert result["confidence"] == 0.95
        assert len(result["citations"]) == 1
        assert len(result["chunks"]) == 1

    async def test_answer_with_history(self):
        """Test answer sends history in payload."""
        expected_history = [{"role": "user", "content": "prev question"}]

        async def handler(request: Request) -> Response:
            body = _body(request)
            assert body["history"] == expected_history
            return _mock_response(json_data={"answer": "", "confidence": 0.0, "citations": [], "chunks": []})

        client = RAGClient()
        client._client = AsyncClient(transport=httpx.MockTransport(handler))

        await client.answer(query="test", history=expected_history)

    async def test_answer_http_error(self):
        """Test answer raises on HTTP error."""
        async def handler(request: Request) -> Response:
            return _mock_response(status_code=400, text='{"detail": "Bad request"}')

        client = RAGClient()
        client._client = AsyncClient(transport=httpx.MockTransport(handler))

        with pytest.raises(httpx.HTTPStatusError):
            await client.answer(query="test")


class TestRAGClientGenerateHyde:
    """RAGClient.generate_hyde() tests."""

    async def test_successful_hyde(self):
        """Test successful HyDE generation returns chunks."""
        async def handler(request: Request) -> Response:
            assert request.url.path == "/api/v1/rag/hyde"
            return _mock_response(json_data={"chunks": ["chunk1", "chunk2", "chunk3"]})

        client = RAGClient()
        client._client = AsyncClient(transport=httpx.MockTransport(handler))

        chunks = await client.generate_hyde(query="test query")

        assert len(chunks) == 3
        assert chunks == ["chunk1", "chunk2", "chunk3"]

    async def test_hyde_empty_result(self):
        """Test HyDE with empty result."""
        async def handler(request: Request) -> Response:
            return _mock_response(json_data={"chunks": []})

        client = RAGClient()
        client._client = AsyncClient(transport=httpx.MockTransport(handler))

        chunks = await client.generate_hyde(query="test")
        assert chunks == []

    async def test_hyde_custom_params(self):
        """Test HyDE sends custom parameters."""
        async def handler(request: Request) -> Response:
            body = _body(request)
            assert body["split_chunks"] is False
            assert body["max_chunks"] == 3
            return _mock_response(json_data={"chunks": []})

        client = RAGClient()
        client._client = AsyncClient(transport=httpx.MockTransport(handler))

        await client.generate_hyde(query="test", split_chunks=False, max_chunks=3)


class TestRAGClientIndexDocument:
    """RAGClient.index_document() tests."""

    async def test_successful_index(self):
        """Test successful index returns empty list (API doesn't return points)."""
        async def handler(request: Request) -> Response:
            assert request.url.path == "/api/v1/rag/index"
            return _mock_response(json_data={"status": "ok", "points_count": 5, "message": "Success"})

        client = RAGClient()
        client._client = AsyncClient(transport=httpx.MockTransport(handler))

        result = await client.index_document(file_path="/path/to/doc.pdf", document_id=42)

        assert result == []

    async def test_index_without_document_id(self):
        """Test index without document_id."""
        async def handler(request: Request) -> Response:
            body = _body(request)
            assert body["file_path"] == "/path/to/doc.pdf"
            assert body["document_id"] is None
            return _mock_response(json_data={"status": "ok", "points_count": 0, "message": "Success"})

        client = RAGClient()
        client._client = AsyncClient(transport=httpx.MockTransport(handler))

        await client.index_document(file_path="/path/to/doc.pdf")

    async def test_index_http_error(self):
        """Test index raises on HTTP error."""
        async def handler(request: Request) -> Response:
            return _mock_response(status_code=500, text="Error")

        client = RAGClient()
        client._client = AsyncClient(transport=httpx.MockTransport(handler))

        with pytest.raises(httpx.HTTPStatusError):
            await client.index_document(file_path="/path/to/doc.pdf")


class TestRAGClientClose:
    """RAGClient.close() tests."""

    async def test_close(self):
        """Test close doesn't raise."""
        client = RAGClient()
        await client.close()  # should not raise