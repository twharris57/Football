# /handoff

Snapshot the current session state so the next agent can resume without re-reading
everything. Run this at the end of any session where the current branch is not complete.

**Skip it** if you're finishing the branch in one session — the PR description and git
log are sufficient history.

## When it's useful

- Multi-session features where position in a sequential build plan matters
- Handing off between users or machines
- Complex branches where the "why we're doing things in this order" context would
  otherwise be lost

## Document Roles

| File | Purpose | What belongs here |
|------|---------|-------------------|
| `HANDOFF.md` | **Session state** — read at the start of the next session | Active branch, recent progress context, ordered next steps |
| Task tracker | **Backlog** — consulted when planning | Task checklists, acceptance criteria, deferred items |
| `CLAUDE.md` | **Conventions** — loaded every conversation | Architecture, coding rules, branch rules, pitfalls |

Do not put history in `HANDOFF.md`. Merge history is in `git log`. PR descriptions are
in GitHub. The handoff doc is a current-state snapshot, not a running log.

## Instructions

### 1. Update the task tracker

Mark tasks completed this session as `[x]`. If a task's scope changed, update its
description in-place. Add anything consciously deferred with a reason.

### 2. Rewrite HANDOFF.md

Keep it short — readable in under two minutes:

```
# [Project] — Handoff

_Last updated: <date>_

---

## Active Branch
Branch name, PR link (if open), one sentence on what it contains.

---

## Recent Progress
Brief bullets on what was completed this session that's relevant context for
what comes next. Focus on decisions made, not a change log. Drop this section
once the work is merged and the context is no longer needed.

---

## Next Steps
Ordered numbered list — concrete, actionable. Each item should point to a
specific task, file, or branch name so the next session can start immediately.
```

**Do not include:**
- Lists of merged PRs or closed branches — use `git log`
- Architecture or convention notes — those belong in `CLAUDE.md`
- Task status checklists — those belong in the task tracker

### 3. Capture new patterns in CLAUDE.md

If the session uncovered a pitfall, a useful pattern, or a constraint every future
session should know — add it to `CLAUDE.md` now. Handoff docs are discarded when
work completes; `CLAUDE.md` is permanent.

### 4. Report to user

State what changed in each file.
