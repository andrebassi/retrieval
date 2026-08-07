// O roteiro do vídeo: transforma o payload de `/api/advice` numa lista de cenas.
//
// Separado da composição de propósito. `Tournament.jsx` só sabe desenhar um
// quadro a partir de `scenes[i]`; quem decide o que cada cena diz é este
// arquivo, que é código puro e não depende de frame nenhum. Misturar os dois
// produz a composição de 600 linhas em que a regra de negócio some no meio do
// `interpolate`.
//
// Nenhuma cena inventa número. Toda nota, legenda e motivo de eliminação vem do
// back-end — o que este arquivo faz é escolher **quando** cada coisa aparece.

/** Quanto tempo cada cena fica na tela, em frames a 30 fps.
 *
 * Números escolhidos lendo em voz alta: uma legenda de ~60 caracteres leva ~3 s
 * para ser lida sem pressa, e a transição do placar come os primeiros ~0,9 s.
 * Cena mais curta que isso vira flash que ninguém termina — foi o defeito da
 * primeira tentativa, com tudo na mesma tela e nada com tempo próprio. */
const D = {
  intro: 80,
  reader: 115,
  budget: 115,
  kind: 130,
  tie: 100,
  step: 105,
  winner: 150,
};

export const FPS = 30;
export const WIDTH = 1600;
export const HEIGHT = 900;

/** Normaliza uma linha de placar.
 *
 * As três origens de board (`rounds.reader`, `rounds.budget`, `grid[].ranked`)
 * trazem campos extras diferentes entre si. A composição recebe sempre a mesma
 * forma para não ter que perguntar de onde a linha veio. */
const row = (item, short) => ({
  name: item.name,
  short: short[item.name] ?? item.label,
  value: item.value,
  p50: item.p50,
  eliminated: Boolean(item.eliminated),
  reason: item.reason ?? "",
});

/** Monta o roteiro inteiro para um cenário.
 *
 * Devolve as cenas já com `from` (frame de entrada) e `frames` (duração), mais
 * os capítulos e o total. Calcular o `from` aqui evita que a composição some
 * durações a cada frame — e evita que o botão de capítulo e a cena discordem
 * sobre onde a rodada 3 começa, que é a mesma classe de bug de ter duas ordens
 * do placar (armadilhas 23 e 24). */
export function buildScenes(data, scenario) {
  const short = Object.fromEntries(data.strategies.map((s) => [s.name, s.short]));
  const label = Object.fromEntries(data.strategies.map((s) => [s.name, s.label]));
  const readerRow = data.readers.find((r) => r.id === scenario.reader);
  const budgetRow = data.budgets.find((r) => r.id === scenario.budget);
  const kindRow = data.kinds.find((r) => r.id === scenario.kind);
  const roundReader = data.rounds.reader[scenario.reader];
  const roundBudget = data.rounds.budget[`${scenario.reader}|${scenario.budget}`];
  const cell = data.grid[`${scenario.reader}|${scenario.budget}|${scenario.kind}`];

  const scenes = [];
  const push = (scene) => {
    scenes.push({ ...scene, index: scenes.length, from: 0 });
  };

  // Cena 0: as seis entram sem nota. A barra a zero existe para que a rodada 1
  // seja **vista** preenchendo — começar já com número pronto joga fora a única
  // animação que explica o que a régua faz.
  push({
    id: "intro",
    frames: D.intro,
    tag: "Antes de começar",
    title: `Seis formas de buscar, ${data.queries.total} perguntas medidas`,
    answer: "",
    metric: "nenhuma régua escolhida ainda",
    caption: "A nota de cada uma depende de três escolhas. Uma por rodada.",
    board: data.strategies.map((s) => ({
      name: s.name,
      short: s.short,
      value: 0,
      p50: s.p50,
      eliminated: false,
      reason: "",
    })),
  });

  push({
    id: "reader",
    frames: D.reader,
    tag: "Rodada 1 de 4",
    title: "Quem lê o resultado?",
    answer: readerRow.label,
    metric: `${readerRow.metric_label} · média das ${data.queries.total} perguntas`,
    caption: roundReader.caption,
    board: roundReader.board.map((item) => row(item, short)),
  });

  push({
    id: "budget",
    frames: D.budget,
    tag: "Rodada 2 de 4",
    title: "Quanto dá para esperar?",
    answer: `${budgetRow.label} — ${roundBudget.ms.toFixed(0)} ms`,
    metric: `${readerRow.metric_label} · quem estoura ${roundBudget.ms.toFixed(0)} ms sai`,
    caption: roundBudget.caption,
    board: roundBudget.board.map((item) => row(item, short)),
    // Quem acabou de cair é o que a cena tem para mostrar; sem isso a linha
    // apaga e ninguém sabe qual das seis saiu.
    flag: roundBudget.out.map((item) => item.name),
  });

  const ranked = cell.ranked.map((item) => row(item, short));

  // Quem já caiu continua caído. O `ranked` do back-end só marca quem saiu por
  // TEMPO, então cada etapa do mata-mata precisa herdar as eliminações das
  // etapas anteriores — sem isso a linha derrubada em “Calibrar” reaparece verde
  // e com a nota inteira em “Relógio”, exibindo um número que ela já não tem
  // direito de disputar. É a mesma armadilha da eliminação por tempo, uma cena
  // mais tarde.
  const gone = new Set(ranked.filter((item) => item.eliminated).map((item) => item.name));
  // O acumulado entra ANTES dos `out` da própria etapa: na cena em que a queda
  // acontece quem marca é o `flag`, que pinta de vermelho em vez de apagar — ver
  // a linha cair é o assunto daquela cena.
  const boardNow = () => ranked.map((item) => (gone.has(item.name) ? { ...item, eliminated: true } : item));

  /** Quem saiu, dito por extenso.
   *
   * O rótulo curto já usa `·` como separador interno (“Duas juntas · notas”), e
   * juntar duas eliminadas com `·` produz “Palavra · simples · Palavra · com
   * peso”, que lê como quatro nomes — a armadilha 30 de novo, agora na legenda.
   * Com três ou mais, nomear todas estoura a linha única, e aí a contagem diz
   * mais: quem saiu está em vermelho no placar logo acima. */
  const outCaption = (items) => {
    if (items.length === 1) return `${short[items[0].name]} sai`;
    if (items.length === 2) return `${short[items[0].name]} e ${short[items[1].name]} saem`;
    return `${items.length} saem neste critério`;
  };

  push({
    id: "kind",
    frames: D.kind,
    tag: "Rodada 3 de 4",
    title: "Que tipo de pergunta?",
    answer: kindRow.label,
    metric: `${readerRow.metric_label} · só as perguntas do tipo “${kindRow.label}”`,
    caption: cell.swap_caption,
    board: boardNow(),
    focus: cell.moved.map((item) => item.name),
  });

  // Empate só ganha cena se existir. Uma cena "não houve empate" gasta 3,3 s
  // para dizer que nada aconteceu — e o mata-mata depois dela ficaria sem
  // assunto, porque o back-end não devolve passo nenhum nesse caso.
  if (cell.tied.length > 1) {
    push({
      id: "tie",
      frames: D.tie,
      tag: "Rodada 4 de 4",
      title: "Empate na nota",
      answer: `${cell.tied.length} competidoras dentro de ${data.band_points} pontos`,
      metric: "a nota não decide — vai para o mata-mata",
      // Listar as empatadas pelo nome dava 89 caracteres e duas linhas de
      // legenda, que subiam por cima da última linha do placar. Quem empatou
      // está aceso no placar logo acima — a legenda só precisa dizer o que isso
      // significa.
      caption: `A nota não separa as ${cell.tied.length} primeiras`,
      board: boardNow(),
      focus: cell.tied,
    });

    for (const step of cell.tiebreak) {
      const out = step.out.map((item) => item.name);
      push({
        id: `tb-${step.id}`,
        frames: D.step,
        tag: "Mata-mata",
        title: step.title,
        answer: step.why,
        // “1 passam” é o mesmo defeito de concordância do back-end, e aqui ele
        // aparece justo no último critério — o que decide a campeã.
        metric: `${step.entered.length} entram · ${step.passed.length} ${step.passed.length === 1 ? "passa" : "passam"}`,
        caption: step.decided
          ? outCaption(step.out)
          : "Não separou ninguém — vai para o critério seguinte",
        board: boardNow(),
        focus: step.entered,
        flag: out,
      });
      for (const name of out) gone.add(name);
    }
  }

  push({
    id: "winner",
    frames: D.winner,
    tag: "Resultado",
    title: cell.winner ? label[cell.winner] : "Nenhuma cabe neste cenário",
    answer: cell.winner ? `acerta ${(cell.value * 100).toFixed(1)}% neste cenário` : "",
    metric: `${readerRow.label} · ${budgetRow.label} · ${kindRow.label}`,
    caption: cell.why_caption,
    board: boardNow(),
    focus: cell.winner ? [cell.winner] : [],
    podium: cell.podium.map((item) => ({ ...item, short: short[item.name] })),
  });

  let acc = 0;
  for (const scene of scenes) {
    scene.from = acc;
    acc += scene.frames;
  }

  // Capítulo aponta para o frame de entrada da cena — e **toda** cena vira
  // capítulo, inclusive cada critério do mata-mata.
  //
  // A primeira versão agrupava o mata-mata inteiro num botão só, para a barra
  // não virar fileira de botões de 3 s. O efeito colateral foi pior que o
  // problema: sem capítulo próprio, as cenas que de fato **decidem** a campeã só
  // existem enquanto o vídeo toca — nenhum print as alcança, e o que print não
  // alcança quebra calado (armadilha 19). Com empate são 8 botões no máximo, e
  // eles cabem na largura.
  const CHAPTER_LABEL = {
    intro: "As seis",
    reader: "Quem lê",
    budget: "Tempo",
    kind: "Pergunta",
    tie: "Empate",
    "tb-starved": "Lista cheia",
    "tb-tuning": "Calibrar",
    "tb-speed": "Relógio",
    winner: "Campeã",
  };
  const chapters = scenes.map((scene) => ({
    id: scene.id,
    label: CHAPTER_LABEL[scene.id] ?? scene.title,
    frame: scene.from,
  }));

  return { scenes, chapters, total: acc };
}
