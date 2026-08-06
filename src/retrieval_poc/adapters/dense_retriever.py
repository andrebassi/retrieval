"""Recuperação densa — pgvector, distância cosseno, índice HNSW."""

from __future__ import annotations

import time

import numpy as np

from ..models import Document, Hit
from ..ports import TextEmbedder
from .postgres import DocumentStore

BATCH = 16


class DenseRetriever:
    """Vizinho mais próximo no espaço do encoder.

    Devolve `k` resultados SEMPRE — existe vizinho mais próximo para qualquer
    ponto do espaço, inclusive para uma consulta sobre assunto que o corpus não
    cobre. É a diferença de natureza para o índice invertido: aqui não há o
    conceito de "não casou".
    """

    name = "dense"

    def __init__(self, store: DocumentStore, embedder: TextEmbedder) -> None:
        self.store = store
        self.embedder = embedder
        self.description = f"pgvector HNSW cosseno sobre {embedder.name} ({embedder.dim}d)"

    def reset(self) -> None:
        """O schema é do DocumentStore; aqui só se apaga o que é vetor."""
        with self.store.conn.cursor() as cur:
            cur.execute("DROP INDEX IF EXISTS documents_embedding_idx")
            cur.execute("UPDATE documents SET embedding = NULL")

    def index(self, docs: list[Document]) -> float:
        started = time.perf_counter()
        for offset in range(0, len(docs), BATCH):
            chunk = docs[offset : offset + BATCH]
            vectors = self.embedder.embed_batch([f"{d.title}. {d.text}" for d in chunk])
            with self.store.conn.cursor() as cur:
                cur.executemany(
                    "UPDATE documents SET embedding = %s WHERE doc_id = %s",
                    [(np.array(v, dtype=np.float32), d.doc_id) for v, d in zip(vectors, chunk)],
                )
        self.store.create_vector_index()
        return (time.perf_counter() - started) * 1000

    def search(self, text: str, k: int) -> list[Hit]:
        vector = np.array(self.embedder.embed(text), dtype=np.float32)
        with self.store.conn.cursor() as cur:
            cur.execute(
                # `<=>` é distância cosseno em [0, 2]. Invertida vira
                # similaridade em [-1, 1], que é como o resto da PoC lê score.
                "SELECT doc_id, 1 - (embedding <=> %s) AS score"
                " FROM documents WHERE embedding IS NOT NULL"
                " ORDER BY embedding <=> %s LIMIT %s",
                (vector, vector, k),
            )
            rows = cur.fetchall()
        return [Hit(doc_id=r[0], score=float(r[1]), rank=i + 1) for i, r in enumerate(rows)]
