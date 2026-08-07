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
# 900 px é altura de tela, não de página: o assistente foi feito para caber sem
# rolar, e um print alto esconderia justamente a falha que importa aqui. Se o
# passo vazar, aparece cortado no PNG — que é o sinal que se quer ver.
WIZARD_H=900
shot recomendacao ""                            "$WIZARD_H"
# Cada passo tem um desenho diferente. Um print só provaria que o primeiro
# desenhou — os outros três renderizam num ramo de código que nunca teria sido
# olhado. `?step=` é 1-based na URL.
shot passo-tempo     "?step=2"                  "$WIZARD_H"
shot passo-perguntas "?step=3"                  "$WIZARD_H"
shot passo-resposta  "?step=4"                  "$WIZARD_H"
# As três respostas do escolhedor são estado de URL. Sem isso, o print só
# pegaria o cenário inicial e a parte interativa da aba ficaria sem prova
# nenhuma: este print tem que mostrar OUTRA vencedora que o `passo-resposta`.
shot recomendacao-llm "?reader=llm&budget=patient&kind=conceptual&step=4" "$WIZARD_H"
# Os cinco abaixo cobrem os ramos do jogo que o cenário de entrada NÃO passa. Cada
# um existe porque o código que ele desenha só roda naquele cenário — e código de
# tela que nunca é fotografado é código que quebra sem ninguém ver.
#
# Corte em massa: o relógio de 5 ms derruba 4 das 6 e o placar fica com quatro
# linhas riscadas. Nos outros orçamentos cai 1 ou nenhuma, então o desenho da
# eliminação em bloco não apareceria em print nenhum.
shot jogo-corte        "?reader=first&budget=instant&step=2" "$WIZARD_H"
# Seis trocam de lugar — é o cenário em que a lista de de-para tem o que mostrar.
shot jogo-trocas       "?reader=first&budget=instant&kind=literal&step=3" "$WIZARD_H"
# E o oposto: ninguém troca. A tela diz isso com todas as letras em vez de ficar
# muda, e é um ramo diferente do mesmo passo.
shot jogo-sem-trocas   "?reader=llm&budget=click&kind=literal&step=3" "$WIZARD_H"
# O mata-mata com as três etapas abertas. 1100 px porque aqui a altura da página
# é o conteúdo — cortar em 900 esconderia justamente a etapa que decide.
shot jogo-mata-mata    "?reader=first&budget=instant&kind=literal&step=4" 1100
# Vencedora sem empate: nenhum mata-mata, e a tela precisa explicar a ausência.
# Sem este print, o texto do caso "a nota decidiu sozinha" nunca é conferido.
shot jogo-sem-empate   "?reader=first&budget=click&kind=conceptual&step=4" "$WIZARD_H"
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
