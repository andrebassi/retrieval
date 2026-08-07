#!/usr/bin/env bash
# Publica o `dist/` no Cloudflare Pages e prende o domínio próprio.
#
# Credencial vem do `pass` — nunca do arquivo, nunca do histórico do shell.
# O script é idempotente: rodar de novo faz um deploy novo e não duplica o
# domínio (a API responde 8000018 quando ele já está preso, e isso é tratado).
set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT="${CF_PAGES_PROJECT:-retrieval}"
DOMAIN="${CF_PAGES_DOMAIN:-retrieval.andrebassi.com.br}"
ACCOUNT="${CLOUDFLARE_ACCOUNT_ID:-e11c18594fd320087af6f18de03012b7}"
ZONE="${CF_ZONE_ID:-0c31505d4a797d97cf9d93269c1c1b32}"
API="https://api.cloudflare.com/client/v4"

[ -f dist/index.html ] || { echo "🛑 dist/ vazio — rode 'task web:static' antes" >&2; exit 1; }
# O snapshot é metade do que se publica: sem ele o bundle sobe e a tela abre
# vazia, com 200 em tudo. Conferir aqui é mais barato que descobrir no ar.
[ -f dist/data/state.json ] || { echo "🛑 dist/data/ sem snapshot — rode 'task web:static'" >&2; exit 1; }

export CLOUDFLARE_API_TOKEN="${CLOUDFLARE_API_TOKEN:-$(pass show bassi/cloudflare/token)}"
export CLOUDFLARE_ACCOUNT_ID="$ACCOUNT"

cf() {
  local method="$1" path="$2"; shift 2
  curl -sS -X "$method" "${API}${path}" \
    -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
    -H "Content-Type: application/json" "$@"
}

# A resposta chega pelo **argumento**, não por stdin — as duas formas óbvias de
# alimentar stdin falham aqui, cada uma do seu jeito:
#
#   `… | grep -q`   o grep fecha o pipe ao casar, quem escreve leva SIGPIPE e o
#                   `pipefail` do topo devolve 141: o teste quebra exatamente
#                   quando a asserção é VERDADEIRA. Foi o que abortou o script
#                   mostrando um `"success": true` como se fosse erro.
#   `<<<"$resp"`    a herestring vira arquivo em `$TMPDIR`, e aqui ela **trava**
#                   acima de ~100 B. Medido: 100 B passa, 1000 B pendura até o
#                   `timeout` matar. Uma resposta de projeto do Pages tem ~6 KB.
#
# `json.loads(sys.argv[1])` não depende de stdin nem de espaçamento, e 6 KB cabe
# folgado no ARG_MAX (1 MB no macOS).
ok() {
  python3 -c 'import json,sys; sys.exit(0 if json.loads(sys.argv[1]).get("success") else 1)' "$1"
}
has_code() {
  python3 -c 'import json,sys
d = json.loads(sys.argv[1])
sys.exit(0 if any(e.get("code") == int(sys.argv[2]) for e in d.get("errors", [])) else 1)' "$1" "$2"
}

echo "==> garantindo o projeto '${PROJECT}'"
if ! ok "$(cf GET "/accounts/${ACCOUNT}/pages/projects/${PROJECT}")"; then
  cf POST "/accounts/${ACCOUNT}/pages/projects" \
    --data "{\"name\":\"${PROJECT}\",\"production_branch\":\"main\"}" >/dev/null
  echo "    criado"
else
  echo "    já existe"
fi

echo "==> enviando o build"
npx --yes wrangler pages deploy dist --project-name "$PROJECT" --branch main --commit-dirty=true

echo "==> prendendo ${DOMAIN}"
attach=$(cf POST "/accounts/${ACCOUNT}/pages/projects/${PROJECT}/domains" \
  --data "{\"name\":\"${DOMAIN}\"}")
if ok "$attach"; then
  echo "    domínio registrado no projeto"
elif has_code "$attach" 8000018; then
  # 8000018 = já está preso. Qualquer outro erro é erro de verdade.
  echo "    já estava preso"
else
  echo "🛑 ${attach}" >&2
  exit 1
fi

echo "==> apontando o DNS"
host="${DOMAIN%%.*}"
existing=$(cf GET "/zones/${ZONE}/dns_records?name=${DOMAIN}")
record=$(python3 -c 'import json,sys; r=json.loads(sys.argv[1])["result"]; print(r[0]["id"] if r else "")' "$existing")
body="{\"type\":\"CNAME\",\"name\":\"${host}\",\"content\":\"${PROJECT}.pages.dev\",\"proxied\":true,\"ttl\":1}"
if [ -n "$record" ]; then
  ok "$(cf PUT "/zones/${ZONE}/dns_records/${record}" --data "$body")" \
    && echo "    CNAME atualizado" || { echo "🛑 falha ao atualizar o CNAME" >&2; exit 1; }
else
  ok "$(cf POST "/zones/${ZONE}/dns_records" --data "$body")" \
    && echo "    CNAME criado" || { echo "🛑 falha ao criar o CNAME" >&2; exit 1; }
fi

echo "==> https://${DOMAIN}"
