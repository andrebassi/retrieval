# retrieval

Um mapa das **estratégias de recuperação** — léxica, densa, fusão e reranking —
medidas sobre **o mesmo corpus, o mesmo gabarito e a mesma máquina**, com uma
regra: o que dá para medir aqui está medido, e o que não dá está marcado como
não medido.

Recuperar é responder a uma pergunta que parece simples: *dada uma consulta,
quais documentos entram na lista, e em que ordem?* Todo sistema de busca, todo
RAG e todo agente com memória param nessa pergunta. A parte difícil não é achar
um motor que funcione — é que **cada motor erra num lugar diferente**, e a
diferença nunca aparece em log de erro: aparece como "a busca anda ruim".

Este repositório existe para mostrar essas diferenças com número no lugar de
opinião. Seis estratégias, 37 consultas em português, 114 documentos, quatro
experimentos que isolam um efeito cada.

| | |
|---|---|
| **Corpus** | 34 documentos operacionais escritos à mão + 80 distratores da Wikipédia em pt |
| **Gabarito** | 37 consultas em 3 famílias (literal, conceitual, híbrida) |
| **Modelo denso** | `bge-m3`, 1024 dimensões, servido pelo Ollama local |
| **Reranker** | `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` |
| **Banco** | PostgreSQL 17.10 + pgvector 0.8.6, subido por **Nix** na porta 5434 |
| **Licença** | não declarada |

Tudo roda **na máquina**: o encoder, o reranker e o Postgres. Nenhuma consulta
sai daqui — não há chave de API em lugar nenhum do repositório.

---

## Sumário

1. [O mapa das estratégias](#o-mapa-das-estratégias)
2. [O fundamento, em cinco minutos](#o-fundamento-em-cinco-minutos)
3. [O corpus e o gabarito](#o-corpus-e-o-gabarito)
4. [O placar](#o-placar--medido)
5. [Por família — onde a média mente](#por-família--onde-a-média-mente)
6. [Os quatro experimentos](#os-quatro-experimentos)
7. [Onde cada estratégia errou, nominalmente](#onde-cada-estratégia-errou-nominalmente)
8. [Como escolher](#como-escolher)
9. [Como rodar](#como-rodar)
10. [A tela](#a-tela)
11. [Arquitetura](#arquitetura)
12. [O que NÃO está implementado](#o-que-não-está-implementado)
13. [Limitações — o que estes números NÃO provam](#limitações--o-que-estes-números-não-provam)
14. [Conclusão prática](#conclusão-prática)

---

## O mapa das estratégias

Toda estratégia de recuperação responde à mesma pergunta — *o que este documento
tem a ver com esta consulta?* — e as respostas se organizam em duas famílias,
mais o que se faz com elas.

```
                        consulta
                            │
            ┌───────────────┴───────────────┐
            │                               │
     casa SÍMBOLO                      casa SENTIDO
     (índice invertido)                (vizinhança vetorial)
            │                               │
    ts_rank_cd   BM25                  bge-m3 + HNSW
            │                               │
            └───────────────┬───────────────┘
                            │
                    FUSÃO das duas listas
                    ├── min-max ponderada   (soma score normalizado)
                    └── RRF                 (soma 1/(k+posição))
                            │
                    RERANKING da lista curta
                    └── cross-encoder       (uma inferência por par)
```

| Estratégia | O que faz | Custo por consulta (p50 medido) |
|---|---|---|
| `ts_rank_cd` | ranking nativo do Postgres, cobertura sem IDF | **0,5 ms** |
| `bm25` | BM25 canônico calculado sobre o mesmo `tsvector` | **1,0 ms** |
| `dense` | cosseno sobre HNSW, `bge-m3` de 1024 dimensões | **112,7 ms** |
| `weighted` | min-max normalizado e somado | **115,2 ms** |
| `rrf` | Reciprocal Rank Fusion, k=60 | **114,5 ms** |
| `rrf_rerank` | RRF com prefetch 20, reordenado por cross-encoder | **383,2 ms** |

A escala aqui já conta metade da história: **o léxico é 112× mais barato que o
denso** (1,0 ms contra 112,7 ms), e o reranker sozinho custa mais que tudo o que
veio antes dele somado.

---

## O fundamento, em cinco minutos

### Buscar é ordenar, não filtrar

`WHERE texto LIKE '%bomba%'` responde *sim ou não*. Recuperação responde *quão
perto*, e devolve uma lista ordenada. A diferença importa porque a decisão que
vem depois — mostrar ao usuário, ou enfiar no contexto de um LLM — só olha os
primeiros k. Documento certo em 40º lugar é indistinguível de documento ausente.

Daí as métricas serem todas sobre posição:

- **hit@k** — o documento certo entrou nos k primeiros? Binário por consulta.
- **MRR@10** — 1/posição do primeiro acerto. Separa "acertou em 1º" de "acertou
  em 9º", coisa que hit@10 trata igual.
- **consultas famintas** — quantas voltaram com **menos** de k resultados. Não é
  qualidade, é cobertura, e é o número que separa os dois modos de falha.

### O léxico casa símbolo

O Postgres guarda cada documento como um `tsvector`: lista de lexemas com
posição. `OS-4471` é um lexema; a consulta `OS-4471` é o mesmo lexema; casou.

BM25 pontua esse casamento:

```
score(D,Q) = Σ  IDF(q) · ─────────tf · (k1 + 1)─────────
             q∈Q          tf + k1 · (1 − b + b · dl/avgdl)
```

Três ideias, e cada uma resolve um problema concreto:

- **IDF** — termo raro vale mais. `OS-4471` aparece em 1 documento; `bomba`
  aparece em dezenas. Neste corpus, **2 229 dos 3 437 termos (64,9%) ocorrem em
  um só documento** — é essa cauda que o IDF explora.
- **saturação por `k1`** (1,2) — a décima ocorrência do termo acrescenta bem
  menos que a segunda.
- **normalização por `b`** (0,75) — documento longo não ganha só por ser longo.

O `ts_rank_cd` nativo do Postgres pontua a mesma coisa **sem IDF**: mede
densidade de cobertura dos termos no texto. O experimento **E2** mede o que essa
ausência custa.

### O denso casa sentido

O `bge-m3` transforma o texto em 1024 números. Textos que falam da mesma coisa
caem perto no espaço, mesmo sem compartilhar uma palavra. `<=>` do pgvector
devolve a distância cosseno; HNSW acha os vizinhos sem varrer tudo.

O preço: o vetor **não guarda o símbolo**. `CNPJ 41.552.907/0001-33` e
`CNPJ 41.552.907/0001-44` são o mesmo ponto, para todos os efeitos práticos.

### Os dois erram de jeitos opostos — e é isso que a fusão explora

| | quando não sabe | consultas famintas medidas |
|---|---|---|
| **léxico** | devolve **pouco ou nada** — silêncio | **15 de 37** |
| **denso** | devolve **sempre k** — palpite | **0 de 37** |

O canário do projeto (`task verify`) prova as duas coisas na mesma consulta sem
sentido:

```
✅ BM25 de termo inexistente devolve lista vazia
✅ denso devolve 10 resultados para a MESMA consulta sem sentido
   (melhor score: 0.3960) — é o palpite, não erro de código
```

Sem a coluna de consultas famintas, as duas falhas aparecem como o mesmo hit@1
ruim, e a conclusão sai invertida.

### Fundir é escolher a unidade comum

BM25 devolve score sem teto (**1,54 a 28,05** neste corpus); cosseno devolve
número estreito (**0,286 a 0,780**). Somar os dois é somar metro com quilo.

- **min-max ponderada** normaliza cada lista para [0,1] e soma. O defeito não é
  a soma, é o normalizador: `min` e `max` saem **daquela consulta**, e documento
  ausente de uma lista entra como **0** — uma afirmação forte ("irrelevante")
  sobre algo que o motor apenas não devolveu.
- **RRF** joga o score fora e usa só a posição: `Σ 1/(60 + rank)`. É grosseiro, e
  é por isso que funciona — posição é a única grandeza que os dois motores
  produzem na mesma unidade.

O experimento **E1** mede a diferença.

---

## O corpus e o gabarito

O gabarito é o ativo mais frágil de qualquer avaliação de retrieval, então ele
foi construído ao contrário do usual: **primeiro as perguntas, depois os
documentos que as respondem**.

| Item | Valor medido |
|---|---|
| Documentos | **114** (34 alvos + 80 distratores) |
| — operacionais (`record`) | 26 |
| — prosa (`prose`) | 88 |
| Tamanho em caracteres | min 444 / média **729,4** / máx 900 |
| Tamanho em lexemas | min 50 / média **77,85** / máx 129 |
| Termos distintos no índice | **3 437** |
| Postings (par termo–documento) | **7 047** |
| Artigos descartados pelo filtro temático | **6** |

Os 34 alvos são ordens de serviço, notas fiscais, pedidos de compra, contratos,
fichas técnicas, chamados e procedimentos de uma fábrica de bebidas — escritos à
mão, com identificadores reais no texto (`OS-4471`, `CMP-8830-B`,
`CNPJ 41.552.907/0001-33`). Os 80 distratores vêm da Wikipédia em português, com
`SEED = 17` e uma **blocklist de 17 termos do domínio** que descartou 6 artigos —
para que nenhum distrator responda por acidente a uma consulta do gabarito.

As 37 consultas se dividem em três famílias, e a divisão é o ponto:

| Família | n | O que testa |
|---|---:|---|
| `literal` | 11 | o identificador está no texto, letra por letra |
| `conceptual` | 15 | a consulta descreve a situação com **outro** vocabulário |
| `hybrid` | 11 | identificador **+** descrição na mesma frase — o caso real |

`relevant` lista **todos** os documentos que respondem, não só o principal:
gabarito artificialmente estreito infla a diferença entre estratégias.

---

## O placar ✅ medido

37 consultas, top_k=10, prefetch=20. Mesma máquina, banco quente.

> **O que se repete e o que não.** O pipeline foi rodado do zero duas vezes
> (`task clean` → `task all`). Com `SEED = 17` o corpus é reconstruído idêntico
> e **todas as colunas de qualidade — hit@k, MRR, famintas — saíram exatamente
> iguais nas duas rodadas**. As colunas de latência oscilaram na casa de 6%
> (p50 do denso 113,6 → 112,7 ms; do reranker 362,6 → 383,2 ms). Trate número de
> qualidade como reprodutível e número de tempo como ordem de grandeza.

| Estratégia | hit@1 | hit@3 | hit@10 | MRR@10 | p50 | p95 | famintas |
|---|---:|---:|---:|---:|---:|---:|---:|
| denso (`bge-m3`) | 81,1% | 91,9% | **100,0%** | 0,877 | 112,7 ms | 126,2 ms | 0 |
| `ts_rank_cd` | 75,7% | 81,1% | 94,6% | 0,804 | **0,5 ms** | 0,8 ms | 16 |
| BM25 | 78,4% | 83,8% | 94,6% | 0,834 | 1,0 ms | 1,7 ms | 15 |
| fusão min-max | 86,5% | **97,3%** | **100,0%** | 0,917 | 115,2 ms | 125,2 ms | 0 |
| RRF | 81,1% | 91,9% | **100,0%** | 0,881 | 114,5 ms | 127,7 ms | 0 |
| RRF + cross-encoder | **91,9%** | 94,6% | 97,3% | **0,932** | 383,2 ms | 424,6 ms | 0 |

Três leituras que a tabela sozinha não entrega:

**1. Nenhum motor puro passa de 81,1% de hit@1.** O denso e o BM25 empatam por
cima de erros completamente diferentes — e é exatamente por isso que fundir
funciona.

**2. O reranker ganha no topo e perde na cauda.** hit@1 sobe de 81,1% para
91,9%, mas hit@10 **cai** de 100% para 97,3%. Ele reordena; ao reordenar, pode
empurrar para fora do top-10 um documento que a fusão já tinha entregue. Foi o
que aconteceu com `q_con_11` (ver [os casos nominais](#onde-cada-estratégia-errou-nominalmente)).

**3. `ts_rank_cd` e BM25 quase empatam — e isso é sobre o corpus, não sobre as
fórmulas.** Com documentos de ~78 lexemas e vocabulário de cauda longa, a
diferença que o IDF faz é pequena. Em corpus com documentos de tamanhos muito
desiguais ela cresce. O E2 quantifica.

---

## Por família — onde a média mente

Uma tabela com uma linha por estratégia diz quem ganhou. A mesma tabela quebrada
por família diz **por quê** — e é sempre a mesma história.

### Literais — o identificador está no texto

| Estratégia | hit@1 | hit@3 | MRR@10 |
|---|---:|---:|---:|
| denso | **54,5%** | 81,8% | 0,700 |
| `ts_rank_cd` | 100,0% | 100,0% | 1,000 |
| BM25 | 100,0% | 100,0% | 1,000 |
| fusão min-max | 100,0% | 100,0% | 1,000 |
| RRF | 81,8% | 100,0% | 0,909 |
| RRF + cross-encoder | 100,0% | 100,0% | 1,000 |

O denso acerta **pouco mais da metade**. Um índice invertido de 1,0 ms resolve
100%. Este é o argumento inteiro contra "vetorizar tudo e pronto".

Repare também que o **RRF pura cai para 81,8% aqui**: quando o léxico acerta
sozinho e o denso erra, misturar a opinião do denso *piora*. A fusão não é de
graça.

### Conceituais — outro vocabulário, mesmo assunto

| Estratégia | hit@1 | hit@3 | MRR@10 |
|---|---:|---:|---:|
| denso | **93,3%** | 93,3% | 0,950 |
| `ts_rank_cd` | 40,0% | 53,3% | 0,517 |
| BM25 | 46,7% | 60,0% | 0,590 |
| fusão min-max | 66,7% | 93,3% | 0,794 |
| RRF | 66,7% | 80,0% | 0,772 |
| RRF + cross-encoder | 80,0% | 86,7% | 0,833 |

Espelho exato da tabela anterior. O léxico fica em torno de 40–47% porque a
consulta não compartilha palavra com o alvo: *"como perceber que um mancal vai
falhar antes de ele quebrar"* contra um documento que só diz **rolamento**.

E aqui aparece o efeito mais incômodo da PoC: **a fusão é pior que o denso puro
nesta família** (66,7% contra 93,3%). Misturar um motor ruim com um bom não dá a
média — dá algo pior que o bom, porque o ruído do léxico desloca o acerto.

### Híbridas — identificador + descrição na mesma frase

| Estratégia | hit@1 | hit@3 | MRR@10 |
|---|---:|---:|---:|
| denso | 90,9% | 100,0% | 0,955 |
| `ts_rank_cd` | 100,0% | 100,0% | 1,000 |
| BM25 | 100,0% | 100,0% | 1,000 |
| fusão min-max | 100,0% | 100,0% | 1,000 |
| RRF | 100,0% | 100,0% | 1,000 |
| RRF + cross-encoder | 100,0% | 100,0% | 1,000 |

Todo mundo acerta, e por um motivo específico deste corpus: **o identificador
sozinho já desambigua**. `TR-17 derrubando embalagem no trecho curvo` é resolvida
pelo `TR-17`; a descrição é enfeite. Num corpus onde o mesmo identificador
aparece em 200 documentos, essa família viraria a mais difícil, não a mais fácil.
É a limitação mais séria do gabarito, e está registrada como tal.

---

## Os quatro experimentos

Cada experimento isola **um** efeito. Nenhum deles reaproveita conclusão do
outro.

### E1 — escala não compara: min-max somado × RRF ✅ medido

| Medida | Valor |
|---|---|
| Faixa de score BM25 | **1,5382 a 28,0471** |
| Faixa de score do denso (cosseno) | **0,2857 a 0,7801** |
| Candidatos presentes em **só uma** das listas | **771 de 971 (79,4%)** |
| hit@1 com RRF | 81,1% |
| hit@1 com fusão min-max | **86,5%** |
| Consultas ordenadas de forma diferente | 6 |

O resultado é **contra-intuitivo e vale registrar**: a fusão min-max, que é a
teoricamente defeituosa, ganhou do RRF neste corpus.

O motivo está na linha dos 79,4%. Quase quatro em cada cinco candidatos aparecem
em uma lista só, e entram na soma com **0** na outra. Isso é um viés — mas um
viés que, aqui, aponta na direção certa: penaliza quem só um motor viu, o que
com 114 documentos e gabarito curto costuma ser ruído. Em corpus grande, onde
"aparecer numa lista só" é a norma e não a exceção, o mesmo viés vira o defeito
que o RRF existe para evitar.

**Conclusão honesta**: a vantagem de 5,4 pontos da min-max é uma propriedade
deste corpus, não uma refutação do RRF. O que o E1 prova de fato é que as escalas
são incomparáveis — 28,05 contra 0,78 — e que qualquer soma direta seria
dominada pelo BM25.

### E2 — `ts_rank_cd` (sem IDF) × BM25 sobre o mesmo `tsvector` ✅ medido

| Medida | Valor |
|---|---|
| Consultas | 37 |
| Conjunto de resultados **idêntico** | 17 |
| Mesmo primeiro colocado | 29 |
| BM25 colocou o relevante mais acima | **4** |
| `ts_rank_cd` colocou mais acima | 1 |
| Empates | 32 |

Os dois leem o mesmo `tsvector` e recuperam o mesmo conjunto **por construção**
(OR entre os lexemas). Toda diferença acima vem da fórmula, e só dela.

Saldo: **4 a 1 para o BM25** — consistente com os 2,7 pontos de hit@1 do placar.
O IDF ajuda, mas não é a diferença entre funcionar e não funcionar. Quem já tem
Postgres e não quer implementar BM25 tem em `ts_rank_cd` um piso decente; quem
implementa BM25 ganha na margem, com o mesmo índice GIN e sem custo extra de
consulta (1,0 ms contra 0,5 ms).

### E3 — quanto custa cada ponto de hit@1 do cross-encoder ✅ medido

| Medida | Antes (RRF) | Depois (+ reranker) |
|---|---:|---:|
| hit@1 | 81,1% | **91,9%** |
| MRR@10 | 0,881 | 0,932 |
| p50 | 151,0 ms | **371,9 ms** |
| p95 | — | 417,1 ms |

| Medida | Valor |
|---|---|
| Custo médio acrescentado | **232,3 ms** por consulta |
| Consultas em que o reranker **tinha como** ajudar | 7 |
| Consultas em que **promoveu** o relevante | **5** |
| Consultas em que **rebaixou** o relevante | **2** |
| Custo por ponto percentual de hit@1 | **21,5 ms** |

Duas coisas que a linha do hit@1 esconde:

**O teto é o prefetch.** O reranker só reordena os 20 candidatos que a fusão
entregou. Documento fora do prefetch é invisível — **reranker não recupera
nada**. Das 37 consultas, ele tinha como ajudar em 7; nas outras 30 gastou 232 ms
para confirmar a ordem que já estava lá.

**Ele erra também.** 5 promoções contra 2 rebaixamentos. É saldo positivo, mas
não é monotônico: em duas consultas o cross-encoder afundou o documento certo, e
numa delas afundou para fora do top-10 (por isso o hit@10 cai de 100% para
97,3%).

### E4 — o vazio: silêncio do léxico × palpite do denso ✅ medido

| Medida | BM25 | Denso |
|---|---:|---:|
| Resultados devolvidos, média | **7,65** | **10,0** |
| Consultas com menos de 10 | **15** | 0 |
| Consultas com **zero** resultado | 0 | 0 |

Média devolvida por família (BM25):

| Família | Média devolvida |
|---|---:|
| `literal` | **4,27** |
| `conceptual` | 9,6 |
| `hybrid` | 8,36 |

Nas literais o BM25 devolve **4,27 documentos em média** — e acerta 100%. O
"pouco" não é defeito: é o índice invertido dizendo *só estes contêm o termo*. O
denso devolve 10 em todas, sempre, inclusive para `xilofone quântico bergamota`.

E o modo do operador muda tudo:

| Modo do léxico | Média devolvida | Consultas vazias |
|---|---:|---:|
| **OR** entre os termos (o desta PoC) | 7,65 | **0** |
| **AND** — o `plainto_tsquery` padrão | 0,49 | **22 de 37** |

O padrão do Postgres é AND. Com ele, **59,5% das consultas voltariam vazias** —
e um sistema que devolve nada em 3 de cada 5 perguntas parece "quebrado", não
"preciso". É a armadilha mais barata de cair e a mais fácil de consertar: trocar
`plainto_tsquery` por `to_tsquery` com `|`.

---

## Onde cada estratégia errou, nominalmente

Média não convence; caso convence. Estas são **todas** as consultas em que cada
estratégia não colocou um documento relevante em primeiro lugar. `pos` é a
posição em que o relevante apareceu (`—` = fora do top-10).

### O denso erra o símbolo — 7 erros, 5 deles literais

| Consulta | Família | 1º devolvido | pos |
|---|---|---|---:|
| `CMP-8830-B` | literal | `ft_cb02` | 3 |
| `CNPJ 41.552.907/0001-33` | literal | `nf_128512` | 2 |
| `certificado 33-2291` | literal | `ft_tc03` | 4 |
| `desenho técnico DT-2207` | literal | `os_4478` | **9** |
| `filtro de óleo FO-221` | literal | `os_4473` | 2 |
| `como perceber que um mancal vai falhar…` | conceitual | `proc_rootcause` | 4 |
| `CB-02 sem pressão suficiente no começo do turno` | híbrida | `os_4473` | 2 |

O padrão é nítido: em `CNPJ 41.552.907/0001-33` ele devolve **outra nota
fiscal** em primeiro. Está certo semanticamente — é um documento do mesmo tipo,
com um CNPJ parecido. E é exatamente a resposta errada.

### O BM25 erra o sentido — 8 erros, **todos** conceituais

| Consulta | 1º devolvido | pos |
|---|---|---:|
| `como perceber que um mancal vai falhar…` | `proc_rootcause` | 4 |
| `vale a pena guardar peça que quase nunca é usada` | `wiki_073` | 5 |
| `o que precisa ficar registrado quando uma equipe entrega…` | `proc_spare` | 2 |
| `chegou material diferente do que tinha sido comprado` | `wiki_016` | 7 |
| `produto saiu com menos conteúdo do que diz o rótulo` | `wiki_048` | 4 |
| `ninguém consegue saber quem mexeu porque a senha era…` | `wiki_057` | **—** |
| `as telas do controle pararam mas os equipamentos continuaram…` | `os_4475` | 2 |
| `entrou água no armário de eletricidade depois do temporal` | `ch_5502` | **—** |

Quatro dos oito primeiros colocados são **distratores da Wikipédia**. Sem uma
palavra em comum com o alvo, o BM25 se agarra a qualquer coincidência de
vocabulário genérico — e em duas consultas o relevante nem aparece no top-10.

### O reranker deixa 3 — e uma delas ele piorou

| Consulta | 1º devolvido | pos com RRF | pos com reranker |
|---|---|---:|---:|
| `como perceber que um mancal vai falhar…` | `proc_rootcause` | 4 | 3 |
| `produto saiu com menos conteúdo do que diz o rótulo` | `os_4477` | 4 | 6 |
| `ninguém consegue saber quem mexeu porque a senha era…` | `wiki_051` | **3** | **—** |

A última linha é o caso a guardar. O RRF já tinha entregue o documento certo em
**3º lugar**. O cross-encoder olhou os 20 candidatos, achou um artigo da
Wikipédia mais convincente, e o relevante saiu do top-10. **Reranking não é um
passo de segurança: é uma aposta com saldo positivo e variância real.**

### Reproduzindo à mão

As tabelas acima saem de `results/hits.json`, e dá para regenerá-las:

```bash
task failures   # discordâncias com id e texto da consulta
```

Ele imprime quatro blocos — léxico falhou × denso resolveu (5 casos), denso
falhou × léxico resolveu (2), a fusão piorou o que um motor puro já tinha em 1º
(6), e o reranker rebaixou o que a fusão entregou (2).

E para ver uma delas acontecer, estratégia por estratégia:

```bash
task query -- "ninguém consegue saber quem mexeu porque a senha era de todo mundo"
```

O top-5 real dessa consulta, medido nesta máquina — o alvo é `ch_5506`:

| Estratégia | 1º | 2º | 3º | 4º | 5º |
|---|---|---|---|---|---|
| `dense` | **ch_5506** | proc_lockout | ch_5501 | proc_shift | wiki_019 |
| `bm25` | wiki_057 | ch_5501 | proc_lockout | wiki_029 | wiki_027 |
| `rrf` | ch_5501 | proc_lockout | **ch_5506** | wiki_051 | proc_shift |
| `rrf_rerank` | wiki_051 | wiki_019 | wiki_034 | wiki_044 | wiki_029 |

A leitura em uma frase: o denso acerta em 1º, o BM25 nem traz o alvo, o RRF
dilui o acerto do denso para 3º, e o cross-encoder entrega **cinco distratores
da Wikipédia** no topo. Uma consulta, os quatro modos de falha da PoC.

---

## Como escolher

Com os números acima, a decisão deixa de ser de gosto:

| Se o seu caso é… | Use | Por quê (medido aqui) |
|---|---|---|
| Consulta com **código, SKU, CNPJ, número de nota** | **BM25 puro** | 100% de hit@1 nas literais, 1,0 ms, e o denso faz 54,5% |
| Pergunta em **linguagem natural** sobre um acervo | **denso puro** | 93,3% de hit@1 nas conceituais, contra 46,7% do BM25 |
| **Os dois misturados** (o caso real) | **fusão** | 86,5% de hit@1 geral e 97,3% de hit@3 — melhor que qualquer motor sozinho |
| Precisa de **hit@1 alto** e aguenta ~230 ms a mais | **fusão + cross-encoder** | 91,9% de hit@1, ao custo de 21,5 ms por ponto |
| **Alto volume, orçamento apertado** | **BM25**, e só | 112× mais barato que qualquer coisa com vetor |
| Alimentar **contexto de LLM** com k=10 | **fusão sem reranker** | hit@10 de 100%; o reranker aqui **derruba** para 97,3% |

Duas regras que caem fora da tabela:

1. **Não fundir por reflexo.** Nas conceituais a fusão fez 66,7% contra 93,3% do
   denso puro. Se o tráfego é homogêneo e você sabe de que tipo ele é, o motor
   puro certo ganha da fusão.
2. **Reranker é a última etapa a acrescentar, não a primeira.** Ele não recupera
   nada que o prefetch não trouxe, e custa mais que todo o resto somado.

---

## Como rodar

Pré-requisitos: [Nix](https://nixos.org/download) com flakes, [uv](https://docs.astral.sh/uv/),
[Task](https://taskfile.dev) e [Ollama](https://ollama.com) rodando com o `bge-m3`
baixado. Nenhum Docker — o Postgres sobe por Nix.

```bash
cd ~/works/labs/retrieval-poc
task all          # setup → db:up → corpus → index → verify → eval → experiments → report
```

Etapa por etapa, que é como se depura:

```bash
task setup        # venv com uv, e confere que o Ollama responde
task db:up        # Postgres 17 + pgvector na porta 5434 (~25 s na primeira vez)
task corpus       # 34 alvos + 80 distratores da Wikipédia → data/corpus.jsonl
task index        # grava documentos, vetores, HNSW e estatística léxica
task verify       # CANÁRIO do índice — prova que ele enxerga antes de medir
task eval         # 6 estratégias × 37 consultas → results/evaluation.json
task experiments  # E1–E4 → results/experiments.json
task report       # results/REPORT.md a partir dos JSON
```

`task check:readme` fica **fora** do `task all` de propósito: a latência oscila
entre rodadas, então ele acusaria divergência ao fim de todo pipeline e o verde
deixaria de significar alguma coisa. Ele é o passo de **manutenção da
documentação**, rodado depois de reescrever os números.

Saída real do `task index` nesta máquina:

```
dimensão medida do modelo bge-m3: 1024
gravados 114 documentos
vetorizados em 12.8s (113 ms/documento)
índice léxico em 18 ms: 3437 termos distintos, 7047 postings,
  comprimento médio 77.8 lexemas
termos que ocorrem em um só documento: 2229
```

Os dois índices que sustentam as consultas, medidos no banco depois disso
(`pg_relation_size` sobre `pg_stat_user_indexes`):

| Índice | Tipo | Tamanho | Serve a |
|---|---|---|---|
| `documents_embedding_idx` | HNSW (pgvector) | 920 kB | `dense`, e as estratégias que a usam |
| `documents_tsv_idx` | GIN (`tsvector`) | 560 kB | `ts_rank_cd` e `bm25` |

O índice denso é **1,6× maior que o léxico** para o mesmo corpus — e é ele que
cresce com a dimensão do modelo, não com o vocabulário.

Depois de qualquer medição nova, o canário da documentação confere se o README
ainda diz a verdade:

```bash
task check:readme   # latências × JSON, âncoras, contagem de código, tamanho de índice
```

Inspecionar uma discordância à mão:

```bash
task query -- "P-101 aquecendo acima do normal"
```

Ou pela tela, que roda a consulta nas seis estratégias de uma vez e marca o
gabarito em cada resultado (detalhes em [A tela](#a-tela)):

```bash
task web          # http://127.0.0.1:8081
```

Derrubar só o banco desta PoC (a porta 5434; o 5433 da PoC de embedding fica de
pé):

```bash
task db:down
```

### O canário não é opcional

`task verify` roda cinco checagens antes de qualquer medição, e falha alto:

1. termo único devolve **só** o documento que o contém (3 casos);
2. termo inexistente devolve **lista vazia** no BM25;
3. o denso devolve **10** para a mesma consulta sem sentido;
4. a dimensão da coluna `vector(n)` bate com a dimensão **medida** do modelo;
5. a estatística léxica existe (`postings > 0`).

Sem isso, um `tsvector` vazio ou uma configuração textual errada produzem uma
tabela inteira de zeros que **parece resultado**. Métrica boa que nunca falha
não está medindo — está decorando.

### O segundo canário: o texto também mente ✅ medido

O `task verify` protege o índice. Nada protegia **este README**: cada `task all`
novo muda as latências, e reescrever à mão sempre esquece um número. Daí o
`task check:readme`, que compara o texto contra o medido — latência citada ×
JSON, âncora × heading, contagem de código × arquivos, tamanho de índice × banco.

Ele foi útil na primeira execução, o que é o teste que importa: acusou três
divergências, uma delas **criada pelo próprio commit que o introduziu** (o
script `09-check-readme.sh` virou o décimo, e o README ainda dizia nove).

E como canário que nunca falha não vale nada, o canário foi testado plantando
três mentiras no README:

```
🛑 latências citadas sem medição correspondente: [999.9]
🛑 README diz 2049 linhas de Python, medido 2069
🛑 README cita documents_tsv_idx com tamanho diferente de 560 kB
erros: 3
```

Restaurado o texto, `erros: 0`.

---

## A tela

A tabela deste README diz *que* as estratégias discordam. A tela mostra **onde**:
a mesma consulta sai nas seis ao mesmo tempo, lado a lado, com o gabarito
marcado em cada resultado.

```bash
task web:build    # compila o front para dentro do pacote Python
task web          # http://127.0.0.1:8081 (compila sozinho se faltar o bundle)
task web:check    # CANÁRIO do front — todas as rotas e o bundle, sem browser
task web:shots    # cinco prints (exige 'task web' de pé)
```

Quatro abas, cada uma respondendo a uma pergunta diferente:

| Aba | Responde |
|---|---|
| **Fazer uma pergunta** | as 6 estratégias sobre a mesma consulta, com acerto, latência e a marca de **voltou incompleta** quando devolveu menos que `k` |
| **Como isso fica guardado** | o que existe no banco para um documento: lexemas com `tf`/`df`/IDF, as 24 primeiras dimensões do vetor e o texto indexado |
| **Quem acerta mais** | a mesma tabela do `results/evaluation.json`, servida byte a byte — não recalculada |
| **Onde elas discordam** | os 15 casos em que as estratégias divergem, com id, texto da consulta e o rank que cada uma deu |

Cada aba tem **URL própria** (`?tab=score`, `?tab=document&doc=ch_5506`). Não é
enfeite: sem isso não existe link para uma aba, e nenhuma ferramenta que fotografa
a tela chega às outras três — foi o que dispensou um script de CDP com websocket
só para clicar em botão.

**A tela fala com quem não é da área.** O nome de cada estratégia aparece em
português (`dense` → "Busca por significado"), e cada cartão dobra uma explicação
de três partes — como funciona, onde acerta, onde erra — que sai do back-end, em
`STRATEGY_PLAIN`, para haver uma fonte só. O identificador técnico não some: fica
no rodapé do cartão e no `title` de cada número. `?explain=1` abre os seis blocos
de uma vez — serve para mandar o link já explicado, e é o que faz o texto dobrado
entrar num print (texto que ninguém confere é texto que envelhece errado).

Decisões que valem registro:

- **O front é dependência de _build_, não de execução.** O `pnpm build` emite em
  `src/retrieval_poc/web/static/` e o FastAPI serve dali. Quem só roda a PoC não
  precisa de Node — precisa do bundle, que já está no lugar. Medido: `index.html`
  554 B, CSS 132,67 kB (21,76 kB gzip), JS 240,59 kB (74,39 kB gzip).
- **A barra de pontuação normaliza dentro da coluna, nunca entre estratégias.**
  BM25 vai de 1,5 a 28; cosseno de 0,29 a 0,78; RRF são frações de 1/61. Uma
  escala comum faria a barra do RRF sumir e dar a impressão de que a fusão
  pontua mal — o E1 mostra que o problema é justamente esse tipo de comparação.
- **O tour de código lê o disco, não a memória.** `code_tour.py` usa `ast` em vez
  de `inspect.getsource` — assim o processo web mostra o corpo de
  `CrossEncoderReranker` **sem importar torch**. O canário confere linha a linha:
  a primeira linha de cada bloco tem que bater com a linha real do arquivo.
- **`/api/measured` devolve o JSON do disco, sem tocar.** Se a tela recalculasse,
  ela poderia discordar do `REPORT.md` e ninguém notaria. O canário compara os
  dois byte a byte.

### O terceiro canário: a tela também mente ✅ medido

Tela é a parte que ninguém testa — abre bonita e mente calada. `task web:check`
faz **99 asserções** em 8 seções contra o servidor no ar, sem browser, e não
aborta na primeira falha (uma rodada mostra tudo que está quebrado). Ele pega
três coisas que passam por qualquer olhada:

1. **rota 200 com o campo errado** — o front lê `first_relevant`; se a chave
   sumir num refactor, o cartão para de marcar acerto e continua verde;
2. **bundle antigo** — build interrompido deixa o HTML apontando para um asset
   apagado. O servidor devolve 404 só para aquele arquivo e a página fica
   **branca**, sem uma linha de erro no terminal. Por isso o canário busca cada
   `src`/`href` do HTML e exige 200;
3. **número exibido divergindo do medido** — `/api/measured` × `results/*.json`.

E ele já se pagou duas vezes, que é o teste que importa. Pegou um HTTP 500 em
`/api/document/proc_cip` — `'Vector' object is not iterable`, porque o
`register_vector` do pgvector devolve um objeto que só entrega os números por
`to_list()`. E acusou um `results/index_stats.json` que **não existe**: era um
nome inventado no código do servidor, e o tamanho de índice já vinha medido do
catálogo do Postgres.

O que o canário **não** pega, e por isso `task web:shots` existe: a tela anunciou
"26 operacionais + 88 da Wikipédia" onde o corpus tem 34 alvos e 80 distratores.
Rota 200, contrato certo, soma fechando — e o rótulo errado. A causa é a
confusão de dois eixos independentes: `source` é a **origem** (à mão × Wikipédia)
e `kind` é a **forma** (registro × prosa). Os 8 procedimentos são `handwritten`
**e** `prose` ao mesmo tempo, então contar alvo por `kind` perde oito. Só
apareceu **olhando o print**. Hoje há duas asserções que impedem a recaída — as
duas somas têm que fechar separadamente, e os dois eixos não podem colapsar no
mesmo número.

E ele deixou passar coisa pior: uma prop indefinida (`explain`, passada ao
componente errado) derrubou o render da **aba inteira**. O canário seguiu com
`erros: 0` — o servidor estava íntegro, quem quebrou foi o JS depois do 200 —, e
o defeito só apareceu porque o print da aba de busca saiu **em branco**. O sinal
barato disso é o tamanho do arquivo: os PNG desta tela nunca descem de 200 kB, e
o branco deu 10 979 B. Por isso `task web:shots` hoje falha (`rc=1`) quando um
print fica abaixo de 60 kB. Verificado invertendo o limiar: com `MIN_BYTES=300000`
ele acusa três dos cinco e sai != 0 — canário que nunca apita não está medindo.

---

## Arquitetura

Ports & Adapters, com uma decisão de projeto que é a tese inteira: `Retriever` e
`Reranker` são contratos **diferentes**.

```
src/retrieval_poc/
├── ports.py                   TextEmbedder · Retriever · Reranker
├── models.py                  Document · Hit · Query
├── config.py                  parâmetros, todos com padrão explícito
├── adapters/
│   ├── postgres.py            DocumentStore: DDL, tsvector, lex_terms, HNSW
│   ├── ollama_embedder.py     texto → 1024 floats, dimensão MEDIDA
│   ├── lexical.py             Bm25Retriever · TsRankRetriever
│   ├── dense_retriever.py     cosseno sobre HNSW
│   └── cross_encoder.py       CrossEncoderReranker
├── strategies/
│   ├── fusion.py              reciprocal_rank_fusion · weighted_fusion
│   ├── base.py                Single · Fusion · Rerank
│   └── registry.py            o "cmd/main": wiring único
├── corpus/                    build.py (alvos + distratores) · queries.py (gabarito)
├── evaluation/                metrics.py · runner.py · experiments.py
├── web/
│   ├── app.py                 FastAPI: 7 rotas, adapter DRIVING da mesma pilha
│   ├── code_tour.py           corpo das funções lido por `ast` (sem importar torch)
│   └── static/                bundle emitido pelo `pnpm build` — servido daqui
├── report.py                  results/REPORT.md
└── cli.py                     corpus · index · verify · eval · experiments · report · query

frontend/                      React 19 + Vite + Kumo — fonte da tela, dependência
                               de BUILD (o pacote Python não precisa de Node)

tools/check_readme.py          canário da documentação (fora do pacote: não é
tools/web_check.py             parte da PoC, é quem audita a PoC — texto e tela)
```

**2 731 linhas de Python**, 15 scripts numerados em `scripts/` (`00-setup` a
`14-web-shots`), e um `Taskfile.yaml`
que chama script — nunca comando ad-hoc.

O servidor web é **adapter driving**, no mesmo sentido do `cli.py`: ele traduz
HTTP para a pilha construída por `registry.py` e não conhece nenhum motor de
busca. Trocar `ts_rank` por SPLADE não muda uma linha de `web/`.

Por que os dois contratos são distintos:

```python
class Retriever(Protocol):
    """Consulta -> candidatos, varrendo o corpus inteiro.
    Custo por consulta é sublinear no tamanho do corpus."""
    def search(self, text: str, k: int) -> list[Hit]: ...

class Reranker(Protocol):
    """(consulta, documentos) -> mesma lista reordenada.
    Custo é linear nos candidatos, e cada candidato custa uma inferência."""
    def rerank(self, text: str, hits: list[Hit], k: int) -> list[Hit]: ...
```

Confundir os dois é o erro que faz gente colocar cross-encoder na frente de um
milhão de documentos. Aqui o tipo impede.

Acrescentar uma estratégia (SPLADE, ColBERT, reranker de API) é escrever um
adapter que satisfaça um dos dois protocolos e somar uma entrada em
`registry.py`. **Nada em `evaluation/` muda** — quem mede não sabe se a lista
veio de índice invertido, de grafo HNSW ou da fusão dos dois.

---

## O que NÃO está implementado

📖 **explicado, não medido** — cada um destes moveria todos os números da tabela:

| Estratégia | O que faria | Por que não está aqui |
|---|---|---|
| **SPLADE / esparso aprendido** | expande a consulta com termos que o modelo julga implícitos; casa símbolo *e* sentido no mesmo índice invertido | exige treinar ou servir um modelo de expansão; muda o pipeline de indexação inteiro |
| **ColBERT / late interaction** | um vetor por token, MaxSim entre consulta e documento; qualidade de cross-encoder com custo pré-computável | armazenamento explode (~centenas de vetores por documento) e o pgvector não tem operador nativo para MaxSim |
| **Chunking** | dividir documento longo em trechos indexados separadamente | os documentos aqui têm 729 caracteres em média — cabem inteiros na janela. Em PDF de 40 páginas, chunking é a decisão mais importante do sistema, e não está medida |
| **Expansão de consulta por LLM** | reescrever a pergunta antes de buscar | acrescentaria uma chamada de LLM por consulta e tornaria a latência incomparável com o resto |
| **Filtro de metadados** (`WHERE kind = 'record'`) | pré-filtrar por tipo antes do ranking | interage de forma não trivial com HNSW (o grafo pode não ter k vizinhos válidos após o filtro) e mereceria uma PoC própria |
| **Quantização / Matryoshka** | vetor menor, índice menor, consulta mais rápida | com 114 documentos o índice HNSW tem 920 kB; não há o que otimizar aqui |

---

## Limitações — o que estes números NÃO provam

| Limitação | Consequência |
|---|---|
| Corpus de **114 documentos**, 37 consultas | os 100% de hit@10 são "não errou em 37 perguntas", não "resolve busca". Em 100 mil documentos os distratores mudam tudo |
| **Duas rodadas, mesma máquina** | as métricas de qualidade repetiram idênticas, mas isso é determinismo (`SEED = 17`), **não** intervalo de confiança: o gabarito é o mesmo nas duas. Diferença de 2,7 pontos entre BM25 e `ts_rank_cd` continua sendo 1 consulta de 37 |
| **Latência varia entre rodadas** | ~6% de oscilação medida (p50 do reranker 362,6 → 383,2 ms). Ler tempo como ordem de grandeza, nunca como constante |
| Nas híbridas, **o identificador sozinho já desambigua** | por isso todo mundo faz 100% ali. Num corpus onde o mesmo código aparece em 200 documentos, essa família seria a mais difícil, não a mais fácil |
| Distratores filtrados por uma **blocklist de 17 termos** | o corpus é *mais fácil* que o real: por construção, nenhum distrator fala do domínio. 6 artigos foram descartados por isso — o número está medido, o viés não está corrigido |
| Alvos **escritos sabendo qual pergunta responderiam** | é o que torna o gabarito defensável e, ao mesmo tempo, otimista. Documento real é escrito sem saber que vai ser procurado |
| Latência do denso (113 ms) é **quase toda HTTP para o Ollama** | num serviço com o modelo residente e batching, esse número cai muito. Não compare 1,0 ms contra 113 ms como se fosse custo de algoritmo — é custo de arquitetura |
| p95 com **37 amostras** é quase o máximo | serve para separar "caro" de "muito caro", não para dimensionar capacidade |
| **Um** modelo denso e **um** reranker | `bge-m3` é forte em português; um encoder pior derrubaria o denso e mudaria toda a conclusão sobre fusão |
| Configuração textual fixa em `portuguese` | o stemmer decide o que é "mesmo termo". Com `simple`, "compressores" e "compressor" deixam de colidir e todo número léxico muda |
| Gabarito **binário**, sem relevância graduada | por isso não há nDCG. "Responde" e "menciona de passagem" valem igual |

---

## Conclusão prática

Para acervo de verdade — ordem de serviço, nota fiscal, procedimento e chamado
no mesmo balde — nenhuma estratégia isolada resolve:

- o **denso** faz **54,5%** de hit@1 quando a pergunta é um código;
- o **léxico** faz **46,7%** quando a pergunta é uma descrição;
- o **reranker** não recupera nada que o prefetch não trouxe, e ainda derrubou o
  hit@10 de 100% para 97,3%.

O que chegou mais longe foi **combinar**, e o preço está medido: 115 ms por
consulta na fusão, 383 ms com reranking, contra 1,0 ms do BM25 sozinho. A decisão
é de custo e de perfil de tráfego, não de acurácia.

E há uma lição que não está em nenhuma célula da tabela: **os dois motores erram
de formas que se enxergam de fora de jeitos opostos**. O léxico erra devolvendo
pouco — parece quebrado, e alguém conserta. O denso erra devolvendo dez
resultados plausíveis e errados — parece funcionando, e ninguém conserta. Por
isso a coluna de consultas famintas está no placar, e por isso o canário roda
antes de qualquer medição.
