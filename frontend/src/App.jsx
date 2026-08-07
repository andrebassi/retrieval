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
//
// Vale para o texto inteiro, não só para os títulos: cada aba abre dizendo o
// que a pessoa está vendo e por que aquilo importa, e todo jargão que sobra
// (hit@1, MRR, lexema, faminta) aparece com a tradução colada. O termo técnico
// não some — some a exigência de já saber o que ele significa para entender a
// tela.

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowsLeftRight,
  Brain,
  Code,
  Compass,
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
import { Failed, Loading, useAsync } from "./common.jsx";
import { AdviceTab, DEFAULT_SCENARIO } from "./Advice.jsx";

// A recomendação vem primeiro e é a aba de entrada. A pergunta que sobrou
// depois de tudo pronto foi “qual delas eu uso?” — se a resposta mora na quinta
// aba, ela não existe. As outras quatro passam a ser a evidência dela.
const TABS = [
  { id: "advice", label: "Qual devo usar?", icon: Compass },
  { id: "search", label: "Fazer uma pergunta", icon: ListMagnifyingGlass },
  { id: "document", label: "Como isso fica guardado", icon: Hash },
  { id: "score", label: "Quem acerta mais", icon: Ranking },
  { id: "disagree", label: "Onde elas discordam", icon: ArrowsLeftRight },
];
const DEFAULT_TAB = "advice";

// Famílias do gabarito, em ordem de leitura — literal primeiro porque é onde o
// vetor falha, e é o contraste que a tela quer mostrar antes de qualquer média.
const FAMILY_ORDER = ["literal", "conceptual", "hybrid"];
const FAMILY_NAME = {
  literal: "Perguntas com código",
  conceptual: "Perguntas com descrição",
  hybrid: "Perguntas com os dois",
};

const KIND_NAME = { record: "documento de trabalho", prose: "texto da Wikipédia" };
// `source` vem do corpus em inglês (é chave de dado, não texto de tela). A
// tradução mora aqui e não no back-end porque o valor também é usado como
// filtro; traduzir na origem quebraria a comparação.
const SOURCE_NAME = { handwritten: "escrito à mão", wikipedia: "Wikipédia" };

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
    return (
      <span className="poc-verdict poc-verdict-unknown" title="Ninguém definiu qual seria a resposta certa para esta pergunta, então a tela não tem como dizer se acertou.">
        pergunta nova
      </span>
    );
  }
  if (result.first_relevant === 1) {
    return <span className="poc-verdict poc-verdict-good">acertou de primeira</span>;
  }
  if (result.first_relevant) {
    return (
      <span className="poc-verdict poc-verdict-mid">
        achou, mas só em {result.first_relevant}º
      </span>
    );
  }
  return <span className="poc-verdict poc-verdict-bad">não achou</span>;
}

/** Como a opção funciona, e onde ela costuma acertar e errar.
 *
 * Fica fechado por padrão: quem já entendeu não quer ler de novo em seis
 * cartões, e quem não entendeu precisa que esteja ali, do lado do resultado —
 * não numa página de documentação que ninguém abre. `<details>` nativo em vez
 * de estado no React porque não há nada para sincronizar. */
function HowItWorks({ plain, startOpen }) {
  if (!plain) return null;
  return (
    <details className="poc-plain" open={startOpen}>
      <summary>como funciona, onde acerta, onde erra</summary>
      <p>{plain.how}</p>
      <p className="poc-plain-good">
        <strong>Vai bem quando:</strong> {plain.good}
      </p>
      <p className="poc-plain-bad">
        <strong>Falha quando:</strong> {plain.bad}
      </p>
    </details>
  );
}

function CodePopup({ strategy, onClose }) {
  const tour = useAsync(() => fetchCode(strategy), [strategy]);
  return (
    <div className="poc-modal-backdrop" onClick={onClose}>
      <div className="poc-modal" onClick={(event) => event.stopPropagation()}>
        <header>
          <Code size={18} weight="bold" /> <strong>{strategy}</strong> — o trecho
          de código que fez esta busca, lido do arquivo agora
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

function SearchTab({ state, explain, onPickDocument }) {
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
      <p className="poc-intro">
        Escreva uma pergunta — ou clique numa das prontas abaixo. Ela vai para as
        seis formas de buscar <strong>ao mesmo tempo</strong>, e cada uma devolve
        a sua lista. Onde as listas ficam diferentes é onde a escolha do motor
        muda o que a pessoa vê.
      </p>

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
          mostrar&nbsp;
          <select value={k} onChange={(event) => setK(Number(event.target.value))}>
            {[3, 5, 10].map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
          &nbsp;por lista
        </label>
        <button type="submit">perguntar às 6</button>
      </form>

      <p className="poc-note">
        As perguntas prontas têm <strong>resposta certa definida à mão</strong> —
        por isso a tela consegue dizer quem acertou. Numa pergunta digitada por
        você ninguém sabe qual era a resposta esperada, então os resultados
        aparecem sem nota.
      </p>

      <div className="poc-suggestions">
        {FAMILY_ORDER.map((family) => (
          <div key={family}>
            {/* O nome curto vai em caixa alta, como todo rótulo de seção da
                tela; a explicação NÃO — frase inteira em caixa alta é mais
                lenta de ler, e essa é a linha que precisa ser entendida por
                quem chegou agora. */}
            <h4>
              {FAMILY_NAME[family]}
              <span className="poc-family-hint">
                {" "}— {byFamily[family][0]?.family_label}
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
          explain={explain}
          onPickDocument={onPickDocument}
          onShowCode={setShowCode}
        />
      )}

      {showCode && <CodePopup strategy={showCode} onClose={() => setShowCode(null)} />}
    </>
  );
}

function SearchResults({ data, strategies, explain, onPickDocument, onShowCode }) {
  return (
    <>
      <div className="poc-querybar">
        <span>
          <Brain size={16} weight="bold" /> a busca por palavra reduziu sua
          pergunta a estes pedaços{" "}
          {data.query_lexemes.length ? (
            data.query_lexemes.map((lex) => (
              <code key={lex} className="poc-lex">
                {lex}
              </code>
            ))
          ) : (
            <strong className="poc-danger">
              nenhum — ela não tem nada para procurar
            </strong>
          )}
        </span>
        <span className="poc-muted">
          {data.has_ground_truth
            ? `resposta certa: ${data.relevant.join(", ")}`
            : "pergunta sua — sem resposta certa definida, a tela não dá nota"}
        </span>
      </div>
      <p className="poc-note">
        Palavras como “o”, “de”, “está” somem, e o resto vira raiz: “compressores”
        e “compressor” viram a mesma coisa. A busca por palavra só enxerga o que
        sobrou aqui — se a sua pergunta não tem nenhum pedaço em comum com o
        documento, ela não tem como achá-lo. Já a busca por significado não passa
        por esta etapa.
      </p>

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

              <HowItWorks plain={strategy.plain} startOpen={explain} />

              <p className="poc-metrics">
                <span title="tempo que esta busca levou para responder">
                  <Timer size={14} weight="bold" /> {result.ms} ms
                </span>
                <span
                  className={result.starved ? "poc-danger" : ""}
                  title={
                    result.starved
                      ? "Devolveu menos do que você pediu: não é que ordenou mal, é que não tinha o que ordenar."
                      : "Devolveu a lista cheia."
                  }
                >
                  {result.returned} de {data.k} pedidos
                  {result.starved ? " — voltou incompleta" : ""}
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
                      {/* “nota” em vez do número solto: cada motor pontua na
                          escala dele — 0,52 aqui e 4,25 ao lado não se comparam.
                          O que compara entre cartões é a POSIÇÃO na lista, e a
                          barra é normalizada dentro da própria coluna. */}
                      <span
                        className="poc-hit-meta"
                        title="Nota dada por esta busca. Só vale para comparar dentro desta coluna — cada forma de buscar pontua na sua própria escala."
                      >
                        <code>{hit.doc_id}</code> · {KIND_NAME[hit.kind] ?? hit.kind} · nota{" "}
                        {hit.score}
                      </span>
                      <ScoreBar value={hit.score} max={max} />
                    </button>
                  </li>
                ))}
                {result.hits.length === 0 && (
                  <li className="poc-empty">
                    Não devolveu nada: nenhuma palavra da sua pergunta aparece em
                    documento nenhum. Repare que isto <strong>parece</strong> um
                    defeito — e é assim que ele avisa. A busca por significado, no
                    lugar dela, devolveria dez palpites errados sem avisar nada.
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
        <strong>Verde</strong> é a resposta certa, <strong>vermelho</strong> é
        errado, e a barrinha mostra a confiança daquela busca naquele resultado.
        A barra só se compara <strong>dentro</strong> de uma mesma lista: cada
        forma de buscar dá nota numa escala própria, e uma nota 28 aqui pode
        valer menos que uma nota 0,7 ali. Comparar as barras entre colunas é
        exatamente o erro que a opção “somando notas” comete.
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
      <p className="poc-intro">
        Escolha um documento e veja o que o computador guardou dele — porque não
        é o texto. São <strong>duas</strong> cópias, e cada busca usa uma. É daqui
        que vêm todos os acertos e erros das outras abas.
      </p>

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
            <h3>Cópia 1 — a lista de palavras</h3>
            <p className="poc-note">
              O texto vira uma lista de palavras sem terminação: “compressores”
              e “compressor” viram a mesma entrada, e “o”, “de”, “para” são
              jogados fora. É esta lista que a busca por palavra consulta —
              palavra que não está aqui, ela não acha.
            </p>
            <p className="poc-note">
              <strong>aqui</strong> = quantas vezes a palavra aparece neste
              documento. <strong>em quantos</strong> = em quantos dos{" "}
              {state.corpus.total} documentos ela aparece.{" "}
              <strong>peso</strong> = o quanto ela ajuda a identificar este
              documento. Repare na relação: quanto <em>menos</em> documentos têm
              a palavra, <em>mais</em> ela pesa — palavra que está em todo lugar
              não distingue nada. Essa conta é a diferença entre as duas buscas
              por palavra: a simples não a faz.
            </p>
            <table className="poc-table">
              <thead>
                <tr>
                  <th>palavra guardada</th>
                  <th>aqui</th>
                  <th>em quantos</th>
                  <th>peso</th>
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
            <h3>Cópia 2 — a lista de números</h3>
            <p className="poc-note">
              O mesmo texto, lido por um modelo de linguagem, vira{" "}
              {doc.data.vector_dim} números. Abaixo, os 24 primeiros — barra para
              cima é positivo, para baixo é negativo. <strong>Nenhum</strong>{" "}
              deles é uma palavra: eles descrevem o <em>assunto</em>. Documentos
              que falam da mesma coisa terminam com números parecidos, mesmo
              escritos com palavras diferentes. É o que faz a busca por
              significado achar sinônimo — e é o mesmo motivo de ela confundir{" "}
              <code>CNPJ …/0001-33</code> com <code>…/0001-44</code>: para ela,
              os dois textos falam do mesmo assunto.
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

            <h4>O texto de verdade, do qual as duas cópias saíram</h4>
            <p className="poc-body">{doc.data.body}</p>
            <p className="poc-muted">
              <code>{doc.data.doc_id}</code> · {KIND_NAME[doc.data.kind] ?? doc.data.kind} ·
              fonte: {SOURCE_NAME[doc.data.source] ?? doc.data.source}
              {doc.data.in_ground_truth.length > 0 && (
                <>
                  {" "}
                  · é a resposta certa de {doc.data.in_ground_truth.join(", ")}
                </>
              )}
            </p>
          </section>
        </div>
      )}
    </>
  );
}

function ScoreTab({ labels }) {
  const measured = useAsync(() => fetchMeasured(), []);
  if (measured.status === "loading") return <Loading what="os números medidos" />;
  if (measured.status === "error") return <Failed error={measured.error} />;

  const evaluation = measured.data.evaluation;
  if (!evaluation) {
    return <Failed error={new Error("sem results/evaluation.json — rode 'task eval'")} />;
  }
  const rows = evaluation.strategies ?? [];

  // `%` em vez de 0,8108: quem lê a tela quer saber que acertou 8 de cada 10,
  // não a fração. Os quatro decimais continuam no `results/evaluation.json`,
  // que é a fonte para quem for conferir.
  const pct = (value) => (value == null ? "—" : `${(value * 100).toFixed(1)}%`);

  return (
    <>
      <p className="poc-intro">
        As mesmas 37 perguntas passaram pelas seis formas de buscar. Cada linha é
        uma forma; cada coluna, uma pergunta diferente sobre o desempenho dela.
        Nenhum número aqui é calculado na hora — todos vêm da medição gravada em
        disco, e é a mesma que está no relatório do projeto.
      </p>
      <table className="poc-table poc-table-wide">
        <thead>
          <tr>
            <th>forma de buscar</th>
            <th>
              acertou de primeira
              <br />
              <span className="poc-th-tech">hit@1</span>
            </th>
            <th>
              apareceu no top 3
              <br />
              <span className="poc-th-tech">hit@3</span>
            </th>
            <th>
              apareceu no top 10
              <br />
              <span className="poc-th-tech">hit@10</span>
            </th>
            <th>
              posição típica
              <br />
              <span className="poc-th-tech">MRR@10</span>
            </th>
            <th>
              tempo comum
              <br />
              <span className="poc-th-tech">p50</span>
            </th>
            <th>
              tempo ruim
              <br />
              <span className="poc-th-tech">p95</span>
            </th>
            <th>
              voltou incompleta
              <br />
              <span className="poc-th-tech">de 37</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.strategy}>
              {/* Nome em pt-BR primeiro, identificador embaixo: é a mesma
                  ordem dos cartões da aba de busca. Com o identificador na
                  frente, ninguém liga a linha `rrf_rerank` ao cartão “As duas
                  juntas + um revisor” que acabou de ver. */}
              <td>
                <strong>{labels[row.strategy] ?? row.strategy}</strong>
                <br />
                <span className="poc-muted">
                  <code>{row.strategy}</code> — {row.description}
                </span>
              </td>
              <td>{pct(row.hit_at_1)}</td>
              <td>{pct(row.hit_at_3)}</td>
              <td>{pct(row.hit_at_10)}</td>
              <td>{row.mrr?.toFixed(2)}</td>
              <td>{row.query_ms_p50?.toFixed(1)} ms</td>
              <td>{row.query_ms_p95?.toFixed(1)} ms</td>
              <td className={row.starved_queries > 0 ? "poc-danger" : ""}>
                {row.starved_queries}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="poc-legend">
        <p>
          <strong>Acertou de primeira</strong> é quantas vezes o documento certo
          veio em 1º lugar. <strong>Apareceu no top 3 / no top 10</strong> é
          quantas vezes ele veio em algum lugar da lista — útil quando a pessoa
          vai ler alguns resultados, e não só o primeiro.
        </p>
        <p>
          <strong>Posição típica</strong> resume em um número onde o certo
          costuma cair: 1,00 seria sempre em 1º; 0,50, tipicamente em 2º; 0,33,
          em 3º. <strong>Tempo comum</strong> é o que metade das perguntas levou
          ou menos; <strong>tempo ruim</strong> é o que só as 5% mais lentas
          passaram.
        </p>
        <p>
          <strong>Voltou incompleta</strong> é a coluna mais importante e a que
          quase todo comparativo esquece: quantas das 37 perguntas receberam
          menos resultados do que se pediu. Ela separa dois fracassos que a nota
          de acerto trata como iguais — “devolveu pouco”, que a pessoa percebe e
          reclama, e “devolveu dez coisas erradas com cara de certas”, que
          ninguém percebe.
        </p>
      </div>
    </>
  );
}

function DisagreeTab({ labels, onPickDocument }) {
  const data = useAsync(() => fetchDisagreements(), []);
  if (data.status === "loading") return <Loading what="as discordâncias" />;
  if (data.status === "error") return <Failed error={data.error} />;

  return (
    <>
      <p className="poc-intro">
        O placar diz <em>quantas</em> cada uma errou. Ele não diz{" "}
        <em>quais</em> — e é isso que muda a decisão. Aqui estão as perguntas em
        que elas discordaram, com o número que cada uma deu ao documento certo:{" "}
        <strong>1</strong> é primeiro lugar, e <strong>fora</strong> quer dizer
        que aquela busca não trouxe o documento certo de jeito nenhum.
      </p>
      {data.data.blocks.map((block) => (
        <section key={block.title} className="poc-panel">
          <h3>
            {block.title}{" "}
            <span className="poc-muted">
              ({block.cases.length} de 37 perguntas)
            </span>
          </h3>
          <p className="poc-note">{block.note}</p>
          <ul className="poc-cases">
            {block.cases.map((item) => (
              <li key={item.query_id}>
                <code>{item.query_id}</code>{" "}
                <span className="poc-muted">[{FAMILY_NAME[item.family] ?? item.family}]</span>
                <p>“{item.text}”</p>
                {/* Nome em pt-BR aqui também. Quatro identificadores soltos
                    numa linha era a parte da tela em que ninguém de fora sabia
                    o que estava comparando com o quê. */}
                <span className="poc-ranks">
                  {["bm25", "dense", "rrf", "rrf_rerank"].map((name) => (
                    <span key={name} title={name}>
                      {labels?.[name] ?? name}:{" "}
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
        Um mesmo caso pode aparecer em dois blocos — são quatro jeitos de errar,
        não quatro grupos separados de perguntas. O documento{" "}
        <button type="button" className="poc-linkish" onClick={() => onPickDocument("ch_5506")}>
          ch_5506
        </button>{" "}
        vale a visita: ele é a resposta certa da pergunta que sofre os quatro
        problemas de uma vez.
      </p>
    </>
  );
}

/** Aba, documento e explicações saem da URL
 * (`?tab=score&doc=ch_5506`, `?explain=1`).
 *
 * Não é enfeite: sem isso não existe link para uma aba, e nenhuma ferramenta
 * que fotografa a tela consegue chegar às outras três — aba é estado de React,
 * não rota, e Chrome headless só sabe abrir URL. Foi o que dispensou um script
 * de CDP inteiro só para tirar print.
 *
 * `explain=1` abre os seis blocos “como funciona” de uma vez. Serve para mandar
 * o link já explicado a quem nunca viu a tela — e, de quebra, é a única forma
 * de o print pegar o conteúdo dobrado, que fechado ninguém confere. */
function readUrl() {
  const params = new URLSearchParams(window.location.search);
  const tab = params.get("tab");
  return {
    tab: TABS.some((t) => t.id === tab) ? tab : DEFAULT_TAB,
    doc: params.get("doc"),
    explain: params.get("explain") === "1",
    // As três respostas do escolhedor também são estado de URL, pelo mesmo
    // motivo da aba: sem isso, "olha o que ele recomenda para o seu caso" não
    // tem link, e o print só consegue fotografar o cenário inicial. Quem valida
    // é a aba, contra o payload — aqui só se lê a string.
    scenario: {
      reader: params.get("reader") ?? DEFAULT_SCENARIO.reader,
      budget: params.get("budget") ?? DEFAULT_SCENARIO.budget,
      kind: params.get("kind") ?? DEFAULT_SCENARIO.kind,
    },
  };
}

export function App() {
  // Estado, não chamada solta: `readUrl()` a cada render lia uma URL que o
  // próprio efeito abaixo já tinha reescrito. Como os cartões só aparecem
  // depois da busca, `explain` chegava neles sempre falso — a tela abria
  // fechada e o print de `?explain=1` mostrava o mesmo que o normal.
  const [initial] = useState(readUrl);
  const [tab, setTab] = useState(initial.tab);
  const [docId, setDocId] = useState(initial.doc);
  const [scenario, setScenario] = useState(initial.scenario);
  const state = useAsync(() => fetchState(), []);

  // `replaceState` e não `pushState`: trocar de aba não é navegação, e encher o
  // histórico faria o botão "voltar" do browser andar aba por aba.
  useEffect(() => {
    const params = new URLSearchParams();
    if (tab !== DEFAULT_TAB) params.set("tab", tab);
    if (docId) params.set("doc", docId);
    // `explain` sobrevive à troca de aba: quem recebeu o link já explicado
    // espera continuar explicado ao clicar em outra aba e voltar.
    if (initial.explain) params.set("explain", "1");
    // Só o que difere do padrão entra na URL — senão a barra de endereço abre
    // com três parâmetros que ninguém escolheu, e o link "limpo" deixa de existir.
    for (const [field, value] of Object.entries(scenario)) {
      if (value !== DEFAULT_SCENARIO[field]) params.set(field, value);
    }
    const query = params.toString();
    window.history.replaceState(null, "", query ? `?${query}` : window.location.pathname);
  }, [tab, docId, initial.explain, scenario]);

  const pickDocument = useCallback((id) => {
    setDocId(id);
    setTab("document");
  }, []);

  if (state.status === "loading") return <Loading what="a PoC" />;
  if (state.status === "error") return <Failed error={state.error} />;

  const data = state.data;
  const currentDoc = docId ?? data.catalog[0]?.doc_id ?? null;
  // O nome em pt-BR de cada estratégia vem do back-end (uma fonte só). As abas
  // de placar e de discordância trabalham sobre o JSON medido, que só conhece o
  // identificador — este mapa é o que liga um ao outro.
  const strategyLabels = Object.fromEntries(
    data.strategies.map((strategy) => [strategy.name, strategy.label]),
  );

  return (
    <div className="poc-app">
      <header className="poc-header">
        <div>
          <h1>Seis formas de achar um documento, comparadas lado a lado</h1>
          {/* Uma frase, e ela diz o que o visitante ganha — não o que é um
              sistema de busca. A versão anterior abria explicando a natureza do
              problema ("todo sistema responde à mesma pergunta…") em quatro
              linhas, e quem lê já sabe disso: o que ele não sabe é qual das seis
              usar, que é justamente o que a primeira aba responde. */}
          <p className="poc-lede">
            As seis respondem às mesmas {data.queries.length} perguntas, sobre o
            mesmo acervo, nesta máquina. Elas erram em perguntas{" "}
            <em>diferentes</em> — e é isso que dá para ver aqui.
          </p>
          {/* Três fichas, não uma linha corrida. Os mesmos números viviam numa
              frase só, com parêntese dentro de parêntese e `·` separando
              assuntos que não têm relação entre si — o olho não achava onde uma
              informação terminava e a outra começava. Separadas, cada uma se lê
              em um segundo. */}
          <ul className="poc-facts">
            <li>
              <b>{data.corpus.total} documentos</b>
              <span>
                {data.corpus.handwritten} escritos à mão ·{" "}
                {data.corpus.wikipedia} da Wikipédia, só para atrapalhar
              </span>
            </li>
            <li>
              <b>{data.queries.length} perguntas</b>
              <span>cada uma com a resposta certa definida antes</span>
            </li>
            <li>
              <b>tudo local</b>
              <span>nada sai desta máquina</span>
            </li>
          </ul>
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
        {tab === "advice" && (
          <AdviceTab scenario={scenario} onScenario={setScenario} />
        )}
        {tab === "search" && (
          <SearchTab state={data} explain={initial.explain} onPickDocument={pickDocument} />
        )}
        {tab === "document" && (
          <DocumentTab state={data} docId={currentDoc} onPickDocument={setDocId} />
        )}
        {tab === "score" && <ScoreTab labels={strategyLabels} />}
        {tab === "disagree" && (
          <DisagreeTab labels={strategyLabels} onPickDocument={pickDocument} />
        )}
      </main>

      <footer className="poc-footer">
        <span className="poc-footer-tag">para quem é da área:</span> BM25 k1=
        {data.settings.bm25_k1} b={data.settings.bm25_b} · RRF k={data.settings.rrf_k} ·
        prefetch {data.settings.prefetch_limit} · stemmer{" "}
        {data.settings.text_search_config} · {data.settings.dim} dimensões (
        {data.settings.dense_model}) · {data.lexical.distinct_terms} termos
        distintos ·{" "}
        {data.indexes.map((index) => `${index.name} ${index.pretty}`).join(" · ")}
      </footer>
    </div>
  );
}
