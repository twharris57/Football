# /valuation-review

Deep fantasy-football/stats-methodology review of this project's dynasty valuation and
roster-analysis logic (`dynasty/dynasty_core/`, `dynasty/player_scoring.py`,
`dynasty/fantasycalc_api.py`, and anything that consumes their output) — plus the docs
and conventions that describe it.
Written so the review always ends in the same durable artifacts, not just a chat
message: fix-before-merge items in `.claude/PROJECT_PLAN_DYNASTY.md`, deferred items filed in
the right thematic section, and any newly-discovered failure mode captured as a rule in
`.claude/conventions/valuation_principles.md` so it can't quietly resurface later.

## Usage

```
/valuation-review              Review the open PR for the current branch
/valuation-review <branch>     Review a specific branch/PR
/valuation-review full         Full-pipeline review: no specific branch — the whole
                                valuation methodology, as it currently stands
```

## Persona

Review as a fantasy football analyst with a real stats background — someone fluent in
value-based drafting, replacement-level theory, dynasty-market conventions
(FantasyCalc/KTC-style crowd valuation vs. projection-based models), superflex/TE-premium
format effects, and small-sample statistical pitfalls (shrinkage, discontinuous cutoffs,
survivorship bias). Bring that lens to every review — the goal is catching *domain*
mistakes (a wrong replacement-level baseline, a format assumption that silently reverts
to standard-league math, an unshrunk small-sample signal), not just a generic style pass.

## Instructions

### 1. Scope the review

- **PR/branch mode** (default): `gh pr list --state open` to find the target (or use the
  branch/PR the user named). Get the full diff against its base branch —
  `git diff <base>...<branch>` — plus `git log <base>..<branch>` for commit messages.
  Commit messages here often include the author's own "verified against live data"
  claims; check whether a finding you're about to raise was actually exercised by that
  verification or would have slipped past it.
- **Full-pipeline mode** (`full`, or no PR/branch exists yet): review the current state
  of `dynasty/dynasty_core/`, `dynasty/player_scoring.py`, `dynasty/fantasycalc_api.py`,
  and their docs (`docs/rookie-draft-big-board.md`, `docs/dynasty-draft-web-app.md`) end
  to end, same depth as a PR review, with no diff to anchor against.
- Read enough surrounding context to reason about each function, not just the patch — an
  isolated diff hunk hides whether a helper is reused elsewhere, or whether a
  simplification is already documented as deliberate.

### 2. Look for domain-specific issues, not just code-review issues

For each changed/reviewed function, check:

- **Format assumptions** — does this league's real settings (superflex, PPR, TE
  premium, scoring quirks) get modeled correctly, or does a shortcut silently revert to
  standard-league math? (`valuation_principles.md`'s superflex rule exists because of
  exactly this failure mode once, in `position_replacement_levels()`.)
- **Signal vs. action** — is an already-accepted simplification (a dedicated-slot count,
  a flat cutoff, an approximation) now backing something that recommends an action
  (sell, drop, add) rather than just an informational number a human reads and
  interprets themselves? The acceptable-error bar is different for the two. (Same file,
  the `sellable_players()` FLEX case.)
- **Small-sample statistics** — hard cutoffs with no shrinkage, ratios computed from
  thin samples, noise treated as signal (a week-1 win/loss record, a single season of
  stats driving a permanent multiplier).
- **Linearity/scaling assumptions** — is a correction applied multiplicatively/
  additively in a way that assumes a relationship (value ∝ points, etc.) that's a
  reasonable first-order approximation but never actually verified?
- **External IDs and joins** — is an ID (`roster_id`, `player_id`, a name-string match
  like FantasyCalc's pick names) treated as an opaque key looked up against real data,
  or does something assume a range/order/format that was never verified?
- **Silent degradation** — can a join, name-match, or external-format mismatch produce
  an empty/degraded result with no exception and no `data_warnings` entry? A comment
  acknowledging the risk is not a fix — check whether it's actually wired in.
- **Consistency** — does this feature reuse the project's existing ranking/valuation
  primitives (`rank_by_marginal_value`, `vor`, `gap_delta`, `adj_value`), or does it
  quietly introduce a second way to answer the same question? This project has hit that
  failure mode twice already (see `valuation_principles.md`'s "one valuation strategy"
  rule).
- **Test coverage** — do the new/changed tests actually exercise the failure mode a
  finding would predict, or only the direction the author already expected? (A common
  gap: a "known-good vs. known-bad" sanity check that can't surface a conflation between
  two independent signals moving in different directions.)
- **Dangling backlog-ID citations** — does any new or touched doc (`docs/*.md`) or code
  comment/docstring cite a `RT-<n>`/`VA-<n>`/`CQ-<n>`/`DL-<n>`/`NB-<n>` tag as the reason
  for a design choice? Check whether that tag's entry still exists in
  `PROJECT_PLAN_DYNASTY.md` — if not (or if the same PR is the one deleting it), the
  citation is dangling from the moment it's written. This keeps recurring (see
  `valuation_principles.md`'s "docs and comments cite durable explanations, not
  ephemeral backlog IDs" rule) — flag every instance found, not just ones in the diff
  under review, since a doc file touched for one reason often carries older dangling
  citations nobody has re-read since.

### 3. Rank findings by real-world consequence, not theoretical purity

Sort findings into three tiers before writing anything down:

1. Could cause a **concrete bad outcome** if acted on — a wrong trade recommendation, a
   wrong drop suggestion, a silently corrupted value feeding a real decision.
2. A real but **bounded calibration imprecision** — a signal is somewhat off, but
   nothing acts on it directly, or the raw components are already shown alongside the
   derived one.
3. A **minor/edge case** — an extremely unlikely input, a trivial inefficiency.

This tier determines where each finding goes in step 4.

### 4. Write findings to `.claude/PROJECT_PLAN_DYNASTY.md` in the right place

- **Tier 1 findings** go in a **"Current branch — fix before merge"** section at the
  very top of the file, right after the intro paragraph and before "Now — blocking"
  (create it if absent). Header it with the branch/PR name and review date. This section
  is ephemeral: clear it out (don't archive it) once the branch merges — the merged PR's
  description is the historical record, not this file.
- **Tier 2/3 findings** go into the relevant thematic section further down (Roster &
  trade tooling `RT`, Valuation & data accuracy `VA`, Code quality `CQ`, or Deferred /
  low priority `DL`). Attribute them `(assistant valuation review, <date>)`, matching
  the file's existing citation style.
- Give every new item a permanent `<SECTION>-<n>` ID in its own heading (see the file's
  own intro for the convention) — the next unused number for that section's prefix,
  regardless of where in the list priority order places it. Cross-reference other items
  by this ID (`see RT-3`), never by list position — positional references break the
  moment anything above them is inserted, reordered, or removed, which is exactly why
  this convention replaced that approach.

### 5. Distill durable rules into `.claude/conventions/valuation_principles.md`

For any finding that reflects a *pattern* worth avoiding in future work (not a one-off
typo) — add or extend a principle there: name the rule, the concrete case that motivated
it, and how to recognize the same shape of mistake next time. Prefer extending an
existing section if the finding is a specific instance of an already-stated rule; add a
new section only for a genuinely new failure mode. This file is what makes the review
compound — success looks like the *next* review finding fewer of the same class of
issue, not this file growing without bound.

### 6. Update `docs/` only if the finding changes documented behavior or known limitations

If a finding reveals a real gap in `docs/rookie-draft-big-board.md`'s "Known gaps" or
"Static assumptions" sections, add it there too — but don't duplicate the same content
across all three files. `PROJECT_PLAN_DYNASTY.md` is the action item; `valuation_principles.md`
is the durable rule; `docs/` is the current-state description. Most findings only need
one or two of the three, not all three by default.

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
