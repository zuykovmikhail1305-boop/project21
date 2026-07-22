"""Новый сервис, который сохраняет идею RAG_Misha: parsing → chunking → HYDE → search → answer."""

from __future__ import annotations

import asyncio
import uuid
from typing import Optional

from sqlalchemy.orm import Session

from app.core import config
from app.services.embedder import EmbedderService
from app.services.gigachat_provider import GigaChatClient
from app.services.reranker import Reranker
from app.services.vector_store import VectorStore


class GigaChatRAGService:
    """RAG-пайплайн, сохраняющий идею RAG_Misha и использующий GigaChat."""

    def __init__(
        self,
        vector_store: Optional[VectorStore] = None,
        embedder: Optional[EmbedderService] = None,
        reranker: Optional[Reranker] = None,
    ):
        self.vector_store = vector_store or VectorStore()
        self.embedder = embedder or EmbedderService()
        self.reranker = reranker or Reranker()
        self.llm = GigaChatClient()
        self._use_gigachat = bool(
            getattr(config, "GIGACHAT_CLIENT_ID", "")
            and getattr(config, "GIGACHAT_CLIENT_SECRET", "")
        )

    def _build_hyde_prompt(self, query: str, history: Optional[list[dict]] = None) -> str:
        """Улучшенный HyDE prompt из RAG_Misha/find.py:47-60."""
        history_text = ""
        if history:
            history_text = "\n".join(
                f"{'Пользователь' if item.get('role') == 'user' else 'Ассистент'}: "
                f"{item.get('content', '')}" for item in history
            )

        return f"""Ты — генератор гипотетических документов для поиска (HyDE).
Твоя задача — по запросу пользователя создать короткий, связный текст, который выглядит как фрагмент реального документа, содержащего ответ на этот запрос.

История диалога (для контекста):
{history_text or 'История диалога пуста.'}

Текущий запрос пользователя: {query}

Учитывая историю, сгенерируй гипотетический документ, который отвечает на текущий запрос, но при этом учитывает предыдущие обсуждения.
Стиль текста должен быть максимально приближен к стилю документов в целевой коллекции (например, научная статья, техническая инструкция, энциклопедическая справка).
Фактическая точность не важна — главное — правдоподобие и релевантность теме.
Не добавляй вводных фраз, пояснений или мета-комментариев. Выведи только текст гипотетического документа.
Не учитывай в каком году ты был обучен, если пользователь просит найти документы из года, в котором ты не был ещё обучен, то просто создавай документ с учётом года пользователя.
Если запрос является уточнением, постарайся включить в документ информацию, связывающую его с предыдущим контекстом."""

    async def generate_hyde(
        self,
        query: str,
        history: Optional[list[dict]] = None,
        split_chunks: bool = True,
        max_chunks: int = 5,
    ) -> list[str]:
        """Генерация HyDE с разбиением на чанки для множественного поиска.

        Перенесено из RAG_Misha/find.py:100-140.
        Генерирует гипотетический документ через LLM, затем разбивает его
        на абзацы (чанки) для поиска по каждому чанку отдельно.

        Args:
            query: Запрос пользователя.
            history: История диалога.
            split_chunks: Если True (по умолчанию), возвращает список чанков.
            max_chunks: Максимальное число чанков.

        Returns:
            Список текстовых чанков HyDE-документа.
        """
        import logging
        logger = logging.getLogger(__name__)
        import time
        t0 = time.time()

        if not self._use_gigachat:
            # Улучшенный fallback: используем сам запрос как HyDE-документ,
            # разбивая его на отдельные фразы/предложения для более точного поиска
            logger.warning("=== DIAG: GigaChat not available, using query as HyDE fallback")
            # Разбиваем запрос на отдельные ключевые фразы для лучшего покрытия
            import re
            sentences = re.split(r'[,.!?;]+', query)
            sentences = [s.strip() for s in sentences if len(s.strip()) > 5]
            if not sentences:
                sentences = [query]
            # Добавляем вариации запроса для улучшения поиска
            hyde_chunks = list(set(sentences + [query]))
            logger.info("[TIMING] generate_hyde() fallback took %.2fs (n_chunks=%d)", time.time() - t0, len(hyde_chunks))
            return hyde_chunks[:max_chunks]
        else:
            prompt = self._build_hyde_prompt(query, history)
            # Асинхронный вызов LLM
            hyde_text = await self.llm._generate_text(
                prompt=prompt,
                system_prompt="Ты генерируешь гипотетический документ для поиска."
            )

        logger.info("[TIMING] generate_hyde() took %.2fs", time.time() - t0)

        if split_chunks:
            return self._split_hyde(hyde_text, max_chunks=max_chunks)
        return [hyde_text]

    @staticmethod
    def _rrf_fusion(
        results_lists: list[list[dict]],
        limit: int = 10,
        k: int = 60,
    ) -> list[dict]:
        """Обобщённый RRF для любого числа списков результатов.

        Перенесено из RAG_Misha/find.py:72-98.
        Каждый список должен содержать словари с ключом 'id'.
        Ранг определяется позицией элемента в списке (начиная с 1).

        Args:
            results_lists: Список списков результатов поиска.
            limit: Максимальное количество результатов после слияния.
            k: Параметр сглаживания RRF (по умолчанию 60).

        Returns:
            Объединённый список результатов, отсортированный по RRF score.
        """
        rrf_scores: dict[str, float] = {}
        items_by_id: dict[str, dict] = {}

        for lst in results_lists:
            for rank, item in enumerate(lst, start=1):
                item_id = str(item["id"])
                if item_id not in items_by_id:
                    items_by_id[item_id] = item
                rrf_scores[item_id] = rrf_scores.get(item_id, 0) + 1.0 / (rank + k)

        sorted_ids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)
        result = []
        for idx in sorted_ids[:limit]:
            item = items_by_id[idx]
            item["rrf_score"] = rrf_scores[idx]
            result.append(item)
        return result

    async def _search_sparse(self, query: str, user_groups: list[int], top_k: int = 20) -> list[dict]:
        """Sparse search (BM25) через hybrid_search VectorStore.

        Использует только sparse вектор (без dense), вызывая hybrid_search
        с пустым query_vector и переданным query_text.

        Args:
            query: Текст запроса для sparse поиска.
            user_groups: Список ID групп пользователя (для ACL).
            top_k: Количество результатов.

        Returns:
            Список чанков, найденных по BM25-подобному sparse поиску.
        """
        import logging
        logger = logging.getLogger(__name__)
        import time
        t0 = time.time()

        try:
            # Используем embedder для получения dense вектора запроса,
            # чтобы hybrid_search мог работать с dense + sparse prefetch
            query_vector = await self.embedder.embed_async(query)
            result = await self.vector_store.hybrid_search(
                query_vector=query_vector,
                user_groups=user_groups,
                query_text=query,
                top_k=top_k,
            )
            logger.info("[TIMING] _search_sparse() took %.2fs (n=%d)", time.time() - t0, len(result))
            return result
        except Exception as e:
            logger.error("[TIMING] _search_sparse() FAILED after %.2fs: %s", time.time() - t0, e)
            raise

    @staticmethod
    def _split_hyde(hyde_text: str, max_chunks: int = 5) -> list[str]:
        """Разбить HyDE-документ на чанки для множественного поиска.

        Перенесено из RAG_Misha/find.py:119-124.
        Разбивает текст по двойным переносам строки (абзацам).

        Args:
            hyde_text: Сгенерированный HyDE-документ.
            max_chunks: Максимальное количество чанков.

        Returns:
            Список текстовых чанков.
        """
        if not hyde_text:
            return []

        paragraphs = [p.strip() for p in hyde_text.split('\n\n') if p.strip()]
        if not paragraphs:
            return [hyde_text]

        return paragraphs[:max_chunks]

    async def search(
        self,
        query: str,
        user_groups: list[int],
        top_k: int = 20,
        history: Optional[list[dict]] = None,
    ) -> list[dict]:
        """Поиск релевантных чанков: dense + sparse + HyDE + RRF fusion.

        Многоэтапный поиск:
        1. Dense search (семантический поиск по эмбеддингам)
        2. Sparse search (BM25-подобный поиск по редким терминам)
        3. HyDE search (если мало результатов — генерация гипотетического документа
           и поиск по его чанкам)
        4. RRF fusion (объединение всех результатов через Reciprocal Rank Fusion)
        5. Reranking (Cross-Encoder для финальной сортировки)

        Args:
            query: Поисковый запрос.
            user_groups: Список ID групп пользователя (для ACL).
            top_k: Количество результатов поиска.
            history: История диалога для HyDE (список словарей с ключами 'role' и 'content').
        """
        import logging
        logger = logging.getLogger(__name__)
        import time
        t0 = time.time()

        # Асинхронный embed
        query_vector = await self.embedder.embed_async(query)
        logger.info("[TIMING] search() embed query took %.2fs", time.time() - t0)

        all_results_lists: list[list[dict]] = []

        # 1. Dense search
        try:
            t1 = time.time()
            dense_results = await self._search_with_vector_store(
                query_vector, user_groups, top_k=top_k
            )
            logger.info(
                "[TIMING] search() dense search took %.2fs (n=%d)",
                time.time() - t1, len(dense_results)
            )
            if dense_results:
                all_results_lists.append(dense_results)
            else:
                logger.warning("=== DIAG: Dense search returned 0 results")
        except Exception as e:
            logger.warning("Dense search failed: %s", e)

        # 2. Sparse search (BM25) через hybrid_search
        try:
            t2 = time.time()
            sparse_results = await self._search_sparse(query, user_groups, top_k=top_k)
            logger.info(
                "[TIMING] search() sparse search took %.2fs (n=%d)",
                time.time() - t2, len(sparse_results)
            )
            if sparse_results:
                all_results_lists.append(sparse_results)
            else:
                logger.warning("=== DIAG: Sparse search returned 0 results")
        except Exception as e:
            logger.warning("Sparse search failed: %s", e)

        # 3. HyDE search (если мало результатов или нет sparse)
        if len(all_results_lists) < 2 or not all_results_lists:
            logger.info("[TIMING] search() few results, trying HyDE...")
            try:
                t3 = time.time()
                hyde_chunks = await self.generate_hyde(query, history=history)
                logger.info("[TIMING] search() HyDE gen + split took %.2fs (n_chunks=%d)", time.time() - t3, len(hyde_chunks))

                for chunk in hyde_chunks:
                    chunk_vector = await self.embedder.embed_async(chunk)
                    chunk_dense = await self._search_with_vector_store(
                        chunk_vector, user_groups, top_k=top_k
                    )
                    if chunk_dense:
                        all_results_lists.append(chunk_dense)

                    chunk_sparse = await self._search_sparse(chunk, user_groups, top_k=top_k)
                    if chunk_sparse:
                        all_results_lists.append(chunk_sparse)

            except Exception as e:
                logger.warning("HyDE search failed: %s", e)

        # 4. RRF fusion
        if all_results_lists:
            t4 = time.time()
            fused = self._rrf_fusion(all_results_lists, limit=top_k)
            logger.info("[TIMING] search() RRF fusion took %.2fs (n=%d)", time.time() - t4, len(fused))
        else:
            fused = []
            logger.warning("=== DIAG: RRF fusion got 0 lists — no results from any search method!")

        # 5. Reranking (асинхронный)
        t5 = time.time()
        reranked = await self.reranker.rerank_async(query, fused, top_k=5)
        logger.info(
            "[TIMING] search() TOTAL took %.2fs (final=%d)",
            time.time() - t0, len(reranked)
        )
        logger.info("=== DIAG: search() final results: %d chunks, query=%s", len(reranked), query[:100])
        if reranked:
            logger.info("=== DIAG: First result: doc_id=%s, score=%.4f, content_preview=%s",
                        reranked[0].get("document_id"), reranked[0].get("score", 0),
                        reranked[0].get("content", "")[:100])
        return reranked

    async def _search_with_vector_store(
        self,
        query_vector: list[float],
        user_groups: list[int],
        top_k: int = 20,
    ) -> list[dict]:
        """Асинхронный поиск в Qdrant через VectorStore.

        Args:
            query_vector: Вектор запроса.
            user_groups: Список ID групп пользователя (для ACL).
            top_k: Количество результатов.

        Returns:
            Список чанков с метаданными.
        """
        import logging
        logger = logging.getLogger(__name__)
        import time
        t0 = time.time()

        try:
            result = await self.vector_store.search(
                query_vector=query_vector,
                user_groups=user_groups,
                top_k=top_k,
            )
            logger.info("[TIMING] _search_with_vector_store() took %.2fs (n=%d)", time.time() - t0, len(result))
            return result
        except Exception as e:
            logger.error("[TIMING] _search_with_vector_store() FAILED after %.2fs: %s", time.time() - t0, e)
            raise

    def _resolve_allowed_groups(
        self,
        document_id: int,
        db: Session,
    ) -> list[int]:
        """Определить список групп, имеющих доступ к документу.

        Использует ACL-правила из DocumentGroupPermission:
        1. Если есть allow-правила — возвращает их group_id.
        2. Если правил нет — при ACL_DEFAULT_DENY=True возвращает [0] (только admin),
           при ACL_DEFAULT_DENY=False возвращает [0] (публичный доступ).
        3. Deny-правила не учитываются на уровне Qdrant (фильтрация происходит
           на уровне приложения через check_access).

        Args:
            document_id: ID документа в БД.
            db: Сессия SQLAlchemy.

        Returns:
            Список ID групп, которым разрешён доступ.
        """
        from app.services.acl import get_allowed_group_ids

        allowed = get_allowed_group_ids(document_id, db)
        if allowed:
            return allowed

        # Если правил нет — используем значение по умолчанию
        # [0] = публичный доступ (все authenticated пользователи)
        return [0]

    def index_document(
        self,
        file_path: str,
        document_id: Optional[int] = None,
        db: Optional[Session] = None,
    ) -> list[dict]:
        """Проиндексировать документ по логике RAG_Misha: parsing → chunking → embed → Qdrant.

        Args:
            file_path: Путь к файлу документа.
            document_id: ID документа в БД (для ACL). Если None — используется [0] (public).
            db: Сессия SQLAlchemy (для ACL). Если None — используется [0] (public).

        Returns:
            Список точек, сохранённых в Qdrant.
        """
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"=== RAG index_document DEBUG: file_path={file_path}, document_id={document_id}")

        # Определяем allowed_groups для ACL
        allowed_groups: list[int] = [0]
        if document_id is not None and db is not None:
            try:
                allowed_groups = self._resolve_allowed_groups(document_id, db)
                logger.info(f"=== RAG DEBUG: Resolved allowed_groups={allowed_groups} for doc {document_id}")
            except Exception as e:
                logger.warning(f"=== RAG DEBUG: Failed to resolve allowed_groups: {e}, using [0]")

        try:
            logger.info("=== RAG DEBUG: Importing RAG_Misha.processing.Processing...")
            from RAG_Misha.processing import Processing
            logger.info("=== RAG DEBUG: Import successful")
        except Exception as e:
            logger.error(f"=== RAG DEBUG: Import failed: {e}", exc_info=True)
            raise

        logger.info(f"=== RAG DEBUG: Creating Processing instance...")
        processor = Processing(file_path)
        logger.info(f"=== RAG DEBUG: Processing instance created, calling chunking()...")
        nodes = processor.chunking()
        logger.info(f"=== RAG DEBUG: chunking() returned {len(nodes) if nodes else 0} nodes")

        if not nodes:
            logger.warning("=== RAG DEBUG: No nodes returned from chunking, returning empty")
            return []

        points = []
        for index, node in enumerate(nodes):
            chunk_text = getattr(node, "text", None)
            if not chunk_text:
                logger.warning(f"=== RAG DEBUG: Node {index} has no text, skipping")
                continue

            logger.info(f"=== RAG DEBUG: Embedding chunk {index}/{len(nodes)} (len={len(chunk_text)})")
            embedding = self.embedder.embed(chunk_text)
            point_id = str(uuid.uuid4())

            # Извлекаем метаданные из ноды
            node_metadata = getattr(node, "metadata", {}) or {}

            # BUGFIX: document_id должен быть числовым ID документа из БД, а не file_path
            # Это необходимо для корректной работы citation и поиска
            doc_id_for_payload = document_id if document_id is not None else file_path

            payload = {
                "content": chunk_text,
                "document_id": doc_id_for_payload,
                "chunk_index": index,
                "chunk_type": "text",
                "metadata": node_metadata,
                "allowed_groups": allowed_groups,
            }
            points.append({
                "id": point_id,
                "vector": embedding,
                "payload": payload,
            })

        logger.info(f"=== RAG DEBUG: Generated {len(points)} points, upserting to vector store...")
        if points:
            self.vector_store.upsert_points(
                points=points,
                vector_size=len(points[0]["vector"]),
            )
            logger.info(f"=== RAG DEBUG: Upsert complete")

        return points

    async def answer(
        self,
        query: str,
        user_groups: list[int],
        top_k: int = 5,
        history: Optional[list[dict]] = None,
    ) -> dict:
        """Сформировать ответ на основании найденных чанков.

        Args:
            query: Вопрос пользователя.
            user_groups: Список ID групп пользователя (для ACL).
            top_k: Количество чанков для поиска.
            history: История диалога для HyDE (список словарей с ключами 'role' и 'content').
        """
        import logging
        logger = logging.getLogger(__name__)
        import time
        t0 = time.time()

        chunks = await self.search(query, user_groups, top_k=top_k, history=history)
        logger.info("[TIMING] answer() search took %.2fs (n_chunks=%d)", time.time() - t0, len(chunks))

        if not chunks:
            logger.warning("=== DIAG: answer() got 0 chunks — returning 'not found' response")
            return {
                "answer": "Я не нашел информации по вашему вопросу в доступных документах.",
                "confidence": 0.0,
                "citations": [],
                "chunks": [],
            }

        context_parts = []
        citations = []
        for chunk in chunks:
            doc_id = chunk.get('document_id')
            chunk_idx = chunk.get('chunk_index')
            content = chunk.get('content', '')
            logger.info("=== DIAG: answer() chunk: doc_id=%s (type=%s), chunk_idx=%s, content_len=%d",
                        doc_id, type(doc_id).__name__, chunk_idx, len(content))
            context_parts.append(
                f"[Источник: документ №{doc_id}, чанк №{chunk_idx}]\n{content}"
            )
            citations.append({
                "document_id": doc_id,
                "chunk_index": chunk_idx,
                "score": chunk.get("rerank_score", chunk.get("score", 0)),
            })

        context = "\n\n".join(context_parts)
        logger.info("=== DIAG: answer() context built: %d chars, %d citations", len(context), len(citations))

        if not self._use_gigachat:
            logger.warning("=== DIAG: _use_gigachat=False — using raw context as answer (no LLM)")
            answer = (
                f"На основании найденного контекста: \n\n{context[:1500]}"
            )
        else:
            t1 = time.time()
            # Асинхронный вызов LLM
            logger.info("=== DIAG: Calling LLM with context (len=%d) and query=%s", len(context), query[:100])
            answer = await self.llm._generate_text(
                prompt=query,
                system_prompt=(
                    "Ты — ассистент по корпоративным документам. "
                    "Отвечай только на основе предоставленного контекста. "
                    "Если информации недостаточно, честно скажи об этом.\n\n"
                    f"Контекст:\n{context}"
                ),
            )
            logger.info("[TIMING] answer() LLM generate took %.2fs (answer_len=%d)", time.time() - t1, len(answer))

        logger.info("[TIMING] answer() TOTAL took %.2fs", time.time() - t0)
        return {
            "answer": answer,
            "confidence": 0.9,
            "citations": citations,
            "chunks": chunks,
        }
