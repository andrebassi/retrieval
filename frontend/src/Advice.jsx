// O escolhedor, em formato de torneio: quatro rodadas, seis competidoras, e um
// placar que nunca sai da tela.
//
// Duas versões morreram antes desta. A primeira punha as três perguntas lado a
// lado e o resultado embaixo — funcionava para quem já sabia o que cada pergunta
// significava, e essa pessoa não precisa da aba. A segunda virou assistente, uma
// pergunta por tela, com um desenho ao lado: melhor, mas ainda **inerte**. Quem
// respondia não via nada acontecer com as seis; via três telas e uma resposta.
//
// O que faltava era o placar. Aqui as seis entram como competidoras e ficam
// visíveis o tempo todo, à direita, em todas as rodadas:
//
//   1. **a régua** troca e o placar se remonta (ninguém sai, todas as notas mudam);
//   2. **o relógio** derruba quem estoura o tempo, antes de a nota ser olhada;
//   3. **o tipo de pergunta** vira a mesa: quem liderava despenca, e o de-para
//      da posição aparece escrito;
//   4. **o mata-mata** decide o empate, um critério por vez, e coroa a campeã.
//
// Cada rodada narra o que acabou de acontecer (`RoundFlash`) — movimento sem
// legenda é enfeite, e enfeite é o que esta tela não pode ser. O desenho de cada
// passo continua: ele mostra a consequência **antes** do clique, o placar mostra
// a consequência **depois**.
//
// Por que `motion` e não Remotion: Remotion renderiza **vídeo** (React → MP4);
// o que ela embute no browser é um player, que não reage a clique. Aqui a
// animação precisa responder ao cursor, ao estado da URL e à reordenação do
// placar (o `layout` do `motion` faz FLIP sozinho), então a ferramenta certa é
// uma lib de animação de UI. Remotion caberia num vídeo de abertura — que é
// outro pedido, não este.

import { useEffect, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import {
  ArrowLeft,
  ArrowRight,
  ArrowsClockwise,
  CheckCircle,
  Crown,
  Warning,
  XCircle,
} from "@phosphor-icons/react";

import { fetchAdvice } from "./api.js";
import { Failed, Loading, useAsync } from "./common.jsx";
import { MoveList, RoundFlash, Scoreboard, Tiebreak } from "./Game.jsx";

// O cenário mais comum de verdade: alguém clicou em buscar, lê o primeiro
// resultado, e as perguntas misturam código com descrição.
export const DEFAULT_SCENARIO = { reader: "first", budget: "click", kind: "hybrid" };

// Os passos são posição na URL (`?step=2`), não índice interno: sem isso não há
// link para "a tela que explica o orçamento de tempo", e o print só alcança o
// primeiro passo.
export const STEP_IDS = ["reader", "budget", "kind", "result"];
export const DEFAULT_STEP = 0;

const STEP_TITLE = {
  reader: "Quem lê o resultado?",
  budget: "Quanto tempo dá para esperar?",
  kind: "Como são as perguntas?",
  result: "A recomendação",
};
const STEP_SHORT = { reader: "quem lê", budget: "tempo", kind: "perguntas", result: "resposta" };
const STEP_NOTE = {
  reader:
    "Isto troca a régua. Acertar de primeira e ter o certo em algum lugar dos dez são metas diferentes — e a opção que ganha numa perde na outra.",
  budget:
    "Isto elimina candidatas antes de comparar nota. Quem não responde no prazo sai da disputa, mesmo acertando mais.",
  kind:
    "Isto é o que a média esconde. As mesmas seis mudam de posição conforme o tipo de pergunta — é aqui que a tabela geral engana.",
  result: "Calculada com os números medidos, sem opinião no meio.",
};

// O que cada rodada faz com as seis. É o que separa "responda três perguntas" de
// "jogue quatro rodadas": a pessoa sabe, antes de responder, se a resposta vai
// **remontar** o placar, **eliminar** alguém ou **virar a mesa**.
const ROUND_TAG = {
  reader: { n: 1, of: 4, verb: "remonta o placar", tone: "swap" },
  budget: { n: 2, of: 4, verb: "elimina por tempo", tone: "cut" },
  kind: { n: 3, of: 4, verb: "vira a mesa", tone: "swap" },
  result: { n: 4, of: 4, verb: "decide a campeã", tone: "win" },
};

// As caixinhas do desenho “o que eu monto, afinal”. O back-end devolve só os
// nomes das etapas; o texto de cada uma mora aqui porque é texto de tela.
const STAGE = {
  lexical: { title: "Busca por palavra", note: "acha o que está escrito, letra por letra" },
  dense: { title: "Busca por significado", note: "acha o assunto, mesmo dito com outras palavras" },
  fusion: { title: "Juntar as listas", note: "soma as posições, não as notas" },
  rerank: { title: "Revisor", note: "relê os 20 primeiros junto com a pergunta" },
};

// Frase de exemplo por tipo de pergunta. Sai daqui e não do corpus de propósito:
// é ilustração de tela, e uma consulta real do gabarito traria o ruído de "por
// que justo essa?" no meio de uma explicação que não é sobre ela.
const KIND_EXAMPLE = {
  literal: "P-101 com vazamento no selo mecânico",
  conceptual: "bomba fazendo barulho estranho quando esquenta",
  hybrid: "P-101 fazendo barulho depois da troca",
};

/** Posição do documento certo no desenho do passo 1, contando de 1.
 *
 * Terceiro lugar é o único valor que faz as três réguas discordarem entre si —
 * com ele, “lê só o primeiro” reprova a mesma lista que “passa o olho em três”
 * aprova. Em 1º as três concordam, em 5º duas concordam, e o desenho perde a
 * razão de existir. */
const TARGET_SLOT = 3;
const SLOTS = 10;
const READER_DEPTH = { first: 1, few: 3, llm: 10 };

const pct = (value) => `${(value * 100).toFixed(1)}%`;

/** Escala logarítmica da régua de tempo do passo 2.
 *
 * Linear é inútil aqui: os p50 vão de 0,5 ms a 600 ms, então as quatro opções
 * baratas viram um borrão colado no zero e a régua deixa de mostrar justamente
 * a diferença que ela existe para mostrar — que 0,5 ms e 120 ms não são "quase
 * igual", são 240 vezes. */
const TIME_MAX = 700;
const timeX = (ms) => (Math.log10(1 + Math.max(0, ms)) / Math.log10(1 + TIME_MAX)) * 100;

/** O desenho do passo 1: uma lista de dez resultados e o holofote da régua.
 *
 * `hover` deixa espiar a consequência sem gastar o clique — quem passa o cursor
 * em “um robô lê os dez” vê o holofote descer até o fim antes de decidir. */
function ReaderDemo({ readers, value, preview }) {
  const active = preview ?? value;
  const depth = READER_DEPTH[active] ?? 1;
  const hit = TARGET_SLOT <= depth;
  const row = readers.find((item) => item.id === active);
  const reduced = useReducedMotion();
  const spring = reduced
    ? { duration: 0 }
    : { type: "spring", stiffness: 260, damping: 26 };

  return (
    <div className="poc-demo">
      <p className="poc-demo-cap">
        A lista que a busca devolveu. O documento certo caiu em{" "}
        <strong>{TARGET_SLOT}º</strong> lugar — o que muda é só{" "}
        <strong>até onde alguém olha</strong>.
      </p>
      <div className="poc-slots">
        <motion.div
          className="poc-slot-light"
          animate={{ height: `calc(${depth} * var(--slot-h) + ${depth - 1} * var(--slot-gap))` }}
          transition={spring}
          aria-hidden="true"
        />
        {Array.from({ length: SLOTS }, (_, index) => {
          const place = index + 1;
          const isTarget = place === TARGET_SLOT;
          const seen = place <= depth;
          return (
            <motion.div
              key={place}
              className={
                isTarget ? "poc-slot poc-slot-target" : "poc-slot"
              }
              animate={{ opacity: seen ? 1 : 0.3 }}
              transition={spring}
            >
              <span className="poc-slot-n">{place}º</span>
              <span className="poc-slot-bar" style={{ width: `${88 - index * 6}%` }} />
              {isTarget && <span className="poc-slot-tag">o documento certo</span>}
            </motion.div>
          );
        })}
      </div>
      <AnimatePresence mode="wait">
        <motion.p
          key={active}
          className={hit ? "poc-demo-verdict poc-good" : "poc-demo-verdict poc-bad"}
          initial={reduced ? false : { opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={reduced ? undefined : { opacity: 0, y: -6 }}
          transition={{ duration: reduced ? 0 : 0.18 }}
        >
          {hit ? <CheckCircle size={18} weight="fill" /> : <XCircle size={18} weight="fill" />}
          {/* Dizer a régua no meio da frase ("com esta régua — acertou de
           * primeira — a lista conta como erro") lia como se ELA tivesse
           * acertado, com um ✗ vermelho do lado. A frase agora começa pelo que
           * dá para ver no desenho e só depois nomeia a régua. */}
          Olhando até o <strong>{depth}º</strong>, o documento em {TARGET_SLOT}º{" "}
          {hit ? "aparece" : "fica de fora"} — pela régua “{row.metric_label}”,{" "}
          {hit ? "conta como acerto" : "conta como erro"}.
        </motion.p>
      </AnimatePresence>
    </div>
  );
}

/** O desenho do passo 2: as seis na régua de tempo, e o corte do orçamento.
 *
 * O ponto é ver a eliminação acontecer: quem está à direita do corte apaga. É a
 * diferença entre "escolha um limite de tempo" e "estas quatro deixam de existir
 * se você escolher este limite". */
function BudgetDemo({ budgets, strategies, value, preview }) {
  const active = preview ?? value;
  const row = budgets.find((item) => item.id === active);
  const reduced = useReducedMotion();
  const spring = reduced ? { duration: 0 } : { type: "spring", stiffness: 220, damping: 28 };
  const alive = strategies.filter((s) => s.p50 <= row.ms).length;

  return (
    <div className="poc-demo">
      <p className="poc-demo-cap">
        Onde cada uma cai no relógio. A escala é logarítmica — de outro jeito as
        quatro baratas viram um borrão colado no zero.
      </p>
      <div className="poc-ruler">
        <motion.div
          className="poc-ruler-ok"
          animate={{ width: `${timeX(row.ms)}%` }}
          transition={spring}
          aria-hidden="true"
        />
        <motion.div
          className="poc-ruler-cut"
          animate={{ left: `${timeX(row.ms)}%` }}
          transition={spring}
        >
          <span>{row.ms} ms</span>
        </motion.div>
        {[1, 10, 100, 700].map((tick) => (
          <span
            key={tick}
            // O último tick fica em 100% e, centrado, sairia metade para fora da
            // régua: quebrava "700 ms" em duas linhas na borda. Depois de 92% o
            // rótulo passa a se pendurar pela direita.
            className={timeX(tick) > 92 ? "poc-ruler-tick poc-ruler-tick-end" : "poc-ruler-tick"}
            style={{ left: `${timeX(tick)}%` }}
          >
            {tick} ms
          </span>
        ))}
      </div>
      <ul className="poc-dots">
        {strategies.map((strategy) => {
          const fits = strategy.p50 <= row.ms;
          const x = timeX(strategy.p50);
          // Nome à direita do ponto é o natural — até o ponto estar perto do
          // fim. O reranker cai em ~96% da régua, e o nome dele saía cortado
          // pela borda ("As duas juntas + um reviso"). Passado o meio, o nome
          // vira para o outro lado e o ponto continua marcando o lugar certo.
          const flip = x > 58;
          return (
            <motion.li
              key={strategy.name}
              className={
                (fits ? "poc-dot" : "poc-dot poc-dot-out") + (flip ? " poc-dot-flip" : "")
              }
              style={{ left: `${x}%` }}
              animate={{ opacity: fits ? 1 : 0.32, y: fits ? 0 : 6 }}
              transition={spring}
              title={`${strategy.label} — ${strategy.p50.toFixed(1)} ms`}
            >
              <span className="poc-dot-pin" />
              <span className="poc-dot-name">{strategy.label}</span>
            </motion.li>
          );
        })}
      </ul>
      <AnimatePresence mode="wait">
        <motion.p
          key={active}
          className={alive > 1 ? "poc-demo-verdict poc-good" : "poc-demo-verdict poc-bad"}
          initial={reduced ? false : { opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={reduced ? undefined : { opacity: 0, y: -6 }}
          transition={{ duration: reduced ? 0 : 0.18 }}
        >
          {alive > 1 ? <CheckCircle size={18} weight="fill" /> : <Warning size={18} weight="fill" />}
          Com {row.ms} ms, <strong>{alive} das {strategies.length}</strong> continuam na
          disputa — as outras saem antes de a nota ser olhada.
        </motion.p>
      </AnimatePresence>
    </div>
  );
}

/** O desenho do passo 3: as mesmas duas buscas, notas trocadas pelo tipo.
 *
 * É a tese inteira da PoC num gráfico: palavra ganha no código, significado
 * ganha na descrição, e a barra da fusão nunca desaba em nenhum dos dois. */
function KindDemo({ strategies, value, preview, queries }) {
  const active = preview ?? value;
  const reduced = useReducedMotion();
  const byName = Object.fromEntries(strategies.map((s) => [s.name, s]));
  const shown = ["bm25", "dense", "rrf"].map((name) => byName[name]).filter(Boolean);
  const best = Math.max(...shown.map((s) => s.by_family[active]));
  const worst = Math.min(...shown.map((s) => s.by_family[active]));
  // Em pontos percentuais, que é a unidade da faixa de ruído — a mesma que o
  // resultado usa para dizer quem está empatado.
  const gap = (best - worst) * 100;

  return (
    <div className="poc-demo">
      <p className="poc-demo-cap">
        Uma pergunta deste tipo é assim:
        <AnimatePresence mode="wait">
          <motion.strong
            key={active}
            className="poc-demo-quote"
            initial={reduced ? false : { opacity: 0, x: 8 }}
            animate={{ opacity: 1, x: 0 }}
            exit={reduced ? undefined : { opacity: 0, x: -8 }}
            transition={{ duration: reduced ? 0 : 0.18 }}
          >
            “{KIND_EXAMPLE[active]}”
          </motion.strong>
        </AnimatePresence>
      </p>
      <ul className="poc-vs">
        {shown.map((strategy, index) => {
          const score = strategy.by_family[active];
          return (
            <li key={strategy.name} className={score === best ? "poc-vs-row poc-vs-top" : "poc-vs-row"}>
              <span className="poc-vs-name">{strategy.label}</span>
              <span className="poc-vs-track">
                <motion.span
                  className="poc-vs-fill"
                  initial={reduced ? false : { width: 0 }}
                  animate={{ width: `${score * 100}%` }}
                  transition={
                    reduced
                      ? { duration: 0 }
                      : { type: "spring", stiffness: 120, damping: 20, delay: index * 0.08 }
                  }
                />
              </span>
              <span className="poc-vs-value">{pct(score)}</span>
            </li>
          );
        })}
      </ul>
      {/* Repetir aqui o `row.hint` era repetir a frase de exemplo que já está
        * em laranja no topo. O que falta dizer é o tamanho da diferença: é ela
        * que a média geral esconde. */}
      <p className="poc-demo-cap poc-muted">
        Acerto de primeira nas {queries[active]} perguntas deste tipo —{" "}
        {gap < 0.1 ? (
          <>as três empatam aqui</>
        ) : (
          <>
            <strong>{gap.toFixed(1)} pontos</strong> separam a melhor da pior
          </>
        )}
        .
      </p>
    </div>
  );
}

/** O desenho do que a recomendação manda montar, com o pedido percorrendo ele.
 *
 * As duas buscas ficam empilhadas de propósito: elas rodam **ao mesmo tempo**, e
 * desenhá-las em fila daria a entender que uma espera a outra — que é
 * exatamente a leitura errada de por que a fusão custa 115 ms e não 230. A
 * bolinha que corre pelas setas existe para dizer qual é a direção do fluxo;
 * seta parada já foi lida como "isso volta". */
function AnimatedPipeline({ stages }) {
  const parallel = stages.filter((stage) => stage === "lexical" || stage === "dense");
  const serial = stages.filter((stage) => stage !== "lexical" && stage !== "dense");
  const reduced = useReducedMotion();

  const box = (stage, index) => (
    <motion.div
      className={`poc-pipe-box poc-pipe-${stage}`}
      initial={reduced ? false : { opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={reduced ? { duration: 0 } : { delay: 0.1 + index * 0.12, duration: 0.28 }}
    >
      <strong>{STAGE[stage].title}</strong>
      <span>{STAGE[stage].note}</span>
    </motion.div>
  );

  const arrow = (delay) => (
    <span className="poc-pipe-arrow" aria-hidden="true">
      {!reduced && (
        <motion.span
          className="poc-pipe-dot"
          animate={{ x: [0, 26, 26], opacity: [0, 1, 0] }}
          transition={{ duration: 1.4, repeat: Infinity, delay, ease: "easeInOut" }}
        />
      )}
    </span>
  );

  return (
    <div className="poc-pipe" aria-label="desenho do que montar">
      <div className="poc-pipe-col">{parallel.map((stage, i) => <div key={stage}>{box(stage, i)}</div>)}</div>
      {serial.map((stage, index) => (
        <div key={stage} className="poc-pipe-step">
          {arrow(index * 0.3)}
          {box(stage, parallel.length + index)}
        </div>
      ))}
      <div className="poc-pipe-step">
        {arrow(serial.length * 0.3)}
        <motion.div
          className="poc-pipe-box poc-pipe-out"
          initial={reduced ? false : { opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={reduced ? { duration: 0 } : { delay: 0.1 + stages.length * 0.12, duration: 0.28 }}
        >
          <strong>a lista que a pessoa vê</strong>
        </motion.div>
      </div>
    </div>
  );
}

/** As opções do passo, com espiada no `hover`. */
function Options({ options, value, onChange, onPreview }) {
  return (
    <div className="poc-choice-options">
      {options.map((option) => (
        <button
          key={option.id}
          type="button"
          className={value === option.id ? "poc-opt poc-opt-on" : "poc-opt"}
          aria-pressed={value === option.id}
          onClick={() => onChange(option.id)}
          onMouseEnter={() => onPreview(option.id)}
          onMouseLeave={() => onPreview(null)}
          onFocus={() => onPreview(option.id)}
          onBlur={() => onPreview(null)}
        >
          <strong>{option.label}</strong>
          <span>{option.hint}</span>
        </button>
      ))}
    </div>
  );
}

/** A trilha das quatro rodadas. Clicável para trás e para as já jogadas: o jogo
 * guia, não prende — e as três respostas já vêm preenchidas com o cenário mais
 * comum, então "avançar" nunca está bloqueado.
 *
 * Cada item diz o que a rodada **faz** ("elimina por tempo"), não só o nome dela.
 * Sem isso a trilha é um índice; com isso ela é a regra do jogo, e quem chega no
 * passo 2 já sabe que vai perder competidoras. */
function StepTrack({ step, onStep, chosen }) {
  return (
    <ol className="poc-track">
      {STEP_IDS.map((id, index) => (
        <li key={id} className={index === step ? "poc-track-on" : "poc-track-item"}>
          <button type="button" onClick={() => onStep(index)} aria-current={index === step}>
            <span className="poc-track-num">{index + 1}</span>
            <span className="poc-track-text">
              <strong>{STEP_SHORT[id]}</strong>
              <span>{chosen[id] ?? "—"}</span>
              <em className="poc-track-verb">{ROUND_TAG[id].verb}</em>
            </span>
          </button>
        </li>
      ))}
    </ol>
  );
}

export function AdviceTab({ explain, scenario, onScenario, step, onStep }) {
  const advice = useAsync(() => fetchAdvice(), []);
  // A espiada é estado local, não da URL: é gesto de cursor, não escolha. Subir
  // isso para a URL faria o link mudar ao passar o mouse.
  const [preview, setPreview] = useState(null);
  // Qual linha do placar está aberta. Mora aqui, e não dentro do placar, porque o
  // placar é remontado a cada rodada — estado interno dele fecharia o detalhe
  // toda vez que a pessoa respondesse, justo quando ela está comparando duas.
  const [open, setOpen] = useState(null);
  const reduced = useReducedMotion();

  // Seta do teclado anda entre os passos. Num assistente isso é esperado, e sai
  // barato — mas só fora de campo de texto, senão a seta que move o cursor
  // dentro da caixa de busca trocaria a tela debaixo de quem está digitando.
  useEffect(() => {
    const onKey = (event) => {
      const tag = document.activeElement?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || event.metaKey || event.altKey) return;
      if (event.key === "ArrowRight") onStep(step + 1);
      if (event.key === "ArrowLeft") onStep(step - 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [step, onStep]);

  if (advice.status === "loading") return <Loading what="a recomendação" />;
  if (advice.status === "error") return <Failed error={advice.error} />;

  const data = advice.data;
  // A URL é digitável, então pode trazer id inventado — e um `?reader=xpto`
  // acharia `undefined` no grid e derrubaria a aba inteira. Quem diz o que
  // existe é o payload, não o front.
  const valid = (rows, id, fallback) => (rows.some((row) => row.id === id) ? id : fallback);
  const reader = valid(data.readers, scenario.reader, DEFAULT_SCENARIO.reader);
  const budget = valid(data.budgets, scenario.budget, DEFAULT_SCENARIO.budget);
  const kind = valid(data.kinds, scenario.kind, DEFAULT_SCENARIO.kind);
  const current = Math.min(Math.max(step, 0), STEP_IDS.length - 1);
  const stepId = STEP_IDS[current];

  const answer = (field) => (id) => {
    onScenario({ reader, budget, kind, [field]: id });
    setPreview(null);
    // Responder avança. A trilha continua clicável para trás, então ninguém
    // fica preso — mas obrigar um clique em "avançar" depois de já ter
    // respondido é pedir duas ações para uma decisão.
    onStep(Math.min(current + 1, STEP_IDS.length - 1));
  };

  const key = `${reader}|${budget}|${kind}`;
  const pick = data.grid[key];
  const byName = Object.fromEntries(data.strategies.map((row) => [row.name, row]));
  const readerRow = data.readers.find((row) => row.id === reader);
  const kindRow = data.kinds.find((row) => row.id === kind);

  // O placar de cada rodada. As duas primeiras vêm prontas do back-end em mapas
  // próprios; as duas últimas saem da célula do grid — a rodada 4 não recalcula
  // nada, ela só para de esconder o desempate que já estava ali.
  const roundReader = data.rounds.reader[reader];
  const roundBudget = data.rounds.budget[`${reader}|${budget}`];
  const board =
    stepId === "reader"
      ? roundReader.board
      : stepId === "budget"
        ? roundBudget.board
        : pick.ranked;
  const flash =
    stepId === "reader"
      ? roundReader.headline
      : stepId === "budget"
        ? roundBudget.headline
        : stepId === "kind"
          ? pick.swap
          : pick.why;
  // O rótulo diz **sobre o quê** é a nota que está na tela, e ele muda no meio do
  // jogo: nas duas primeiras rodadas ainda é a média das perguntas todas, porque
  // o tipo só é escolhido na rodada 3. Sem dizer isso, o placar da rodada 2
  // pareceria já valer para o cenário — e a virada da rodada 3 viraria bug.
  const boardMetric =
    stepId === "reader" || stepId === "budget"
      ? `${readerRow.metric_label} · média das ${data.queries.total} perguntas`
      : `${readerRow.metric_label} · perguntas do tipo “${kindRow.label}”`;
  const base = byName[data.default.base];
  const upgrade = byName[data.default.upgrade];
  const risky = byName[data.default.avoid_alone];
  const chosen = {
    reader: data.readers.find((row) => row.id === reader).label,
    budget: data.budgets.find((row) => row.id === budget).label,
    kind: data.kinds.find((row) => row.id === kind).label,
    result: pick.winner ? byName[pick.winner].label : "nenhuma cabe",
  };

  const slide = reduced
    ? {}
    : {
        initial: { opacity: 0, x: 24 },
        animate: { opacity: 1, x: 0 },
        exit: { opacity: 0, x: -24 },
        transition: { duration: 0.22, ease: "easeOut" },
      };

  return (
    <>
      {/* Duas linhas, não cinco: a tese inteira cabe aqui, e o resto dela está
        * no `<details>` do rodapé. Texto de abertura longo empurra o jogo para
        * fora da primeira tela, e aí a rodada 1 nasce sem ser vista. */}
      <p className="poc-intro">
        Seis competidoras, quatro rodadas. Elas erram mais ou menos a mesma
        quantidade — só que em perguntas diferentes, então <em>quem ganha depende
        do que você responder</em>. O placar à direita se mexe a cada resposta, e
        a linha em laranja diz por quê.
      </p>

      <StepTrack step={current} onStep={onStep} chosen={chosen} />

      <div className="poc-game">
        <div className="poc-game-main">
          <div className="poc-step-frame">
            <AnimatePresence mode="wait">
              <motion.section key={stepId} className="poc-step" {...slide}>
                <header className="poc-step-head">
                  <p className="poc-round-tag">
                    rodada {ROUND_TAG[stepId].n} de {ROUND_TAG[stepId].of} ·{" "}
                    <strong>{ROUND_TAG[stepId].verb}</strong>
                  </p>
                  <h3>{STEP_TITLE[stepId]}</h3>
                  <p className="poc-note">{STEP_NOTE[stepId]}</p>
                </header>

                {/* A narração da rodada. Fica ACIMA das opções e não abaixo do
                  * desenho: ela conta o que a resposta anterior fez com o placar,
                  * e a pessoa lê isso antes de escolher de novo — depois do
                  * desenho, ela já teria decidido. */}
                <RoundFlash
                  text={flash}
                  tone={ROUND_TAG[stepId].tone}
                  icon={stepId === "result" ? Crown : undefined}
                />

                {stepId === "reader" && (
                  <div className="poc-step-body">
                    <Options
                      options={data.readers}
                      value={reader}
                      onChange={answer("reader")}
                      onPreview={setPreview}
                    />
                    <ReaderDemo readers={data.readers} value={reader} preview={preview} />
                  </div>
                )}

                {stepId === "budget" && (
                  <div className="poc-step-body">
                    <Options
                      options={data.budgets}
                      value={budget}
                      onChange={answer("budget")}
                      onPreview={setPreview}
                    />
                    <BudgetDemo
                      budgets={data.budgets}
                      strategies={data.strategies}
                      value={budget}
                      preview={preview}
                    />
                  </div>
                )}

                {stepId === "kind" && (
                  <div className="poc-step-body">
                    <Options
                      options={data.kinds}
                      value={kind}
                      onChange={answer("kind")}
                      onPreview={setPreview}
                    />
                    <div className="poc-step-stack">
                      <KindDemo
                        strategies={data.strategies}
                        value={kind}
                        preview={preview}
                        queries={data.queries}
                      />
                      {/* O de-para das posições. Ele é o argumento inteiro da
                        * rodada: sem "do 1º para o 5º" escrito, o placar ao lado
                        * se remonta e a pessoa lê como se as notas tivessem só
                        * mudado de valor. */}
                      <MoveList moved={pick.moved} />
                    </div>
                  </div>
                )}

                {stepId === "result" && (
                  /* Coluna única: o placar saiu daqui e virou a barra lateral do
                   * jogo, presente nas quatro rodadas. O que sobra à esquerda é a
                   * campeã, o caminho dela e o mata-mata que a coroou — a
                   * resposta à pergunta "por que essa e não a de cima". */
                  <div className="poc-outcome">
                    {/* O desenho vem PRIMEIRO, e na largura inteira. Espremido ao
                      * lado do cartão ele quebrava em três linhas e passava de
                      * 260 px; empurrado para o fim, era o primeiro a sair da
                      * tela — justo ele, que é a única parte visual da resposta. */}
                    {pick.winner && (
                      <div className="poc-outcome-flow">
                        <AnimatedPipeline stages={pick.pipeline} />
                      </div>
                    )}

                    {pick.winner ? (
                      <motion.div
                        className="poc-winner"
                        initial={reduced ? false : { opacity: 0, y: 12 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ duration: reduced ? 0 : 0.3 }}
                      >
                        <span className="poc-winner-tag">
                          <Crown size={13} weight="fill" /> campeã
                        </span>
                        <h3>{byName[pick.winner].label}</h3>
                        <code>{pick.winner}</code>
                        {/* "O que a derruba" saiu daqui de propósito: ele é a
                          * terceira linha do detalhe que abre ao clicar na linha
                          * da campeã, no placar ao lado. Repetido nos dois
                          * lugares custava 40 px — e 40 px eram a sexta linha do
                          * placar saindo da tela. */}
                        <p className="poc-winner-needs">
                          <strong>Precisa de:</strong> {byName[pick.winner].trait.needs} ·{" "}
                          <strong>Ajuste:</strong> {byName[pick.winner].trait.tuning}
                        </p>
                      </motion.div>
                    ) : (
                      <div className="poc-alert">
                        <Warning size={18} weight="bold" /> {pick.why}
                      </div>
                    )}

                    {/* O mata-mata, um critério por vez. É aqui que "por que
                      * ganhou" deixa de ser uma frase e passa a ser uma sequência
                      * que acontece na tela — e a resposta quase nunca é "acerta
                      * mais", é um critério de engenharia dentro de um empate. */}
                    {pick.winner && pick.tiebreak.length > 0 && (
                      <>
                        <h4 className="poc-tb-title">
                          {pick.tied.length} empatam dentro de{" "}
                          <strong>{data.band_points} pontos</strong> — o mata-mata:
                        </h4>
                        <Tiebreak
                          steps={pick.tiebreak}
                          winnerLabel={byName[pick.winner].label}
                        />
                      </>
                    )}
                    {/* Sem mata-mata quando ninguém entrou na faixa junto com a
                      * campeã. Dizer isso é melhor que calar: o silêncio no lugar
                      * onde nas outras rodadas há um mata-mata lê como tela
                      * quebrada, e o caso "ganhou pela nota, sem empate" é o
                      * único em que a nota decide sozinha. */}
                    {pick.winner && pick.tiebreak.length === 0 && (
                      <p className="poc-tb-skip">
                        Sem mata-mata: nenhuma outra chegou a menos de{" "}
                        <strong>{data.band_points} pontos</strong> da campeã, então a
                        nota decidiu sozinha.
                      </p>
                    )}

                    {pick.notes.map((note) => (
                      <p key={note} className="poc-warnline">
                        <Warning size={16} weight="bold" /> {note}
                      </p>
                    ))}

                    <p className="poc-legend">
                      O selo <em>empatada</em> no placar vale{" "}
                      <strong>{data.band_points} pontos</strong>, que é o que{" "}
                      <strong>uma única pergunta</strong> vale com{" "}
                      {data.queries.total} perguntas medidas. Quem cai dentro dessa
                      faixa não está atrás da campeã: está empatado. Toda comparação de
                      busca que você ler por aí ignora essa faixa — e é por isso que
                      tanta gente troca de motor para ganhar dois pontos que não
                      existem.
                    </p>

                    {/* Dobrado: é a saída de quem não quer jogar as rodadas, e
                      * quem chegou até aqui já jogou. Aberto, empurrava o desenho
                      * do caminho para fora da tela. */}
                    <details className="poc-answer">
                      <summary>E se eu não quiser responder nada disso</summary>
                      <ol className="poc-answer-list">
                        <li>
                          <strong>Comece pela fusão por posição</strong> (
                          <code>{base.name}</code>) — “{base.label}”. Traz a lista cheia
                          nas {data.queries.total} perguntas, põe o documento certo entre
                          os dez em {pct(base.hit_at_10)} delas, responde em{" "}
                          {base.p50.toFixed(0)} ms e <em>não tem nada para calibrar</em>.
                        </li>
                        <li>
                          <strong>Ligue o revisor</strong> (<code>{upgrade.name}</code>) só
                          quando o primeiro resultado for o que a pessoa lê: ele sobe o
                          acerto de primeira de {pct(base.hit_at_1)} para{" "}
                          {pct(upgrade.hit_at_1)}, e cobra {upgrade.p50.toFixed(0)} ms no
                          lugar de {base.p50.toFixed(0)} ms.
                        </li>
                        <li>
                          <strong>Nunca use a busca por significado sozinha.</strong> Na
                          média ela parece boa ({pct(risky.hit_at_1)}), mas nas perguntas
                          com código acerta {pct(risky.by_family.literal)} — erra quase
                          metade, e erra confiante.
                        </li>
                      </ol>
                    </details>
                  </div>
                )}
              </motion.section>
            </AnimatePresence>
          </div>

          <nav className="poc-steps-nav">
            <button
              type="button"
              className="poc-nav-btn"
              onClick={() => onStep(Math.max(current - 1, 0))}
              disabled={current === 0}
            >
              <ArrowLeft size={16} weight="bold" /> voltar
            </button>
            <span className="poc-nav-where">
              rodada {current + 1} de {STEP_IDS.length}
            </span>
            {current < STEP_IDS.length - 1 ? (
              <button
                type="button"
                className="poc-nav-btn poc-nav-go"
                onClick={() => onStep(current + 1)}
              >
                avançar <ArrowRight size={16} weight="bold" />
              </button>
            ) : (
              <button type="button" className="poc-nav-btn" onClick={() => onStep(0)}>
                <ArrowsClockwise size={16} weight="bold" /> jogar de novo
              </button>
            )}
          </nav>
        </div>

        {/* O placar. Nunca sai da tela — é ele que transforma três perguntas num
          * jogo, porque é onde a resposta vira consequência visível. */}
        <Scoreboard
          rows={board}
          phase={stepId}
          winner={pick.winner}
          tied={pick.tied}
          podium={pick.podium}
          metricLabel={boardMetric}
          byName={byName}
          bandPoints={data.band_points}
          open={open}
          onOpen={setOpen}
        />
      </div>

      <details className="poc-plain" open={explain}>
        <summary>por que não existe “a melhor” — leia antes de discordar</summary>
        <p>
          A tabela de médias resolve a pergunta errada. Ela responde “qual acerta
          mais no geral”, e ninguém tem um sistema “no geral”: seu sistema tem um
          tipo de pergunta que aparece toda hora e um jeito específico de mostrar
          o resultado. A média de {pct(risky.hit_at_1)} da busca por significado é a
          média entre acertar {pct(risky.by_family.conceptual)} nas descrições e{" "}
          {pct(risky.by_family.literal)} nos códigos — e não descreve nenhuma das
          duas situações.
        </p>
        <p className="poc-plain-good">
          <strong>O que transfere para o seu projeto:</strong> a forma das curvas.
          Palavra ganha no código, significado ganha na descrição, e juntar as duas
          não perde feio em nenhum dos dois. Isso vale em qualquer acervo.
        </p>
        <p className="poc-plain-bad">
          <strong>O que NÃO transfere:</strong> os números. São{" "}
          {data.queries.total} perguntas escritas para esta comparação, sobre um
          acervo pequeno. Meça no seu — o mesmo código que roda aqui roda lá, e é
          exatamente para isso que esta PoC existe.
        </p>
      </details>
    </>
  );
}
