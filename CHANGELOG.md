# Changelog and release notes

## Where release notes live

Release notes for every version are published on the GitHub releases page:

**<https://github.com/noharm-ai/backend/releases>**

Each release lists the pull requests merged since the previous one, with their
authors and links to the full diff. That page is the authoritative record; this
file documents how versions are numbered and how a release is produced.

## Versioning scheme

Versions are numbered `v<MAJOR>.<MINOR>-beta`, for example `v6.60-beta`.

| Component | Meaning |
|---|---|
| `MAJOR` | Incremented on a significant platform change. A major bump can require a database migration and a coordinated frontend release. |
| `MINOR` | Incremented on every regular release — new endpoints, clinical rules, fixes. Backward compatible with the previous minor of the same major. |
| `-beta` | The suffix the project has carried since the 6.x line; it marks the release channel, not an unstable build. These are the versions running in production. |

What this means for an integrator:

- **Within a major version**, existing endpoints keep their paths, request
  shapes and response envelope. New optional fields may be added — clients must
  ignore unknown fields rather than reject them.
- **Across a major version**, assume something breaks and read the release notes.
- **Removals and renames** are announced in the release notes before they ship.
  The codebase marks superseded permissions and fields as deprecated for at
  least one release before removing them.

The [frontend](https://github.com/noharm-ai/frontend) is versioned separately
(`MAJOR.MINOR.PATCH`) but released in step with the backend. Running matching
minor versions of both is the supported configuration.

## Recent releases

| Version | Date |
|---|---|
| [v6.60-beta](https://github.com/noharm-ai/backend/releases/tag/v6.60-beta) | 2026-09-07 |
| [v6.57-beta](https://github.com/noharm-ai/backend/releases/tag/v6.57-beta) | 2026-08-26 |
| [v6.44-beta](https://github.com/noharm-ai/backend/releases/tag/v6.44-beta) | 2026-07-15 |
| [v6.35-beta](https://github.com/noharm-ai/backend/releases/tag/v6.35-beta) | 2026-06-01 |
| [v6.30-beta](https://github.com/noharm-ai/backend/releases/tag/v6.30-beta) | 2026-05-12 |

See the [releases page](https://github.com/noharm-ai/backend/releases) for the
complete history and the notes of each version.

## Release process

1. Work is merged into `develop` through pull requests. Every pull request runs
   the lint and test workflow, and merging deploys to the test environment.
2. When `develop` is ready to ship, it is merged into `master`.
3. A push to `master` runs the tests again and deploys.
4. A tagged release is published on GitHub with generated notes.
5. Any database change is applied from
   [`noharm-ai/database`](https://github.com/noharm-ai/database) **before** the
   code that needs it is deployed.

## Upgrading

Read [docs/deployment.md, section 7](docs/deployment.md#7-upgrading) before
upgrading an existing installation.
