---
name: review-changes
description: Code review of branch changes against remote origin/develop. Use when you want a review of current branch changes before merging or creating a PR.
allowed-tools: Bash(git *), Read, Grep
---

# NoHarm Backend - Code Review

Review the current branch changes against `origin/develop` using NoHarm's architecture and coding standards.

## Context

- **Current branch:** !`git rev-parse --abbrev-ref HEAD`
- **Changed files:** !`git diff origin/develop...HEAD --name-only`
- **Diff summary:** !`git diff origin/develop...HEAD --stat`

## Full diff

!`git diff origin/develop...HEAD`

---

## Review checklist

Go through every changed file and evaluate the following, reporting only actual issues found (skip passing checks):

### Architecture & Patterns
- Routes are thin (only request parsing + service call, no business logic)
- Services contain business logic and are properly decorated
- Repository layer handles only data access (no business logic)
- New endpoints follow the blueprint registration pattern

### Permission System
- Every service function with `@has_permission` accepts the `user_permissions: list[Permission]` parameter
- Permissions used are appropriate for the operation (READ vs WRITE)
- No permission checks bypassed or missing for sensitive operations

### Request Validation
- POST/PUT endpoints use Pydantic models with `request.get_json()`
- GET endpoints use Pydantic models with `request.args.to_dict(flat=True)`
- No raw `request.form` or unvalidated input passed to services

### Multi-tenancy & Schema
- Repository queries respect schema context via `schema_translate_map`
- No hardcoded schema names
- Cross-schema joins are explicit and intentional

### Error Handling
- Business logic errors raise `ValidationError` (not generic exceptions)
- `ValidationError` includes a user-friendly message, an i18n key, and proper HTTP status code
- No bare `except:` or silent error swallowing

### Security
- No raw SQL strings (use SQLAlchemy ORM or parameterized queries)
- No sensitive data logged
- No new endpoints skipping authentication

### Code Quality
- No unused imports or dead code introduced
- Type hints present where helpful
- No obvious performance issues (e.g., N+1 queries, missing filters)

---

## Output format

Respond with:

1. **Summary** — one paragraph describing what changed and the overall quality
2. **Issues** — grouped by file, each issue with:
   - Severity: `critical` / `warning` / `suggestion`
   - File and line reference
   - Clear explanation and recommended fix
3. **Looks good** — briefly mention what was done well

If there are no issues, say so clearly.
