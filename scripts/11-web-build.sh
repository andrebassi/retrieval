#!/usr/bin/env bash
# Compila o front para dentro do pacote Python (`web/static`).
#
# O bundle vive dentro do pacote de propósito: quem clona a PoC roda `task web`
# e vê a tela sem instalar Node. Node é dependência de BUILD, não de execução.
set -euo pipefail
cd "$(dirname "$0")/../frontend"

# pnpm 11 aborta o install não-interativo quando precisa recriar `node_modules`
# por causa de aprovação de build script: `ERR_PNPM_ABORTED_REMOVE_MODULES_DIR_NO_TTY`.
# O `allowBuilds` do pnpm-workspace.yaml resolve a aprovação; o `CI=true` resolve
# o prompt. Precisa dos dois — só um deles ainda trava.
export CI=true

if [ ! -d node_modules ]; then
  echo "==> instalando dependências do front"
  pnpm install --frozen-lockfile 2>/dev/null || pnpm install
fi

echo "==> compilando"
pnpm build

OUT="../src/retrieval_poc/web/static"
echo "==> bundle em $OUT"
ls -la "$OUT"
