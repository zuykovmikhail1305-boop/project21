from embending import Embedding

import os

def delete_bm25_index(index_file="bm25_index.pkl"):
    """Удаляет файл с сохранённым BM25 индексом."""
    if os.path.exists(index_file):
        os.remove(index_file)
        print(f"✅ BM25 индекс удалён (файл {index_file})")
    else:
        print(f"⚠️ Файл {index_file} не найден, ничего не делаем.")


def delete_all_data(collection_name="my_docs", index_file="bm25_index.pkl"):
    """Удаляет коллекцию в Qdrant и файл BM25 индекса."""
    emb = Embedding()
    emb.clear_points(collection_name)
    delete_bm25_index(index_file)
    print("✅ Все данные удалены.")



# 4. Полная очистка (коллекция + BM25)
delete_all_data()