#!/usr/bin/env bash
# Grava a PROVA de que a revisão essencial rodou: nota em refs/notes/review.
#
#   bash .review-gate/hooks/review-receipt.sh <sha> <arquivo-com-o-corpo> [--remote r] [--branch b] [--base <branch>] [--origem headless|sessao]
#
# Quem chama: review-local.sh (revisão headless, origem=headless) e a skill
# pr-review-essentials em modo local numa sessão do Claude Code (origem=sessao,
# o modelo escreve o corpo num arquivo e roda este script). Determinístico de
# propósito: o modelo não decide o formato da prova nem o patch-id — só entrega
# o corpo. A validação da prova (lib.sh: review_note_valid) é quem manda; este
# script só produz o que ela aceita.
set -uo pipefail

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${HOOK_DIR}/lib.sh"

usage() {
    echo "uso: review-receipt.sh <sha> <arquivo-corpo> [--remote r] [--branch b] [--base <branch>] [--origem x]" >&2
    exit 2
}

SHA=""; BODY=""; REMOTE="origin"; BRANCH=""; BASE=""; ORIGEM="sessao"
while [ $# -gt 0 ]; do
    case "$1" in
        --remote) REMOTE="$2"; shift 2 ;;
        --branch) BRANCH="$2"; shift 2 ;;
        --base)   BASE="$2";   shift 2 ;;
        --origem) ORIGEM="$2"; shift 2 ;;
        -h|--help) usage ;;
        *) if [ -z "$SHA" ]; then SHA="$1"; elif [ -z "$BODY" ]; then BODY="$1"; else usage; fi; shift ;;
    esac
done
[ -n "$SHA" ] && [ -n "$BODY" ] || usage
[ -f "$BODY" ] || { _rv_say "arquivo do corpo não existe: $BODY"; exit 2; }

SHA="$(git rev-parse --verify "${SHA}^{commit}" 2>/dev/null)" || { _rv_say "sha inválido"; exit 2; }
review_load_config "$REMOTE"
[ -n "$BRANCH" ] || BRANCH="$(git symbolic-ref --short -q HEAD 2>/dev/null || true)"
[ -n "$BASE" ] || BASE="$(review_base_branch "$BRANCH")"

# O corpo tem de começar pelo cabeçalho da skill: é o que o pre-push e o CI
# procuram. Corpo sem ele é uma revisão que não terminou — não vira prova.
first="$(awk 'NF { print; exit }' "$BODY")"
case "$first" in
    "$REVIEW_MARKER"*) ;;
    *) _rv_say "corpo não começa com (${REVIEW_MARKER}) — a revisão não terminou; nada gravado"; exit 1 ;;
esac

review_fetch_base "$REMOTE" "$BASE" || exit 2
MB="$(git merge-base "refs/remotes/${REMOTE}/${BASE}" "$SHA" 2>/dev/null)" \
    || { _rv_say "merge-base com ${REMOTE}/${BASE} falhou (clone raso? git fetch --unshallow)"; exit 2; }
PID="$(review_patch_id "$MB" "$SHA")"
[ -n "$PID" ] || { _rv_say "diff vazio contra ${REMOTE}/${BASE}: nada a revisar, nada a gravar"; exit 1; }

review_note_write "$SHA" "$PID" "$MB" "${REMOTE}/${BASE}" "$ORIGEM" "$BODY" \
    || { _rv_say "git notes add falhou"; exit 2; }
_rv_say "recibo gravado: nota em ${SHA:0:12}, patch-id ${PID:0:12}, base ${REMOTE}/${BASE} (origem ${ORIGEM})"
