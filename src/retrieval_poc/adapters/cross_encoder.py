"""Reranker cross-encoder — o único componente que lê consulta e documento juntos.

Bi-encoder (o denso da PoC) codifica os dois lados **separadamente** e compara
dois vetores prontos; por isso dá para indexar o corpus inteiro de antemão. O
cross-encoder concatena consulta e documento numa entrada só e roda o modelo:
cada par custa uma inferência, nada é pré-computável, e em compensação ele
enxerga interação entre as palavras dos dois lados.

É por isso que ele só aparece depois da fusão, sobre uma lista curta.
"""

from __future__ import annotations

from ..config import SETTINGS
from ..models import Hit


class CrossEncoderReranker:
    name = "cross_encoder"

    def __init__(self, texts_provider, model: str | None = None) -> None:
        from sentence_transformers import CrossEncoder  # import tardio: carrega torch

        self.model_name = model or SETTINGS.reranker_model
        self.description = f"cross-encoder {self.model_name} sobre os candidatos da fusão"
        self._model = CrossEncoder(self.model_name, max_length=512)
        # Função que devolve {doc_id: texto}. O reranker precisa do TEXTO — se
        # dependesse de vetor, seria um bi-encoder com outro nome.
        self._texts = texts_provider

    def rerank(self, text: str, hits: list[Hit], k: int) -> list[Hit]:
        if not hits:
            return []
        texts = self._texts([hit.doc_id for hit in hits])
        pairs = [(text, texts.get(hit.doc_id, "")) for hit in hits]
        scores = self._model.predict(pairs)
        ordered = sorted(
            zip(hits, scores), key=lambda pair: float(pair[1]), reverse=True
        )
        return [
            Hit(doc_id=hit.doc_id, score=float(score), rank=i + 1)
            for i, (hit, score) in enumerate(ordered[:k])
        ]
