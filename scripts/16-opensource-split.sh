#!/usr/bin/env bash
# Extrai a PoC do monorepo `work-labs` para repositório próprio, com histórico.
#
# A PoC nasceu como subdiretório de `~/works/labs`, que é um repo privado com
# trabalho de cliente. Publicar não é copiar os arquivos: é preciso levar SÓ os
# commits que tocaram este prefixo — `git subtree split` faz exatamente isso e
# preserva autoria e data de cada um.
#
# O script é idempotente e NÃO empurra nada: ele para com o histórico filtrado
# pronto para conferência (scan de segredo, contagem de commits). O push é o
# passo seguinte, deliberadamente separado — histórico publicado não volta.
set -euo pipefail
cd "$(dirname "$0")/.."

PREFIX="${PREFIX:-retrieval-poc}"
MONOREPO="${MONOREPO:-$HOME/works/labs}"
BRANCH="${SPLIT_BRANCH:-opensource-split}"

# Regex de segredo da rule 19 §3b. Varre o histórico INTEIRO, não só o topo: um
# commit intermediário com credencial continua público depois do push, mesmo que
# o arquivo já não exista na ponta.
SECRET_RE="AKIA[0-9A-Z]{16}|glpat-[A-Za-z0-9._-]{20}|ghp_[A-Za-z0-9]{36}|-----BEGIN [A-Z ]*PRIVATE KEY|AIza[0-9A-Za-z]{35}|xox[baprs]-[A-Za-z0-9-]{10}|whsec_[A-Za-z0-9]{10,}|re_[A-Za-z0-9]{24,}|(sk|rk)_live_[A-Za-z0-9]{10,}"

# Canário: prova que a varredura enxerga antes de confiar no verde dela. Um scan
# que nunca acha nada é indistinguível de um scan cego (rule 19 §3b).
echo "+AKIA0000000000CANARY" | grep -qE "$SECRET_RE" \
  || { echo "🛑 regex de scan quebrada — abortando" >&2; exit 1; }

echo "==> conferindo a árvore do monorepo"
if [ -n "$(git -C "$MONOREPO" status --porcelain -- "$PREFIX")" ]; then
  echo "🛑 $PREFIX tem mudança não commitada — o split ignoraria" >&2
  exit 1
fi

echo "==> filtrando o histórico de $PREFIX/"
git -C "$MONOREPO" branch -D "$BRANCH" 2>/dev/null || true
git -C "$MONOREPO" subtree split --prefix="$PREFIX" -b "$BRANCH" >/dev/null
count=$(git -C "$MONOREPO" rev-list --count "$BRANCH")
echo "    $count commits"

echo "==> varrendo o histórico inteiro por segredo"
found=0
while read -r sha; do
  if git -C "$MONOREPO" show "$sha" 2>/dev/null | grep -qE "$SECRET_RE"; then
    echo "  🛑 $sha"
    found=$((found + 1))
  fi
done < <(git -C "$MONOREPO" rev-list "$BRANCH")
[ "$found" = "0" ] || { echo "🛑 $found commit(s) com segredo — NÃO publicar" >&2; exit 1; }
echo "    limpo nos $count commits"

# `subtree split` REESCREVE cada commit (árvore diferente, pai diferente), então o
# SHA novo nasce sem assinatura — a do commit original cobre a árvore do monorepo,
# não esta. Assinar de novo não é reescrever história publicada: esta branch ainda
# não existe em lugar nenhum. Desligar a assinatura para "destravar" é o que a
# rule 28 proíbe, e o histórico publicado é justamente onde o `Unverified` fica
# para sempre.
echo "==> reassinando os $count commits (a YubiKey precisa estar plugada)"
WORKTREE="${SPLIT_WORKTREE:-$HOME/works/.retrieval-split-wt}"
git -C "$MONOREPO" worktree remove --force "$WORKTREE" 2>/dev/null || true
git -C "$MONOREPO" worktree prune
git -C "$MONOREPO" worktree add --quiet "$WORKTREE" "$BRANCH"
git -C "$WORKTREE" rebase --root --exec 'git commit --amend --no-edit -S' >/dev/null

echo "==> conferindo a assinatura de cada commit"
unsigned=$(git -C "$WORKTREE" log --format="%H %G?" | grep -cv " G$" || true)
if [ "$unsigned" != "0" ]; then
  echo "🛑 $unsigned commit(s) sem assinatura boa — NÃO publicar" >&2
  git -C "$WORKTREE" log --format="%h %G? %s" | grep -v " G " >&2
  exit 1
fi
echo "    todos os $count assinados"

# A branch está *checked out* no worktree, então a `rebase` já a moveu — não cabe
# `branch -f` aqui (o git recusa mexer em branch em uso, e é o certo). Só resta
# devolver o worktree, senão a próxima execução esbarra no nome da branch já
# reservada, e o erro aparece longe da causa.
git -C "$MONOREPO" worktree remove --force "$WORKTREE"

echo
echo "pronto: branch '$BRANCH' em $MONOREPO"
echo "próximo passo, depois de conferir o log acima:"
echo "  git -C $MONOREPO push git@github.com:andrebassi/retrieval.git $BRANCH:main"
