from fastapi import FastAPI
from pydantic import BaseModel
from find import Find_answer
from agent import Agent
from embending import Embedding
from index_documents import create_index
import pickle


class Question (BaseModel):
    query: str

app = FastAPI()
history_HYDE = []
agent = Agent(max_context_messages=10)

@app.get("/")
async def root():
    return {"message": "Ручки FastAPI"}   

@app.post("/ask")
async def ask(query: Question):
    global history_HYDE
    with open("bm25_index.pkl", "rb") as f:
        bm25 = pickle.load(f)
    finder = Find_answer(query.query, bm25_index=bm25, history=history_HYDE)
    candidates = finder.find_answer()
    if candidates:
        # Опциональный реранжинг (берём топ-3)
        best = finder.reranked(query.query, candidates)
        # Генерируем ответ через агента
        answer, sources = agent.response(query.query, best, return_sources=True)
        # Обновляем историю (вопрос и ответ)
        finder.update_history(query.query, answer)
        history_HYDE = finder.history
        return {"answer": answer, "sources": sources}

@app.post("/load_documents/index/{idx}")
async def load_documents():
    create_index(recreate=True)
    return {"message": "Документы загружены и проиндексированы"}