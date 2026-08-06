"""Lista as consultas em que duas estratégias discordam, nominalmente.

A tabela de médias diz *quanto* cada estratégia errou; ela não diz *onde*, e é
onde que muda decisão. Este utilitário lê `results/hits.json` e imprime os casos
que interessam para argumentar:

    léxico não achou × denso achou   → o argumento a favor do vetor
    léxico achou     × denso não     → o argumento a favor do índice invertido
    fusão piorou o que o motor puro já tinha certo → o preço de fundir

Uso: `task failures` (sem argumento imprime os três blocos).
"""

from __future__ import annotations

import json
from pathlib import Path

RESULTS = Path(__file__).resolve().parent.parent / "results"
TOP_FOR_GOOD = 1  # "achou" = trouxe o relevante em primeiro
TOP_FOR_BAD = 3   # "não achou" = relevante fora do top-3, ou ausente


def first_relevant_rank(entry: dict) -> int | None:
    for hit in entry["hits"]:
        if hit["relevant"]:
            return hit["rank"]
    return None


def load() -> dict[str, dict]:
    hits = json.loads((RESULTS / "hits.json").read_text(encoding="utf-8"))
    by_query: dict[str, dict] = {}
    for strategy, rows in hits.items():
        for row in rows:
            slot = by_query.setdefault(
                row["query_id"], {"text": row["text"], "family": row["family"]}
            )
            slot[strategy] = {
                "rank": first_relevant_rank(row),
                "returned": row["returned"],
            }
    return by_query


def show(title: str, rows: list[str]) -> None:
    print(f"\n── {title}  ({len(rows)} de 37)")
    for row in rows:
        print(row)


def main() -> int:
    by_query = load()

    def fmt(qid: str, slot: dict, left: str, right: str) -> str:
        lr, rr = slot[left]["rank"], slot[right]["rank"]
        return (
            f"  {qid} [{slot['family']}]\n"
            f"      \"{slot['text']}\"\n"
            f"      {left}: rank {lr} (devolveu {slot[left]['returned']})"
            f"  |  {right}: rank {rr}"
        )

    def worse(rank: int | None) -> bool:
        return rank is None or rank > TOP_FOR_BAD

    show(
        "léxico falhou, denso resolveu — o argumento a favor do vetor",
        [
            fmt(qid, slot, "bm25", "dense")
            for qid, slot in by_query.items()
            if worse(slot["bm25"]["rank"]) and slot["dense"]["rank"] == TOP_FOR_GOOD
        ],
    )
    show(
        "denso falhou, léxico resolveu — o argumento a favor do índice invertido",
        [
            fmt(qid, slot, "dense", "bm25")
            for qid, slot in by_query.items()
            if worse(slot["dense"]["rank"]) and slot["bm25"]["rank"] == TOP_FOR_GOOD
        ],
    )
    show(
        "a fusão PIOROU o que um motor puro já tinha em 1º — o preço de fundir",
        [
            fmt(qid, slot, "rrf", "dense")
            for qid, slot in by_query.items()
            if slot["rrf"]["rank"] not in (None, TOP_FOR_GOOD)
            and TOP_FOR_GOOD in (slot["dense"]["rank"], slot["bm25"]["rank"])
        ],
    )
    show(
        "o reranker REBAIXOU o relevante que a fusão já tinha entregue",
        [
            fmt(qid, slot, "rrf_rerank", "rrf")
            for qid, slot in by_query.items()
            if slot["rrf"]["rank"] is not None
            and (
                slot["rrf_rerank"]["rank"] is None
                or slot["rrf_rerank"]["rank"] > slot["rrf"]["rank"]
            )
        ],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
