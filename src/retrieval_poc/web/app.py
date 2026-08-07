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


def fmt_number(value: float, digits: int = 1) -> str:
    """Número para LER, com vírgula decimal — a tela inteira é em pt-BR.

    `f"{x:.1f}"` devolve `100.0`, que numa frase portuguesa lê como outra coisa:
    em pt-BR o ponto é separador de milhar. A tela dizia `acerta 100.0%` ao lado
    de um README que diz `100,0%`, e os dois números são o mesmo.

    Fica aqui, e não no front, porque a frase inteira nasce aqui: `verdict`,
    `why`, `reason` e as legendas chegam prontas do back-end (é o que impede o
    cartão de divergir do texto ao lado). Formatar no front resolveria metade —
    a metade que o front desenha — e deixaria a outra metade em inglês.

    NÃO vale para o rodapé técnico (`k1=1.2`, `b=0.75`): ali o número é **valor
    de parâmetro** copiado da configuração, e trocar o separador faria a tela
    discordar do que está escrito no `config.py`.
    """
    return f"{value:.{digits}f}".replace(".", ",")


# Nome de tela em pt-BR na frente; o identificador técnico vai no rodapé do
# cartão. Quem não é da área não lê `ts_rank_cd` como "a busca do Postgres".
STRATEGY_LABEL = {
    "dense": "Busca por significado",
    "ts_rank": "Busca por palavra, simples",
    "bm25": "Busca por palavra, com peso",
    "weighted": "As duas juntas, somando notas",
    "rrf": "As duas juntas, somando posições",
    "rrf_rerank": "As duas juntas + um revisor",
}

# O mesmo nome, curto o bastante para caber numa linha do placar.
#
# Não é economia de espaço: o placar corta com reticências, e as três variantes
# de "As duas juntas…" ficavam todas em “As duas juntas, somando…”. Três linhas
# com o mesmo texto e notas diferentes é pior que nome nenhum — quem lê acha que
# a tela repetiu a mesma estratégia. O `·` separa o que era vírgula porque o
# corte por reticências costumava cair exatamente nela.
#
# Os três primeiros abrem com **“Por …”** por causa do cartão da resposta: ali o
# nome aparece grande, sozinho, sob a palavra "use". "Significado" naquele lugar
# lê como rótulo de campo — o visitante pergunta "significado de quê?" em vez de
# ler o nome de uma busca. A preposição custa quatro caracteres e diz que aquilo
# é o *critério* pelo qual se procura, não um cabeçalho.
STRATEGY_SHORT = {
    "dense": "Por significado",
    "ts_rank": "Por palavra · simples",
    "bm25": "Por palavra · com peso",
    "weighted": "Duas juntas · notas",
    "rrf": "Duas juntas · posições",
    "rrf_rerank": "Duas juntas + revisor",
}

# Cada opção em uma frase, mais o que ela faz bem e o que ela faz mal. É o que
# a tabela de médias não conta: as seis "erram 20%", só que em perguntas
# diferentes — e escolher motor é escolher **qual erro** você aceita.
STRATEGY_PLAIN = {
    "dense": {
        "how": "Transforma a pergunta e cada documento em uma lista de números "
        "que representa o assunto. Depois procura os documentos cujos números "
        "ficam mais perto dos da pergunta.",
        "good": "Entende quando você descreve o problema com outras palavras: "
        "acha “vazamento de óleo” num texto que só diz “perda de lubrificante”.",
        "bad": "Confunde códigos parecidos. Para ele, dois números de nota "
        "fiscal quase iguais querem dizer quase a mesma coisa — e não querem.",
    },
    "ts_rank": {
        "how": "Procura as palavras da pergunta dentro do texto e ordena por "
        "quantas vezes elas aparecem e por onde aparecem.",
        "good": "É a busca que todo banco de dados já tem, custa quase nada e "
        "acha o código exato quando ele está escrito lá.",
        "bad": "Trata toda palavra como se valesse o mesmo. “bomba” e “de” "
        "pesam igual, e aí o documento certo perde para um que só repete “de”.",
    },
    "bm25": {
        "how": "Mesma busca por palavra, com uma diferença: palavra rara vale "
        "mais que palavra comum, e texto longo não leva vantagem por ser longo.",
        "good": "Acha o número de série, a placa, o código do equipamento — "
        "justamente as palavras que aparecem em poucos documentos.",
        "bad": "Se você não usar nenhuma palavra que está escrita no documento, "
        "ele devolve pouca coisa ou nada. Não sabe o que é sinônimo.",
    },
    "weighted": {
        "how": "Roda as duas buscas e soma as notas delas, depois de colocar as "
        "duas na mesma escala de 0 a 1.",
        "good": "Aproveita as duas: quem acha por palavra e quem acha por "
        "assunto entram na mesma lista.",
        "bad": "As duas notas nascem em escalas diferentes, e forçá-las a "
        "conviver distorce as duas. É a opção que mais depende de sorte no ajuste.",
    },
    "rrf": {
        "how": "Roda as duas buscas e ignora as notas: só olha em que lugar "
        "cada documento ficou em cada lista, e soma os lugares.",
        "good": "Não precisa de ajuste nenhum e não sofre com escala. É a fusão "
        "que funciona sem ninguém calibrar.",
        "bad": "Perde a informação de “ganhou por muito” ou “ganhou por pouco”. "
        "1º lugar folgado e 1º lugar apertado valem a mesma coisa.",
    },
    "rrf_rerank": {
        "how": "Faz a fusão acima, pega os 20 primeiros e passa cada um por um "
        "modelo que lê a pergunta e o documento na mesma passada, um ao lado do "
        "outro, para reordenar.",
        "good": "É quem mais acerta na primeira posição — o revisor percebe "
        "detalhes que a busca não percebe.",
        "bad": "Só reordena o que a fusão já trouxe: se o documento certo ficou "
        "de fora dos 20, ele nunca aparece. E é a opção mais lenta, de longe.",
    },
}

FAMILY_LABEL = {
    "literal": "a pergunta cita um código que está escrito no documento",
    "conceptual": "a pergunta descreve o problema com outras palavras",
    "hybrid": "a pergunta traz o código e a descrição na mesma frase",
}

# O que cada opção custa para manter no ar, e o que a derruba quando o acervo
# muda. Isto não sai de medição — é a leitura de engenharia que a tabela de
# médias não carrega, e é justamente o que decide entre duas linhas empatadas.
#
# `tuning_free` não é enfeite de documentação: é critério de desempate. Duas
# estratégias empatadas na medição não estão empatadas na manutenção, e a que
# precisa de um número calibrado neste acervo é a que quebra em silêncio no
# próximo. Só a `weighted` tem esse problema — os "dois números fixos" do BM25
# são constantes do artigo original, iguais em qualquer acervo.
STRATEGY_TRAIT = {
    "ts_rank": {
        "needs": "só o Postgres, nada mais",
        "tuning": "nada para ajustar",
        "tuning_free": True,
        "risk": "sem sinônimo: pergunta escrita com outras palavras não acha nada.",
    },
    "bm25": {
        "needs": "só o Postgres, com a estatística de termos gravada",
        "tuning": "dois números fixos (k1 e b), os mesmos do artigo original",
        "tuning_free": True,
        "risk": "sem sinônimo, igual à de cima — o peso melhora a ordem, não o alcance.",
    },
    "dense": {
        "needs": "um modelo de embedding rodando o tempo todo",
        "tuning": "nada para ajustar, mas troca de modelo refaz o índice inteiro",
        "tuning_free": True,
        "risk": "código exato: para o vetor, dois números quase iguais falam do mesmo assunto.",
    },
    "weighted": {
        "needs": "o modelo de embedding, mais a soma das duas notas",
        "tuning": "peso e escala, calibrados neste acervo",
        "tuning_free": False,
        "risk": "a escala das notas muda com o acervo, e o peso calibrado aqui deixa de valer lá.",
    },
    "rrf": {
        "needs": "o modelo de embedding, mais a soma das posições",
        "tuning": "nada para ajustar — só olha o lugar na lista",
        "tuning_free": True,
        "risk": "trata 1º folgado e 1º apertado como a mesma coisa.",
    },
    "rrf_rerank": {
        "needs": "o modelo de embedding e mais um modelo revisor",
        "tuning": "nada para ajustar, mas o revisor só vê os 20 primeiros",
        "tuning_free": True,
        "risk": "documento certo fora dos 20 nunca aparece, e o revisor às vezes rebaixa quem estava certo.",
    },
}

# As três perguntas do escolhedor. Cada uma escolhe **uma coluna** da medição:
# quem lê define a métrica, o tempo define quem é elegível, o tipo de pergunta
# define qual família olhar. Nenhuma delas é preferência — as três mudam o
# vencedor porque mudam o número que está sendo comparado.
ADVICE_READERS = [
    {
        "id": "first",
        "label": "Uma pessoa, e ela lê só o primeiro",
        "hint": "caixa de busca que já mostra a resposta, assistente que responde uma coisa só",
        "metric": "hit_at_1",
        "metric_label": "acertou de primeira",
    },
    {
        "id": "few",
        "label": "Uma pessoa, e ela passa o olho em três",
        "hint": "lista de resultados que alguém varre antes de clicar",
        "metric": "hit_at_3",
        "metric_label": "apareceu entre os três primeiros",
    },
    {
        "id": "llm",
        "label": "Um robô, e ele lê os dez",
        "hint": "os resultados viram o contexto de um modelo de linguagem",
        "metric": "hit_at_10",
        "metric_label": "apareceu entre os dez",
    },
]

ADVICE_BUDGETS = [
    {
        "id": "instant",
        "label": "Enquanto a pessoa digita",
        "ms": 5,
        "hint": "sugestão que reaparece a cada tecla — não cabe chamar modelo nenhum",
    },
    {
        "id": "click",
        "label": "Depois de um clique",
        "ms": 150,
        "hint": "apertou buscar e espera a página trocar",
    },
    {
        "id": "patient",
        "label": "Pode esperar meio segundo",
        "ms": 500,
        "hint": "resposta de assistente, relatório, processamento em fila",
    },
]

ADVICE_KINDS = [
    {
        "id": "literal",
        "label": "Códigos, placas, números de nota",
        "hint": "o que a pessoa digita está escrito no documento, letra por letra",
    },
    {
        "id": "conceptual",
        "label": "O problema descrito com palavras livres",
        "hint": "quem pergunta não sabe o termo que o documento usa",
    },
    {
        "id": "hybrid",
        "label": "Os dois na mesma frase",
        "hint": "“P-101 fazendo barulho” — código e sintoma juntos",
    },
]

# Como cada vencedor se desenha em caixinhas na tela. É a mesma informação do
# `needs`, na forma que responde “o que eu monto, afinal?”.
PIPELINE_OF = {
    "ts_rank": ["lexical"],
    "bm25": ["lexical"],
    "dense": ["dense"],
    "weighted": ["lexical", "dense", "fusion"],
    "rrf": ["lexical", "dense", "fusion"],
    "rrf_rerank": ["lexical", "dense", "fusion", "rerank"],
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
                # `description` é a frase técnica que já existia no registry;
                # `plain` é a explicação de tela. Os dois convivem: o rodapé do
                # cartão continua mostrando o identificador para quem quer ver o
                # código, e a frente fala com quem só quer decidir.
                "description": current.stack.strategies[name].description,
                "plain": STRATEGY_PLAIN[name],
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
                "A busca por palavra falhou e a por significado salvou",
                "É o caso que justifica ter busca por significado: a pergunta não"
                " usa nenhuma palavra que está escrita no documento.",
                lambda s: worse(s["bm25"]["rank"]) and s["dense"]["rank"] == 1,
            ),
            block(
                "A busca por significado falhou e a por palavra salvou",
                "É o caso que justifica manter a busca por palavra: um código não"
                " tem sinônimo, e é por isso que “parecido” não ajuda a achá-lo.",
                lambda s: worse(s["dense"]["rank"]) and s["bm25"]["rank"] == 1,
            ),
            block(
                "Juntar as duas piorou o que uma sozinha já tinha acertado",
                "O preço de juntar: quando uma das duas erra feio, a mistura fica"
                " pior do que a que estava certa.",
                lambda s: s["rrf"]["rank"] not in (None, 1)
                and 1 in (s["dense"]["rank"], s["bm25"]["rank"]),
            ),
            block(
                "O revisor rebaixou o que a mistura já tinha colocado na frente",
                "O revisor melhora a média, mas erra em casos específicos — é"
                " aposta com saldo positivo, não garantia.",
                lambda s: s["rrf"]["rank"] is not None
                and (
                    s["rrf_rerank"]["rank"] is None
                    or s["rrf_rerank"]["rank"] > s["rrf"]["rank"]
                ),
            ),
        ]
    }


# A régua mais frouxa das três. Serve de linha-base para dizer o que a escolha
# de quem lê **fez** com o placar: em `hit_at_10` quase todas empatam, e é o
# aperto da régua que separa as seis. Sem uma linha-base a rodada 1 não tem o que
# narrar — mostraria seis notas sem dizer que elas mudaram.
BASELINE_METRIC = "hit_at_10"


def _round_reader(rows: list[dict], reader: dict) -> dict:
    """Rodada 1: a régua troca e o placar inteiro se remonta.

    Nenhuma competidora é eliminada aqui — o que muda é o **número que está
    sendo comparado**. A rodada existe para mostrar isso acontecendo: quem tinha
    100% olhando os dez pode cair para 54% se a régua exigir o primeiro lugar, e
    esse tombo é a coisa mais informativa da tela.
    """
    metric = reader["metric"]
    board = []
    for row in rows:
        value = row[metric]
        baseline = row[BASELINE_METRIC]
        board.append(
            {
                "name": row["strategy"],
                "label": STRATEGY_LABEL[row["strategy"]],
                "value": value,
                "p50": row["query_ms_p50"],
                # As três rodadas alimentam o MESMO placar, então elas devolvem o
                # mesmo formato de linha — inclusive os campos que não se aplicam
                # ainda. Deixar o front preencher o que falta é convidá-lo a
                # inventar: `eliminated` ausente vira `undefined`, que é falso por
                # acidente e não por decisão.
                "eliminated": False,
                "reason": "",
                "baseline": baseline,
                # Em pontos percentuais, que é a unidade da faixa de empate — a
                # mesma que o resto da tela usa para dizer o que é diferença real.
                "drop": round((baseline - value) * 100, 1),
            }
        )
    board.sort(key=lambda item: (-item["value"], item["name"]))

    spread = round((board[0]["value"] - board[-1]["value"]) * 100, 1)
    hardest = max(board, key=lambda item: item["drop"])
    if metric == BASELINE_METRIC:
        headline = (
            f"Esta é a régua mais frouxa das três: basta o documento certo aparecer "
            f"em algum lugar dos dez. {sum(1 for item in board if item['value'] >= 1.0)} "
            f"das {len(board)} chegam a 100% aqui — e é por isso que quase toda "
            f"comparação de busca que você lê por aí parece um empate."
        )
    elif hardest["drop"] <= 0:
        headline = f"Ninguém perde nota ao apertar a régua para “{reader['metric_label']}”."
    else:
        headline = (
            f"Apertando a régua para “{reader['metric_label']}”, "
            f"“{hardest['label']}” é quem mais sofre: cai {fmt_number(hardest['drop'])} pontos "
            f"em relação a olhar os dez. O placar se remonta inteiro."
        )
    # A mesma notícia em uma linha, para o vídeo.
    #
    # O `headline` acima tem 3 a 4 linhas — no player ele vira parede de texto que
    # ninguém termina antes de a cena virar. Encurtar no front seria recalcular
    # número em dois lugares; escrever aqui mantém a fonte única, e o limite de
    # comprimento vira asserção do canário em vez de disciplina.
    if metric == BASELINE_METRIC:
        # A concordância é calculada, não presumida: o número de estratégias que
        # cravam 100% depende do corpus, e “1 das 6 chegam” é o tipo de erro que
        # aparece só no dia em que o corpus muda — quando ninguém está olhando
        # esta linha.
        perfect = sum(1 for item in board if item["value"] >= 1.0)
        caption = (
            f"{perfect} das {len(board)} {'chegam' if perfect != 1 else 'chega'} "
            "a 100% — a régua mais frouxa"
        )
    elif hardest["drop"] <= 0:
        caption = "Ninguém perde nota com esta régua"
    else:
        caption = f"{STRATEGY_SHORT[hardest['name']]} perde {fmt_number(hardest['drop'])} pontos"
    return {
        "metric": metric,
        "board": board,
        "spread": spread,
        "headline": headline,
        "caption": caption,
    }


def _budget_seats(rows: list[dict], metric: str, budget_ms: float) -> dict[str, int]:
    """Em que posição o placar terminou a rodada 2.

    Existe como função própria porque **dois** lugares precisam da mesma ordem: a
    rodada 2, que a desenha, e a rodada 3, que compara contra ela para dizer quem
    subiu e quem desceu. Calculada nos dois, ela sairia diferente no dia em que um
    dos dois mudasse de critério — e a tela mostraria uma seta para cima ao lado de
    uma linha que não se mexeu.
    """
    alive = sorted(
        (row for row in rows if row["query_ms_p50"] <= budget_ms),
        key=lambda row: (-row[metric], row["query_ms_p50"]),
    )
    out = sorted(
        (row for row in rows if row["query_ms_p50"] > budget_ms),
        key=lambda row: row["query_ms_p50"],
    )
    return {row["strategy"]: index for index, row in enumerate(alive + out)}


def _round_budget(rows: list[dict], reader: dict, budget: dict) -> dict:
    """Rodada 2: o relógio elimina, e elimina antes de a nota ser olhada.

    O tempo comparado aqui é o **global**, não o da família: o tipo de pergunta
    só é escolhido na rodada seguinte. Isso não é imprecisão a esconder — é a
    reviravolta da rodada 3, quando o mesmo corte é refeito com o tempo daquele
    tipo e alguém pode voltar para a mesa. A tela diz que é provisório.
    """
    metric = reader["metric"]
    alive, out = [], []
    for row in rows:
        p50 = row["query_ms_p50"]
        eliminated = p50 > budget["ms"]
        item = {
            "name": row["strategy"],
            "label": STRATEGY_LABEL[row["strategy"]],
            "value": row[metric],
            "p50": p50,
            "eliminated": eliminated,
            "reason": (
                f"leva {fmt_number(p50)} ms, e o limite é {fmt_number(budget['ms'], 0)} ms" if eliminated else ""
            ),
        }
        (out if eliminated else alive).append(item)
    seats = _budget_seats(rows, metric, budget["ms"])

    if not out:
        headline = (
            f"Com {fmt_number(budget['ms'], 0)} ms de folga, as {len(rows)} continuam na mesa. "
            "Esta pergunta não elimina ninguém — ela só deixa de eliminar."
        )
    elif not alive:
        headline = f"Nenhuma das {len(rows)} responde em até {fmt_number(budget['ms'], 0)} ms."
    else:
        best_out = max(out, key=lambda item: item["value"])
        headline = (
            f"{len(out)} de {len(rows)} saem da mesa por tempo, sem a nota ter sido "
            f"olhada — inclusive “{best_out['label']}”, que acerta "
            f"{fmt_number(best_out['value'] * 100)}%. Nota alta não salva de estourar o relógio."
        )
    # Eliminadas embaixo, e ordenadas por tempo: o placar conta a história de
    # cima para baixo, e quem saiu fica visível — some da disputa, não da tela.
    #
    # `out` sai na MESMA ordem do placar, e não na ordem em que `rows` chegou:
    # os dois desenham a mesma eliminação, e ordens diferentes fazem a lista de
    # quem caiu contradizer as linhas riscadas logo ao lado. Pego pelo canário.
    if not out:
        caption = f"Ninguém sai — {fmt_number(budget['ms'], 0)} ms é folga para as {len(rows)}"
    elif not alive:
        caption = f"As {len(rows)} estouram {fmt_number(budget['ms'], 0)} ms"
    elif len(out) == 1:
        # Uma só: dizer QUAL saiu vale mais que dizer que saiu uma — e ainda
        # resolve a concordância, que “1 saem por tempo” quebrava na tela.
        caption = f"{STRATEGY_SHORT[out[0]['name']]} sai — estourou {fmt_number(budget['ms'], 0)} ms"
    else:
        caption = f"{len(out)} saem por tempo — o limite é {fmt_number(budget['ms'], 0)} ms"
    return {
        "ms": budget["ms"],
        "board": sorted(alive + out, key=lambda item: seats[item["name"]]),
        "alive": [item["name"] for item in alive],
        "out": sorted(out, key=lambda item: seats[item["name"]]),
        "headline": headline,
        "caption": caption,
    }


# Os três critérios do desempate, na ordem em que são aplicados. Cada um é uma
# rodada do mata-mata: quem não tem o melhor valor **sai**, e o motivo da saída é
# derivado do próprio critério — texto fixo aqui já produziu a contradição da
# armadilha 23.
TIEBREAK_CRITERIA = [
    {
        "id": "starved",
        "title": "Devolve a lista cheia?",
        "why": (
            "Lista curta é o fracasso que ninguém percebe: o documento certo está "
            "lá, mas a tela parece vazia e quem usa desiste antes de rolar."
        ),
        "key": lambda row: row["starved"],
    },
    {
        "id": "tuning",
        "title": "Tem algo para calibrar?",
        "why": (
            "Número calibrado neste acervo é dívida: no próximo acervo ele deixa de "
            "valer e a qualidade cai sem ninguém receber alerta."
        ),
        "key": lambda row: 0 if row["tuning_free"] else 1,
    },
    {
        "id": "speed",
        "title": "Quem responde mais rápido?",
        "why": "Empatadas em tudo o que importa, sobra o relógio.",
        "key": lambda row: row["p50"],
    },
]


def _tiebreak_out_reason(criterion_id: str, row: dict, winner: dict) -> str:
    """Por que **esta** saiu **nesta** rodada, lido do critério que a cortou."""
    if criterion_id == "starved":
        return (
            f"devolve lista curta em {row['starved']} perguntas, contra "
            f"{winner['starved']} de quem passou"
        )
    if criterion_id == "tuning":
        return "precisa de peso e escala calibrados neste acervo"
    return f"leva {fmt_number(row['p50'])} ms, contra {fmt_number(winner['p50'])} ms de quem passou"


def _tiebreak_steps(contenders: list[dict]) -> list[dict]:
    """O desempate contado como mata-mata, um critério por vez.

    A frase única de `why` já dizia o resultado do desempate; o que faltava era
    ver **acontecer**. Cada etapa devolve quem entrou, quem passou e quem caiu —
    e a etapa que não separa ninguém também aparece, porque "este critério não
    distinguiu nada" é informação: é o que justifica passar para o próximo.
    """
    steps: list[dict] = []
    alive = list(contenders)
    for criterion in TIEBREAK_CRITERIA:
        if len(alive) <= 1:
            break
        best = min(criterion["key"](row) for row in alive)
        passed = [row for row in alive if criterion["key"](row) == best]
        cut = [row for row in alive if criterion["key"](row) != best]
        steps.append(
            {
                "id": criterion["id"],
                "title": criterion["title"],
                "why": criterion["why"],
                "entered": [row["name"] for row in alive],
                "passed": [row["name"] for row in passed],
                "out": [
                    {
                        "name": row["name"],
                        "label": row["label"],
                        "reason": _tiebreak_out_reason(criterion["id"], row, passed[0]),
                    }
                    for row in cut
                ],
                "decided": bool(cut),
            }
        )
        alive = passed
    return steps


def _rank_for(rows: list[dict], family: str, metric: str, budget_ms: float, band: float) -> dict:
    """Quem ganha neste cenário, e por quê — só com o que foi medido.

    As três escolhas do usuário não são preferência: cada uma troca **qual
    número** está sendo comparado. Quem lê define a métrica (1º, 3º ou 10º
    lugar), o tempo define quem sequer entra na disputa, e o tipo de pergunta
    define a família — e é aí que a média engana, porque o denso acerta 93% nas
    descrições e 55% nos códigos, e a média de 81% não descreve nem uma coisa
    nem outra.

    O tempo comparado é o da própria família, não a média geral: o cenário já
    fixou o tipo de pergunta, então o custo relevante é o daquele tipo.
    """
    ranked = []
    for row in rows:
        family_row = row["by_family"][family]
        p50 = family_row["query_ms_p50"]
        ranked.append(
            {
                "name": row["strategy"],
                "label": STRATEGY_LABEL[row["strategy"]],
                "value": family_row[metric],
                "p50": p50,
                "starved": family_row["starved_queries"],
                "tuning_free": STRATEGY_TRAIT[row["strategy"]]["tuning_free"],
                "eliminated": p50 > budget_ms,
                "reason": (
                    f"leva {fmt_number(p50)} ms, acima do limite de {fmt_number(budget_ms, 0)} ms"
                    if p50 > budget_ms
                    else ""
                ),
            }
        )

    eligible = [row for row in ranked if not row["eliminated"]]
    ranked.sort(key=lambda row: (row["eliminated"], -row["value"], row["starved"], row["p50"]))

    if not eligible:
        # Sem ninguém dentro do orçamento não há desempate a fazer; a lista sai
        # na ordem de nota mesmo, só para a tela mostrar o quanto cada uma
        # estourou o tempo. Nenhum dos 27 cenários chega aqui hoje — este ramo é
        # a defesa para o corpus futuro em que o relógio derrube as seis.
        for row in ranked:
            row["out_at"] = "budget"
        return {
            "winner": None,
            "value": None,
            "tied": [],
            "ranked": ranked,
            "pipeline": [],
            "why": f"Nenhuma das seis responde em até {fmt_number(budget_ms, 0)} ms neste tipo de pergunta.",
            "verdict": [f"Nenhuma responde em até {fmt_number(budget_ms, 0)} ms neste tipo de pergunta"],
            "notes": [],
            "tiebreak": [],
            "moved": [],
            "swap": (
                f"Não sobrou ninguém para trocar de lugar: o limite de {fmt_number(budget_ms, 0)} ms "
                "tirou as seis da mesa na rodada anterior."
            ),
            "swap_caption": f"Ninguém sobrou: {fmt_number(budget_ms, 0)} ms tirou as seis",
            "why_caption": f"Sem campeã — nenhuma responde em {fmt_number(budget_ms, 0)} ms",
        }

    # Dentro da faixa de uma pergunta **não existe ordem por nota** — declarar
    # vencedora a que tem o número maior ali dentro é premiar uma pergunta que
    # caiu para um lado. Então: a faixa define quem disputa, e a disputa é
    # decidida por engenharia, nesta ordem:
    #
    #   1. devolve a lista cheia (o fracasso que ninguém percebe vem primeiro);
    #   2. não tem nada para calibrar (o que quebra em silêncio no próximo acervo);
    #   3. responde mais rápido.
    #
    # Sem o critério 2, a `weighted` ganhava o cenário mais comum da tela por
    # 3 ms de diferença — 3 ms escolhendo a única opção que precisa de ajuste
    # manual, dentro de um empate onde a nota não distingue nada.
    best = max(row["value"] for row in eligible)
    contenders = [row for row in eligible if best - row["value"] < band]
    contenders.sort(key=lambda row: (row["starved"], 0 if row["tuning_free"] else 1, row["p50"]))

    winner = contenders[0]
    tied = [row["name"] for row in contenders]
    losers = contenders[1:]
    tiebreak = _tiebreak_steps(contenders)

    # A lista da tela tem que sair na MESMA ordem do desempate, senão o topo dela
    # contradiz o cartão logo acima: com o `sort` por nota, a `weighted` (117,8 ms)
    # aparecia em 1º e a vencedora `rrf` (118,8 ms) em 2º, na mesma tela que
    # explica que a `rrf` ganhou. Quem disputou vem primeiro, na ordem em que
    # disputou; o resto segue por nota; eliminadas por último.
    seat = {row["name"]: index for index, row in enumerate(contenders)}
    ranked.sort(
        key=lambda row: (
            row["eliminated"],
            seat.get(row["name"], len(seat)),
            -row["value"],
            row["starved"],
            row["p50"],
        )
    )

    # `eliminated` só marcava quem estourou o **tempo**, e a tela lê o campo como
    # "está fora". Quem caía no mata-mata continuava verde, com a nota inteira: o
    # cenário padrão exibia `rrf 100,0%`, `weighted 100,0%` e `ts_rank 100,0%`
    # lado a lado — e as duas últimas já tinham sido eliminadas, uma em
    # `tuning`, outra em `starved`. Aqui o booleano passa a valer "fora por
    # qualquer motivo" e `out_at` diz por qual, para a tela não ter que cruzar
    # `tiebreak` com `ranked` para saber quem ainda disputa.
    #
    # Depois do `sort` de propósito: ele usa `eliminated` como primeira chave, e
    # marcar antes jogaria as contendoras derrotadas para o fim da lista, fora
    # da ordem em que elas de fato disputaram.
    cut_reason = {row["name"]: row["reason"] for step in tiebreak for row in step["out"]}
    for row in ranked:
        if row["name"] in cut_reason:
            row["eliminated"] = True
            row["reason"] = cut_reason[row["name"]]
            row["out_at"] = "tiebreak"
        else:
            row["out_at"] = "budget" if row["eliminated"] else None

    if losers:
        # O motivo do desempate é lido do que de fato distinguiu — texto fixo
        # aqui produzia a contradição de anunciar "devolve a lista cheia" logo
        # acima do aviso de que ela devolve 10 listas curtas.
        reasons = []
        # A mesma lista em versão de legenda, montada **nas mesmas linhas** que a
        # longa. Duas listas construídas em blocos separados divergem no dia em
        # que alguém acrescenta um critério a um só; lado a lado, esquecer uma é
        # difícil de não ver.
        short_reasons = []
        worst_starved = min(row["starved"] for row in losers)
        if winner["starved"] < worst_starved:
            # "A única que devolve a lista cheia" só vale se ela devolve mesmo.
            # Ganhar por devolver menos listas curtas que as outras é outra
            # frase — a primeira contradizia o aviso logo abaixo em
            # `llm|instant|conceptual`, onde a vencedora tem 3 perguntas famintas
            # e as perdedoras, 10.
            reasons.append(
                "é a única que devolve a lista cheia"
                if winner["starved"] == 0
                else f"devolve lista curta em {winner['starved']} perguntas, "
                f"contra {worst_starved} da melhor concorrente"
            )
            short_reasons.append(
                "é a única que devolve a lista cheia"
                if winner["starved"] == 0
                else "devolve menos listas curtas"
            )
        if winner["tuning_free"] and any(not row["tuning_free"] for row in losers):
            reasons.append("não tem nada para calibrar")
            short_reasons.append("não tem nada para calibrar")
        if winner["p50"] < min(row["p50"] for row in losers):
            reasons.append(f"responde em {fmt_number(winner['p50'])} ms, o menor tempo entre elas")
            short_reasons.append(f"é a mais rápida ({fmt_number(winner['p50'])} ms)")
        # Enumeração com “e” antes da última, e cada nome entre aspas: quatro
        # nomes longos separados só por vírgula viram uma frase que ninguém
        # termina de ler — “empata com As duas juntas, somando notas, Busca por
        # palavra, simples” tem sete vírgulas e três nomes.
        names = [f"“{STRATEGY_LABEL[name]}”" for name in tied if name != winner["name"]]
        others = names[0] if len(names) == 1 else ", ".join(names[:-1]) + f" e {names[-1]}"
        why = (
            f"“{winner['label']}” acerta {fmt_number(winner['value'] * 100)}% e empata com "
            f"{others}: a diferença entre elas cabe dentro de uma pergunta. "
        )
        why += (
            f"O desempate não foi pela nota — {'; '.join(reasons)}."
            if reasons
            else "Nenhum critério as separou; esta ficou na frente por ordem de listagem."
        )
        # A mesma conclusão em duas linhas curtas, uma por linha do cartão. Sai
        # do que já existe (`tied`, `value`, `short_reasons`) — nenhum número
        # novo nasce aqui, e por isso não há como divergir do `why` logo ao lado.
        verdict = [
            f"{len(tied)} empataram em {fmt_number(winner['value'] * 100)}%",
            f"Ganhou porque {short_reasons[0]}"
            if short_reasons
            else "Ganhou por ordem de listagem: nenhum critério as separou",
        ]
    else:
        second = next((row for row in eligible if row["name"] != winner["name"]), None)
        why = f"“{winner['label']}” acerta {fmt_number(winner['value'] * 100)}%"
        if second:
            why += (
                f", contra {fmt_number(second['value'] * 100)}% da segunda colocada "
                f"(“{second['label']}”)"
            )
        why += f", e responde em {fmt_number(winner['p50'])} ms."
        verdict = ["Ganhou sozinha, sem empate"]
        if second:
            verdict.append(
                f"{fmt_number(winner['value'] * 100)}% contra "
                f"{fmt_number(second['value'] * 100)}% da segunda"
            )

    notes = []
    if winner["starved"] > 0:
        notes.append(
            f"Devolve lista incompleta em {winner['starved']} das perguntas deste "
            "tipo: acha o documento certo, mas traz pouca coisa junto. Se a tela "
            "mostra uma lista, ela vai parecer vazia."
        )
    if winner["name"] == "weighted":
        notes.append(
            "A soma de notas foi calibrada neste acervo. Em outro acervo as notas "
            "nascem em outra escala, e o ajuste precisa ser refeito — até lá o "
            "número cai sem avisar ninguém."
        )
    if winner["name"] == "rrf_rerank" and metric != "hit_at_10":
        rerank = next(r for r in rows if r["strategy"] == "rrf_rerank")
        fusion = next(r for r in rows if r["strategy"] == "rrf")
        if rerank["hit_at_10"] < fusion["hit_at_10"]:
            notes.append(
                f"O revisor derruba o “apareceu entre os dez” de "
                f"{fmt_number(fusion['hit_at_10'] * 100)}% para {fmt_number(rerank['hit_at_10'] * 100)}%: "
                "ele reordena os 20 primeiros e às vezes empurra o certo para fora "
                "da lista curta. Se um dia esses dez forem para um modelo ler, "
                "esta escolha muda."
            )
    # Quem subiu e quem desceu ao trocar a média geral pelo tipo de pergunta.
    # É a reviravolta da rodada 3, e o número que a sustenta: o denso sai de 81,1%
    # na média para 54,5% nos códigos. Sem o "de que posição para qual", a tela
    # mostraria notas novas sem dizer que **mudou de ordem**.
    #
    # A comparação é contra o placar como ele terminou a **rodada 2**, não contra
    # a ordem de nota global: é o que está desenhado na tela no instante anterior,
    # e "subiu duas posições" precisa bater com o que a pessoa acabou de ver.
    seat_before = _budget_seats(rows, metric, budget_ms)
    moved = [
        {
            "name": row["name"],
            "label": row["label"],
            "from": seat_before[row["name"]] + 1,
            "to": index + 1,
            "value": row["value"],
            "was": next(r[metric] for r in rows if r["strategy"] == row["name"]),
        }
        for index, row in enumerate(ranked)
        if seat_before[row["name"]] != index
    ]

    # A frase da rodada 3. Prioriza a **queda** e não a subida: o que a média
    # esconde é sempre alguém despencando, e é essa a lição da PoC. Sem troca
    # nenhuma a frase diz isso também — "não mudou nada" é resultado, não é falta
    # de resultado, e calar aqui deixaria o placar mudo justo na rodada que existe
    # para mostrar movimento.
    if moved:
        worst = min(moved, key=lambda item: item["value"] - item["was"])
        delta = (worst["was"] - worst["value"]) * 100
        if delta > 0:
            swap = (
                f"A mesa virou: “{worst['label']}” cai do {worst['from']}º para o "
                f"{worst['to']}º lugar e perde {fmt_number(delta)} pontos — "
                f"{fmt_number(worst['was'] * 100)}% na média, {fmt_number(worst['value'] * 100)}% neste "
                "tipo de pergunta. É exatamente isso que a tabela geral esconde."
            )
        else:
            best = max(moved, key=lambda item: item["value"] - item["was"])
            swap = (
                f"{len(moved)} trocam de lugar, e ninguém piora: “{best['label']}” sobe do "
                f"{best['from']}º para o {best['to']}º com {fmt_number(best['value'] * 100)}% "
                "neste tipo de pergunta."
            )
    else:
        swap = (
            "Ninguém troca de lugar: neste tipo de pergunta a ordem é a mesma da "
            "média geral. Acontece — o que não dá é contar com isso sem medir."
        )

    # As mesmas duas notícias em uma linha cada, para o vídeo (ver `_round_reader`).
    if moved:
        worst = min(moved, key=lambda item: item["value"] - item["was"])
        delta = (worst["was"] - worst["value"]) * 100
        swap_caption = (
            f"{STRATEGY_SHORT[worst['name']]} cai do {worst['from']}º ao {worst['to']}º — "
            f"perde {fmt_number(delta)} pontos"
            if delta > 0
            else f"{len(moved)} trocam de lugar, e ninguém piora"
        )
    else:
        swap_caption = "Ninguém troca de lugar neste tipo de pergunta"
    # `short_reasons` é a lista dos critérios que de fato distinguiram, na ordem
    # em que foram aplicados — o primeiro é o que decidiu. Só ele vai para a
    # legenda: citar todos devolve a frase longa que o vídeo não comporta. O
    # `and` faz short-circuit e é o que segura o `NameError`, porque a lista só
    # nasce dentro do `if losers`.
    why_caption = (
        f"{STRATEGY_SHORT[winner['name']]} ganha: {short_reasons[0]}"
        if losers and short_reasons
        else f"{STRATEGY_SHORT[winner['name']]} ganha sozinha, sem empate"
    )

    return {
        "winner": winner["name"],
        "value": winner["value"],
        "tied": tied,
        "ranked": ranked,
        "pipeline": PIPELINE_OF[winner["name"]],
        "why": why,
        "verdict": verdict,
        "notes": notes,
        "tiebreak": tiebreak,
        "moved": moved,
        "swap": swap,
        "swap_caption": swap_caption,
        "why_caption": why_caption,
    }


@app.get("/api/advice")
def advice() -> dict:
    """“Qual eu uso?” respondido pela medição, não por opinião.

    Todo número daqui sai do `results/evaluation.json`. O que esta rota
    acrescenta é aritmética: filtrar por tempo, escolher a coluna certa e
    ordenar. Nenhum vencedor está escrito no código — troque a medição e a
    recomendação muda junto.
    """
    path = RESULTS_DIR / "evaluation.json"
    if not path.is_file():
        raise HTTPException(503, "sem results/evaluation.json — rode 'task eval'")
    evaluation = json.loads(path.read_text(encoding="utf-8"))
    rows = evaluation["strategies"]
    totals = evaluation["queries"]

    # Uma pergunta a mais ou a menos move a nota em 1/37 = 2,7 pontos. Duas
    # estratégias separadas por menos que isso não estão em ordem de qualidade:
    # está uma pergunta que caiu para um lado. A tela chama isso de empate em
    # vez de coroar um vencedor que o próximo acervo derruba.
    band = 1.0 / totals["total"]

    grid = {}
    # As rodadas 1 e 2 não dependem do cenário inteiro: a régua depende só de quem
    # lê, e o corte por tempo de quem lê + quanto se espera. Guardá-las em mapas
    # de 3 e 9 entradas — em vez de repetir dentro das 27 células do grid — mantém
    # o payload numa chamada só, e o jogo sem espera entre rodadas.
    rounds_reader = {reader["id"]: _round_reader(rows, reader) for reader in ADVICE_READERS}
    rounds_budget = {}
    for reader in ADVICE_READERS:
        for budget in ADVICE_BUDGETS:
            rounds_budget[f"{reader['id']}|{budget['id']}"] = _round_budget(rows, reader, budget)
        for budget in ADVICE_BUDGETS:
            for kind in ADVICE_KINDS:
                grid[f"{reader['id']}|{budget['id']}|{kind['id']}"] = _rank_for(
                    rows, kind["id"], reader["metric"], budget["ms"], band
                )

    return {
        "queries": totals,
        "band": round(band, 4),
        "band_points": round(band * 100, 1),
        "readers": ADVICE_READERS,
        "budgets": ADVICE_BUDGETS,
        "kinds": ADVICE_KINDS,
        "strategies": [
            {
                "name": row["strategy"],
                "label": STRATEGY_LABEL[row["strategy"]],
                "short": STRATEGY_SHORT[row["strategy"]],
                "hit_at_1": row["hit_at_1"],
                "hit_at_3": row["hit_at_3"],
                "hit_at_10": row["hit_at_10"],
                "mrr": row["mrr"],
                "p50": row["query_ms_p50"],
                "starved": row["starved_queries"],
                "by_family": {
                    family: values["hit_at_1"] for family, values in row["by_family"].items()
                },
                "trait": STRATEGY_TRAIT[row["strategy"]],
                "pipeline": PIPELINE_OF[row["strategy"]],
            }
            for row in rows
        ],
        "grid": grid,
        "rounds": {"reader": rounds_reader, "budget": rounds_budget},
        "tiebreak_order": [
            {"id": item["id"], "title": item["title"], "why": item["why"]}
            for item in TIEBREAK_CRITERIA
        ],
        # A resposta curta, para quem não quer responder três perguntas. Os
        # nomes ficam aqui e os números que os sustentam saem de `strategies` —
        # não há número escrito duas vezes.
        "default": {"base": "rrf", "upgrade": "rrf_rerank", "avoid_alone": "dense"},
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
