"""Roda todas as estratégias sobre todas as consultas e escreve os resultados.

Regra de justiça, e ela é o que dá validade à comparação: **mesmo corpus, mesmo
índice, mesmas consultas, mesmo top_k**. A única coisa que muda entre uma linha
e outra da tabela é a estratégia. Se algo mais mudar, a tabela mede a diferença
errada.
"""

from __future__ import annotations

import json
import time

from ..config import RESULTS_DIR, SETTINGS
from ..corpus import build as corpus_build
from ..corpus import queries as corpus_queries
from ..models import Query
from ..strategies.registry import Stack
from .metrics import summarize

RESULT_PATH = RESULTS_DIR / "evaluation.json"


def run_strategy(strategy, queries: list[Query], top_k: int):
    rows = []
    detail = []
    for query in queries:
        started = time.perf_counter()
        hits = strategy.search(query.text, top_k)
        elapsed_ms = (time.perf_counter() - started) * 1000
        rows.append((query, hits, elapsed_ms))
        detail.append(
            {
                "query_id": query.query_id,
                "family": query.family,
                "text": query.text,
                "returned": len(hits),
                "ms": round(elapsed_ms, 2),
                "hits": [
                    {
                        "doc_id": h.doc_id,
                        "rank": h.rank,
                        "score": round(h.score, 6),
                        "relevant": h.doc_id in query.relevant,
                    }
                    for h in hits
                ],
            }
        )
    return rows, detail


def evaluate(stack: Stack, top_k: int | None = None) -> dict:
    top_k = top_k or SETTINGS.top_k
    docs = corpus_build.load()
    queries = corpus_queries.load(known_ids={d.doc_id for d in docs})
    families = corpus_queries.by_family(queries)

    report = {
        "corpus": {
            "documents": len(docs),
            "records": sum(1 for d in docs if d.kind == "record"),
            "prose": sum(1 for d in docs if d.kind == "prose"),
        },
        "queries": {
            "total": len(queries),
            **{fam: len(qs) for fam, qs in families.items()},
        },
        "settings": {
            "top_k": top_k,
            "prefetch_limit": SETTINGS.prefetch_limit,
            "rrf_k": SETTINGS.rrf_k,
            "bm25_k1": SETTINGS.bm25_k1,
            "bm25_b": SETTINGS.bm25_b,
            "dense_model": SETTINGS.dense_model,
            "reranker_model": SETTINGS.reranker_model,
            "text_search_config": SETTINGS.text_search_config,
        },
        "lexical": stack.store.lexical_summary(),
        "strategies": [],
    }

    details: dict[str, list] = {}
    for name, strategy in stack.strategies.items():
        rows, detail = run_strategy(strategy, queries, top_k)
        entry = {
            "strategy": name,
            "description": strategy.description,
            **summarize(rows, top_k),
            "by_family": {
                fam: summarize(
                    [r for r in rows if r[0].family == fam],
                    top_k,
                )
                for fam in families
            },
        }
        report["strategies"].append(entry)
        details[name] = detail

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (RESULTS_DIR / "hits.json").write_text(
        json.dumps(details, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report
