"""Recorte do código-fonte real de cada estratégia, lido do disco na hora.

Não é cópia colada num dicionário: o arquivo é aberto e o bloco é localizado por
nome de símbolo. Se alguém editar o `Bm25Retriever`, o popup da tela muda junto —
é o que impede a explicação de envelhecer em silêncio enquanto o código anda.

A alternativa óbvia (`inspect.getsource`) foi descartada: ela exige importar o
módulo, e importar `cross_encoder` puxa `torch` para dentro do processo web só
para exibir dez linhas de texto.
"""

from __future__ import annotations

import ast
from pathlib import Path

from ..config import SETTINGS

SRC = Path(__file__).resolve().parent.parent

# Cada entrada é um trecho de tela: o arquivo, o símbolo, e a frase que diz o
# que olhar ali. A frase é editorial — o código é lido, ela não.
TOUR: dict[str, list[dict]] = {
    "ts_rank": [
        {
            "file": "adapters/lexical.py",
            "symbol": "TsRankRetriever.search",
            "note": "Uma consulta ao índice GIN. Sem IDF em lugar nenhum — o `ts_rank_cd`"
            " pontua cobertura, não raridade.",
        },
        {
            "file": "adapters/lexical.py",
            "symbol": "query_lexemes",
            "note": "A consulta passa pelo MESMO analisador que indexou o corpus."
            " Tokenizar em Python seria a fonte clássica de discrepância.",
        },
    ],
    "bm25": [
        {
            "file": "adapters/lexical.py",
            "symbol": "Bm25Retriever.search",
            "note": "A fórmula inteira em SQL, sobre as mesmas tabelas que o ts_rank lê."
            " A diferença entre as duas estratégias é só esta expressão.",
        },
        {
            "file": "adapters/postgres.py",
            "symbol": "DocumentStore.build_lexical_stats",
            "note": "`unnest(tsvector)` desmonta o índice em (documento, termo, tf)."
            " É o que garante que BM25 conte os mesmos termos que o Postgres conta.",
        },
    ],
    "dense": [
        {
            "file": "adapters/dense_retriever.py",
            "symbol": "DenseRetriever.search",
            "note": "`<=>` é distância cosseno; a similaridade é `1 - distância`."
            " O ORDER BY é o que o HNSW acelera.",
        },
        {
            "file": "adapters/ollama_embedder.py",
            "symbol": "OllamaEmbedder.embed",
            "note": "Um POST por consulta. É daqui que vêm os ~110 ms do denso —"
            " custo de rede e de modelo, não de álgebra.",
        },
    ],
    "weighted": [
        {
            "file": "strategies/fusion.py",
            "symbol": "weighted_fusion",
            "note": "O defeito não é a soma, é o normalizador: `min` e `max` saem"
            " daquela consulta, e documento ausente de uma lista entra como 0.",
        },
    ],
    "rrf": [
        {
            "file": "strategies/fusion.py",
            "symbol": "reciprocal_rank_fusion",
            "note": "Joga o score fora e usa só a posição. É grosseiro, e é por isso"
            " que funciona: posição é a única grandeza comum aos dois motores.",
        },
    ],
    "rrf_rerank": [
        {
            "file": "adapters/cross_encoder.py",
            "symbol": "CrossEncoderReranker.rerank",
            "note": "Uma inferência por par (consulta, documento). Documento fora do"
            f" prefetch de {SETTINGS.prefetch_limit} é invisível — reranker não recupera.",
        },
        {
            "file": "strategies/base.py",
            "symbol": "RerankStrategy.search",
            "note": "Recupera larga, reordena estreito. O prefetch é o teto do que o"
            " reranker pode consertar.",
        },
    ],
}


def _segment(path: Path, symbol: str) -> dict:
    """Extrai o bloco do símbolo com `ast`, que sabe onde a definição termina.

    Procurar por `def nome` e cortar na próxima linha em branco funciona até o
    primeiro corpo com linha em branco no meio — e aí o recorte engana em vez de
    explicar.
    """
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    target: ast.AST | None = None

    if "." in symbol:
        class_name, method = symbol.split(".", 1)
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for child in node.body:
                    if isinstance(child, ast.FunctionDef) and child.name == method:
                        target = child
        # Decorador acima da linha do `def` não entra no `lineno` da função em
        # Python < 3.8; aqui entra, mas o recorte fica melhor sem ele.
    else:
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == symbol:
                target = node

    if target is None:
        raise KeyError(f"símbolo {symbol} não achado em {path.name}")

    lines = source.splitlines()
    start, end = target.lineno, target.end_lineno or target.lineno
    return {
        "code": "\n".join(lines[start - 1 : end]),
        "first_line": start,
        "lines": end - start + 1,
    }


def tour_for(strategy: str) -> dict:
    if strategy not in TOUR:
        raise KeyError(strategy)
    blocks = []
    for entry in TOUR[strategy]:
        path = SRC / entry["file"]
        segment = _segment(path, entry["symbol"])
        blocks.append(
            {
                "file": f"src/retrieval_poc/{entry['file']}",
                "symbol": entry["symbol"],
                "note": entry["note"],
                **segment,
            }
        )
    return {"strategy": strategy, "blocks": blocks}
