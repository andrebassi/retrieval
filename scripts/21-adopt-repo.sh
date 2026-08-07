#!/usr/bin/env bash
# Faz este diretório passar a ser um clone do repositório público, e sai do
# monorepo — o mesmo arranjo do `image-embedding-poc`.
#
# A ordem importa: primeiro o monorepo esquece o prefixo (`rm --cached` +
# `.gitignore`), só então nasce o `.git` de dentro. Invertida, o monorepo enxerga
# o diretório com `.git` próprio e o transforma em **gitlink** — um submódulo
# quebrado, que a rule 19 §3a existe para evitar.
#
# Idempotente: rodar de novo com tudo já no lugar não muda nada.
set -euo pipefail
cd "$(dirname "$0")/.."
POC="$PWD"

MONOREPO="${MONOREPO:-$HOME/works/labs}"
PREFIX="${PREFIX:-retrieval-poc}"
ORIGIN="${ORIGIN:-https://github.com/andrebassi/retrieval.git}"

echo "==> conferindo que o repositório público responde"
# `grep -c` e não `grep -q`, pelo mesmo motivo do 16: `-q` fecha o pipe ao casar
# e derruba quem escreve com SIGPIPE sob `pipefail`. Herestring também não serve
# — ela trava acima de ~100 B neste ambiente.
[ "$(timeout 60s git ls-remote "$ORIGIN" refs/heads/main | grep -c main || true)" != "0" ] \
  || { echo "🛑 $ORIGIN não tem main — rode o 20 antes" >&2; exit 1; }

if [ -d "$POC/.git" ]; then
  echo "==> .git próprio já existe — nada a adotar"
else
  echo "==> tirando $PREFIX do índice do monorepo"
  if git -C "$MONOREPO" ls-files --error-unmatch "$PREFIX" >/dev/null 2>&1; then
    git -C "$MONOREPO" rm -r -q --cached "$PREFIX"
    echo "    removido do índice (os arquivos ficam no disco)"
  else
    echo "    já não estava no índice"
  fi

  if ! grep -q "^$PREFIX/$" "$MONOREPO/.gitignore"; then
    cat >> "$MONOREPO/.gitignore" <<EOF

# retrieval-poc virou repo próprio, público:
# https://github.com/andrebassi/retrieval
# Continua nesta pasta, mas quem versiona é o repo de dentro.
$PREFIX/
EOF
    echo "    acrescentado ao .gitignore do monorepo"
  fi

  echo "==> criando o clone aqui dentro"
  git init -q -b main "$POC"
  git -C "$POC" remote add origin "$ORIGIN"
  timeout 180s git -C "$POC" fetch -q origin main
  # `reset --mixed` e não `checkout`: a árvore de trabalho JÁ é o conteúdo do
  # commit publicado. Checkout tentaria escrever por cima e recusaria com
  # "would be overwritten"; o reset só popula o índice e deixa os arquivos.
  git -C "$POC" reset -q --mixed origin/main
  git -C "$POC" branch -q --set-upstream-to=origin/main main
fi

echo "==> estado final"
echo "    remote: $(git -C "$POC" remote get-url origin)"
echo "    branch: $(git -C "$POC" rev-parse --abbrev-ref HEAD) → $(git -C "$POC" rev-parse --short HEAD)"
dirty=$(git -C "$POC" status --porcelain | wc -l | tr -d " ")
echo "    árvore: $dirty arquivo(s) fora do commit"
git -C "$POC" status --porcelain | head -10
