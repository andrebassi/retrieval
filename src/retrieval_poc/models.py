"""Tipos de domínio da PoC. Sem dependência de infraestrutura."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Document:
    """Um trecho indexável do corpus.

    `kind` separa as duas metades do corpus e é o que permite ler o resultado
    por origem: prosa enciclopédica em pt-BR contra documento operacional cheio
    de identificador literal (OS, NF, CNPJ, código de peça).
    """

    doc_id: str
    text: str
    kind: str  # "prose" | "record"
    title: str
    source: str

    def as_row(self) -> dict[str, str]:
        return {
            "doc_id": self.doc_id,
            "title": self.title,
            "kind": self.kind,
            "source": self.source,
            "text": self.text,
        }


@dataclass(frozen=True)
class Query:
    """Pergunta em pt-BR com o gabarito de quais documentos contam como acerto.

    `family` é o eixo do estudo, não um rótulo cosmético:
      - `literal`    — cita um identificador que existe no texto;
      - `conceptual` — descreve o assunto sem usar o vocabulário do documento;
      - `hybrid`     — as duas coisas na mesma frase, que é o caso real.
    """

    query_id: str
    text: str
    family: str
    relevant: tuple[str, ...]
    note: str = ""


@dataclass
class Hit:
    """Resultado de busca já normalizado: rank começa em 1."""

    doc_id: str
    score: float
    rank: int


@dataclass
class StrategyReport:
    """Métricas de uma estratégia sobre o conjunto inteiro de consultas."""

    strategy: str
    description: str
    hit_at_1: float
    hit_at_3: float
    hit_at_10: float
    mrr: float
    query_ms_p50: float
    query_ms_p95: float
    # Quantas consultas voltaram com MENOS de top_k resultados. Num motor
    # léxico isso não é detalhe: é o modo de falha característico dele.
    starved_queries: int = 0
    returned_avg: float = 0.0
    by_family: dict[str, dict[str, float]] = field(default_factory=dict)
