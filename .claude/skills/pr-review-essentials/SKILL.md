---
name: pr-review-essentials
description: Faz a revisão essencial de um Pull Request (ou do diff de uma branch antes do push) num repositório NoHarm que tem o review-gate instalado, focada nos pontos definidos pelo tech lead — vazamento de secret, vazamento de infra, risco de supply chain (dependências/imagens/CI), aderência à organização/arquitetura do repo e problemas óbvios de segurança — com a régua de tolerância definida no `.review-gate/PERFIL.md` do repo. No fluxo GitHub posta o resultado como review (sempre em modo COMMENT, nunca aprova nem bloqueia sozinha); em modo local devolve o corpo da review para o hook pre-push gravar a prova. Use sempre que o usuário pedir para "revisar", "revisar essa PR", "dar uma olhada na PR X", "fazer o review essencial/básico", ou "modo local" antes de um push.
---

# PR Review — Essenciais (review-gate)

Checklist de revisão pedido pelo tech lead: pontos que ele olha em toda PR, antes de qualquer
outra coisa. Esta skill automatiza essa primeira passada — **não substitui revisão humana de
arquitetura/lógica de negócio em profundidade**, é o filtro rápido dos problemas que não podem
passar.

Esta skill é **genérica**: o que muda de repo para repo (onde o código roda, quem enxerga,
escala, arquitetura, baseline aceito) está em **`.review-gate/PERFIL.md`** do repositório, escrito
pelo tech lead. Instalada e atualizada pelo `install.sh` do
[review-gate](https://github.com/noharm-ai/review-gate); não edite este arquivo no repo
consumidor — o que é do repo vai no PERFIL.

## Onde esta skill roda

Três pontos de entrada, um só resultado (o corpo da review no template abaixo):

- **Antes do push, na máquina do dev** — é o caminho que *impõe* a revisão. O hook
  `.review-gate/hooks/pre-push` (ativado com `git config core.hooksPath .review-gate/hooks`, que o
  hook `SessionStart` do `.claude/settings.json` faz sozinho na primeira sessão no clone)
  bloqueia o push de qualquer branch sem uma prova de revisão para o conteúdo dela. A prova é
  uma nota de git em `refs/notes/review` (patch-id do diff + corpo da review), gravada por
  `.review-gate/hooks/review-receipt.sh`. Quem produz a review é esta skill em **modo local**
  (seção abaixo), rodada de duas formas: `bash .review-gate/hooks/review-local.sh` (headless,
  `claude -p`, login do próprio dev) ou `/pr-review-essentials modo local` numa sessão do Claude
  Code no clone.
- **No CI**, por `.github/workflows/pr-review-essentials.yml`, em toda PR para as branches base:
  **não roda modelo** — confere a nota do head da PR (mesma regra do hook,
  `.review-gate/hooks/lib.sh`) e republica o corpo como review COMMENT na PR. É o status check
  obrigatório `revisao-essencial`. Verde = a revisão rodou para exatamente este conteúdo.
- **Sob demanda, contra uma PR aberta** (fluxo GitHub abaixo): quando alguém pede para revisar a
  PR X. Aí a skill lê a PR pelas ferramentas do GitHub e posta a review ela mesma.

O cabeçalho `## Revisão essencial` (primeira linha do template) é o que o hook e o CI procuram
— `REVIEW_MARKER` em `.review-gate/hooks/lib.sh`; mudar o título aqui sem mudar lá deixa toda PR
vermelha (os testes do review-gate travam).

## Passo 0 — Ler o perfil do repositório

Leia `.review-gate/PERFIL.md` na raiz do checkout (Read). Ele tem quatro seções que calibram tudo
abaixo:

1. **Perfil de risco** — onde este código roda, quem consegue ler o checkout/os logs, em quantas
   instalações. Define a régua: código que roda em servidor de terceiro pede a tolerância mais
   baixa possível para secret/infra leak; serviço interno atrás de VPN pede menos.
2. **Arquitetura e convenções** — o que conta como violação de estrutura (ponto 4). Sem isso,
   "diferente do que eu faria" vira achado, e não é.
3. **Baseline aceito / falsos positivos conhecidos** — o que NÃO é achado neste repo (ex.: um
   arquivo de env local que carrega credencial por design).
4. **Áreas sensíveis** — arquivos/diretórios a olhar primeiro numa PR grande.

Se o PERFIL não existir ou ainda for o stub do instalador, siga com o `CLAUDE.md`/`README.md` do
repo como fonte e **diga na review** (uma linha, no rodapé) que o perfil está por preencher —
sem isso a ausência passa em silêncio e a régua fica implícita.

## Os pontos essenciais

1. **Vazamento de secret** — credenciais, tokens, chaves de API, senhas, chaves privadas
   (`BEGIN PRIVATE KEY`), connection strings com usuário/senha embutidos, cookies/JWT reais,
   `.env` com valores reais (não `.env.example`) commitado no diff. O baseline do PERFIL diz o
   que é design aceito; achado é o segredo aparecer fora desse mecanismo.
2. **Vazamento de infra** — hostnames internos, IPs privados, ARNs, account IDs de nuvem, URLs
   de ambiente interno, topologia de rede exposta em código/doc/comentário; dado real de cliente
   ou paciente em fixture, backup ou diretório que deveria estar no `.gitignore`. Nome de
   cliente/hospital em arquivo versionado conta aqui quando o PERFIL diz que o checkout é visível
   a terceiros.
3. **Risco de supply chain** — `Dockerfile` com base image sem tag fixa (`:latest`) ou de registry
   não oficial; dependência nova não pinada ou de origem estranha (typosquatting) em
   `requirements*.txt`, `pyproject.toml`, `package.json`, lockfiles; `curl`/`wget` de script
   executável direto de URL em Dockerfile ou script de setup; GitHub Action de terceiro
   referenciada por tag mutável em vez de SHA fixo; instalação de pacote fora do wrapper que o
   repo adota (ex.: `sfw`), quando o PERFIL/CI exigem.
4. **Organização/estrutura do código** — o diff respeita a arquitetura documentada no PERFIL
   (e no `CLAUDE.md` do repo): separação de camadas/módulos, onde entra comando/rota/serviço
   novo, o que é código genérico e o que é específico, idempotência e confirmação em operação
   destrutiva. Só é achado quando contradiz algo que o repo **declara** como convenção.
5. **Problema óbvio de segurança** — injection (SQL/comando/path), validação ausente numa borda
   de confiança (input de usuário, dado vindo de sistema externo), segredo logado em texto plano,
   deserialização insegura, comando shell montado por concatenação de string sem sanitização,
   arquivo temporário em caminho previsível de `/tmp`.

## Workflow (fluxo GitHub — PR aberta)

### 1. Resolver a PR

A partir do que o usuário passou (URL, número, ou descrição), determine `owner`, `repo` e
`pullNumber`. Sem `owner`/`repo` explícitos, use o remoto `origin` do checkout.

Busque os dados da PR com `mcp__github__pull_request_read`:
- `method: get` — título, descrição, branch base/head, autor.
- `method: get_diff` — o diff completo (ponto de partida da análise).
- `method: get_files` — lista de arquivos tocados, paginando se for grande.

### 2. Confirmar as regras do repo contra a fonte viva

O PERFIL cobre o ponto 4 na maioria dos casos. Quando precisar do detalhe, busque no `CLAUDE.md`
do repo **só a seção** da área que a PR toca (Read/Grep no checkout; pela API com
`mcp__github__get_file_contents` se não houver checkout) — não leia o arquivo inteiro. Problema
já documentado pelo repo como conhecido e resolvido **não é achado novo**; só vira achado se a PR
o reintroduz, o piora, ou o espalha para um lugar novo.

### 3. Analisar o diff contra os pontos essenciais

Percorra o diff arquivo a arquivo. Para cada achado, anote: arquivo, linha, qual dos pontos
essenciais, e o cenário concreto de falha (que dado vaza, ou que quebra, e em que condição) —
sem isso o achado é ruído, não uma revisão. Com o perfil de risco alto, erre para o lado de
reportar quando em dúvida sobre secret/infra leak.

Juízo sobre falso positivo:
- `.env.example`, fixtures de teste, valores obviamente fake (`changeme`, `xxx`, `sk-teste`)
  não são secret real — mas hardcode de algo que parece uma chave real, mesmo em teste, merece
  ao menos uma nota de baixa confiança.
- No ponto 3, diferencie "dependência nova, legítima, só não é o que eu escolheria" (não é
  achado) de "dependência/imagem/action sem verificação mínima de origem ou integridade" (é).
- No ponto 4, "diferente do que eu faria" não é achado.

Se, depois de investigar, um ponto não tiver nada a reportar, não invente achado para preencher
a categoria — "sem problema encontrado aqui" é o resultado correto.

### Histórico da branch — o que o diff acumulado esconde

`git diff <mb> <head>` mostra o resultado final. Um segredo commitado e apagado no commit seguinte
**não aparece nele** — e o push leva o commit assim mesmo: fica no remoto, em forks e em clones, e
squash merge não apaga a branch da PR. O único momento em que isso ainda se resolve por completo é
antes do push, reescrevendo a branch. Por isso a checagem é parte da revisão local.

Entrada: as linhas que algum commit de `<mb>..<head>` **adicionou** e outro commit da mesma branch
**removeu ou alterou** depois. Quem calcula é `.review-gate/hooks/review-history.sh <mb> <head>`
(`lib.sh:review_ghost_lines`), saída agrupada por commit (`# <sha> <assunto>` e depois
`<arquivo>: <linha>`). Em modo headless o `review-local.sh` já entrega essa lista no prompt (ou diz
para rodar o script quando é grande); em sessão interativa, rode o script você mesmo. Lista vazia
= nada a checar além do diff.

Sobre essa lista aplique **só os pontos 1 e 2** (secret e infra leak): estrutura, supply chain e
segurança de código que já não existe no head não são achado. A régua é a mesma do diff, com uma
diferença na saída:

- O achado cita o **commit** (`sha curto`) e `arquivo`, além do valor **mascarado** como na seção
  abaixo — o commit é o que o dev precisa para corrigir.
- A recomendação é **reescrever o histórico antes do push**, não só "remover": o valor já foi
  removido, o problema é o commit. Indique `git rebase -i <mb>` marcando o commit como `edit` (ou
  `fixup` do commit que removeu no commit que adicionou) e confira com `git log -p` que a linha
  sumiu de todos os commits. O pre-push aceita a branch reescrita sem nova revisão quando o diff
  acumulado não mudou (a prova é por patch-id).
- Se a branch **já foi empurrada** alguma vez com aquele commit (`git branch -r --contains
  <sha>` mostra o remoto, ou a PR já existia), reescrever não desfaz: o segredo é considerado
  comprometido e tem de ser **rotacionado**. Diga isso na review, sem suavizar.

No template, o resultado vai na linha **Histórico da branch**. Em modo GitHub (PR aberta) os
commits já estão no remoto: se houver checkout local, rode o script com o merge-base e o head da
PR e reporte com a orientação de rotacionar; sem checkout, diga no rodapé que o histórico não foi
checado.

### Mascarar o segredo antes de escrever o achado

Tudo o que esta skill escreve vira texto público: o corpo da review é gravado na nota
(`refs/notes/review`), empurrado com a branch e **republicado pelo CI como comentário na PR**; o
comentário de linha vai direto para o GitHub. Reportar um secret/infra leak copiando o valor
para o achado é publicar o leak uma segunda vez, agora fora do diff e fora do alcance de um
`git push --force`.

Regra: **nunca reproduza em claro o valor vazado** — nem no corpo, nem no comentário de linha,
nem no cenário de falha. Mostre-o mascarado, o suficiente para o dev localizar e nada mais:

- Secret (token, senha, chave, JWT, cookie): os 4 primeiros caracteres e o comprimento, resto
  substituído por `*`. Ex.: `AKIA****************` (20 caracteres), `ghp_************ (40)`.
  Chave privada: só `-----BEGIN PRIVATE KEY----- (…)`, sem nenhuma linha do corpo.
- Connection string / URL com credencial: mantenha esquema, host e caminho, mascare usuário e
  senha. Ex.: `postgres://****:****@db.exemplo.interno/app`.
- Infra (IP privado, hostname interno, ARN, account ID): mascare os octetos/segmentos finais e a
  conta. Ex.: `10.0.***.***`, `arn:aws:iam::****:role/deploy`, `*.interno.exemplo`.
- Dado pessoal ou clínico de paciente em fixture/backup: nunca reproduza — diga o tipo do dado
  (`CPF`, `nome`, `prontuário`) e onde está (`arquivo:linha`).

Vale também em modo local: o terminal é do dev, mas o mesmo texto vai para a nota e para a PR.

### 4. Postar o review no GitHub — sempre como COMMENT

O veredito (aprovar ou pedir mudança) é decisão humana. Esta skill **nunca** submete a review
como `APPROVE` nem `REQUEST_CHANGES` — sempre `COMMENT`, mesmo quando encontra algo grave.
Achado grave vira destaque no texto, não bloqueio automático.

Sequência (`mcp__github__pull_request_review_write` + `mcp__github__add_comment_to_pending_review`):

1. `pull_request_review_write` `method: create` (sem `event`) — abre a review pendente.
2. Para cada achado com localização precisa, `add_comment_to_pending_review` com `path`, `line`
   (e `startLine`/`side` se cobrir um range), `subjectType: LINE`, e o corpo explicando o achado
   e o cenário de falha.
3. `pull_request_review_write` `method: submit_pending`, `event: COMMENT`, com o `body` resumo
   (template abaixo).

Sem nenhum achado, ainda assim submeta uma review `COMMENT` curta confirmando que os pontos
foram checados — silêncio total não deixa rastro de que a revisão rodou.

**Toda review/comentário postado no GitHub termina com o rodapé de atribuição:**

```
---
_Generated by [Claude Code](https://claude.ai/code)_
```

### Template do corpo da review (resumo)

```markdown
## Revisão essencial (secret / infra / supply chain / estrutura / segurança)

**Secret leaks:** ✅ nada encontrado | ⚠️ N achado(s)
**Infra leaks:** ✅ nada encontrado | ⚠️ N achado(s)
**Supply chain:** ✅ nada encontrado | ⚠️ N achado(s)
**Estrutura/organização:** ✅ ok | ⚠️ N achado(s)
**Segurança óbvia:** ✅ ok | ⚠️ N achado(s)
**Histórico da branch:** ✅ nada sensível em commit intermediário | ⚠️ N achado(s) — reescrever antes do push

<achados relevantes resumidos em 1 linha cada, com arquivo:linha ou link pro comentário de linha;
 valor vazado sempre mascarado, nunca em claro>

Revisão automática dos pontos essenciais definidos pelo time — não substitui review humana de
lógica de negócio/arquitetura em profundidade. Régua: a do `.review-gate/PERFIL.md` deste repo.

---
_Generated by [Claude Code](https://claude.ai/code)_
```

## Modo local (antes do push — sem PR, sem GitHub)

Invocada como `/pr-review-essentials modo local: branch <b> para <base>. Merge-base <mb>, head
<sha>.` — pelo `review-local.sh` (headless) ou pelo dev numa sessão do Claude Code no clone.
Não existe PR ainda. Diferenças em relação ao fluxo GitHub:

1. **Entrada** é o diff local, com os shas exatos do prompt: `git diff <mb> <sha>` e
   `git log --oneline <mb>..<sha>` (só `git diff`/`log`/`show` e o `review-history.sh` são
   permitidos). Se o prompt não trouxer os shas, calcule: base conforme
   `.review-gate/review.conf` (`REVIEW_BASE_BRANCH`; `REVIEW_HOTFIX_BASE` para `hotfix/*`),
   `mb = git merge-base origin/<base> HEAD`, `sha = HEAD`. Mais o **histórico da branch** (seção
   acima): headless, a lista vem no prompt; interativo, rode
   `bash .review-gate/hooks/review-history.sh <mb> <sha>`.
2. **Passo 0 e 2** usam Read/Grep no checkout, não a API.
3. **Análise** igual: os cinco pontos, mesma régua. Achado com localização cita `arquivo:linha`
   no texto (não há comentário de linha).
4. **Saída** é o corpo da review no template acima, primeira linha começando por
   `## Revisão essencial` — sem achado, o mesmo template com ✅. Nada de ferramentas do GitHub.
5. **Prova.** Em modo headless (chamada pelo `review-local.sh`), responda **só** com o corpo:
   quem grava a nota é o script. Em sessão interativa, escreva o corpo num arquivo temporário e
   rode `bash .review-gate/hooks/review-receipt.sh HEAD <arquivo> --origem sessao`; ele valida o
   cabeçalho, calcula o patch-id e grava a nota. Depois diga ao dev: `git push` (o hook empurra
   `refs/notes/review` junto; se o remoto recusar `refs/notes/*`, como o proxy de git das sessões
   do Claude Code na nuvem, o hook empurra a branch-espelho `review-gate/notes`, que o CI também
   lê. Não é preciso nenhum passo à mão).

Achado **não** bloqueia o push nem o merge — só "a revisão não rodou" bloqueia. O veredito é
humano, aqui como no fluxo GitHub.

## Guardrails

- Nunca aprove nem peça mudanças sozinha — o veredito é sempre humano.
- Nunca escreva em claro um valor vazado (secret, credencial, IP/host interno, dado de paciente)
  no corpo da review nem em comentário de linha — sempre mascarado (seção "Mascarar o segredo").
  A review é publicada como comentário na PR pelo CI.
- Achado no histórico da branch (linha commitada e removida antes do push) pede **reescrever a
  branch** antes de empurrar, e **rotacionar** se aquele commit já esteve em algum remoto — diga
  as duas coisas; "já foi removido" não encerra o assunto.
- Nunca reabra como achado novo uma dívida que o próprio repo documenta como conhecida e
  resolvida/aceita — cite que existe, mas só marque como achado se a PR a reintroduz/piora.
- O baseline do PERFIL não é achado por existir; achado é o que vai além dele.
- Antes de reportar violação de estrutura (ponto 4) com confiança alta, confirme contra o PERFIL
  e o `CLAUDE.md` vivo do repo.
- PR grande demais para o diff inteiro de uma vez: pagine e priorize as **áreas sensíveis** do
  PERFIL e, sempre, config, `.env*`, Dockerfile, manifestos de dependência, workflows de CI,
  módulos de secrets/auth — antes de ir arquivo por arquivo em ordem alfabética.
