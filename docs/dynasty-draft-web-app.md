# Dynasty Draft Web App — Streamlit + Docker

The web presentation layer for the logic in `docs/rookie-draft-big-board.md`.
Built so the draft tool is usable from a phone during the live draft instead
of requiring a terminal, and deployable to the user's Synology NAS.

## Streamlit app (`dynasty/streamlit_app.py` + `dynasty/tabs/`)

Five tabs, all reading from one `dynasty_core.gather_state()` call per refresh:

1. **Draft Plan** — the round-by-round marginal-value simulation, backup
   alternates in expanders, a full player-projection lookup, weekly-gap
   impact.
2. **Lineup** — current optimal starters/bench.
3. **Draft Board** — the full rookie class, tiered, with draft attribution.
4. **Roster** — capacity, needs, value analysis, bye conflicts, weekly
   gaps, handcuffs, sellable veterans, free agents, and the team timeline
   read, for any team in the league via a selector (defaults to the user's
   own).
5. **Trade Evaluator** — an arbitrary multi-asset trade (players and/or
   picks) between two selected teams, evaluated for both sides, plus
   Suggested Trades: leaguewide by default (no partner/target pre-selected),
   or search one specific player directly. Its own tab rather than another
   Roster section — it's inherently two-team, not the "pick a team, see
   everything about them" shape every Roster section shares.

There is exactly one ranking method for "what should I pick next," used
everywhere in the app — the round-by-round Draft Plan. See
`.claude/conventions/valuation_principles.md`'s "one valuation strategy,
used everywhere" rule.

### Team selector (Roster tab)

Every per-roster analysis function (`roster_needs_summary`,
`roster_capacity`, `roster_value_analysis`, `lineup_breakdown`,
`roster_bye_conflicts`, `roster_weekly_gaps`, `roster_handcuff_status`)
takes a generic `roster` dict — the only thing that makes them "the user's
own" is which roster gets passed in. `team_roster_analysis()` bundles all
seven into one call and is what `gather_state` itself uses internally for
the user's roster, so there's exactly one code path, not a second
roster-agnostic model answering a similar-sounding question. The tab's
`st.selectbox` (user's own team first, then alphabetical) reuses the cached
bundle for the user's own team for free, and calls `team_roster_analysis()`
fresh on-demand for any other selected team — cheap enough (well under a
second) that no separate caching was needed. `gather_state` exposes
`rosters_by_id`, `players`, `fc_by_sleeper_id`, `byes`, `handcuffs`, and
`league` at the top level specifically so this (and the drop-search below)
can be computed outside the main per-refresh pass.

**Not built:** a league-wide summary view (one row per team — value,
biggest need, capacity — scannable before drilling into one team); see
`.claude/PROJECT_PLAN.md`. The team-selector approach answers "how does the
tool see this *one* team" well; it doesn't answer "which teams across the
league are worth scouting first."

### Roster needs: VOR / Weak columns

The "Roster needs" table adds `VOR`/`Weak` columns from
`positional_strength_summary` (methodology: `docs/rookie-draft-big-board.md`)
alongside the young-core `Need` flag, joined by `team_roster_analysis()`
since they're two answers about the same position. Works through the team
selector above unchanged; `replacement_level` is computed once per refresh
and passed into every on-demand `team_roster_analysis()` call.

### Team timeline

Sits above Roster capacity, for whichever team is selected — the
continuous power/timeline read (`team_power_timeline_scores()`, methodology
in the other doc). Computed for the whole league at once in `gather_state`
(the z-scoring needs every team together), unlike the VOR/Weak columns
above. Shown as `rank`/`league_size` (e.g. "3 of 12") rather than the raw
z-score — reads better cold, with the raw score one hover away via
`help=`. Pre-season, the win % caption reads "no games played yet" instead
of a misleading flat 50%. The CLI mirrors this with a `--- Team timeline
---` line for the user's own team.

A "❓ Glossary" button next to the page title opens an `st.dialog` (`GLOSSARY`
in `tabs/components.py`) defining VOR, power score, and adj. value.

### Sellable veterans / Free agents / Draft pick trade values

Three sections in the Roster tab, added for trade/roster-move evaluation
— see `docs/rookie-draft-big-board.md` and `.claude/PROJECT_PLAN.md` for
what's deliberately out of scope.

"Sellable veterans" sits right after Roster value analysis, and "Free
agents" right after that, both for whichever team the selector above has
picked — `analysis["sellable_players"]`/`analysis["free_agent_board"]`,
same on-demand-per-team pattern as the rest of the tab (unlike Team
timeline above, neither needs every team's row together). "Draft pick
trade values" sits at the bottom of the tab instead, explicitly *not*
filtered to the selected team — a pick's owner is already a column in
`state["pick_trade_values"]`, computed once league-wide in `gather_state`
the same way `team_power_timeline` is; a caption says so directly so it
doesn't read as a bug that changing the team selector above doesn't change
this table.

### Trade Evaluator (its own tab)

Its own tab, not folded into Roster — a trade is inherently two teams plus
a hypothetical exchange, so it gets its own "Trade partner" selector,
independent of the Roster tab's. Four multiselects (players/picks given
up/received) built from data already in `state`; recomputes reactively on
every change rather than needing an "Evaluate" button. Calls
`dynasty_core.evaluate_trade()` twice, once per side — "both sides" falls
out of the function's own symmetry, not a second code path. The "Lineup
value" metric shows `lineup_delta_after_drops` (post-forced-cuts) rather
than the raw `lineup_delta` when cuts are needed, raw number one hover
away via `help=` — same pattern as the Team timeline metric's raw z-score.

A second section, "Suggested Trades," sits below and is deliberately
*not* wired to the manual evaluator's team selectors — it always scans for
`state["user_roster_id"]`'s real roster (`RT-15`). A `st.selectbox` across
every player on every other roster is the optional single-target picker:
choosing one runs `dynasty_core.find_trade_offers()` immediately (same
"acquire for free" read plus each suggested offer's both sides in its own
expander as before, an `st.info` explaining directly when nothing clears
the partner's bar). Leaving it unset shows the default leaguewide view
instead: `state["suggested_trade_candidates"]` (Stage 1, already computed
every refresh inside `gather_state()`) as a plain candidate count, plus a
"Scan the league for offers" button that runs `dynasty_core.suggested_trades()`
(Stage 2, the expensive part — kept behind a button rather than reactive)
and renders up to 3 results the same expander style, each one naming its
owning team since there's no longer a single implied partner. Results
persist across reruns via `st.session_state["suggested_trades_results"]`
rather than needing a re-click on every unrelated page interaction.

### Player projection lookup

Each round's "Backup options" table defaults to the top
`MAX_DISPLAYED_ALTERNATES` (2), but `rank_by_marginal_value` already scores
every candidate, so the full ranked list is exposed via a `st.selectbox`
per round at no extra cost (`Name (POS) — marginal value`, web-only — the
CLI is unchanged). The top alternates' displayed value comes from the
cheap `recommend_drop()` heuristic used during ranking; selecting a
candidate from the full list instead triggers a real
`dynasty_core.best_position_relevant_drop()` search on-demand, restricted
to players sharing a slot type with that specific candidate (effectively
"any skill player" here, since SUPER_FLEX covers all four positions) —
only computed for the one selected candidate, not precomputed for the
whole pool.

### Sidebar league name and version footer

The sidebar section header shows the actual loaded league name instead of a
generic "League" label — but since Streamlit renders the sidebar before
`gather_state()` has run (the league ID input itself determines what to
fetch), there's a chicken-and-egg problem. Solved via
`st.session_state.league_name`, seeded to `"League"` and updated once state
loads successfully: the very first render of a session shows the generic
label, and it settles to the real name from the next rerun onward. No extra
network call, no attempt to force a same-render update that Streamlit's
execution model doesn't support.

A footer (`Dynasty Rookie Draft · build {APP_VERSION}`) shows the short git
SHA the running image was built from, read from a `GIT_SHA` environment
variable — this exists specifically to verify a NAS deployment actually
picked up a new image rather than silently continuing to run a stale one.
The `Dockerfile` declares `ARG GIT_SHA=dev` / `ENV GIT_SHA=$GIT_SHA`;
`docker-publish.yml` passes `--build-arg GIT_SHA=${{ github.sha }}` so the
footer matches the same commit the image is tagged with in GHCR. Local
`docker compose build` (no build-arg passed) and plain `streamlit run` both
fall back to `dev` — if a NAS deployment ever showed `dev`, that would mean
the image wasn't actually built by CI.

### Refresh model

Streamlit reruns the whole script top-to-bottom on any widget interaction,
so a naive port would refetch on every unrelated click. `st.cache_data` is
keyed on an explicit `refresh_token` in `st.session_state`, set only by
the Refresh button or the Advanced-refresh "Apply" button — mirroring the
CLI's Enter-vs-`f` prompt. A button/checkbox's own value can't be the cache
key directly — it's only current on the exact run it was clicked, so a
later rerun (e.g. opening an expander) would see a stale/default value and
get a different key, silently missing cache and re-fetching for no reason.
`st.session_state.force_refresh_pending`/`force_scoring_pending` hold the
durable versions instead, set once per click and stable across reruns.

**`load_state`'s cache-busting argument must never be named with a leading
underscore.** This is the actual root cause of a "Refresh doesn't pick up
new picks" bug that took three attempts to actually fix (found live on the
Synology deployment, 2026-08-16) — worth stating first and plainly, since
the two earlier, incomplete fixes below are easy to misread as the real
story. Streamlit's `st.cache_data` silently excludes any argument whose name
starts with `_` from the cache key entirely (a real, documented convention
for genuinely unhashable arguments, like a DB connection) — confirmed
directly against the installed `streamlit` source
(`streamlit.runtime.caching.cache_utils._make_value_key`) and by a live
repro. `load_state`'s token parameter used to be named `_token`: a plain
`float`, always hashable, that never needed the underscore. Its *value*
never mattered to caching at all — only `league_id`, `username`,
`force_full_refresh`, and `force_scoring_refresh` were ever actually part of
the cache key. A plain Refresh click leaves all four of those unchanged, so
**a plain Refresh has never busted the cache** — it silently returned
whatever was cached under `(league_id, username, False, False)` from the
first time that combination was ever called in the process's lifetime.
Advanced refresh *did* work (it flips `force_full_refresh`, a real, hashed
argument), which is exactly why "Advanced refresh fixes it, then the very
next plain Refresh reverts" was the reported symptom every time — the two
force flags select a genuinely different cache entry, and a plain Refresh
right after switches back to the older one. Fixed by simply renaming the
parameter to `token` (no leading underscore), restoring it to the hash.
`tests/test_streamlit_refresh_cache.py` is a regression test for this
specific hazard — it drives the real app via `streamlit.testing.v1.AppTest`
and asserts a repeated Refresh click produces a repeated real fetch, not one
cached value forever; it fails against a reintroduced `_token`.

The two earlier attempts, left below for the record since neither was wrong
so much as incomplete — both changed the token's *value* without ever
addressing that the *name* made the value irrelevant to caching:

`refresh_token` is a real timestamp (`dt.datetime.now().timestamp()`) when a
click sets it, not an incrementing counter — found live during a draft
(2026-08-08): `st.cache_data`'s cache is shared across the *whole server
process*, not per session, but `st.session_state.refresh_token` resets for
every new/reconnected session (a page reload, a phone backgrounding the
tab). A counter restarting at a small integer on each session could land on
a value some *other* session already used earlier in the same draft,
silently hitting that session's stale cached snapshot instead of actually
re-fetching — the working theory at the time. A sub-second timestamp can't
collide with a prior click's value the way a small per-session counter can
— true, but moot while the token wasn't part of the cache key at all.

The pre-click default (before the user has ever clicked Refresh this
session) is `dt.datetime.now().timestamp() // 60` — "now, rounded down to
the minute" — not the fixed `0` used right after the fix above shipped.
Found live again on the NAS deployment (2026-08-16, the same investigation
that found the underscore issue above): a fixed `0` default never expires,
so *any* reconnect (not just the first load) would fall back to whatever
got cached under key `0` — the working theory at the time was that this
explained the NAS-specific staleness on its own. Minute-bucketing keeps a
reasonable property regardless (sessions loading within the same minute,
e.g. two of your own devices opening the page at once, still share one
fetch) and is harmless to keep, but with the token now actually part of the
cache key, a plain Refresh no longer depends on this default at all — it
always sets a fresh, real timestamp on click. `load_state`'s `@st.cache_data`
also sets `ttl="1h"` as a backstop, so a long-lived NAS process can't
accumulate an unbounded number of cache entries with no ttl to evict them.

Refresh is always manual — there is no polling or background auto-refresh
anywhere in this app or the CLI. A sidebar caption ("Last refreshed:
HH:MM:SS") makes that visible: `load_state()` stamps `state["loaded_at"]`
with `dt.datetime.now()` *inside* the `@st.cache_data`-wrapped function, so
it's frozen at the moment `gather_state()` actually ran and reused verbatim
on every cache hit (tab switches, expanders) — reading the clock anywhere
outside that function would just report "now" on every rerun instead of
when the data was actually pulled. The Draft Plan tab's "How this works"
repeats the same point with the specific timing that matters: refresh right
before your own pick, not just after one lands elsewhere, since the plan
otherwise simulates as if no other team has picked in between.

Refresh re-pulls league/rosters/draft/picks (cheap, always live) plus
whatever's expired on `fantasycalc_api`/`bye_week_by_team`/`handcuff_map`'s
own TTL caches (12-24h, not tied to any button at all). The sidebar's
"Advanced refresh" expander splits the two remaining, genuinely different
concerns instead of bundling them behind one "force full refresh" button:

- **Players + market values (fast, default on)** — busts the on-disk 14MB
  players-dataset cache; a few seconds.
- **Recompute scoring multipliers (slow, 1-2 min, default off)** — forces
  `player_scoring`'s multiplier cache to re-import 3 seasons of weekly +
  play-by-play data. Its own checkbox, off by default, and gated behind a
  second "Apply advanced refresh" button — a routine refresh must never
  trigger this by accident mid-draft. This is also the in-app equivalent of
  running `python scripts/derive_position_multipliers.py` directly.

Whenever byes, handcuffs, or the scoring multipliers silently fall back to
an empty/default result (a fetch failure, non-fatal by design — see
`docs/rookie-draft-big-board.md`), `gather_state` returns a
`data_warnings` list, surfaced as `st.warning`/CLI `WARNING:` lines.

Network/parsing errors surface as `st.error` with a retry hint instead of a
raw traceback — this needs to stay usable on a phone mid-draft. The CLI's
own refresh loop mirrors this: it catches `ValueError`/`TypeError` (a bad
`--league-id`/typo'd `--username`) with a clean message and exit, rather
than a traceback or an infinite retry loop that can't fix a bad input.

A connectivity failure names which of the two upstream services actually
failed, instead of one generic message that's true either way — real on
draft day, when everyone hits both unauthenticated public APIs at once.
`gather_state()` wraps its Sleeper calls and its one FantasyCalc call in
their own `try`/`except requests.RequestException`, re-raising with a
`"Couldn't reach Sleeper: ..."` / `"Couldn't reach FantasyCalc: ..."`
prefix — same exception type, so the CLI/Streamlit `except
requests.RequestException` handlers didn't need to change. Covered by
`tests/dynasty_core/test_state.py`'s `TestGatherStateConnectivityErrors`, which
monkeypatches `sleeper_api`/`fantasycalc_api` directly — the one place in
that test suite `testing.md`'s "mock only external services you do not
control" applies, since everything else there is pure logic over synthetic
data with no real boundary to mock.

The `{gsis_id: sleeper_id}` crosswalk `player_scoring.py` and
`dynasty_core.handcuff_map` each need from `nfl_data_py`'s ID table is built
once, by `player_scoring.gsis_to_sleeper_crosswalk()`, rather than as two
separate copies of the same dict comprehension — it logs a warning listing
any `gsis_id` with more than one distinct `sleeper_id` before falling back
to last-row-wins.

### Table presentation

Conventions applied consistently across every tab:

- **Human-readable column labels**, display-only — DataFrames keep plain
  snake_case columns for the rest of the codebase/tests; a `cols()` helper
  builds `st.dataframe`'s `column_config` from `(key, label[, help])`
  tuples (`"_index"` relabels an index-as-column header, e.g. Roster
  Needs' `pos` → "Pos").
- **Decimal precision capped at 2 digits, display-only** — `cols()` checks
  each column's dtype and applies `NumberColumn(format="%.2f")` to floats
  uniformly (raw `adj_value` routinely carries 6+ digits). The CLI mirrors
  this via `to_string(float_format=...)`.
- **Per-cell hover tooltips need custom HTML** — `column_config`'s `help`
  only tooltips column headers, not cells. Roster Value Analysis's
  `status` icons need per-cell detail (the actual `injury_status` word),
  so that one table renders as escaped HTML (`show_status_table()`)
  instead of the shared `show_df()`/`cols()` path — a scoped exception,
  applying the same 2-decimal cap manually since it bypasses `cols()`.
- **Methodology text lives in a closed "How this works" expander**, not a
  bare caption — keeps data above the fold on mobile.

## CLI (`dynasty/rookie_draft.py`)

Thin wrapper: `print_report()` renders the same `gather_state()` output as
plain text, `main()` adds the interactive Enter/`f`/`q` refresh loop. Kept
in full parity with the web app deliberately — it's the tested fallback if
Docker or the NAS has a problem on draft day.

Every `DataFrame.to_string()` call passes `float_format=DISPLAY_FLOAT_FORMAT`
(`"{:.2f}".format`) — pandas' own default (`display.precision`, 6 digits)
otherwise prints raw values straight from the underlying computation.
Display-only: `float_format` is a formatting callback for `to_string()`'s
own output, not something that touches the DataFrame it's called on, so
nothing downstream (tests, further computation) is affected. Same cap and
reasoning as the web app's `cols()` (see above), applied uniformly rather
than per-column.

## Docker + CI/CD

Matches the pattern already established in the sibling `Finance-Dashboards`
project, for consistency across the user's projects rather than inventing a
new one:

- **`python:3.12-slim`, not alpine** — `nfl_data_py` pulls in
  `fastparquet`/`cramjam`, which frequently lack prebuilt musl wheels and
  force a slow/fragile Rust source build on alpine. Same call, same reason,
  made independently in both projects.
- **Non-root**, pinned `uid/gid 1000`.
- **stdlib-`urllib` `HEALTHCHECK`** — no `curl` install, keeps the slim image
  slim.
- **GitHub Actions builds and publishes to GHCR on push to `main`**
  (`.github/workflows/docker-publish.yml`), using the automatic
  `GITHUB_TOKEN` — no registry secrets to manage. Tagged `:latest` and
  `:<short-sha>`; no `VERSION`-file semver, a deliberate simplification
  since this is a single-image personal tool, not a versioned release
  product (`Finance-Dashboards` does use a `VERSION` file — an intentional
  divergence, not an oversight).
- **Two compose files**: `docker-compose.yml` builds from source for local
  dev; `docker-compose.deploy.yml` only ever *pulls* the prebuilt GHCR image
  — the NAS never builds on-device. Host port is remappable via `.env`'s
  `HOST_PORT` (`.env.example` committed); the container's internal port
  stays fixed at 8501.
- **Named volume** (`nfl_data_cache`) for the whole `.cache/` directory —
  the on-disk players-dataset cache (so it survives container restarts
  instead of re-downloading ~14MB every time) and the real-scoring
  multiplier cache (see `player_scoring.py`) — matches
  `docker_guidelines.md`'s "named volumes for data that should persist"
  directly.

### API resilience and test coverage

`sleeper_api.py` and `fantasycalc_api.py` each use a `requests.Session` with
a mounted `Retry` adapter (3 retries, exponential backoff, retrying only
GET and only on connection errors/429/5xx) instead of a bare `requests.get`
— draft day means everyone hits these APIs at once, so a transient hiccup
shouldn't be a hard failure. The CLI's interactive loop wraps
`gather_state()` in a try/except: a failure prints an error and offers
retry/quit instead of crashing the whole session.

`.github/workflows/ci.yml` runs `tests/dynasty_core/` and
`tests/test_player_scoring.py` on every PR to `main`. See
`docs/rookie-draft-big-board.md` for what's actually covered.

### Verified before merge

Checks run against a fresh `docker compose build && up` before any Docker/CI
change ships:

- Image builds, container reports healthy, serves on `:8501`.
- From inside the running container: `dynasty_core.gather_state(...)`
  succeeds (confirms outbound network access to Sleeper/FantasyCalc) and
  writes `players.json` to the mounted volume.
- Restarting the container leaves the cache file's timestamp unchanged —
  the named volume actually persists, not just configured to.
- After merge to `main`: `docker-publish.yml` runs to completion and the
  image lands in GHCR.
