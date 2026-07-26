# /update-from-agentconfig

Pull upstream changes from AgentConfig into this project's agent configuration,
preserving any project-specific customizations made after the initial `load-repo`.

## Usage

```
/update-from-agentconfig <agentconfig-path>
```

`<agentconfig-path>` is the local path to the AgentConfig repository
(e.g., `../AgentConfig`).

## What This Skill Does

### 1. Verify this project's branch

Check the current branch in this project (`git branch --show-current`).

- If on `main` or another protected branch: stop. Tell the user: "Updates from
  AgentConfig should be applied on a feature branch, not directly on main. Suggested
  action: `git checkout -b feature/sync-agentconfig`. Shall I do that now?"
  Wait for confirmation before creating the branch.
- If already on a feature branch: proceed. If the branch name does not suggest a sync
  (e.g., it's mid-feature work), note it and ask whether to continue on this branch or
  create a dedicated one. Do not block — the user may have a reason.

### 2. Verify paths

Confirm `<agentconfig-path>` exists and contains a `Templates/` subdirectory. Use Bash
to enumerate files — **do not use Glob**, as it does not traverse dotfile directories:

```bash
find "<agentconfig-path>/Templates" -type f -name "*.md"
find "<agentconfig-path>/Templates" -name "settings.json"
```

Stop and report if `Templates/` is absent or empty.

Confirm this project has a `.claude/` directory using the same approach:

```bash
find ".claude" -type f
```

If absent, suggest running `/load-repo` instead — this skill is for updating an existing
installation.

### 3. Verify AgentConfig state

Check the current branch in AgentConfig (`git -C <agentconfig-path> branch --show-current`).

- If **not on `main`**: warn the user: "AgentConfig is currently on branch `<branch>`,
  not `main`. Updates pulled from this state may include unreleased or in-progress work.
  Options: (a) switch AgentConfig to main and pull latest, (b) proceed using the current
  state of AgentConfig. Which do you prefer?"
  - If the user chooses (a): run `git -C <agentconfig-path> checkout main &&
    git -C <agentconfig-path> pull`. Report success or any errors before continuing.
  - If the user chooses (b): proceed, but note in the final report that updates were
    sourced from a non-main branch.
- If **on `main`**: check whether local main is behind remote with
  `git -C <agentconfig-path> fetch && git -C <agentconfig-path> log HEAD..origin/main --oneline`.
  - If behind: tell the user: "AgentConfig's local main is behind origin by N commit(s).
    Shall I pull latest before diffing?" Wait for confirmation before pulling.
  - If up to date: proceed.

### 4. Diff each convention file

For each `.md` file found in `<agentconfig-path>/Templates/.claude/conventions/`:

**New files** (present upstream, absent locally):
- Group by relevance to the project's stack. If multiple new files clearly don't apply
  (e.g., Blazor and C# guidelines for a Java project), list them together under a single
  "not applicable to this stack" heading and ask for one batch confirmation rather than
  asking file-by-file.
- For files that may apply, ask individually.
- Do not copy any file without confirmation.

**Existing files** (present in both):
Diff by reading both files with the Read tool and classifying changes at the section
level — you do not need line-level precision:
- **Additive** — section or rule present upstream but absent locally (safe to accept)
- **Conflicting** — section present in both but content differs (show the upstream
  version and ask)
- **Identical** — no action needed

If Bash is available, `diff <upstream-file> <local-file>` produces clean output that
makes classification straightforward.

### 5. Diff each command file

Repeat the same process for `.md` files in
`<agentconfig-path>/Templates/.claude/commands/`.

If all command files are identical to local versions, report them as a single line:
"Commands: all unchanged." Do not enumerate each file individually.

### 6. Diff settings.json

Compare `<agentconfig-path>/Templates/.claude/settings.json` with this project's
`.claude/settings.json`:

- **New upstream entries** (in AgentConfig but not locally): report as available to add.
- **Project-specific entries** (local but not in AgentConfig's template): treat as
  intentional project additions — preserve them, and list them explicitly in the report
  under "Project-specific settings (not in upstream)" so the user has a clear inventory.
- Do not remove or overwrite project-specific entries under any circumstance.

### 7. Present a review summary

Before making any changes, present a grouped summary:

```
New files — applicable:
  - conventions/docker_guidelines.md  [add? y/n]

New files — not applicable to this stack (batch skip or add):
  - conventions/blazor_guidelines.md
  - conventions/csharp_guidelines.md
  [skip all? y/n]

Additive changes (safe to accept):
  - conventions/code_conventions.md: new "Surgical Changes" section

Conflicting changes (review required):
  - conventions/git_workflow_software.md: upstream changed "Session Close-Out" section
    — your version differs. Show diff? [y/n]

Commands: all unchanged.

Settings.json — new upstream entries:
  - "Bash(cargo *)"  [add? y/n]

Settings.json — project-specific entries (preserved, not in upstream):
  - "Bash(dotnet *)"
  - "Bash(npm run *)"
```

Wait for the user to work through each item. Accept, skip, or show diffs on request.
Do not apply any change until the user confirms it.

### 8. Apply confirmed changes

For each accepted change:
- **New file**: copy it to `.claude/conventions/` (or `commands/`) and add the
  corresponding `@` import to `CLAUDE.md` if it is a convention file.
- **Additive change**: apply only the new section/content, leaving existing content
  untouched.
- **Conflicting change**: apply only if the user explicitly accepted it after reviewing
  the diff. Warn that this overwrites the local version.
- **New settings entry**: append to the `allow` or `deny` array as appropriate.

### 9. Report

List every file changed and what was done. Note any skipped items and why.
Remind the user to review `CLAUDE.md` if new `@` imports were added.
If updates were sourced from a non-main AgentConfig branch, repeat that note here.
