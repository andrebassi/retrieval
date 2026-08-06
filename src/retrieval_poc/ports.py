"""Portas — contratos que os adapters implementam.

O ponto da PoC é trocar o mecanismo de recuperação sem mexer no avaliador: quem
mede recall não sabe se a lista veio de um índice invertido, de um grafo HNSW ou
da fusão dos dois.

`Retriever` e `Reranker` são propositalmente contratos DIFERENTES, e a diferença
é a tese do projeto: um recuperador varre o corpus inteiro e precisa ser barato;
um reranqueador olha uma lista curta e pode ser caro. Confundir os dois é o erro
que faz gente colocar cross-encoder na frente de um milhão de documentos.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import Document, Hit


@runtime_checkable
class TextEmbedder(Protocol):
    """Texto -> vetor denso."""

    dim: int
    name: str

    def embed(self, text: str) -> list[float]: ...

    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


@runtime_checkable
class Retriever(Protocol):
    """Consulta -> candidatos, varrendo o corpus inteiro.

    Custo por consulta é sublinear no tamanho do corpus (índice invertido ou
    grafo de vizinhos). É o que pode rodar em cima de tudo.
    """

    name: str
    description: str

    def reset(self) -> None: ...

    def index(self, docs: list[Document]) -> float:
        """Indexa o corpus e devolve o tempo total em ms."""
        ...

    def search(self, text: str, k: int) -> list[Hit]: ...


@runtime_checkable
class Reranker(Protocol):
    """(consulta, documentos) -> mesma lista reordenada.

    Custo por consulta é linear no número de candidatos, e cada candidato custa
    uma inferência. Só faz sentido sobre lista curta.
    """

    name: str
    description: str

    def rerank(self, text: str, hits: list[Hit], k: int) -> list[Hit]: ...
