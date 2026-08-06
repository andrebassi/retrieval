"""As duas formas de juntar duas listas — e por que uma delas dá errado.

O problema: o léxico devolve score BM25 (sem teto, cresce com a raridade do
termo) e o denso devolve cosseno (limitado a [-1, 1], e concentrado num naco
estreito na prática). Somar os dois direto é somar metro com quilo.

`reciprocal_rank_fusion` joga fora o score e usa só a POSIÇÃO. É feio, é
grosseiro, e é justamente por isso que funciona: posição é a única grandeza que
os dois motores produzem na mesma unidade.

`weighted_fusion` faz o que parece mais natural — normaliza cada lista para
[0, 1] e soma. O experimento E1 mostra o que acontece.
"""

from __future__ import annotations

from ..models import Hit


def reciprocal_rank_fusion(lists: list[list[Hit]], k_rrf: int, limit: int) -> list[Hit]:
    """score(d) = Σ 1 / (k + posição de d na lista i)

    Documento que aparece razoavelmente bem nas duas listas ganha de documento
    que aparece em primeiro numa e some da outra — é a propriedade que faz a
    fusão corrigir os dois modos de falha ao mesmo tempo.
    """
    scores: dict[str, float] = {}
    for hits in lists:
        for hit in hits:
            scores[hit.doc_id] = scores.get(hit.doc_id, 0.0) + 1.0 / (k_rrf + hit.rank)
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return [Hit(doc_id=d, score=s, rank=i + 1) for i, (d, s) in enumerate(ordered[:limit])]


def weighted_fusion(
    lists: list[list[Hit]], weights: list[float], limit: int
) -> list[Hit]:
    """Normaliza cada lista para [0, 1] pelo min-max e soma com peso.

    O defeito não é a soma: é o normalizador. `min` e `max` saem dos resultados
    DAQUELA consulta, então a mesma pontuação bruta vira número diferente
    dependendo de quem mais voltou junto. Documento ausente de uma das listas
    entra como 0, o que é uma afirmação forte ("irrelevante") sobre algo que o
    motor apenas não devolveu.
    """
    scores: dict[str, float] = {}
    for hits, weight in zip(lists, weights):
        if not hits:
            continue
        values = [hit.score for hit in hits]
        low, high = min(values), max(values)
        span = high - low
        for hit in hits:
            # Lista de um elemento só, ou empate geral: span 0. Vira 1.0 — e é
            # exatamente aí que o método começa a mentir.
            normalized = 1.0 if span == 0 else (hit.score - low) / span
            scores[hit.doc_id] = scores.get(hit.doc_id, 0.0) + weight * normalized
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return [Hit(doc_id=d, score=s, rank=i + 1) for i, (d, s) in enumerate(ordered[:limit])]
