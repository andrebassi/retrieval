"""Monta o corpus: documentos-alvo escritos à mão + distratores da Wikipédia.

Por que a divisão existe:

- **Alvos** (`data/documents.yaml`) são escritos sabendo qual consulta cada um
  responde. É o que torna o gabarito defensável — com corpus só baixado, ninguém
  consegue afirmar com honestidade qual trecho responde a "por que a máquina
  superaqueceu".
- **Distratores** vêm da Wikipédia em português porque texto real tem
  distribuição de termo, tamanho e ruído que texto gerado não tem. BM25 vive de
  IDF, e IDF só faz sentido sobre distribuição real.

Os distratores passam por uma blocklist temática: artigo que fale do assunto dos
alvos é descartado. Isso protege o gabarito (ninguém sabe se um artigo sobre
compressores responderia melhor que a OS-4471), ao custo de deixar os
distratores mais fáceis do que seriam num corpus corporativo real — onde o mesmo
assunto se repete em dezenas de documentos. O README registra isso como
limitação, e `corpus.json` guarda quantos artigos a blocklist descartou.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import yaml

from ..config import DATA_DIR
from ..models import Document

CORPUS_PATH = DATA_DIR / "corpus.jsonl"
CORPUS_META = DATA_DIR / "corpus.json"
DOCUMENTS_YAML = DATA_DIR / "documents.yaml"

# Sorteio dos distratores. Fixo para que duas rodadas comparem o mesmo corpus —
# número que muda entre execuções não é medição, é impressão.
SEED = 17

# Artigo que toque nestes assuntos vira distrator ambíguo: ele PODE responder a
# uma consulta conceitual melhor que o alvo, e aí a métrica passa a medir o
# gabarito em vez da estratégia.
BLOCKED_TERMS = (
    "compressor",
    "caldeira",
    "pasteuriz",
    "rolamento",
    "mancal",
    "vibração",
    "manutenção",
    "cadeado",
    "engrenagem",
    "trocador de calor",
    "refrigeração",
    "amônia",
    "envasa",
    "esteira transportadora",
    "lubrific",
    "célula de carga",
    "inversor de frequência",
)

MIN_CHARS = 400
MAX_CHARS = 900
POOL_SIZE = 900  # quantos artigos ler do stream antes de sortear


def load_targets() -> list[Document]:
    raw = yaml.safe_load(DOCUMENTS_YAML.read_text(encoding="utf-8"))
    return [
        Document(
            doc_id=item["id"],
            title=item["title"],
            kind=item["kind"],
            source="handwritten",
            text=item["body"].strip(),
        )
        for item in raw["documents"]
    ]


def _trim(text: str) -> str:
    """Corta no fim de frase, não no meio da palavra."""
    text = " ".join(text.split())
    if len(text) <= MAX_CHARS:
        return text
    cut = text[:MAX_CHARS]
    dot = cut.rfind(". ")
    return cut[: dot + 1] if dot > MIN_CHARS else cut


def fetch_distractors(target_count: int) -> tuple[list[Document], int]:
    """Devolve (distratores, quantos a blocklist descartou)."""
    try:
        from datasets import load_dataset
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "pacote `datasets` ausente — rode `task setup` antes de `task corpus`"
        ) from exc

    stream = load_dataset(
        "wikimedia/wikipedia", "20231101.pt", split="train", streaming=True
    )

    pool: list[tuple[str, str]] = []
    blocked = 0
    for row in stream:
        if len(pool) >= POOL_SIZE:
            break
        text = _trim(row.get("text", ""))
        if len(text) < MIN_CHARS:
            continue
        haystack = (row.get("title", "") + " " + text).lower()
        if any(term in haystack for term in BLOCKED_TERMS):
            blocked += 1
            continue
        pool.append((row["title"], text))

    rng = random.Random(SEED)
    chosen = rng.sample(pool, min(target_count, len(pool)))
    docs = [
        Document(
            doc_id=f"wiki_{i:03d}",
            title=title,
            kind="prose",
            source="wikipedia",
            text=text,
        )
        for i, (title, text) in enumerate(chosen)
    ]
    return docs, blocked


def build(distractors: int = 80) -> list[Document]:
    targets = load_targets()
    noise, blocked = fetch_distractors(distractors)
    docs = targets + noise

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with CORPUS_PATH.open("w", encoding="utf-8") as handle:
        for doc in docs:
            handle.write(json.dumps(doc.as_row(), ensure_ascii=False) + "\n")

    chars = [len(doc.text) for doc in docs]
    meta = {
        "total": len(docs),
        "targets": len(targets),
        "distractors": len(noise),
        "blocked_by_topic_filter": blocked,
        "seed": SEED,
        "chars_min": min(chars),
        "chars_max": max(chars),
        "chars_avg": round(sum(chars) / len(chars), 1),
        "by_kind": {
            kind: sum(1 for d in docs if d.kind == kind) for kind in ("record", "prose")
        },
    }
    CORPUS_META.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return docs


def load() -> list[Document]:
    """Lê o corpus já montado. Falha alto se ninguém rodou `task corpus`."""
    if not CORPUS_PATH.exists():
        raise SystemExit(f"corpus ausente em {CORPUS_PATH} — rode `task corpus`")
    docs = []
    with CORPUS_PATH.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            docs.append(
                Document(
                    doc_id=row["doc_id"],
                    title=row["title"],
                    kind=row["kind"],
                    source=row["source"],
                    text=row["text"],
                )
            )
    return docs
