"""Congela a API inteira em arquivos, para a PoC rodar sem backend.

A promessa do projeto é que todo número da tela vem do banco. Publicar num host
estático não pode virar exceção a isso — então nada aqui é escrito à mão: cada
arquivo é a RESPOSTA do servidor rodando, gravada como está. O que muda é só de
onde o front lê.

O que não dá para congelar é a pergunta livre: sem Postgres e sem Ollama do outro
lado, só existe resposta para as perguntas que foram medidas. O front trata a
ausência como erro explicado, nunca como lista vazia — lista vazia numa tela que
compara motores de busca lê como "o motor não achou nada", que é exatamente a
conclusão errada.
"""

from __future__ import annotations

import json
import sys
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

# Os mesmos `k` que o `<select>` do front oferece (App.jsx). Congelar um `k` que
# ninguém pede é peso morto; faltar um deixa a tela sem resposta no meio de uma
# interação que ela mesma ofereceu.
SEARCH_K = (3, 5, 10)


def slugify(text: str) -> str:
    """Nome de arquivo estável para uma pergunta — o front repete isto em JS.

    Sem acento e sem hash: o diretório publicado fica legível, e conferir se uma
    pergunta foi congelada é um `ls`. As duas implementações têm que casar, então
    a regra é a mais simples possível: minúscula, sem acento, resto vira hífen.
    """
    plain = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(ch for ch in plain if not unicodedata.combining(ch))
    out = [ch if ch.isalnum() else "-" for ch in plain]
    return "-".join(part for part in "".join(out).split("-") if part)


class Exporter:
    def __init__(self, base: str, out: Path) -> None:
        self.base = base.rstrip("/")
        self.out = out
        self.written = 0
        self.bytes = 0

    def save(self, path: str, target: str) -> dict:
        with urllib.request.urlopen(f"{self.base}{path}", timeout=60) as response:
            body = response.read()
        destination = self.out / target
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(body)
        self.written += 1
        self.bytes += len(body)
        return json.loads(body)


def main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8081"
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "dist") / "data"
    snapshot_map = Path(sys.argv[3]) if len(sys.argv) > 3 else None

    export = Exporter(base, out)

    print("  state")
    state = export.save("/api/state", "state.json")

    # As quatro telas que não dependem de pergunta. São as que carregam o
    # raciocínio da PoC — placar, discordâncias e a recomendação — e sem elas o
    # que sobra publicado é um campo de busca sem tese.
    for route, name in (
        ("/api/measured", "measured.json"),
        ("/api/disagreements", "disagreements.json"),
        ("/api/advice", "advice.json"),
    ):
        print(f"  {name}")
        export.save(route, name)

    strategies = [row["name"] for row in state["strategies"]]
    print(f"  code × {len(strategies)}")
    for name in strategies:
        export.save(f"/api/code/{name}", f"code/{name}.json")

    queries = state["queries"]
    slugs: list[str] = []
    seen: dict[str, str] = {}
    print(f"  search × {len(queries)} perguntas × {len(SEARCH_K)} valores de k")
    for query in queries:
        text = query["text"]
        slug = slugify(text)
        # Colisão de slug faz uma pergunta responder pela outra, calada. Só se
        # manifesta como "cliquei na pergunta A e veio o resultado de B", que
        # ninguém atribui ao exportador.
        if slug in seen and seen[slug] != text:
            print(f"🛑 slug repetido: {slug!r} — {seen[slug]!r} e {text!r}", file=sys.stderr)
            return 1
        seen[slug] = text
        slugs.append(slug)
        encoded = urllib.parse.quote(text)
        for k in SEARCH_K:
            export.save(f"/api/search?q={encoded}&k={k}", f"search/{slug}-k{k}.json")

    # O corpus INTEIRO, não só o que os resultados congelados apontam. A aba do
    # catálogo lista os 114 e cada linha abre a ficha; rastrear referência
    # deixaria de fora justamente o documento que ninguém recupera — que é o
    # mais interessante de abrir, porque explica por que ele nunca aparece.
    # Num host estático o clique perdido não mostra erro, só não faz nada.
    documents = sorted(doc["doc_id"] for doc in state["catalog"])
    print(f"  document × {len(documents)}")
    for doc_id in documents:
        export.save(f"/api/document/{urllib.parse.quote(doc_id)}", f"document/{doc_id}.json")

    if snapshot_map is not None:
        # O front precisa saber, em tempo de build, o que existe congelado — é o
        # que separa "pergunta que não foi medida" (aviso honesto) de "arquivo
        # que faltou" (defeito). Gravado como fonte, não como asset: o bundle
        # embute e a checagem acontece antes do fetch.
        snapshot_map.write_text(
            json.dumps(
                {
                    "queries": [q["text"] for q in queries],
                    "slugs": slugs,
                    "k": list(SEARCH_K),
                    "documents": documents,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    print(f"  {export.written} arquivos, {export.bytes / 1024:.0f} kB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
