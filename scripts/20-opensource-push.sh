#!/usr/bin/env bash
# Cria o repositório público no GitHub e empurra o histórico filtrado pelo 16.
#
# Separado do 16 de propósito: o split é reversível (branch local), o push não —
# histórico publicado não volta. Quem roda este script já conferiu o log do
# outro: contagem de commits, varredura de segredo e assinatura.
#
# Idempotente: repositório que já existe é reaproveitado, e o push é normal
# (nunca `--force`), então rodar duas vezes não reescreve nada.
set -euo pipefail
cd "$(dirname "$0")/.."

MONOREPO="${MONOREPO:-$HOME/works/labs}"
BRANCH="${SPLIT_BRANCH:-opensource-split}"
OWNER="${OWNER:-andrebassi}"
REPO="${REPO:-retrieval}"
DESCRIPTION="Seis formas de achar um documento, medidas lado a lado: ts_rank, BM25, denso (bge-m3), fusão, RRF e RRF + cross-encoder — Postgres/pgvector e Ollama, tudo local"
HOMEPAGE="https://retrieval.andrebassi.com.br"

# O token sai do pass e vive só no ambiente deste processo (rule 02). `gh` o lê
# de GH_TOKEN sem que ele passe por linha de comando, que é visível no `ps`.
export GH_TOKEN
GH_TOKEN="$(pass show bassi/github/token)"

echo "==> conferindo a branch filtrada"
git -C "$MONOREPO" rev-parse --verify "$BRANCH" >/dev/null
count=$(git -C "$MONOREPO" rev-list --count "$BRANCH")
unsigned=$(git -C "$MONOREPO" log --format="%H %G?" "$BRANCH" | grep -cv " G$" || true)
[ "$unsigned" = "0" ] || { echo "🛑 $unsigned commit(s) sem assinatura — rode o 16 antes" >&2; exit 1; }
echo "    $count commits, todos assinados"

echo "==> repositório $OWNER/$REPO"
if timeout 30s gh api "/repos/$OWNER/$REPO" >/dev/null 2>&1; then
  echo "    já existe"
else
  timeout 60s gh repo create "$OWNER/$REPO" \
    --public \
    --description "$DESCRIPTION" \
    --homepage "$HOMEPAGE" >/dev/null
  echo "    criado"
fi

echo "==> empurrando $BRANCH → main"
# URL https e não SSH: as chaves SSH desta máquina não estão registradas no
# GitHub pessoal, e o credential helper global já lê o token do pass (rule 19).
timeout 180s git -C "$MONOREPO" push "https://github.com/$OWNER/$REPO.git" "$BRANCH:main"

echo "==> conferindo o que chegou lá"
timeout 30s gh api "/repos/$OWNER/$REPO" \
  --jq '"    \(.full_name) · \(.visibility) · \(.license.spdx_id // "sem licença") · \(.homepage // "sem homepage")"'
timeout 30s gh api "/repos/$OWNER/$REPO/commits?per_page=1" \
  --jq '"    topo: \(.[0].sha[0:7]) · verificado: \(.[0].commit.verification.verified) (\(.[0].commit.verification.reason))"'
