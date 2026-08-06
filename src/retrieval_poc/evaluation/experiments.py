"""Quatro experimentos que a tabela principal não consegue contar.

A tabela de estratégias responde "qual ganhou". Estes quatro respondem "por
quê", e cada um foi escolhido porque desmonta uma crença comum:

  E1  fusão ponderada parece razoável — o normalizador é que não é.
  E2  `ts_rank_cd` é ranking léxico do Postgres, mas não é BM25.
  E3  reranker melhora — a pergunta é quanto custa cada ponto.
  E4  o léxico não erra: ele não devolve. É outro modo de falha.
"""

from __future__ import annotations

import json
import statistics
import time

from ..config import RESULTS_DIR, SETTINGS
from ..corpus import build as corpus_build
from ..corpus import queries as corpus_queries
from ..strategies.base import FusionStrategy
from ..strategies.fusion import reciprocal_rank_fusion, weighted_fusion
from ..strategies.registry import Stack
from .metrics import first_relevant_rank, percentile, reciprocal_rank

EXPERIMENTS_PATH = RESULTS_DIR / "experiments.json"


def _queries():
    docs = corpus_build.load()
    return corpus_queries.load(known_ids={d.doc_id for d in docs})


# ---------------------------------------------------------------- E1
def e1_scale_mismatch(stack: Stack) -> dict:
    """E1 — somar BM25 com cosseno é somar grandezas diferentes.

    Mede as duas coisas ao mesmo tempo: a amplitude bruta de cada braço (que é a
    causa) e o hit@1 de cada método de fusão (que é o efeito). Registra também
    quantas consultas têm documento presente em só uma das listas — cada uma
    dessas é um caso em que o min-max atribui 0 a um documento que ninguém
    julgou irrelevante.
    """
    queries = _queries()
    prefetch = SETTINGS.prefetch_limit
    bm25_spans, dense_spans = [], []
    only_one_side = 0
    total_pairs = 0
    rrf_hit, weighted_hit = [], []
    disagreements = []

    for query in queries:
        lex = stack.bm25.search(query.text, prefetch)
        den = stack.dense.search(query.text, prefetch)
        if lex:
            bm25_spans.append((min(h.score for h in lex), max(h.score for h in lex)))
        if den:
            dense_spans.append((min(h.score for h in den), max(h.score for h in den)))

        lex_ids = {h.doc_id for h in lex}
        den_ids = {h.doc_id for h in den}
        union = lex_ids | den_ids
        total_pairs += len(union)
        only_one_side += len(union - (lex_ids & den_ids))

        r_hits = reciprocal_rank_fusion([lex, den], SETTINGS.rrf_k, SETTINGS.top_k)
        w_hits = weighted_fusion([lex, den], [1.0, 1.0], SETTINGS.top_k)
        r_rank = first_relevant_rank(r_hits, query.relevant)
        w_rank = first_relevant_rank(w_hits, query.relevant)
        rrf_hit.append(1.0 if r_rank == 1 else 0.0)
        weighted_hit.append(1.0 if w_rank == 1 else 0.0)
        if r_rank != w_rank:
            disagreements.append(
                {
                    "query_id": query.query_id,
                    "family": query.family,
                    "text": query.text,
                    "rrf_rank": r_rank,
                    "weighted_rank": w_rank,
                }
            )

    return {
        "title": "E1 — escala não compara: min-max somado × RRF",
        "bm25_score_range": {
            "min": round(min(s[0] for s in bm25_spans), 4) if bm25_spans else None,
            "max": round(max(s[1] for s in bm25_spans), 4) if bm25_spans else None,
        },
        "dense_score_range": {
            "min": round(min(s[0] for s in dense_spans), 4) if dense_spans else None,
            "max": round(max(s[1] for s in dense_spans), 4) if dense_spans else None,
        },
        "candidates_in_one_list_only": only_one_side,
        "candidates_total": total_pairs,
        "pct_zeroed_by_minmax": round(100 * only_one_side / total_pairs, 1)
        if total_pairs
        else 0.0,
        "hit_at_1_rrf": round(statistics.fmean(rrf_hit), 4),
        "hit_at_1_weighted": round(statistics.fmean(weighted_hit), 4),
        "queries_ranked_differently": len(disagreements),
        "disagreements": disagreements,
    }


# ---------------------------------------------------------------- E2
def e2_ts_rank_vs_bm25(stack: Stack) -> dict:
    """E2 — mesmo conjunto recuperado, fórmula diferente.

    Os dois recuperadores leem o MESMO `tsvector` e aplicam o mesmo critério de
    casamento (OR entre os lexemas da consulta). O conjunto de candidatos é
    idêntico por construção — então toda diferença medida aqui é da fórmula de
    pontuação, e de mais nada. É a única forma de comparar `ts_rank_cd` com BM25
    sem que tokenização diferente contamine o resultado.

    O que muda: `ts_rank_cd` pontua por densidade de cobertura e proximidade dos
    termos, e **não tem IDF**. Termo raro e termo banal valem o mesmo. BM25
    pesa cada termo pela raridade no corpus.
    """
    queries = _queries()
    k = SETTINGS.top_k
    rows = []
    same_set = 0
    same_top1 = 0
    bm25_better = 0
    ts_better = 0

    for query in queries:
        bm = stack.bm25.search(query.text, k)
        ts = stack.ts_rank.search(query.text, k)
        if {h.doc_id for h in bm} == {h.doc_id for h in ts}:
            same_set += 1
        if bm and ts and bm[0].doc_id == ts[0].doc_id:
            same_top1 += 1
        bm_rank = first_relevant_rank(bm, query.relevant)
        ts_rank_ = first_relevant_rank(ts, query.relevant)
        bm_rr = reciprocal_rank(bm_rank)
        ts_rr = reciprocal_rank(ts_rank_)
        if bm_rr > ts_rr:
            bm25_better += 1
        elif ts_rr > bm_rr:
            ts_better += 1
        rows.append(
            {
                "query_id": query.query_id,
                "family": query.family,
                "bm25_rank": bm_rank,
                "ts_rank_cd_rank": ts_rank_,
            }
        )

    return {
        "title": "E2 — ts_rank_cd (sem IDF) × BM25 sobre o mesmo tsvector",
        "queries": len(queries),
        "identical_result_set": same_set,
        "identical_top1": same_top1,
        "bm25_ranks_relevant_higher": bm25_better,
        "ts_rank_ranks_relevant_higher": ts_better,
        "ties": len(queries) - bm25_better - ts_better,
        "detail": rows,
    }


# ---------------------------------------------------------------- E3
def e3_reranker_cost(stack: Stack) -> dict:
    """E3 — o reranker paga o que cobra?

    Compara a MESMA lista antes e depois do cross-encoder: o ganho é só de
    ordenação, porque o reranker não pode trazer documento que a fusão não
    devolveu. Registra o custo por consulta e o teto — quantas consultas já
    tinham o alvo na lista mas fora do topo, que é o único material com que ele
    tem como trabalhar.
    """
    if "rrf_rerank" not in stack.strategies:
        return {"title": "E3 — reranker", "skipped": "reranker desabilitado"}

    queries = _queries()
    k = SETTINGS.top_k
    prefetch = SETTINGS.prefetch_limit
    base: FusionStrategy = stack.strategies["rrf"]
    reranker = stack.strategies["rrf_rerank"].reranker

    base_ms, rerank_ms = [], []
    base_rr, rerank_rr = [], []
    base_hit1, rerank_hit1 = [], []
    fixable = 0
    promoted, demoted = 0, 0

    for query in queries:
        t0 = time.perf_counter()
        candidates = base.search(query.text, prefetch)
        base_elapsed = (time.perf_counter() - t0) * 1000

        t1 = time.perf_counter()
        reranked = reranker.rerank(query.text, candidates, k)
        rerank_elapsed = (time.perf_counter() - t1) * 1000

        before = first_relevant_rank(candidates[:k], query.relevant)
        after = first_relevant_rank(reranked, query.relevant)
        in_prefetch = first_relevant_rank(candidates, query.relevant)

        if in_prefetch is not None and (before is None or before > 1):
            fixable += 1
        if after is not None and (before is None or after < before):
            promoted += 1
        elif before is not None and (after is None or after > before):
            demoted += 1

        base_ms.append(base_elapsed)
        rerank_ms.append(base_elapsed + rerank_elapsed)
        base_rr.append(reciprocal_rank(before))
        rerank_rr.append(reciprocal_rank(after))
        base_hit1.append(1.0 if before == 1 else 0.0)
        rerank_hit1.append(1.0 if after == 1 else 0.0)

    delta_hit1 = statistics.fmean(rerank_hit1) - statistics.fmean(base_hit1)
    added_ms = statistics.fmean(rerank_ms) - statistics.fmean(base_ms)
    return {
        "title": "E3 — quanto custa cada ponto de hit@1 do cross-encoder",
        "prefetch": prefetch,
        "hit_at_1_before": round(statistics.fmean(base_hit1), 4),
        "hit_at_1_after": round(statistics.fmean(rerank_hit1), 4),
        "mrr_before": round(statistics.fmean(base_rr), 4),
        "mrr_after": round(statistics.fmean(rerank_rr), 4),
        "ms_p50_before": round(percentile(base_ms, 0.50), 2),
        "ms_p50_after": round(percentile(rerank_ms, 0.50), 2),
        "ms_p95_after": round(percentile(rerank_ms, 0.95), 2),
        "ms_added_avg": round(added_ms, 2),
        "queries_reranker_could_fix": fixable,
        "queries_promoted": promoted,
        "queries_demoted": demoted,
        "ms_per_point_of_hit_at_1": round(added_ms / (delta_hit1 * 100), 2)
        if delta_hit1 > 0
        else None,
    }


# ---------------------------------------------------------------- E4
def e4_the_void(stack: Stack) -> dict:
    """E4 — o léxico não erra, ele não devolve.

    Duas medições no mesmo lugar:

    1. **Silêncio.** Quantas consultas o BM25 devolve com menos de k
       resultados — e quantas devolve ZERO. O denso, na mesma linha, devolve
       sempre k, aconteça o que acontecer. Uma lista vazia é uma resposta
       honesta ("não tenho isso"); dez vizinhos aleatórios com score 0,42 não.

    2. **AND × OR.** O modo AND reproduz o `plainto_tsquery` que a maioria
       escreve sem pensar: exige TODOS os termos. Basta uma palavra da consulta
       não existir em nenhum documento para o resultado ser vazio.
    """
    queries = _queries()
    k = SETTINGS.top_k

    lex_returned, dense_returned = [], []
    lex_empty = 0
    and_returned, and_empty = [], 0

    stack.ts_rank.use_and = True
    for query in queries:
        and_hits = stack.ts_rank.search(query.text, k)
        and_returned.append(len(and_hits))
        if not and_hits:
            and_empty += 1
    stack.ts_rank.use_and = False

    per_family: dict[str, list[int]] = {}
    for query in queries:
        lex = stack.bm25.search(query.text, k)
        den = stack.dense.search(query.text, k)
        lex_returned.append(len(lex))
        dense_returned.append(len(den))
        if not lex:
            lex_empty += 1
        per_family.setdefault(query.family, []).append(len(lex))

    return {
        "title": "E4 — o vazio: silêncio do léxico × palpite do denso",
        "top_k": k,
        "bm25_avg_returned": round(statistics.fmean(lex_returned), 2),
        "bm25_starved": sum(1 for n in lex_returned if n < k),
        "bm25_empty": lex_empty,
        "dense_avg_returned": round(statistics.fmean(dense_returned), 2),
        "dense_starved": sum(1 for n in dense_returned if n < k),
        "bm25_returned_by_family": {
            fam: round(statistics.fmean(v), 2) for fam, v in per_family.items()
        },
        "and_mode_avg_returned": round(statistics.fmean(and_returned), 2),
        "and_mode_empty": and_empty,
        "or_mode_empty": lex_empty,
    }


def run_all(stack: Stack) -> dict:
    result = {
        "e1_scale": e1_scale_mismatch(stack),
        "e2_formula": e2_ts_rank_vs_bm25(stack),
        "e3_reranker": e3_reranker_cost(stack),
        "e4_void": e4_the_void(stack),
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    EXPERIMENTS_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result
