---
name: release
description: Cut a backend release - bump VERSION in config.py on develop, push it and open the develop → master PR listing what ships. Use when asked to release, bump the version, or open the release PR to master. Optional argument - the version to use (e.g. v6.80-beta or v7.0); without it, the minor number goes up by one.
allowed-tools: Bash(git *), Bash(gh *), Bash(grep *), Read, Edit
---

# NoHarm Backend - Release

A release is one commit on `develop` that bumps `Config.VERSION` in `config.py`, and a PR from `develop` into `master` titled with the new version.

## Context

- **Current branch:** !`git rev-parse --abbrev-ref HEAD`
- **Working tree:** !`git status --short`
- **Current version:** !`grep -n 'VERSION = ' config.py`
- **Open PRs to master:** !`gh pr list --base master --state open`

## Steps

1. **Check before touching anything.** Stop and tell the user if:
   - the current branch is not `develop`;
   - the working tree has changes (the release commit carries only the version);
   - a PR from `develop` into `master` is already open (link it instead of opening another).

2. **Sync.** `git fetch origin` and `git pull --ff-only origin develop`. If it doesn't fast-forward, stop and tell the user.

3. **See what ships.** `git log --oneline origin/master..origin/develop`. If there is nothing besides merges, tell the user there is nothing to release and stop.

4. **Bump the version.** Edit `VERSION` in `config.py` only (not `FRONTEND_VERSION`):
   - with an argument, use it as given (add the leading `v` if missing);
   - otherwise bump the minor number and keep the suffix: `v6.78-beta` → `v6.79-beta`.

5. **Commit and push.** The commit message is the version alone, followed by the attribution line from the system reminder, if one is present:
   ```bash
   git commit -am "v6.79-beta"
   git push origin develop
   ```
   GitHub reports "Bypassed rule violations" for `develop` - expected for maintainers, the push still goes through. If the push is rejected, stop and report; don't force push.

6. **Open the PR** from `develop` into `master`, titled with the version. The body lists what ships, one line per change, newest first:
   - a merged PR as `- #<number> <title>` (the number is in the merge commit, `Merge pull request #NNN from ...`; the title is the PR title, `gh pr view NNN --json title`);
   - a commit pushed straight to `develop` as `- <commit subject>`;
   - skip merge commits like `Merge branch 'develop' of ...` and commits already covered by a listed PR;
   - last line: `- chore: bump version to <version>`.

   ```bash
   gh pr create --base master --head develop --title "v6.79-beta" --body "## Summary
   - #791 feat: prescalc automatic check for diet only and white list prescriptions
   - fix: custom report process interval
   - chore: bump version to v6.79-beta

   <PR attribution line from the system reminder, if present>"
   ```

7. **Report** the old and new version, the PR link and the list of what ships. Don't merge the PR.
