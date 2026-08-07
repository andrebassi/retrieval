// “Qual devo usar?” respondido na hora, sem play.
//
// Quatro formatos morreram antes deste, e cada morte ensinou uma coisa:
//
//   1. as três perguntas lado a lado — só servia para quem já sabia o que cada
//      pergunta significava, e essa pessoa não precisa da aba;
//   2. o assistente, uma pergunta por tela — melhor, mas inerte: quem respondia
//      não via nada acontecer com as seis;
//   3. o torneio com placar ao vivo — o placar se mexia, mas ao lado dele havia
//      texto explicando tudo ao mesmo tempo, e a tela passou a **rolar**;
//   4. o vídeo Remotion de 8 capítulos — resolveu a rolagem por construção, e
//      criou um problema maior: **ninguém assiste 30 s para saber qual usar**.
//      Oito botões de capítulo e um palco de 800×450 num viewport de 1440×900
//      para responder uma pergunta de uma linha.
//
// O que sobrou é a resposta: escolhe as três opções, e a campeã aparece com o
// número e o motivo. Sem play, sem barra, sem capítulo. As seis continuam na
// tela, abaixo — mas quem caiu aparece como **fora**, com o motivo, e não mais
// exibindo a nota como se ainda disputasse (era o que o pódio do vídeo fazia:
// três `100,0%` lado a lado, dois deles já eliminados).

import { useMemo } from "react";

import { fetchAdvice } from "./api.js";
import { Failed, Loading, useAsync } from "./common.jsx";

// O cenário mais comum de verdade: alguém clicou em buscar, lê o primeiro
// resultado, e as perguntas misturam código com descrição.
export const DEFAULT_SCENARIO = { reader: "first", budget: "click", kind: "hybrid" };

const FIELD = [
  { field: "reader", rows: "readers", title: "Quem lê" },
  { field: "budget", rows: "budgets", title: "Quanto espera" },
  { field: "kind", rows: "kinds", title: "Que pergunta" },
];

/** Rótulo curto de cada opção do seletor.
 *
 * Mora aqui e não no back-end porque é decisão de tela: o servidor já devolve o
 * `label` inteiro, que é o que vai para o `title` do botão. Encurtar lá
 * obrigaria o servidor a saber a largura do botão. */
const SHORT = {
  first: "o 1º resultado",
  few: "os 3 primeiros",
  llm: "os 10 (robô)",
  instant: "5 ms",
  click: "150 ms",
  patient: "500 ms",
  literal: "códigos",
  conceptual: "descrição livre",
  hybrid: "os dois juntos",
};

const pct = (value) => `${(value * 100).toFixed(1)}%`;
const ms = (value) => `${value.toFixed(1)} ms`;

/** Seletor de uma escolha do cenário.
 *
 * Rótulo curto na pílula e o texto inteiro no `title`: o rótulo do back-end tem
 * até 38 caracteres (“Uma pessoa, e ela passa o olho em três”), e três linhas
 * desse tamanho empurram a resposta para baixo da dobra — que é o defeito que
 * matou a terceira versão desta aba. */
function Picker({ title, options, value, onChange }) {
  return (
    <div className="poc-vid-pick">
      <span className="poc-vid-pick-title">{title}</span>
      <div className="poc-vid-pick-row">
        {options.map((option) => (
          <button
            key={option.id}
            type="button"
            title={`${option.label} — ${option.hint}`}
            className={option.id === value ? "poc-vid-opt poc-vid-opt-on" : "poc-vid-opt"}
            onClick={() => onChange(option.id)}
          >
            {SHORT[option.id] ?? option.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export function AdviceTab({ scenario, onScenario }) {
  const advice = useAsync(() => fetchAdvice(), []);
  const data = advice.status === "ok" ? advice.data : null;

  // A URL é digitável, então pode trazer id inventado — e um `?reader=xpto`
  // acharia `undefined` no grid e derrubaria a aba inteira. Quem diz o que
  // existe é o payload, não o front.
  const picked = useMemo(() => {
    if (!data) return DEFAULT_SCENARIO;
    const valid = (rows, id, fallback) => (rows.some((r) => r.id === id) ? id : fallback);
    return {
      reader: valid(data.readers, scenario.reader, DEFAULT_SCENARIO.reader),
      budget: valid(data.budgets, scenario.budget, DEFAULT_SCENARIO.budget),
      kind: valid(data.kinds, scenario.kind, DEFAULT_SCENARIO.kind),
    };
  }, [data, scenario]);

  if (advice.status === "loading") return <Loading what="a recomendação" />;
  if (advice.status === "error") return <Failed error={advice.error} />;

  const cell = data.grid[`${picked.reader}|${picked.budget}|${picked.kind}`];
  const short = Object.fromEntries(data.strategies.map((row) => [row.name, row.short]));
  // A campeã é sempre `ranked[0]` (o back-end ordena a lista pela ordem do
  // desempate), mas procurar pelo nome não depende dessa ordem continuar valendo
  // — e é o mesmo caminho que serve o cenário sem campeã.
  const winner = cell.ranked.find((row) => row.name === cell.winner) ?? null;
  const rest = cell.ranked.filter((row) => row.name !== cell.winner);

  return (
    <section className="poc-vid">
      <header className="poc-vid-head">
        {FIELD.map(({ field, rows, title }) => (
          <Picker
            key={field}
            title={title}
            options={data[rows]}
            value={picked[field]}
            onChange={(id) => onScenario({ ...picked, [field]: id })}
          />
        ))}
      </header>

      <div className="poc-ans-card">
        <span className="poc-ans-tag">{winner ? "use" : "nenhuma serve"}</span>
        {winner && (
          <>
            <p className="poc-ans-name" title={winner.label}>
              {short[winner.name] ?? winner.label}
            </p>
            <p className="poc-ans-figures">
              acerta <strong>{pct(winner.value)}</strong> · responde em{" "}
              <strong>{ms(winner.p50)}</strong>
            </p>
          </>
        )}
        <ul className="poc-ans-why">
          {cell.verdict.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
        {/* O aviso não é rodapé de contrato: “devolve lista incompleta em 3
            perguntas” é justamente o que uma recomendação de uma linha esconde,
            e esconder isso seria a armadilha 23 em roupa nova. */}
        {cell.notes.map((note) => (
          <p className="poc-ans-note" key={note}>
            {note}
          </p>
        ))}
      </div>

      <ul className="poc-ans-rest">
        {rest.map((row) => (
          <li
            key={row.name}
            className={row.eliminated ? "poc-ans-row poc-ans-out" : "poc-ans-row"}
          >
            <span className="poc-ans-row-name" title={row.label}>
              {short[row.name] ?? row.label}
            </span>
            {/* Quem saiu não exibe nota. Ela acerta mesmo aqueles 100%, só que
                estourando o relógio ou perdendo o critério de desempate — e
                mostrar o número ao lado dos vivos é dizer que ainda disputa. */}
            <span className="poc-ans-row-value">
              {row.eliminated ? "fora" : pct(row.value)}
            </span>
            <span className="poc-ans-row-note">
              {row.eliminated ? row.reason : ms(row.p50)}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
