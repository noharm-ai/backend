#!/usr/bin/env bash
# Suíte do portão de revisão essencial (hooks/): pre-push, review-local.sh,
# review-receipt.sh, review-verify.sh e lib.sh.
#
# Tudo roda num repo temporário com um origin bare, `core.hooksPath` apontando
# para os hooks REAIS ao lado desta suíte, e um `claude` de mentira em
# NOHARM_REVIEW_CLAUDE_BIN — o claude de verdade do dev nunca é chamado daqui.
# Sem rede, sem Docker: só git e python3.
#
# O que a suíte trava, em resumo: branch sem nota não sai da máquina; nota
# válida deixa sair e vai junto (refs/notes/review no origin); amend/rebase sem
# mudar hunks reaproveita a prova; mudança de conteúdo bloqueia de novo;
# develop/main/tag/delete passam sem revisão; dois devs empurrando notas não se
# atropelam; o verificador do CI aceita e recusa pelos mesmos motivos do hook;
# o portão se ativa sozinho (ensure-hookspath.sh) sem pisar em hooksPath alheio;
# e o cabeçalho que os scripts procuram é o do template da skill.
set -uo pipefail

# Layout igual no repo do review-gate (hooks/ + test/) e vendorizado num
# consumidor (.review-gate/hooks + .review-gate/test): os hooks ficam ao lado.
GATE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOKS="${GATE_DIR}/hooks"
if [ -f "${GATE_DIR}/skill/pr-review-essentials/SKILL.md" ]; then
    SKILL="${GATE_DIR}/skill/pr-review-essentials/SKILL.md"          # repo do review-gate
else
    SKILL="$(cd "$GATE_DIR/.." && pwd)/.claude/skills/pr-review-essentials/SKILL.md"   # consumidor
fi

PASS=0; FAIL=0
_ok()   { echo "[OK] $*";       PASS=$((PASS + 1)); }
_fail() { echo "[FAIL] $*" >&2; FAIL=$((FAIL + 1)); }
_test() { echo ""; echo "[TEST] $*"; }
_assert_rc() {  # <esperado> <obtido> <msg>
    if [ "$1" -eq "$2" ]; then _ok "$3 (rc=$2)"; else _fail "$3 — rc esperado $1, obtido $2"; fi
}
_assert_contains() {  # <texto> <trecho> <msg>
    case "$1" in *"$2"*) _ok "$3" ;; *) _fail "$3 — não achei ($2) em:"$'\n'"$1" ;; esac
}
_assert_not_contains() {
    case "$1" in *"$2"*) _fail "$3 — achei ($2) e não devia" ;; *) _ok "$3" ;; esac
}
# Quantos \r há no arquivo — por tr/wc, não grep (no Git Bash do Windows o CR não é confiável no grep/sed).
_cr_count() { tr -cd '\r' < "$1" | wc -c | tr -d ' '; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
export HOME="$WORK/home"; mkdir -p "$HOME"
export GIT_CONFIG_NOSYSTEM=1
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@x GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@x
unset ANTHROPIC_API_KEY NOHARM_REVIEW_ALLOW_API_KEY NOHARM_REVIEW_IN_SYNC CLAUDECODE
export GIT_TERMINAL_PROMPT=0

# --- claude de mentira ------------------------------------------------------
STUB_LOG="$WORK/stub.log"; : > "$STUB_LOG"
STUB_ENV="$WORK/stub.env"; : > "$STUB_ENV"
mkdir -p "$WORK/bin"
cat > "$WORK/bin/claude" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" | tr '\n' ' ' >> "$STUB_LOG"; echo >> "$STUB_LOG"
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then echo "key=present" >> "$STUB_ENV"; else echo "key=absent" >> "$STUB_ENV"; fi
case "${STUB_MODE:-marker}" in
    marker)   printf '{"type":"result","subtype":"success","is_error":false,"result":"## Revisão essencial (stub)\\n\\n**Secret leaks:** ✅ nada encontrado\\n","session_id":"sess-1","total_cost_usd":0.01}\n' ;;
    nomarker) printf '{"type":"result","subtype":"success","is_error":false,"result":"não consegui","session_id":"s","total_cost_usd":0}\n' ;;
    fail)     echo "stub: erro simulado" >&2; exit 1 ;;
    notjson)  echo "isto não é json" ;;
esac
STUB
chmod +x "$WORK/bin/claude"
export STUB_LOG STUB_ENV
export NOHARM_REVIEW_CLAUDE_BIN="$WORK/bin/claude"
stub_calls() { wc -l < "$STUB_LOG" | tr -d ' '; }

# --- repo + origin -------------------------------------------------------------
git init -q --bare "$WORK/origin.git"
git init -q "$WORK/repo"
cd "$WORK/repo" || exit 1
git remote add origin "$WORK/origin.git"
git checkout -q -b develop
echo base > base.txt && git add base.txt && git commit -q -m "base"
git push -q origin develop 2>/dev/null
git checkout -q -b main && git push -q origin main 2>/dev/null
git checkout -q develop
git config core.hooksPath "$HOOKS"

commit_file() {  # <arquivo> <conteúdo> <msg>
    printf '%s\n' "$2" > "$1" && git add "$1" && git commit -q -m "$3"
}
push() {  # <args…> → PUSH_OUT, PUSH_RC
    PUSH_OUT="$(git push "$@" 2>&1)"; PUSH_RC=$?
}
remote_has() { git ls-remote --exit-code origin "$1" >/dev/null 2>&1; }
write_receipt() {  # <sha> [args…] — corpo válido
    local body="$WORK/body.$$"
    printf '## Revisão essencial (teste)\n\n**Secret leaks:** ✅ nada encontrado\n' > "$body"
    bash "$HOOKS/review-receipt.sh" "$@" "$body" 2>"$WORK/receipt.err"; RECEIPT_RC=$?
    RECEIPT_ERR="$(cat "$WORK/receipt.err")"
    rm -f "$body"
}
note_of() { git notes --ref=refs/notes/review show "$1" 2>/dev/null; }

# ---------------------------------------------------------------------------
_test "scripts executáveis e com sintaxe válida"
for f in pre-push lib.sh review-local.sh review-receipt.sh review-verify.sh review-history.sh ensure-hookspath.sh; do
    [ -x "$HOOKS/$f" ] && _ok "$f executável" || _fail "$f não é executável"
done
bash -n "$HOOKS/pre-push" "$HOOKS"/*.sh && _ok "bash -n" || _fail "bash -n"
# Fim de linha é contrato: bash não sobrevive a CRLF; o .cmd (cmd.exe) é CRLF de propósito.
for f in pre-push lib.sh review-local.sh review-receipt.sh review-verify.sh review-history.sh ensure-hookspath.sh; do
    if [ "$(_cr_count "$HOOKS/$f")" -eq 0 ]; then _ok "$f é LF"; else _fail "$f tem CRLF"; fi
done
[ -f "$HOOKS/review-local.cmd" ] && _ok "review-local.cmd existe" || _fail "review-local.cmd ausente"
[ "$(_cr_count "$HOOKS/review-local.cmd")" -gt 0 ] && [ "$(_cr_count "$HOOKS/review-local.cmd")" = "$(wc -l < "$HOOKS/review-local.cmd" | tr -d ' ')" ] \
    && _ok "review-local.cmd é CRLF em todas as linhas" || _fail "review-local.cmd sem CRLF uniforme"
grep -q 'review-local.sh' "$HOOKS/review-local.cmd" && _ok ".cmd chama o review-local.sh" || _fail ".cmd não chama o review-local.sh"
grep -q 'bash.exe' "$HOOKS/review-local.cmd" && _ok ".cmd procura o bash.exe do Git for Windows" || _fail ".cmd não procura o bash.exe"

# ---------------------------------------------------------------------------
_test "branch sem revisão: push bloqueado com instruções"
git checkout -q -b feature/a
commit_file a.txt "conteudo a" "feat: a"
push origin feature/a
_assert_rc 1 "$PUSH_RC" "push bloqueado"
_assert_contains "$PUSH_OUT" "review-local.sh" "mensagem manda rodar o review-local.sh"
_assert_contains "$PUSH_OUT" "--no-verify" "mensagem explica o --no-verify"
_assert_contains "$PUSH_OUT" "modo local" "mensagem cita a skill em modo local"
_assert_contains "$PUSH_OUT" "review-local.cmd" "mensagem cita o atalho do Windows (PowerShell/cmd)"
# Caminho dos hooks relativo à raiz do clone: absoluto aqui era o bug do /var → /private/var
# (macOS) e do /c/… vs C:/… (Windows).
_assert_not_contains "$PUSH_OUT" "bash /" "caminho do review-local.sh é relativo à raiz do clone"
remote_has refs/heads/feature/a && _fail "feature/a chegou ao origin sem revisão" || _ok "feature/a não chegou ao origin"
[ "$(stub_calls)" = "0" ] && _ok "o hook não chamou claude" || _fail "o hook chamou claude"

# ---------------------------------------------------------------------------
_test "review-receipt.sh: corpo sem o cabeçalho não vira prova"
printf 'qualquer coisa\n' > "$WORK/bad"
bash "$HOOKS/review-receipt.sh" HEAD "$WORK/bad" >/dev/null 2>"$WORK/err"; rc=$?
_assert_rc 1 "$rc" "recusado"
_assert_contains "$(cat "$WORK/err")" "não começa com" "diz por quê"
[ -z "$(note_of HEAD)" ] && _ok "nenhuma nota gravada" || _fail "nota gravada indevidamente"

_test "review-receipt.sh: corpo válido grava nota com cabeçalho completo"
write_receipt HEAD
_assert_rc 0 "$RECEIPT_RC" "gravado"
note="$(note_of HEAD)"
for k in patch_id sha base merge_base data origem; do
    _assert_contains "$note" "${k}=" "nota tem ${k}="
done
_assert_contains "$note" "base=origin/develop" "base é origin/develop para feature/*"
_assert_contains "$note" "origem=sessao" "origem padrão é sessao"
mb_dev="$(git rev-parse origin/develop)"
_assert_contains "$note" "merge_base=${mb_dev}" "merge_base é o tip da develop"

# ---------------------------------------------------------------------------
_test "branch com nota válida: push passa e a nota vai junto"
push origin feature/a
_assert_rc 0 "$PUSH_RC" "push permitido"
_assert_contains "$PUSH_OUT" "revisão essencial OK" "hook confirma"
remote_has refs/heads/feature/a && _ok "feature/a no origin" || _fail "feature/a não chegou"
remote_has refs/notes/review && _ok "refs/notes/review no origin" || _fail "notas não chegaram ao origin"
SHA_A="$(git rev-parse HEAD)"

# ---------------------------------------------------------------------------
_test "amend só de mensagem: prova copiada, push passa"
git commit -q --amend -m "feat: a (mensagem melhor)"
[ "$(git rev-parse HEAD)" != "$SHA_A" ] && _ok "sha mudou" || _fail "sha não mudou"
push --force-with-lease origin feature/a
_assert_rc 0 "$PUSH_RC" "push permitido"
_assert_contains "$PUSH_OUT" "copiado" "recibo copiado pelo patch-id"
[ -n "$(note_of HEAD)" ] && _ok "novo sha tem nota" || _fail "novo sha sem nota"

# ---------------------------------------------------------------------------
_test "develop anda em arquivo alheio + rebase: prova ainda vale"
git checkout -q develop
commit_file outro.txt "mudanca na develop" "chore: develop anda"
push origin develop
_assert_rc 0 "$PUSH_RC" "push da develop passa sem revisão"
_assert_contains "$PUSH_OUT" "ref protegido" "develop é pulada pelo hook"
git checkout -q feature/a
git rebase -q origin/develop 2>/dev/null
push --force-with-lease origin feature/a
_assert_rc 0 "$PUSH_RC" "push pós-rebase permitido"
_assert_not_contains "$PUSH_OUT" "NÃO rodou" "não pediu revisão nova"

# ---------------------------------------------------------------------------
_test "conteúdo novo na branch: bloqueia de novo"
commit_file a.txt "conteudo a v2" "feat: a v2"
push origin feature/a
_assert_rc 1 "$PUSH_RC" "bloqueado"
_assert_contains "$PUSH_OUT" "NÃO rodou" "diz que a revisão não rodou para este conteúdo"

_test "nota existente mas conteúdo divergente: o motivo aparece"
# Forja uma nota com patch_id errado no HEAD para ver a mensagem de recusa.
printf 'patch_id=deadbeef\nsha=x\nbase=origin/develop\nmerge_base=%s\ndata=x\norigem=teste\n---\n## Revisão essencial (forjada)\n' "$(git merge-base origin/develop HEAD)" > "$WORK/forged"
git notes --ref=refs/notes/review add -f -F "$WORK/forged" HEAD
push origin feature/a
_assert_rc 1 "$PUSH_RC" "bloqueado"
_assert_contains "$PUSH_OUT" "conteúdo mudou" "explica que o patch-id diverge"
git notes --ref=refs/notes/review remove HEAD >/dev/null 2>&1
write_receipt HEAD
push origin feature/a
_assert_rc 0 "$PUSH_RC" "com a prova certa, passa"

# ---------------------------------------------------------------------------
_test "tag e delete passam sem revisão"
git tag v0.0.0-teste
push origin v0.0.0-teste
_assert_rc 0 "$PUSH_RC" "push de tag permitido"
git checkout -q -b feature/del develop
commit_file del.txt "x" "tmp"
push --no-verify origin feature/del
_assert_rc 0 "$PUSH_RC" "(--no-verify sobe a branch descartável)"
push origin :feature/del
_assert_rc 0 "$PUSH_RC" "delete permitido"
_assert_contains "$PUSH_OUT" "pulado (delete)" "hook diz que pulou o delete"

# ---------------------------------------------------------------------------
_test "hotfix/*: base é main"
git checkout -q -b hotfix/h main
commit_file fix.txt "fix" "fix: h"
push origin hotfix/h
_assert_rc 1 "$PUSH_RC" "bloqueado sem prova"
write_receipt HEAD
_assert_contains "$(note_of HEAD)" "base=origin/main" "nota aponta origin/main"
_assert_contains "$(note_of HEAD)" "merge_base=$(git rev-parse origin/main)" "merge_base é o tip da main"
push origin hotfix/h
_assert_rc 0 "$PUSH_RC" "passa com a prova"

# ---------------------------------------------------------------------------
_test "duas branches num push: uma sem prova bloqueia tudo, as duas são avaliadas"
git checkout -q -b feature/b develop; commit_file b.txt "b" "feat: b"; write_receipt HEAD
git checkout -q -b feature/c develop; commit_file c.txt "c" "feat: c"
push origin feature/b feature/c
_assert_rc 1 "$PUSH_RC" "bloqueado"
_assert_contains "$PUSH_OUT" "feature/b: revisão essencial OK" "feature/b avaliada como OK"
_assert_contains "$PUSH_OUT" "conteúdo de feature/c" "feature/c apontada como sem revisão"
remote_has refs/heads/feature/b && _fail "feature/b subiu apesar do bloqueio" || _ok "nada subiu (push é tudo ou nada)"
write_receipt HEAD
push origin feature/b feature/c
_assert_rc 0 "$PUSH_RC" "com as duas provas, passa"

# ---------------------------------------------------------------------------
_test "worktree: prova e hook funcionam de dentro dela"
git worktree add -q "$WORK/wt" -b feature/wt develop
( cd "$WORK/wt" && commit_file wt.txt "wt" "feat: wt" && write_receipt HEAD && push origin feature/wt; exit $PUSH_RC )
_assert_rc 0 "$?" "push da worktree permitido"
git worktree remove --force "$WORK/wt"

# ---------------------------------------------------------------------------
_test "outro dev empurrou notas antes: o hook mescla e não é rejeitado"
git clone -q "$WORK/origin.git" "$WORK/dev2" 2>/dev/null
(
    cd "$WORK/dev2" || exit 1
    git fetch -q origin "+refs/notes/review:refs/notes/review"
    git notes --ref=refs/notes/review add -f -m "patch_id=zz\nsha=x\n---\n## Revisão essencial (dev2)" "$(git rev-parse origin/develop)"
    git push -q origin refs/notes/review:refs/notes/review 2>/dev/null
) && _ok "dev2 empurrou uma nota" || _fail "setup do dev2 falhou"
git checkout -q -b feature/d develop; commit_file d.txt "d" "feat: d"; write_receipt HEAD
push origin feature/d
_assert_rc 0 "$PUSH_RC" "push permitido apesar das notas remotas terem andado"
_assert_not_contains "$PUSH_OUT" "não consegui empurrar" "notas sincronizadas"
git fetch -q origin "+refs/notes/review:refs/notes/review-check"
n_notes="$(git notes --ref=refs/notes/review-check list | wc -l | tr -d ' ')"
[ "$n_notes" -ge 2 ] && _ok "origin tem as notas dos dois devs (${n_notes})" || _fail "origin perdeu notas (${n_notes})"

# ---------------------------------------------------------------------------
_test "remoto que recusa refs/notes: o erro real aparece e a prova vai pelo espelho (branch)"
# Um pre-receive no origin que recusa qualquer ref fora de refs/heads/* simula o
# proxy das sessões remotas do Claude Code, que só libera branches (foi assim que
# o 403 apareceu em campo).
cat > "$WORK/origin.git/hooks/pre-receive" <<'PRE'
#!/usr/bin/env bash
while read -r old new ref; do
    case "$ref" in refs/heads/*) ;; *) echo "servidor: ref ${ref} nao permitido (HTTP 403 simulado)" >&2; exit 1 ;; esac
done
PRE
chmod +x "$WORK/origin.git/hooks/pre-receive"
git checkout -q -b feature/notes-403 develop; commit_file n403.txt "x" "feat: n403"; write_receipt HEAD
SHA_403="$(git rev-parse HEAD)"
push origin feature/notes-403
_assert_rc 0 "$PUSH_RC" "branch empurrada"
remote_has refs/heads/feature/notes-403 && _ok "feature/notes-403 no origin" || _fail "branch não subiu"
_assert_contains "$PUSH_OUT" "HTTP 403 simulado" "o erro REAL do servidor é mostrado"
_assert_not_contains "$PUSH_OUT" "outro dev empurrou antes" "não adivinha non-fast-forward"
_assert_contains "$PUSH_OUT" "prova entregue pelo espelho review-gate/notes" "diz que a prova foi pelo espelho"
_assert_not_contains "$PUSH_OUT" "não consegui empurrar" "não anuncia falha quando o espelho aceitou"
_assert_not_contains "$PUSH_OUT" "NÃO rodou" "o push do espelho não passa pelo portão"
remote_has refs/heads/review-gate/notes && _ok "espelho refs/heads/review-gate/notes no origin" || _fail "espelho não chegou"
git --git-dir="$WORK/origin.git" notes --ref=refs/notes/review show "$SHA_403" >/dev/null 2>&1 \
    && _fail "nota chegou ao ref canônico apesar da recusa" || _ok "ref canônico do origin não tem a nota (só o espelho)"

_test "review-verify.sh acha a prova que só está no espelho, mesmo sem identidade de git (runner do CI)"
# Outro dev empurra uma nota no ref canônico por fora do proxy: canônico e espelho
# divergem e o CI precisa de um merge de verdade (commit), que pede identidade.
(
    cd "$WORK/dev2" || exit 1
    git fetch -q origin "+refs/notes/review:refs/notes/review"
    git notes --ref=refs/notes/review add -f -m "patch_id=yy\nsha=x\n---\n## Revisão essencial (dev2 de novo)" "$(git rev-parse origin/main)"
    git --git-dir="$WORK/origin.git" config receive.denyNonFastForwards false
    mv "$WORK/origin.git/hooks/pre-receive" "$WORK/pre-receive.off"
    git push -q origin refs/notes/review:refs/notes/review 2>/dev/null; rc=$?
    mv "$WORK/pre-receive.off" "$WORK/origin.git/hooks/pre-receive"
    exit $rc
) && _ok "dev2 empurrou nota no ref canônico" || _fail "setup do dev2 falhou"
git clone -q "$WORK/origin.git" "$WORK/ci-mirror" 2>/dev/null
out="$(cd "$WORK/ci-mirror" && env -u GIT_AUTHOR_NAME -u GIT_AUTHOR_EMAIL -u GIT_COMMITTER_NAME -u GIT_COMMITTER_EMAIL \
        GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=user.useConfigOnly GIT_CONFIG_VALUE_0=true \
        bash "$HOOKS/review-verify.sh" origin/develop "$SHA_403" 2>"$WORK/err")"; rc=$?
_assert_rc 0 "$rc" "head com prova só no espelho passa"
_assert_contains "$out" "## Revisão essencial" "stdout é o corpo da review"
(cd "$WORK/ci-mirror" && git notes --ref=refs/notes/review show "$(git rev-parse origin/main)" 2>/dev/null) | grep -q "dev2 de novo" \
    && _ok "notas do ref canônico continuam lá (merge, não troca)" || _fail "merge perdeu as notas do canônico: $(cat "$WORK/err")"

_test "remoto que recusa refs/notes E o espelho: a branch segue, os dois erros e os comandos aparecem"
cat > "$WORK/origin.git/hooks/pre-receive" <<'PRE'
#!/usr/bin/env bash
while read -r old new ref; do
    case "$ref" in refs/heads/feature/*) ;; *) echo "servidor: ref ${ref} nao permitido (HTTP 403 simulado)" >&2; exit 1 ;; esac
done
PRE
git checkout -q -b feature/notes-403b develop; commit_file n403b.txt "x" "feat: n403b"; write_receipt HEAD
push origin feature/notes-403b
_assert_rc 0 "$PUSH_RC" "branch empurrada mesmo com as notas recusadas"
remote_has refs/heads/feature/notes-403b && _ok "feature/notes-403b no origin" || _fail "branch não subiu"
_assert_contains "$PUSH_OUT" "ref refs/notes/review nao permitido" "erro do ref canônico, como veio"
_assert_contains "$PUSH_OUT" "ref refs/heads/review-gate/notes nao permitido" "erro do espelho, como veio"
_assert_contains "$PUSH_OUT" "git push origin refs/notes/review" "diz como empurrar as notas à mão"
_assert_contains "$PUSH_OUT" "refs/notes/review:refs/heads/review-gate/notes" "e como empurrar o espelho à mão"
rm -f "$WORK/origin.git/hooks/pre-receive"

_test "push de máquina sem restrição leva as notas do espelho para o ref canônico"
# Outra máquina (clone novo, sem as notas locais de quem revisou na sessão remota).
git clone -q "$WORK/origin.git" "$WORK/dev3" 2>/dev/null
(
    cd "$WORK/dev3" || exit 1
    git config core.hooksPath "$HOOKS"
    git checkout -q -b feature/notes-livre origin/develop; commit_file livre.txt "x" "feat: livre"; write_receipt HEAD
    push origin feature/notes-livre
    printf '%s\n' "$PUSH_OUT" > "$WORK/dev3.out"; exit $PUSH_RC
); rc=$?
_assert_rc 0 "$rc" "push permitido"
_assert_not_contains "$(cat "$WORK/dev3.out")" "espelho" "remoto aceitou o ref canônico, espelho não usado"
git --git-dir="$WORK/origin.git" notes --ref=refs/notes/review show "$SHA_403" >/dev/null 2>&1 \
    && _ok "nota que só estava no espelho agora está no ref canônico" || _fail "nota do espelho não foi para o canônico"

_test "push manual do espelho não passa pelo portão"
push origin refs/notes/review:refs/heads/review-gate/notes
_assert_rc 0 "$PUSH_RC" "push do espelho permitido"
_assert_not_contains "$PUSH_OUT" "NÃO rodou" "hook não pede revisão do espelho"

# ---------------------------------------------------------------------------
_test "review-local.sh: revisão headless grava prova; stdout é só o corpo"
git checkout -q -b feature/e develop; commit_file e.txt "e" "feat: e"
before="$(stub_calls)"
STUB_MODE=marker out="$(bash "$HOOKS/review-local.sh" 2>"$WORK/err")"; rc=$?
_assert_rc 0 "$rc" "rodou"
[ "$(stub_calls)" = "$((before + 1))" ] && _ok "claude chamado uma vez" || _fail "claude chamado $(stub_calls) vez(es)"
first="$(printf '%s\n' "$out" | awk 'NF { print; exit }')"
case "$first" in "## Revisão essencial"*) _ok "stdout começa pelo cabeçalho" ;; *) _fail "stdout: $first" ;; esac
_assert_contains "$(note_of HEAD)" "origem=headless" "nota gravada com origem headless"
args="$(tail -1 "$STUB_LOG")"
for f in "--permission-mode dontAsk" "--output-format json" "--strict-mcp-config" "/pr-review-essentials" "modo local" "--max-turns"; do
    _assert_contains "$args" "$f" "argv tem $f"
done
_assert_contains "$args" "$(git merge-base origin/develop HEAD)" "argv tem o merge-base"
_assert_contains "$args" "$(git rev-parse HEAD)" "argv tem o head"
_assert_not_contains "$args" "Edit" "allowlist sem Edit"
_assert_not_contains "$args" "Write" "allowlist sem Write"
[ "$(tail -1 "$STUB_ENV")" = "key=absent" ] && _ok "sem ANTHROPIC_API_KEY no ambiente do claude" || _fail "chave vazou"
push origin feature/e
_assert_rc 0 "$PUSH_RC" "push passa com a prova headless"

_test "review-local.sh: corpo UTF-8 sobrevive a um Python com pipes em outro encoding (Windows/cp1252)"
# PYTHONIOENCODING=ascii simula o Python do Windows (< 3.15), que lê e escreve pipes em
# cp1252: sem UTF-8 forçado, (Revisão) e ✅ do stub viram UnicodeDecodeError → (não é JSON).
git checkout -q -b feature/utf8 develop; commit_file utf8.txt "u" "feat: utf8"
out="$(PYTHONIOENCODING=ascii STUB_MODE=marker bash "$HOOKS/review-local.sh" 2>"$WORK/err")"; rc=$?
_assert_rc 0 "$rc" "rodou"
_assert_contains "$out" "✅" "stdout preservou o ✅"
_assert_contains "$out" "Revisão" "stdout preservou o (Revisão)"
[ -n "$(note_of HEAD)" ] && _ok "nota gravada" || _fail "sem nota"

_test "review-local.sh: Python descoberto como (python) quando (python3) é o stub da Microsoft Store"
REAL_PY="$(command -v python3)"
mkdir -p "$WORK/pybin"
# O stub da Store: existe no PATH, mas não é um Python — imprime um aviso e sai com erro.
printf '#!/usr/bin/env bash\necho "Python was not found; run without arguments to install from the Microsoft Store" >&2\nexit 9009\n' > "$WORK/pybin/python3"
printf '#!/usr/bin/env bash\nexec "%s" "$@"\n' "$REAL_PY" > "$WORK/pybin/python"
chmod +x "$WORK/pybin/python3" "$WORK/pybin/python"
git checkout -q -b feature/py develop; commit_file py.txt "p" "feat: py"
PATH="$WORK/pybin:$PATH" STUB_MODE=marker bash "$HOOKS/review-local.sh" >/dev/null 2>"$WORK/err"; rc=$?
_assert_rc 0 "$rc" "rodou com (python)"
[ -n "$(note_of HEAD)" ] && _ok "nota gravada" || _fail "sem nota: $(cat "$WORK/err")"
( source "$HOOKS/lib.sh" && PATH="$WORK/pybin:$PATH" review_python && [ "${REVIEW_PYTHON[*]}" = "python" ] ) \
    && _ok "review_python escolheu (python), pulando o stub" || _fail "review_python não escolheu (python)"
_test "review-local.sh: sem nenhum Python 3 → rc 2 e diz o que procurou"
cp "$WORK/pybin/python3" "$WORK/pybin/python"; cp "$WORK/pybin/python3" "$WORK/pybin/py"
git checkout -q -b feature/nopy develop; commit_file nopy.txt "n" "feat: nopy"
PATH="$WORK/pybin:$PATH" bash "$HOOKS/review-local.sh" >/dev/null 2>"$WORK/err"; rc=$?
_assert_rc 2 "$rc" "rc 2"
_assert_contains "$(cat "$WORK/err")" "Python 3 ausente" "mensagem"
_assert_contains "$(cat "$WORK/err")" "py -3" "cita o launcher py do Windows"
[ -z "$(note_of HEAD)" ] && _ok "sem nota" || _fail "nota gravada sem Python"
git checkout -q feature/e

_test "review-local.sh: já revisado não chama claude de novo"
before="$(stub_calls)"
bash "$HOOKS/review-local.sh" >/dev/null 2>"$WORK/err"; rc=$?
_assert_rc 0 "$rc" "rc 0"
_assert_contains "$(cat "$WORK/err")" "já revisado" "diz que já revisou"
[ "$(stub_calls)" = "$before" ] && _ok "claude não chamado" || _fail "claude chamado"

_test "review-local.sh: ANTHROPIC_API_KEY é removida por padrão e passa com opt-in"
git checkout -q -b feature/f develop; commit_file f.txt "f" "feat: f"
ANTHROPIC_API_KEY=sk-teste bash "$HOOKS/review-local.sh" >/dev/null 2>"$WORK/err"
_assert_contains "$(cat "$WORK/err")" "ANTHROPIC_API_KEY ignorada" "avisa que ignorou a chave"
[ "$(tail -1 "$STUB_ENV")" = "key=absent" ] && _ok "chave removida" || _fail "chave passou sem opt-in"
git checkout -q -b feature/g develop; commit_file g.txt "g" "feat: g"
ANTHROPIC_API_KEY=sk-teste NOHARM_REVIEW_ALLOW_API_KEY=1 bash "$HOOKS/review-local.sh" >/dev/null 2>/dev/null
[ "$(tail -1 "$STUB_ENV")" = "key=present" ] && _ok "com opt-in a chave passa" || _fail "opt-in ignorado"

_test "review-local.sh: saídas ruins não viram prova"
for mode in nomarker fail notjson; do
    git checkout -q -b "feature/bad-$mode" develop; commit_file "bad-$mode.txt" "$mode" "feat: $mode"
    STUB_MODE="$mode" bash "$HOOKS/review-local.sh" >/dev/null 2>"$WORK/err"; rc=$?
    _assert_rc 1 "$rc" "modo $mode bloqueia"
    _assert_contains "$(cat "$WORK/err")" "NÃO rodou até o fim" "modo $mode: mensagem"
    [ -z "$(note_of HEAD)" ] && _ok "modo $mode: sem nota" || _fail "modo $mode: nota gravada"
done
_test "review-local.sh: claude ausente"
git checkout -q -b feature/nobin develop; commit_file nobin.txt "x" "feat: nobin"
NOHARM_REVIEW_CLAUDE_BIN="$WORK/nao-existe" bash "$HOOKS/review-local.sh" >/dev/null 2>"$WORK/err"; rc=$?
_assert_rc 1 "$rc" "bloqueia"
_assert_contains "$(cat "$WORK/err")" "não encontrado" "diz que não achou o binário"
_assert_contains "$(cat "$WORK/err")" "--no-verify" "explica o --no-verify"

# ---------------------------------------------------------------------------
_test "review-verify.sh (o que o CI roda): aceita e recusa pelos mesmos motivos"
git clone -q "$WORK/origin.git" "$WORK/ci" 2>/dev/null
CI="$WORK/ci"
head_e="$(git rev-parse feature/e)"
( cd "$CI" && git fetch -q origin "+refs/heads/feature/e:refs/remotes/origin/feature/e" )
out="$(cd "$CI" && bash "$HOOKS/review-verify.sh" origin/develop "$head_e" 2>"$WORK/err")"; rc=$?
_assert_rc 0 "$rc" "head revisado passa"
first="$(printf '%s\n' "$out" | awk 'NF { print; exit }')"
case "$first" in "## Revisão essencial"*) _ok "stdout é o corpo da review" ;; *) _fail "stdout: $first" ;; esac
hdr="$(cd "$CI" && bash "$HOOKS/review-verify.sh" origin/develop "$head_e" --cabecalho 2>/dev/null)"
_assert_contains "$hdr" "patch_id=" "--cabecalho imprime o cabeçalho"
_assert_not_contains "$hdr" "## Revisão" "--cabecalho não imprime o corpo"
# head sem nota (commit local só do CI)
( cd "$CI" && git checkout -q -b feature/semnota origin/develop && commit_file sn.txt "x" "sem nota" )
head_sn="$(cd "$CI" && git rev-parse HEAD)"
( cd "$CI" && bash "$HOOKS/review-verify.sh" origin/develop "$head_sn" >/dev/null 2>"$WORK/err" ); rc=$?
_assert_rc 1 "$rc" "head sem nota falha"
_assert_contains "$(cat "$WORK/err")" "NÃO encontrada" "instruções"
_assert_contains "$(cat "$WORK/err")" "review-local.sh" "manda rodar a revisão local"
_assert_contains "$(cat "$WORK/err")" "review-local.cmd" "cita o atalho do Windows"
# develop anda depois da revisão: a prova continua valendo (merge-base gravado)
git checkout -q develop; commit_file outro2.txt "mais develop" "chore: develop anda 2"; push origin develop
( cd "$CI" && git fetch -q origin "+refs/heads/develop:refs/remotes/origin/develop" && bash "$HOOKS/review-verify.sh" origin/develop "$head_e" >/dev/null 2>&1 ); rc=$?
_assert_rc 0 "$rc" "prova vale mesmo com a develop adiantada"
# base errada: prova de feature (develop) conferida contra main falha
( cd "$CI" && bash "$HOOKS/review-verify.sh" origin/main "$head_e" >/dev/null 2>"$WORK/err" ); rc=$?
_assert_rc 1 "$rc" "merge-base fora da base declarada é recusado"

# ---------------------------------------------------------------------------
_test "review-history.sh: linha commitada e removida dentro da branch aparece; o diff final não"
git checkout -q -b feature/hist develop
commit_file cfg.py 'SECRET="SEGREDO_FAKE_SO_PARA_TESTE_0001"' "feat: cfg com segredo"
sha_leak="$(git rev-parse --short HEAD)"
commit_file cfg.py 'SECRET=os.environ["S"]' "fix: segredo para env"
printf '\n   \n' > blank.txt && git add blank.txt && git commit -q -m "chore: em branco"
commit_file keep.txt "LINHA_QUE_FICA" "feat: keep"
mb="$(git merge-base origin/develop HEAD)"
out="$(bash "$HOOKS/review-history.sh" "$mb" HEAD 2>"$WORK/err")"; rc=$?
_assert_rc 0 "$rc" "rc 0 com fantasma"
_assert_contains "$out" "# ${sha_leak} feat: cfg com segredo" "cabeçalho do commit que adicionou"
_assert_contains "$out" 'cfg.py: SECRET="SEGREDO_FAKE_SO_PARA_TESTE_0001"' "linha fantasma com arquivo"
_assert_not_contains "$out" "LINHA_QUE_FICA" "linha que sobreviveu ao diff final não aparece"
_assert_not_contains "$out" 'os.environ' "linha que está no head não aparece"
_assert_not_contains "$out" "keep" "commit sem fantasma não aparece"
[ "$(printf '%s\n' "$out" | grep -c -v '^#')" -eq 1 ] && _ok "só uma linha fantasma (whitespace ignorado)" || _fail "linhas: $(printf '%s\n' "$out" | grep -c -v '^#')"
out2="$(bash "$HOOKS/review-history.sh" 2>"$WORK/err")"; rc=$?
_assert_rc 0 "$rc" "sem argumentos calcula merge-base/head"
[ "$out2" = "$out" ] && _ok "sem argumentos dá o mesmo resultado" || _fail "saída diverge sem argumentos"
out="$(bash "$HOOKS/review-history.sh" HEAD~1 HEAD 2>"$WORK/err")"; rc=$?
_assert_rc 0 "$rc" "rc 0 sem fantasma"
[ -z "$out" ] && _ok "sem fantasma → stdout vazio" || _fail "stdout deveria ser vazio: $out"
bash "$HOOKS/review-history.sh" HEAD 2>"$WORK/err"; rc=$?
_assert_rc 2 "$rc" "um argumento só → rc 2"

_test "review-local.sh: histórico da branch vai no prompt (entregue, não pedido)"
STUB_MODE=marker bash "$HOOKS/review-local.sh" >/dev/null 2>"$WORK/err"; rc=$?
_assert_rc 0 "$rc" "rodou"
args="$(tail -1 "$STUB_LOG")"
_assert_contains "$args" 'cfg.py: SECRET="SEGREDO_FAKE_SO_PARA_TESTE_0001"' "prompt traz a linha fantasma"
_assert_contains "$args" "# ${sha_leak} feat: cfg com segredo" "prompt traz o commit de origem"
_assert_contains "$args" "review-history.sh:*)" "allowlist libera o review-history.sh para a skill"
_assert_not_contains "$args" "LINHA_QUE_FICA" "prompt não repete o diff final"
_assert_contains "$(cat "$WORK/err")" "1 linha(s) adicionada(s) e removida(s)" "stderr diz quantas linhas foram"

_test "review-local.sh: sem fantasma o prompt diz que não há nada no histórico"
git checkout -q -b feature/semhist develop; commit_file s.txt "s" "feat: s"
STUB_MODE=marker bash "$HOOKS/review-local.sh" >/dev/null 2>"$WORK/err"; rc=$?
_assert_rc 0 "$rc" "rodou"
_assert_contains "$(tail -1 "$STUB_LOG")" "nenhuma linha adicionada em commit intermediário" "prompt: histórico limpo"

_test "review-local.sh: histórico grande não vai no argv (Windows: 32K) — manda rodar o script"
git checkout -q -b feature/histgrande develop
awk 'BEGIN { for (i = 0; i < 400; i++) printf "LINHA_GRANDE_%04d_%s\n", i, "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" }' > big.txt
git add big.txt && git commit -q -m "feat: big"
git rm -q big.txt && git commit -q -m "chore: remove big"
commit_file g.txt "g" "feat: g"
STUB_MODE=marker bash "$HOOKS/review-local.sh" >/dev/null 2>"$WORK/err"; rc=$?
_assert_rc 0 "$rc" "rodou"
args="$(tail -1 "$STUB_LOG")"
_assert_not_contains "$args" "LINHA_GRANDE_0100" "conteúdo grande fica fora do argv"
_assert_contains "$args" "400 linhas foram ADICIONADAS" "prompt diz quantas linhas há"
_assert_contains "$args" "/review-history.sh $(git merge-base origin/develop HEAD) $(git rev-parse HEAD)" "prompt dá o comando exato com merge-base e head"
_assert_contains "$(cat "$WORK/err")" "grande demais para o prompt" "stderr avisa"

# ---------------------------------------------------------------------------
_test "contratos entre arquivos (cabeçalho e skill)"
marker_lib="$(awk -F'"' '/^REVIEW_MARKER=/ { print $2; exit }' "$HOOKS/lib.sh")"
marker_skill="$(awk '/^```markdown/ { inblk = 1; next } inblk && NF { print; exit }' "$SKILL")"
case "$marker_skill" in "$marker_lib"*) _ok "REVIEW_MARKER (${marker_lib}) é prefixo do título do template da skill" ;;
    *) _fail "REVIEW_MARKER (${marker_lib}) não é prefixo de (${marker_skill})" ;; esac
grep -q 'review-receipt.sh' "$SKILL" && _ok "skill cita o review-receipt.sh (modo local interativo)" || _fail "skill não cita o review-receipt.sh"
grep -q 'modo local' "$SKILL" && _ok "skill documenta o modo local" || _fail "skill sem modo local"
grep -q 'Mascarar o segredo' "$SKILL" && _ok "skill exige mascarar o valor vazado (a review vira comentário público na PR)" || _fail "skill não exige mascarar o valor vazado"
grep -q 'review-history.sh' "$SKILL" && _ok "skill cita o review-history.sh (histórico da branch)" || _fail "skill não cita o review-history.sh"
grep -q 'Histórico da branch' "$SKILL" && _ok "skill cobre o histórico da branch (commit intermediário)" || _fail "skill sem seção de histórico da branch"
grep -q 'rebase -i' "$SKILL" && _ok "skill manda reescrever a branch antes do push" || _fail "skill não manda reescrever a branch"
grep -qi 'rotacionad' "$SKILL" && _ok "skill manda rotacionar se o commit já esteve no remoto" || _fail "skill não manda rotacionar"
grep -q 'Histórico da branch' "$HOOKS/review-local.sh" && _ok "review-local.sh entrega o histórico no prompt" || _fail "review-local.sh não entrega o histórico"

# ---------------------------------------------------------------------------
_test "configuração: repo develop+master (modelo backend/frontend) é detectado"
# Cópia dos hooks SEM review.conf ao lado: num consumidor, .review-gate/review.conf
# existe e vence a detecção (é o comportamento certo) — aqui a detecção é o alvo.
PURE="$WORK/pure-gate/hooks"; mkdir -p "$PURE" && cp "$HOOKS"/* "$PURE/" && chmod +x "$PURE"/*
mk_repo() {  # <nome> <branches…> — primeiro = HEAD do remoto
    local name="$1"; shift
    git init -q --bare "$WORK/$name.git"
    git init -q "$WORK/$name"; ( cd "$WORK/$name" && git remote add origin "$WORK/$name.git" \
        && git checkout -q -b "$1" && echo x > f && git add f && git commit -q -m base \
        && git push -q origin "$1" 2>/dev/null && git symbolic-ref "refs/remotes/origin/HEAD" "refs/remotes/origin/$1" \
        && for b in "${@:2}"; do git branch -q "$b" && git push -q origin "$b" 2>/dev/null; done \
        && git config core.hooksPath "$PURE" )
}
mk_repo dm master develop
( cd "$WORK/dm" && source "$PURE/lib.sh" && review_load_config origin \
  && [ "$REVIEW_BASE_BRANCH" = develop ] && [ "$REVIEW_HOTFIX_BASE" = master ] \
  && [ "$REVIEW_PROTECTED" = "master develop" ] ) && _ok "base=develop hotfix=master protegidas=[master develop]" \
  || _fail "detecção errada em develop+master"
( cd "$WORK/dm" && git checkout -q -b hotfix/x master && echo h > h && git add h && git commit -q -m h \
  && printf '## Revisão essencial (t)\n' > body && bash "$PURE/review-receipt.sh" HEAD body 2>/dev/null \
  && git notes --ref=refs/notes/review show HEAD | grep -q 'base=origin/master' ) && _ok "hotfix usa origin/master" || _fail "hotfix não usou master"
( cd "$WORK/dm" && git checkout -q master && echo m > m && git add m && git commit -q -m m && git push -q origin master 2>/dev/null ) \
  && _ok "push da master passa sem revisão (protegida detectada)" || _fail "push da master bloqueado"

_test "configuração: repo só com main"
mk_repo mo main
( cd "$WORK/mo" && source "$PURE/lib.sh" && review_load_config origin \
  && [ "$REVIEW_BASE_BRANCH" = main ] && [ "$REVIEW_HOTFIX_BASE" = main ] && [ "$REVIEW_PROTECTED" = "main" ] ) \
  && _ok "base=main hotfix=main protegidas=[main]" || _fail "detecção errada em main-only"
( cd "$WORK/mo" && git checkout -q -b feature/z && echo z > z && git add z && git commit -q -m z && ! git push -q origin feature/z 2>/dev/null ) \
  && _ok "feature sem prova bloqueada (base main)" || _fail "feature passou sem prova"

_test "escopo do CI: só PR para a base de feature/bugfix passa pelo portão"
out="$(cd "$WORK/dm" && bash "$PURE/review-verify.sh" --escopo develop 2>/dev/null)"
[ "$out" = "aplica=true" ] && _ok "develop+master: PR para develop → aplica" || _fail "PR para develop fora do portão ($out)"
out="$(cd "$WORK/dm" && bash "$PURE/review-verify.sh" --escopo master 2>"$WORK/err")"
[ "$out" = "aplica=false" ] && _ok "develop+master: PR para master (release) → não aplica" || _fail "PR para master cobrada ($out)"
_assert_contains "$(cat "$WORK/err")" "fora do portão" "stderr diz por que pulou"
out="$(cd "$WORK/mo" && bash "$PURE/review-verify.sh" --escopo main 2>/dev/null)"
[ "$out" = "aplica=true" ] && _ok "só main: PR para main → aplica" || _fail "PR para main fora do portão em main-only ($out)"
( cd "$WORK/dm" && bash "$PURE/review-verify.sh" --escopo >/dev/null 2>&1 ); rc=$?
_assert_rc 2 "$rc" "--escopo sem branch → uso, rc 2"
WF="$(cd "$HOOKS/.." && pwd)/templates/pr-review-essentials.yml"
[ -f "$WF" ] || WF="$(cd "$HOOKS/../.." && pwd)/.github/workflows/pr-review-essentials.yml"
if [ -f "$WF" ]; then
    grep -q 'review-verify.sh --escopo' "$WF" && _ok "workflow roda o passo de escopo" || _fail "workflow sem passo de escopo"
    # Todo passo depois do Escopo tem de estar condicionado a ele.
    n_steps="$(awk '/- name: Escopo/ { on = 1; next } on && /^      - name:/ { n++ } END { print n + 0 }' "$WF")"
    n_gated="$(grep -c "if: steps.escopo.outputs.aplica == 'true'" "$WF")"
    [ "$n_steps" -gt 0 ] && [ "$n_steps" = "$n_gated" ] && _ok "os ${n_steps} passos depois do escopo dependem dele" \
        || _fail "passos depois do escopo: ${n_steps}, condicionados: ${n_gated}"
    grep -q -- '- develop' "$WF" && grep -q -- '- main' "$WF" && _ok "workflow ainda dispara para main (check obrigatório não fica Expected)" \
        || _fail "workflow parou de disparar para main/develop"
else
    _fail "workflow não encontrado ($WF)"
fi

_test "configuração: review.conf explícito vence a detecção"
mkdir -p "$WORK/conf-gate/hooks" && cp "$HOOKS"/* "$WORK/conf-gate/hooks/" && chmod +x "$WORK/conf-gate/hooks/"*
printf 'REVIEW_BASE_BRANCH=trunk\nREVIEW_HOTFIX_BASE=release\nREVIEW_PROTECTED="trunk release"\nREVIEW_MAX_TURNS=7\n' > "$WORK/conf-gate/review.conf"
( cd "$WORK/mo" && source "$WORK/conf-gate/hooks/lib.sh" && review_load_config origin \
  && [ "$REVIEW_BASE_BRANCH" = trunk ] && [ "$REVIEW_HOTFIX_BASE" = release ] && [ "$REVIEW_MAX_TURNS" = 7 ] \
  && review_is_protected release && ! review_is_protected main ) && _ok "conf lida: base=trunk hotfix=release max_turns=7" || _fail "conf ignorada"

_test "configuração: review.conf com CRLF (Notepad, autocrlf) é lido sem o \\r"
printf 'REVIEW_BASE_BRANCH=trunk\r\nREVIEW_HOTFIX_BASE=release\r\nREVIEW_PROTECTED="trunk release"\r\nREVIEW_MAX_TURNS=7\r\n' > "$WORK/conf-gate/review.conf"
( cd "$WORK/mo" && source "$WORK/conf-gate/hooks/lib.sh" && review_load_config origin \
  && [ "$REVIEW_BASE_BRANCH" = trunk ] && [ "$REVIEW_HOTFIX_BASE" = release ] && [ "$REVIEW_MAX_TURNS" = 7 ] \
  && review_is_protected release ) && _ok "valores sem \\r: base=trunk hotfix=release max_turns=7" || _fail "CRLF vazou para os valores"

_test "ativação: ensure-hookspath.sh liga o portão num clone novo (SessionStart do Claude Code)"
# Clone recém-feito de um consumidor: hooks vendorizados, core.hooksPath vazio.
read -r -a PY <<<"$(source "$HOOKS/lib.sh" && review_python && printf '%s' "${REVIEW_PYTHON[*]}")"
git clone -q "$WORK/origin.git" "$WORK/fresh" 2>/dev/null
mkdir -p "$WORK/fresh/.review-gate/hooks" && cp "$HOOKS"/* "$WORK/fresh/.review-gate/hooks/" && chmod +x "$WORK/fresh/.review-gate/hooks/"*
ENS="$WORK/fresh/.review-gate/hooks/ensure-hookspath.sh"
out="$(cd "$WORK/fresh" && bash "$ENS" 2>"$WORK/ens.err")"; rc=$?
_assert_rc 0 "$rc" "ensure-hookspath.sh sai 0"
[ "$(git -C "$WORK/fresh" config --get core.hooksPath)" = ".review-gate/hooks" ] && _ok "core.hooksPath=.review-gate/hooks gravado (relativo)" \
  || _fail "hooksPath=$(git -C "$WORK/fresh" config --get core.hooksPath)"
_assert_contains "$out" '{"systemMessage": "[revisao] core.hooksPath=.review-gate/hooks configurado' "stdout é o JSON do hook, com systemMessage"
printf '%s' "$out" | "${PY[@]}" -c 'import json, sys; json.loads(sys.stdin.buffer.read().decode("utf-8"))' 2>/dev/null \
  && _ok "systemMessage é JSON válido" || _fail "JSON inválido: $out"
_assert_contains "$(cat "$WORK/ens.err")" "git config --unset core.hooksPath" "diz como desfazer"
out="$(cd "$WORK/fresh/.review-gate" && bash "$ENS" 2>&1)"; rc=$?
_assert_rc 0 "$rc" "segunda vez sai 0"
[ -z "$out" ] && _ok "segunda vez em silêncio (nem stdout nem stderr)" || _fail "segunda vez falou: $out"
( cd "$WORK/fresh" && git checkout -q -b feature/fresh && echo f > f && git add f && git commit -q -m f && ! git push -q origin feature/fresh 2>/dev/null ) \
  && _ok "com o portão ativado, push sem prova bloqueia" || _fail "portão ativado não bloqueou"

_test "ativação: hooksPath absoluto para os mesmos hooks conta como ativo"
git -C "$WORK/fresh" config core.hooksPath "$WORK/fresh/.review-gate/hooks"
# Comparar com o que o git devolve, não com o caminho do bash: no Git Bash o MSYS
# converte /tmp/… em C:/… ao passar o argumento para o git.exe.
abs="$(git -C "$WORK/fresh" config --get core.hooksPath)"
out="$(cd "$WORK/fresh" && bash "$ENS" 2>&1)"
[ -z "$out" ] && _ok "silêncio" || _fail "falou: $out"
[ "$(git -C "$WORK/fresh" config --get core.hooksPath)" = "$abs" ] && _ok "valor absoluto preservado" || _fail "valor absoluto trocado: $abs → $(git -C "$WORK/fresh" config --get core.hooksPath)"

_test "ativação: hooksPath de outra ferramenta (husky) não é sobrescrito"
git -C "$WORK/fresh" config core.hooksPath .husky
out="$(cd "$WORK/fresh" && bash "$ENS" 2>"$WORK/ens.err")"; rc=$?
_assert_rc 0 "$rc" "sai 0"
[ "$(git -C "$WORK/fresh" config --get core.hooksPath)" = ".husky" ] && _ok ".husky preservado" || _fail "hooksPath alheio sobrescrito"
_assert_contains "$out" "NÃO está ativo" "systemMessage avisa que o portão está inativo"
_assert_contains "$(cat "$WORK/ens.err")" "git config core.hooksPath .review-gate/hooks" "stderr dá o comando para ativar"

_test "ativação: fora de um clone, sai 0 e não grava nada"
mkdir -p "$WORK/solto/hooks" && cp "$HOOKS"/* "$WORK/solto/hooks/"
out="$(cd "$WORK" && GIT_CEILING_DIRECTORIES="$WORK" bash "$WORK/solto/hooks/ensure-hookspath.sh" 2>&1)"; rc=$?
_assert_rc 0 "$rc" "sai 0"
[ -z "$out" ] && _ok "em silêncio" || _fail "falou: $out"
cmd="$(tr -d '\r' < "$GATE_DIR/templates/claude-settings.json" 2>/dev/null | "${PY[@]}" -c 'import json, sys; print(json.load(sys.stdin)["hooks"]["SessionStart"][0]["hooks"][0]["command"])' 2>/dev/null)"
if [ -n "$cmd" ]; then  # só no repo do review-gate: o template não é vendorizado
    git init -q "$WORK/sem-gate"
    ( cd "$WORK/sem-gate" && bash -c "$cmd" ) >/dev/null 2>&1; rc=$?
    _assert_rc 0 "$rc" "command do SessionStart num repo sem .review-gate sai 0"
    [ -z "$(git -C "$WORK/sem-gate" config --get core.hooksPath)" ] && _ok "e não grava hooksPath" || _fail "gravou hooksPath num repo sem portão"
fi

_test "ativação: review-local.sh liga o portão de quem chega nele à mão"
git -C "$WORK/fresh" config --unset core.hooksPath
( cd "$WORK/fresh" && git checkout -q develop && bash .review-gate/hooks/review-local.sh >/dev/null 2>&1 )
[ "$(git -C "$WORK/fresh" config --get core.hooksPath)" = ".review-gate/hooks" ] && _ok "hooksPath configurado pelo review-local.sh" \
  || _fail "review-local.sh não ativou: $(git -C "$WORK/fresh" config --get core.hooksPath)"

_test "ativação: hooks vendorizados em OUTRO clone não mexem no hooksPath deste"
# (Nunca rodar o ensure-hookspath.sh de $HOOKS aqui: ele ativaria o clone onde a suíte mora.)
git -C "$WORK/fresh" config --unset core.hooksPath
before="$(git config --get core.hooksPath)"   # como o git guardou (C:/… no Git Bash), não $HOOKS
( cd "$WORK/repo" && source "$WORK/fresh/.review-gate/hooks/lib.sh" && review_ensure_hookspath ) >/dev/null 2>&1; rc=$?
_assert_rc 0 "$rc" "review_ensure_hookspath sai 0 sem fazer nada"
[ "$(git config --get core.hooksPath)" = "$before" ] && _ok "hooksPath do repo de teste intacto" || _fail "mexeu no hooksPath: $(git config --get core.hooksPath)"
[ -z "$(git -C "$WORK/fresh" config --get core.hooksPath)" ] && _ok "nem no clone dos hooks (cwd é outro)" || _fail "ativou o clone dos hooks"

echo ""
echo "pre_push_test: ${PASS} ok, ${FAIL} falha(s)"
[ "$FAIL" -eq 0 ]
