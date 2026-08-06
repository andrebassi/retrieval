"""Configuração da PoC — variável de ambiente com padrão explícito."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
RESULTS_DIR = ROOT / "results"


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql://postgres@127.0.0.1:5434/retrieval"
    )
    ollama_url: str = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")

    # bge-m3: multilíngue de verdade (o corpus e as consultas são em pt-BR) e
    # 1024 dimensões. É o mesmo encoder do image-embedding-poc, o que permite
    # comparar as duas PoCs sem trocar de espaço vetorial.
    dense_model: str = os.getenv("DENSE_MODEL", "bge-m3")

    # Reranker cross-encoder multilíngue treinado no mMARCO (a tradução do
    # MS MARCO para 14 idiomas, português entre eles). Pontua o par
    # (consulta, documento) de uma vez — não existe vetor de documento aqui.
    reranker_model: str = os.getenv(
        "RERANKER_MODEL", "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
    )

    # Configuração de idioma do índice léxico. O stemmer decide o que é "mesmo
    # termo": com `portuguese`, "compressores" e "compressor" colidem; com
    # `simple`, não. Trocar isto muda todo número léxico da PoC.
    text_search_config: str = os.getenv("TEXT_SEARCH_CONFIG", "portuguese")

    # BM25: os valores canônicos do artigo original (Robertson & Zaragoza).
    # k1 satura o ganho de repetir o termo; b pesa o comprimento do documento.
    bm25_k1: float = float(os.getenv("BM25_K1", "1.2"))
    bm25_b: float = float(os.getenv("BM25_B", "0.75"))

    # Quantos candidatos cada braço traz antes da fusão. Igual para os dois:
    # dar mais a um lado é escolher o vencedor antes de medir.
    prefetch_limit: int = int(os.getenv("PREFETCH_LIMIT", "20"))
    top_k: int = int(os.getenv("TOP_K", "10"))

    # k do RRF. 60 é o valor do artigo de Cormack (2009) e o padrão de fato do
    # Elasticsearch e do Qdrant; o experimento E1 mede o que ele muda.
    rrf_k: int = int(os.getenv("RRF_K", "60"))


SETTINGS = Settings()
