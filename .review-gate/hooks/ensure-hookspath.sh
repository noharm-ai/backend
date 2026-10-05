#!/usr/bin/env bash
# Ativa o portão (core.hooksPath) no clone onde este arquivo está vendorizado.
#
#   bash .review-gate/hooks/ensure-hookspath.sh
#
# Quem chama: o hook SessionStart do Claude Code, que o install.sh grava em
# .claude/settings.json do repo consumidor. O git não roda nada do repo no
# clone (é proteção, não esquecimento), então "cada dev, uma vez por clone:
# git config core.hooksPath" era passo manual — e esquecido. Todo dev abre o
# Claude Code no clone (a revisão depende dele), e é nessa primeira sessão que
# o portão liga. A regra mora em lib.sh:review_ensure_hookspath.
#
# stdout é o protocolo do hook do Claude Code: quando configurou ou quando o
# hooksPath é de outra ferramenta, um JSON {"systemMessage": …} para o dev VER
# o que aconteceu na sessão; no resto, nada. Diagnóstico em stderr (_rv_say).
# Sempre rc 0: nenhum problema aqui pode atrapalhar a sessão do Claude Code.
set -uo pipefail

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" || exit 0
# shellcheck source=lib.sh
source "${HOOK_DIR}/lib.sh" || exit 0
cd "$HOOK_DIR" 2>/dev/null || exit 0

review_ensure_hookspath; rc=$?
rel="$(review_hooks_rel)"
case "$rc" in
    10) printf '{"systemMessage": "[revisao] core.hooksPath=%s configurado neste clone: o pre-push da revisão essencial está ativo. Desfazer: git config --unset core.hooksPath"}\n' "$rel" ;;
    11) printf '{"systemMessage": "[revisao] ATENÇÃO: core.hooksPath aponta para outra pasta; o pre-push da revisão essencial NÃO está ativo neste clone. Para ativar: git config core.hooksPath %s"}\n' "$rel" ;;
esac
exit 0
