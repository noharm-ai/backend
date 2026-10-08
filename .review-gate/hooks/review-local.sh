#!/usr/bin/env bash
# Revisão essencial HEADLESS, rodada pelo dev antes do push.
#
#   bash .review-gate/hooks/review-local.sh [sha] [--remote r] [--branch b] [--base <branch>]
#
# Roda a skill pr-review-essentials em modo local via `claude -p` com o LOGIN
# do Claude Code do próprio dev (nenhuma chave de API: em modo -p não-bare o
# Claude Code usa a assinatura salva quando ANTHROPIC_API_KEY não está no
# ambiente). Imprime o corpo da review em stdout e grava a prova via
# review-receipt.sh. É isto que o pre-push manda rodar quando bloqueia.
#
# Alternativa equivalente: numa sessão interativa do Claude Code neste clone,
# `/pr-review-essentials modo local` — a skill escreve o corpo e chama o
# review-receipt.sh ela mesma.
#
# O que bloqueia aqui é só "a revisão não rodou até o fim" (sem login, sem
# claude, saída sem o cabeçalho). Achado NÃO bloqueia: o veredito é humano.
#
# Botões (só estes dois, de propósito — um NOHARM_REVIEW_SKIP acabaria no
# .bashrc e desligaria o portão para sempre em silêncio; `--no-verify` é por
# invocação e visível na linha de comando):
#   NOHARM_REVIEW_CLAUDE_BIN      caminho do binário claude (também o seam dos testes)
#   NOHARM_REVIEW_ALLOW_API_KEY=1 deixa ANTHROPIC_API_KEY passar para o claude
#                                 (por padrão ela é removida: cobrar da chave de
#                                 alguém sem avisar é consentimento inferido)
set -uo pipefail

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${HOOK_DIR}/lib.sh"

SHA="HEAD"; REMOTE="origin"; BRANCH=""; BASE=""
while [ $# -gt 0 ]; do
    case "$1" in
        --remote) REMOTE="$2"; shift 2 ;;
        --branch) BRANCH="$2"; shift 2 ;;
        --base)   BASE="$2";   shift 2 ;;
        -h|--help) sed -n '2,6p' "$0" >&2; exit 2 ;;
        *) SHA="$1"; shift ;;
    esac
done

review_python || { _rv_say "Python 3 ausente (procurei python3, python e py -3): necessário para ler a saída JSON do claude"; exit 2; }
TOPLEVEL="$(git rev-parse --show-toplevel 2>/dev/null)" || { _rv_say "rode dentro do clone"; exit 2; }
# Quem chega aqui à mão (CI vermelho, hook nunca ativado) sai com o portão ligado.
review_ensure_hookspath || true
SHA="$(git rev-parse --verify "${SHA}^{commit}" 2>/dev/null)" || { _rv_say "sha inválido"; exit 2; }
review_load_config "$REMOTE"
[ -n "$BRANCH" ] || BRANCH="$(git symbolic-ref --short -q HEAD 2>/dev/null || printf 'HEAD')"
[ -n "$BASE" ] || BASE="$(review_base_branch "$BRANCH")"
BASE_REF="refs/remotes/${REMOTE}/${BASE}"

review_fetch_base "$REMOTE" "$BASE" || exit 2
MB="$(git merge-base "$BASE_REF" "$SHA" 2>/dev/null)" \
    || { _rv_say "merge-base com ${REMOTE}/${BASE} falhou (clone raso? git fetch --unshallow)"; exit 2; }
PID="$(review_patch_id "$MB" "$SHA")"
if [ -z "$PID" ]; then
    _rv_say "nada a revisar: ${BRANCH} não difere de ${REMOTE}/${BASE}"
    exit 0
fi
if review_note_valid "$SHA" "$BASE_REF" 2>/dev/null; then
    _rv_say "já revisado: nota válida em ${SHA:0:12} (patch-id ${PID:0:12})"
    exit 0
fi

BIN="${NOHARM_REVIEW_CLAUDE_BIN:-claude}"
if ! command -v "$BIN" >/dev/null 2>&1; then
    _rv_say "Revisão essencial NÃO rodou: (${BIN}) não encontrado."
    _rv_say "Instale o Claude Code e faça login (claude /login), ou aponte NOHARM_REVIEW_CLAUDE_BIN para o binário."
    _rv_say "Para empurrar sem a revisão local: git push --no-verify — o check obrigatório (revisao-essencial) no CI continua exigindo a nota na PR."
    exit 1
fi

if [ -n "${ANTHROPIC_API_KEY:-}" ] && [ "${NOHARM_REVIEW_ALLOW_API_KEY:-}" != "1" ]; then
    _rv_say "ANTHROPIC_API_KEY ignorada: a revisão usa o login do Claude Code. Exporte NOHARM_REVIEW_ALLOW_API_KEY=1 para cobrar da chave."
    unset ANTHROPIC_API_KEY
fi
unset CLAUDECODE   # sessão aninhada (dev rodando o push de dentro de um Claude Code) não deve confundir o filho

nfiles="$(git diff --name-only "$MB" "$SHA" | wc -l | tr -d ' ')"
_rv_say "rodando a revisão essencial de ${BRANCH} contra ${REMOTE}/${BASE} (${nfiles} arquivo(s)) — 1 a 3 min, sem saída até terminar"

# O que o diff acumulado esconde (lib.sh:review_ghost_lines): linha commitada e
# apagada dentro da branch não está em (git diff MB SHA), mas vai no push. Vai
# no prompt quando cabe — entregue, não depende do modelo lembrar de pedir. O
# teto é pelo argv do Windows (32K chars no CreateProcess): acima dele o prompt
# diz quantas linhas há e a skill roda o review-history.sh, que está na allowlist.
HOOKS_REL="$(review_hooks_rel)"
GHOST_MAX_BYTES=12000
ghost="$(review_ghost_lines "$MB" "$SHA")"
if [ -z "$ghost" ]; then
    HIST="Histórico da branch (commits ${MB:0:12}..${SHA:0:12}): nenhuma linha adicionada em commit intermediário foi removida depois — nada a checar além do diff."
elif [ "$(printf '%s' "$ghost" | wc -c | tr -d ' ')" -le "$GHOST_MAX_BYTES" ]; then
    nghost="$(printf '%s\n' "$ghost" | grep -c -v '^#')"
    _rv_say "histórico: ${nghost} linha(s) adicionada(s) e removida(s) dentro da branch vão para a revisão (não estão no diff final)"
    HIST="Histórico da branch: as linhas abaixo foram ADICIONADAS por um commit e REMOVIDAS/alteradas por outro
commit desta branch — não estão em (git diff ${MB} ${SHA}), mas o push leva o commit. Aplique os pontos
1 e 2 (secret e infra leak) a elas, com a regra de mascaramento (seção Histórico da branch da skill):
${ghost}"
else
    nghost="$(printf '%s\n' "$ghost" | grep -c -v '^#')"
    _rv_say "histórico: ${nghost} linha(s) adicionada(s) e removida(s) dentro da branch — grande demais para o prompt; a skill roda o review-history.sh"
    HIST="Histórico da branch: ${nghost} linhas foram ADICIONADAS por um commit e REMOVIDAS/alteradas por outro
commit desta branch — não estão em (git diff ${MB} ${SHA}), mas o push leva o commit. Rode
(bash ${HOOKS_REL}/review-history.sh ${MB} ${SHA}) e aplique os pontos 1 e 2 (secret e infra leak) à saída,
com a regra de mascaramento (seção Histórico da branch da skill)."
fi

PROMPT="/pr-review-essentials modo local: branch ${BRANCH} para ${BASE}. Merge-base ${MB}, head ${SHA}.
Use exatamente (git diff ${MB} ${SHA}) e (git log --oneline ${MB}..${SHA}). Não há PR nem GitHub aqui:
responda SÓ com o corpo da review no template da skill, primeira linha começando por (${REVIEW_MARKER}).
Não escreva arquivos nem grave recibo — quem grava é o script que te chamou.
${HIST}"

RUNNER=()
if command -v timeout >/dev/null 2>&1; then RUNNER=(timeout 900); else _rv_say "sem (timeout) no PATH: rodando sem teto de tempo"; fi

cd "$TOPLEVEL" || exit 2
# stderr do claude vai para um mktemp (nome imprevisível — nada de caminho fixo
# em /tmp, que em máquina compartilhada é alvo de symlink) e é reproduzido
# depois, para não se misturar ao JSON que vem por stdout.
errf="$(mktemp)"
# ${RUNNER[@]+…}: array vazio sob set -u quebra no bash 3.2 do macOS.
out="$(${RUNNER[@]+"${RUNNER[@]}"} "$BIN" -p "$PROMPT" \
        --permission-mode dontAsk \
        --allowedTools "Skill,Read,Grep,Glob,Bash(git diff:*),Bash(git log:*),Bash(git show:*),Bash(bash ${HOOKS_REL}/review-history.sh:*)" \
        --strict-mcp-config \
        --output-format json \
        --max-turns "$REVIEW_MAX_TURNS" </dev/null 2>"$errf")"
rc=$?
[ -s "$errf" ] && cat "$errf" >&2
rm -f "$errf"

# Campos do JSON via Python (jq não é garantido na máquina do dev). Bytes UTF-8
# explícitos nos dois lados, e PYTHONUTF8/PYTHONIOENCODING por cima: no Windows
# o Python < 3.15 lê e escreve pipes em cp1252, e o corpo tem (Revisão), ✅, ⚠️.
_json_field() {
    printf '%s' "$out" | PYTHONUTF8=1 PYTHONIOENCODING=utf-8 "${REVIEW_PYTHON[@]}" -c '
import json, sys
try:
    d = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
except Exception:
    sys.exit(3)
v = d.get(sys.argv[1])
if v is None:
    sys.exit(0)
sys.stdout.buffer.write(((v if isinstance(v, str) else json.dumps(v)) + "\n").encode("utf-8"))' "$1" 2>/dev/null
}
result="$(_json_field result)"; jrc=$?
if [ "$jrc" -eq 3 ]; then
    printf '%s\n' "$out" >&2
    _rv_say "Revisão essencial NÃO rodou até o fim (rc=${rc}): saída do claude não é JSON. Nenhum recibo gravado."
    _rv_say "Causas comuns: sem login (claude /login), binário errado em NOHARM_REVIEW_CLAUDE_BIN. Alternativa: git push --no-verify (o CI ainda exige a nota)."
    exit 1
fi
is_error="$(_json_field is_error)"
subtype="$(_json_field subtype)"
cost="$(_json_field total_cost_usd)"
session="$(_json_field session_id)"

# O corpo vai para stdout SEMPRE — bloqueado ou não, o dev tem de ler.
printf '%s\n' "$result"

first="$(printf '%s\n' "$result" | awk 'NF { print; exit }')"
case "$first" in "$REVIEW_MARKER"*) has_marker=1 ;; *) has_marker=0 ;; esac
if [ "$rc" -ne 0 ] || [ "$is_error" = "true" ] || [ "$has_marker" -ne 1 ]; then
    _rv_say "Revisão essencial NÃO rodou até o fim (rc=${rc}, subtype=${subtype:-?}): a saída não começa com (${REVIEW_MARKER}). Nenhum recibo gravado."
    _rv_say "Causas comuns: sem login (claude /login), --max-turns estourado em diff grande, skill não encontrada (rode da raiz do clone)."
    _rv_say "Alternativa: git push --no-verify (o CI ainda exige a nota na PR)."
    exit 1
fi

body="$(mktemp)"
printf '%s\n' "$result" > "$body"
bash "${HOOK_DIR}/review-receipt.sh" "$SHA" "$body" --remote "$REMOTE" --branch "$BRANCH" --base "$BASE" --origem headless
rrc=$?
rm -f "$body"
[ "$rrc" -eq 0 ] || exit "$rrc"
_rv_say "OK — custo estimado US\$ ${cost:-?}, sessão ${session:-?}. Achados acima são para VOCÊ ler: não bloqueiam o push. Agora: git push"
