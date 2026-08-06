"""As métricas, e o que cada uma esconde.

**hit@k** — a resposta apareceu entre os k primeiros? Binário por consulta. É a
métrica honesta quando o consumidor é um humano olhando uma lista, ou um LLM
recebendo k trechos: ou o trecho certo entrou no contexto, ou não entrou.

**MRR@k** — 1/posição do primeiro acerto, média sobre as consultas. Distingue
"acertou em primeiro" de "acertou em nono", coisa que hit@10 trata igual. É a
métrica que mostra ganho de reranking, porque reranker não traz documento novo:
ele só sobe o que já estava lá.

**starved** — quantas consultas voltaram com MENOS de k resultados. Não é
qualidade, é cobertura, e é o número que separa os dois modos de falha:

    léxico erra devolvendo POUCO   →  starved alto, hit baixo
    denso  erra devolvendo QUALQUER COISA →  starved zero, hit baixo

Sem essa coluna, as duas falhas aparecem como o mesmo hit@1 ruim, e a conclusão
sai invertida.

O que NÃO está medido, de propósito: nDCG (exigiria relevância graduada, e o
gabarito aqui é binário) e recall total (exigiria anotar o corpus inteiro por
consulta — 114 documentos × 37 consultas de julgamento manual).
"""

from __future__ import annotations

import statistics

from ..models import Hit, Query


def first_relevant_rank(hits: list[Hit], relevant: tuple[str, ...]) -> int | None:
    for hit in hits:
        if hit.doc_id in relevant:
            return hit.rank
    return None


def hit_at(rank: int | None, k: int) -> float:
    return 1.0 if rank is not None and rank <= k else 0.0


def reciprocal_rank(rank: int | None, k: int = 10) -> float:
    return 1.0 / rank if rank is not None and rank <= k else 0.0


def percentile(values: list[float], pct: float) -> float:
    """p95 com 37 amostras é grosso — e é justamente por isso que ele aparece.

    A latência que importa não é a média: é a cauda que o usuário sente. Com
    poucas consultas o p95 vira quase o máximo, o que já basta para separar
    "cross-encoder custa caro" de "custa muito caro".
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    idx = min(int(round(pct * (len(ordered) - 1))), len(ordered) - 1)
    return ordered[idx]


def summarize(
    rows: list[tuple[Query, list[Hit], float]], top_k: int
) -> dict[str, float]:
    """rows = [(consulta, resultados, latência em ms)]"""
    if not rows:
        return {}
    ranks = [first_relevant_rank(hits, q.relevant) for q, hits, _ in rows]
    latencies = [ms for _, _, ms in rows]
    returned = [len(hits) for _, hits, _ in rows]
    return {
        "hit_at_1": round(statistics.fmean(hit_at(r, 1) for r in ranks), 4),
        "hit_at_3": round(statistics.fmean(hit_at(r, 3) for r in ranks), 4),
        "hit_at_10": round(statistics.fmean(hit_at(r, 10) for r in ranks), 4),
        "mrr": round(statistics.fmean(reciprocal_rank(r) for r in ranks), 4),
        "query_ms_p50": round(percentile(latencies, 0.50), 2),
        "query_ms_p95": round(percentile(latencies, 0.95), 2),
        "starved_queries": sum(1 for n in returned if n < top_k),
        "returned_avg": round(statistics.fmean(returned), 2),
    }
