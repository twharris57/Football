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
afternoon and Monday-night games "almost always" go on the sheet; weeks
17-18 move to Saturday-only, since the bylaws' own deadline there is
earlier than any of that week's actual kickoffs (rule 2). `picks_core.select_games()`
encodes this as:

- `game_type == 'REG'` (excludes preseason and any playoff rows this pool
  never uses).
- Weeks 1-16: `weekday in ('Sunday', 'Monday')`, and for Sunday,
  `gametime >= '13:00'` — this excludes Thursday Night Football and any
  early/international Sunday game.
- Weeks 17-18: `weekday == 'Saturday'` only. Confirmed against the real
  2025/2026 schedules (`nfl_data_py`): week 17/18 games actually spread
  across Thu/Sat/Sun/Mon, and the bylaws' "Weeks 17 & 18 will all feature
  Saturday games" turned out to mean *the sheet only uses that week's
  Saturday game(s)*, not that every game that week is on Saturday.

Because the bylaws themselves say "almost always" (commissioner discretion,
exceptions happen), the Picks tab shows the auto-selected list with a
per-game include/exclude checkbox before ranking runs — not just an
escape-hatch override for a wrong guess, a normal part of reviewing each
week.

### Pick-submission deadline

`picks_core.week_deadline()`: weeks 1-16 use the earliest kickoff among
that week's selected games (rule 2: "before kick-off"). Weeks 17-18 use an
explicit early cutoff from `season_config` instead — the bylaws' own
example (2025: Sat Dec 27 before 1:00pm ET; Sat Jan 3 before 4:30pm ET) is
*earlier* than either week's actual kickoffs, so it's commissioner-
announced each year, not computable from the schedule. Falls back to the
earliest Saturday kickoff if the season's cutoff hasn't been configured
yet (Settings tab).

## Persistence (`store.py`)

SQLite, four tables, all keyed by `(season_year, week[, game_id])` so
multiple seasons coexist in one store:

| Table | Holds |
|---|---|
| `season_config` | Which season is active; weeks 17/18's configured deadlines |
| `week_status` | `locked`/`locked_at`/`generated_at` per week |
| `weekly_games` | The evaluated game list at generation time (teams, moneylines, kickoff, `included`) |
| `weekly_picks` | The generated recommendation (points, predicted winner, confidence) |

Every week's evaluated games and generated picks get saved as part of the
normal flow (not just on request) so future analysis — what-if scoring
against real outcomes, an eventual small analytics API — has real
historical input instead of needing to reconstruct it later (see
`.claude/PROJECT_PLAN_CONFIDENCE_POOL.md`'s `CP-3`/`CP-5`).

### Lock-in

A week can be regenerated freely before its deadline (`Picks` tab's
"Regenerate picks" button overwrites the saved snapshot). Once
`is_locked(now, deadline)` is true, `picks_core.resolve_week_lock()`
decides what to lock: the last manually-generated snapshot if one exists
(reused as-is, not recomputed against whatever odds happen to be live at
that moment — moneylines move over a week, and the locked row is the
permanent historical record `CP-3`/`CP-4` depend on), or one final
computed snapshot if nothing was ever generated. If odds are still
pending for a selected game and there's no prior snapshot to fall back
on, the week is left unlocked with an explicit warning rather than
silently not locking. The picks tab then switches to a read-only view —
`store.save_week()` refuses to overwrite an already-locked week's row.
There's no background scheduler: "locked" is computed from `now` vs. the
deadline on every page load/regenerate attempt, which is sufficient since
checking the app close to game time is the whole point of using it.

Manually overriding a locked week, or recording an actual submitted pick
that deviated from the recommendation, is deliberately not built — see
`CP-4` in the project plan.

## Season configuration (Settings tab)

`season_config` holds the one thing this pool's rules can't derive from
`nfl_data_py`: the commissioner-announced weeks-17/18 deadline, which
changes every year. Editing it is a form, not a code change/redeploy —
`CP-1` in the project plan tracks confirming/correcting 2026's value once
it's announced. The active-season switch is the same table's `active`
flag, letting the Picks tab default to the right season without a code
change each year either.

## Docker (`confidence_pool/Dockerfile`)

Same base image and non-root pattern as the dynasty app's root `Dockerfile`
(see `docker_guidelines.md`), on port 8502 (8501 is the dynasty app) so
both run side by side in `docker-compose.yml`/`docker-compose.deploy.yml`.
The SQLite file lives in a named volume (`confidence_pool_data`) —
`CP-2` in the project plan tracks confirming the NAS's offsite backup
actually covers it.

## Known gaps

- **Team display names**: the UI shows `nfl_data_py`/Sleeper team
  abbreviations (`LAC`), not the names printed on the Legion pool's own
  pick sheet (`LA Chargers`, `DENVER`, `DALLAS`, ...) — `CP-7`.
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
| Sunday-afternoon cutoff is a fixed `13:00` ET | `picks_core.SUNDAY_AFTERNOON_CUTOFF` | The pool ever includes an early Sunday game, or a normal 1pm slate game gets flexed earlier | Confirm against a season where this mattered; make configurable if it ever does |
| Weeks 17-18 are `weekday == 'Saturday'`-only | `picks_core.select_games` | A future season's final two weeks aren't scheduled with a Saturday game at all | Falls through to an empty selection, caught by the Picks tab's "no games matched" warning — not silent |
| `default_season_year()`'s March cutoff between "still last season" and "next season" | `picks_core.default_season_year` | Never expected to matter in practice — no one uses this app in February/early March | Not worth hardening further unless it does |
