#!/usr/bin/env bash
# Um print de cada aba, em /tmp/retrieval-poc-shots.
#
# Olhar a tela é parte da entrega (rule 32): o canário prova que a rota
# responde, não que o layout ficou de pé — layout colapsado não emite erro.
#
# Cada aba tem URL própria (`?tab=…`), então basta o `--screenshot` do Chrome.
# A alternativa era um script de CDP com websocket só para clicar na aba; a URL
# resolve o mesmo problema e ainda dá link compartilhável.
set -euo pipefail
cd "$(dirname "$0")/.."

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
OUT="${1:-/tmp/retrieval-poc-shots}"
mkdir -p "$OUT"

if ! lsof -nP -iTCP:8081 -sTCP:LISTEN -t >/dev/null 2>&1; then
  echo "🛑 tela não está de pé — rode 'task web' em outro terminal" >&2
  exit 1
fi

# PNG de tela cheia deste projeto nunca desce de 200 kB; tela branca deu 10 979 B
# quando uma prop indefinida derrubou o render da aba de busca. O canário do
# front continuou verde nessa rodada — ele prova que a rota responde, não que a
# página desenha. O tamanho do arquivo é o sinal barato de que ela desenhou.
MIN_BYTES="${MIN_BYTES:-60000}"
errors=0

# nome | query | altura da janela
shot() {
  local name="$1" query="$2" height="$3"
  # `--virtual-time-budget` avança o relógio da página até as chamadas de rede
  # terminarem; sem ele o print sai antes do `/api/state` responder e mostra
  # "carregando a PoC…".
  # `--force-prefers-reduced-motion` não é preferência de gosto: sem ela o print
  # é uma corrida. As animações de entrada nascem em `opacity: 0` e só sobem no
  # `requestAnimationFrame`, que no headless nem sempre roda antes do disparo —
  # o passo 4 saiu VAZIO numa rodada e cheio na seguinte, com o mesmo bundle
  # (122 917 B contra 315 971 B). Layout de pé, conteúdo transparente, canário
  # verde: exatamente a falha silenciosa que estes prints existem para pegar.
  # Com a flag, o `useReducedMotion()` devolve true, todo `initial` vira `false`
  # e o desenho nasce pronto — de quebra, é o caminho de acessibilidade que
  # passa a ser conferido a cada rodada.
  timeout 90s "$CHROME" --headless --disable-gpu --no-sandbox \
    --force-prefers-reduced-motion \
    --window-size="1440,${height}" --virtual-time-budget=20000 \
    --screenshot="$OUT/$name.png" "http://127.0.0.1:8081/$query" >/dev/null 2>&1
  local bytes
  bytes="$(stat -f%z "$OUT/$name.png" 2>/dev/null || echo 0)"
  if [ "$bytes" -lt "$MIN_BYTES" ]; then
    printf '  🛑 %-14s %s B — abaixo de %s B, provável tela em branco\n' "$name" "$bytes" "$MIN_BYTES"
    errors=$((errors + 1))
  else
    printf '  ✅ %-14s %s B\n' "$name" "$bytes"
  fi
}

# A aba de entrada é a recomendação, então a URL sem parâmetro nenhum já cai
# nela — e é justamente o cenário mais comum (lê o primeiro resultado, espera um
# clique, perguntas misturadas).
# 900 px é altura de TELA, e é a única altura que faz sentido aqui: o vídeo
# dimensiona o próprio palco a partir de `100vh`. Um print alto daria um palco
# alto e esconderia exatamente a falha que se procura — conteúdo que não coube.
VIDEO_H=900
# `--force-prefers-reduced-motion` deixa o player PARADO no frame do capítulo
# (ver `Advice.jsx`), então cada print abaixo é um quadro determinístico: o
# mesmo `?step=` devolve sempre o mesmo pixel, hoje e daqui a um mês.
shot video-abertura  ""                         "$VIDEO_H"
# Um capítulo por print. Cada cena desenha um ramo diferente da composição — a
# rodada 2 é a única com linha eliminada, a 3 é a única em que o placar reordena,
# e a última troca o placar inteiro pelo pódio. Um print só provaria a abertura.
# `?step=` é 1-based na URL.
shot video-quem-le   "?step=2"                  "$VIDEO_H"
shot video-tempo     "?step=3"                  "$VIDEO_H"
shot video-pergunta  "?step=4"                  "$VIDEO_H"
shot video-desempate "?step=5"                  "$VIDEO_H"
# Os critérios do mata-mata são as cenas que de fato ELEGEM a campeã. Enquanto
# cabiam num capítulo só, nenhum print as alcançava — e o que print não alcança
# quebra calado. O cenário padrão decide em duas etapas (`starved`, `tuning`);
# a terceira só aparece quando as duas primeiras empatam, e quem cobre isso é o
# `video-criterio3`, com um cenário escolhido para chegar lá.
shot video-criterio1 "?step=6"                  "$VIDEO_H"
shot video-criterio2 "?step=7"                  "$VIDEO_H"
shot video-criterio3 "?reader=llm&budget=patient&kind=conceptual&step=8" "$VIDEO_H"
# `?step=9` é o teto de `STEP_IDS` e clampa no último capítulo de QUALQUER
# cenário — 8 quando o desempate tem duas etapas, 9 quando tem três, 5 quando
# não há empate. Fixar o número exato aqui exigiria saber de antemão quantas
# etapas cada cenário produz, que é justamente o que muda quando o corpus muda.
shot video-campea    "?step=9"                  "$VIDEO_H"
# As três escolhas são estado de URL. Sem isto o print só cobriria o cenário de
# entrada, e a parte que reage à escolha ficaria sem prova: este tem que mostrar
# OUTRA campeã que o `video-campea`.
shot video-llm       "?reader=llm&budget=patient&kind=conceptual&step=9" "$VIDEO_H"
# Corte em massa: o relógio de 5 ms derruba 4 das 6 e a cena fica com quatro
# linhas em vermelho. Nos outros orçamentos cai 1 ou nenhuma, então o desenho da
# eliminação em bloco não apareceria em print nenhum.
shot video-corte     "?reader=first&budget=instant&step=3" "$VIDEO_H"
# Seis trocam de lugar — é o cenário em que a reordenação do placar tem o que
# mostrar, e é a cena que dá nome à PoC inteira.
shot video-trocas    "?reader=first&budget=instant&kind=literal&step=4" "$VIDEO_H"
# Vencedora sem empate: o roteiro pula a cena de desempate e o mata-mata inteiro,
# então os capítulos são CINCO. `?step=6` clampa no último — se um dia o clamp
# sumir, este print é quem acusa.
shot video-sem-empate "?reader=first&budget=click&kind=conceptual&step=9" "$VIDEO_H"
shot busca        "?tab=search"                 1700
shot documento    "?tab=document&doc=ch_5506"   1500
shot placar       "?tab=score"                  1000
shot discordancia "?tab=disagree"               1700
# O texto que explica cada opção vive dobrado num `<details>`. Fechado, ele não
# entra em print nenhum — e texto que ninguém confere é texto que envelhece
# errado. `?explain=1` abre os seis de uma vez.
shot explicacoes  "?tab=search&explain=1"       2400

echo "==> prints em $OUT — erros: $errors"
exit $((errors > 0 ? 1 : 0))
