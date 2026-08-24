# Confidence Pool Data Model — Schema & Persistence

How the confidence-pool app's SQLite store is actually shaped, and why —
current-state reference only, per `docs/README.md`'s convention. Active/open
work belongs in `.claude/PROJECT_PLAN_CONFIDENCE_POOL.md`, not here. Mirrors
`docs/dynasty-data-model.md`'s role for the dynasty subsystem.

## Why a normalized schema, not one flat table per feature

The schema grew feature-by-feature at first — `season_config`, then
`weekly_games`/`weekly_picks`, then `team_display_names` — until two seams
stopped being tolerable once multi-season, backtestable history became the
actual goal: schedule facts (teams, kickoff time) were tangled together with
one generation event's odds/picks in the same row, and the weeks-17/18
bylaws exception was a Python constant (`LATE_SEASON_WEEKS`) rather than
data. The fix: split **stable reference data** (`teams`, `games`, per-season
rules) from **event data** (a specific generation's odds/picks), and give
the event data an explicit type instead of only ever holding "whatever's
current."

## Tables

| Table | Holds |
|---|---|
| `seasons` | Which season is active; the per-season Sunday-afternoon cutoff time |
| `season_week_rules` | Only for weeks whose selection/deadline rule differs from the default (today: 17-18) |
| `teams` | Abbreviation -> pool-sheet display name, all 32 teams |
| `games` | The stable schedule + outcome fact for one game -- teams, kickoff, and (once known) the final score |
| `algorithm_versions` | Every `picks_core.ALGORITHM_VERSION` string that's ever generated a pick, with a description |
| `weekly_games` | A game's evaluated odds/inclusion at a point in time (`snapshot_type`: `'current'` or `'first'`) |
| `weekly_picks` | The generated recommendation for a game at a point in time, same `snapshot_type` split |
| `week_status` | `locked`/`locked_at`/`generated_at` per `(season_year, week)` |

### `seasons` and `season_week_rules`

```sql
CREATE TABLE seasons (
    season_year INTEGER PRIMARY KEY,
    active INTEGER NOT NULL DEFAULT 0,
    sunday_afternoon_cutoff TEXT NOT NULL DEFAULT '13:00'
);

CREATE TABLE season_week_rules (
    season_year INTEGER NOT NULL REFERENCES seasons(season_year),
    week INTEGER NOT NULL,
    selection_rule TEXT NOT NULL CHECK (selection_rule IN ('standard', 'all_games')),
    deadline_override TEXT,
    PRIMARY KEY (season_year, week)
);
```

Only *exception* weeks get a `season_week_rules` row. A week with no row
follows the default `'standard'` rule (Sunday-afternoon + Monday,
deadline = earliest kickoff) in `picks_core.select_games()`/`week_deadline()`
— those functions take `selection_rule`/`configured_deadline` as plain
parameters and don't know which weeks are special; the caller (`panels/picks_tab.py`)
looks up `store.get_week_rule()` and decides. Weeks 17-18 get an
`'all_games'` row (every game that week, no weekday filter — see
"Static assumptions" below) with `deadline_override` set once the
commissioner announces it each year (`store.set_late_season_deadline`,
Settings tab). This is deliberately not a general rule engine (no stored
weekday lists, no DSL) — two known rule shapes isn't enough cases to justify
one, per this project's "wait for three concrete cases" convention.

### `teams`

```sql
CREATE TABLE teams (
    abbreviation TEXT PRIMARY KEY,
    display_name TEXT NOT NULL
);
```

Seeded on every `connect()` with `store.DEFAULT_TEAMS` (`INSERT OR IGNORE`,
so a Settings-tab edit is never clobbered). What `games`/`weekly_picks`
foreign-key into for `home_team`/`away_team`/`predicted_winner`.

### `games`

```sql
CREATE TABLE games (
    game_id TEXT PRIMARY KEY,
    season_year INTEGER NOT NULL,
    week INTEGER NOT NULL,
    home_team TEXT NOT NULL REFERENCES teams(abbreviation),
    away_team TEXT NOT NULL REFERENCES teams(abbreviation),
    gameday TEXT NOT NULL,
    weekday TEXT NOT NULL,
    gametime TEXT NOT NULL,
    home_score REAL,
    away_score REAL,
    outcome_synced_at TEXT
);
```

Populated by `store.save_week()` for whatever games a week's generation
actually evaluated — a game the pool's rules never select (a Thursday game
in a `'standard'` week) never gets a row here at all. `home_score`/`away_score`
start `NULL` and get backfilled by `store.sync_game_outcomes()`, called on
every Picks-tab page load against the schedule already fetched for the
season being viewed (`nfl_data_py`'s schedule export carries `home_score`/
`away_score`, `NULL` until a game completes — verified against a real fetch,
not assumed). Update-only: it never inserts a new `games` row, so this stays
scoped to games the app actually evaluated. `game_id` is `nfl_data_py`'s own
key (`{season}_{week:02d}_{away}_{home}`, e.g. `2026_01_BAL_IND`) — stable
and human-readable, confirmed live.

### `algorithm_versions`

```sql
CREATE TABLE algorithm_versions (
    version_id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    introduced_at TEXT NOT NULL
);
```

`picks_core.ALGORITHM_VERSION` (currently `"vig-proportional-v1"`) is
registered once at app startup (`streamlit_app.py`, `store.register_algorithm_version`,
idempotent) and stamped onto every `weekly_picks` row by `picks_core.rank_games()`.
Bump the constant — and add a row here describing what changed — whenever
the ranking math changes, so a historical pick stays attributable to the
exact formula that produced it.

### `weekly_games` / `weekly_picks` and the `snapshot_type` split

```sql
CREATE TABLE weekly_games (
    game_id TEXT NOT NULL REFERENCES games(game_id),
    snapshot_type TEXT NOT NULL CHECK (snapshot_type IN ('current', 'first')),
    home_moneyline REAL,
    away_moneyline REAL,
    included INTEGER NOT NULL DEFAULT 1,
    captured_at TEXT NOT NULL,
    PRIMARY KEY (game_id, snapshot_type)
);

CREATE TABLE weekly_picks (
    game_id TEXT NOT NULL REFERENCES games(game_id),
    snapshot_type TEXT NOT NULL CHECK (snapshot_type IN ('current', 'first')),
    points INTEGER NOT NULL,
    predicted_winner TEXT NOT NULL REFERENCES teams(abbreviation),
    confidence REAL NOT NULL,
    algorithm_version TEXT NOT NULL REFERENCES algorithm_versions(version_id),
    PRIMARY KEY (game_id, snapshot_type)
);
```

`'current'` is the live working snapshot — overwritten by `store.save_week()`
on every "Regenerate picks" click, frozen the moment `week_status.locked = 1`
(`save_week()` refuses to touch an already-locked week). `'first'` is
captured once, on the very first `save_week()` call ever made for a
`(season_year, week)`, and never touched again after that — exactly two rows
per game, ever, no unbounded growth. This is what makes "did the odds move
between when I first checked this week and when it locked" a query
(compare `captured_at`/`confidence` across the two `snapshot_type` rows)
instead of something that would've needed a manual screenshot at the time.

`home_team`/`away_team`/`gameday`/`weekday`/`gametime` live only in `games`
now, not repeated on every snapshot — they're true for the life of the game,
not just one generation event.

## Schema migrations

```
confidence_pool/
  db_schema/
    __init__.py          # apply_migrations(conn)
    migrations/
      0001_initial.sql
```

`store.connect()` calls `db_schema.apply_migrations(conn)`, which tracks
applied versions in `schema_migrations` (`version INTEGER PRIMARY KEY,
applied_at TEXT`) and runs any `*.sql` file under `migrations/` not yet
recorded there, in ascending numeric-prefix order, each as its own
transaction. `0001_initial.sql` is the schema above in full — a fresh
origin migration for a greenfield deploy, not a replay of the app's
pre-migration development history (which never held real production data).
Every schema change from here forward gets its own numbered migration file.

Named `db_schema`, not `schema`, specifically to avoid ever colliding with
the `schema` PyPI package (a validation library) if that's added as a
dependency elsewhere in this repo.

## Static assumptions

| Assumption | Where | Breaks if | How to revisit |
|---|---|---|---|
| Weeks 17-18 use the `'all_games'` rule (every game that week, no weekday filter) | `season_week_rules` seed data / `set_late_season_deadline` | A future season's bylaws genuinely narrow weeks 17-18 back to a subset | Insert a `season_week_rules` row with a different `selection_rule` for that season/week — no code change needed, this is exactly what the table is for |
| `game_id` stability across a season | `store.save_week`/`sync_game_outcomes`, both keyed on it | `nfl_data_py` ever changes a game's `game_id` mid-season between fetches | Not verified over a full season yet (this app re-derives `select_games()`'s output fresh every fetch and has never depended on `game_id` stability before now) -- watch for it |
| `sunday_afternoon_cutoff` is `13:00` ET for every season so far | `seasons.sunday_afternoon_cutoff` default | The pool ever includes an earlier Sunday game, or a normal 1pm slate game gets flexed earlier | Already a per-season Settings value, not a code constant -- just needs editing if it happens |
