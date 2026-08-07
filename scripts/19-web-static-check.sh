#!/usr/bin/env bash
# Valida o `dist/` publicável: serve o diretório, abre num Chrome headless e
# percorre as cinco abas clicando de verdade.
#
# Serve tanto para o build local quanto para a URL já no ar:
#   bash scripts/19-web-static-check.sh                              # dist/ local
#   bash scripts/19-web-static-check.sh https://retrieval.andrebassi.com.br
set -euo pipefail
cd "$(dirname "$0")/.."

TARGET="${1:-}"
# 8098, não 8099: o `image-embedding-poc` usa aquele para a mesma coisa, e as
# duas PoCs convivem nesta máquina (mesma razão do 5434 contra o 5433).
PORT="${POC_STATIC_PORT:-8098}"
PROFILE="/tmp/retrieval-poc-chrome-profile"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
DEBUG_PORT="${POC_CDP_PORT:-9223}"
server_pid=""
chrome_pid=""

cleanup() {
  [ -n "$server_pid" ] && kill "$server_pid" 2>/dev/null || true
  [ -n "$chrome_pid" ] && kill "$chrome_pid" 2>/dev/null || true
}
trap cleanup EXIT

if [ -z "$TARGET" ]; then
  [ -f dist/index.html ] || { echo "🛑 dist/ vazio — rode 'task web:static' antes" >&2; exit 1; }
  echo "==> servindo dist/ em 127.0.0.1:${PORT}"
  (cd dist && python3 -m http.server "$PORT" >/tmp/retrieval-poc-static-serve.log 2>&1) &
  server_pid=$!
  TARGET="http://127.0.0.1:${PORT}"
  sleep 2
fi

echo "==> subindo Chrome headless"
rm -rf "$PROFILE"
"$CHROME" --headless=new --disable-gpu --no-first-run \
  --remote-debugging-port="$DEBUG_PORT" --user-data-dir="$PROFILE" \
  --window-size=1600,1000 about:blank >/tmp/retrieval-poc-chrome.log 2>&1 &
chrome_pid=$!
for _ in $(seq 1 15); do
  curl -sf "http://127.0.0.1:${DEBUG_PORT}/json/version" >/dev/null && break
  sleep 1
done

node scripts/static_check.mjs "$TARGET" "http://127.0.0.1:${DEBUG_PORT}"
