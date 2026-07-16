import os
from processing import Processing
from embending import Embedding

def process_folder(folder_path="test", collection_name="my_docs", recreate_collection=False):
    """
    Обрабатывает все файлы в указанной папке и сохраняет чанки в Qdrant.
    
    :param folder_path: путь к папке с документами
    :param collection_name: имя коллекции в Qdrant
    :param recreate_collection: если True, удаляет существующую коллекцию перед загрузкой
    """
    # Проверяем существование папки
    if not os.path.isdir(folder_path):
        print(f"❌ Папка '{folder_path}' не найдена.")
        return

    # Если нужно пересоздать коллекцию
    if recreate_collection:
        emb = Embedding()
        emb.delete_collection(collection_name)
        print(f"Коллекция '{collection_name}' удалена. Будет создана заново.")

    # Поддерживаемые расширения (можно расширить)
    supported_extensions = ('.docx', '.pdf', '.txt', '.pptx', '.xlsx', '.html', '.doc')

    # Обходим все файлы в папке (не рекурсивно)
    for filename in os.listdir(folder_path):
        file_path = os.path.join(folder_path, filename)
        if not os.path.isfile(file_path):
            continue
        if not filename.lower().endswith(supported_extensions):
            print(f"⏭️ Пропускаем {filename}: неподдерживаемый формат")
            continue

        try:
            print(f"🔄 Обработка: {filename}")
            p = Processing(file_path)
            data = p.chunking()
            if not data:
                print(f"⚠️ Файл {filename} не дал чанков (возможно, пустой).")
                continue

            emb = Embedding()
            emb.save_to_qdrant(data, collection_name=collection_name)
            print(f"✅ {filename} загружен в Qdrant")

        except Exception as e:
            print(f"❌ Ошибка при обработке {filename}: {e}")

    print("🎯 Все файлы обработаны.")

# Использование:
if __name__ == "__main__":
    process_folder(folder_path="test", recreate_collection=False)