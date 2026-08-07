#!/usr/bin/env python3
"""Canário do front: exercita todas as rotas e o bundle, sem browser.

A tela é a parte da PoC que ninguém testa — abre bonito e mente calado. Três
falhas que só este script pega:

1. **rota que responde 200 com o campo errado.** O front lê `first_relevant`;
   se a chave sumir num refactor, o cartão para de marcar acerto e continua
   verde na tela.
2. **bundle antigo.** O `index.html` referencia `assets/index-<hash>.js`. Um
   build interrompido deixa o HTML novo apontando para um asset que já foi
   apagado — o servidor devolve 404 só para aquele arquivo, e a página fica
   branca sem nenhum erro no terminal.
3. **número que o front exibe divergindo do medido.** O `/api/measured` tem que
   devolver exatamente o `results/evaluation.json`, não uma versão recalculada.

Não aborta na primeira falha de propósito: uma rodada mostra tudo que está
quebrado, como o `08-validar.sh` da rule 32. O código de saída soma os erros.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8081"
ROOT = Path(__file__).resolve().parent.parent

errors = 0


def fail(message: str) -> None:
    global errors
    errors += 1
    print(f"  🛑 {message}")


def ok(message: str) -> None:
    print(f"  ✅ {message}")


def get(path: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(BASE + path, timeout=120) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except OSError as exc:
        return 0, str(exc).encode()


def get_json(path: str) -> dict | None:
    status, body = get(path)
    if status != 200:
        fail(f"{path} devolveu {status}: {body[:160].decode(errors='replace')}")
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        fail(f"{path} não é JSON: {exc}")
        return None


def require(condition: bool, message: str) -> None:
    ok(message) if condition else fail(message)


print(f"\n== 1. página e bundle ({BASE}/) ==")
status, html = get("/")
if status != 200:
    fail(f"/ devolveu {status} — 'task web:build' rodou?")
else:
    text = html.decode("utf-8", errors="replace")
    ok(f"index.html servido ({len(html)} bytes)")
    # Cada asset citado pelo HTML tem que existir DE VERDADE. É a checagem que
    # separa "compilou" de "a página abre".
    assets = re.findall(r'(?:src|href)="(/static/[^"]+)"', text)
    require(len(assets) >= 2, f"{len(assets)} assets referenciados no HTML")
    for asset in assets:
        code, payload = get(asset)
        require(code == 200 and len(payload) > 0, f"{asset} → {code} ({len(payload)} B)")

print("\n== 2. /api/state ==")
state = get_json("/api/state")
if state:
    require(state["corpus"]["total"] > 0, f"corpus com {state['corpus']['total']} documentos")
    require(
        state["corpus"]["records"] + state["corpus"]["prose"] == state["corpus"]["total"],
        "records + prose fecha com o total",
    )
    # Os dois eixos têm que fechar SEPARADAMENTE. Foi somando `record` com
    # "escrito à mão" que a tela anunciou 26 alvos onde o corpus tem 34: os 8
    # procedimentos são handwritten e prose ao mesmo tempo.
    require(
        state["corpus"]["handwritten"] + state["corpus"]["wikipedia"] == state["corpus"]["total"],
        f"origem fecha: {state['corpus']['handwritten']} à mão + "
        f"{state['corpus']['wikipedia']} Wikipédia",
    )
    require(
        state["corpus"]["handwritten"] != state["corpus"]["records"],
        "origem e forma são eixos distintos (não colapsaram no mesmo número)",
    )
    require(len(state["strategies"]) == 6, f"{len(state['strategies'])} estratégias expostas")
    require(all(s["label"] for s in state["strategies"]), "toda estratégia tem nome em pt-BR")
    # A explicação de tela é contrato, não enfeite: sem ela o cartão mostra um
    # número e nenhuma pista de por que aquele número é assim. Cobrar os três
    # campos separadamente porque o modo de falha real é acrescentar estratégia
    # nova e esquecer de descrever onde ela erra — que é justamente a parte que
    # ninguém escreve espontaneamente.
    for field in ("how", "good", "bad"):
        missing = [
            s["name"]
            for s in state["strategies"]
            if not (s.get("plain") or {}).get(field, "").strip()
        ]
        require(not missing, f"toda estratégia explica '{field}'" + (f" — falta em {missing}" if missing else ""))
    # A tela imprime esse texto como texto, sem passar por Markdown. `**x**`
    # escrito aqui aparece com os asteriscos na cara do usuário — aconteceu em
    # `rrf` e `rrf_rerank`, e só o print mostrou.
    marked = [
        s["name"]
        for s in state["strategies"]
        if "**" in " ".join((s.get("plain") or {}).values())
    ]
    require(not marked, "explicações sem Markdown cru" + (f" — {marked}" if marked else ""))
    require(len(state["queries"]) > 0, f"{len(state['queries'])} consultas com gabarito")
    require(
        {q["family"] for q in state["queries"]} == {"literal", "conceptual", "hybrid"},
        "as três famílias presentes",
    )
    require(state["settings"]["dim"] > 0, f"dimensão medida do banco: {state['settings']['dim']}")
    require(len(state["catalog"]) == state["corpus"]["total"], "catálogo com o corpus inteiro")
    require(len(state["indexes"]) >= 2, f"{len(state['indexes'])} índices no catálogo do Postgres")

print("\n== 3. /api/search — consulta COM gabarito ==")
sample = state["queries"][0] if state and state["queries"] else None
if sample:
    payload = get_json(f"/api/search?q={urllib.parse.quote(sample['text'])}&k=5")
    if payload:
        require(payload["has_ground_truth"], f"'{sample['text'][:40]}…' reconhecida no gabarito")
        require(set(payload["results"]) == {s["name"] for s in state["strategies"]},
                "as 6 estratégias responderam")
        for name, result in payload["results"].items():
            keys = {"label", "hits", "ms", "returned", "starved", "first_relevant"}
            require(keys <= set(result), f"{name}: contrato completo")
            require(result["ms"] >= 0, f"{name}: {result['ms']} ms")
            require(
                result["returned"] == len(result["hits"]),
                f"{name}: returned bate com a lista ({result['returned']})",
            )
            require(
                result["starved"] == (result["returned"] < payload["k"]),
                f"{name}: starved coerente com returned",
            )
            for hit in result["hits"]:
                if hit["relevant"] is None:
                    fail(f"{name}: relevant nulo numa consulta com gabarito")
        # `first_relevant` é a posição do primeiro acerto — se existir acerto.
        for name, result in payload["results"].items():
            first = next((h["rank"] for h in result["hits"] if h["relevant"]), None)
            require(
                result["first_relevant"] == first,
                f"{name}: first_relevant={result['first_relevant']} confere com a lista",
            )

print("\n== 4. /api/search — pergunta livre, sem gabarito ==")
free = get_json("/api/search?q=" + urllib.parse.quote("quantos parafusos tem um guindaste"))
if free:
    require(not free["has_ground_truth"], "pergunta inédita NÃO ganha gabarito inventado")
    require(
        all(h["relevant"] is None for r in free["results"].values() for h in r["hits"]),
        "sem gabarito, nenhum resultado é marcado certo ou errado",
    )
    require(isinstance(free["query_lexemes"], list), "lexemas da pergunta devolvidos")

print("\n== 5. /api/document ==")
if state:
    target = state["catalog"][0]["doc_id"]
    doc = get_json(f"/api/document/{target}")
    if doc:
        require(doc["vector_dim"] == state["settings"]["dim"], f"vetor com {doc['vector_dim']} dimensões")
        require(len(doc["vector_preview"]) == 24, "prévia de 24 números")
        require(len(doc["lexemes"]) > 0, f"{len(doc['lexemes'])} lexemas guardados")
        require(
            all(row["idf"] is not None and row["tf"] > 0 for row in doc["lexemes"]),
            "todo lexema tem tf e IDF",
        )
        # IDF cai quando df sobe — se essa relação inverter, a coluna está errada.
        pairs = [(row["df"], row["idf"]) for row in doc["lexemes"]]
        require(
            all(a[1] >= b[1] for a, b in zip(pairs, pairs[1:]) if a[0] <= b[0]),
            "IDF é monotônico em relação ao df",
        )
    require(get("/api/document/nao-existe-42")[0] == 404, "documento inexistente devolve 404")

print("\n== 6. /api/code — o tour lê o disco ==")
for strategy in ("ts_rank", "bm25", "dense", "weighted", "rrf", "rrf_rerank"):
    tour = get_json(f"/api/code/{strategy}")
    if tour:
        require(len(tour["blocks"]) > 0, f"{strategy}: {len(tour['blocks'])} bloco(s)")
        for block in tour["blocks"]:
            path = ROOT / block["file"]
            snippet = block["code"].splitlines()[0].strip()
            source = path.read_text(encoding="utf-8").splitlines()
            live = source[block["first_line"] - 1].strip() if path.is_file() else ""
            require(
                path.is_file() and live == snippet,
                f"{strategy}: {block['file']}:{block['first_line']} confere com o arquivo",
            )
require(get("/api/code/inexistente")[0] == 404, "estratégia sem tour devolve 404")

print("\n== 7. /api/measured — igual ao JSON no disco ==")
measured = get_json("/api/measured")
if measured:
    for name in ("evaluation", "experiments"):
        path = ROOT / "results" / f"{name}.json"
        if not path.is_file():
            print(f"  ➖ results/{name}.json ausente — 'task all' não rodou por completo")
            continue
        require(
            measured.get(name) == json.loads(path.read_text(encoding="utf-8")),
            f"{name} servido byte a byte como o medido",
        )

print("\n== 8. /api/disagreements ==")
blocks = get_json("/api/disagreements")
if blocks:
    require(len(blocks["blocks"]) == 4, f"{len(blocks['blocks'])} blocos de discordância")
    for block in blocks["blocks"]:
        require(bool(block["title"] and block["note"]), f"'{block['title'][:40]}' com nota")
        for case in block["cases"]:
            require(
                bool(case["query_id"] and case["text"]),
                f"{case.get('query_id')}: id e texto presentes",
            )
    total = sum(len(b["cases"]) for b in blocks["blocks"])
    print(f"  ℹ️  {total} casos no total (um mesmo caso pode aparecer em 2 blocos)")

def check_caption(text: str, where: str) -> list[str]:
    """Uma legenda do vídeo cabe numa linha, ou desaparece sem avisar.

    A composição usa `white-space: nowrap` — dobrar a linha faria a segunda subir
    por cima da última linha do placar, que foi o defeito que motivou o `nowrap`.
    O preço é que o excesso agora sai pela borda e o `overflow: hidden` do palco
    o engole: legenda longa não quebra o layout, ela some pelo lado, que é falha
    silenciosa e por isso mora aqui.

    O teto de 100 é MEDIDO, não estimado: a legenda mais longa hoje (62 chars,
    `first|click|literal`) ocupa 812 px dos 1488 px úteis a 38 px de corpo — 13,1
    px por caractere. A composição cai para 30 px acima de 62 chars, o que estica
    o limite físico para ~144. 100 é o meio-termo com folga para caractere largo.
    """
    problems = []
    if not text:
        problems.append(f"{where} sem legenda — a cena fica muda")
    elif len(text) > 100:
        problems.append(f"{where} com {len(text)} chars — passa de 100 e sai pela borda")
    return problems


print("\n== 9. /api/advice — a recomendação ==")
advice = get_json("/api/advice")
if advice:
    combos = len(advice["readers"]) * len(advice["budgets"]) * len(advice["kinds"])
    require(len(advice["grid"]) == combos, f"grid com {combos} cenários, um por combinação")
    # A rota arredonda a faixa em 4 casas para caber na tela; comparar com o
    # 1/37 cru falha por 2,7e-5 e o erro parece um defeito de cálculo.
    require(
        advice["band"] == round(1 / advice["queries"]["total"], 4),
        f"faixa de ruído = 1/{advice['queries']['total']} = {advice['band_points']} pontos",
    )
    known = {row["name"]: row for row in advice["strategies"]}
    require(len(known) == 6, f"{len(known)} estratégias no payload")
    require(
        all(row["trait"]["needs"] and row["trait"]["risk"] for row in advice["strategies"]),
        "toda estratégia declara o que exige e o risco dela",
    )
    # A aritmética é do back-end justamente para caber aqui. Cada asserção abaixo
    # já pegou um defeito de verdade: vencedor fora do empate, texto de desempate
    # contradizendo a nota logo abaixo, e lista com outra ordem que o cartão.
    for key, cell in advice["grid"].items():
        reader, budget, kind = key.split("|")
        if cell["winner"] is None:
            continue
        problems = []
        if cell["winner"] not in known:
            problems.append("vencedora não existe em strategies")
        if cell["winner"] not in cell["tied"]:
            problems.append("vencedora fora da própria lista de empate")
        if cell["ranked"] and cell["ranked"][0]["name"] != cell["winner"]:
            problems.append(f"lista começa por {cell['ranked'][0]['name']}, não pela vencedora")
        if cell["pipeline"] != known[cell["winner"]]["pipeline"]:
            problems.append("pipeline diverge do declarado na estratégia")
        # Contradição textual: anunciar "lista cheia" e avisar de lista incompleta.
        starved_note = any("lista incompleta" in note for note in cell["notes"])
        if starved_note and "devolve a lista cheia" in cell["why"]:
            problems.append("o porquê diz 'lista cheia' e a nota diz 'lista incompleta'")
        # Markdown cru vaza para a tela como asterisco literal.
        for text in [cell["why"], *cell["notes"]]:
            if re.search(r"\*\*|`", text):
                problems.append("Markdown cru no texto")
                break
        # Toda empatada tem que caber na faixa em relação à vencedora.
        by_name = {row["name"]: row for row in cell["ranked"]}
        gaps = [cell["value"] - by_name[name]["value"] for name in cell["tied"]]
        if any(gap >= advice["band"] for gap in gaps):
            problems.append("alguém no empate está fora da faixa de ruído")
        # A partir daqui é o jogo: o placar da direita e as rodadas desenham
        # exatamente estes campos, e cada um já apareceu errado na tela.
        if not cell["swap"]:
            problems.append("rodada 3 sem frase — o placar se mexe e ninguém sabe por quê")
        problems += check_caption(cell["swap_caption"], "legenda da rodada 3")
        problems += check_caption(cell["why_caption"], "legenda da campeã")
        if not cell["podium"] or cell["podium"][0]["name"] != cell["winner"]:
            problems.append("o pódio não começa pela vencedora")
        # O mata-mata é uma sequência: cada etapa recebe quem passou da anterior,
        # e a última tem que terminar na vencedora. Etapa que "decide" sem tirar
        # ninguém é o defeito clássico — a tela mostra o critério e a lista igual.
        entered_before = None
        for index, step in enumerate(cell["tiebreak"]):
            names_in = set(step["entered"])
            names_pass = set(step["passed"])
            names_out = {row["name"] for row in step["out"]}
            if not names_pass:
                problems.append(f"etapa {index + 1} do mata-mata elimina todo mundo")
            if not names_pass <= names_in:
                problems.append(f"etapa {index + 1} deixa passar quem não entrou")
            if names_in - names_pass != names_out:
                problems.append(f"etapa {index + 1} não fecha: entrou − passou ≠ saiu")
            if step["decided"] and not names_out:
                problems.append(f"etapa {index + 1} diz que decidiu sem tirar ninguém")
            if entered_before is not None and names_in != entered_before:
                problems.append(f"etapa {index + 1} não recebe quem passou da anterior")
            entered_before = names_pass
        if cell["tiebreak"] and cell["tiebreak"][-1]["passed"][0] != cell["winner"]:
            problems.append("o mata-mata termina em outra estratégia que não a vencedora")
        # "subiu duas posições" só vale se o de-para bater com o placar desenhado.
        for item in cell["moved"]:
            if item["from"] == item["to"]:
                problems.append(f"{item['name']} está na lista de trocas sem ter trocado")
        require(not problems, f"{key} → {cell['winner']}" + (f" [{'; '.join(problems)}]" if problems else ""))
    winners = {cell["winner"] for cell in advice["grid"].values()}
    print(f"  ℹ️  {len(winners)} estratégias diferentes vencem em algum cenário: {sorted(winners)}")
    require(
        advice["default"]["base"] in known and advice["default"]["upgrade"] in known,
        "a resposta curta aponta para estratégias que existem",
    )

print("\n== 10. /api/advice — as rodadas do jogo ==")
if advice:
    readers = advice["readers"]
    budgets = advice["budgets"]
    require(
        len(advice["rounds"]["reader"]) == len(readers),
        f"rodada 1 pronta para as {len(readers)} réguas",
    )
    require(
        len(advice["rounds"]["budget"]) == len(readers) * len(budgets),
        f"rodada 2 pronta para as {len(readers) * len(budgets)} combinações de régua × relógio",
    )
    # As duas primeiras rodadas vêm prontas justamente para o placar não recalcular
    # nada no navegador. Se o back-end mandar um placar com menos de 6 linhas, a
    # tela some com uma competidora sem dizer que ela saiu.
    for key, round_data in advice["rounds"]["reader"].items():
        problems = []
        if len(round_data["board"]) != len(known):
            problems.append(f"placar com {len(round_data['board'])} linhas, não {len(known)}")
        if any(row["eliminated"] for row in round_data["board"]):
            problems.append("alguém eliminado numa rodada que não elimina ninguém")
        if not round_data["headline"]:
            problems.append("rodada sem frase")
        problems += check_caption(round_data["caption"], "legenda da rodada 1")
        values = [row["value"] for row in round_data["board"]]
        if values != sorted(values, reverse=True):
            problems.append("placar fora de ordem")
        require(not problems, f"rodada 1 · {key}" + (f" [{'; '.join(problems)}]" if problems else ""))
    for key, round_data in advice["rounds"]["budget"].items():
        problems = []
        board = round_data["board"]
        if len(board) != len(known):
            problems.append(f"placar com {len(board)} linhas, não {len(known)}")
        cut = [row["name"] for row in board if row["eliminated"]]
        if cut != [row["name"] for row in round_data["out"]]:
            problems.append("quem está riscado no placar não é quem está na lista de fora")
        if len(round_data["alive"]) + len(round_data["out"]) != len(known):
            problems.append("vivas + fora não fecham o total")
        # A eliminação é por relógio, e só por relógio: linha riscada com p50
        # dentro do limite significa que a régua de corte mudou no meio.
        for row in board:
            over = row["p50"] > round_data["ms"]
            if over != row["eliminated"]:
                problems.append(f"{row['name']} com {row['p50']:.1f} ms marcada errada")
        if any(row["eliminated"] and not row["reason"] for row in board):
            problems.append("eliminada sem motivo escrito")
        if not round_data["headline"]:
            problems.append("rodada sem frase")
        problems += check_caption(round_data["caption"], "legenda da rodada 2")
        require(not problems, f"rodada 2 · {key}" + (f" [{'; '.join(problems)}]" if problems else ""))
    require(
        len(advice["tiebreak_order"]) == 3
        and all(step["title"] and step["why"] for step in advice["tiebreak_order"]),
        "os 3 critérios do mata-mata chegam com título e motivo",
    )
    # Concordância de plural em frase montada com contagem. “1 saem por tempo” e
    # “1 das 6 chegam” apareceram na tela porque o verbo era fixo e o número não —
    # o defeito só se manifesta no dia em que a contagem cai para 1, que é
    # justamente o cenário mais interessante (uma eliminada, uma que passa). A
    # varredura é sobre o payload inteiro serializado porque a frase pode nascer
    # em qualquer rodada, célula ou etapa, e cobrir campo por campo deixaria de
    # fora o próximo campo que alguém acrescentar.
    plural_slips = re.findall(
        r"\b1 (?:saem|chegam|passam|entram|competidoras|primeiras|estratégias)\b",
        json.dumps(advice, ensure_ascii=False),
    )
    require(not plural_slips, f"nenhuma frase com “1” seguido de verbo no plural ({len(plural_slips)} achadas)")

print(f"\n== erros: {errors} ==")
sys.exit(1 if errors else 0)
