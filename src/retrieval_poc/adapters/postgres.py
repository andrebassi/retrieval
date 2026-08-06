"""Postgres — o corpus e os dois índices vivem na mesma tabela.

Uma tabela só, três formas de procurar nela:

    documents.tsv        índice GIN, invertido  -> ts_rank_cd e BM25
    documents.embedding  índice HNSW, cosseno   -> vizinho mais próximo

Isso é deliberado. Um dos números que a PoC persegue é o que o Postgres que já
está no projeto entrega sem nenhuma extensão nova, e para isso os dois caminhos
precisam ver exatamente o mesmo texto.
"""

from __future__ import annotations

import time

import psycopg
from pgvector.psycopg import register_vector

from ..config import SETTINGS
from ..models import Document


def connect() -> psycopg.Connection:
    conn = psycopg.connect(SETTINGS.database_url, autocommit=True)
    register_vector(conn)
    return conn


class DocumentStore:
    """Dono do schema. Os retrievers leem daqui; nenhum deles cria tabela."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def reset(self, dim: int) -> None:
        cfg = SETTINGS.text_search_config
        with self.conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS lex_terms")
            cur.execute("DROP TABLE IF EXISTS lex_stats")
            cur.execute("DROP TABLE IF EXISTS documents")
            cur.execute(
                f"""
                CREATE TABLE documents (
                    doc_id  text PRIMARY KEY,
                    title   text NOT NULL,
                    kind    text NOT NULL,
                    source  text NOT NULL,
                    body    text NOT NULL,
                    -- Coluna gerada: o tsvector nunca sai de sincronia com o
                    -- texto, e o stemmer usado fica registrado no schema.
                    tsv tsvector GENERATED ALWAYS AS (
                        to_tsvector('{cfg}', title || ' ' || body)
                    ) STORED,
                    embedding vector({dim})
                )
                """
            )
            cur.execute("CREATE INDEX documents_tsv_idx ON documents USING gin (tsv)")

    def insert(self, docs: list[Document]) -> None:
        with self.conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO documents (doc_id, title, kind, source, body)"
                " VALUES (%s, %s, %s, %s, %s)",
                [(d.doc_id, d.title, d.kind, d.source, d.text) for d in docs],
            )

    def create_vector_index(self) -> None:
        """HNSW só depois de todos os vetores gravados — construir antes é mais
        lento e o grafo sai pior."""
        with self.conn.cursor() as cur:
            cur.execute(
                "CREATE INDEX documents_embedding_idx ON documents"
                " USING hnsw (embedding vector_cosine_ops)"
            )

    def count(self) -> int:
        with self.conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM documents")
            return cur.fetchone()[0]

    def texts(self, doc_ids: list[str]) -> dict[str, str]:
        """Texto cru dos candidatos — o reranker precisa dele, não do vetor."""
        if not doc_ids:
            return {}
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT doc_id, title || '. ' || body FROM documents WHERE doc_id = ANY(%s)",
                (doc_ids,),
            )
            return {row[0]: row[1] for row in cur.fetchall()}

    def build_lexical_stats(self) -> float:
        """Desmonta o tsvector em (documento, termo, frequência).

        O `unnest(tsvector)` devolve lexema, posições e pesos — a frequência do
        termo no documento é o tamanho do vetor de posições. Usar isto em vez de
        tokenizar em Python garante que o BM25 desta PoC conte exatamente os
        mesmos termos que o `ts_rank_cd` do Postgres conta: as duas estratégias
        léxicas passam a diferir só na fórmula, que é o que se quer medir.
        """
        started = time.perf_counter()
        with self.conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS lex_terms")
            cur.execute("DROP TABLE IF EXISTS lex_stats")
            cur.execute(
                """
                CREATE TABLE lex_terms AS
                SELECT d.doc_id,
                       t.lexeme AS term,
                       coalesce(array_length(t.positions, 1), 1)::int AS tf
                FROM documents d, unnest(d.tsv) AS t(lexeme, positions, weights)
                """
            )
            cur.execute("CREATE INDEX lex_terms_term_idx ON lex_terms (term)")
            cur.execute("CREATE INDEX lex_terms_doc_idx ON lex_terms (doc_id)")
            # Comprimento do documento em termos indexados (não em caracteres):
            # é o `dl` da fórmula, e é o que o `b` do BM25 pesa.
            cur.execute(
                """
                CREATE TABLE lex_stats AS
                SELECT doc_id, sum(tf)::float AS dl FROM lex_terms GROUP BY doc_id
                """
            )
            cur.execute("CREATE INDEX lex_stats_doc_idx ON lex_stats (doc_id)")
        return (time.perf_counter() - started) * 1000

    def vector_dim(self) -> int:
        """Dimensão declarada na coluna, lida do catálogo.

        Serve ao canário do `verify`: coluna e modelo têm que concordar, e a
        única forma de saber é perguntar aos dois.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT atttypmod FROM pg_attribute"
                " WHERE attrelid = 'documents'::regclass AND attname = 'embedding'"
            )
            return int(cur.fetchone()[0])

    def lexical_summary(self) -> dict:
        with self.conn.cursor() as cur:
            # Duas consultas de propósito: juntar as tabelas antes do `avg`
            # ponderaria o comprimento médio pelo número de termos do documento,
            # e o resultado deixaria de ser o `avgdl` que a fórmula do BM25 usa.
            cur.execute("SELECT count(DISTINCT term), count(*) FROM lex_terms")
            terms, postings = cur.fetchone()
            cur.execute("SELECT avg(dl), min(dl), max(dl) FROM lex_stats")
            avgdl, mindl, maxdl = cur.fetchone()
            cur.execute("SELECT count(*) FROM (SELECT term FROM lex_terms GROUP BY term HAVING count(*) = 1) s")
            unique_terms = cur.fetchone()[0]
        return {
            "distinct_terms": terms,
            "postings": postings,
            "terms_in_one_doc": unique_terms,
            "avg_doc_length": round(float(avgdl), 2),
            "min_doc_length": int(mindl),
            "max_doc_length": int(maxdl),
        }
