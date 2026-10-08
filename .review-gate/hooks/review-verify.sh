#!/usr/bin/env bash
# O que o CI executa: confere a prova da revisão local para o head da PR.
#
#   bash .review-gate/hooks/review-verify.sh <base-ref> <head-sha> [--remote origin] [--cabecalho]
#
# Busca refs/notes/review do remoto (e o espelho refs/heads/review-gate/notes,
# por onde chegam as provas de quem só consegue empurrar branches) e aplica a MESMA regra do pre-push
# (lib.sh:review_note_valid): nota no head, merge-base gravado ancestral do
# head e da base, patch-id recomputado igual, corpo começando pelo cabeçalho
# da skill. Passou → imprime o corpo da review em stdout (o workflow republica
# como review COMMENT na PR). Com --cabecalho imprime as linhas do cabeçalho da
# nota em vez do corpo (o workflow usa para o rodapé de procedência).
# Falhou → instruções em stderr, rc 1. Nenhum Claude aqui: o CI só confere.
#
#   bash .review-gate/hooks/review-verify.sh --escopo <branch-base-da-PR> [--remote origin]
#
# Primeiro passo do workflow: imprime aplica=true|false (formato do
# $GITHUB_OUTPUT) — o portão só vale para PR que mira a base de feature/bugfix
# (lib.sh:review_pr_in_scope). PR develop → main sai verde sem conferir nada.
#
# Testável localmente sem GitHub — é por isso que a lógica mora aqui e não
# inline no YAML.
set -uo pipefail

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${HOOK_DIR}/lib.sh"

if [ "${1:-}" = "--escopo" ]; then
    PR_BASE="${2:-}"; REMOTE="origin"
    [ "${3:-}" = "--remote" ] && REMOTE="${4:-origin}"
    [ -n "$PR_BASE" ] || { echo "uso: review-verify.sh --escopo <branch-base-da-PR> [--remote r]" >&2; exit 2; }
    review_load_config "$REMOTE"
    if review_pr_in_scope "$PR_BASE"; then
        _rv_say "PR para ${PR_BASE} (base de feature/bugfix): o portão vale"
        printf 'aplica=true\n'
    else
        _rv_say "PR para ${PR_BASE}: fora do portão — só PR para ${REVIEW_BASE_BRANCH} exige a revisão essencial (REVIEW_BASE_BRANCH no review.conf)"
        printf 'aplica=false\n'
    fi
    exit 0
fi

BASE_REF=""; HEAD_SHA=""; REMOTE="origin"; MODO="corpo"
while [ $# -gt 0 ]; do
    case "$1" in
        --remote) REMOTE="$2"; shift 2 ;;
        --cabecalho) MODO="cabecalho"; shift ;;
        *) if [ -z "$BASE_REF" ]; then BASE_REF="$1"; elif [ -z "$HEAD_SHA" ]; then HEAD_SHA="$1"; fi; shift ;;
    esac
done
[ -n "$BASE_REF" ] && [ -n "$HEAD_SHA" ] || { echo "uso: review-verify.sh <base-ref> <head-sha> [--remote r] [--cabecalho]" >&2; exit 2; }

git rev-parse -q --verify "${BASE_REF}^{commit}" >/dev/null 2>&1 || { _rv_say "base-ref (${BASE_REF}) não existe neste clone — faça o fetch antes"; exit 2; }
HEAD_SHA="$(git rev-parse --verify "${HEAD_SHA}^{commit}" 2>/dev/null)" || { _rv_say "head-sha inválido"; exit 2; }

if ! review_notes_pull "$REMOTE"; then
    _rv_say "${REMOTE} não tem ${NOTES_REF} nem o espelho ${NOTES_MIRROR_REF#refs/heads/}: nenhuma revisão local foi empurrada ainda"
fi

if review_note_valid "$HEAD_SHA" "$BASE_REF"; then
    if [ "$MODO" = "cabecalho" ]; then
        review_note_read "$HEAD_SHA" | awk '/^---$/ { exit } { print }'
    else
        review_note_read "$HEAD_SHA" | review_note_body
    fi
    exit 0
fi

_rv_say "Revisão essencial NÃO encontrada para o head ${HEAD_SHA:0:12}."
_rv_say "  No clone, na branch da PR:  bash $(review_hooks_rel)/review-local.sh  (ou /pr-review-essentials modo local;"
_rv_say "  no Windows fora do Git Bash: $(review_hooks_rel_win)\\review-local.cmd)"
_rv_say "  Depois: git push  (o hook pre-push empurra ${NOTES_REF}; se empurrou com --no-verify: git push ${REMOTE} ${NOTES_REF},"
_rv_say "  ou, se o remoto recusa refs/notes/*: git push ${REMOTE} ${NOTES_REF}:${NOTES_MIRROR_REF})"
_rv_say "  e re-execute este check ou faça um push novo."
_rv_say "  Se o push saiu sem o hook barrar, o portão não está ativo nesse clone: git config core.hooksPath $(review_hooks_rel)"
_rv_say "  (ou abra o Claude Code no clone: o SessionStart do .claude/settings.json ativa sozinho)."
exit 1
