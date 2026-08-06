// A tela da PoC: quatro abas, uma pergunta cada.
//
//   Buscar        a mesma frase nas 6 estratégias, lado a lado
//   O que ficou   o que cada motor guardou de UM documento (lexema × vetor)
//   Placar        os números de `task all`, servidos como estão
//   Discordância  onde as estratégias divergiram, com id e texto
//
// Regra de linguagem, herdada do front da PoC de imagens: **nome em português
// na frente, identificador técnico no rodapé do cartão**. Quem não é da área
// não lê `ts_rank_cd` como "a busca que o Postgres já tem" — e a PoC existe
// para ser lida por quem vai decidir, não só por quem escreveu o SQL.

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowsLeftRight,
  Brain,
  Code,
  Hash,
  ListMagnifyingGlass,
  Ranking,
  Timer,
  Warning,
} from "@phosphor-icons/react";

import {
  fetchCode,
  fetchDisagreements,
  fetchDocument,
  fetchMeasured,
  fetchSearch,
  fetchState,
} from "./api.js";

const TABS = [
  { id: "search", label: "Buscar", icon: ListMagnifyingGlass },
  { id: "document", label: "O que ficou guardado", icon: Hash },
  { id: "score", label: "Placar medido", icon: Ranking },
  { id: "disagree", label: "Onde discordam", icon: ArrowsLeftRight },
];

// Famílias do gabarito, em ordem de leitura — literal primeiro porque é onde o
// vetor falha, e é o contraste que a tela quer mostrar antes de qualquer média.
const FAMILY_ORDER = ["literal", "conceptual", "hybrid"];
const FAMILY_NAME = {
  literal: "Literal",
  conceptual: "Conceitual",
  hybrid: "Híbrida",
};

const KIND_NAME = { record: "documento operacional", prose: "prosa (Wikipédia)" };

function useAsync(loader, deps) {
  const [state, setState] = useState({ status: "loading" });
  useEffect(() => {
    let alive = true;
    setState({ status: "loading" });
    loader()
      .then((data) => alive && setState({ status: "ok", data }))
      .catch((error) => alive && setState({ status: "error", error }));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return state;
}

function Loading({ what }) {
  return <p className="poc-muted">carregando {what}…</p>;
}

function Failed({ error }) {
  return (
    <div className="poc-alert">
      <Warning size={18} weight="bold" /> {String(error.message || error)}
    </div>
  );
}

/** Barra normalizada DENTRO da coluna — entre colunas não compara.
 *
 * BM25 vai de 1,5 a 28; cosseno vive entre 0,29 e 0,78; RRF soma frações de
 * 1/61. Desenhar as três na mesma escala produziria a leitura errada de que uma
 * "acertou mais" — que é exatamente o erro que a fusão min-max comete. */
function ScoreBar({ value, max }) {
  const pct = max > 0 ? Math.max(2, (value / max) * 100) : 0;
  return (
    <div className="poc-bar">
      <div className="poc-bar-fill" style={{ width: `${pct}%` }} />
    </div>
  );
}

function Verdict({ result, hasGroundTruth }) {
  if (!hasGroundTruth) {
    return <span className="poc-verdict poc-verdict-unknown">sem gabarito</span>;
  }
  if (result.first_relevant === 1) {
    return <span className="poc-verdict poc-verdict-good">acertou em 1º</span>;
  }
  if (result.first_relevant) {
    return (
      <span className="poc-verdict poc-verdict-mid">
        certo em {result.first_relevant}º
      </span>
    );
  }
  return <span className="poc-verdict poc-verdict-bad">não trouxe o certo</span>;
}

function CodePopup({ strategy, onClose }) {
  const tour = useAsync(() => fetchCode(strategy), [strategy]);
  return (
    <div className="poc-modal-backdrop" onClick={onClose}>
      <div className="poc-modal" onClick={(event) => event.stopPropagation()}>
        <header>
          <Code size={18} weight="bold" /> <strong>{strategy}</strong> — o código
          que rodou, lido do disco agora
          <button type="button" className="poc-close" onClick={onClose}>
            fechar
          </button>
        </header>
        {tour.status === "loading" && <Loading what="o código" />}
        {tour.status === "error" && <Failed error={tour.error} />}
        {tour.status === "ok" &&
          tour.data.blocks.map((block) => (
            <section key={block.symbol}>
              <p className="poc-note">{block.note}</p>
              <p className="poc-mono poc-muted">
                {block.file}:{block.first_line} · {block.lines} linhas
              </p>
              <pre>
                <code>{block.code}</code>
              </pre>
            </section>
          ))}
      </div>
    </div>
  );
}

function SearchTab({ state, onPickDocument }) {
  const [text, setText] = useState(state.queries[0]?.text ?? "");
  const [submitted, setSubmitted] = useState(state.queries[0]?.text ?? "");
  const [k, setK] = useState(5);
  const [showCode, setShowCode] = useState(null);

  const search = useAsync(
    () => (submitted ? fetchSearch(submitted, k) : Promise.resolve(null)),
    [submitted, k],
  );

  const byFamily = useMemo(() => {
    const out = {};
    for (const family of FAMILY_ORDER) {
      out[family] = state.queries.filter((query) => query.family === family);
    }
    return out;
  }, [state.queries]);

  return (
    <>
      <form
        className="poc-search"
        onSubmit={(event) => {
          event.preventDefault();
          setSubmitted(text.trim());
        }}
      >
        <input
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder="digite uma pergunta em português"
          aria-label="pergunta"
        />
        <label>
          top&nbsp;
          <select value={k} onChange={(event) => setK(Number(event.target.value))}>
            {[3, 5, 10].map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <button type="submit">buscar nas 6</button>
      </form>

      <div className="poc-suggestions">
        {FAMILY_ORDER.map((family) => (
          <div key={family}>
            <h4>
              {FAMILY_NAME[family]}{" "}
              <span className="poc-muted">
                — {byFamily[family][0]?.family_label}
              </span>
            </h4>
            <div className="poc-chips">
              {byFamily[family].slice(0, 6).map((query) => (
                <button
                  key={query.id}
                  type="button"
                  className={submitted === query.text ? "poc-chip poc-chip-on" : "poc-chip"}
                  onClick={() => {
                    setText(query.text);
                    setSubmitted(query.text);
                  }}
                >
                  {query.text}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>

      {search.status === "loading" && <Loading what="as 6 estratégias" />}
      {search.status === "error" && <Failed error={search.error} />}
      {search.status === "ok" && search.data && (
        <SearchResults
          data={search.data}
          strategies={state.strategies}
          onPickDocument={onPickDocument}
          onShowCode={setShowCode}
        />
      )}

      {showCode && <CodePopup strategy={showCode} onClose={() => setShowCode(null)} />}
    </>
  );
}

function SearchResults({ data, strategies, onPickDocument, onShowCode }) {
  return (
    <>
      <div className="poc-querybar">
        <span>
          <Brain size={16} weight="bold" /> o índice invertido leu sua pergunta
          como{" "}
          {data.query_lexemes.length ? (
            data.query_lexemes.map((lex) => (
              <code key={lex} className="poc-lex">
                {lex}
              </code>
            ))
          ) : (
            <strong className="poc-danger">nenhum lexema</strong>
          )}
        </span>
        <span className="poc-muted">
          {data.has_ground_truth
            ? `gabarito: ${data.relevant.join(", ")}`
            : "pergunta livre — sem gabarito, a tela não marca acerto"}
        </span>
      </div>

      <div className="poc-grid">
        {strategies.map((strategy) => {
          const result = data.results[strategy.name];
          if (!result) return null;
          const max = Math.max(...result.hits.map((hit) => hit.score), 0);
          return (
            <article key={strategy.name} className="poc-card">
              <header>
                <h3>{result.label}</h3>
                <Verdict result={result} hasGroundTruth={data.has_ground_truth} />
              </header>

              <p className="poc-metrics">
                <span>
                  <Timer size={14} weight="bold" /> {result.ms} ms
                </span>
                <span className={result.starved ? "poc-danger" : ""}>
                  {result.returned} de {data.k} resultados
                  {result.starved ? " — faminta" : ""}
                </span>
              </p>

              <ol className="poc-hits">
                {result.hits.map((hit) => (
                  <li
                    key={hit.doc_id}
                    className={
                      hit.relevant === true
                        ? "poc-hit poc-hit-good"
                        : hit.relevant === false
                          ? "poc-hit poc-hit-bad"
                          : "poc-hit"
                    }
                  >
                    <button type="button" onClick={() => onPickDocument(hit.doc_id)}>
                      <span className="poc-hit-title">{hit.title}</span>
                      <span className="poc-hit-meta">
                        <code>{hit.doc_id}</code> · {KIND_NAME[hit.kind] ?? hit.kind} ·{" "}
                        {hit.score}
                      </span>
                      <ScoreBar value={hit.score} max={max} />
                    </button>
                  </li>
                ))}
                {result.hits.length === 0 && (
                  <li className="poc-empty">
                    lista vazia — nenhum termo da pergunta existe no índice
                  </li>
                )}
              </ol>

              <footer>
                <code>{strategy.name}</code>
                {strategy.has_code_tour && (
                  <button type="button" onClick={() => onShowCode(strategy.name)}>
                    ver o código
                  </button>
                )}
              </footer>
            </article>
          );
        })}
      </div>
      <p className="poc-legend">
        A barra é normalizada <strong>dentro</strong> de cada coluna. Entre
        colunas não compara: BM25 devolve score sem teto, cosseno vive entre 0 e
        1, e RRF soma frações de 1/61 — somar isso sem normalizar é o defeito que
        a fusão min-max comete.
      </p>
    </>
  );
}

function DocumentTab({ state, docId, onPickDocument }) {
  const doc = useAsync(
    () => (docId ? fetchDocument(docId) : Promise.resolve(null)),
    [docId],
  );
  const maxIdf = useMemo(() => {
    if (doc.status !== "ok" || !doc.data) return 0;
    return Math.max(...doc.data.lexemes.map((row) => row.idf), 0);
  }, [doc]);

  return (
    <>
      <div className="poc-picker">
        <label>
          documento&nbsp;
          <select value={docId ?? ""} onChange={(event) => onPickDocument(event.target.value)}>
            {state.catalog.map((row) => (
              <option key={row.doc_id} value={row.doc_id}>
                {row.doc_id} — {row.title}
              </option>
            ))}
          </select>
        </label>
      </div>

      {doc.status === "loading" && <Loading what="o documento" />}
      {doc.status === "error" && <Failed error={doc.error} />}
      {doc.status === "ok" && doc.data && (
        <div className="poc-two">
          <section className="poc-panel">
            <h3>O que o índice invertido guardou</h3>
            <p className="poc-note">
              Lexema, não palavra: o stemmer de <code>{state.settings.text_search_config}</code>{" "}
              reduz “compressores” a “compressor”. <strong>tf</strong> é quantas vezes
              aparece aqui; <strong>df</strong>, em quantos documentos do corpus;{" "}
              <strong>IDF</strong> é o peso que o BM25 dá — e é a coluna que o{" "}
              <code>ts_rank_cd</code> não tem.
            </p>
            <table className="poc-table">
              <thead>
                <tr>
                  <th>lexema</th>
                  <th>tf</th>
                  <th>df</th>
                  <th>IDF</th>
                </tr>
              </thead>
              <tbody>
                {doc.data.lexemes.map((row) => (
                  <tr key={row.term}>
                    <td>
                      <code>{row.term}</code>
                    </td>
                    <td>{row.tf}</td>
                    <td>{row.df}</td>
                    <td>
                      {row.idf}
                      <ScoreBar value={row.idf} max={maxIdf} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section className="poc-panel">
            <h3>O que o vetor guardou</h3>
            <p className="poc-note">
              {doc.data.vector_dim} números, dos quais os 24 primeiros. Nenhum
              deles é uma palavra — e é por isso que{" "}
              <code>CNPJ 41.552.907/0001-33</code> e{" "}
              <code>…/0001-44</code> caem praticamente no mesmo ponto.
            </p>
            <div className="poc-vector">
              {doc.data.vector_preview.map((value, position) => {
                // Metade de cima e metade de baixo desenhadas separado, com a
                // linha do zero visível: sem ela, sinal vira só "cor diferente"
                // e a leitura de que metade dos números é negativa se perde.
                const size = `${Math.min(100, Math.abs(value) * 700)}%`;
                return (
                  <div key={position} className="poc-vector-cell" title={String(value)}>
                    <div className="poc-vector-half poc-vector-up">
                      {value >= 0 && <span style={{ height: size }} />}
                    </div>
                    <div className="poc-vector-half poc-vector-down">
                      {value < 0 && <span style={{ height: size }} />}
                    </div>
                  </div>
                );
              })}
            </div>
            <p className="poc-mono poc-muted">
              [{doc.data.vector_preview.slice(0, 8).join(", ")}, …]
            </p>

            <h4>Texto indexado</h4>
            <p className="poc-body">{doc.data.body}</p>
            <p className="poc-muted">
              <code>{doc.data.doc_id}</code> · {KIND_NAME[doc.data.kind] ?? doc.data.kind} ·
              fonte: {doc.data.source}
              {doc.data.in_ground_truth.length > 0 && (
                <> · é o alvo de {doc.data.in_ground_truth.join(", ")}</>
              )}
            </p>
          </section>
        </div>
      )}
    </>
  );
}

function ScoreTab() {
  const measured = useAsync(() => fetchMeasured(), []);
  if (measured.status === "loading") return <Loading what="os números medidos" />;
  if (measured.status === "error") return <Failed error={measured.error} />;

  const evaluation = measured.data.evaluation;
  if (!evaluation) {
    return <Failed error={new Error("sem results/evaluation.json — rode 'task eval'")} />;
  }
  const rows = evaluation.strategies ?? [];

  return (
    <>
      <p className="poc-note">
        Estes números saem de <code>results/evaluation.json</code>, gravado por{" "}
        <code>task eval</code>. A tela não recalcula nada — se um valor aqui
        divergir do <code>results/REPORT.md</code>, é bug.
      </p>
      <table className="poc-table poc-table-wide">
        <thead>
          <tr>
            <th>estratégia</th>
            <th>hit@1</th>
            <th>hit@3</th>
            <th>hit@10</th>
            <th>MRR@10</th>
            <th>p50</th>
            <th>p95</th>
            <th>famintas</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.strategy}>
              <td>
                <strong>{row.strategy}</strong>
                <br />
                <span className="poc-muted">{row.description}</span>
              </td>
              <td>{row.hit_at_1?.toFixed(4)}</td>
              <td>{row.hit_at_3?.toFixed(4)}</td>
              <td>{row.hit_at_10?.toFixed(4)}</td>
              <td>{row.mrr?.toFixed(4)}</td>
              <td>{row.query_ms_p50?.toFixed(1)} ms</td>
              <td>{row.query_ms_p95?.toFixed(1)} ms</td>
              <td className={row.starved_queries > 0 ? "poc-danger" : ""}>
                {row.starved_queries}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="poc-legend">
        <strong>Famintas não é qualidade, é cobertura</strong>: quantas das 37
        consultas voltaram com menos de 10 resultados. É a coluna que separa
        “errou devolvendo pouco” (léxico) de “errou devolvendo qualquer coisa”
        (denso). Sem ela, as duas falhas viram o mesmo hit@1 ruim.
      </p>
    </>
  );
}

function DisagreeTab({ onPickDocument }) {
  const data = useAsync(() => fetchDisagreements(), []);
  if (data.status === "loading") return <Loading what="as discordâncias" />;
  if (data.status === "error") return <Failed error={data.error} />;

  return (
    <>
      <p className="poc-note">
        A tabela de médias diz <em>quanto</em> cada estratégia errou; ela não diz{" "}
        <em>onde</em> — e onde é o que muda decisão. Cada bloco abaixo lê o{" "}
        <code>results/hits.json</code> da rodada medida.
      </p>
      {data.data.blocks.map((block) => (
        <section key={block.title} className="poc-panel">
          <h3>
            {block.title} <span className="poc-muted">({block.cases.length} de 37)</span>
          </h3>
          <p className="poc-note">{block.note}</p>
          <ul className="poc-cases">
            {block.cases.map((item) => (
              <li key={item.query_id}>
                <code>{item.query_id}</code>{" "}
                <span className="poc-muted">[{FAMILY_NAME[item.family] ?? item.family}]</span>
                <p>“{item.text}”</p>
                <span className="poc-ranks">
                  {["bm25", "dense", "rrf", "rrf_rerank"].map((name) => (
                    <span key={name}>
                      {name}:{" "}
                      <strong className={item[name]?.rank === 1 ? "poc-good" : ""}>
                        {item[name]?.rank ?? "fora"}
                      </strong>
                    </span>
                  ))}
                </span>
              </li>
            ))}
            {block.cases.length === 0 && <li className="poc-empty">nenhum caso</li>}
          </ul>
        </section>
      ))}
      <p className="poc-legend">
        Clique num documento na aba <strong>Buscar</strong> para ver o que cada
        motor guardou dele.{" "}
        <button type="button" className="poc-linkish" onClick={() => onPickDocument("ch_5506")}>
          ch_5506
        </button>{" "}
        é o alvo da consulta que os quatro modos de falha atingem de uma vez.
      </p>
    </>
  );
}

/** Aba e documento saem da URL (`?tab=score&doc=ch_5506`).
 *
 * Não é enfeite: sem isso não existe link para uma aba, e nenhuma ferramenta
 * que fotografa a tela consegue chegar às outras três — aba é estado de React,
 * não rota, e Chrome headless só sabe abrir URL. Foi o que dispensou um script
 * de CDP inteiro só para tirar print. */
function readUrl() {
  const params = new URLSearchParams(window.location.search);
  const tab = params.get("tab");
  return {
    tab: TABS.some((t) => t.id === tab) ? tab : "search",
    doc: params.get("doc"),
  };
}

export function App() {
  const initial = readUrl();
  const [tab, setTab] = useState(initial.tab);
  const [docId, setDocId] = useState(initial.doc);
  const state = useAsync(() => fetchState(), []);

  // `replaceState` e não `pushState`: trocar de aba não é navegação, e encher o
  // histórico faria o botão "voltar" do browser andar aba por aba.
  useEffect(() => {
    const params = new URLSearchParams();
    if (tab !== "search") params.set("tab", tab);
    if (docId) params.set("doc", docId);
    const query = params.toString();
    window.history.replaceState(null, "", query ? `?${query}` : window.location.pathname);
  }, [tab, docId]);

  const pickDocument = useCallback((id) => {
    setDocId(id);
    setTab("document");
  }, []);

  if (state.status === "loading") return <Loading what="a PoC" />;
  if (state.status === "error") return <Failed error={state.error} />;

  const data = state.data;
  const currentDoc = docId ?? data.catalog[0]?.doc_id ?? null;

  return (
    <div className="poc-app">
      <header className="poc-header">
        <div>
          <h1>Recuperação: as seis estratégias, na mesma máquina</h1>
          <p className="poc-muted">
            {data.corpus.total} documentos ({data.corpus.handwritten} escritos à
            mão + {data.corpus.wikipedia} distratores da Wikipédia) ·{" "}
            {data.queries.length} consultas com gabarito ·{" "}
            {data.lexical.distinct_terms} termos distintos · {data.settings.dim}{" "}
            dimensões ({data.settings.dense_model})
          </p>
        </div>
        <nav className="poc-tabs">
          {TABS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              type="button"
              className={tab === id ? "poc-tab poc-tab-on" : "poc-tab"}
              onClick={() => setTab(id)}
            >
              <Icon size={16} weight="bold" /> {label}
            </button>
          ))}
        </nav>
      </header>

      <main>
        {tab === "search" && <SearchTab state={data} onPickDocument={pickDocument} />}
        {tab === "document" && (
          <DocumentTab state={data} docId={currentDoc} onPickDocument={setDocId} />
        )}
        {tab === "score" && <ScoreTab />}
        {tab === "disagree" && <DisagreeTab onPickDocument={pickDocument} />}
      </main>

      <footer className="poc-footer">
        BM25 k1={data.settings.bm25_k1} b={data.settings.bm25_b} · RRF k=
        {data.settings.rrf_k} · prefetch {data.settings.prefetch_limit} · stemmer{" "}
        {data.settings.text_search_config} ·{" "}
        {data.indexes.map((index) => `${index.name} ${index.pretty}`).join(" · ")}
      </footer>
    </div>
  );
}
