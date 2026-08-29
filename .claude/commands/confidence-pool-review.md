# /confidence-pool-review

Deep sports-betting/reliability-methodology review of this project's confidence-pool
picking logic (`confidence_pool/picks_core.py`, `confidence_pool/store.py`,
`confidence_pool/panels/`, and anything that consumes their output) — plus the docs and
conventions that describe it.
Written so the review always ends in the same durable artifacts, not just a chat
message: fix-before-merge items in `.claude/PROJECT_PLAN_CONFIDENCE_POOL.md`, deferred
items filed in that same plan's Backlog, and any newly-discovered failure mode captured
as a rule in `.claude/conventions/confidence_pool_principles.md` so it can't quietly
resurface later. This is the confidence-pool subsystem's counterpart to
`/valuation-review` — same process, different domain and different target files, since
the two subsystems share no code (see `CLAUDE.md`'s "Architecture") and are tracked
separately on purpose.

## Usage

```
/confidence-pool-review              Review the open PR for the current branch
/confidence-pool-review <branch>     Review a specific branch/PR
/confidence-pool-review full         Full-pipeline review: no specific branch — the
                                      whole confidence-pool app, as it currently stands
```

## Persona

Review with two lenses at once, both genuinely load-bearing for this app:

1. **A sports-betting analyst with a real probability background** — fluent in American-odds
   conversion, vig/overround removal (multiplicative de-vig vs. Shin's model and their
   different behavior at extreme favorites), why confidence-pool point assignment is a
   ranking problem over |edge|, not a pure win-probability problem, and small-sample
   pitfalls (a single season/week treated as a stable signal, an exact-tie edge case).
2. **A reliability engineer for an unattended system.** This app's entire reason to exist
   is being trustworthy when the user *can't* check in personally (see
   `docs/confidence-pool-web-app.md`'s opening motivation) — its deadline auto-lock is a
   safety net that runs with nobody watching. Review every code path that can fire
   without a human present (the auto-lock, any future scheduled action) with the same
   scrutiny a production on-call engineer would give an unattended cron job: what does it
   do when its assumptions don't hold, and does a failure announce itself or just go
   quiet? The three bugs found in the 2026-08-22 review (`CP-8`-`CP-10`, now documented
   in `confidence_pool_principles.md`) were all reliability failures, not math errors —
   don't let the betting-math lens crowd this one out.

## Instructions

### 1. Scope the review

- **PR/branch mode** (default): `gh pr list --state open` to find the target (or use the
  branch/PR the user named). Get the full diff against its base branch —
  `git diff <base>...<branch>` — plus `git log <base>..<branch>` for commit messages.
  Commit messages here often include the author's own "verified against live data"
  claims (e.g. real 2025/2026 schedule checks for `select_games`'s weekday rules) — check
  whether a finding you're about to raise was actually exercised by that verification or
  would have slipped past it.
- **Full-pipeline mode** (`full`, or no PR/branch exists yet): review the current state
  of `confidence_pool/picks_core.py`, `confidence_pool/store.py`,
  `confidence_pool/panels/`, and `docs/confidence-pool-web-app.md` end to end, same depth
  as a PR review, with no diff to anchor against.
- Read enough surrounding context to reason about each function, not just the patch — an
  isolated diff hunk hides whether a helper is reused elsewhere (e.g. whether a new save
  path reuses `resolve_week_lock`/`games_with_included_flags` or reinvents the decision),
  or whether a simplification is already documented as deliberate (`docs/confidence-pool-web-app.md`'s
  "Known gaps"/"Static assumptions" tables).

### 2. Look for domain-specific issues, not just code-review issues

For each changed/reviewed function, check:

- **Odds/probability correctness** — is `compute_probability` + the vig-removal
  normalization applied correctly, and does anything new introduce a second way to turn
  odds into a ranking rather than reusing `rank_games`? (`confidence_pool_principles.md`'s
  "business logic belongs in the tested library" rule applies here too — a second scoring
  path in a panel is the same shape of mistake as a second decision path.)
- **Game-selection rule fidelity** — any change to `select_games`'s weekday/gametime/week
  logic needs to be checked against what the bylaws actually say (`docs/confidence-pool-web-app.md`'s
  "Game-selection rules" section) and, ideally, real schedule data for a season where the
  edge case in question actually occurred — not just a synthetic fixture that happens to
  agree with the new code.
- **Deadline/lock integrity** — does every path that can write to `weekly_games`/
  `weekly_picks` around a deadline preserve "what was actually reviewed/submitted" as the
  authoritative record, per `confidence_pool_principles.md`'s auto-lock rules? A new save
  path that duplicates `resolve_week_lock`'s decision instead of calling it is a regression
  risk even if today's version happens to get the logic right.
- **Persistence completeness** — does every field the UI reads back on a later load get
  written for *all* the rows that need to disambiguate a choice, not just a filtered
  "passing" subset? (The `CP-8` shape: a missing row and an explicitly-negative row must
  stay distinguishable.)
- **Silent degradation / safety-net visibility** — can any automated or fallback code path
  (the auto-lock, or anything added that runs without direct user action) end up doing
  nothing with no user-facing signal? A comment noting the risk is not a fix — check
  whether a `st.warning`/equivalent is actually wired in for the failure case.
- **Panel vs. library placement** — is new decision logic (anything more than "call a
  `picks_core`/`store` function and render its result") landing in `panels/`, where it has
  no test coverage, instead of `picks_core.py`/`store.py`, where it would?
- **Season/week edge cases** — weeks 17-18's special-casing, `default_season_year`'s
  March year-boundary cutoff, timezone handling (every deadline/kickoff comparison should
  stay ET-aware, never a naive datetime slipping in).
- **Test coverage** — do the new/changed tests exercise the actual failure mode a finding
  would predict (a game excluded then reloaded, a lock attempted with pending odds, a
  lock attempted with an existing snapshot to reuse), or only the path the author already
  had in mind?
- **Dangling backlog-ID citations** — does any new or touched doc (`docs/*.md`) or code
  comment/docstring cite a `CP-<n>` tag as the reason for a design choice? Check whether
  that tag's entry still exists in `PROJECT_PLAN_CONFIDENCE_POOL.md` — if not (or if the
  same PR is the one deleting it), the citation is dangling from the moment it's written.
  This keeps recurring (see `confidence_pool_principles.md`'s "Code comments cite durable
  docs, not ephemeral backlog IDs" rule, and its dynasty-side counterpart in
  `valuation_principles.md`) — flag every instance found, not just ones in the diff under
  review, since a doc file touched for one reason often carries older dangling citations
  nobody has re-read since.

### 3. Rank findings by real-world consequence, not theoretical purity

Sort findings into three tiers before writing anything down:

1. Could cause a **concrete bad outcome** if it reached a real week's picks — wrong
   points assigned, a silently corrupted or lost historical record, a safety net that
   fails exactly when it's needed and gives no sign of it.
2. A real but **bounded imprecision** — an odds-methodology choice that's a reasonable
   approximation but not the most rigorous option, with the raw inputs still visible/
   recoverable; nothing acts on the imprecision blindly.
3. A **minor/edge case** — an extremely unlikely input (an exact-tie moneyline), a
   trivial inefficiency.

This tier determines where each finding goes in step 4.

### 4. Write findings to `.claude/PROJECT_PLAN_CONFIDENCE_POOL.md` in the right place

- **Tier 1 findings** go in the **"Current branch — fix before merge"** section at the
  top of the file (create it if absent, matching its existing header style: branch/PR
  name, one-line scope, "Cleared out when the branch merges"). This section is ephemeral
  — clear it out (don't archive it) once the branch merges; the merged PR's description
  is the historical record, not this file.
- **Tier 2/3 findings** go into the **Backlog** section. Attribute them
  `(assistant confidence-pool review, <date>)`, matching the file's existing citation
  style (see the dynasty plan's `(assistant valuation review, <date>)` convention, which
  this mirrors).
- Give every new item the next unused `CP-<n>` tag per the file's own "ID tracker" line —
  this plan uses one flat `CP-` prefix for every item regardless of theme, unlike the
  dynasty plan's per-theme prefixes (`RT-`/`VA-`/`CQ-`/`DL-`). Cross-reference other items
  by tag (`see CP-9`), never by list position.

### 5. Distill durable rules into `.claude/conventions/confidence_pool_principles.md`

For any finding that reflects a *pattern* worth avoiding in future work (not a one-off
typo) — add or extend a principle there: name the rule, the concrete case that motivated
it, and how to recognize the same shape of mistake next time. Prefer extending an
existing section if the finding is a specific instance of an already-stated rule; add a
new section only for a genuinely new failure mode. Do not add rules to the dynasty
subsystem's `valuation_principles.md` — the two files are kept separate on purpose, even
when a rule happens to rhyme with one already stated there (name the parallel in prose
instead, as the existing rules already do). This file is what makes the review compound
— success looks like the *next* review finding fewer of the same class of issue, not this
file growing without bound.

### 6. Update `docs/confidence-pool-web-app.md` only if the finding changes documented behavior or known limitations

If a finding reveals a real gap in its "Known gaps" or "Static assumptions" sections, add
it there too — but don't duplicate the same content across all three files.
`PROJECT_PLAN_CONFIDENCE_POOL.md` is the action item; `confidence_pool_principles.md` is
the durable rule; `docs/confidence-pool-web-app.md` is the current-state description.
Most findings only need one or two of the three, not all three by default. If a fix
changes what a doc section describes (e.g. the "Lock-in" section's description of what
gets locked), update that section directly rather than appending a "known gap" bullet
that contradicts it — the doc should always describe present behavior, per
`docs/README.md`'s own stated policy.

### 7. Commit and push to the branch under review — never to `main`

Confirm the current branch with `git branch --show-current` before touching git (per
`.claude/conventions/git_workflow_simple.md`) — checkout the branch under review if not
already on it. Commit the plan/convention/doc updates directly to that branch (this *is*
PR feedback, applied as a commit, not a separate deliverable). Stage only the files this
review touched — if the working tree has other unrelated in-flight changes you didn't
review, leave them uncommitted and tell the user. Push. Do not merge, and do not
implement the code fixes themselves unless the user separately asks for that.

### 8. Report to the user

Summarize findings in severity order (most severe first). State plainly which are
blocking vs. deferred, and confirm what was committed/pushed and where. Offer — don't
assume — whether to implement the fix-before-merge items now.
