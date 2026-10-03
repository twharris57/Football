# /update-from-agentconfig

Pull upstream AgentConfig changes into this project, keeping local customizations.

```
/update-from-agentconfig <agentconfig-path>   # e.g. ../AgentConfig
```

## Instructions

1. **Branch.** If on `main`, stop and offer `git checkout -b feature/sync-agentconfig`.
   If on an unrelated feature branch, ask whether to continue there.
2. **Paths.** Confirm `<path>/Templates/` and local `.claude/` exist. Enumerate with
   `find` (Glob skips dot-directories).
3. **Upstream state.** If AgentConfig isn't on `main`, ask whether to switch and pull or
   use it as-is (and say so in the final report). If `main` is behind origin, offer to pull.
4. **Diff conventions, commands, and `settings.json`** (`diff` works). Classify each:
   - **New file** — ask; batch the ones clearly irrelevant to this stack.
   - **Additive** — upstream section missing locally; safe.
   - **Conflicting** — both differ; show the upstream version and ask.
   - **Identical** — say "all unchanged" in one line.
   - Local-only `settings.json` entries are intentional; list and keep them.
5. **Summarize, then wait.** Present a grouped list (new / additive / conflicting /
   settings) and apply nothing until the user confirms each item.
6. **Apply** confirmed items only. New conventions also need an `@` import in `CLAUDE.md`.
   Warn before overwriting a conflicting local version.
7. **Report** each file changed and anything skipped.
