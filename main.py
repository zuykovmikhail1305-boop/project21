from fastapi import FastAPI
from pydantic import BaseModel
from find import Find_answer
from index_documents import create_index


class Question (BaseModel):
    query: str

app = FastAPI()
history_HYDE = []


@app.get("/")
async def root():
    return {"message": "Ручки FastAPI"}   

@app.post("/ask")
async def ask(query: Question):
    finder = Find_answer()
    return {'answer': finder.find_answer(query.query)}
    

@app.post("/uploads/documents/{id}")
async def load_documents(id: str):
    create_index(file_path=None, id=id)
    return {"message": "Документы загружены и проиндексированы"}

