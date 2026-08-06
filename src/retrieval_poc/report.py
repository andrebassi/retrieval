"""Gera `results/REPORT.md` a partir do que foi medido.

O relatório é **derivado**: nasce dos JSON de `results/` e é reescrito por
inteiro a cada `task report`. Editar o arquivo à mão faz o texto discordar do
número na próxima rodada, e nenhum dos dois avisa.
"""

from __future__ import annotations

import json

from .config import RESULTS_DIR

EVAL = RESULTS_DIR / "evaluation.json"
EXPERIMENTS = RESULTS_DIR / "experiments.json"
REPORT = RESULTS_DIR / "REPORT.md"

LABEL = {
    "dense": "denso (bge-m3)",
    "ts_rank": "ts_rank_cd",
    "bm25": "BM25",
    "weighted": "fusão min-max",
    "rrf": "RRF",
    "rrf_rerank": "RRF + cross-encoder",
}


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _load(path):
    if not path.exists():
        raise SystemExit(f"faltou {path} — rode `task eval` e `task experiments`")
    return json.loads(path.read_text(encoding="utf-8"))


def render() -> str:
    ev = _load(EVAL)
    ex = _load(EXPERIMENTS)
    out: list[str] = []
    add = out.append

    corpus = ev["corpus"]
    queries = ev["queries"]
    cfg = ev["settings"]
    lex = ev["lexical"]

    add("# Resultados medidos\n")
    add(
        "> Gerado por `task report` a partir de `results/*.json`. "
        "Não editar à mão — a próxima rodada sobrescreve.\n"
    )
    add("## O que foi medido\n")
    add("| Item | Valor |")
    add("|---|---|")
    add(f"| Documentos indexados | {corpus['documents']} |")
    add(f"| — operacionais (`record`) | {corpus['records']} |")
    add(f"| — prosa (`prose`) | {corpus['prose']} |")
    add(f"| Consultas | {queries['total']} |")
    add(f"| — literais | {queries['literal']} |")
    add(f"| — conceituais | {queries['conceptual']} |")
    add(f"| — híbridas | {queries['hybrid']} |")
    add(f"| Modelo denso | `{cfg['dense_model']}` |")
    add(f"| Reranker | `{cfg['reranker_model']}` |")
    add(f"| Configuração textual do Postgres | `{cfg['text_search_config']}` |")
    add(f"| BM25 | k1={cfg['bm25_k1']}, b={cfg['bm25_b']} |")
    add(f"| RRF | k={cfg['rrf_k']} |")
    add(f"| top_k / prefetch | {cfg['top_k']} / {cfg['prefetch_limit']} |")
    add(f"| Termos distintos no índice léxico | {lex['distinct_terms']} |")
    add(f"| Postings (par termo–documento) | {lex['postings']} |")
    add(
        f"| Termos que ocorrem em UM só documento | {lex['terms_in_one_doc']} "
        f"({_pct(lex['terms_in_one_doc'] / lex['distinct_terms'])} do vocabulário) |"
    )
    add(
        f"| Tamanho de documento em lexemas | min {lex['min_doc_length']}, "
        f"média {lex['avg_doc_length']}, máx {lex['max_doc_length']} |"
    )
    add("")

    add("## Placar geral\n")
    add("| Estratégia | hit@1 | hit@3 | hit@10 | MRR@10 | p50 | p95 | consultas famintas |")
    add("|---|---:|---:|---:|---:|---:|---:|---:|")
    for s in ev["strategies"]:
        add(
            f"| {LABEL.get(s['strategy'], s['strategy'])} | {_pct(s['hit_at_1'])} | "
            f"{_pct(s['hit_at_3'])} | {_pct(s['hit_at_10'])} | {s['mrr']:.3f} | "
            f"{s['query_ms_p50']:.1f} ms | {s['query_ms_p95']:.1f} ms | "
            f"{s['starved_queries']} |"
        )
    add("")
    add(
        "*Consultas famintas* = voltaram com menos de "
        f"{cfg['top_k']} resultados. É cobertura, não qualidade — e é o número "
        "que separa \"errou devolvendo pouco\" de \"errou devolvendo qualquer coisa\".\n"
    )

    add("## Por família de consulta\n")
    add("A média esconde o resultado. Aqui está o que ela esconde.\n")
    for fam, titulo in (
        ("literal", "Literais — o identificador está no texto"),
        ("conceptual", "Conceituais — outro vocabulário, mesmo assunto"),
        ("hybrid", "Híbridas — identificador + descrição na mesma frase"),
    ):
        add(f"### {titulo}\n")
        add("| Estratégia | hit@1 | hit@3 | MRR@10 |")
        add("|---|---:|---:|---:|")
        for s in ev["strategies"]:
            row = s["by_family"].get(fam, {})
            if not row:
                continue
            add(
                f"| {LABEL.get(s['strategy'], s['strategy'])} | {_pct(row['hit_at_1'])} | "
                f"{_pct(row['hit_at_3'])} | {row['mrr']:.3f} |"
            )
        add("")

    add("## Experimentos\n")

    e1 = ex["e1_scale"]
    add(f"### {e1['title']}\n")
    add("| Medida | Valor |")
    add("|---|---|")
    add(
        f"| Faixa de score BM25 | {e1['bm25_score_range']['min']} a "
        f"{e1['bm25_score_range']['max']} |"
    )
    add(
        f"| Faixa de score do denso (cosseno) | {e1['dense_score_range']['min']} a "
        f"{e1['dense_score_range']['max']} |"
    )
    add(
        f"| Candidatos presentes em só uma das listas | {e1['candidates_in_one_list_only']} "
        f"de {e1['candidates_total']} ({e1['pct_zeroed_by_minmax']}%) |"
    )
    add(f"| hit@1 com RRF | {_pct(e1['hit_at_1_rrf'])} |")
    add(f"| hit@1 com fusão min-max | {_pct(e1['hit_at_1_weighted'])} |")
    add(f"| Consultas ordenadas de forma diferente | {e1['queries_ranked_differently']} |")
    add("")
    add(
        "Cada candidato que aparece em uma lista só entra na fusão min-max com "
        "score 0 na outra — uma afirmação de irrelevância sobre algo que o motor "
        "apenas não devolveu.\n"
    )

    e2 = ex["e2_formula"]
    add(f"### {e2['title']}\n")
    add("| Medida | Valor |")
    add("|---|---|")
    add(f"| Consultas | {e2['queries']} |")
    add(f"| Conjunto de resultados idêntico | {e2['identical_result_set']} |")
    add(f"| Mesmo primeiro colocado | {e2['identical_top1']} |")
    add(f"| BM25 colocou o relevante mais acima | {e2['bm25_ranks_relevant_higher']} |")
    add(f"| `ts_rank_cd` colocou mais acima | {e2['ts_rank_ranks_relevant_higher']} |")
    add(f"| Empates | {e2['ties']} |")
    add("")
    add(
        "Os dois leem o mesmo `tsvector` e recuperam o mesmo conjunto por "
        "construção. Toda diferença acima é da fórmula: `ts_rank_cd` pontua "
        "densidade de cobertura e **não tem IDF** — termo raro e termo banal "
        "valem o mesmo.\n"
    )

    e3 = ex["e3_reranker"]
    add(f"### {e3['title']}\n")
    if e3.get("skipped"):
        add(f"Pulado: {e3['skipped']}\n")
    else:
        add("| Medida | Antes | Depois |")
        add("|---|---:|---:|")
        add(f"| hit@1 | {_pct(e3['hit_at_1_before'])} | {_pct(e3['hit_at_1_after'])} |")
        add(f"| MRR@10 | {e3['mrr_before']:.3f} | {e3['mrr_after']:.3f} |")
        add(f"| p50 | {e3['ms_p50_before']:.1f} ms | {e3['ms_p50_after']:.1f} ms |")
        add(f"| p95 | — | {e3['ms_p95_after']:.1f} ms |")
        add("")
        add("| Medida | Valor |")
        add("|---|---|")
        add(f"| Custo médio acrescentado | {e3['ms_added_avg']:.1f} ms por consulta |")
        add(
            f"| Consultas em que o reranker TINHA como ajudar | "
            f"{e3['queries_reranker_could_fix']} |"
        )
        add(f"| Consultas em que promoveu o relevante | {e3['queries_promoted']} |")
        add(f"| Consultas em que rebaixou o relevante | {e3['queries_demoted']} |")
        if e3.get("ms_per_point_of_hit_at_1") is not None:
            add(
                f"| Custo por ponto percentual de hit@1 | "
                f"{e3['ms_per_point_of_hit_at_1']:.1f} ms |"
            )
        add("")
        add(
            f"Teto do reranker: ele só reordena os {e3['prefetch']} candidatos que a "
            "fusão entregou. Documento fora do prefetch é invisível para ele — "
            "reranker não recupera nada.\n"
        )

    e4 = ex["e4_void"]
    add(f"### {e4['title']}\n")
    add("| Medida | BM25 | Denso |")
    add("|---|---:|---:|")
    add(f"| Resultados devolvidos, média | {e4['bm25_avg_returned']} | {e4['dense_avg_returned']} |")
    add(f"| Consultas com menos de {e4['top_k']} | {e4['bm25_starved']} | {e4['dense_starved']} |")
    add(f"| Consultas com ZERO resultado | {e4['bm25_empty']} | 0 |")
    add("")
    add("| Modo do léxico | Média devolvida | Consultas vazias |")
    add("|---|---:|---:|")
    add(f"| OR entre os termos (o desta PoC) | {e4['bm25_avg_returned']} | {e4['or_mode_empty']} |")
    add(f"| AND — o `plainto_tsquery` padrão | {e4['and_mode_avg_returned']} | {e4['and_mode_empty']} |")
    add("")
    add("Média devolvida por família de consulta (BM25):\n")
    add("| Família | Média |")
    add("|---|---:|")
    for fam, value in e4["bm25_returned_by_family"].items():
        add(f"| {fam} | {value} |")
    add("")

    return "\n".join(out) + "\n"


def write() -> str:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    text = render()
    REPORT.write_text(text, encoding="utf-8")
    return text
