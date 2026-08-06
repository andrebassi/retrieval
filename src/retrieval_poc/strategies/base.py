"""Estratégia = um jeito completo de responder a uma consulta.

Toda estratégia recebe texto e devolve `k` documentos ordenados. O avaliador não
sabe se por baixo houve um índice, dois, uma fusão ou uma rede neural relendo
cada candidato — é o que permite pôr todas na mesma tabela.
"""

from __future__ import annotations

from typing import Protocol

from ..config import SETTINGS
from ..models import Hit
from ..ports import Reranker, Retriever
from .fusion import reciprocal_rank_fusion, weighted_fusion


class Strategy(Protocol):
    name: str
    description: str

    def search(self, text: str, k: int) -> list[Hit]: ...


class SingleStrategy:
    """Um recuperador sozinho. O piso de comparação."""

    def __init__(self, retriever: Retriever, name: str | None = None) -> None:
        self.retriever = retriever
        self.name = name or retriever.name
        self.description = retriever.description

    def search(self, text: str, k: int) -> list[Hit]:
        return self.retriever.search(text, k)


class FusionStrategy:
    """Dois recuperadores, uma lista.

    Cada braço traz `prefetch_limit` candidatos — o mesmo número para os dois.
    Dar mais a um lado é escolher o vencedor antes de medir.
    """

    def __init__(
        self,
        retrievers: list[Retriever],
        method: str = "rrf",
        weights: list[float] | None = None,
        name: str | None = None,
        prefetch: int | None = None,
    ) -> None:
        self.retrievers = retrievers
        self.method = method
        self.weights = weights or [1.0] * len(retrievers)
        self.prefetch = prefetch or SETTINGS.prefetch_limit
        self.name = name or method
        arms = " + ".join(r.name for r in retrievers)
        formula = (
            f"RRF k={SETTINGS.rrf_k}" if method == "rrf" else f"soma min-max, pesos {self.weights}"
        )
        self.description = f"{arms} fundidos por {formula} (prefetch {self.prefetch} de cada)"

    def candidates(self, text: str) -> list[list[Hit]]:
        return [r.search(text, self.prefetch) for r in self.retrievers]

    def search(self, text: str, k: int) -> list[Hit]:
        lists = self.candidates(text)
        if self.method == "rrf":
            return reciprocal_rank_fusion(lists, SETTINGS.rrf_k, k)
        return weighted_fusion(lists, self.weights, k)


class RerankStrategy:
    """Recupera larga, reordena estreito.

    O `prefetch` daqui é o teto do que o reranker pode consertar: documento que
    não veio na lista não tem como ser promovido. Reranker não recupera nada —
    só reordena o que já chegou.
    """

    def __init__(
        self,
        base: Strategy,
        reranker: Reranker,
        prefetch: int | None = None,
        name: str | None = None,
    ) -> None:
        self.base = base
        self.reranker = reranker
        self.prefetch = prefetch or SETTINGS.prefetch_limit
        self.name = name or f"{base.name}+rerank"
        self.description = f"{base.name} → {reranker.description}, {self.prefetch} candidatos"

    def search(self, text: str, k: int) -> list[Hit]:
        return self.reranker.rerank(text, self.base.search(text, self.prefetch), k)
