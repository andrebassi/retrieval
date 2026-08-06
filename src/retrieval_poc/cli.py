"""Ponto de entrada. Cada subcomando é uma etapa do pipeline, na ordem.

    corpus  →  index  →  eval  →  experiments  →  report
                  ↑
               verify (canário: prova que o índice enxerga antes de confiar nele)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

from .config import RESULTS_DIR, SETTINGS
from .corpus import build as corpus_build
from .corpus import queries as corpus_queries


def cmd_corpus(args) -> int:
    docs = corpus_build.build(distractors=args.distractors)
    meta = json.loads((corpus_build.CORPUS_META).read_text(encoding="utf-8"))
    print(f"corpus: {meta['total']} documentos "
          f"({meta['targets']} alvos + {meta['distractors']} distratores)")
    print(f"filtro temático descartou {meta['blocked_by_topic_filter']} artigos")
    print(f"tamanho em caracteres: min {meta['chars_min']} / "
          f"média {meta['chars_avg']} / máx {meta['chars_max']}")
    # Valida o gabarito agora, e não depois de indexar tudo.
    queries = corpus_queries.load(known_ids={d.doc_id for d in docs})
    print(f"gabarito: {len(queries)} consultas, todas apontando para documento existente")
    return 0


def cmd_index(args) -> int:
    from .strategies.registry import build_stack

    stack = build_stack(with_reranker=False)
    docs = corpus_build.load()

    dim = stack.embedder.dim
    print(f"dimensão medida do modelo {SETTINGS.dense_model}: {dim}")
    stack.store.reset(dim)

    # Duas etapas, e a ordem importa: o texto entra primeiro (o `tsvector` é
    # coluna gerada, então o índice léxico nasce junto do INSERT), e só depois o
    # DenseRetriever preenche a coluna de vetor das linhas que já existem.
    stack.store.insert(docs)
    print(f"gravados {stack.store.count()} documentos")

    started = time.perf_counter()
    # `index` grava os vetores e cria o HNSW no fim — construir o índice com a
    # tabela vazia e inserir depois produz um grafo pior.
    stack.dense.index(docs)
    elapsed = time.perf_counter() - started
    print(f"vetorizados em {elapsed:.1f}s ({elapsed / len(docs) * 1000:.0f} ms/documento)")

    stats_ms = stack.store.build_lexical_stats()
    summary = stack.store.lexical_summary()
    print(f"índice léxico em {stats_ms:.0f} ms: {summary['distinct_terms']} termos "
          f"distintos, {summary['postings']} postings, comprimento médio "
          f"{summary['avg_doc_length']:.1f} lexemas")
    print(f"termos que ocorrem em um só documento: {summary['terms_in_one_doc']}")
    return 0


def cmd_verify(args) -> int:
    """Canário: prova que o índice enxerga o que deveria, ANTES de medir.

    Sem isto, uma configuração textual errada ou um `tsvector` vazio produzem
    uma tabela inteira de zeros que parece resultado.
    """
    from .strategies.registry import build_stack

    stack = build_stack(with_reranker=False)
    problems: list[str] = []

    count = stack.store.count()
    if count == 0:
        raise SystemExit("banco vazio — rode `task index`")
    print(f"✅ {count} documentos no banco")

    # 1. termo único tem que voltar SÓ o documento que o contém
    unique = [("E-217", "os_4475"), ("DT-2207", "pc_774410"), ("L-0339", "ch_5503")]
    for term, expected in unique:
        hits = stack.bm25.search(term, 10)
        ids = [h.doc_id for h in hits]
        if ids != [expected]:
            problems.append(f"BM25('{term}') devolveu {ids}, esperado ['{expected}']")
        else:
            print(f"✅ BM25('{term}') → {expected}, e só ele")

    # 2. termo que não existe em documento nenhum tem que voltar VAZIO
    hits = stack.bm25.search("xilofone quântico bergamota", 10)
    if hits:
        problems.append(f"BM25 de termo inexistente devolveu {len(hits)} resultados")
    else:
        print("✅ BM25 de termo inexistente devolve lista vazia")

    # 3. o denso devolve k SEMPRE — inclusive para a consulta acima
    dense_hits = stack.dense.search("xilofone quântico bergamota", 10)
    if len(dense_hits) != 10:
        problems.append(f"denso devolveu {len(dense_hits)} para consulta sem sentido")
    else:
        print(f"✅ denso devolve 10 resultados para a MESMA consulta sem sentido "
              f"(melhor score: {dense_hits[0].score:.4f}) — é o palpite, não erro de código")

    # 4. dimensão medida bate com a coluna
    dim = stack.store.vector_dim()
    if dim != stack.embedder.dim:
        problems.append(f"coluna vector({dim}) × modelo de {stack.embedder.dim} dimensões")
    else:
        print(f"✅ coluna vector({dim}) bate com a dimensão medida do modelo")

    # 5. estatística léxica existe
    summary = stack.store.lexical_summary()
    if summary["postings"] == 0:
        problems.append("lex_terms vazio — `build_lexical_stats` não rodou")
    else:
        print(f"✅ estatística léxica com {summary['postings']} postings")

    if problems:
        for p in problems:
            print(f"🛑 {p}", file=sys.stderr)
        return 1
    print("\nerros: 0")
    return 0


def cmd_eval(args) -> int:
    from .evaluation.runner import evaluate
    from .strategies.registry import build_stack

    stack = build_stack(with_reranker=not args.no_reranker)
    report = evaluate(stack)
    for entry in report["strategies"]:
        print(
            f"{entry['strategy']:<12} hit@1 {entry['hit_at_1']:.3f}  "
            f"hit@3 {entry['hit_at_3']:.3f}  mrr {entry['mrr']:.3f}  "
            f"p50 {entry['query_ms_p50']:.1f}ms  famintas {entry['starved_queries']}"
        )
    return 0


def cmd_experiments(args) -> int:
    from .evaluation.experiments import run_all
    from .strategies.registry import build_stack

    stack = build_stack(with_reranker=not args.no_reranker)
    result = run_all(stack)
    for key, block in result.items():
        print(f"\n── {block['title']}")
        for k, v in block.items():
            if k in ("title", "detail", "disagreements"):
                continue
            print(f"   {k}: {v}")
    return 0


def cmd_report(args) -> int:
    from .report import REPORT, write

    write()
    print(f"relatório escrito em {REPORT}")
    return 0


def cmd_query(args) -> int:
    """Consulta única, para inspecionar uma discordância à mão."""
    from .strategies.registry import build_stack

    stack = build_stack(with_reranker=not args.no_reranker)
    for name, strategy in stack.strategies.items():
        started = time.perf_counter()
        hits = strategy.search(args.text, SETTINGS.top_k)
        ms = (time.perf_counter() - started) * 1000
        print(f"\n── {name} ({ms:.1f} ms, {len(hits)} resultados)")
        for hit in hits[:5]:
            print(f"   {hit.rank}. {hit.doc_id:<14} {hit.score:.4f}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="poc", description="PoC de retrieval híbrido")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("corpus", help="monta o corpus")
    p.add_argument("--distractors", type=int, default=80)
    p.set_defaults(func=cmd_corpus)

    p = sub.add_parser("index", help="grava documentos, vetores e estatística léxica")
    p.set_defaults(func=cmd_index)

    p = sub.add_parser("verify", help="canário: prova que o índice enxerga")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("eval", help="mede todas as estratégias")
    p.add_argument("--no-reranker", action="store_true")
    p.set_defaults(func=cmd_eval)

    p = sub.add_parser("experiments", help="roda E1–E4")
    p.add_argument("--no-reranker", action="store_true")
    p.set_defaults(func=cmd_experiments)

    p = sub.add_parser("report", help="gera results/REPORT.md")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("query", help="uma consulta em todas as estratégias")
    p.add_argument("text")
    p.add_argument("--no-reranker", action="store_true")
    p.set_defaults(func=cmd_query)

    args = parser.parse_args()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    rc = args.func(args)

    # `os._exit` e não `return`: o `datasets` (e o `torch`, no eval) deixam
    # thread não-daemon viva, e o interpretador trava no shutdown DEPOIS de ter
    # feito todo o trabalho. Medido: `poc corpus` gravou os 114 documentos,
    # imprimiu tudo, e ficou 11 minutos em `pthread_cond_wait` dentro de
    # `__cxa_finalize_ranges` — o `task all` parecia travado no corpus quando o
    # corpus já estava pronto no disco. Como `os._exit` pula o flush dos
    # buffers, ele vem depois do flush explícito.
    #
    # `_exit_function` é o mesmo cleanup que o `atexit` do multiprocessing faria:
    # sem ele o `os._exit` deixa o pool do `datasets` para trás e o processo
    # morre imprimindo "leaked semaphore objects". Ele fecha filhos, não espera
    # thread — então não traz o travamento de volta.
    from multiprocessing.util import _exit_function

    _exit_function()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(rc)


if __name__ == "__main__":
    raise SystemExit(main())
