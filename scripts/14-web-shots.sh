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
# 900 px é altura de TELA, e continua sendo a altura certa aqui mesmo sem o
# palco de vídeo: a promessa desta aba é caber sem rolar, e print alto esconde
# exatamente a falha que se procura — conteúdo abaixo da dobra.
ADVICE_H=900
# `--force-prefers-reduced-motion` continua na chamada mesmo sem player: não é
# mais o que congela o quadro, é o que faz as animações de entrada nascerem
# prontas (ver o comentário do `shot` acima). Sem ela o print volta a ser uma
# corrida contra o `requestAnimationFrame`.
#
# Um print por RAMO do payload — a tela é uma só, mas o que ela desenha muda com
# o cenário, e cada linha abaixo cobre um caso que as outras não alcançam.
shot advice-padrao     ""                       "$ADVICE_H"
# Sem empate: `tied` tem um nome só, então o cartão perde a linha de empate e a
# segunda frase passa a comparar com a segunda colocada.
shot advice-sem-empate "?reader=first&budget=click&kind=conceptual" "$ADVICE_H"
# Corte em massa: o relógio de 5 ms derruba 4 das 6 por TEMPO (`out_at=budget`).
# Nos outros orçamentos cai 1 ou nenhuma, então a lista com quatro linhas `fora`
# não apareceria em print nenhum.
shot advice-corte      "?reader=first&budget=instant" "$ADVICE_H"
# Outra campeã, e o desempate mais longo do payload (três etapas). Sem isto a
# parte que reage à escolha ficaria sem prova.
shot advice-llm        "?reader=llm&budget=patient&kind=conceptual" "$ADVICE_H"
# As seis trocam de lugar ao sair da média geral para o tipo de pergunta — é a
# reviravolta que dá nome à PoC, e aqui ela aparece como ordem da lista.
shot advice-trocas     "?reader=first&budget=instant&kind=literal" "$ADVICE_H"
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
