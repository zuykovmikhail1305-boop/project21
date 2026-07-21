import os
import pickle
import glob
from processing import Processing
from embending import Embedding
from bm25_search import BM25Search
import os
from dotenv import load_dotenv
load_dotenv()

def create_index(
    folder_path="test",
    collection_name="my_docs",
    index_file="bm25_index.pkl",
    recreate=False,
    chunking_threshold=75
):
    """
    Создаёт коллекцию в Qdrant и BM25 индекс для всех документов в папке.
    
    :param folder_path: путь к папке с документами
    :param collection_name: имя коллекции в Qdrant
    :param index_file: файл для сохранения BM25 индекса
    :param recreate: если True, удаляет существующую коллекцию и индекс перед созданием
    :param chunking_threshold: порог для SemanticSplitterNodeParser
    """
    # Проверяем, существует ли папка
    if not os.path.isdir(folder_path):
        print(f"❌ Папка '{folder_path}' не найдена.")
        return

    # Поддерживаемые расширения (можно расширить)
    supported_extensions = ('.docx', '.pdf', '.txt', '.pptx', '.xlsx', '.html', '.doc', '.md')

    # 1. Сбор всех чанков из всех файлов
    print("📂 Сбор документов из папки:", folder_path)
    all_chunks = []
    for file_path in glob.glob(os.path.join(folder_path, '*')):
        if not os.path.isfile(file_path):
            continue
        if not file_path.lower().endswith(supported_extensions):
            print(f"⏭️ Пропускаем {os.path.basename(file_path)}: неподдерживаемый формат")
            continue
        print(f"🔄 Обработка: {os.path.basename(file_path)}")
        try:
            p = Processing(file_path)
            # Передаём порог для чанкинга (если метод chunking принимает threshold)
            chunks = p.chunking()  # если нужно, можно добавить параметр threshold
            if chunks:
                all_chunks.extend(chunks)
                print(f"   → Добавлено {len(chunks)} чанков")
            else:
                print(f"   ⚠️ Файл не дал чанков")
        except Exception as e:
            print(f"   ❌ Ошибка при обработке {file_path}: {e}")

    if not all_chunks:
        print("❌ Нет чанков для индексации.")
        return

    print(f"📦 Всего собрано {len(all_chunks)} чанков.")

    # 2. Работа с Qdrant
    emb = Embedding()
    if recreate:
        # Удаляем старую коллекцию, если она есть
        try:
            emb.delete_collection(collection_name)
            print(f"🗑️ Коллекция '{collection_name}' удалена.")
        except Exception as e:
            print(f"⚠️ Не удалось удалить коллекцию (возможно, её нет): {e}")

    # Сохраняем чанки в Qdrant (автоматически создаст коллекцию)
    print("💾 Сохранение в Qdrant...")
    emb.save_to_qdrant(all_chunks, collection_name=collection_name)
    print(f"✅ Сохранено {len(all_chunks)} точек в Qdrant.")

    # 3. Построение BM25 индекса
    if recreate and os.path.exists(index_file):
        os.remove(index_file)
        print(f"🗑️ Старый BM25 индекс удалён ({index_file})")

    print("🧠 Построение BM25 индекса...")
    bm25 = BM25Search()
    bm25.build_index(all_chunks)

    # Сохраняем индекс в файл
    with open(index_file, "wb") as f:
        pickle.dump(bm25, f)
    print(f"✅ BM25 индекс сохранён в {index_file}")

    print("\n🎯 Индексация завершена успешно!")
    print(f"   - Коллекция '{collection_name}' в Qdrant: {len(all_chunks)} точек")
    print(f"   - BM25 индекс: {len(all_chunks)} документов")

    return bm25

if __name__ == "__main__":
    # Пример использования
    # Если вы хотите пересоздать индексы с нуля, установите recreate=True
    create_index(folder_path="test", recreate=False)