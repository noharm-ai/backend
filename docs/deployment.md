# Deployment guide

The backend is an ordinary WSGI application, so it can be deployed in two ways:
as a serverless function (what the NoHarm project runs in production) or as a
long-running process behind any WSGI server (the simplest option for a
self-hosted instance).

## 1. Choosing a deployment model

| | Serverless (AWS Lambda + Zappa) | Self-hosted (WSGI server) |
|---|---|---|
| Entrypoint | `mobile.app` | `mobile.py` / `mobile:app` |
| Scaling | Automatic, per request | Managed by you |
| Cold starts | Yes (mitigated by keep-warm) | No |
| Infrastructure required | AWS account | A server or container runtime |
| Used by | The hosted NoHarm platform | Independent deployments |

Nothing in the application code depends on Lambda. If you are standing up your
own instance, the self-hosted path is the shorter one.

## 2. Prerequisites for any deployment

1. A PostgreSQL database with the schema from
   [`noharm-ai/database`](https://github.com/noharm-ai/database) loaded, and at
   least one tenant schema created.
2. A Redis instance (caching, rate limiting).
3. Environment variables set as described in
   [installation.md, section 4](installation.md#4-configuration). In particular:
   - `ENV=production`
   - a long, random, environment-specific `SECRET_KEY`
   - `POTGRESQL_CONNECTION_STRING`
   - `ENCRYPTION_KEY` if you store encrypted fields
4. HTTPS in front of the application. Tokens travel in the `Authorization`
   header and must never cross the network in clear text.

## 3. Self-hosted deployment

Install the production dependency set and run the app under a WSGI server:

```bash
python3 -m venv env
source env/bin/activate
pip3 install -r requirements-prod.txt
pip3 install gunicorn

export ENV=production
export SECRET_KEY='...'
export POTGRESQL_CONNECTION_STRING='postgresql://user:password@host/noharm'
export REDIS_HOST=... REDIS_PORT=6379

gunicorn 'mobile:app' --bind 0.0.0.0:5000 --workers 4 --timeout 120
```

Then put a reverse proxy (nginx, Caddy, an ingress controller) in front of it to
terminate TLS and forward to port 5000.

Sizing notes:

- The SQLAlchemy pool is 20 connections with 30 overflow **per process**.
  Multiply by your worker count and check it against the database's
  `max_connections`.
- Requests are short by design; a 120 s timeout is generous. Report generation
  is the main exception.

A container image is easy to build on the same basis — install
`requirements-prod.txt`, copy the source, and run the `gunicorn` command as the
entrypoint.

## 4. Serverless deployment (AWS Lambda + Zappa)

`zappa_settings.json` defines three stages — `dev`, `test` and `homolog` — all
running `mobile.app` on `python3.12` in `sa-east-1`, with 1024 MB of memory,
CORS enabled, an API Gateway API key required, and keep-warm scheduled.

```bash
python3 -m venv venv
source venv/bin/activate
pip3 install -r requirements-prod.txt

zappa deploy <stage>     # first deployment of a stage
zappa update <stage>     # every subsequent deployment
zappa tail <stage>       # stream CloudWatch logs
zappa rollback <stage> -n 1
zappa undeploy <stage>   # tear the stage down
```

Environment variables for Lambda are supplied through the deployment
environment (AWS console, `aws_environment_variables` in the Zappa settings, or
a secret manager) — never through a committed `.env` file.

Around the function you also need:

- **VPC access** if the database is not publicly reachable, plus a NAT route for
  any outbound calls (S3, LLM providers, Odoo).
- **IAM permissions** for the S3 buckets, the SQS queue, CloudWatch Logs, and
  `lambda:InvokeFunction` for the asynchronous jobs.
- **API Gateway**, with the API key the application expects.

## 5. Continuous delivery

The GitHub Actions workflows in `.github/workflows/` implement the pipeline.

| Workflow | Trigger | What it does |
|---|---|---|
| `build.yml` | Pull requests to `develop` and `master` | Ruff lint, then the pytest suite against a PostgreSQL service container seeded from `noharm-ai/database` |
| `deploy-dev.yml` | Push to the development branch | `zappa update dev` |
| `deploy-test.yml` | Push to `develop` | Tests, then `zappa update test` |
| `deploy-prod.yml` | Push to `master` | Tests, then `zappa update homolog` |
| `deploy-dev-manual.yml`, `deploy-test-manual.yml` | Manual dispatch | Redeploy a stage without a new commit |

Every AWS credential and integration secret is injected from GitHub Actions
secrets. None of them are stored in the repository.

## 6. Post-deployment checklist

- [ ] `ENV=production` — this disables the admin-only endpoints that exist for
      local debugging.
- [ ] `SECRET_KEY` is unique to this environment and stored in a secret manager.
- [ ] TLS terminates in front of the application.
- [ ] CORS origins in `app/flask_config.py` match the frontend's real origin.
- [ ] Database backups and point-in-time recovery are configured.
- [ ] Logs reach CloudWatch (or your log aggregator) and are retained for as
      long as your regulator requires.
- [ ] Redis is reachable within the 2 s client timeout.
- [ ] A smoke test passes: authenticate, list prescriptions, read one.

## 7. Upgrading

1. Read the release notes for the versions you are skipping — see
   [the releases page](https://github.com/noharm-ai/backend/releases) and
   [CHANGELOG.md](../CHANGELOG.md).
2. Apply any database changes from
   [`noharm-ai/database`](https://github.com/noharm-ai/database) **before**
   deploying the new code.
3. Deploy the backend.
4. Deploy a compatible [frontend](https://github.com/noharm-ai/frontend)
   version.

The frontend and backend are released together; keeping their minor versions
aligned is the supported configuration.
