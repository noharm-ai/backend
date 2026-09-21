# Contributing to the NoHarm backend

Thank you for considering a contribution. This project is open source and
open to outside contributors — bug reports, documentation fixes, new clinical
rules and whole features are all welcome.

By participating you agree to abide by our
[Code of Conduct](CODE_OF_CONDUCT.md).

## Ways to contribute

| | Where to start |
|---|---|
| Report a bug | [Open an issue](https://github.com/noharm-ai/backend/issues) with steps to reproduce, the version, and what you expected |
| Suggest a feature | Open an issue describing the clinical or operational problem first — the solution is easier to agree on afterwards |
| Improve documentation | Edit the files in `docs/` and open a pull request; no issue required |
| Fix a bug or build a feature | Follow the workflow below |
| Report a vulnerability | **Do not open an issue** — follow [SECURITY.md](SECURITY.md) |

## Development workflow

### 1. Set up

Follow [docs/installation.md](docs/installation.md). In short:

```bash
git clone https://github.com/<your-username>/backend.git
cd backend
python3 -m venv env && source env/bin/activate
pip3 install -r requirements.txt
make test-setup
cp .env.example .env
```

Read [docs/architecture.md](docs/architecture.md) before your first change — the
layering rules there are what code review checks against.

### 2. Fork and branch

External contributors work from a fork; maintainers branch directly.

| Branch | Purpose |
|---|---|
| `master` | Production. Never commit to it directly. |
| `develop` | Integration branch. **Branch from here and target it in your pull request.** |
| `feature/...`, `fix/...` | Your work |

```bash
git remote add upstream https://github.com/noharm-ai/backend.git
git fetch upstream
git checkout -b fix/short-description upstream/develop
```

### 3. Write the change

Follow the existing patterns; the reviewer will ask for them otherwise.

- **Respect the layering.** Routes parse HTTP and call one service. Services
  hold the business rules. Repositories hold the queries. Models hold no logic.
- **Validate with Pydantic.** Every request body or query string becomes a model
  in `models/requests/`. Do not read `request.json` inside a service.
- **Declare permissions.** Service functions that act on tenant data carry
  `@has_permission(...)` and accept `user_permissions: list[Permission]`. A
  request that performs no permission check is rejected at runtime — that is
  intentional, not a bug to work around.
- **Never hard-code a schema name.** The tenant comes from the token; queries
  leave the schema implicit.
- **Raise `ValidationError`** with a message, an i18n key and a status code for
  business-rule failures, rather than returning an error dictionary.
- **Use `utils/dateutils.py`** for anything involving dates; the platform runs
  in `America/Sao_Paulo`.
- **Add a short docstring** to every function you create.
- **Type hints** where they make the signature clearer.

### 4. Test

```bash
make lint                                          # ruff — the same check CI runs
make test                                          # full suite
make test-file FILE=tests/integration/test_drug.py # while iterating
```

New behaviour needs a test. Put tests that need no database in `tests/unit/` and
the rest in `tests/integration/`. Integration tests run against the `demo`
schema; test-generated prescriptions use IDs ≥ 100,000 and test substances IDs
≥ 10,000 so the cleanup fixture can find them.

Both lint and tests must pass locally before you push — a red pull request
costs a review cycle.

### 5. Commit

Write commit messages in the imperative mood, with a type prefix:

```
fix: reject conciliation on a prescription without an admission
feat: add culture alerts to the prescription payload
docs: document the multi-tenant request lifecycle
test: cover the prioritization filters
refactor: move the score calculation into the service layer
```

Keep the subject under ~72 characters and explain *why* in the body when it is
not obvious.

### 6. Open a pull request

Target `develop`. In the description, say what changed, why, and how you tested
it; link the issue it closes. Pull requests run lint and the full test suite
automatically.

Keep pull requests focused — one problem per pull request reviews far faster
than a mixed batch.

## Test data

**Never put a real person's data in this repository.** Not in code, tests,
fixtures, comments, docstrings or commit messages. This covers names, e-mail
addresses, phone numbers, CPF, CNS, addresses, patient records and credentials —
including your own and the maintainers'.

Use obviously fictitious values instead:

| Kind | Use |
|---|---|
| People | `Fulano Beltrano`, `Ciclano de Tal`, `Maria Teste` |
| E-mail | `fulano@example.com` (`example.com` is reserved for this) |
| Documents | Clearly invalid placeholders — never a real or checksum-valid CPF/CNS |
| Patients | Synthetic names and identifiers only |

This is a healthcare product. Real patient data in a public repository is a
compliance incident, not a style problem.

The same rule covers secrets: no connection strings, API keys, AWS identifiers,
hospital hostnames or client names. `.env` is git-ignored; keep it that way.

## Dependencies

1. Add the pinned version to `requirements.txt`.
2. If the dependency is needed at runtime in production, add it to
   `requirements-prod.txt` as well.
3. Say in the pull request why the dependency is needed — the deployment target
   is a Lambda package, so size and transitive dependencies matter.

## Database changes

Schema changes do **not** live in this repository. They go to
[`noharm-ai/database`](https://github.com/noharm-ai/database) and must be
merged and applied before the code that depends on them is deployed. Mention the
companion pull request in yours.

## Review and merge

A maintainer reviews every pull request. Expect questions about clinical
correctness as well as code — a wrong dose rule is a patient-safety issue.
Once approved and green, a maintainer merges into `develop`; it reaches
production on the next release (see [CHANGELOG.md](CHANGELOG.md)).

## Licence

Contributions are accepted under the repository's [MIT licence](LICENSE). By
submitting a pull request you confirm that you have the right to contribute the
code and that it may be distributed under that licence.
