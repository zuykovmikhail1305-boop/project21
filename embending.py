from qdrant_client import QdrantClient, models

class Embending():
    def __init__(self, text):
        self.text = text
        
    def make_embending(self):
        client = QdrantClient(":memory:")

        client.create_collection(
        collection_name="my_docs",
        vectors_config=models.VectorParams(
            size=384,                 # размерность вашей модели
            distance=models.Distance.COSINE
        )
    )      