"""RAG API endpoints for document search and indexing."""

import pickle
import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional

from app.services.rag_finder import Find_answer
from app.services.agent_rag import Agent
from app.services.rag_indexer import create_index
from app.services.bm25_searcher import BM25Search
from dotenv import load_dotenv

load_dotenv()

router = APIRouter(prefix="/rag", tags=["rag"])

# Global instances
_agent: Optional[Agent] = None
_history = []


def get_agent() -> Agent:
    """Get or create RAG Agent singleton."""
    global _agent
    if _agent is None:
        _agent = Agent(max_context_messages=10)
    return _agent


class QuestionRequest(BaseModel):
    """Request model for RAG questions."""
    query: str


class SourceItem(BaseModel):
    """Source item from RAG response."""
    text: str
    filename: Optional[str] = None
    page: Optional[Any] = None
    metadata: Optional[Dict[str, Any]] = None


class RAGResponse(BaseModel):
    """Response model for RAG answers."""
    answer: str
    sources: List[Dict[str, Any]]


class IndexStatusResponse(BaseModel):
    """Response model for index status."""
    status: str
    message: str


@router.get("/health", response_model=dict)
async def rag_health():
    """Health check for RAG service."""
    return {
        "status": "healthy",
        "service": "RAG Pipeline",
        "gigachat_enabled": True
    }


@router.post("/ask", response_model=RAGResponse)
async def ask_question(request: QuestionRequest) -> RAGResponse:
    """
    Ask a question using RAG pipeline.

    Returns the answer with sources/citations from the indexed documents.
    """
    global _history

    try:
        index_path = os.getenv("INDEX_PATH", "bm25_index.pkl")

        # Load BM25 index
        if not os.path.exists(index_path):
            raise HTTPException(
                status_code=400,
                detail="BM25 index not found. Please load documents first."
            )

        with open(index_path, "rb") as f:
            bm25 = pickle.load(f)

        # Initialize finder with history
        finder = Find_answer(request.query, bm25_index=bm25, history=_history)

        # Find relevant documents
        candidates = finder.find_answer()

        if not candidates:
            return RAGResponse(
                answer="No relevant documents found for your query.",
                sources=[]
            )

        # Rerank candidates
        best = finder.reranked(request.query, candidates)

        # Generate answer using agent
        agent = get_agent()
        answer, sources = agent.response(request.query, best, return_sources=True)

        # Update history
        finder.update_history(request.query, answer)
        _history = finder.history

        return RAGResponse(answer=answer, sources=sources)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing query: {str(e)}")


@router.post("/load-documents", response_model=IndexStatusResponse)
async def load_documents() -> IndexStatusResponse:
    """
    Load and index all documents from the configured folder.

    Creates both Qdrant vector collection and BM25 index.
    """
    try:
        create_index(recreate=True)
        return IndexStatusResponse(
            status="success",
            message="Documents loaded and indexed successfully"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error loading documents: {str(e)}"
        )


@router.post("/reload-documents", response_model=IndexStatusResponse)
async def reload_documents() -> IndexStatusResponse:
    """
    Reload and recreate all indices from scratch.

    Useful for updating indices when documents are modified.
    """
    try:
        create_index(recreate=True)
        global _history
        _history = []  # Clear history on reload
        return IndexStatusResponse(
            status="success",
            message="Indices recreated successfully"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error reloading documents: {str(e)}"
        )


@router.post("/clear-history", response_model=dict)
async def clear_history() -> dict:
    """Clear the conversation history."""
    global _history, _agent
    _history = []
    if _agent:
        _agent.messages = [{"role": "system", "content": _agent.system_prompt}]
    return {"status": "success", "message": "History cleared"}
