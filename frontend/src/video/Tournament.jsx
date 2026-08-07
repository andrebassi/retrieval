// A composição do vídeo: um quadro do torneio, desenhado a partir do frame.
//
// Por que Remotion e não a lib de animação de UI que já estava aqui: o pedido é
// **vídeo passo a passo**, e vídeo tem três coisas que animação de UI não tem
// de graça — linha do tempo (a cena 5 existe no segundo 21, não "depois que
// alguém clicar"), controle de transporte (play, pausa, voltar, arrastar) e
// canvas de tamanho fixo que o player escala para caber. Esse último resolve a
// rolagem de raiz: 1600×900 sempre cabe, em qualquer janela, porque o Player
// aplica um `scale`.
//
// O quarto ganho é de teste. Aqui o desenho é função pura do frame — o mesmo
// frame produz sempre o mesmo pixel. O print de verificação deixa de ser uma
// corrida contra a animação (armadilha 27): pede-se o frame 260 e o frame 260 é
// o que aparece.
//
// Nada aqui calcula nota. O roteiro chega pronto de `scenes.js`, que por sua vez
// só reempacota `/api/advice`.

import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

const C = {
  bg: "#0f1116",
  panel: "#171a21",
  line: "#262b35",
  ink: "#f2f4f7",
  muted: "#8b93a3",
  accent: "#f38020",
  good: "#35c07f",
  bad: "#e4573d",
  gold: "#f5c451",
};

// 78 e não 84: com 84 as seis linhas terminam a 18 px da legenda, e a legenda
// encostada na última linha lê como se fosse a nota dela. Os 36 px que sobram
// separam o placar do que se diz sobre ele.
const ROW_H = 78;
const PAD = 56;
const BOARD_TOP = 268;

const pct = (value) => `${(value * 100).toFixed(1)}%`;

/** Qual cena está no ar neste frame, e quanto da transição já correu.
 *
 * `findLast` em vez de somar durações a cada quadro: a soma já foi feita uma vez
 * em `buildScenes`, e refazê-la aqui abriria a porta para os dois lugares
 * discordarem sobre onde a cena começa. */
function useScene(scenes) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  let index = 0;
  for (let i = scenes.length - 1; i >= 0; i -= 1) {
    if (frame >= scenes[i].from) {
      index = i;
      break;
    }
  }
  const scene = scenes[index];
  const previous = scenes[index - 1] ?? scene;
  const local = frame - scene.from;
  // Mola em vez de rampa linear: o placar precisa parecer que **assentou**, e o
  // overshoot pequeno é o que dá essa leitura. `damping` alto porque linha de
  // placar quicando vira desenho animado, não medição.
  const t = spring({ frame: local, fps, config: { damping: 26, stiffness: 110, mass: 0.9 } });
  const enter = spring({ frame: local, fps, config: { damping: 200 }, durationInFrames: 16 });
  return { scene, previous, local, t, enter, index, frame };
}

/** Uma linha do placar, já interpolada entre a cena anterior e a atual.
 *
 * A ordem de renderização é fixa (a de `strategies`) e a posição vai no
 * `transform`. É o que permite o React não remontar nada quando as seis trocam
 * de lugar — remontar zeraria a barra e a troca viraria um piscar. */
function Row({ name, short, from, to, t, focus, flagged }) {
  const pos = interpolate(t, [0, 1], [from.pos, to.pos]);
  const value = interpolate(t, [0, 1], [from.value, to.value]);
  const dead = interpolate(t, [0, 1], [from.eliminated ? 1 : 0, to.eliminated ? 1 : 0]);
  // `focus` vazio significa "a cena fala de todas" — apagar todo mundo nesse
  // caso deixaria a tela inteira cinza.
  const off = focus.length > 0 && !focus.includes(name) ? 0.32 : 1;
  const opacity = off * (1 - dead * 0.55);
  const bar = interpolate(dead, [0, 1], [1, 0.25]);
  const color = flagged ? C.bad : focus.includes(name) && focus.length < 3 ? C.accent : C.good;
  // Quem caiu continua fora nas cenas seguintes, e a opacidade sozinha não diz
  // isso: “apagada” também é como fica quem só não é o assunto da cena. Sem a
  // palavra, a linha eliminada reaparece na rodada 3 exibindo 100% — nota que
  // ela não tem mais direito de disputar. `dead` e não `flagged`: `flagged` só
  // vale na cena em que a eliminação acontece.
  const out = flagged || dead > 0.5;

  return (
    <div
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        right: 0,
        height: ROW_H - 12,
        transform: `translateY(${pos * ROW_H}px)`,
        opacity,
        display: "flex",
        alignItems: "center",
        gap: 18,
        padding: "0 22px",
        borderRadius: 14,
        background: flagged ? "rgba(228,87,61,0.14)" : C.panel,
        border: `1px solid ${flagged ? "rgba(228,87,61,0.45)" : C.line}`,
      }}
    >
      <span
        style={{
          width: 46,
          height: 46,
          flex: "0 0 auto",
          borderRadius: 12,
          background: "#0f1116",
          color: C.muted,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 24,
          fontWeight: 700,
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {Math.round(pos) + 1}
      </span>
      <span style={{ width: 300, flex: "0 0 auto", fontSize: 27, fontWeight: 600 }}>{short}</span>
      <span
        style={{
          flex: 1,
          height: 22,
          borderRadius: 11,
          background: "#0f1116",
          overflow: "hidden",
        }}
      >
        <span
          style={{
            display: "block",
            height: "100%",
            width: `${value * 100}%`,
            borderRadius: 11,
            background: color,
            opacity: bar,
          }}
        />
      </span>
      <span
        style={{
          width: 130,
          flex: "0 0 auto",
          textAlign: "right",
          fontSize: 28,
          fontWeight: 700,
          fontVariantNumeric: "tabular-nums",
          // Nota riscada porque ela continua verdadeira e deixou de valer: a
          // eliminada acerta mesmo aqueles 100%, só que estourando o relógio.
          // Apagar o número esconderia justamente o que torna o corte por tempo
          // interessante — quem saiu era boa.
          textDecoration: out ? "line-through" : "none",
        }}
      >
        {pct(value)}
      </span>
      <span
        style={{
          width: 130,
          flex: "0 0 auto",
          textAlign: "right",
          fontSize: 21,
          color: out ? C.bad : C.muted,
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {out ? "fora" : `${from.p50.toFixed(1)} ms`}
      </span>
    </div>
  );
}

/** O pódio da última cena, sobreposto ao placar.
 *
 * Aparece só no fim e cobre o placar de propósito: a cena da campeã tem um
 * assunto, e o placar de seis linhas atrás dela devolve a parede de informação
 * que este formato existe para não ter. */
function Podium({ podium, t }) {
  const heights = [230, 175, 140];
  const order = [1, 0, 2];
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        display: "flex",
        alignItems: "flex-end",
        justifyContent: "center",
        gap: 26,
        opacity: t,
      }}
    >
      {order.map((place) => {
        const item = podium[place];
        if (!item) return null;
        const grow = interpolate(t, [0, 1], [0, heights[place]], {
          extrapolateRight: "clamp",
        });
        return (
          <div key={item.name} style={{ width: 300, textAlign: "center" }}>
            <p style={{ margin: "0 0 10px", fontSize: 26, fontWeight: 700 }}>{item.short}</p>
            <p
              style={{
                margin: "0 0 12px",
                fontSize: 34,
                fontWeight: 800,
                color: place === 0 ? C.gold : C.ink,
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {pct(item.value)}
            </p>
            <div
              style={{
                height: grow,
                borderRadius: "14px 14px 0 0",
                background: place === 0 ? C.gold : C.panel,
                border: `1px solid ${place === 0 ? C.gold : C.line}`,
                color: place === 0 ? "#0f1116" : C.muted,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 46,
                fontWeight: 800,
              }}
            >
              {place + 1}º
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function Tournament({ scenes, order }) {
  const { scene, previous, t, enter, frame } = useScene(scenes);
  const { durationInFrames } = useVideoConfig();
  const focus = scene.focus ?? [];
  const flag = scene.flag ?? [];

  const posOf = (board) => Object.fromEntries(board.map((item, i) => [item.name, i]));
  const prevPos = posOf(previous.board);
  const curPos = posOf(scene.board);
  const prevBy = Object.fromEntries(previous.board.map((item) => [item.name, item]));
  const curBy = Object.fromEntries(scene.board.map((item) => [item.name, item]));

  return (
    <AbsoluteFill style={{ background: C.bg, color: C.ink, fontFamily: "ui-sans-serif, system-ui, sans-serif" }}>
      {/* Linha do tempo no topo: onde estamos no vídeo inteiro. Sem ela, uma
          cena de 3 s parece a tela inteira do produto, e não um trecho. */}
      <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 5, background: C.line }}>
        <div
          style={{
            height: "100%",
            width: `${(frame / Math.max(1, durationInFrames - 1)) * 100}%`,
            background: C.accent,
          }}
        />
      </div>

      <div style={{ padding: `${PAD}px ${PAD}px 0` }}>
        <p
          style={{
            margin: 0,
            fontSize: 20,
            letterSpacing: 3,
            textTransform: "uppercase",
            color: C.accent,
            fontWeight: 700,
            opacity: enter,
          }}
        >
          {scene.tag}
        </p>
        <h2
          style={{
            margin: "10px 0 0",
            fontSize: 52,
            lineHeight: 1.1,
            fontWeight: 800,
            transform: `translateY(${interpolate(enter, [0, 1], [16, 0])}px)`,
            opacity: enter,
          }}
        >
          {scene.title}
        </h2>
        {scene.answer && (
          <p
            style={{
              margin: "12px 0 0",
              fontSize: 28,
              color: C.muted,
              opacity: enter,
            }}
          >
            {scene.answer}
          </p>
        )}
      </div>

      <div
        style={{
          position: "absolute",
          top: BOARD_TOP,
          left: PAD,
          right: PAD,
          height: ROW_H * order.length,
        }}
      >
        {scene.podium ? (
          <Podium podium={scene.podium} t={t} />
        ) : (
          order.map((name) => {
            const from = prevBy[name] ?? curBy[name];
            const to = curBy[name] ?? from;
            return (
              <Row
                key={name}
                name={name}
                short={to.short}
                from={{ ...from, pos: prevPos[name] ?? curPos[name] }}
                to={{ ...to, pos: curPos[name] ?? prevPos[name] }}
                t={t}
                focus={focus}
                flagged={flag.includes(name)}
              />
            );
          })
        )}
      </div>

      <div
        style={{
          position: "absolute",
          left: PAD,
          right: PAD,
          bottom: 40,
          display: "flex",
          alignItems: "center",
          gap: 22,
        }}
      >
        <div style={{ flex: 1 }}>
          <p style={{ margin: 0, fontSize: 19, color: C.muted }}>{scene.metric}</p>
          <p
            style={{
              margin: "8px 0 0",
              // A legenda tem uma linha, e o corpo cede antes de a linha
              // dobrar: a segunda linha sobe por cima da última linha do
              // placar — o desempate saiu com “Palavra · com peso” tapado.
              // Reticências resolveriam o transbordo escondendo o final da
              // frase, que é justamente onde mora a conclusão (armadilha 30).
              fontSize: scene.caption.length > 62 ? 30 : 38,
              fontWeight: 700,
              lineHeight: 1.2,
              whiteSpace: "nowrap",
              transform: `translateY(${interpolate(enter, [0, 1], [14, 0])}px)`,
              opacity: enter,
            }}
          >
            {scene.caption}
          </p>
        </div>
      </div>
    </AbsoluteFill>
  );
}
