"""Montagem das estratégias comparadas — o "cmd/main" desta PoC.

Ponto único de wiring: quem avalia importa daqui e não conhece nenhum adapter
concreto. Somar uma estratégia (SPLADE, ColBERT, reranker de API) é escrever um
adapter que satisfaça `Retriever` ou `Reranker` e acrescentar uma entrada aqui.
Nada em `evaluation/` muda.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..adapters.dense_retriever import DenseRetriever
from ..adapters.lexical import Bm25Retriever, TsRankRetriever
from ..adapters.ollama_embedder import OllamaEmbedder
from ..adapters.postgres import DocumentStore, connect
from .base import FusionStrategy, RerankStrategy, SingleStrategy, Strategy

# Ordem de leitura, não alfabética: os dois caminhos puros primeiro, depois o
# que se faz com eles.
STRATEGY_ORDER = ["dense", "ts_rank", "bm25", "weighted", "rrf", "rrf_rerank"]


@dataclass
class Stack:
    """Tudo que uma rodada precisa, montado uma vez só."""

    store: DocumentStore
    embedder: OllamaEmbedder
    dense: DenseRetriever
    bm25: Bm25Retriever
    ts_rank: TsRankRetriever
    strategies: dict[str, Strategy]


def build_stack(with_reranker: bool = True) -> Stack:
    conn = connect()
    store = DocumentStore(conn)
    embedder = OllamaEmbedder()

    dense = DenseRetriever(store, embedder)
    bm25 = Bm25Retriever(store)
    ts_rank = TsRankRetriever(store)

    strategies: dict[str, Strategy] = {
        "dense": SingleStrategy(dense),
        "ts_rank": SingleStrategy(ts_rank),
        "bm25": SingleStrategy(bm25),
        # A fusão ingênua entra como estratégia de primeira classe, não como
        # nota de rodapé: ela é o que a maioria escreve primeiro.
        "weighted": FusionStrategy([bm25, dense], method="weighted", name="weighted"),
        "rrf": FusionStrategy([bm25, dense], method="rrf", name="rrf"),
    }

    if with_reranker:
        from ..adapters.cross_encoder import CrossEncoderReranker

        reranker = CrossEncoderReranker(texts_provider=store.texts)
        strategies["rrf_rerank"] = RerankStrategy(
            strategies["rrf"], reranker, name="rrf_rerank"
        )

    return Stack(
        store=store,
        embedder=embedder,
        dense=dense,
        bm25=bm25,
        ts_rank=ts_rank,
        strategies={n: strategies[n] for n in STRATEGY_ORDER if n in strategies},
    )
