#!/usr/bin/env bash
# O que o diff acumulado da branch esconde: linhas adicionadas em algum commit
# e removidas (ou alteradas) por outro commit da MESMA branch antes do push.
#
#   bash .review-gate/hooks/review-history.sh [<merge-base> <head>] [--remote r] [--base b]
#
# Sem argumentos, calcula merge-base e head como o review-local.sh (base do
# review.conf, head = HEAD). Imprime em stdout, agrupado por commit:
#   # <sha curto> <assunto>
#   <caminho>: <linha adicionada>
# Vazio (e rc 0) quando o histórico não tem nada que o diff final não mostre.
#
# Por que existe: a skill revisa (git diff <merge-base> <head>). Um segredo
# commitado e apagado no commit seguinte não aparece nesse diff, mas o push leva
# o commit — e ele fica no remoto, em forks e clones; squash merge não apaga a
# branch da PR. Enquanto só existe no clone local, reescrever a branch resolve
# (git rebase -i); é por isso que a checagem fica ANTES do push. A lógica é
# lib.sh:review_ghost_lines; isto é só a interface de linha de comando, usada
# pelo review-local.sh (headless) e pela skill em sessão interativa.
set -uo pipefail

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${HOOK_DIR}/lib.sh"

REMOTE="origin"; BASE=""; pos=()
while [ $# -gt 0 ]; do
    case "$1" in
        --remote) REMOTE="$2"; shift 2 ;;
        --base)   BASE="$2";   shift 2 ;;
        -h|--help) sed -n '2,12p' "$0" >&2; exit 2 ;;
        *) pos+=("$1"); shift ;;
    esac
done

git rev-parse --show-toplevel >/dev/null 2>&1 || { _rv_say "rode dentro do clone"; exit 2; }
case "${#pos[@]}" in
    2)
        MB="$(git rev-parse --verify "${pos[0]}^{commit}" 2>/dev/null)" || { _rv_say "merge-base inválido: ${pos[0]}"; exit 2; }
        SHA="$(git rev-parse --verify "${pos[1]}^{commit}" 2>/dev/null)" || { _rv_say "head inválido: ${pos[1]}"; exit 2; }
        ;;
    0)
        review_load_config "$REMOTE"
        SHA="$(git rev-parse --verify HEAD 2>/dev/null)" || { _rv_say "sem HEAD"; exit 2; }
        branch="$(git symbolic-ref --short -q HEAD 2>/dev/null || printf 'HEAD')"
        [ -n "$BASE" ] || BASE="$(review_base_branch "$branch")"
        review_fetch_base "$REMOTE" "$BASE" || exit 2
        MB="$(git merge-base "refs/remotes/${REMOTE}/${BASE}" "$SHA" 2>/dev/null)" \
            || { _rv_say "merge-base com ${REMOTE}/${BASE} falhou (clone raso? git fetch --unshallow)"; exit 2; }
        ;;
    *) _rv_say "uso: review-history.sh [<merge-base> <head>] [--remote r] [--base b]"; exit 2 ;;
esac

review_ghost_lines "$MB" "$SHA"
