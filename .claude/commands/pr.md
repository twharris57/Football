# /pr

Create or update a pull request for the current branch, following the project's PR
conventions.

## Usage

```
/pr          Create a new PR for the current branch
/pr update   Update the description of the existing open PR for the current branch
```

## Instructions

### 1. Verify branch state

- Confirm you are not on `main`, `develop`, or the project's equivalent protected
  branches (check the active git workflow convention). Stop and warn the user if you are.
- Run `git status` — the working tree must be clean. If there are uncommitted changes,
  stop and ask the user whether to commit them first.
- Run `git log <base-branch>..HEAD` (check the active git workflow convention for the base branch) to see what this PR contains.

### 2. Run the pre-PR gate

Run the checks documented in the "Development Commands" section of `CLAUDE.md` in order:

1. **Build** — must complete with 0 errors and 0 warnings
2. **Tests** — all must pass; any behavior changed by this branch must have updated or
   new test coverage
3. **Version and changelog** — if the project maintains these manually, bump and update
   now (see the project's active git workflow convention for when this applies)
4. **Task tracker** — mark completed work, update current status

If any gate item fails, stop and report the failure. Do not open the PR.

### 3. Build the PR description

Using `git log` and the diff, construct a description that follows the project's PR
template in the project's active git workflow convention file. If no template is defined there, use:

```
## Summary
- <what changed and why — one bullet per logical area>

## Key changes
| File | Change |
|------|--------|
| `path/to/File` | One-line description |

## Pre-PR checklist
- [ ] Build — 0 errors, 0 warnings
- [ ] Tests — all pass; new/changed behavior covered
- [ ] Version bump + changelog entry (if applicable)
- [ ] Task tracker updated

## Test plan
- [ ] <specific scenario to verify manually>
- [ ] <regression: existing feature still works>

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

Checklist items must reflect what was actually verified — they are a record, not a to-do.

### 4. Create or update the PR

**New PR:** `gh pr create --base <base-branch> --title "<title>" --body "<description>"`

**Update existing PR:** `gh pr edit --body "<updated-description>"`
When updating, add a brief note at the top of the description explaining what changed
since the PR was opened, so the reviewer knows what to re-examine.

**Note:** `gh pr merge` is intentionally excluded from the project's pre-approved
permissions. Merging is irreversible and must always be explicitly confirmed by the user —
it will prompt for approval every time, by design. Do not attempt to bypass this.

### 5. Report to user

Return the PR URL. Summarize: what the branch changes as a whole, and anything specific
worth the reviewer's attention (edge cases, tradeoffs, assumptions made).

The PR now represents the final state of the work. Any further commits require explicitly
informing the reviewer of what changed and why.
