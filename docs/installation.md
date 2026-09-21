# Installation guide

How to get the NoHarm backend running — on a developer machine, in a container,
or on a server. If you only want to *call* a running instance, read the
[user guide](user-guide.md) instead.

## 1. Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.12 or newer | The version CI uses |
| PostgreSQL | 16 | 11.6 also works; 16 is what the local setup provisions |
| Redis | 6 or newer | Optional for a first run; required for caching and rate limiting |
| Docker + Docker Compose | recent | Only needed for the scripted database setup |
| Git | any | Used to fetch the database schema repository |

The database schema is **not** in this repository. It lives in
[`noharm-ai/database`](https://github.com/noharm-ai/database) and is fetched by
the setup script described below.

## 2. Quick start (local development)

```bash
# 1. Clone
git clone https://github.com/noharm-ai/backend.git
cd backend

# 2. Create and activate a virtual environment
python3 -m venv env
source env/bin/activate          # Windows: env\Scripts\activate

# 3. Install dependencies
pip3 install --upgrade pip
pip3 install -r requirements.txt

# 4. Provision a database (starts PostgreSQL 16 in Docker and loads the schema)
make test-setup

# 5. Configure the environment
cp .env.example .env
# edit .env — at minimum set SECRET_KEY

# 6. Run
make dev
```

The API listens on `http://127.0.0.1:5000`.

`make dev` loads `.env`, activates `env/`, and runs `python3 mobile.py`. If you
manage the environment yourself, `python3 mobile.py` with the variables already
exported does the same thing.

### Verify the installation

```bash
curl -i http://127.0.0.1:5000/authenticate \
  -H 'Content-Type: application/json' \
  -d '{"email":"fulano@example.com","password":"wrong-on-purpose"}'
```

A JSON error response means the app, the configuration and the database
connection are all working. A connection refused or a stack trace means one of
them is not — see [troubleshooting](#7-troubleshooting) below.

## 3. Database setup

### Scripted (recommended)

```bash
make test-setup      # start the container and load the schema + seed data
make db-stop         # stop the container, keep the data
make db-start        # start it again
make db-reset        # destroy the volume and reload from scratch
```

`scripts/setup-test-db.sh` starts the container defined in
`docker-compose.test.yml` (PostgreSQL 16, database `noharm`, user `postgres`,
trust authentication, port 5432), clones `noharm-ai/database`, and applies the
SQL files in order:

| File | Contents |
|---|---|
| `noharm-public.sql` | The shared `public` schema |
| `noharm-create.sql` | Tenant schema structure |
| `noharm-newuser.sql` | Database roles |
| `noharm-triggers.sql` | Triggers |
| `noharm-insert.sql` | Seed and demo data (the `demo` schema) |

### Manual

Against any PostgreSQL instance you control:

```bash
git clone https://github.com/noharm-ai/database /tmp/noharm-database
createdb noharm
for f in public create newuser triggers insert; do
  psql "postgresql://user:password@host/noharm" \
    -f "/tmp/noharm-database/noharm-$f.sql" -v ON_ERROR_STOP=1
done
```

Then point `POTGRESQL_CONNECTION_STRING` at that database.

> The environment variable name is spelled `POTGRESQL_CONNECTION_STRING`. The
> typo is historical and is what the code reads.

## 4. Configuration

Configuration is read from environment variables (see `config.py`).
`.env.example` is the authoritative list; copy it to `.env` and fill it in.

### Required

| Variable | Description |
|---|---|
| `ENV` | `development`, `production` or `test` — selects the config class in `app/flask_config.py` |
| `SECRET_KEY` | JWT signing key. Use a long random value; never reuse it across environments |
| `POTGRESQL_CONNECTION_STRING` | Main database URL |

### Commonly needed

| Variable | Default | Description |
|---|---|---|
| `REDIS_HOST` / `REDIS_PORT` | `localhost` / `6379` | Cache and rate limiting |
| `ENCRYPTION_KEY` | — | Fernet key for sensitive data at rest |
| `API_KEY` | — | Shared key for internal service-to-service calls |
| `APP_URL` / `APP_DOMAIN` | — | Public frontend URL and cookie domain |
| `JWT_ACCESS_TOKEN_EXPIRES` | `20` | Access token lifetime, in minutes |
| `JWT_REFRESH_TOKEN_EXPIRES` | `30` | Refresh token lifetime, in days |
| `REPORT_CONNECTION_STRING` | — | Separate reporting database (SQLAlchemy bind `report`) |

### Optional integrations

Leave these empty to run without the corresponding feature.

| Variable group | Enables |
|---|---|
| `MAIL_HOST`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_SENDER`, `MAIL_TEMPLATE_HOST` | Outgoing e-mail (password reset, notifications) |
| `NIFI_BUCKET_NAME`, `NIFI_SQS_QUEUE_REGION`, `NIFI_LOG_GROUP_NAME` | The data-pipeline integration |
| `CACHE_BUCKET_NAME`, `CACHE_BUCKET_ID`, `CACHE_BUCKET_KEY` | S3-backed cache and report files |
| `SCORES_FUNCTION_NAME`, `BACKEND_FUNCTION_NAME` | Asynchronous Lambda invocations |
| `OPEN_AI_API_ENDPOINT`, `OPEN_AI_API_KEY`, `OPEN_AI_API_VERSION`, `OPEN_AI_API_MODEL` | LLM features via Azure OpenAI / OpenAI |
| `MARITACA_API_KEY` | LLM features via Maritaca |
| `ODOO_API_URL`, `ODOO_API_DB`, `ODOO_API_USER`, `ODOO_API_KEY` | Odoo ERP integration (support tickets) |

### Feature flags

| Variable | Default | Description |
|---|---|---|
| `FEATURE_CONCILIATION_ALGORITHM` | `FUZZY` | Algorithm used for medication reconciliation |
| `FEATURE_USER_ONBOARDING` | `false` | Enables the onboarding/training flow |

Per-tenant features (conciliation, regulation, culture, discharge summary, …)
are **not** environment variables — they are stored in each schema's
configuration and read through `services/feature_service.py`.

> **Never commit a filled-in `.env`.** `.gitignore` already excludes it. Real
> credentials, hospital hostnames and client identifiers belong in your secret
> manager, not in the repository.

## 5. Running the test suite

Tests need PostgreSQL; SQLite is not compatible with schema-based
multi-tenancy. Always go through the `make` targets, which set `ENV=test`.

```bash
make test-setup                                   # once
make test                                         # everything
make test-unit                                    # no database required
make test-integration                             # database required
make test-file FILE=tests/integration/test_drug.py
make test-cov                                     # HTML report in htmlcov/
```

Integration tests run against the `demo` schema of
`postgresql://postgres@localhost/noharm`. Override the connection with
`TEST_DATABASE_URL` (see `TestConfig` in `app/flask_config.py`).

A session-scoped fixture removes test-generated rows before and after each run,
so the suite is re-runnable without manual cleanup.

## 6. Linting

```bash
make lint      # ruff check . — the same check CI runs
```

## 7. Troubleshooting

**`.env not found`** — `make dev` requires it. `cp .env.example .env`.

**`connection refused` on port 5432** — the database container is not running.
`make db-start`, or `make test-setup` if it was never created.

**`psql: command not found` during `make test-setup`** — the script loads the
SQL from the host. Install the PostgreSQL client package
(`postgresql-client` on Debian/Ubuntu, `libpq` on macOS).

**`relation "..." does not exist`** — the schema was never loaded, or was loaded
partially. `make db-reset` reloads it from scratch.

**Tests fail with an authorization error** — every service must run at least one
`@has_permission` check; `@api_endpoint` rejects the request otherwise. Check
that the service function under test declares its permission.

**`ModuleNotFoundError` after pulling** — dependencies changed.
`pip3 install -r requirements.txt` inside the virtual environment.

**Timezone-related test failures** — the application forces
`America/Sao_Paulo`. Use `utils/dateutils.py` instead of naive `datetime`
values.

**Redis timeouts** — the client uses a 2 s timeout. If your local Redis is slow
or absent, leave `REDIS_HOST` pointing at a working instance or expect cache
operations to fail fast.

## 8. Next steps

- [architecture.md](architecture.md) — how the pieces fit together
- [user-guide.md](user-guide.md) — authenticate and make your first calls
- [deployment.md](deployment.md) — run it on a server or on AWS Lambda
- [../CONTRIBUTING.md](../CONTRIBUTING.md) — fork, patch and open a pull request
