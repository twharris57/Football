# /handoff

Snapshot session state so the next session can resume. Use it only when a branch spans
sessions; a finished branch needs nothing beyond its PR.

## Instructions

1. **Update the project plan.** Remove finished items; adjust changed scope; add
   deferred work with a one-line reason.
2. **Rewrite `HANDOFF.md`** — readable in two minutes, current state only:

   ```
   # <Project> — Handoff
   _Last updated: <date>_

   ## Active branch
   <name>, <PR link>, one sentence on what it contains.

   ## Context
   Decisions from this session that the next steps depend on.

   ## Next steps
   1. <concrete action pointing at a file, task, or branch>
   ```

   No merge history, conventions, or task checklists — those live in git, `CLAUDE.md`,
   and the plan.
3. **Add any lasting pitfall to `CLAUDE.md`** — one short line.
4. **Report** what changed in each file.
