#!/usr/bin/env bash
# Monta a versão publicável: o mesmo front, com a API congelada em arquivo.
#
# Exige `task web` no ar — o snapshot é a resposta do servidor de verdade,
# gravada como veio. Sem servidor não há o que congelar, e o script para aqui em
# vez de publicar uma tela vazia.
#
# Saída: `dist/` na raiz do projeto, pronta para qualquer host estático.
set -euo pipefail
cd "$(dirname "$0")/.."

BASE_URL="${POC_WEB_URL:-http://127.0.0.1:8081}"
DIST="$PWD/dist"
SNAPSHOT_MAP="$PWD/frontend/src/snapshot.json"
FRONT_ONLY=0
[ "${1:-}" = "--front-only" ] && FRONT_ONLY=1

# `--front-only` recompila só a interface por cima do snapshot que já está em
# `dist/`. Serve para iterar em comportamento de tela (um rótulo, um aviso) sem
# precisar do Postgres e do Ollama no ar. Os números continuam sendo os da última
# congelada — se o que mudou for dado, é a rodada completa que vale.
if [ "$FRONT_ONLY" = "1" ]; then
  [ -f "$DIST/data/state.json" ] || { echo "🛑 dist/ sem snapshot — rode a versão completa antes" >&2; exit 1; }
  echo "==> reaproveitando o snapshot já congelado em dist/"
else
  echo "==> conferindo o servidor em ${BASE_URL}"
  if ! curl -fsS --max-time 10 "${BASE_URL}/api/state" >/dev/null; then
    echo "🛑 ${BASE_URL}/api/state não respondeu — suba com 'task db:up && task web'" >&2
    exit 1
  fi

  echo "==> congelando a API"
  python3 scripts/static_export.py "$BASE_URL" "$DIST" "$SNAPSHOT_MAP"
fi

echo "==> compilando o front em modo snapshot"
cd frontend
# Mesmos dois motivos do 11-web-build.sh: `allowBuilds` resolve a aprovação de
# script de pós-instalação, `CI=true` resolve o prompt. Um só ainda trava.
export CI=true
if [ ! -d node_modules ]; then
  pnpm install --frozen-lockfile 2>/dev/null || pnpm install
fi
# `base=/` porque na publicação o front fica na raiz do domínio, não sob
# `/static/`; o `outDir` aponta para o mesmo `dist/` que já tem o snapshot, e por
# isso `emptyOutDir` precisa ficar desligado — o Vite apagaria `data/`.
VITE_SNAPSHOT=1 VITE_BASE=/ VITE_OUT_DIR="$DIST" VITE_EMPTY_OUT_DIR=0 pnpm build
cd ..

# `emptyOutDir` desligado preserva `data/` — e, de quebra, deixa o bundle da
# compilação anterior para trás. O nome tem hash, então ninguém carrega o velho;
# só ocupa espaço e confunde quem for conferir qual arquivo está no ar.
find "$DIST/assets" -type f \( -name '*.js' -o -name '*.css' \) 2>/dev/null | while read -r asset; do
  grep -q "$(basename "$asset")" "$DIST/index.html" || { echo "  removendo sobra: $(basename "$asset")"; rm -f "$asset"; }
done

# Um host estático devolve 404 para uma rota que não é arquivo. A PoC é de página
# única, então o 404 é a própria página — mesma resposta, código diferente.
cp "$DIST/index.html" "$DIST/404.html"

echo "==> pronto"
du -sh "$DIST"
find "$DIST" -type f | wc -l | sed 's/^ */arquivos: /'
