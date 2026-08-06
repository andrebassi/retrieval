"""Recuperação léxica — as duas formas que o Postgres permite sobre o mesmo índice.

`TsRankRetriever` usa o ranking nativo (`ts_rank_cd`). `Bm25Retriever` usa BM25,
escrito em SQL a partir das mesmas estatísticas. Os dois leem o MESMO `tsvector`
e recuperam o MESMO conjunto de candidatos — a única diferença entre eles é a
fórmula que ordena. Sem isso, qualquer diferença medida poderia ser tokenização.

A pergunta que este arquivo responde: **vale instalar uma extensão de BM25, ou o
Postgres que já está no projeto resolve?**
"""

from __future__ import annotations

import time

from ..config import SETTINGS
from ..models import Document, Hit
from .postgres import DocumentStore


def query_lexemes(store: DocumentStore, text: str) -> list[str]:
    """Passa a consulta pelo MESMO analisador que indexou os documentos.

    Tokenizar a consulta em Python seria a fonte clássica de discrepância: o
    stemmer do Postgres reduz "compressores" a "compressor", e um `split()`
    não. Aqui a pergunta e o documento veem o mesmo mundo.
    """
    with store.conn.cursor() as cur:
        cur.execute(
            "SELECT t.lexeme FROM unnest(to_tsvector(%s, %s)) AS t(lexeme, positions, weights)",
            (SETTINGS.text_search_config, text),
        )
        return [row[0] for row in cur.fetchall()]


class TsRankRetriever:
    """`ts_rank_cd` — o que o Postgres entrega sem instalar nada.

    Cover density: pontua pela proximidade entre os termos da consulta dentro do
    documento. NÃO é BM25 — não há IDF, e a normalização por comprimento é
    opcional e por flag. Termo raro e termo banal pesam igual.
    """

    name = "ts_rank"
    description = "ts_rank_cd nativo do Postgres sobre tsvector (sem IDF)"

    def __init__(self, store: DocumentStore, use_and: bool = False) -> None:
        self.store = store
        # `use_and` reproduz o `plainto_tsquery`, que é o que quase todo mundo
        # escreve: exige TODOS os termos. O experimento E4 mede o preço disso.
        self.use_and = use_and

    def reset(self) -> None:
        """Nada a fazer: o tsvector é coluna gerada, sempre em dia."""

    def index(self, docs: list[Document]) -> float:
        return 0.0

    def _tsquery(self, text: str) -> str | None:
        lexemes = query_lexemes(self.store, text)
        if not lexemes:
            return None
        joiner = " & " if self.use_and else " | "
        return joiner.join(f"'{lex}'" for lex in lexemes if "'" not in lex)

    def search(self, text: str, k: int) -> list[Hit]:
        expression = self._tsquery(text)
        if not expression:
            return []
        with self.store.conn.cursor() as cur:
            cur.execute(
                "SELECT doc_id, ts_rank_cd(tsv, q) AS score"
                " FROM documents, to_tsquery(%s, %s) AS q"
                " WHERE tsv @@ q ORDER BY score DESC, doc_id LIMIT %s",
                (SETTINGS.text_search_config, expression, k),
            )
            rows = cur.fetchall()
        return [Hit(doc_id=r[0], score=float(r[1]), rank=i + 1) for i, r in enumerate(rows)]


class Bm25Retriever:
    """BM25 calculado em SQL sobre `lex_terms` e `lex_stats`.

        score(D,Q) = Σ  IDF(q) · ( tf · (k1+1) ) / ( tf + k1·(1 − b + b·dl/avgdl) )
                   q∈Q

        IDF(q) = ln( 1 + (N − df + 0.5) / (df + 0.5) )

    Os dois termos da fórmula são o que falta no `ts_rank_cd`:

    - **IDF** faz termo raro valer mais que termo comum. É por isso que BM25
      acha um código de peça — ele aparece em um documento só.
    - **dl/avgdl** impede que documento longo ganhe por acumular ocorrência.

    A variante de IDF é a "probabilística com piso" (a de Lucene e Elasticsearch):
    o `1 +` de dentro do logaritmo evita valor negativo para termo presente em
    mais da metade do corpus, que na fórmula original de 1976 vira score
    negativo e desordena o ranking em corpus pequeno.
    """

    name = "bm25"

    def __init__(self, store: DocumentStore) -> None:
        self.store = store
        self.description = (
            f"BM25 em SQL (k1={SETTINGS.bm25_k1}, b={SETTINGS.bm25_b}) sobre o mesmo tsvector"
        )

    def reset(self) -> None:
        """As estatísticas são derivadas — quem manda apagar é o `index`."""

    def index(self, docs: list[Document]) -> float:
        # Não há embedding para calcular: o custo aqui é só desmontar o
        # tsvector em postings e medir o comprimento de cada documento.
        return self.store.build_lexical_stats()

    def search(self, text: str, k: int) -> list[Hit]:
        lexemes = query_lexemes(self.store, text)
        if not lexemes:
            return []
        with self.store.conn.cursor() as cur:
            cur.execute(
                """
                WITH stats AS (
                    SELECT (SELECT count(*)::float FROM documents) AS n_docs,
                           (SELECT avg(dl) FROM lex_stats)         AS avgdl
                ),
                df AS (
                    SELECT term, count(DISTINCT doc_id)::float AS df
                    FROM lex_terms WHERE term = ANY(%(terms)s) GROUP BY term
                )
                SELECT lt.doc_id,
                       sum(
                           ln(1 + (stats.n_docs - df.df + 0.5) / (df.df + 0.5))
                           * (lt.tf * (%(k1)s + 1))
                           / (lt.tf + %(k1)s * (1 - %(b)s + %(b)s * ls.dl / stats.avgdl))
                       ) AS score
                FROM lex_terms lt
                JOIN df       ON df.term = lt.term
                JOIN lex_stats ls ON ls.doc_id = lt.doc_id
                CROSS JOIN stats
                GROUP BY lt.doc_id
                ORDER BY score DESC, lt.doc_id
                LIMIT %(k)s
                """,
                {
                    "terms": lexemes,
                    "k1": SETTINGS.bm25_k1,
                    "b": SETTINGS.bm25_b,
                    "k": k,
                },
            )
            rows = cur.fetchall()
        return [Hit(doc_id=r[0], score=float(r[1]), rank=i + 1) for i, r in enumerate(rows)]
