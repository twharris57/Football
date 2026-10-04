# Git Workflow — Simple Projects

`main` is always stable and gets **no direct commits, ever**. All work happens on a
`feature/<name>` branch and squash-merges via PR.

```
git fetch origin && git checkout main && git pull && git checkout -b feature/<name>
```

Run `git branch` before every commit and push to confirm you're not on `main`.

## Commits

- Commit at stable checkpoints, without being asked — not one lump at session end.
- Keep commit messages short; the PR title/body becomes the permanent squash message.
- Summarize a branch to the user as a whole, not commit by commit.

## Pull requests

Before `gh pr create`, all of these must pass:

1. Build clean (if applicable).
2. Tests pass; tests added/updated for changed behavior.
3. Version/changelog updated (if maintained manually).

```
## Summary
- <what changed and why>

## Key changes
| File | Change |
|------|--------|

## Pre-PR checklist
- [ ] Build/tests pass
- [ ] Versioning updated (if applicable)

## Test plan
- [ ] <scenario to verify manually>

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

Review feedback → new commit, push, and tell the reviewer what changed.

## Merging

- **Never merge without explicit user approval** ("merge it" or equivalent).
- Squash merge, then clean up immediately:
  - `gh pr merge --squash --delete-branch`
  - `git checkout main && git pull && git branch -d feature/<name>` (a warning from
    `-d` after a squash merge is normal).

## Versioning

Each independently deployed app has its own `VERSION` file at its root and its own tag
prefix (`confidence-pool-v1.2.0`, `dynasty-v1.2.0`). Bump only the app that shipped;
tag on `main` after merge.

## Close-out

When a branch is ready, open the PR with `/pr` unprompted, then give one summary and
flag anything that needs the reviewer's attention.
