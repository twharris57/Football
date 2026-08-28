# Git Workflow — Simple Projects

Use this workflow for docs, config, tooling, or solo low-complexity projects where a
`develop` integration buffer adds overhead without benefit. For multi-contributor
software projects with CI/CD pipelines, see `git_workflow_software.md`.

## Branch Strategy

| Branch | Purpose | How changes arrive |
|--------|---------|-------------------|
| `main` | Stable at all times | Squash merge from `feature/*` |
| `feature/<name>` | All active development | PRs → `main` |

- `main` receives **no direct commits** — not even small fixes or doc updates.
- All work goes through a `feature/*` branch and PR. No exceptions.

**Before starting any work:**
```
git fetch origin
git checkout main && git pull
git checkout -b feature/<name>
```

**Before any commit, run `git branch`** and confirm you are not on `main`.

## Commit Discipline

**Commit at stable checkpoints, not at session end.**

Each commit should represent a coherent unit of work. Individual commits on the feature
branch are transient — the squash commit message (PR title and body) becomes the
permanent record in `main`. Invest in writing a clear PR description; keep individual
commit messages short and descriptive.

Do not batch all work into one commit at session end. Do not wait to be asked to commit.

**When summarizing branch changes to the user:** describe what changed as a whole — what
the user can now do, how the system behaves, any non-obvious design decisions. Do not
break it down commit by commit.

## Pull Requests

The PR represents the **final state** of the work. All pre-PR gate items must be
satisfied before opening — not addressed in follow-up commits after the reviewer has
seen the branch. If review conversation surfaces a needed change, make the commit,
push it, and explicitly tell the reviewer what changed and why.

### Pre-PR gate

Run these in order before calling `gh pr create`. Do not open the PR if any step fails.

1. Build — 0 errors, 0 warnings (if applicable)
2. Tests — all pass; update or add tests for any behavior this branch changes (if applicable)
3. Versioning and changelog — if the project maintains these manually, update them now.
   Skip if managed by pipeline or not used.

### PR description template

```
## Summary
- <what changed and why>

## Key changes
| File | Change |
|------|--------|
| `path/to/File` | One-line description |

## Pre-PR checklist
- [ ] Build/tests pass (if applicable)
- [ ] Versioning/changelog updated (if applicable)

## Test plan
- [ ] <specific scenario to verify manually>

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

Checklist items must be confirmed true at the time `gh pr create` runs. Test plan items
use `- [ ]` checkboxes, not plain bullets.

### Merge rules

- **Never merge a PR without explicit user approval.** Opening and updating a PR is fine.
  Calling `gh pr merge` requires the user to say "merge it", "go ahead and merge", or an
  equivalent direct instruction. `gh pr merge` is intentionally excluded from
  pre-approved permissions — merging is irreversible and must always be user-confirmed.
- Squash merge `feature/*` → `main`.
- **Before any `git push`**, confirm you are not on `main`. Claude Code does not
  currently support branch-scoped push restrictions in `settings.json`, so this is a
  manual discipline check — run `git branch` before pushing.

## Versioning

If the project uses version numbers, tag each release on `main` as `v{version}`
(e.g., `v1.0.0`). Bump only when something ships — don't increment mid-branch.

**Multi-app repos**: if a repo holds more than one independently-deployed app (as
this one does — see `CLAUDE.md`'s "Architecture"), each app keeps its own version,
bumped only when *that* app ships something — one app's release doesn't bump the
other's number. Concretely:
- Each app's current version lives in a `VERSION` file at that app's own root
  (e.g. `confidence_pool/VERSION`, `dynasty/VERSION`), read at runtime so the UI
  can display it (see each app's `streamlit_app.py` footer).
- Tag releases with a per-app prefix so tags from different apps never collide:
  `confidence-pool-v{version}`, `dynasty-v{version}`.
- Bumping an app's version is: edit its `VERSION` file, commit, and (once merged
  to `main`) tag that commit `«app»-v{version}`.

## Session Close-Out

When a branch is complete and ready for review, open a PR without waiting to be asked —
run `/pr` to create it. Then:
- Give one summary of what the branch changes as a whole.
- Note anything specific worth the reviewer's attention (edge cases, tradeoffs made).
