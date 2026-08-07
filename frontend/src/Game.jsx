// O placar do torneio, e as peças que o fazem parecer um jogo.
//
// A versão anterior era um assistente correto e morto: três perguntas, resposta
// no fim. Quem respondia não via **nada acontecer** — e o que esta PoC tem de
// interessante é justamente que as seis trocam de lugar conforme a pergunta.
//
// Aqui as seis entram como competidoras e ficam na tela o tempo todo, à direita,
// em todos os passos. Cada resposta mexe no placar na frente de quem respondeu:
// a régua remonta as notas (rodada 1), o relógio derruba competidoras da mesa
// (rodada 2), o tipo de pergunta vira a mesa do avesso (rodada 3) e o empate vai
// para o mata-mata (rodada 4). A explicação vem junto do movimento, não depois
// dele — é a diferença entre ler "o denso cai nas literais" e ver a linha do
// denso despencar quatro posições.
//
// Nada aqui inventa número: o backend devolve cada rodada pronta em
// `/api/advice` (`rounds.reader`, `rounds.budget`, `grid[...].tiebreak`), pelo
// mesmo motivo de sempre — dois lugares calculando a mesma coisa é um lugar
// mentindo mais cedo ou mais tarde.

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { Crown, Prohibit, Timer, TrendDown, TrendUp } from "@phosphor-icons/react";

const pct = (value) => `${(value * 100).toFixed(1)}%`;

/** Molas do placar.
 *
 * `layout` do `motion` anima a troca de posição sozinho (mede antes, mede depois
 * e interpola). É o efeito que faz o placar parecer vivo — e é exatamente o que
 * não dá para fazer à mão sem reimplementar FLIP. */
const useSprings = () => {
  const reduced = useReducedMotion();
  return {
    reduced,
    layout: reduced ? { duration: 0 } : { type: "spring", stiffness: 320, damping: 34 },
    bar: reduced ? { duration: 0 } : { type: "spring", stiffness: 130, damping: 22 },
  };
};

const MEDAL = ["🥇", "🥈", "🥉"];

/** O placar ao vivo — a única coisa que nunca sai da tela.
 *
 * `rows` já vem ordenado pelo backend; o componente não reordena nada, só
 * desenha. Ordenar aqui abriria a porta para a tela contradizer o motivo do
 * desempate, que é a armadilha 24 de novo.
 */
export function Scoreboard({
  rows,
  phase,
  winner,
  tied = [],
  podium = [],
  metricLabel,
  byName,
  bandPoints,
  open,
  onOpen,
}) {
  const { reduced, layout, bar } = useSprings();
  const live = rows.filter((row) => !row.eliminated).length;
  const final = phase === "result";

  return (
    <aside className="poc-board">
      <header className="poc-board-head">
        <h4>Placar ao vivo</h4>
        <p className="poc-board-count">
          {final && winner ? (
            <>
              <Crown size={14} weight="fill" /> campeã definida
            </>
          ) : (
            <>
              <strong>{live}</strong> de {rows.length} na mesa
            </>
          )}
        </p>
      </header>
      {/* O que a faixa vale é dito UMA vez, aqui, e não repetido em cada linha
          empatada: com quatro empatadas o mesmo “a menos de 2,7 pontos” aparecia
          quatro vezes na mesma coluna e virava textura, não informação. */}
      <p className="poc-board-metric">
        {metricLabel}
        {final && tied.length > 1 && (
          <> · empate = diferença menor que {bandPoints} pontos</>
        )}{" "}
        · <em>clique numa competidora para ver o que ela exige</em>
      </p>

      <ol className="poc-board-list">
        {rows.map((row, index) => {
          const isWinner = final && row.name === winner;
          // Empate é conclusão da rodada 4, e só dela: `tied` fala da nota do tipo
          // de pergunta escolhido. Marcado antes disso, o selo aparecia já na
          // rodada 1, ao lado de uma nota que é a média geral — dizendo que duas
          // estratégias empatam num número que nem é o do cenário.
          const isTied = final && !isWinner && tied.includes(row.name);
          const place = podium.findIndex((item) => item.name === row.name);
          const isOpen = open === row.name;
          const trait = byName?.[row.name]?.trait;
          const state = row.eliminated
            ? "poc-bl poc-bl-out"
            : isWinner
              ? "poc-bl poc-bl-win"
              : isTied
                ? "poc-bl poc-bl-tie"
                : "poc-bl";
          return (
            <motion.li key={row.name} layout transition={layout} className={state}>
              <button
                type="button"
                className="poc-bl-hit"
                aria-expanded={isOpen}
                /* O nome longo é cortado com reticências para caber numa linha —
                 * o `title` devolve o nome inteiro sem custar altura. */
                title={`${row.label} (${row.name}) — ${row.p50.toFixed(1)} ms`}
                onClick={() => onOpen(isOpen ? null : row.name)}
              >
                <span className="poc-bl-seat">
                  {final && place >= 0 && place < 3 ? MEDAL[place] : index + 1}
                </span>
                <span className="poc-bl-name">{byName?.[row.name]?.short ?? row.label}</span>
                {/* A faixa listrada de empate das outras telas NÃO cabe aqui: a
                    faixa vale 2,7 pontos e o track tem 74 px, ou seja, 2 px de
                    listra — decoração que ninguém enxerga fingindo ser
                    informação. Neste placar quem carrega o empate é o selo
                    "empatada" na linha, que diz a mesma coisa e é legível. */}
                <span className="poc-bl-track">
                  <motion.span
                    className="poc-bl-fill"
                    initial={reduced ? false : { width: 0 }}
                    animate={{ width: `${row.value * 100}%` }}
                    transition={bar}
                  />
                </span>
                <span className="poc-bl-value">{pct(row.value)}</span>
                {row.eliminated ? (
                  <span className="poc-bl-flag poc-bl-flag-out">
                    <Prohibit size={12} weight="bold" /> fora
                  </span>
                ) : isWinner ? (
                  <span className="poc-bl-flag poc-bl-flag-win">
                    <Crown size={12} weight="fill" /> campeã
                  </span>
                ) : isTied ? (
                  <span
                    className="poc-bl-flag poc-bl-flag-tie"
                    title={`Dentro de ${bandPoints} pontos da campeã — a diferença cabe numa pergunta`}
                  >
                    empatada
                  </span>
                ) : (
                  <span className="poc-bl-flag poc-bl-flag-ms">{row.p50.toFixed(1)} ms</span>
                )}
              </button>
              <AnimatePresence initial={false}>
                {isOpen && trait && (
                  <motion.div
                    className="poc-bl-detail"
                    initial={reduced ? false : { height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={reduced ? undefined : { height: 0, opacity: 0 }}
                    transition={{ duration: reduced ? 0 : 0.22 }}
                  >
                    <p>
                      <strong>Precisa de:</strong> {trait.needs}
                    </p>
                    <p>
                      <strong>Ajuste:</strong> {trait.tuning}
                    </p>
                    <p>
                      <strong>O que a derruba:</strong> {trait.risk}
                    </p>
                    {row.eliminated && row.reason && (
                      <p className="poc-bl-detail-out">
                        <Prohibit size={12} weight="bold" /> Fora nesta rodada: {row.reason}
                      </p>
                    )}
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.li>
          );
        })}
      </ol>
    </aside>
  );
}

/** A narração do que a resposta acabou de fazer com o placar.
 *
 * Fica colada no topo do passo, e troca com a resposta. Sem ela o placar se
 * mexe e ninguém sabe por quê — movimento sem legenda é enfeite, e enfeite é o
 * que esta tela não pode ser. */
export function RoundFlash({ text, tone = "info", icon }) {
  const { reduced } = useSprings();
  const Icon = icon ?? (tone === "cut" ? Timer : tone === "swap" ? TrendDown : TrendUp);
  return (
    <AnimatePresence mode="wait">
      <motion.p
        key={text}
        className={`poc-flash poc-flash-${tone}`}
        initial={reduced ? false : { opacity: 0, y: -6 }}
        animate={{ opacity: 1, y: 0 }}
        exit={reduced ? undefined : { opacity: 0, y: 6 }}
        transition={{ duration: reduced ? 0 : 0.2 }}
      >
        <Icon size={16} weight="bold" />
        <span>{text}</span>
      </motion.p>
    </AnimatePresence>
  );
}

/** As trocas de posição da rodada 3, listadas com o de-para.
 *
 * "As notas mudaram" não é notícia; "o denso caiu do 1º para o 5º e perdeu 26,6
 * pontos" é. O componente só aparece quando alguém de fato se moveu — em cenário
 * sem troca, uma caixa vazia dizendo "nada mudou" ocupa a altura que o placar
 * precisa. */
export function MoveList({ moved }) {
  const { reduced } = useSprings();
  if (!moved.length) return null;
  const shown = moved.slice(0, 3);
  return (
    <ul className="poc-moves">
      {shown.map((item, index) => {
        const up = item.to < item.from;
        return (
          <motion.li
            key={item.name}
            className={up ? "poc-move poc-move-up" : "poc-move poc-move-down"}
            initial={reduced ? false : { opacity: 0, x: up ? -10 : 10 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: reduced ? 0 : 0.24, delay: reduced ? 0 : index * 0.08 }}
          >
            {up ? <TrendUp size={14} weight="bold" /> : <TrendDown size={14} weight="bold" />}
            <strong>{item.label}</strong>
            <span>
              {item.from}º → {item.to}º
            </span>
            <em>
              {pct(item.was)} → {pct(item.value)}
            </em>
          </motion.li>
        );
      })}
    </ul>
  );
}

/** O mata-mata do desempate: um critério por vez, quem passou e quem caiu.
 *
 * Este é o coração do "por que ela ganhou". A vencedora quase nunca vence por
 * acertar mais — ela vence por critério de engenharia dentro de um empate que a
 * nota não resolve. Antes isso era uma frase de três linhas que ninguém lia; aqui
 * é uma sequência que acontece na tela, e cada etapa diz o que estava em jogo.
 *
 * As etapas nascem todas no DOM, com atraso escalonado, e não atrás de um botão
 * "próximo": atrás do botão, o print pega só a primeira, e o texto que ninguém
 * fotografa é o texto que envelhece errado. */
export function Tiebreak({ steps, winnerLabel }) {
  const { reduced } = useSprings();
  if (!steps.length) return null;

  return (
    <ol className="poc-tb">
      {steps.map((step, index) => (
        <motion.li
          key={step.id}
          className={step.decided ? "poc-tb-step" : "poc-tb-step poc-tb-flat"}
          initial={reduced ? false : { opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: reduced ? 0 : 0.3, delay: reduced ? 0 : 0.25 + index * 0.35 }}
        >
          <div className="poc-tb-head">
            <span className="poc-tb-n">{index + 1}</span>
            <strong>{step.title}</strong>
            <span className="poc-tb-count">
              {step.entered.length} → {step.passed.length}
            </span>
          </div>
          <p className="poc-tb-why">{step.why}</p>
          {step.out.length > 0 ? (
            <ul className="poc-tb-out">
              {step.out.map((row) => (
                <li key={row.name}>
                  <Prohibit size={12} weight="bold" /> <strong>{row.label}</strong> sai —{" "}
                  {row.reason}
                </li>
              ))}
            </ul>
          ) : (
            <p className="poc-tb-none">
              Não separou ninguém — as {step.entered.length} passam, e a decisão vai
              para o critério seguinte.
            </p>
          )}
        </motion.li>
      ))}
      <motion.li
        className="poc-tb-end"
        initial={reduced ? false : { opacity: 0, scale: 0.94 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: reduced ? 0 : 0.3, delay: reduced ? 0 : 0.25 + steps.length * 0.35 }}
      >
        <Crown size={16} weight="fill" /> Sobrou <strong>{winnerLabel}</strong>.
      </motion.li>
    </ol>
  );
}
