# Confidence Pool Principles

Durable rules for how the confidence-pool app (`confidence_pool/picks_core.py`,
`confidence_pool/store.py`, `confidence_pool/panels/`) derives, ranks, and
persists a week's picks. This file is the *rules to follow* when extending
or changing that logic — see `docs/confidence-pool-web-app.md` for the
current design itself, and `.claude/PROJECT_PLAN_CONFIDENCE_POOL.md` for
what's still open. Mirrors `valuation_principles.md`'s role for the
dynasty subsystem, kept as its own file because the two subsystems share
no code and are tracked separately on purpose (see `CLAUDE.md`'s
"Architecture"). Grew out of the 2026-08-22 confidence-pool review; keep
it updated as the methodology evolves rather than letting it drift into a
historical snapshot.

## A persisted flag must be written for every evaluated candidate, not just the ones that pass

`picks_tab.py`'s "Regenerate picks" and deadline auto-lock (`CP-8`,
2026-08-22 review) both used to call `store.save_week()` with only the
*included* subset of that week's auto-selected games
(`chosen.assign(included=True)`) — an unchecked/excluded game was never
written to `weekly_games` at all, not stored with `included=0`, just
absent from the table. On the next load, `included_map` (rebuilt from
whatever rows actually exist) had no entry for that game, and the lookup
defaulted back to `True` — silently re-including a game the user had
deliberately excluded. The schema already supported the negative case
(`weekly_games.included INTEGER NOT NULL DEFAULT 1`); only the caller
never used it, because filtering to the "passing" subset before the save
call looked like the natural thing to do.

**The rule**: when persisting the result of a filter/checkbox/review step
that a later load needs to reconstruct, save the *full* evaluated set
with an explicit flag per row — never just the subset that passed. A
missing row and an explicitly-excluded row are different facts, and if
only the passing subset is ever written, the two become indistinguishable
on reload, with the default swallowing the negative case. Fixed via
`picks_core.games_with_included_flags()`, called before every
`store.save_week()`, not by post-hoc special-casing the reload path.

## An automated fallback must prefer the last human-reviewed state over recomputing from live inputs

The deadline auto-lock (`CP-9`, 2026-08-22 review) always re-ran
`rank_games()` against whatever odds happened to be live at the moment
the page loaded past the deadline, even when a manually-generated
snapshot (`saved_picks`) already existed from an earlier "Regenerate
picks" click. Moneylines move over the course of a week, so the
locked-in row — the permanent historical record future what-if analysis
and actual-vs-algorithm comparison are meant to build on — could silently
diverge from the picks the user actually reviewed and (in reality)
submitted to the pool earlier. The bug wasn't
in the math; it was in reusing "recompute fresh" as the automated
fallback's default action, when a canonical human-reviewed result was
already sitting there to reuse.

**The rule**: this app's whole purpose is a reliable fallback for when
the user *can't* check in personally (see `docs/confidence-pool-web-app.md`'s
opening motivation) — so any automated action taken in the user's absence
must prefer the last state the user actually reviewed over recomputing
from whatever the outside world looks like right now. Recompute from live
data only when there's genuinely nothing else to fall back on. Fixed via
`picks_core.resolve_week_lock()`, which checks `saved_picks` first.

## A safety-net path that can silently no-op needs a user-visible signal when it does

Same auto-lock block (`CP-10`, 2026-08-22 review): if a selected game's
odds hadn't posted yet at the deadline, the code simply skipped the
`store.save_week(..., lock=True)` call — nothing saved, `locked` stayed
`False`, and the tab fell through to the normal unlocked edit view with
no indication anything was wrong. Most likely on weeks 17-18, where
`configured_deadline` is deliberately set earlier than that week's real
kickoffs, i.e. exactly when Vegas may not have posted every line yet. A
user checking the app after the real deadline had passed would see
nothing to suggest the safety net had failed.

**The rule**: this is the same shape as the dynasty side's
"silent data-degradation must surface as a warning" rule
(`valuation_principles.md`), independently rediscovered here — a
computation that can quietly do nothing instead of its intended action
must say so where the user will see it, not just fail to act. Applies
doubly hard to any code whose entire job is being a safety net for an
unattended moment (a deadline lock, a scheduled auto-save, a background
retry) — that is precisely the moment nobody is present to notice a
silent no-op. Fixed by having `resolve_week_lock()` return an explicit
`warning` string the panel renders via `st.warning()`.

## Moving a hardcoded domain rule into configurable data must preserve its original unconditional default

The Phase 1 schema redesign (`CP-19`/`CP-21`, 2026-08-23) intentionally
moved the weeks-17/18 bylaws exception from a Python constant
(`LATE_SEASON_WEEKS`) into `season_week_rules` data, so a future season
that changes the rule is a Settings-tab edit, not a code change. But the
old code applied the "every game counts, no weekday filter" *selection*
rule unconditionally by week number (`if week in LATE_SEASON_WEEKS`) —
only the *deadline* half of that exception had a graceful "fall back to
earliest kickoff" default when unconfigured. The new design collapsed
both facts into one `season_week_rules` row, written only by
`store.set_late_season_deadline()`, itself called only from a Settings-tab
button click (`CP-24`, 2026-08-23 review). Until a human visits Settings
for that season, `panels/picks_tab.py`'s fallback
(`week_rule["selection_rule"] if week_rule else "standard"`) silently
applies the *wrong* rule for weeks 17-18 — excluding real games the
bylaws say should count and producing a wrong point assignment for real
money, with no warning anywhere (the `st.info` banner about the week's
special rule only renders once the row already exists). This is a
near-certain hit every new season: `current_week()` lands on week 17
automatically as the season progresses, with nothing prompting
configuration first. The bug was invisible to the rewritten test suite
because `TestSelectGames`'s tests all pass `selection_rule` explicitly —
none of them exercise the *caller's* decision of what to pass when no
row exists yet.

**The rule**: when replacing a hardcoded domain constant (a rule that
fires unconditionally for certain inputs) with a database-driven
override, check whether the constant's *original* unconditional behavior
needs to survive as the config table's *seeded default* — not just as
one of several rows a human can optionally create later. If a table
starts empty and a feature's correctness depends on a row existing for a
known case, either seed that row automatically (the same pattern `teams`
already uses via `_seed_default_teams` — `INSERT OR IGNORE`, safe to
reseed on every connect, never clobbers a later edit) or make the reading
code path fail loud/warn when the row is absent for a case the rule is
known to apply to, rather than silently falling through to the *other*
case's default. Losing one axis of an old constant's behavior (here: the
deadline, which already degraded gracefully) while accidentally
introducing a bad default for a *different* axis bundled into the same
row (the selection rule, which never used to depend on configuration at
all) is easy to miss precisely because the config-driven function's own
unit tests still pass.

**Confirmed real, not just theoretical, four days later (2026-08-27):**
the real 2026 Legion Pool bylaws document arrived, and the late-season
exception had grown from weeks 17-18 to weeks 16-18 — exactly the "a
future season narrows/widens this set" risk this rule's own "Static
assumptions" table entry had flagged as *possible*, now observed as
*actual* on only the second season this schema has existed for.
`store.set_late_season_deadline()` had also inherited the old hardcoded
pair as a hard `ValueError` guard (`week not in (17, 18)`), which would
have completely blocked configuring week 16 even by hand — a stricter
failure than CP-24's silent-wrong-default, but still a real gap the
Settings tab had no way around. Fixed by widening the guard to a plain
`1 <= week <= 18` bounds check (any week can be configured; the tuple is
only ever a default) and renaming the hardcoded pair to
`store.KNOWN_LATE_SEASON_WEEKS` specifically so it reads as "the current
best guess, check every season" rather than "the permanent set."
**Extend this rule**: a hardcoded default that's itself a *set of
which cases the exception applies to* (not just the exception's
resolved value) needs the same yearly re-verification as the deadline
value it defaults alongside — don't assume last year's set of exception
cases still holds just because the *mechanism* for handling them is
correct.

## Reusing a prior snapshot to lock a week must also reuse its own timestamps, not the lock moment's

`resolve_week_lock()`'s snapshot-reuse path (`CP-9`) is right that an
already-generated snapshot's *values* (points, predicted winner,
confidence, moneylines) should be locked in verbatim rather than
recomputed against live odds. But `panels/picks_tab.py`'s caller
(`CP-25`, 2026-08-23 review) passes `now` — the moment the
deadline-passed check happened to run — as `save_week()`'s single
`generated_at` argument regardless of whether the snapshot being
persisted was freshly computed or reused from `saved_picks`.
`save_week()` stamps that same value onto both `week_status.generated_at`
and every `'current'`-snapshot `weekly_games.captured_at` row, so the
reused snapshot's real generation/capture time is silently overwritten by
an unrelated lock-evaluation timestamp — corrupting exactly the fact the
`'first'`/`'current'` snapshot split (this same schema redesign) exists
to make queryable ("did odds move between first review and lock").

**The rule**: this is the same shape as this file's earlier "prefer the
last human-reviewed state over recomputing" rule, one field deeper —
reusing a prior snapshot's *content* on lock isn't enough if the
persistence call still takes a fresh timestamp for *when it happened*.
Any save path that can either persist a freshly-computed result or
re-persist an already-persisted one needs to carry the original
timestamp through in the reuse case, not let the caller substitute
`now()` for lack of an alternative in the function's return value. Thread
the reused snapshot's own timestamp through the decision object
(`LockOutcome`, here) rather than leaving the caller to guess which
moment is "correct" to persist — that guess is business logic, and per
this file's own rule below it belongs in the tested library, not the
untested panel that currently makes it.

## Business logic that decides what to persist belongs in the tested library, not the panel

All three bugs above lived entirely in `panels/picks_tab.py`, which has
zero test coverage — `tests/confidence_pool/` covers `picks_core.py` and
`store.py` thoroughly, but nothing exercises the panels, because they're
meant to be thin Streamlit orchestrators (`CLAUDE.md`'s Architecture
section). The auto-lock/inclusion-merge logic was a real exception to
that split: multi-branch decision logic with no Streamlit dependency,
just sitting inline in the panel where it couldn't be unit-tested.

**The rule**: before adding a new `if`/branch to a `panels/` module that
decides *what gets saved* (as opposed to *what gets rendered*), ask
whether it could be written as a plain function taking/returning
dataclasses or DataFrames with no `st.*` calls. If so, put it in
`picks_core.py` (or `store.py` for persistence-shape decisions) and give
it a test — the panel should only call it and render the result. This is
what let `CP-8`-`CP-10` all get fixed with real unit tests
(`games_with_included_flags`, `resolve_week_lock`) instead of relying on
manual QA against a live deadline.

## Code comments cite durable docs, not ephemeral backlog IDs

The Phase 1 schema redesign shipped two docstrings citing `CP-19`/`CP-20`/
`CP-21` as the reason a design choice was made (PR #49 review,
2026-08-24). Both were already dangling the moment they were written —
this plan file's own convention is "remove an item's entry the moment
it's done," and those items were removed in the same branch that added
the citations, in an earlier commit. A reader following the comment's
pointer into `PROJECT_PLAN_CONFIDENCE_POOL.md` would find nothing.

**The rule**: a `CP-<n>`/`RT-<n>`/etc. tag is a coordinates system for
*currently open, in-progress work* — the moment an item resolves, its
entry is deleted (that's the convention, on purpose, so the plan file
doesn't accumulate a permanent history). A code comment is read long
after the PR that added it merges, so citing a tag as the *reason* for a
design choice is citing something guaranteed to eventually 404. Write the
durable explanation directly in the comment (or point at a `docs/*.md`
file, which *is* durable, per `docs/README.md`'s own policy) instead of
outsourcing it to a backlog pointer. A backlog ID belongs in a *commit
message* (permanent, historical) or in the plan file's own attribution
line (`user, PR #46 review, 2026-08-23`) — never as the sole explanation
inside a docstring or inline comment that will outlive the ID it points to.

## "Invalid-looking" input the domain's own rules already resolve should be recorded, not rejected

The first `actual_picks` design (Phase 2, 2026-08-24) required a clean
`1..N` points permutation before saving, blocking the form with an error
otherwise — a reasonable-looking guard, written from general data-hygiene
instinct ("this doesn't look like a valid confidence-pool card") rather
than from the pool's own bylaws. Reading the real 2026 rules document
(2026-08-27) for the late-season deadline question (`CP-1`) surfaced,
unprompted, that the bylaws devote three separate numbered rules to
exactly the states that guard was rejecting: rule 7 (two games sharing a
points value — the lower one counts), rule 15 (a blank points box — that
number's points are lost), rule 16 (an unmarked winner — that game's
points are lost). None of them exclude the card. `actual_picks` exists to
record what was *actually* submitted, mistakes included — a validation
guard modeled on "what a correct card looks like" was silently unable to
represent the exact real-world states the bylaws exist to handle, on the
one table whose entire job is capturing reality rather than a corrected
version of it.

**The rule**: before writing a validation guard that rejects or blocks on
a domain input shaped "wrong" (a duplicate, a gap, a missing value),
check whether the domain's own rules (here, bylaws rule 8 is the actual
invalidation path — illegible cards, forwarded to a committee — and nothing
else is) already define a resolution for that specific shape, rather than
assuming it's an error state to prevent. This is easiest to miss exactly
when the "invalid" shape is also a plausible data-entry *mistake* (a
duplicate points value could be a typo, or could be a real card the user
is faithfully transcribing) — the fix isn't picking one interpretation,
it's not forcing the choice: store what was entered, and surface the
condition as an explicit flag alongside the row you're recording. Watch for
this whenever a table's job is "record what really happened" (as opposed
to "record a value that's always internally consistent") — those tables
should default toward accepting and flagging the domain's own known edge
cases, not rejecting them, since narrowing what's storable to "the app's
idea of a valid state" is itself a source of silent data loss the moment
reality doesn't match that idea.

## A nullable column loaded via pandas silently upgrades its whole column's type, not just the null cells

`_render_actual_picks_form()`'s two paths into `check_actual_picks()`
(`CP-28`, 2026-08-27 review) read the same `actual_picks.points` data but
disagree on type: the per-game widget-default loop casts explicitly
(`int(default_points) if default_points is not None else 0`), while the
reload-time "already recorded" warning passes `row["points"]` straight
through with only an `is-null` check, no cast. `store.load_actual_picks()`
loads `points` via `pd.read_sql_query` — a SQLite `INTEGER` column that
has *any* `NULL` in the result set forces pandas to represent the *entire*
column as `float64`, not just the null cells, since there's no way to
mix a real `NaN` into an `int64` Series. Because a blank points box
(bylaws rule 15) is a normal, expected state this feature exists to
handle, `existing_entries`' otherwise-clean point values silently arrive
as `numpy.float64` (`3.0`) rather than `int` (`3`) the moment any other
game that week is blank — and the uncast path's rule-7 duplicate message
prints "3.0 points" in the exact banner meant to give a clean, citable
bylaws reference for real-money bookkeeping.

**The rule**: a nullable numeric column read through `pd.read_sql_query`
(or any pandas DB loader) is not "float only where the value is missing"
— a single `NULL` anywhere in the *result set* changes the dtype of every
row in that column, including the ones with real values. Before passing
such a column's values into a message, a dict key, or any place its exact
type is user-visible, cast explicitly (`int(x)` after an `isna` check) at
*every* call site that consumes it — not just the one that happened to be
written first. This is the same shape of mistake this file's "displayed
number and filter must round on the same basis" rule already describes
one layer up (two consumers of one value silently disagreeing on
precision), and the same shape `valuation_principles.md` names for the
dynasty subsystem's `NaN`-vs-`None` handling — worth recognizing here too:
watch for it anywhere `weekly_games`/`weekly_picks`/`actual_picks` data
(all of which have genuinely nullable columns by design) gets read back
and formatted in more than one place.
