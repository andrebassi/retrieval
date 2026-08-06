"""HTTP para inspecionar a PoC no browser.

Adapter *driving*: não decide nada e não calcula nada por conta própria — chama
as mesmas estratégias do `registry.py` e o mesmo store que o `cli.py` usa. Se um
número aqui divergir do `results/REPORT.md`, é bug: não existe caminho
alternativo de cálculo.

A tela responde três perguntas que a tabela do README não responde sozinha:

1. **a mesma pergunta nas seis estratégias, lado a lado** — é onde se vê o BM25
   devolver lista vazia enquanto o denso devolve dez palpites confiantes;
2. **o que cada motor guardou deste documento** — os lexemas com IDF de um lado,
   os primeiros números do vetor do outro. Ler os dois lado a lado dissolve a
   ideia de que "o banco procura a palavra";
3. **onde as estratégias discordam**, nominalmente, com o gabarito na mão.
"""

from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query as QueryParam
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..adapters.lexical import query_lexemes
from ..config import RESULTS_DIR, SETTINGS
from ..corpus import queries as queries_module
from ..models import Query
from ..strategies.registry import STRATEGY_ORDER, Stack, build_stack
from .code_tour import TOUR, tour_for

STATIC_DIR = Path(__file__).parent / "static"

# Nome de tela em pt-BR na frente; o identificador técnico vai no rodapé do
# cartão. Quem não é da área não lê `ts_rank_cd` como "a busca do Postgres".
STRATEGY_LABEL = {
    "dense": "Semântica — texto vira vetor",
    "ts_rank": "Postgres puro — ts_rank_cd",
    "bm25": "BM25 — o clássico do índice invertido",
    "weighted": "Fusão por score normalizado",
    "rrf": "Fusão por posição (RRF)",
    "rrf_rerank": "RRF relido por cross-encoder",
}

FAMILY_LABEL = {
    "literal": "cita um identificador que está no texto",
    "conceptual": "descreve o assunto sem usar as palavras do documento",
    "hybrid": "as duas coisas na mesma frase",
}


class Poc:
    """Estado carregado uma vez no startup.

    O cross-encoder fica residente de propósito: carregá-lo por requisição
    somaria alguns segundos a cada busca e o tempo exibido na tela deixaria de
    ser o custo de consulta de um serviço vivo.
    """

    def __init__(self) -> None:
        self.stack: Stack = build_stack(with_reranker=True)
        self.catalog = self.stack.store.catalog()
        self.known_ids = {row["doc_id"] for row in self.catalog}
        self.queries: list[Query] = queries_module.load(self.known_ids)

    def relevant_for(self, text: str) -> tuple[str, ...] | None:
        """Gabarito da consulta, quando o texto bate com uma das 37 avaliadas.

        Pergunta digitada à mão não tem gabarito — a tela então mostra o
        resultado sem marcar acerto nem erro. Inventar relevância na hora seria
        exatamente o número não medido que esta PoC existe para evitar.
        """
        needle = text.strip().casefold()
        for query in self.queries:
            if query.text.strip().casefold() == needle:
                return query.relevant
        return None

    def close(self) -> None:
        self.stack.store.conn.close()


poc: Poc | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global poc
    poc = Poc()
    if poc.stack.store.count() == 0:
        raise RuntimeError("corpus vazio — rode 'task index' antes")
    yield
    poc.close()


app = FastAPI(title="retrieval-poc", lifespan=lifespan, docs_url="/api/docs")

# Liberar `*` é aceitável aqui: servidor local, sem autenticação e sem cookie,
# servindo dado público de uma PoC. Num serviço com sessão seria outra conversa.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

# `check_dir=False` porque o diretório só existe depois de `task web:build`. Sem
# isso o servidor nem sobe num clone recém-feito, e o erro falaria de um
# diretório em vez de falar do build que falta.
app.mount("/static", StaticFiles(directory=STATIC_DIR, check_dir=False), name="static")


def _state() -> Poc:
    if poc is None:  # pragma: no cover — só ocorre fora do lifespan
        raise HTTPException(503, "aplicação ainda inicializando")
    return poc


@app.get("/")
def index() -> FileResponse:
    entry = STATIC_DIR / "index.html"
    if not entry.is_file():
        raise HTTPException(503, "front não compilado — rode 'task web:build'")
    return FileResponse(entry)


@app.get("/api/state")
def state() -> dict:
    """Tudo que o front precisa para desenhar a tela, medido do banco."""
    current = _state()
    store = current.stack.store

    return {
        # Dois eixos diferentes, e confundi-los produz número errado na tela:
        # `source` é a ORIGEM (escrito à mão × Wikipédia) e `kind` é a FORMA
        # (registro operacional × prosa corrida). Os 8 procedimentos são
        # `handwritten` **e** `prose` ao mesmo tempo — contar alvo por `kind`
        # daria 26 em vez dos 34 que o corpus tem.
        "corpus": {
            "total": store.count(),
            "handwritten": sum(1 for d in current.catalog if d["source"] == "handwritten"),
            "wikipedia": sum(1 for d in current.catalog if d["source"] == "wikipedia"),
            "records": sum(1 for d in current.catalog if d["kind"] == "record"),
            "prose": sum(1 for d in current.catalog if d["kind"] == "prose"),
        },
        "lexical": store.lexical_summary(),
        "indexes": store.index_sizes(),
        "settings": {
            "dense_model": SETTINGS.dense_model,
            "reranker_model": SETTINGS.reranker_model,
            "text_search_config": SETTINGS.text_search_config,
            "bm25_k1": SETTINGS.bm25_k1,
            "bm25_b": SETTINGS.bm25_b,
            "rrf_k": SETTINGS.rrf_k,
            "prefetch_limit": SETTINGS.prefetch_limit,
            "top_k": SETTINGS.top_k,
            "dim": store.vector_dim(),
        },
        "strategies": [
            {
                "name": name,
                "label": STRATEGY_LABEL[name],
                "description": current.stack.strategies[name].description,
                "has_code_tour": name in TOUR,
            }
            for name in STRATEGY_ORDER
            if name in current.stack.strategies
        ],
        "queries": [
            {
                "id": q.query_id,
                "text": q.text,
                "family": q.family,
                "family_label": FAMILY_LABEL.get(q.family, q.family),
                "note": q.note,
                "relevant": list(q.relevant),
            }
            for q in current.queries
        ],
        "catalog": current.catalog,
    }


@app.get("/api/search")
def search(
    q: str = QueryParam(..., min_length=1, max_length=300),
    k: int = QueryParam(5, ge=1, le=10),
) -> dict:
    """A mesma pergunta contra todas as estratégias, uma por vez.

    O tempo é medido aqui, por estratégia, do mesmo jeito que o `runner.py`
    mede: relógio em volta da chamada de `search`, sem descontar nada.
    """
    current = _state()
    relevant = current.relevant_for(q)
    lexemes = query_lexemes(current.stack.store, q)

    results = {}
    for name, strategy in current.stack.strategies.items():
        started = time.perf_counter()
        hits = strategy.search(q, k)
        elapsed = (time.perf_counter() - started) * 1000

        rows = []
        for hit in hits:
            doc = current.stack.store.document(hit.doc_id)
            rows.append(
                {
                    "doc_id": hit.doc_id,
                    "rank": hit.rank,
                    "score": round(hit.score, 4),
                    "title": doc["title"] if doc else "",
                    "kind": doc["kind"] if doc else "?",
                    "snippet": (doc["body"][:220] + "…") if doc else "",
                    "relevant": None if relevant is None else hit.doc_id in relevant,
                }
            )
        results[name] = {
            "label": STRATEGY_LABEL[name],
            "hits": rows,
            "ms": round(elapsed, 1),
            # Devolver menos que k é o modo de falha característico do léxico, e
            # é informação diferente de "errou" — a tela marca os dois separado.
            "returned": len(rows),
            "starved": len(rows) < k,
            "first_relevant": next(
                (r["rank"] for r in rows if r["relevant"]), None
            ),
        }

    return {
        "query": q,
        "k": k,
        "has_ground_truth": relevant is not None,
        "relevant": list(relevant) if relevant else [],
        # Os lexemas são a resposta para "por que o léxico não achou nada": se a
        # lista sai vazia, ou com termo que não existe no corpus, acabou ali.
        "query_lexemes": lexemes,
        "results": results,
    }


@app.get("/api/document/{doc_id}")
def document(doc_id: str) -> dict:
    """O que cada motor guardou deste documento — os dois lados, lado a lado."""
    current = _state()
    doc = current.stack.store.document(doc_id)
    if doc is None:
        raise HTTPException(404, "documento fora do corpus")

    vector = current.stack.store.vector_of(doc_id) or []
    return {
        **doc,
        "lexemes": current.stack.store.lexemes_of(doc_id, limit=40),
        # 24 números: cabe numa linha de barras e já mostra que não há palavra
        # nenhuma ali. Mais que isso vira enfeite.
        "vector_preview": [round(v, 4) for v in vector[:24]],
        "vector_dim": len(vector),
        "in_ground_truth": sorted(
            q.query_id for q in current.queries if doc_id in q.relevant
        ),
    }


@app.get("/api/code/{strategy}")
def code(strategy: str) -> dict:
    """O código real desta estratégia, lido do disco agora — nunca uma cópia."""
    try:
        return tour_for(strategy)
    except KeyError:
        raise HTTPException(404, "estratégia sem tour de código") from None


@app.get("/api/measured")
def measured() -> JSONResponse:
    """Os JSON de `task all`, servidos como estão. Nada é recalculado aqui."""
    out = {}
    # Só o que `task eval` e `task experiments` gravam. Tamanho de índice não
    # entra aqui: ele vem do catálogo do Postgres em `/api/state`, medido na
    # hora — um JSON com esse número envelheceria em silêncio.
    for name in ("evaluation", "experiments"):
        path = RESULTS_DIR / f"{name}.json"
        if path.is_file():
            out[name] = json.loads(path.read_text(encoding="utf-8"))
    return JSONResponse(out)


@app.get("/api/disagreements")
def disagreements() -> dict:
    """Onde as estratégias discordaram na rodada medida.

    Mesma leitura do `tools/inspect_failures.py`, servida para a tela. Lê o
    `results/hits.json` gravado por `task eval` — não roda busca nenhuma, para
    que o que aparece aqui seja exatamente o que foi medido.
    """
    path = RESULTS_DIR / "hits.json"
    if not path.is_file():
        raise HTTPException(503, "sem results/hits.json — rode 'task eval'")
    hits = json.loads(path.read_text(encoding="utf-8"))

    by_query: dict[str, dict] = {}
    for strategy, rows in hits.items():
        for row in rows:
            slot = by_query.setdefault(
                row["query_id"],
                {"query_id": row["query_id"], "text": row["text"], "family": row["family"]},
            )
            rank = next((h["rank"] for h in row["hits"] if h["relevant"]), None)
            slot[strategy] = {"rank": rank, "returned": row["returned"]}

    def worse(rank: int | None) -> bool:
        return rank is None or rank > 3

    def block(title: str, note: str, keep) -> dict:
        return {
            "title": title,
            "note": note,
            "cases": [slot for slot in by_query.values() if keep(slot)],
        }

    return {
        "blocks": [
            block(
                "O léxico falhou e o vetor resolveu",
                "O argumento a favor do denso: a pergunta não usa as palavras do documento.",
                lambda s: worse(s["bm25"]["rank"]) and s["dense"]["rank"] == 1,
            ),
            block(
                "O vetor falhou e o léxico resolveu",
                "O argumento a favor do índice invertido: o identificador é um símbolo,"
                " e símbolo não tem vizinhança semântica.",
                lambda s: worse(s["dense"]["rank"]) and s["bm25"]["rank"] == 1,
            ),
            block(
                "A fusão piorou o que um motor puro já tinha em 1º",
                "O preço de fundir: misturar motor ruim com motor bom dá pior que o bom.",
                lambda s: s["rrf"]["rank"] not in (None, 1)
                and 1 in (s["dense"]["rank"], s["bm25"]["rank"]),
            ),
            block(
                "O reranker rebaixou o que a fusão já tinha entregue",
                "Reranking é aposta com saldo positivo e variância real, não passo de segurança.",
                lambda s: s["rrf"]["rank"] is not None
                and (
                    s["rrf_rerank"]["rank"] is None
                    or s["rrf_rerank"]["rank"] > s["rrf"]["rank"]
                ),
            ),
        ]
    }


def main() -> None:
    import uvicorn

    uvicorn.run(
        "retrieval_poc.web.app:app",
        host="127.0.0.1",
        port=8081,  # o 8080 é do image-embedding-poc; derrubá-lo seria acidente
        log_level="info",
    )


if __name__ == "__main__":
    main()
