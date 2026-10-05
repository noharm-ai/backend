#!/usr/bin/env bash
# Funções compartilhadas do portão de revisão essencial (pre-push + CI).
#
# Quem carrega este arquivo: hooks/pre-push (o portão), review-local.sh (a
# revisão headless que o dev roda à mão), review-receipt.sh (grava a prova),
# review-verify.sh (o que o CI executa) e ensure-hookspath.sh (ativa o portão
# no clone, chamado pelo SessionStart do Claude Code). É a FONTE ÚNICA do que os quatro têm
# de concordar — o cabeçalho da review, o ref das notas, o algoritmo do
# patch-id e a regra de validade da prova. Duplicar qualquer um deles em dois
# arquivos é a classe de bug que este repo mais documenta: duas cópias
# divergem em silêncio.
#
# Modelo
# ------
# A prova de que a revisão rodou viaja como NOTA DE GIT (refs/notes/review)
# no commit revisado: cabeçalho com o patch-id do diff revisado + o corpo da
# review. O pre-push exige a nota (ou uma equivalente por patch-id, caso de
# amend/rebase sem mudança de hunks) antes de deixar a branch sair da máquina,
# e empurra o ref das notas junto. O CI busca a nota do head da PR, refaz a
# conta do patch-id sobre o MESMO merge-base que o dev usou e republica o corpo
# como review COMMENT. Ninguém roda Claude no CI: o CI só confere e publica.
#
# Por que patch-id e não sha do commit: o sha muda num amend de mensagem ou
# num rebase; o conteúdo, não. `git patch-id --stable` ignora número de linha
# dos hunks e whitespace, então amend e rebase que não tocam os hunks
# reaproveitam a prova, e mudança de conteúdo invalida. Limite conhecido:
# edição só de whitespace depois da revisão não invalida a prova — aceito, o
# revisor humano vê o diff final de qualquer jeito.
#
# Por que o merge-base GRAVADO e não um novo: se a develop andou depois da
# revisão, o merge-base de hoje muda o contexto dos hunks e o patch-id
# divergiria — falso vermelho. A nota guarda o merge-base que o dev usou; a
# validação exige só que ele seja ancestral do head E da base. Assim a prova
# cobre exatamente o que foi revisado (head contra um ponto da base), e commits
# novos da base não são mudanças da PR.
#
# stdout é produto, stderr é diagnóstico (CLAUDE.md): tudo aqui fala por
# `_rv_say` em stderr; quem devolve valor devolve por printf.

REVIEW_MARKER="## Revisão essencial"
NOTES_REF="refs/notes/review"
NOTES_ORIGIN_REF="refs/notes/review-origin"
# Espelho das notas numa BRANCH: o mesmo histórico de notas, empurrado para
# refs/heads/* quando o remoto recusa refs/notes/* (achado de campo: o proxy de
# git das sessões remotas do Claude Code só aceita refs/heads/*). O CI e o
# pre-push leem os dois e mesclam — ver review_notes_sync e review_notes_pull.
NOTES_MIRROR_REF="refs/heads/review-gate/notes"
NOTES_MIRROR_LOCAL_REF="refs/notes/review-mirror"

# Onde os scripts estão (hooks/) e o diretório do gate (o pai: .review-gate/
# num repo consumidor, a raiz no repo do review-gate). review.conf mora no pai.
REVIEW_HOOKS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REVIEW_GATE_DIR="$(cd "${REVIEW_HOOKS_DIR}/.." && pwd)"
REVIEW_CONF="${REVIEW_GATE_DIR}/review.conf"

_rv_say() { printf '[revisao] %s\n' "$*" >&2; }

# Caminho dos hooks relativo à raiz do clone, para as mensagens (bash
# .review-gate/hooks/review-local.sh). Pelo git (--show-prefix a partir do
# diretório dos hooks), e NÃO recortando --show-toplevel do pwd: os dois
# divergem por symlink (/var → /private/var no macOS) e por estilo de caminho
# (/c/… do MSYS vs C:/… do git.exe no Windows), e a mensagem saía absoluta.
# GIT_DIR/GIT_WORK_TREE relativos (herdados de quem chamou) quebrariam o -C.
review_hooks_rel() {
    local rel
    rel="$(unset GIT_DIR GIT_WORK_TREE; git -C "$REVIEW_HOOKS_DIR" rev-parse --show-prefix 2>/dev/null)"
    if [ -n "$rel" ]; then printf '%s\n' "${rel%/}"; else printf '%s\n' "$REVIEW_HOOKS_DIR"; fi
}

# Caminho dos hooks como o cmd.exe/PowerShell aceitam (barra invertida), para a
# linha (no Windows, fora do Git Bash) das mensagens.
review_hooks_rel_win() {
    review_hooks_rel | tr '/' '\\'
}

# review_ensure_hookspath → 0 já ativo (ou estes hooks não são deste clone) |
# 10 configurou agora | 11 core.hooksPath é de outra ferramenta | 1 erro
# Ativa o portão no clone onde estes hooks estão vendorizados. O git não roda
# nada do repo no clone (de propósito), então o "uma vez por clone" do README
# era um passo manual que os devs esqueciam; quem chama isto é o SessionStart
# do Claude Code (ensure-hookspath.sh), o install.sh e o review-local.sh.
# Vazio → grava o caminho relativo e diz como desfazer. Valor de OUTRA
# ferramenta (husky, hook global do dev) → não sobrescreve: avisa e dá o comando.
review_ensure_hookspath() {
    local top hooks_top rel cur now
    top="$(git rev-parse --show-toplevel 2>/dev/null)" || return 0
    hooks_top="$(unset GIT_DIR GIT_WORK_TREE; git -C "$REVIEW_HOOKS_DIR" rev-parse --show-toplevel 2>/dev/null)" || return 0
    # pwd -P dos dois lados: symlink (/var → /private/var) e /c/… vs C:/… no Windows.
    [ "$(cd "$top" && pwd -P)" = "$(cd "$hooks_top" && pwd -P)" ] || return 0
    rel="$(review_hooks_rel)"
    cur="$(git config --get core.hooksPath 2>/dev/null || true)"
    if [ -z "$cur" ]; then
        git config core.hooksPath "$rel" || { _rv_say "não consegui gravar core.hooksPath=${rel} neste clone"; return 1; }
        _rv_say "core.hooksPath=${rel} configurado neste clone: o pre-push da revisão essencial está ativo. Desfazer: git config --unset core.hooksPath"
        return 10
    fi
    # Relativo é relativo à raiz do clone (é de lá que o git roda os hooks).
    now="$(cd "$top" 2>/dev/null && cd "$cur" 2>/dev/null && pwd -P)"
    if [ -n "$now" ] && [ "$now" = "$(cd "$REVIEW_HOOKS_DIR" && pwd -P)" ]; then
        return 0
    fi
    _rv_say "core.hooksPath=${cur} (outra ferramenta?): o pre-push da revisão essencial NÃO está ativo neste clone, e não vou sobrescrever."
    _rv_say "  Para ativar: git config core.hooksPath ${rel}   (ou chame ${rel}/pre-push a partir do hook atual)"
    return 11
}

# ---------------------------------------------------------------------------
# Configuração: review.conf (escrito pelo install.sh, editável) + auto-detecção
# ---------------------------------------------------------------------------
# Chaves (todas opcionais — o que faltar é detectado a partir do remoto):
#   REVIEW_BASE_BRANCH   base de feature/bugfix (padrão: develop se existir no
#                        remoto; senão o HEAD do remoto — main ou master)
#   REVIEW_HOTFIX_BASE   base de hotfix/* (padrão: HEAD do remoto)
#   REVIEW_PROTECTED     branches cujo push NÃO passa pelo portão, separadas
#                        por espaço (padrão: as que existirem entre main,
#                        master e develop) — a revisão é da PR, não da base
#   REVIEW_MAX_TURNS     teto de turnos do claude -p (padrão 40)
#
# Por que detectar em vez de exigir: os repos da NoHarm não têm um só modelo —
# uns são develop+master, outros develop+main, outros só main ou só master.
# Exigir conf em todo repo é atrito; detectar errado em silêncio é pior. Então
# o install.sh detecta UMA vez e grava explícito no review.conf, e a detecção
# aqui é só o fallback (conf ausente ou chave apagada), sempre dizendo o que
# assumiu.
# tr -d '\r': review.conf editado no Notepad, ou checkout com autocrlf (padrão
# do Git for Windows), vem com CRLF — e REVIEW_BASE_BRANCH=develop<CR> é uma
# branch que não existe. eval, e não source <(…): o bash 3.2 do macOS lê vazio
# de process substitution.
if [ -f "$REVIEW_CONF" ]; then
    eval "$(tr -d '\r' < "$REVIEW_CONF")"
fi

# _review_remote_head <remote> → main|master|… (HEAD do remoto) | vazio
_review_remote_head() {
    local remote="$1" ref
    ref="$(git symbolic-ref -q "refs/remotes/${remote}/HEAD" 2>/dev/null)" && { printf '%s\n' "${ref#refs/remotes/${remote}/}"; return 0; }
    ref="$(git ls-remote --symref "$remote" HEAD 2>/dev/null | awk '/^ref:/ { sub("refs/heads/", "", $2); print $2; exit }')"
    [ -n "$ref" ] && { printf '%s\n' "$ref"; return 0; }
    return 1
}

# _review_branch_exists <remote> <branch>: ref local de tracking, senão ls-remote
_review_branch_exists() {
    git rev-parse -q --verify "refs/remotes/$1/$2^{commit}" >/dev/null 2>&1 && return 0
    [ -n "$(git ls-remote --heads "$1" "$2" 2>/dev/null)" ]
}

# review_load_config <remote>: completa o que o review.conf não fixou.
review_load_config() {
    local remote="${1:-origin}" head b found=""
    if [ -z "${REVIEW_PROTECTED:-}" ]; then
        for b in main master develop; do
            _review_branch_exists "$remote" "$b" && found="${found}${found:+ }${b}"
        done
        REVIEW_PROTECTED="${found:-main}"
    fi
    if [ -z "${REVIEW_BASE_BRANCH:-}" ] || [ -z "${REVIEW_HOTFIX_BASE:-}" ]; then
        head="$(_review_remote_head "$remote" 2>/dev/null || true)"
        if [ -z "$head" ]; then
            case " $REVIEW_PROTECTED " in *" main "*) head=main ;; *" master "*) head=master ;; *) head="${REVIEW_PROTECTED%% *}" ;; esac
        fi
        if [ -z "${REVIEW_BASE_BRANCH:-}" ]; then
            case " $REVIEW_PROTECTED " in *" develop "*) REVIEW_BASE_BRANCH=develop ;; *) REVIEW_BASE_BRANCH="$head" ;; esac
        fi
        [ -n "${REVIEW_HOTFIX_BASE:-}" ] || REVIEW_HOTFIX_BASE="$head"
    fi
    REVIEW_MAX_TURNS="${REVIEW_MAX_TURNS:-40}"
    export REVIEW_BASE_BRANCH REVIEW_HOTFIX_BASE REVIEW_PROTECTED REVIEW_MAX_TURNS
}

# review_base_branch <branch> → branch base (hotfix/* parte de outra base)
review_base_branch() {
    case "$1" in
        hotfix/*) printf '%s\n' "$REVIEW_HOTFIX_BASE" ;;
        *)        printf '%s\n' "$REVIEW_BASE_BRANCH" ;;
    esac
}

# review_pr_in_scope <branch-base-da-PR>: o check do CI vale para esta PR?
# Só PR que mira a base de feature/bugfix (REVIEW_BASE_BRANCH) passa pelo
# portão. PR entre branches de release (develop → main/master) só leva adiante
# o que já foi revisado quando entrou na develop — cobrar de novo exigiria uma
# revisão do diff inteiro do release, que ninguém roda. Repo só com main/master
# tem a própria main como base, e ali o portão continua valendo.
# Chame depois de review_load_config.
review_pr_in_scope() {
    [ "$1" = "$REVIEW_BASE_BRANCH" ]
}

# review_is_protected <branch>
review_is_protected() {
    case " $REVIEW_PROTECTED " in *" $1 "*) return 0 ;; *) return 1 ;; esac
}

# review_fetch_base <remote> <branch>
# Refspec EXPLÍCITO: `git fetch origin develop` só grava FETCH_HEAD e deixaria
# refs/remotes/origin/develop parado (armadilha documentada no CLAUDE.md).
# Fetch falhou mas o ref local existe → avisa e segue (pode estar velho);
# não existe → rc 1, quem chamou decide.
review_fetch_base() {
    local remote="$1" branch="$2" ref="refs/remotes/$1/$2"
    if git fetch --quiet --no-tags "$remote" "+refs/heads/${branch}:${ref}" 2>/dev/null; then
        return 0
    fi
    if git rev-parse -q --verify "${ref}^{commit}" >/dev/null 2>&1; then
        _rv_say "fetch de ${remote}/${branch} falhou; usando o ref local (pode estar desatualizado)"
        return 0
    fi
    _rv_say "sem ${remote}/${branch} local e o fetch falhou"
    return 1
}

# review_patch_id <merge-base> <sha> → id (vazio se o diff for vazio)
# Config pinada: renames e cor do usuário não podem mudar o fluxo que é hasheado.
review_patch_id() {
    git -c diff.renames=true -c color.ui=never diff --no-ext-diff "$1" "$2" \
        | git patch-id --stable | awk '{ print $1 }'
}

# review_ghost_lines <merge-base> <sha> → linhas adicionadas em algum commit de
# merge-base..sha que NÃO estão no diff acumulado (foram removidas ou alteradas
# por um commit posterior da própria branch). É o que o diff final esconde e o
# push leva mesmo assim: um segredo commitado e apagado no commit seguinte vive
# no histórico do remoto, de forks e de clones — e squash merge não apaga a
# branch da PR. Vazio = nada a olhar no histórico.
#
# Formato (agrupado por commit, para o prompt ficar curto):
#   # <sha curto> <assunto>
#   <caminho>: <linha adicionada, sem o + do diff>
# Linhas só de whitespace ficam de fora. Merges ficam de fora (rev-list
# --no-merges): o diff combinado de um merge não é (linha adicionada aqui).
# Config pinada como em review_patch_id: cor, diff externo e renames do usuário
# não podem mudar o que se compara.
review_ghost_lines() {
    local mb="$1" sha="$2" final c
    final="$(mktemp)"
    git -c diff.renames=true -c color.ui=never diff --no-ext-diff "$mb" "$sha" \
        | awk '/^\+\+\+ / { next } /^\+/ { print substr($0, 2) }' | LC_ALL=C sort -u > "$final"
    for c in $(git rev-list --reverse --no-merges "${mb}..${sha}"); do
        git -c diff.renames=true -c color.ui=never show --no-ext-diff --format='%h %s' "$c" \
            | awk -v final="$final" '
                BEGIN { while ((getline l < final) > 0) seen[l] = 1; close(final) }
                NR == 1 { hdr = "# " $0; next }
                /^\+\+\+ \/dev\/null/ { path = "(arquivo removido)"; next }
                /^\+\+\+ b\// { path = substr($0, 7); next }
                /^\+/ {
                    t = substr($0, 2)
                    if (t ~ /^[[:space:]]*$/ || (t in seen)) next
                    if (!ph) { print hdr; ph = 1 }
                    print path ": " t
                }'
    done
    rm -f "$final"
}

# review_note_read <sha> → texto da nota | rc 1
review_note_read() {
    git notes --ref="$NOTES_REF" show "$1" 2>/dev/null
}

# review_note_field <campo> ← nota em stdin → valor do cabeçalho (antes do ---)
review_note_field() {
    awk -v k="$1" -F'=' '/^---$/ { exit } $1 == k { sub(/^[^=]*=/, ""); print; exit }'
}

# review_note_body ← nota em stdin → corpo (depois do primeiro ---)
review_note_body() {
    awk 'body { print; next } /^---$/ { body = 1 }'
}

# review_note_valid <sha> <base-ref>
# A regra de validade, a mesma no pre-push e no CI:
#   nota existe, com patch_id e merge_base;
#   merge_base é ancestral do sha e da base;
#   patch-id de (merge_base..sha) == o gravado;
#   primeira linha do corpo começa com o cabeçalho da skill.
# Motivo da recusa vai para stderr para quem está lendo o terminal ou o log.
review_note_valid() {
    local sha="$1" base_ref="$2" note pid mb now first
    note="$(review_note_read "$sha")" || { _rv_say "sem nota de revisão em ${sha:0:12}"; return 1; }
    pid="$(printf '%s\n' "$note" | review_note_field patch_id)"
    mb="$(printf '%s\n' "$note" | review_note_field merge_base)"
    if [ -z "$pid" ] || [ -z "$mb" ]; then
        _rv_say "nota em ${sha:0:12} sem patch_id/merge_base (formato inesperado)"; return 1
    fi
    if ! git cat-file -e "${mb}^{commit}" 2>/dev/null; then
        _rv_say "merge_base ${mb:0:12} da nota não existe neste clone"; return 1
    fi
    if ! git merge-base --is-ancestor "$mb" "$sha"; then
        _rv_say "merge_base ${mb:0:12} da nota não é ancestral de ${sha:0:12}"; return 1
    fi
    if [ -n "$base_ref" ] && ! git merge-base --is-ancestor "$mb" "$base_ref"; then
        _rv_say "merge_base ${mb:0:12} da nota não está em ${base_ref}"; return 1
    fi
    now="$(review_patch_id "$mb" "$sha")"
    if [ "$now" != "$pid" ]; then
        _rv_say "conteúdo mudou desde a revisão (patch-id ${pid:0:12} → ${now:0:12})"; return 1
    fi
    first="$(printf '%s\n' "$note" | review_note_body | awk 'NF { print; exit }')"
    case "$first" in
        "$REVIEW_MARKER"*) return 0 ;;
        *) _rv_say "corpo da nota não começa com (${REVIEW_MARKER})"; return 1 ;;
    esac
}

# review_note_find_by_patch_id <patch-id> → sha do commit que tem nota com esse id | rc 1
# Caso do amend/rebase: o sha mudou, o conteúdo não. Varre as notas locais.
review_note_find_by_patch_id() {
    local want="$1" blob commit pid
    while read -r blob commit; do
        [ -n "$commit" ] || continue
        pid="$(git cat-file -p "$blob" 2>/dev/null | review_note_field patch_id)"
        if [ "$pid" = "$want" ]; then
            printf '%s\n' "$commit"
            return 0
        fi
    done < <(git notes --ref="$NOTES_REF" list 2>/dev/null)
    return 1
}

# review_note_write <sha> <patch-id> <merge-base> <base-label> <origem> <arquivo-corpo>
review_note_write() {
    local sha="$1" pid="$2" mb="$3" base="$4" origem="$5" body="$6" tmp
    tmp="$(mktemp)"
    {
        printf 'patch_id=%s\n' "$pid"
        printf 'sha=%s\n' "$sha"
        printf 'base=%s\n' "$base"
        printf 'merge_base=%s\n' "$mb"
        printf 'data=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        printf 'origem=%s\n' "$origem"
        printf -- '---\n'
        cat "$body"
    } > "$tmp"
    git notes --ref="$NOTES_REF" add -f -F "$tmp" "$sha" >/dev/null 2>&1
    local rc=$?
    rm -f "$tmp"
    return $rc
}

# review_python → preenche REVIEW_PYTHON (array: comando de um Python 3) | rc 1
# No Windows o Python instala como python.exe ou py.exe; o python3.exe que às
# vezes existe no PATH é o stub da Microsoft Store (abre a loja e sai com erro).
# Por isso cada candidato é EXECUTADO, não só procurado com command -v.
REVIEW_PYTHON=()
review_python() {
    local cand
    [ "${#REVIEW_PYTHON[@]}" -gt 0 ] && return 0
    for cand in python3 python "py -3"; do
        # shellcheck disable=SC2086
        if $cand -c 'import sys; sys.exit(0 if sys.version_info[0] == 3 else 1)' </dev/null >/dev/null 2>&1; then
            read -r -a REVIEW_PYTHON <<<"$cand"
            return 0
        fi
    done
    return 1
}

# review_notes_sync <remote>
# O ref de notas é UM só, compartilhado por todo dev: sem mesclar antes de
# empurrar, o segundo a revisar no mesmo dia leva non-fast-forward. Estratégia
# union: commits distintos nunca conflitam; nota dupla no mesmo commit vira
# concatenação. O push aninhado reentra no pre-push com um ref que não é
# branch (pulado) — e NOHARM_REVIEW_IN_SYNC é o cinto além do suspensório.
#
# Só repete quando o erro é non-fast-forward (aí mesclar de novo resolve).
# Qualquer outro erro (403 de proxy que só libera a branch, rede, ref
# bloqueado no servidor) é impresso COMO VEIO — adivinhar a causa foi o que
# fez a primeira versão dizer (outro dev empurrou antes) para um 403.
#
# Recusado o ref canônico, tenta o espelho (NOTES_MIRROR_REF, uma branch): o
# mesmo commit de notas, que o CI também lê. Espelho aceito → rc 0, avisando
# por onde a prova foi. Os dois recusados → os dois erros e o comando à mão.
review_notes_sync() {
    local remote="$1" err
    [ "${NOHARM_REVIEW_IN_SYNC:-}" = "1" ] && return 0
    err="$(_review_notes_push "$remote" "$NOTES_REF")" && return 0
    printf '%s\n' "$err" >&2
    _rv_say "${remote} recusou ${NOTES_REF} (erro acima, como veio); tentando o espelho ${NOTES_MIRROR_REF#refs/heads/}"
    if err="$(_review_notes_push "$remote" "$NOTES_MIRROR_REF")"; then
        _rv_say "prova entregue pelo espelho ${NOTES_MIRROR_REF#refs/heads/} (branch): o CI lê as notas de lá também."
        return 0
    fi
    printf '%s\n' "$err" >&2
    _rv_say "não consegui empurrar ${NOTES_REF} nem o espelho para ${remote}. A branch segue, mas o check (revisao-essencial)"
    _rv_say "no CI vai falhar até as notas chegarem: git push ${remote} ${NOTES_REF}   (ou ${NOTES_REF}:${NOTES_MIRROR_REF})"
    return 1
}

# _review_notes_push <remote> <ref-destino> → rc 0 | rc 1 com o erro do git em stdout
_review_notes_push() {
    local remote="$1" dst="$2" tentativa err
    for tentativa in 1 2; do
        review_notes_pull "$remote" || true
        # LC_ALL=C: o case abaixo lê a mensagem do git, e o Git Bash herda o LANG
        # do Windows (pt_BR…) — mensagem traduzida não casaria.
        err="$(NOHARM_REVIEW_IN_SYNC=1 LC_ALL=C git push --quiet "$remote" "${NOTES_REF}:${dst}" 2>&1)" && return 0
        case "$err" in
            *non-fast-forward*|*"fetch first"*)
                [ "$tentativa" -eq 1 ] && _rv_say "push de ${dst} rejeitado (non-fast-forward: outro dev empurrou antes); mesclando de novo" ;;
            *) break ;;
        esac
    done
    printf '%s\n' "$err"
    return 1
}

# review_notes_pull <remote> → rc 0 se o remoto tinha notas (canônico ou espelho) | rc 1
# Traz refs/notes/review E o espelho do remoto e mescla os dois no ref local.
# Usado pelo pre-push (antes de empurrar) e pelo CI (review-verify.sh): assim
# uma prova que só chegou pelo espelho vale, e o próximo push de uma máquina
# que aceita refs/notes/* a leva para o ref canônico.
review_notes_pull() {
    local remote="$1" achou=1 src
    git fetch --quiet --no-tags "$remote" "+${NOTES_REF}:${NOTES_ORIGIN_REF}" 2>/dev/null && achou=0
    git fetch --quiet --no-tags "$remote" "+${NOTES_MIRROR_REF}:${NOTES_MIRROR_LOCAL_REF}" 2>/dev/null && achou=0
    [ "$achou" -eq 0 ] || return 1
    for src in "$NOTES_ORIGIN_REF" "$NOTES_MIRROR_LOCAL_REF"; do
        git rev-parse -q --verify "$src" >/dev/null 2>&1 || continue
        if ! git rev-parse -q --verify "$NOTES_REF" >/dev/null 2>&1; then
            git update-ref "$NOTES_REF" "$src"
            continue
        fi
        _review_notes_merge "$src" || _rv_say "git notes merge de ${src} falhou; sigo com as notas locais"
    done
    return 0
}

# Mesclar notas pode criar commit, e o runner do CI não tem identidade de git:
# sem uma, o merge falha e a prova que só está no espelho some. A identidade
# fixa só entra quando o git não tem nenhuma; a do dev nunca é trocada.
_review_notes_merge() {
    if git var GIT_COMMITTER_IDENT >/dev/null 2>&1; then
        git notes --ref="$NOTES_REF" merge -q -s union "$1" >/dev/null 2>&1
    else
        git -c user.name=review-gate -c user.email=review-gate@users.noreply.github.com \
            notes --ref="$NOTES_REF" merge -q -s union "$1" >/dev/null 2>&1
    fi
}
