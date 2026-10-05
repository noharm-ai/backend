# Perfil de revisão deste repositório

Lido pela skill `pr-review-essentials` (`.claude/skills/pr-review-essentials/SKILL.md`) antes de
toda revisão. É o que muda de repo para repo; a skill em si é genérica e vem do
[review-gate](https://github.com/noharm-ai/review-gate).

## 1. Perfil de risco

**Régua: a mais baixa possível para secret e infra leak.**

- **O repositório é PÚBLICO no GitHub** (`noharm-ai/backend`). Qualquer pessoa lê o código, o
  histórico de commits, as mensagens de commit, as PRs e **os comentários de review** — inclusive
  o corpo desta review, que o CI republica na PR. O que entra num commit está publicado, mesmo que
  seja removido no commit seguinte; um secret que chegou ao remoto tem de ser **rotacionado**.
- **Onde roda:** infra da NoHarm, AWS `sa-east-1`, como Lambda atrás de API Gateway (Zappa,
  `zappa_settings.json`), com RDS PostgreSQL, Redis, S3, SQS, CloudWatch e Lambdas auxiliares.
  Não roda em servidor de cliente. Logs ficam no CloudWatch, visíveis só ao time.
- **Escala:** uma única instalação **multi-tenant** atende todos os clientes (hospitais e redes de
  saúde), um schema PostgreSQL por cliente. Um furo de isolamento de tenant ou de autorização
  expõe dado de **todos** os hospitais de uma vez.
- **Dado tocado:** PHI no sentido pleno — pacientes, prescrições, exames, evoluções e notas
  clínicas, alergias, intervenções. O que vai para provedores de LLM (Azure OpenAI, Maritaca,
  Bedrock via `strands-agents`) é **anônimo por design**: não há como relacionar ao paciente.
  Achado é a PR quebrar essa garantia — passar a enviar nome, identificador (prontuário,
  atendimento, ID de paciente/prescrição) ou outro dado que permita a reidentificação. Credenciais em jogo: chave de assinatura do JWT,
  `ENCRYPTION_KEY`, `API_KEY` interna, Odoo, OpenAI/Maritaca, SMTP, connection strings do RDS,
  credenciais AWS (só em GitHub Secrets).
- **Consequência para a régua:** nome de cliente/hospital, nome de schema de tenant real, host
  de RDS/Redis, ARN, account ID, ID de VPC/subnet/security group, URL de ambiente interno e
  qualquer dado de pessoa real são achado, mesmo em comentário, teste, doc ou mensagem de commit.

## 2. Arquitetura e convenções

A referência viva é o `CLAUDE.md` (seção *Common Patterns*) e o `docs/architecture.md`. O que
conta como violação aqui:

- **Camadas:** `routes/` → `services/` → `repository/` → `models/`. Rota não tem regra de negócio
  nem acessa o banco; repository não decide autorização; model não tem regra de negócio. Chamada
  na direção contrária é defeito declarado (architecture.md §2).
- **Rota nova:** fina, envolvida em `@api_endpoint()` (verifica JWT, fixa o schema do tenant,
  commit/rollback, envelope `{"status": "success", "data": ...}`). Entrada sempre por modelo
  Pydantic em `models/requests/` (`request.get_json()` em POST/PUT,
  `request.args.to_dict(flat=True)` em GET). Blueprint novo registrado em `app/blueprints.py`.
- **Autorização:** toda função de serviço chamada por uma rota tem `@has_permission(...)` e aceita
  `user_permissions`. O `@api_endpoint` devolve 401 se nenhuma checagem de permissão rodou — um
  serviço sem decorator é bug, e um que contorna esse contador (ex.: mexer em
  `g.permission_test_count`) é achado de segurança. Permissão nova vai em
  `security/permission.py` e é atribuída a papel em `security/role.py`; permissão mais ampla que
  o necessário (ex.: `ADMIN` onde bastava leitura) é achado. `@api_endpoint(is_admin=True)`
  **bloqueia o endpoint em produção** (ferramenta só de dev/homolog) — remover essa flag de
  rota existente é mudança de superfície em produção e precisa estar justificada na PR.
- **Multi-tenancy:** o tenant vem **só** do JWT (`user_context.schema` / `schema_translate_map`),
  **nunca** de body, query string ou path. Query não fixa nome de schema de tenant; join com
  `public` nomeia `public` explicitamente. Rotas novas no estilo `/static/<schema>/...`
  (schema vindo da URL) não devem ser criadas.
- **SQL cru:** `text(...)` com parâmetros ligados (`:param`). Interpolar valor de usuário em
  f-string SQL é SQL injection. Interpolar `{schema}` só é aceitável quando ele vem de
  `user_context.schema` ou do contexto estático já autenticado — nunca de input.
- **Erros:** regra de negócio levanta `ValidationError(msg, "chave.i18n", status.HTTP_...)`;
  autorização, `AuthorizationError`. Não devolver traceback/exception crua ao cliente.
- **Banco:** sem migrations neste repo — DDL vive em `noharm-ai/database`. Model alterado sem a
  mudança correspondente lá, ou DDL de produção escondido em código de serviço, é achado.
- **Funções internas (Lambda):** `static.py` + `utils/static_context.py` rodam com usuário
  estático (`Role.STATIC_USER`); não expor isso por HTTP nem aceitar papel diferente ali.
- **Feature flag × permissão:** permissão diz *quem* pode; feature flag
  (`feature_service`, `FeatureEnum`) diz *se o tenant contratou*. Usar um no lugar do outro é
  achado.
- **Testes e dados:** nunca dado de pessoa real (inclusive dos mantenedores) em código, teste,
  fixture, docstring ou commit — ver *Test Data* no `CLAUDE.md`. Testes usam o schema `demo`,
  prescrições de teste com ID ≥ 100.000 e substâncias de teste com ID ≥ 10.000.
- **Configuração:** valor de ambiente entra por `getenv` em `config.py` e é documentado em
  `.env.example` com placeholder vazio ou fake.

## 3. Baseline aceito / falsos positivos conhecidos

Não é achado por si só:

- `.env.example` com placeholders (`change-me`, vazio, `user@example.com`, `localhost`).
- Fallbacks de desenvolvimento já existentes em `config.py` (`"secret_key"`, `"password"`,
  `"user@gmail.com"`, `postgresql://postgres@localhost/noharm`). **Achado** é um fallback novo
  com cara de credencial real, ou um fallback que passa a valer em produção sem a env var.
- `config.py` aparece no `.gitignore` mas **é versionado** — mudanças nele vão para o remoto
  público como qualquer outro arquivo; não presuma que ficou local.
- `config/certs.pem`: bundle público de CA (certificado, não chave privada). Achado só se
  aparecer `BEGIN ... PRIVATE KEY`.
- `zappa_settings.json`: região `sa-east-1`, nome do projeto e do bucket de deploy já públicos.
  ARN, account ID, VPC/subnet/SG ou role novos ali são achado.
- `PROTOCOL_AGENT_MODEL_ID` padrão em `config.py` (ID público de modelo do Bedrock).
- Referências `${{ secrets.* }}` nos workflows — é o mecanismo correto.
- Schema `demo`, banco `noharm`, usuário `postgres` sem senha em `docker-compose.test.yml`,
  `Makefile`, `scripts/setup-test-db.sh` e `tests/`: ambiente de teste local.
- Nomes fictícios (`Fulano`, `Ciclano`, `Maria Teste`, `@example.com`) em testes.
- SQL cru que interpola `{schema}` vindo do `user_context` (padrão existente em `repository/`).
- Log com nome de schema, ID de prescrição ou ID de usuário para CloudWatch (padrão existente).
  **Achado** é logar conteúdo clínico, nome de paciente, token, senha ou payload completo.
- `apiKey` devolvido no login por `services/auth_service.py` — comportamento existente de que o
  frontend depende; só é achado se a PR o espalhar para outro endpoint ou log.
- Rotas `/static/<schema>/...` em `routes/static.py`: legado depreciado, não reabrir como achado
  — mas estender esse padrão é.

## 4. Áreas sensíveis

Olhar primeiro numa PR grande:

- **Autenticação e autorização:** `decorators/api_endpoint_decorator.py`,
  `decorators/has_permission_decorator.py`, `security/permission.py`, `security/role.py`,
  `services/auth_service.py`, `routes/authentication.py`, `routes/user.py`,
  `routes/user_admin.py`, `services/admin/`, `routes/admin/`.
- **Isolamento de tenant:** `models/main.py` (`dbSession.setSchema`), qualquer `text(...)` em
  `repository/` e `services/`, troca de schema (`switch-schema`), `static.py`,
  `utils/static_context.py`, `routes/static.py`.
- **Configuração e app:** `config.py`, `.env.example`, `app/flask_config.py` (CORS, JWT, cookies),
  `app/security.py` (headers), `app/extensions.py`, `app/handlers.py` (o que vaza no erro).
- **Criptografia e PHI saindo do sistema:** `utils/cryptutils.py`, `utils/logger.py`,
  `app/logging_config.py`, `services/llm_service.py`, `services/protocol_agent_service.py` e
  `agents/` (o que entra no prompt continua anônimo?), `services/odoo_client.py`,
  `utils/emailutils.py`, `utils/aws.py`, `utils/lambdautils.py`, relatórios em
  `services/reports/` e `routes/reports/` (exportação de dados).
- **Supply chain e deploy:** `requirements.txt` e `requirements-prod.txt` (sempre pinados com
  `==`; dependência nova precisa entrar nos dois quando vai para produção),
  `zappa_settings.json`, `docker-compose.test.yml` (imagem com tag fixa), `.github/workflows/*`
  (actions de terceiros pinadas por SHA; instalação de pacote via `sfw pip`; o clone de
  `noharm-ai/database` sem pin é baseline),
  `scripts/`, `Makefile`.
- **Fixtures e dados:** `tests/` (dados de pessoa real), `assets/`, qualquer CSV/JSON/dump novo.
- **O próprio portão:** `.review-gate/`, `.claude/`, `.github/workflows/pr-review-essentials.yml` —
  PR que enfraquece hook, workflow ou este perfil merece atenção explícita.
