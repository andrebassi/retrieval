"""Confere que o README afirma só o que foi medido.

Existe porque a regra 1 do `CLAUDE.md` — nenhum número sem o comando que o mediu —
não se sustenta na disciplina: um `task all` novo muda as latências, e o README
fica mentindo em silêncio. Aqui o desalinhamento vira rc != 0.

Cada bloco imprime o que mediu ANTES de julgar, e nenhum aborta o seguinte: o
valor está em ver a lista inteira de divergências numa passada, não a primeira.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
RESULTS = ROOT / "results"

problems: list[str] = []


def slug(text: str) -> str:
    """Reproduz o slug de âncora do GitHub.

    Duas armadilhas já pagas aqui: o GitHub **descarta** `—` e emoji em vez de
    trocá-los por hífen, e **não colapsa** espaços consecutivos — por isso
    `## Por família — onde a média mente` vira `...família--onde...`, com dois
    hífens. Colapsar acusa âncora quebrada onde o link está certo.
    """
    t = re.sub(r"`", "", text.strip().lower())
    t = re.sub(r"[^\w\s\-]", "", t, flags=re.UNICODE)
    return t.strip().replace(" ", "-")


def check_latencies(md: str) -> None:
    evaluation = json.loads((RESULTS / "evaluation.json").read_text(encoding="utf-8"))
    experiments = json.loads((RESULTS / "experiments.json").read_text(encoding="utf-8"))

    measured: set[float] = set()
    for entry in evaluation["strategies"]:
        measured.update(round(entry[k], 1) for k in ("query_ms_p50", "query_ms_p95"))
        # O tempo **por família** também é medição, e é o que a aba “Qual devo
        # usar?” compara — o cenário já fixou o tipo de pergunta, então o custo
        # relevante é o daquele tipo. Sem isto, citar no texto um número que a
        # tela exibe era acusado de órfão.
        for family in entry["by_family"].values():
            measured.update(round(family[k], 1) for k in ("query_ms_p50", "query_ms_p95"))
    for block in experiments.values():
        for key, value in block.items():
            if isinstance(value, (int, float)) and "ms" in key:
                measured.add(round(float(value), 1))

    cited = {float(m.replace(",", ".")) for m in re.findall(r"(\d+,\d)\s*ms", md)}
    print(f"latências medidas nos JSON: {len(measured)} valores distintos")
    # Tolerância de 0,1: `round` do Python arredonda 126,25 para o par (126,2) e
    # o texto escreve 126,3. As duas grafias descrevem a mesma medição.
    orphans = sorted(c for c in cited if not any(abs(c - m) <= 0.1 for m in measured))
    if orphans:
        problems.append(f"latências citadas sem medição correspondente: {orphans}")
    else:
        print(f"✅ as {len(cited)} latências citadas existem nos JSON")


def check_anchors(md: str) -> None:
    headings = {slug(h) for h in re.findall(r"^#{1,6}\s+(.*)$", md, re.M)}
    links = re.findall(r"\]\(#([^)]+)\)", md)
    broken = [link for link in links if link not in headings]
    if broken:
        problems.append(f"âncoras quebradas: {broken}")
    else:
        print(f"✅ {len(links)} links internos apontam para headings existentes")


def check_code_counts(md: str) -> None:
    lines = sum(
        1
        for path in sorted((ROOT / "src").rglob("*.py"))
        for _ in path.read_text(encoding="utf-8").splitlines()
    )
    scripts = len(list((ROOT / "scripts").glob("[0-9][0-9]-*.sh")))
    print(f"código: {lines} linhas de Python, {scripts} scripts numerados")

    # O README escreve milhar com espaço fino ("2 069"), então a comparação
    # normaliza antes — senão o regex nunca casa e o teste passa por vacuidade.
    claimed_lines = re.search(r"\*\*([\d\s  ]+) linhas de Python\*\*", md)
    if not claimed_lines:
        problems.append("README não afirma contagem de linhas de Python")
    else:
        value = int(re.sub(r"\D", "", claimed_lines.group(1)))
        if value != lines:
            problems.append(f"README diz {value} linhas de Python, medido {lines}")

    claimed_scripts = re.search(r"(\d+) scripts numerados", md)
    if not claimed_scripts:
        problems.append("README não afirma quantidade de scripts")
    elif int(claimed_scripts.group(1)) != scripts:
        problems.append(
            f"README diz {claimed_scripts.group(1)} scripts, medido {scripts}"
        )


def check_index_sizes(md: str) -> None:
    """Tamanho de índice sai do banco, não da memória — e o banco pode estar no chão."""
    query = (
        "SELECT indexrelname, pg_size_pretty(pg_relation_size(indexrelid)) "
        "FROM pg_stat_user_indexes WHERE relname = 'documents' ORDER BY 1;"
    )
    proc = subprocess.run(
        ["psql", "postgresql://postgres@127.0.0.1:5434/retrieval", "-Atc", query],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        print("⚠️  banco fora do ar — tamanhos de índice não verificados "
              "(rode `task db:up`)")
        return
    for line in proc.stdout.strip().splitlines():
        name, size = line.split("|")
        # Só cobra o índice que o README resolveu citar pelo nome. Exigir todos
        # transformaria o canário em ruído: `documents_pkey` não interessa a
        # ninguém e apareceria como erro para sempre.
        cited = name in md
        print(f"índice {name}: {size}" + ("" if cited else "  (não citado — ignorado)"))
        if cited and size.replace(" ", "") not in md.replace(" ", ""):
            problems.append(f"README cita {name} com tamanho diferente de {size}")


def main() -> int:
    md = README.read_text(encoding="utf-8")
    for check in (check_latencies, check_anchors, check_code_counts, check_index_sizes):
        print(f"\n── {check.__name__}")
        check(md)

    print()
    for problem in problems:
        print(f"🛑 {problem}", file=sys.stderr)
    print(f"erros: {len(problems)}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
