// “Qual devo usar?” respondido como vídeo, não como página.
//
// Três versões morreram antes desta, e cada morte ensinou uma coisa:
//
//   1. as três perguntas lado a lado — só servia para quem já sabia o que cada
//      pergunta significava, e essa pessoa não precisa da aba;
//   2. o assistente, uma pergunta por tela — melhor, mas inerte: quem respondia
//      não via nada acontecer com as seis;
//   3. o torneio com placar ao vivo — o placar se mexia, mas ao lado dele havia
//      texto explicando tudo ao mesmo tempo, e a tela passou a **rolar**. Texto
//      que tenta explicar tudo de uma vez não explica nada, e o que rola para
//      fora não é lido.
//
// O que sobrou é uma composição de vídeo: cenas em sequência, uma ideia por
// cena, legenda de uma linha, e controles de vídeo de verdade — play, pausa,
// voltar, arrastar a barra. O canvas é 1600×900 fixo e o Player o escala para
// caber na janela, o que elimina a rolagem por construção, não por ajuste de
// CSS.
//
// Desta tela em texto sobrou o mínimo: três seletores e a barra de capítulos.
// Todo o resto é o vídeo — montado a partir do mesmo `/api/advice` de sempre,
// sem número novo em lugar nenhum.

import { useEffect, useMemo, useRef, useState } from "react";
import { Player } from "@remotion/player";

import { fetchAdvice } from "./api.js";
import { Failed, Loading, useAsync } from "./common.jsx";
import { Tournament } from "./video/Tournament.jsx";
import { buildScenes, FPS, HEIGHT, WIDTH } from "./video/scenes.js";

// O cenário mais comum de verdade: alguém clicou em buscar, lê o primeiro
// resultado, e as perguntas misturam código com descrição.
export const DEFAULT_SCENARIO = { reader: "first", budget: "click", kind: "hybrid" };

// Os capítulos possíveis, na ordem, incluindo os três critérios do mata-mata.
// Sem empate o vídeo tem só cinco, então a lista real costuma ser menor — mas o
// clamp da URL roda no `App` antes de o payload existir e precisa de um teto
// fixo. Ele é **teto**: o clamp de verdade, contra a quantidade de capítulos que
// aquele cenário produziu, acontece no `seekTo` logo abaixo.
export const STEP_IDS = [
  "intro",
  "reader",
  "budget",
  "kind",
  "tie",
  "tb-starved",
  "tb-tuning",
  "tb-speed",
  "winner",
];
export const DEFAULT_STEP = 0;

const FIELD = [
  { field: "reader", rows: "readers", title: "Quem lê" },
  { field: "budget", rows: "budgets", title: "Quanto espera" },
  { field: "kind", rows: "kinds", title: "Que pergunta" },
];

/** Rótulo curto de cada opção do seletor.
 *
 * Mora aqui e não no back-end porque é decisão de tela: o servidor já devolve o
 * `label` inteiro, que é o que vai para o vídeo e para o `title` do botão.
 * Encurtar lá obrigaria o servidor a saber a largura do botão. */
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

/** Seletor de uma escolha do cenário.
 *
 * Rótulo curto na pílula e o texto inteiro no `title`: o rótulo do back-end tem
 * até 38 caracteres (“Uma pessoa, e ela passa o olho em três”), e três linhas
 * desse tamanho comem a altura de que o vídeo precisa para não rolar. */
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

export function AdviceTab({ scenario, onScenario, step, onStep }) {
  const advice = useAsync(() => fetchAdvice(), []);
  const playerRef = useRef(null);
  const [frame, setFrame] = useState(0);
  // Quem desligou animação no sistema não recebe o vídeo tocando sozinho — e a
  // mesma decisão dá de graça o print determinístico: parado, o Chrome headless
  // fotografa sempre o mesmo quadro. Com autoplay o print vira corrida contra a
  // reprodução, que é a armadilha 27 em roupa nova.
  const still = useMemo(
    () => typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    [],
  );

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

  const film = useMemo(() => (data ? buildScenes(data, picked) : null), [data, picked]);
  // A ordem de renderização das linhas do placar, fixa. É o que faz o React
  // reaproveitar cada linha quando as seis trocam de lugar — reordenar o array
  // remontaria os nós, e a troca viraria um piscar em vez de um deslize.
  const order = useMemo(() => (data ? data.strategies.map((s) => s.name) : []), [data]);
  const key = `${picked.reader}|${picked.budget}|${picked.kind}`;

  // O capítulo escolhido manda o player para o frame dele. O caminho contrário
  // não existe de propósito: se a reprodução também escrevesse `step`, cada
  // segundo de vídeo trocaria a URL e o botão de voltar do navegador viraria
  // inútil.
  useEffect(() => {
    if (!film || !playerRef.current) return;
    const chapter = film.chapters[Math.min(step, film.chapters.length - 1)];
    if (!chapter) return;
    // Tocando, o capítulo começa no primeiro frame da cena — é onde a transição
    // do placar nasce, e vê-la nascer é metade da explicação. Parado, esse mesmo
    // frame mostraria o placar ainda na posição da cena ANTERIOR: 34 frames
    // adiante a mola já assentou, e é esse quadro que vale como retrato.
    const target = still ? chapter.frame + 34 : chapter.frame;
    playerRef.current.seekTo(target);
    setFrame(target);
  }, [film, step, still]);

  useEffect(() => {
    const player = playerRef.current;
    if (!player) return undefined;
    const onUpdate = (event) => setFrame(event.detail.frame);
    player.addEventListener("frameupdate", onUpdate);
    return () => player.removeEventListener("frameupdate", onUpdate);
  }, [film]);

  if (advice.status === "loading") return <Loading what="a recomendação" />;
  if (advice.status === "error") return <Failed error={advice.error} />;

  const scene = film.scenes.reduce(
    (best, item) => (frame >= item.from ? item : best),
    film.scenes[0],
  );
  const active = film.chapters.reduce(
    (best, item, index) => (frame >= item.frame ? index : best),
    0,
  );

  return (
    <section className="poc-vid">
      <header className="poc-vid-head">
        {FIELD.map(({ field, rows, title }) => (
          <Picker
            key={field}
            title={title}
            options={data[rows]}
            value={picked[field]}
            onChange={(id) => {
              onScenario({ ...picked, [field]: id });
              onStep(0);
            }}
          />
        ))}
      </header>

      <div className="poc-vid-stage">
        <Player
          key={key}
          ref={playerRef}
          component={Tournament}
          inputProps={{ scenes: film.scenes, order }}
          durationInFrames={film.total}
          fps={FPS}
          compositionWidth={WIDTH}
          compositionHeight={HEIGHT}
          style={{ width: "100%", height: "100%" }}
          controls
          autoPlay={!still}
          loop
          acknowledgeRemotionLicense
        />
      </div>

      <nav className="poc-vid-chapters" aria-label="capítulos do vídeo">
        {film.chapters.map((chapter, index) => (
          <button
            key={chapter.id}
            type="button"
            className={index === active ? "poc-vid-chap poc-vid-chap-on" : "poc-vid-chap"}
            onClick={() => onStep(index)}
          >
            <span className="poc-vid-chap-n">{index + 1}</span>
            {chapter.label}
          </button>
        ))}
        {/* A cena atual escrita por extenso serve de legenda do que a barra
            destaca — “Desempate” aceso não diz qual dos três critérios está
            correndo agora. */}
        <span className="poc-vid-now">{scene.title}</span>
      </nav>
    </section>
  );
}
