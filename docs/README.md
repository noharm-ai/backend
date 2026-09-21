# NoHarm backend documentation

| Document | Read it when you want to… |
|---|---|
| [architecture.md](architecture.md) | Understand how the system is structured — layers, multi-tenancy, authorization, deployment topology, and the diagrams that tie them together |
| [installation.md](installation.md) | Run the backend locally: prerequisites, database setup, configuration reference, tests, troubleshooting |
| [user-guide.md](user-guide.md) | Call the API as a client: authentication, tenants, the core clinical workflows, error handling, FAQ |
| [api.md](api.md) | Look up a specific endpoint, its parameters and its payload |
| [deployment.md](deployment.md) | Deploy to a server or to AWS Lambda, and run the upgrade checklist |

At the repository root:

| Document | Contents |
|---|---|
| [../README.md](../README.md) | Project overview and quick start |
| [../CONTRIBUTING.md](../CONTRIBUTING.md) | How to fork, patch, test and open a pull request |
| [../CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md) | Community standards |
| [../SECURITY.md](../SECURITY.md) | How to report a vulnerability |
| [../CHANGELOG.md](../CHANGELOG.md) | Versioning scheme and where release notes live |
| [../LICENSE](../LICENSE) | MIT licence |

## Related repositories

| Repository | Contents |
|---|---|
| [noharm-ai/frontend](https://github.com/noharm-ai/frontend) | The React web application users interact with |
| [noharm-ai/database](https://github.com/noharm-ai/database) | The PostgreSQL schema and seed data this service runs against |

## Suggested reading order

1. [../README.md](../README.md) — what the system does and who uses it
2. [architecture.md](architecture.md) — how it is built
3. [installation.md](installation.md) — get it running
4. [user-guide.md](user-guide.md) + [api.md](api.md) — use it
5. [../CONTRIBUTING.md](../CONTRIBUTING.md) — change it
