# CLAUDE.md — retrieval-poc

Guia para o Claude Code trabalhar neste diretório. O `README.md` é o documento
para humanos, com os números e o raciocínio; aqui ficam as regras de operação, a
arquitetura e — o mais importante — **as armadilhas já pagas**.

## O que este projeto é

PoC que compara **seis estratégias de recuperação** sobre o mesmo corpus, o mesmo
gabarito e a mesma máquina: `ts_rank_cd`, BM25, denso (`bge-m3`), fusão min-max,
RRF e RRF + cross-encoder.

Não é biblioteca, não é serviço, não vai para produção. É **bancada de medição**:
o valor está nos números serem reprodutíveis e nas conclusões serem defensáveis,
não no código ser reaproveitável.

Corpus: 114 documentos (34 alvos de manutenção industrial escritos à mão + 80
distratores da Wikipédia em pt). Gabarito: 37 consultas em 3 famílias.

## Regras invioláveis deste projeto

1. **Nenhum número no README ou no REPORT.md sem ter rodado o comando que o
   mediu, nesta máquina.** Estimativa é proibida. Se o número mudou, rode
   `task report` de novo — ele reescreve o `results/REPORT.md` a partir dos JSON
   — e feche com **`task check:readme`**, que compara o README contra o medido e
   sai != 0 na divergência. Ele **não** está no `task all`: latência oscila ~6%
   entre rodadas, e um canário que apita por rotina deixa de ser lido. Rode-o
   depois de reescrever os números, como último passo.
2. **`task verify` roda antes de qualquer medição.** É o canário. Métrica que
   nunca falha não está medindo.
3. **Postgres só por Nix, na porta 5434.** Nunca Docker (rule 23). O 5432 é o do
   sistema e o 5433 é o do `image-embedding-poc` — derrubar qualquer um dos dois
   é acidente, não colateral aceitável.
4. **Comando ad-hoc não entra.** Script em `scripts/NN-nome.sh`, task no
   `Taskfile.yaml`, e o `Taskfile` chama o script (rule 05).
5. **Identificador em inglês, comentário e texto em pt-BR acentuado** (rule 24).
   Vale para nome de arquivo, de coluna e de task.
6. **Comentário explica a decisão, não a sintaxe.** Todo comentário do projeto
   responde "por que assim, e não do jeito óbvio". Se explica o que a linha faz,
   apague a linha de comentário.
7. **Corpus e resultados não são versionados** (`data/corpus.jsonl`,
   `results/*.json` estão no `.gitignore`); **`results/REPORT.md` é**, porque é o
   registro do que foi medido.

## Arquitetura — Ports & Adapters

```
src/retrieval_poc/
├── ports.py            TextEmbedder · Retriever · Reranker  ← contratos
├── models.py           Document · Hit · Query
├── config.py           Settings, tudo com padrão explícito e env var
├── adapters/
│   ├── postgres.py     DocumentStore — DDL, tsvector gerado, lex_terms/lex_stats, HNSW
│   ├── ollama_embedder.py   texto → vetor; `dim` é MEDIDA, não constante
│   ├── lexical.py      Bm25Retriever (fórmula à mão) · TsRankRetriever (nativo)
│   ├── dense_retriever.py   cosseno `<=>` sobre HNSW
│   └── cross_encoder.py     CrossEncoderReranker (sentence-transformers)
├── strategies/
│   ├── fusion.py       reciprocal_rank_fusion · weighted_fusion
│   ├── base.py         SingleStrategy · FusionStrategy · RerankStrategy
│   └── registry.py     build_stack() — ponto ÚNICO de wiring
├── corpus/
│   ├── build.py        alvos do YAML + distratores da Wikipédia (SEED=17, blocklist)
│   └── queries.py      gabarito, com validação que aborta em id inexistente
├── evaluation/
│   ├── metrics.py      hit@k · MRR · percentil · starved
│   ├── runner.py       roda todas as estratégias → results/evaluation.json + hits.json
│   └── experiments.py  E1–E4 → results/experiments.json
├── report.py           gera results/REPORT.md
└── cli.py              subcomandos, um por etapa do pipeline
```

**A decisão que sustenta o projeto**: `Retriever` e `Reranker` são protocolos
diferentes de propósito. Recuperador varre o corpus inteiro e precisa ser barato;
reranqueador olha lista curta e pode ser caro. Não unifique os dois "para
simplificar" — a separação é a tese, não acidente.

Somar uma estratégia = escrever adapter que satisfaça um dos protocolos +
acrescentar entrada em `registry.py` e em `STRATEGY_ORDER`. **Nada em
`evaluation/` muda.**

## Comandos

```bash
task -l                # descobrir
task all               # pipeline completo
task db:up             # Postgres 17 + pgvector, porta 5434 (~25 s na 1ª vez)
task db:down           # derruba SÓ o 5434
task db:psql           # psql no banco da PoC
task corpus            # monta data/corpus.jsonl
task index             # documentos + vetores + HNSW + estatística léxica
task verify            # CANÁRIO do índice — 5 checagens, sai != 0 se algo não enxerga
task check:readme      # CANÁRIO da documentação — README × números medidos
task eval              # 6 estratégias × 37 consultas
task experiments       # E1–E4
task report            # results/REPORT.md
task query -- "P-101 aquecendo acima do normal"
task clean             # apaga corpus e resultados, mantém o banco
```

Toda task loga em `/tmp/retrieval-poc-*.log` via `tee`, e o `Taskfile` tem
`set: [pipefail]` no topo — sem ele o `tee` mascara o status do comando e toda
task "passa".

## Armadilhas já pagas — não repetir

| # | Sintoma | Causa | Correção |
|---|---|---|---|
| 1 | `error: Path 'retrieval-poc' in the repository "…/labs" is not tracked by Git` | `nix run .#services` só enxerga arquivo versionado, e a PoC roda antes do primeiro commit | `nix run "path:$PWD#services"` — o prefixo `path:` lê o diretório direto |
| 2 | `FTL TUI startup error error="open /dev/tty: device not configured"` | process-compose tenta abrir TUI sem terminal | acrescentar `-- --tui=false` ao `nix run` |
| 3 | `pg_available_extensions` mostra `vector` com `installed_version` vazio, e o `CREATE TABLE` quebra em `type "vector" does not exist` | `initialScript.before` roda **antes** de os bancos de `initialDatabases` existirem — a extensão nasceu no banco `postgres`, não no `retrieval` | mover para `schemas` dentro de `initialDatabases`, e apagar `data/pg` para reinicializar |
| 4 | `task db:down` diz "nada encontrado" e o Postgres continua de pé | `pgrep -f "process-compose.*retrieval-poc"` não casa: o process-compose renomeia o processo e o caminho do projeto não aparece na linha de comando | identificar pela **porta**: `lsof -nP -iTCP:5434 -sTCP:LISTEN -t`. **Nunca** `pkill -f process-compose` — derruba o 5433 do `image-embedding-poc` junto |
| 5 | `indexados 0 documentos em 13.9s` | `cmd_index` chamava `dense.index(docs)` sem antes gravar as linhas; `UPDATE documents SET embedding` em tabela vazia não afeta nada e não dá erro | `store.insert(docs)` **antes** de `dense.index(docs)` |
| 6 | `psycopg.errors.DuplicateTable: relation "documents_embedding_idx" already exists` | `create_vector_index()` chamado em dois lugares — dentro de `DenseRetriever.index()` e de novo no `cli.py` | a chamada vive **só** em `DenseRetriever.index()`, depois de gravar todos os vetores (HNSW construído com tabela vazia produz grafo pior) |
| 7 | Léxico devolve vazio em 22 das 37 consultas | `plainto_tsquery` faz **AND** entre os termos — é o padrão do Postgres | `to_tsquery` com `\|`. Está medido no E4: AND devolve 0,49 documento em média contra 7,65 do OR |
| 8 | Comentário diz 33 consultas, `task corpus` diz 37 | contagem escrita à mão e não recontada depois de acrescentar consultas | qualquer número em comentário/doc sai de comando rodado (regra 1 acima) |
| 9 | `task all` parado no corpus por 11 min, com `data/corpus.jsonl` **já completo** no disco | `datasets` (e `torch`) deixam thread não-daemon viva; o processo trava em `pthread_cond_wait` dentro de `__cxa_finalize_ranges` **depois** de imprimir tudo | `main()` termina em `os._exit(rc)`, precedido de `multiprocessing.util._exit_function()` (senão sai "leaked semaphore objects") e do flush explícito. Sem isso o hang é invisível: parece lentidão, não travamento |
| 10 | Diagnosticar processo travado com `ps \| grep` e não achar nada | o wrapper `rtk` filtra a listagem | `rtk proxy ps -eo pid,ppid,etime,command`. Para a pilha: `sample <pid> 3 -f /tmp/x.txt` — foi o que mostrou o `__cxa_finalize_ranges` da linha acima |
| 11 | Verificador de âncoras acusa `por-família--onde-a-média-mente` como quebrada, e o link funciona no GitHub | o GitHub **descarta** `—` e emoji em vez de virar hífen, e **não colapsa** espaços — daí os dois hífens | `re.sub(r"[^\w\s\-]", "", …)` e depois `.replace(" ", "-")`, nunca `re.sub(r"\s+", "-", …)`. Está em `tools/check_readme.py` |
| 12 | README fica mentindo depois de um `task all` novo | latência muda a cada rodada; a disciplina de reescrever à mão não se sustenta | `task check:readme`. Ele já pegou 3 divergências na primeira execução — inclusive uma criada pelo próprio commit que o introduziu (o script 09 virou o 10º e o README dizia 9) |

## Como interpretar os resultados

- **`starved_queries` não é qualidade, é cobertura.** É a coluna que separa
  "errou devolvendo pouco" (léxico) de "errou devolvendo qualquer coisa"
  (denso). Sem ela as duas falhas viram o mesmo hit@1 ruim e a conclusão sai
  invertida.
- **A média por estratégia esconde tudo.** Sempre leia a quebra por família: o
  denso faz 54,5% de hit@1 nas literais e 93,3% nas conceituais. A média (81,1%)
  não descreve nenhum dos dois comportamentos.
- **Fusão nem sempre ajuda.** Nas conceituais a fusão fica em 66,7% contra 93,3%
  do denso puro. Misturar motor ruim com motor bom dá pior que o bom.
- **Reranker não recupera.** Ele só reordena o prefetch (20). Documento fora
  dali é invisível. Medido: 5 promoções, 2 rebaixamentos, e hit@10 **cai** de
  100% para 97,3%.
- **Diferença de 1 consulta = 2,7 pontos.** Com 37 consultas e uma rodada só, não
  há intervalo de confiança. Não trate 2 pontos como vitória.
- **p50 do denso é quase todo HTTP para o Ollama**, não custo de algoritmo. Não
  compare 1,0 ms contra 113 ms como se fosse a mesma natureza de custo.
- **Latência oscila entre rodadas, qualidade não.** Duas rodadas do zero deram
  hit@k/MRR/famintas idênticos (`SEED = 17` fixa o corpus) e p50 variando ~6%.
  Ao reescrever o README depois de um `task all`, só as colunas de tempo mudam —
  se uma métrica de qualidade mudou, algo de verdade mudou, investigue.

## Ao mexer aqui

- Mudou o corpus, o gabarito ou qualquer `Settings`? → `task index` → `task verify`
  → `task eval` → `task experiments` → `task report`, nessa ordem, e **atualize os
  números do README**. Número velho num documento que se apresenta como exato é
  pior que número nenhum.
- Trocou `text_search_config` de `portuguese` para outro? Todo número léxico da
  PoC muda — o stemmer decide o que é "mesmo termo".
- Trocou o modelo denso? A dimensão é **medida** em `OllamaEmbedder.dim` e a
  coluna é recriada por `store.reset(dim)`; a checagem 4 do `verify` existe para
  pegar descompasso entre os dois.
- Acrescentou consulta ao `data/queries.yaml`? `corpus/queries.py` aborta se o
  `relevant` apontar para documento inexistente ou se a família for desconhecida
  — é de propósito, não contorne.
- Não versione `data/pg/`. É o datadir do Postgres.
