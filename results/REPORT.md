# Resultados medidos

> Gerado por `task report` a partir de `results/*.json`. Não editar à mão — a próxima rodada sobrescreve.

## O que foi medido

| Item | Valor |
|---|---|
| Documentos indexados | 114 |
| — operacionais (`record`) | 26 |
| — prosa (`prose`) | 88 |
| Consultas | 37 |
| — literais | 11 |
| — conceituais | 15 |
| — híbridas | 11 |
| Modelo denso | `bge-m3` |
| Reranker | `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` |
| Configuração textual do Postgres | `portuguese` |
| BM25 | k1=1.2, b=0.75 |
| RRF | k=60 |
| top_k / prefetch | 10 / 20 |
| Termos distintos no índice léxico | 3437 |
| Postings (par termo–documento) | 7047 |
| Termos que ocorrem em UM só documento | 2229 (64.9% do vocabulário) |
| Tamanho de documento em lexemas | min 50, média 77.85, máx 129 |

## Placar geral

| Estratégia | hit@1 | hit@3 | hit@10 | MRR@10 | p50 | p95 | consultas famintas |
|---|---:|---:|---:|---:|---:|---:|---:|
| denso (bge-m3) | 81.1% | 91.9% | 100.0% | 0.877 | 112.7 ms | 126.2 ms | 0 |
| ts_rank_cd | 75.7% | 81.1% | 94.6% | 0.804 | 0.5 ms | 0.8 ms | 16 |
| BM25 | 78.4% | 83.8% | 94.6% | 0.834 | 1.0 ms | 1.7 ms | 15 |
| fusão min-max | 86.5% | 97.3% | 100.0% | 0.917 | 115.2 ms | 125.2 ms | 0 |
| RRF | 81.1% | 91.9% | 100.0% | 0.881 | 114.5 ms | 127.7 ms | 0 |
| RRF + cross-encoder | 91.9% | 94.6% | 97.3% | 0.932 | 383.2 ms | 424.6 ms | 0 |

*Consultas famintas* = voltaram com menos de 10 resultados. É cobertura, não qualidade — e é o número que separa "errou devolvendo pouco" de "errou devolvendo qualquer coisa".

## Por família de consulta

A média esconde o resultado. Aqui está o que ela esconde.

### Literais — o identificador está no texto

| Estratégia | hit@1 | hit@3 | MRR@10 |
|---|---:|---:|---:|
| denso (bge-m3) | 54.5% | 81.8% | 0.700 |
| ts_rank_cd | 100.0% | 100.0% | 1.000 |
| BM25 | 100.0% | 100.0% | 1.000 |
| fusão min-max | 100.0% | 100.0% | 1.000 |
| RRF | 81.8% | 100.0% | 0.909 |
| RRF + cross-encoder | 100.0% | 100.0% | 1.000 |

### Conceituais — outro vocabulário, mesmo assunto

| Estratégia | hit@1 | hit@3 | MRR@10 |
|---|---:|---:|---:|
| denso (bge-m3) | 93.3% | 93.3% | 0.950 |
| ts_rank_cd | 40.0% | 53.3% | 0.517 |
| BM25 | 46.7% | 60.0% | 0.590 |
| fusão min-max | 66.7% | 93.3% | 0.794 |
| RRF | 66.7% | 80.0% | 0.772 |
| RRF + cross-encoder | 80.0% | 86.7% | 0.833 |

### Híbridas — identificador + descrição na mesma frase

| Estratégia | hit@1 | hit@3 | MRR@10 |
|---|---:|---:|---:|
| denso (bge-m3) | 90.9% | 100.0% | 0.955 |
| ts_rank_cd | 100.0% | 100.0% | 1.000 |
| BM25 | 100.0% | 100.0% | 1.000 |
| fusão min-max | 100.0% | 100.0% | 1.000 |
| RRF | 100.0% | 100.0% | 1.000 |
| RRF + cross-encoder | 100.0% | 100.0% | 1.000 |

## Experimentos

### E1 — escala não compara: min-max somado × RRF

| Medida | Valor |
|---|---|
| Faixa de score BM25 | 1.5382 a 28.0471 |
| Faixa de score do denso (cosseno) | 0.2857 a 0.7801 |
| Candidatos presentes em só uma das listas | 771 de 971 (79.4%) |
| hit@1 com RRF | 81.1% |
| hit@1 com fusão min-max | 86.5% |
| Consultas ordenadas de forma diferente | 6 |

Cada candidato que aparece em uma lista só entra na fusão min-max com score 0 na outra — uma afirmação de irrelevância sobre algo que o motor apenas não devolveu.

### E2 — ts_rank_cd (sem IDF) × BM25 sobre o mesmo tsvector

| Medida | Valor |
|---|---|
| Consultas | 37 |
| Conjunto de resultados idêntico | 17 |
| Mesmo primeiro colocado | 29 |
| BM25 colocou o relevante mais acima | 4 |
| `ts_rank_cd` colocou mais acima | 1 |
| Empates | 32 |

Os dois leem o mesmo `tsvector` e recuperam o mesmo conjunto por construção. Toda diferença acima é da fórmula: `ts_rank_cd` pontua densidade de cobertura e **não tem IDF** — termo raro e termo banal valem o mesmo.

### E3 — quanto custa cada ponto de hit@1 do cross-encoder

| Medida | Antes | Depois |
|---|---:|---:|
| hit@1 | 81.1% | 91.9% |
| MRR@10 | 0.881 | 0.932 |
| p50 | 151.0 ms | 371.9 ms |
| p95 | — | 417.1 ms |

| Medida | Valor |
|---|---|
| Custo médio acrescentado | 232.3 ms por consulta |
| Consultas em que o reranker TINHA como ajudar | 7 |
| Consultas em que promoveu o relevante | 5 |
| Consultas em que rebaixou o relevante | 2 |
| Custo por ponto percentual de hit@1 | 21.5 ms |

Teto do reranker: ele só reordena os 20 candidatos que a fusão entregou. Documento fora do prefetch é invisível para ele — reranker não recupera nada.

### E4 — o vazio: silêncio do léxico × palpite do denso

| Medida | BM25 | Denso |
|---|---:|---:|
| Resultados devolvidos, média | 7.65 | 10.0 |
| Consultas com menos de 10 | 15 | 0 |
| Consultas com ZERO resultado | 0 | 0 |

| Modo do léxico | Média devolvida | Consultas vazias |
|---|---:|---:|
| OR entre os termos (o desta PoC) | 7.65 | 0 |
| AND — o `plainto_tsquery` padrão | 0.49 | 22 |

Média devolvida por família de consulta (BM25):

| Família | Média |
|---|---:|
| literal | 4.27 |
| conceptual | 9.6 |
| hybrid | 8.36 |

