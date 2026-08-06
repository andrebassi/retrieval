"""Carrega o gabarito e valida que ele ainda faz sentido.

A validação não é zelo: gabarito que aponta para documento inexistente produz
uma métrica que parece medida e é ruído. Falhar aqui é barato; descobrir depois
que a tabela do README compara estratégias contra um alvo ausente, não.
"""

from __future__ import annotations

import yaml

from ..config import DATA_DIR
from ..models import Query

QUERIES_YAML = DATA_DIR / "queries.yaml"
FAMILIES = ("literal", "conceptual", "hybrid")


def load(known_ids: set[str] | None = None) -> list[Query]:
    raw = yaml.safe_load(QUERIES_YAML.read_text(encoding="utf-8"))
    queries = [
        Query(
            query_id=item["id"],
            text=item["text"],
            family=item["family"],
            relevant=tuple(item["relevant"]),
            note=item.get("note", ""),
        )
        for item in raw["queries"]
    ]

    bad_family = [q.query_id for q in queries if q.family not in FAMILIES]
    if bad_family:
        raise SystemExit(f"família desconhecida em: {bad_family}")

    if known_ids is not None:
        missing = {
            q.query_id: [d for d in q.relevant if d not in known_ids]
            for q in queries
            if any(d not in known_ids for d in q.relevant)
        }
        if missing:
            raise SystemExit(f"gabarito aponta para documento inexistente: {missing}")

    return queries


def by_family(queries: list[Query]) -> dict[str, list[Query]]:
    return {fam: [q for q in queries if q.family == fam] for fam in FAMILIES}
