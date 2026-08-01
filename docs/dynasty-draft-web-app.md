# Dynasty Draft Web App — Streamlit + Docker

The web presentation layer for the logic in `docs/rookie-draft-big-board.md`.
Built so the draft tool is usable from a phone during the live draft instead
of requiring a terminal, and deployable to the user's Synology NAS.

## Streamlit app (`streamlit_app.py`)

Four tabs, all reading from one `dynasty_core.gather_state()` call per refresh:

1. **Draft Plan** — the round-by-round marginal-value simulation, backup
   alternates in expanders, a full player-projection lookup, weekly-gap
   impact.
2. **Lineup** — current optimal starters/bench.
3. **Draft Board** — the full rookie class, tiered, with draft attribution.
4. **Your Roster** — capacity, needs, value analysis, bye conflicts, weekly
   gaps, handcuffs, for any team in the league via a selector (defaults to
   the user's own).

An earlier "Strategy" tab (a single top-pick recommendation, computed by a
*different* algorithm than the round-by-round plan) was merged into Draft
Plan after the two turned out to disagree with each other on what to pick
next — two answers to the same question was a real bug, not a feature; there
is now exactly one ranking method, used everywhere.

### Team selector (Your Roster tab)

User feedback: the original idea of "a player dropdown" actually meant
*other teams in the league*, not other draft candidates (the Draft Plan
tab's lookup, below, covers that instead) — specifically, seeing how the
tool evaluates competitors' rosters. Every per-roster analysis function
(`roster_needs_summary`, `roster_capacity`, `roster_value_analysis`,
`lineup_breakdown`, `roster_bye_conflicts`, `roster_weekly_gaps`,
`roster_handcuff_status`) already took a generic `roster` dict — the only
thing that ever made them "the user's own" was which roster `gather_state`
happened to pass in. `team_roster_analysis()` bundles all seven into one
call and is now what `gather_state` itself uses internally for the user's
roster, so there's exactly one code path, not a second roster-agnostic
model built to answer a similar-sounding question. The tab's `st.selectbox`
(user's own team first, then alphabetical) reuses the cached bundle for the
user's own team for free, and calls `team_roster_analysis()` fresh
on-demand for any other selected team — cheap enough (well under a second,
confirmed directly) that no separate caching was needed. `gather_state`
exposes `rosters_by_id`, `players`, `fc_by_sleeper_id`, `byes`, `handcuffs`,
and `league` at the top level specifically so this (and the drop-search
below) can be computed outside the main per-refresh pass.

**Backlog, not built here:** a league-wide summary view (one row per team -
value, biggest need, capacity - scannable at a glance before drilling into
one team) was considered and explicitly deferred; see
`.claude/PROJECT_PLAN.md`. This team-selector approach answers "how does
the tool see this *one* team" well; it doesn't answer "which teams across
the league are worth scouting first," which needs its own summary view,
not just this same call repeated.

### Roster needs: VOR / Weak columns

The "Roster needs" table gained two columns (`positional_strength_summary`,
see `docs/rookie-draft-big-board.md` for the full methodology) alongside
the existing young-core `Need` flag: `VOR` (value-over-replacement) and
`Weak` (`VOR <= 0`) — a position whose actual starters aren't worth what's
freely available anywhere else in the league. `team_roster_analysis()`
joins this onto the existing `roster_needs` table rather than adding a
separate one, since they're two answers about the same position a user
would want side by side, not competing views. The "How this works"
expander spells out why they can disagree (plenty of bodies but no real
value, or the reverse) and why VOR compares against the whole league
rather than the rest of the team's own roster specifically — the latter
would make one elite player elsewhere distort every other position's
apparent strength. Works through the team selector above unchanged:
`replacement_level` (the league-wide baseline) is computed once per
refresh in `gather_state` and passed into every `team_roster_analysis()`
call, including the on-demand ones for other teams.

### Player projection lookup

Each round's "Backup options" table only ever showed the top
`MAX_DISPLAYED_ALTERNATES` (2) alternates — useful as a default, but not a
way to check an arbitrary player. `dynasty_core.rank_by_marginal_value`
already scores *every* available candidate before sorting and slicing to
the displayed few (`multi_round_plan`'s docstring notes the ~20,000-call
cost of that pass), so exposing the rest costs nothing extra — `top_n` is
now just `len(candidate_ids)` for upcoming rounds, and the full ranked list
is returned as `all_candidates_by_pick` alongside the existing
`alternates_by_pick`. Each round's expander gets a `st.selectbox` built
from that full list (sorted best-first, same order as the table), showing
`Name (POS) — marginal value` per option so the number is visible without
even opening the detail line below it. Deliberately skips
`alternate_gap_note` for the full list — fine for 2 backups, not worth a
per-candidate weekly-gap comparison for a ~200-player pool most of which
nobody will ever look up. Web-only — the CLI has no interactive selectbox
equivalent, and its `alternates_by_pick` table output is unchanged, so
this is an intentional, scoped divergence from the "full parity" rule
below, not an oversight.

The displayed marginal value still comes from the cheap
`recommend_drop()` heuristic every candidate was scored with during
ranking (lowest-value bench player, full stop) — accurate enough to sort
~227 candidates quickly, but not a real per-candidate answer to "what
should I actually drop for *this* player." User feedback on an earlier
version of this feature: showing that heuristic's drop alongside each
candidate was actively unhelpful, since one globally-low-value player
often "wins" as the suggested drop for every candidate regardless of
position, making the field look broken/repetitive rather than
informative. Once a candidate is selected, the app instead calls
`dynasty_core.best_position_relevant_drop()` fresh (using that round's
roster snapshot from `hypothetical_ids_by_pick`) — a real search,
restricted to players who share a slot type with the *specific* selected
candidate (own position, plus FLEX/SUPER_FLEX-eligible positions if the
league's `roster_positions` actually has those slots and the candidate
qualifies), over every resulting season-average marginal value, not just
whichever player has the lowest raw `adj_value`. In this league SUPER_FLEX
covers all four fantasy positions, so that restriction is effectively "any
rostered skill player" — a correct reflection of the real slot structure,
not a bug. This can still legitimately land on the same player as the
cheap heuristic (verified directly: with the live roster's real bye/value
distribution as of this writing, it does, for every candidate checked) —
that's not a sign the fix didn't work, it means that player really is the
optimal drop, now *proven* by search rather than assumed by a value
shortcut. It's deliberately only computed on-demand for the one selected
candidate, not precomputed for all ~227 — evaluating every drop option
for every candidate during the main ranking pass would multiply that
pass's cost by the size of the search pool.

### Sidebar league name and version footer

The sidebar section header shows the actual loaded league name instead of a
generic "League" label — but since Streamlit renders the sidebar before
`gather_state()` has run (the league ID input itself determines what to
fetch), there's a genuine chicken-and-egg problem. Solved via
`st.session_state.league_name`, seeded to `"League"` and updated once state
loads successfully: the very first render of a session shows the generic
label, and it settles to the real name from the next rerun onward (verified
directly via `AppTest` — one `.run()` still shows `"League"`, a second
`.run()` shows the real name). No extra network call, no attempt to force a
same-render update that Streamlit's execution model doesn't support.

A footer (`Dynasty Rookie Draft · build {APP_VERSION}`) shows the short git
SHA the running image was built from, read from a `GIT_SHA` environment
variable. This exists specifically to verify a NAS deployment actually
picked up a new image rather than silently continuing to run a stale one —
compare the footer against the commit that should be live. The `Dockerfile`
declares `ARG GIT_SHA=dev` / `ENV GIT_SHA=$GIT_SHA`; `docker-publish.yml`
passes `--build-arg GIT_SHA=${{ github.sha }}` so the footer matches the
same commit the image is tagged with in GHCR. Local `docker compose build`
(no build-arg passed) and plain `streamlit run` both fall back to `dev`,
which is itself a useful signal — if a NAS deployment ever showed `dev`, that
would mean the image wasn't actually built by CI. Verified directly: built
the image with `--build-arg GIT_SHA=abc1234` and confirmed the container's
environment carries it through.

### Refresh model

Streamlit reruns the whole script top-to-bottom on any widget interaction, so
a naive port would refetch on every unrelated click. `st.cache_data` is keyed
on an explicit `refresh_token` in `st.session_state`, bumped only by the
Refresh button or the Advanced-refresh "Apply" button — mirroring the CLI's
Enter-vs-`f` prompt. A button/checkbox's own value can't be the cache key
directly — it's only current on the exact run it was clicked, so a later
rerun (e.g. opening an expander) would see a stale/default value and get a
different key, silently missing cache and re-fetching for no reason.
`st.session_state.force_refresh_pending`/`force_scoring_pending` hold the
durable versions instead, set once per click and stable across reruns
(verified directly: patched `gather_state`/`player_scoring.get_multipliers`
with call counters and confirmed a plain rerun after a refresh click adds
no extra call).

Refresh re-pulls league/rosters/draft/picks (cheap, always live) plus
whatever's expired on `fantasycalc_api`/`bye_week_by_team`/`handcuff_map`'s
own TTL caches (12-24h, not tied to any button at all). The sidebar's
"Advanced refresh" expander splits the two remaining, genuinely different
concerns instead of bundling them behind one "force full refresh" button:

- **Players + market values (fast, default on)** — busts the on-disk 14MB
  players-dataset cache; a few seconds.
- **Recompute scoring multipliers (slow, 1-2 min, default off)** — forces
  `player_scoring`'s multiplier cache to re-import 3 seasons of weekly +
  play-by-play data. Deliberately its own checkbox, off by default, and
  gated behind a second "Apply advanced refresh" button — a routine
  refresh must never trigger this by accident mid-draft. This is also the
  in-app equivalent of running `python scripts/derive_position_multipliers.py`
  directly: a genuine prewarm option reachable from a phone if the user
  needs to warm the cache away from a terminal, not just ahead of time
  from the CLI.

Whenever byes, handcuffs, or the scoring multipliers silently fall back to
an empty/default result (a fetch failure, non-fatal by design — see
`docs/rookie-draft-big-board.md`), `gather_state` returns a
`data_warnings` list, surfaced as `st.warning`/CLI `WARNING:` lines — a
fallback used to be indistinguishable from "there's nothing to report."

Network/parsing errors surface as `st.error` with a retry hint instead of a
raw traceback — this needs to stay usable on a phone mid-draft, not just
technically correct. The CLI's own refresh loop mirrors this: it catches
`ValueError`/`TypeError` (a bad `--league-id`/typo'd `--username`) with a
clean message and exit, rather than a traceback or an infinite retry loop
that can't fix a bad input.

### Table presentation

Conventions applied consistently across every tab:

- **Human-readable column labels.** Every table's underlying DataFrame
  keeps its plain snake_case column names (so the rest of the codebase and
  its tests can keep referring to them normally) — only the *displayed*
  header is relabeled, via `st.dataframe`'s `column_config` and a small
  `cols()` helper (`streamlit_app.py`) that builds a `{column: st.column_config.Column(label, help=...)}`
  dict from `(key, label)`/`(key, label, help_text)` tuples. The special
  `"_index"` key relabels an index-as-column table's header too (e.g.
  Roster Needs' `pos` index shows as "Pos").
- **Decimal precision capped at 2 digits, display-only** (user-flagged
  2026-07-26). `st.dataframe` otherwise shows whatever precision the
  underlying float happens to carry — `adj_value`'s real-scoring multiplier
  routinely produces values like `7827.988709`. `cols()` now takes the
  DataFrame itself (dtypes only, never mutated) and checks each column with
  `pd.api.types.is_float_dtype` — a float column gets
  `st.column_config.NumberColumn(format="%.2f")` instead of the plain
  `Column` a string/int/bool column gets. Deliberately uniform across every
  float column, including ones that are always whole numbers in practice
  (`value`, `bye`, `big_board`'s `age`) rather than hand-picking a different
  precision per column — simpler and more consistent than the alternative,
  and every one of them is still correctly capped, not truncated (a real
  `.5` still rounds to `.50`, not `.49`). The CLI mirrors this via
  `to_string(float_format=...)` (see below) — same cap, same reasoning,
  different mechanism since the CLI has no per-column config to hook into.
- **Per-cell hover tooltips need custom HTML, not `st.dataframe`.**
  `column_config`'s `help` text only tooltips the column *header*, not
  individual cells. Roster Value Analysis's `status` icons each need their
  own detail (e.g. the actual `injury_status` word), so that one table
  renders as plain HTML (`show_status_table()`) instead of the shared
  `show_df()`/`cols()` approach — a deliberate, scoped exception, not the
  general pattern. Cell text is `html.escape()`d; the `status` column
  specifically wraps each icon in `<span title="...">` using
  `dynasty_core.player_status_details()`'s (icon, description) pairs.
  Since this table bypasses `cols()` entirely, its own cell-rendering loop
  separately applies the same 2-decimal cap to any `float` cell value.
- **Methodology text lives in a closed "How this works" expander**, not a
  bare `st.caption`, on every tab/section that has one (Draft Plan, Draft
  Board, Roster Value Analysis, Bye Week Impact, Weekly Gaps) — keeps the
  actual data above the fold on a phone instead of pushing it down on
  every refresh. Reformatted as bulleted term-definition lists rather than
  run-on prose (user feedback 2026-07-26) — `st.caption` renders Markdown,
  including lists, same as `st.markdown`.

## CLI (`rookie_draft.py`)

Thin wrapper: `print_report()` renders the same `gather_state()` output as
plain text, `main()` adds the interactive Enter/`f`/`q` refresh loop. Kept in
full parity with the web app deliberately — it's the tested fallback if
Docker or the NAS has a problem on draft day.

Every `DataFrame.to_string()` call passes `float_format=DISPLAY_FLOAT_FORMAT`
(`"{:.2f}".format`) — pandas' own default (`display.precision`, 6 digits)
otherwise prints raw values straight from the underlying computation (e.g.
`6703.189338`). Display-only: `float_format` is a formatting callback for
`to_string()`'s own output, not something that touches the DataFrame it's
called on, so nothing downstream (tests, further computation) is affected.
Same cap and reasoning as the web app's `cols()` (see above), applied
uniformly rather than per-column for the same reason.

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
  `:<short-sha>`; no `VERSION`-file semver, a deliberate simplification since
  this is a single-image personal tool, not a versioned release product
  (`Finance-Dashboards` does use a `VERSION` file — noted as an intentional
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
— a pre-draft review flagged that one transient hiccup used to be a hard
failure, and draft day means everyone hits these APIs at once. The CLI's
interactive loop also wraps `gather_state()` in a try/except now: a failure
prints an error and offers retry/quit instead of crashing the whole
session. Verified directly by simulating a `ConnectionError` on the first
`gather_state()` call and confirming the loop recovers on retry rather than
propagating.

`.github/workflows/ci.yml` (new) runs `tests/test_dynasty_core.py` on every
PR to `main` — the ranking/lineup logic didn't have any automated coverage
before this, flagged as a real gap given it's non-trivial custom logic
about to be trusted for real roster decisions. See
`docs/rookie-draft-big-board.md` for what's actually covered.

A connectivity failure now names which of the two upstream services
actually failed, instead of one generic "Couldn't reach Sleeper/FantasyCalc"
that's true either way — real on draft day, when everyone hits both
unauthenticated public APIs at once. `gather_state()` wraps its Sleeper
calls and its one FantasyCalc call in their own `try`/`except
requests.RequestException`, re-raising with a `"Couldn't reach Sleeper: ..."`
/ `"Couldn't reach FantasyCalc: ..."` prefix — same exception type, so the
CLI/Streamlit `except requests.RequestException` handlers didn't need to
change, just stop adding their own now-redundant generic prefix on top.
Covered by `tests/test_dynasty_core.py`'s `TestGatherStateConnectivityErrors`,
which monkeypatches `sleeper_api`/`fantasycalc_api` directly — the one place
in that test file testing.md's "mock only external services you do not
control" applies, since everything else there is pure logic over synthetic
data with no real boundary to mock.

Separately, the `{gsis_id: sleeper_id}` crosswalk `player_scoring.py` and
`dynasty_core.handcuff_map` each built from `nfl_data_py`'s ID table used
to be two copies of the same plain dict comprehension, which silently kept
whichever row came last on a collision — not a currently-live bug (a direct
check found 5 duplicate `gsis_id` rows in the real data, all agreeing on the
same `sleeper_id`), but invisible if a genuine conflict (two different
`sleeper_id`s for one `gsis_id`) ever occurred. Consolidated into one
function, `player_scoring.gsis_to_sleeper_crosswalk()`, which logs a warning
listing any `gsis_id` with more than one distinct `sleeper_id` before
falling back to the same last-row-wins behavior.

### Verified before merge (not just written and hoped)

- `docker compose build && up` locally: image builds, container reports
  healthy, serves on `:8501`.
- From inside the running container: `dynasty_core.gather_state(...)`
  succeeds (confirms outbound network access to Sleeper/FantasyCalc) and
  writes `players.json` to the mounted volume.
- Restarted the container and confirmed the cache file's timestamp didn't
  change — the named volume actually persists, not just configured to.
- After merge to `main`: confirmed `docker-publish.yml` ran to completion
  and the image landed in GHCR (the workflow's own push step would fail
  loudly if it hadn't).
