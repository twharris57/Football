# Confidence Pool Web App — Streamlit + Docker

A small web frontend for the Legion pool's weekly confidence picks, built
so generating a week's picks doesn't depend on having a dev machine handy
(the original motivation: a week was missed while traveling, falling back
to public consensus odds instead of the tool's own ranking — still 7th of
100+ for the season, but the whole point of this app is that it shouldn't
have to happen again). Deployable to the user's Synology NAS alongside the
dynasty app, in its own container — the two subsystems share no code (see
`CLAUDE.md`'s "Architecture").

`confidence_pool/football.py` and `football_enhanced.py` (the original CLI
scripts) are kept as untouched, standalone legacy/reference
implementations. This app is a fresh library (`picks_core.py`) that reuses
`football_enhanced.py`'s proven Vegas-odds math and ranking as its
reference design, not a refactor of it.

## Game-selection rules (Legion pool bylaws, rule 14)

The pool's own sheet doesn't include every game in a week — only Sunday-
afternoon and Monday-night games "almost always" go on the sheet, for
most of the season. `picks_core.select_games()` encodes this as:

- `game_type == 'REG'` (excludes preseason and any playoff rows this pool
  never uses).
- `'standard'` rule (the default): a game is selected if its kickoff falls
  in the window from that week's Sunday at the configured
  `sunday_afternoon_cutoff` (13:00 ET by default) through the following
  Tuesday end-of-day (**changed 2026-08-29**: previously a
  `weekday in ('Sunday', 'Monday')` enumeration with a `gametime >= '13:00'`
  check for Sunday specifically). In practice this is still
  Sunday-afternoon and Monday-night games, but as a real datetime
  comparison it also picks up a rare Tuesday makeup game (a weather
  postponement has happened at least once in NFL history) that the old
  weekday enumeration would have silently excluded. The reason this
  window exists at all: the deadline (below) is "before kickoff" of the
  *earliest selected* game, so an excluded early game's result can't leak
  information before picks are due. A game whose kickoff time nfl_data_py
  hasn't finalized yet (most likely a late-season, flex-scheduling-eligible
  game) is excluded from this window rather than crashing the rest of the
  week's selection over it.
- **`'all_games'` rule: every game that week, once no deadline is
  configured yet** — applies to the season's final few weeks —
  `store.KNOWN_LATE_SEASON_WEEKS`, 16-18 as of the 2026 rules (see below).
  Once that week's deadline *is* configured (Settings tab), selection
  switches to the same kind of real check as `'standard'`'s window: only
  games kicking off at or after it. Their deadline is a single early
  cutoff *before all* of that week's kickoffs (see "Pick-submission
  deadline" below), so in practice this ends up including every game
  anyway — but it's now an actual comparison against the configured
  deadline rather than an assumption that the deadline always predates
  every kickoff that week. A game whose kickoff time isn't finalized yet
  is *included* rather than excluded here — the opposite default from
  `'standard'`'s window — since this rule's own deadline is already
  documented to predate every real kickoff that week regardless, so an
  unknown time is never evidence the game should come off the sheet.

**Which weeks get the `'all_games'` rule changes year to year — confirmed
against real bylaws documents twice, not assumed to carry forward.** An
earlier version of this doc, and `picks_core.select_games()` itself,
restricted weeks 17-18 to `weekday == 'Saturday'` only, reading the
bylaws' "Weeks 17 & 18 will all feature Saturday games" as a
game-selection filter (**corrected 2026-08-24**): real 2025-season
results (a full-season scoring sheet the user provided) proved that
wrong directly — week 18 scores as high as 114 are only mathematically
possible with roughly 15 games on the sheet that week (points are `1..N`
for `N` games, so max score is `N(N+1)/2`), nowhere close to what a
1-3-game Saturday-only slate would produce. The actual 2025 week-18
sheet listed games on both Jan 3 (Saturday) and Jan 4 (Sunday),
confirming the bylaws sentence was describing *when the deadline falls*,
not which games are eligible. Then, reading the **real 2026 rules
document** (**2026-08-27**) revealed the exception itself had grown: rule
14 there reads "Weeks 16, 17 & 18 will all feature Saturday games" and
rule 2 explicitly lists week 16 alongside 17-18 as deadline exceptions —
up from just 17-18 the year before. `store.KNOWN_LATE_SEASON_WEEKS` is
the one place this needs checking against each season's actual bylaws;
`set_late_season_deadline()` itself accepts any week 1-18, so a wrong
assumption there is a Settings-tab fix, not a code change.

Because the bylaws themselves say "almost always" (commissioner discretion,
exceptions happen), the Picks tab shows the auto-selected list with a
per-game include/exclude checkbox before ranking runs — not just an
escape-hatch override for a wrong guess, a normal part of reviewing each
week.

### Pick-submission deadline

`picks_core.week_deadline()`: a `'standard'`-rule week uses the earliest
kickoff among that week's selected games (rule 2: "before kick-off"). An
`'all_games'`-rule week uses an explicit early cutoff from
`season_week_rules` instead — the 2026 bylaws' own example (Sat Dec 26
before 1:00pm ET for week 16; Sat Jan 2 and Sat Jan 9 before 4:30pm ET for
weeks 17-18) is *earlier* than any of those weeks' actual kickoffs, so
it's commissioner-announced each year, not computable from the schedule.
Falls back to the earliest kickoff among that week's selected games if
the season's cutoff hasn't been configured yet (Settings tab).
`week_deadline()` itself just trusts whichever `configured_deadline` the
caller passes -- it doesn't know which weeks are special;
`panels/picks_tab.py` decides that by looking up `store.get_week_rule()`.

## Persistence (`store.py`)

SQLite, normalized around stable reference data (`seasons`, `teams`,
`games`) versus per-generation event data (`weekly_games`/`weekly_picks`,
split into `'current'`/`'first'` snapshots) — see
`docs/confidence-pool-data-model.md` for the full table-by-table schema and
design rationale. Every week's evaluated games and generated picks get
saved as part of the normal flow (not just on request) so future analysis —
what-if scoring against real outcomes, an eventual small analytics API —
has real historical input instead of needing to reconstruct it later (see
`.claude/PROJECT_PLAN_CONFIDENCE_POOL.md`'s `CP-3`/`CP-5`).

### Lock-in

A week can be regenerated freely before its deadline (`Picks` tab's
"Regenerate picks" button overwrites the saved snapshot). Once
`is_locked(now, deadline)` is true, `picks_core.resolve_week_lock()`
decides what to lock: the last manually-generated snapshot if one exists
(reused as-is, not recomputed against whatever odds happen to be live at
that moment — moneylines move over a week, and the locked row is the
permanent historical record `CP-3` depends on), or one final
computed snapshot if nothing was ever generated. If odds are still
pending for a selected game and there's no prior snapshot to fall back
on, the week is left unlocked with an explicit warning rather than
silently not locking. If that last-resort computed snapshot is generated
after kickoff for one of that week's included games — the app was never
opened for the week until well after its deadline — it still locks (no
better data to fall back to) but carries an explanatory warning
(`week_status.lock_warning`) naming which games, since their moneylines
may no longer reflect the original pregame line; the warning is persisted
so it stays visible on every later view of the locked week, not just the
page load when the lock happened. The picks tab then switches to a
read-only view — `store.save_week()` refuses to overwrite an
already-locked week's row. There's no background scheduler: "locked" is
computed from `now` vs. the deadline on every page load/regenerate
attempt, which is sufficient since checking the app close to game time is
the whole point of using it.

Wherever picks are shown — locked or still open — a "Snapshot" toggle
lets you switch between the week's frozen `'first'` look and its
`'current'` snapshot (`store.load_week(..., snapshot_type=...)`), so
"what did I first see" vs. "what's it look like now/at lock" is visible
in the UI rather than only queryable in the database. Hidden until a
`'first'` snapshot actually exists for that week.

Manually overriding a locked week's algorithm recommendation is
deliberately not built — the locked snapshot is a permanent record, not
an editable one. What *is* built: once a week locks, the Picks tab shows
an "Your actual submission" form (`actual_picks`, `store.save_actual_picks()`)
defaulting every field to the algorithm's own recommendation, so you can
record what you actually wrote on the pool sheet if it ever deviated —
without re-entering every game by hand when it didn't. Purely a record
for future comparison; it has no effect on the locked picks themselves.

The form also lets you leave a game's winner unmarked, leave its points
box blank, assign the same points value to two games, or flag the whole
card as submitted late — real outcomes the bylaws themselves define exact
(non-exclusionary) resolutions for, so the form records them rather than
blocking the save (`picks_core.check_actual_picks()` explains which
bylaws rule applies whenever one of these is present, both right after
saving and on any later visit to an already-recorded week).

## Weekly scoring (once outcomes are known)

Once a locked week's games start finishing, the Picks tab shows the
algorithm's hypothetical score next to what you actually submitted —
`picks_core.score_picks()` scores either set of picks (`weekly_picks` or
`actual_picks` — same `game_id -> (predicted_winner, points)` shape, one
scoring function for both) against `games.home_score`/`away_score`,
applying bylaws rule 6 (a tied game awards no points to anyone) and rule 7
(two games sharing a points value are credited that value once, not
twice). A game without a final score yet is excluded from the running
total but still counted, so a mid-week check shows a partial, clearly-
labeled score ("6/9 games decided so far") instead of quietly scoring an
undecided game as wrong. An expander below the actual score breaks it down
game by game — pick, points assigned, actual winner, points actually
awarded — mainly so a reported-score mismatch (below) is diagnosable
instead of just a bare "these don't match."

Bylaws rule 2's late-card penalty (10 points below the field's lowest
card that week) is the one thing this can't compute — it needs every
other pool entrant's score, and this is a single-user tool that's never
tracked that. Instead, the same section lets you record the pool's
*officially reported* score for the week once the commissioner posts it
(`store.set_reported_score`) — authoritative for a late card, and for an
on-time card, a sanity check against the app's own computed total
(`picks_core.check_reported_score` flags a mismatch, skipped entirely for
a late card since a mismatch there is expected, not a bug). Manual entry
is the interim step before an eventual score-sheet/PDF import — see the
project plan's backlog.

## Season configuration (Settings tab)

`season_week_rules` holds the one thing this pool's rules can't derive from
`nfl_data_py`: the commissioner-announced late-season deadline(s), which
change every year — and, as of the 2026 rules, *which weeks* count as
"late season" can change too (`store.KNOWN_LATE_SEASON_WEEKS`). Editing
the deadlines is a form, not a code change/redeploy — `CP-1` in the
project plan tracks confirming/correcting each season's real values once
announced. The active-season switch is `seasons.active`, letting the
Picks tab default to the right season without a code change each year
either. See `docs/confidence-pool-data-model.md` for the full schema.

## Team display names (Settings tab)

The Legion pool's own pick sheet doesn't use `nfl_data_py`'s raw team
abbreviations (`LAC`, `LA`, ...) — it uses its own naming, inconsistent
across teams (some city+mascot, some city-only or all-caps). The Picks
tab shows `teams.display_name` wherever a team name appears (the game
checklist, the picks table) instead of the raw abbreviation. `store.DEFAULT_TEAMS`
seeds all 32 teams on first connect (`INSERT OR IGNORE`, so it never
overwrites a later edit) from names the user supplied directly against a
real 2025 late-season pick sheet — a starting basis, not a fixed constant,
since the whole point of storing this in the database (rather than a
Python constant) is that it's a UI label the user can correct or update
themselves via Settings without a code change or redeploy, the same
reasoning as the late-season deadlines above.

## Docker (`confidence_pool/Dockerfile`)

Same base image and non-root pattern as the dynasty app's root `Dockerfile`
(see `docker_guidelines.md`), on port 8502 (8501 is the dynasty app) so
both run side by side in `docker-compose.yml`/`docker-compose.deploy.yml`.
The SQLite file lives in a named volume (`confidence_pool_data`) —
`CP-2` in the project plan tracks confirming the NAS's offsite backup
actually covers it.

## Known gaps

- **Odds not yet posted**: a selected game missing a moneyline is
  surfaced separately as "pending" rather than ranked (see
  `picks_core.rank_games()`) — can happen early in a week before Vegas
  lines are posted for every game.
- **Only Vegas odds** — the other signals `football_enhanced.py` sketches
  (injury impact, weather/altitude, sentiment) aren't wired into
  `picks_core.py` — `CP-6`, deliberately deferred; the pure-odds approach
  already placed 7th of 100+ last season.

## Static assumptions

| Assumption | Where | Breaks if | How to revisit |
|---|---|---|---|
| `default_season_year()`'s March cutoff between "still last season" and "next season" | `picks_core.default_season_year` | Never expected to matter in practice — no one uses this app in February/early March | Not worth hardening further unless it does |

Schema-level assumptions (which weeks get the `'all_games'` selection
rule, `game_id` stability, the Sunday-afternoon cutoff default) live in
`docs/confidence-pool-data-model.md`'s own "Static assumptions" table.
