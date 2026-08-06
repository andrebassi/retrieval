"""Embedding de texto pelo Ollama local — nada sai da máquina."""

from __future__ import annotations

import httpx

from ..config import SETTINGS

# Dimensão MEDIDA de cada modelo, nunca presumida. A anotação errada de um
# modelo de mesma dimensão aparente é o tipo de erro que não levanta exceção:
# a busca funciona, devolve linhas, e o score não quer dizer nada.
KNOWN_DIMS = {
    "bge-m3": 1024,
    "all-minilm": 384,
    "paraphrase-multilingual": 768,
    "nomic-embed-text": 768,
    "snowflake-arctic-embed:33m": 384,
}


class OllamaEmbedder:
    """POST /api/embed. Lote de verdade — o Ollama aceita lista em `input`."""

    def __init__(self, model: str | None = None) -> None:
        self.name = model or SETTINGS.dense_model
        self._client = httpx.Client(base_url=SETTINGS.ollama_url, timeout=180.0)
        self.dim = self._measure_dim()

    def _measure_dim(self) -> int:
        vector = self.embed("dimensão")
        declared = KNOWN_DIMS.get(self.name)
        if declared is not None and declared != len(vector):
            raise SystemExit(
                f"{self.name}: KNOWN_DIMS diz {declared}, o servidor devolveu {len(vector)}"
            )
        return len(vector)

    def embed(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        response = self._client.post(
            "/api/embed", json={"model": self.name, "input": texts}
        )
        response.raise_for_status()
        return response.json()["embeddings"]
