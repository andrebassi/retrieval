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

Esta tabela é estática e cabe em três linhas de resumo: **comece pela fusão por
posição** (`rrf`), **ligue o revisor** (`rrf_rerank`) só quando o primeiro
resultado for o que a pessoa lê, e **nunca use o denso sozinho**. Quem quiser a
mesma decisão para o *seu* caso, com os 27 cenários calculados sobre os mesmos
números medidos, assiste ao vídeo de 20 a 34 s da aba **“Qual devo usar?”** do
`task web` — descrito em [A tela](#a-tela).

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
task web:shots    # dezoito prints (exige 'task web' de pé)
task web:restart  # rebuild não basta: o servidor sobe sem reload
```

Cinco abas, cada uma respondendo a uma pergunta diferente. A primeira é a de
entrada, e responde a pergunta que sobra depois de ler a tabela inteira:

| Aba | Responde |
|---|---|
| **Qual devo usar?** | um **vídeo** de 20 a 34 s, montado no navegador a partir do payload: as seis entram sem nota, cada cena aplica **um** critério e mexe no placar na frente de quem assiste, e o empate vai para um mata-mata que decide a campeã. Uma ideia por cena, uma linha de legenda, controles de vídeo de verdade |
| **Fazer uma pergunta** | as 6 estratégias sobre a mesma consulta, com acerto, latência e a marca de **voltou incompleta** quando devolveu menos que `k` |
| **Como isso fica guardado** | o que existe no banco para um documento: lexemas com `tf`/`df`/IDF, as 24 primeiras dimensões do vetor e o texto indexado |
| **Quem acerta mais** | a mesma tabela do `results/evaluation.json`, servida byte a byte — não recalculada |
| **Onde elas discordam** | os 15 casos em que as estratégias divergem, com id, texto da consulta e o rank que cada uma deu |

Cada aba tem **URL própria** (`?tab=score`, `?tab=document&doc=ch_5506`), e o
vídeo também, inclusive o capítulo em que ele está
(`?reader=llm&budget=patient&kind=conceptual&step=8`). Não é enfeite: sem isso
não existe link para uma aba nem para um cenário, e nenhuma ferramenta que
fotografa a tela chega às outras quatro — foi o que dispensou um script de CDP
com websocket só para clicar em botão.

No vídeo o `step` faz mais: cada cena desenha um ramo diferente da composição, e
o que só existe **enquanto o vídeo toca** nenhum print alcança. Daí os **treze
prints `video-*`**, um por ramo:

| Print | O ramo que ele é o único a cobrir |
|---|---|
| `video-abertura` | as seis entram com a barra a zero — o único quadro sem régua escolhida |
| `video-quem-le` · `video-tempo` · `video-pergunta` | as três rodadas que remontam o placar; `video-tempo` é a única com linha riscada |
| `video-desempate` | a cena que existe **só** quando a nota empata |
| `video-criterio1/2/3` | os critérios do mata-mata, que são as cenas que de fato **elegem** a campeã. O 3º só aparece quando os dois primeiros não separam ninguém, e tem cenário próprio para chegar lá |
| `video-campea` | o placar dá lugar ao pódio — outro desenho, não outro estado |
| `video-llm` | o mesmo componente, cenário diferente, **campeã diferente** |
| `video-corte` | o relógio de 5 ms derrubando 4 das 6 de uma vez; nos outros orçamentos cai uma ou nenhuma |
| `video-trocas` | seis mudando de posição na mesma cena — a reordenação que dá nome à PoC |
| `video-sem-empate` | o caso em que a nota decide sozinha: o roteiro pula a cena de empate **e o mata-mata inteiro**, e o vídeo tem cinco capítulos em vez de oito |

O print determinístico sai de graça de uma decisão de acessibilidade:
`prefers-reduced-motion: reduce` deixa o player **parado** em vez de tocando
sozinho, e o Chrome headless roda com `--force-prefers-reduced-motion`. Sem isso
o print seria uma corrida contra a reprodução — o mesmo `?step=` devolveria um
quadro diferente a cada rodada.

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
  554 B (370 B gzip), CSS 134 362 B (22 105 B gzip), JS 512 972 B (159 173 B
  gzip). Contra o que este README media na versão anterior — CSS 147,67 kB
  (24,58 kB gzip), JS 415,60 kB (128,60 kB gzip) —, trocar o torneio em CSS +
  `motion` pelo `@remotion/player` custou **+97 372 B de JS** e devolveu
  **−13 308 B de CSS**: saldo de +84 064 B crus, +28 098 B gzipados, num arquivo
  servido da própria máquina. O que isso compra é a rolagem sumir **por
  construção** — canvas 1600×900 escalado pelo Player — em vez de sumir por
  ajuste de CSS que a próxima janela estreita desfaz. O `motion` saiu do
  `package.json` junto: sem nenhum `import`, ele já não entrava no bundle (o
  hash do JS não mudou ao removê-lo), mas dependência que ninguém usa é
  dependência que alguém reinstala sem querer.
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

### O vídeo: a mesma decisão, uma cena por critério

A aba de entrada não opina — ela lê `results/evaluation.json` e resolve, para
cada um dos **27 cenários** (3 leitores × 3 orçamentos de tempo × 3 tipos de
pergunta), qual estratégia recomendar. A aritmética inteira vive no back-end
(`/api/advice`), pela mesma razão de sempre: existe **um** caminho de cálculo, e
ele é testável pelo canário. O front só desenha.

**Três versões morreram até chegar aqui, e cada morte ensinou uma coisa.** A
primeira punha as três perguntas lado a lado: só servia para quem já sabia o que
cada pergunta significava, e essa pessoa não precisa da aba. A segunda virou
assistente — uma pergunta por tela, resposta no fim —, correta e inerte: quem
respondia não via nada acontecer com as seis. A terceira pôs um placar ao vivo ao
lado do texto, e o placar de fato se mexia — mas o texto explicava tudo ao mesmo
tempo e a página passou a **rolar**. Texto que tenta explicar tudo de uma vez não
explica nada, e o que rola para fora não é lido.

A quarta não é uma página animada: é um **vídeo**. `@remotion/player` toca uma
composição React determinística por frame, com play, pausa, barra arrastável e
capítulos — e o canvas é 1600×900 fixo, escalado para caber na janela. **A
rolagem não foi consertada, ela deixou de ser possível**: o que não cabe no
quadro não existe, e isso aparece na hora de escrever a cena, não no dia em que
alguém abre num monitor menor.

| Cena | Quanto dura | O que ela e só ela mostra |
|---|---|---|
| As seis | 2,7 s | as competidoras entram com a barra **a zero** — para que a rodada 1 seja vista preenchendo |
| Quem lê | 3,8 s | a régua troca (hit@1 → hit@3 → hit@10) e as notas **remontam** |
| Tempo | 3,8 s | o relógio risca quem estoura o orçamento, com o motivo na linha (`383,2 ms · o limite é 5 ms`) |
| Pergunta | 4,3 s | a nota deixa de ser a média das 37 e passa a ser a da família — o placar **reordena** |
| Empate | 3,3 s | quantas ficaram dentro de 2,7 pontos. Só existe se houver empate |
| Mata-mata | 3,5 s **por critério** | um critério por cena: quem entrou, quem passou, quem caiu e por quê |
| Campeã | 5,0 s | o placar dá lugar ao pódio, com a frase que diz o que de fato decidiu |

Duração total **medida**, ponta a ponta nos 27 cenários: **19,7 s** no mais curto
(`few|instant|conceptual`, 5 cenas, sem empate) e **33,5 s** no mais longo
(`llm|patient|literal`, 9 cenas, mata-mata de três critérios).

Cada cena tem **um** assunto e **uma** linha de legenda. É a regra que substituiu
o painel de texto da versão anterior: quando a legenda não cabe numa linha, não é
a fonte que está grande — é a cena que está tentando dizer duas coisas.

O roteiro e o desenho são arquivos **separados**, e isso não é organização, é
testabilidade:

```
frontend/src/video/
├── scenes.js       ROTEIRO — payload → lista de cenas. Código puro, sem frame
└── Tournament.jsx  DESENHO — um quadro a partir do frame. Não calcula nota
```

`scenes.js` decide **o que** cada cena diz e **quando** ela entra; `Tournament.jsx`
recebe `scenes[i]` e o frame atual, e só interpola. Misturar os dois produz a
composição de 600 linhas em que a regra de negócio some no meio do `interpolate`
— e nenhuma das duas partes fica conferível sozinha.

O mata-mata é o coração do "por que ela ganhou": a campeã quase nunca vence por
acertar mais — ela vence **por critério de engenharia dentro de um empate que a
nota não resolve**. Antes isso era uma frase de três linhas que ninguém lia.

A regra tem três degraus, nesta ordem:

1. **corta quem estoura o tempo** — `p50` acima do orçamento sai da disputa,
   mesmo acertando mais. Na cena em que cai, a linha fica **vermelha** com o
   motivo escrito; das cenas seguintes em diante, riscada, apagada e sem número:
   o lugar da nota passa a dizer `fora`, porque quem já caiu não tem mais direito
   de exibir um número que não vai disputar;
2. **acha a faixa de empate** — com 37 perguntas medidas, **uma** pergunta vale
   `1/37` = **2,7 pontos**. Quem estiver a menos disso da líder não está atrás:
   está empatado, e a cena de empate acende exatamente essas linhas;
3. **desempata por engenharia, não por nota** — dentro da faixa a nota não
   distingue nada, então vence quem (a) devolve a lista cheia, (b) não tem nada
   para calibrar, (c) responde mais rápido — nesta ordem.

O critério (b) não é decoração. **Sem ele, o cenário mais comum da tela — o
estado inicial, que é o que 90% das pessoas vão ver — recomendava a `weighted`
por 3 ms de diferença**: dentro de um empate de 100% onde a nota não separa nada,
os 3 ms elegiam justamente a única opção que precisa de peso e escala calibrados
neste acervo. `tuning_free` virou campo do payload e entrou antes do tempo.

E o texto do desempate é **derivado** do que de fato distinguiu, não fixo. A
frase fixa produzia a contradição de anunciar “é a única que devolve a lista
cheia” logo acima do aviso de que a vencedora devolve lista curta em 3 perguntas.
Hoje há asserção para isso no canário — e a mutação que reintroduz a frase fixa
faz o canário apitar (`llm|instant|conceptual`), como toda verificação que
precisa provar que enxerga.

Um efeito colateral que valeu por si: a lista de ranking passou a sair na **mesma
ordem do desempate**. Ordenada por nota, ela colocava a `weighted` (117,8 ms) em
1º e a vencedora `rrf` (119,7 ms) em 2º — na mesma tela que explica por que a
`rrf` ganhou.

**A animação carrega significado, não enfeite.** A rodada 3 troca seis linhas de
lugar; num quadro só, "as notas mudaram" deixaria de ser notícia. Com o
deslocamento animado dá para **ver** o denso descer da 1ª para a 5ª.

A versão anterior conseguia isso com a prop `layout` do `motion` — FLIP de
verdade: mede a posição antes, mede depois, interpola. Na composição não existe
"antes": o quadro `n` é uma função pura de `n`, e um FLIP que mede o DOM
devolveria um pixel diferente conforme a máquina estivesse ocupada. O que
substitui é determinístico e mais simples de auditar: a **ordem de render é fixa**
(sempre a mesma sequência de `name`, o que faz o React reaproveitar cada linha), e
a posição sai de `translateY(pos × 78 px)` com `pos` interpolado entre a cena
anterior e a atual. Nota, opacidade e o esmaecimento de quem caiu passam pela
mesma interpolação. Mesma leitura na tela, e o print do frame 34 de um capítulo é
sempre o mesmo arquivo.

O que **não** mudou é a razão pela qual todas as etapas do mata-mata têm capítulo
próprio: a primeira versão as agrupava num botão só, para a barra não virar
fileira de botões de 3 s. O efeito colateral foi pior que o problema — sem
capítulo próprio, as cenas que de fato **decidem** a campeã só existem enquanto o
vídeo toca, e o que print não alcança quebra calado (armadilha 19). Com empate são
8 botões no máximo, e eles cabem na largura.

### O terceiro canário: a tela também mente ✅ medido

Tela é a parte que ninguém testa — abre bonita e mente calada. `task web:check`
faz **147 asserções** em 10 seções contra o servidor no ar, sem browser, e não
aborta na primeira falha (uma rodada mostra tudo que está quebrado). Ele pega
três coisas que passam por qualquer olhada:

1. **rota 200 com o campo errado** — o front lê `first_relevant`; se a chave
   sumir num refactor, o cartão para de marcar acerto e continua verde;
2. **bundle antigo** — build interrompido deixa o HTML apontando para um asset
   apagado. O servidor devolve 404 só para aquele arquivo e a página fica
   **branca**, sem uma linha de erro no terminal. Por isso o canário busca cada
   `src`/`href` do HTML e exige 200;
3. **número exibido divergindo do medido** — `/api/measured` × `results/*.json`.

E ele já se pagou três vezes, que é o teste que importa. Pegou um HTTP 500 em
`/api/document/proc_cip` — `'Vector' object is not iterable`, porque o
`register_vector` do pgvector devolve um objeto que só entrega os números por
`to_list()`. E acusou um `results/index_stats.json` que **não existe**: era um
nome inventado no código do servidor, e o tamanho de índice já vinha medido do
catálogo do Postgres.

A terceira foi na estreia da seção 10 — as asserções do torneio pegaram, na
primeira rodada, um defeito de produto em 3 das 9 combinações:

```
🛑 rodada 2 · first|instant [quem está riscado no placar não é quem está na lista de fora]
```

O placar saía na ordem dos assentos e a lista de eliminadas na ordem em que as
linhas chegaram do `evaluation.json`. Os dois desenham **a mesma** eliminação, e
ordens diferentes fazem a lista de quem caiu contradizer as linhas riscadas ao
lado. Nenhuma asserção anterior via isso: cada estrutura estava certa sozinha, e
o defeito só existe na relação entre as duas — que é o que a asserção nova
compara. É também o padrão das armadilhas 23 e 24, pela terceira vez: **duas
partes da tela contando a mesma história em ordens diferentes**.

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
barato disso é o tamanho do arquivo: o menor PNG desta tela tem 129 642 B
(`video-sem-empate`) e o branco deu 10 979 B — uma ordem de grandeza de folga.
Por isso `task web:shots` hoje falha (`rc=1`) quando um print fica abaixo de
60 kB. Verificado invertendo o limiar: com `MIN_BYTES=300000` ele acusa **15 dos
18** e sai `rc=1` — canário que nunca apita não está medindo.

E os prints continuam pegando o que nenhuma asserção pega. Cinco defeitos desta
última rodada só apareceram **olhando o PNG**, todos com canário verde:

| O que o print mostrou | Causa |
|---|---|
| o mata-mata cortado na 3ª etapa — some justamente a que decide | `height` fixo na moldura do passo. Fixa deixa os quatro passos do mesmo tamanho e a troca não dá salto, mas o passo 4 é o mais longo de todos e o excedente era cortado. `min-height` mantém a estabilidade e deixa o 4 crescer |
| três linhas do placar com o **mesmo** nome, notas diferentes | o rótulo longo é cortado com reticências, e "As duas juntas, somando…" / "…por posição" / "…+ revisor" viravam todas o mesmo texto. Rótulo curto próprio (`STRATEGY_SHORT`), com `·` no lugar da vírgula — o corte caía exatamente nela |
| selo `empatada` já na **rodada 1** | `tied` é conclusão da rodada 4: fala da nota do tipo de pergunta escolhido. Marcado antes, o selo dizia que duas empatam num número que nem é o do cenário |
| faixa listrada de empate **invisível** | ela vale 2,7 pontos num track de 74 px = 2 px de listra. Decoração que ninguém enxerga fingindo ser informação — quem carrega o empate no placar é o selo, que é legível |
| “a menos de 2,7 pontos” **quatro vezes** na mesma coluna | com quatro empatadas o mesmo texto repetido vira textura, não informação. O número é dito uma vez, no cabeçalho do placar |

E a rodada do vídeo rendeu mais quatro, no mesmo regime de canário verde:

| O que o print mostrou | Causa |
|---|---|
| uma eliminada do mata-mata **verde de novo**, com a nota inteira, na etapa seguinte | o `ranked` do back-end só marca quem saiu por **tempo**. Cada etapa precisa herdar as eliminações das anteriores — sem isso a linha derrubada em “Calibrar” volta a disputar em “Relógio”, exibindo um número a que já não tem direito. Um `Set` acumula quem caiu, e a cena reescreve `eliminated` antes de desenhar |
| `Palavra · simples · Palavra · com peso saem` — lê como **quatro** nomes | o rótulo curto já usa `·` como separador interno (foi a correção do nome repetido, duas linhas acima). Juntar duas eliminadas com `·` ressuscita a mesma ambiguidade na legenda. Hoje é `e` para duas, e a contagem para três ou mais — quem saiu está em vermelho logo acima |
| legenda em **duas linhas**, a segunda por cima da última linha do placar | legenda é linha única por contrato (`nowrap`), e o corpo cai de 38 px para 30 px acima de 62 caracteres. O canário ganhou teto de 100 chars — **medido**: a legenda mais longa de hoje tem 62 chars e ocupa 812 px dos 1488 px úteis, ou 13,1 px por caractere |
| `1 saem por tempo`, `1 das 6 chegam` | frase montada com contagem e verbo fixo. Só se manifesta no dia em que a contagem cai para 1 — que é justamente o cenário mais interessante. O canário varre o payload **inteiro** serializado com um regex de plural, porque a frase pode nascer em qualquer rodada, célula ou etapa |

Nenhum desses quebra rota, contrato ou soma. Todos quebram a tela.

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
│   ├── app.py                 FastAPI: 8 rotas, adapter DRIVING da mesma pilha
│   ├── code_tour.py           corpo das funções lido por `ast` (sem importar torch)
│   └── static/                bundle emitido pelo `pnpm build` — servido daqui
├── report.py                  results/REPORT.md
└── cli.py                     corpus · index · verify · eval · experiments · report · query

frontend/                      React 19 + Vite 6 + Kumo — fonte da tela, dependência
│                              de BUILD (o pacote Python não precisa de Node)
└── src/video/                 composição Remotion da aba "Qual devo usar?"
    ├── scenes.js              ROTEIRO — payload → cenas. Código puro, sem frame
    └── Tournament.jsx         DESENHO — um quadro a partir do frame

tools/check_readme.py          canário da documentação (fora do pacote: não é
tools/web_check.py             parte da PoC, é quem audita a PoC — texto e tela)
```

**3 482 linhas de Python** em `src/`, 2 667 de front em `frontend/src/` (617 delas
na composição de vídeo), 16 scripts numerados em `scripts/` (`00-setup` a
`15-web-restart`), e um `Taskfile.yaml`
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
