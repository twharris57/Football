# Dynasty Draft Web App — Streamlit + Docker

The web presentation layer for the logic in `docs/rookie-draft-big-board.md`.
Built so the draft tool is usable from a phone during the live draft instead
of requiring a terminal, and deployable to the user's Synology NAS.

## Streamlit app (`streamlit_app.py`)

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
   picks) between two selected teams, evaluated for both sides. Its own
   tab rather than another Roster section — it's inherently two-team, not
   the "pick a team, see everything about them" shape every Roster section
   shares.

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

The "Roster needs" table has two columns from `positional_strength_summary`
(see `docs/rookie-draft-big-board.md` for the full methodology) alongside
the young-core `Need` flag: `VOR` (value-over-replacement) and `Weak`
(`VOR <= 0`) — a position whose actual starters aren't worth what's freely
available anywhere else in the league. `team_roster_analysis()` joins this
onto the existing `roster_needs` table rather than adding a separate one,
since they're two answers about the same position a user would want side by
side. The "How this works" expander explains why they can disagree (plenty
of bodies but no real value, or the reverse) and why VOR compares against
the whole league rather than the rest of the team's own roster (the latter
would let one elite player elsewhere distort every other position's
apparent strength). Works through the team selector above unchanged:
`replacement_level` (the league-wide baseline) is computed once per refresh
in `gather_state` and passed into every `team_roster_analysis()` call,
including the on-demand ones for other teams.

### Team timeline

A "Team timeline" section sits above Roster capacity, for whichever team
the selector above has picked — the continuous power/timeline read
(`team_power_timeline_scores()`, see `docs/rookie-draft-big-board.md` for
the full methodology). Unlike the VOR/Weak columns above, this isn't
computed per-team on demand: every team's row is needed together for the
z-scoring itself, so `gather_state` computes the whole league's table once
and the UI just looks up
`state["team_power_timeline"].loc[selected_roster_id]`. Shown as an
`st.metric` (phase label + the underlying continuous score) plus a caption
breaking out the three component signals (VOR, weighted age, win %), so the
*why* behind the label is always visible. The CLI mirrors this with a plain
`--- Team timeline ---` line for the user's own team.

The `st.metric` value shows `rank`/`league_size` (e.g. "3 of 12") rather
than the raw score — a plain rank reads better cold than a z-score, with
the raw score and its 0/± meaning one hover away via the metric's `help=`
tooltip. Pre-season, the win % caption reads "no games played yet" instead
of a flat 50% for every team (`games_played == 0`, exposed in the same
table) — the raw number is real math (a neutral default contributing zero
variance) but misleading as a literal win rate before any games exist.

A "❓ Glossary" button next to the page title opens an `st.dialog` (module
constant `GLOSSARY` in `streamlit_app.py`) defining VOR, power score, and
adj. value — one reachable place for the terms this section and Roster
needs both use.

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

Not folded into the Roster tab like the sections above — those are all
"pick a team, see everything about them"; a trade is inherently two teams
plus a hypothetical exchange, so it gets its own tab with its own second
team selector ("Trade partner"), independent of the Roster tab's selector.
Four `st.multiselect` widgets (players/picks given up, players/picks
received), built from `state["rosters_by_id"]` and `state["pick_trade_values"]`
(filtered by `owner_roster_id`) — no new data pulled, everything already in
`state`. Recomputes reactively on every selection change (cheap — one
`season_average_starter_value` call per side) rather than needing an
explicit "Evaluate" button. Calls `dynasty_core.evaluate_trade()` twice,
once per side of the identical trade (the second call swaps the roster and
the two asset lists) — the "both sides" requirement falls out of the
function's own symmetry, not a second code path. A pick with no resolvable
`value` is called out in a caption rather than silently contributing
nothing.

The "Lineup value" `st.metric` shows `lineup_delta_after_drops` (the real
number once any forced cuts are applied) rather than the raw `lineup_delta`
whenever `recommended_drops` is non-empty — the raw number stays one hover
away via the metric's `help=` tooltip, same "don't hide the simpler number,
just don't lead with it when it's misleading" pattern the Team timeline
metric already uses for its raw z-score. An `st.warning` lists each
recommended cut by name/position, tagging any that's an actual current
starter (not just bench depth) rather than leaving that distinction only
visible in the underlying data.

### Player projection lookup

Each round's "Backup options" table only shows the top
`MAX_DISPLAYED_ALTERNATES` (2) alternates by default. `dynasty_core.
rank_by_marginal_value` already scores *every* available candidate before
sorting and slicing to the displayed few, so exposing the rest costs
nothing extra — `top_n` is `len(candidate_ids)` for upcoming rounds, and
the full ranked list is returned as `all_candidates_by_pick` alongside the
existing `alternates_by_pick`. Each round's expander gets a `st.selectbox`
built from that full list (sorted best-first), showing
`Name (POS) — marginal value` per option. Deliberately skips
`alternate_gap_note` for the full list — fine for 2 backups, not worth a
per-candidate weekly-gap comparison for a ~200-player pool most of which
nobody will ever look up. Web-only — the CLI has no interactive selectbox
equivalent, so its `alternates_by_pick` table output is unchanged.

The displayed marginal value for the top alternates comes from the cheap
`recommend_drop()` heuristic every candidate was scored with during ranking
(lowest-value bench player, full stop) — accurate enough to sort ~227
candidates quickly, but not a real per-candidate answer to "what should I
actually drop for *this* player." Once a candidate is selected from the
full list, the app instead calls `dynasty_core.best_position_relevant_drop()`
fresh (using that round's roster snapshot from `hypothetical_ids_by_pick`)
— a real search, restricted to players who share a slot type with the
*specific* selected candidate (own position, plus FLEX/SUPER_FLEX-eligible
positions if the league's `roster_positions` actually has those slots and
the candidate qualifies), over every resulting season-average marginal
value, not just whichever player has the lowest raw `adj_value`. In this
league SUPER_FLEX covers all four fantasy positions, so that restriction is
effectively "any rostered skill player" — a correct reflection of the real
slot structure. It's deliberately only computed on-demand for the one
selected candidate, not precomputed for all ~227 — evaluating every drop
option for every candidate during the main ranking pass would multiply that
pass's cost by the size of the search pool.

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
keyed on an explicit `refresh_token` in `st.session_state`, bumped only by
the Refresh button or the Advanced-refresh "Apply" button — mirroring the
CLI's Enter-vs-`f` prompt. A button/checkbox's own value can't be the cache
key directly — it's only current on the exact run it was clicked, so a
later rerun (e.g. opening an expander) would see a stale/default value and
get a different key, silently missing cache and re-fetching for no reason.
`st.session_state.force_refresh_pending`/`force_scoring_pending` hold the
durable versions instead, set once per click and stable across reruns.

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
`tests/test_dynasty_core.py`'s `TestGatherStateConnectivityErrors`, which
monkeypatches `sleeper_api`/`fantasycalc_api` directly — the one place in
that test file `testing.md`'s "mock only external services you do not
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

- **Human-readable column labels.** Every table's underlying DataFrame
  keeps its plain snake_case column names (so the rest of the codebase and
  its tests can keep referring to them normally) — only the *displayed*
  header is relabeled, via `st.dataframe`'s `column_config` and a small
  `cols()` helper (`streamlit_app.py`) that builds a
  `{column: st.column_config.Column(label, help=...)}` dict from
  `(key, label)`/`(key, label, help_text)` tuples. The special `"_index"`
  key relabels an index-as-column table's header too (e.g. Roster Needs'
  `pos` index shows as "Pos").
- **Decimal precision capped at 2 digits, display-only.** `st.dataframe`
  otherwise shows whatever precision the underlying float happens to carry
  (`adj_value`'s real-scoring multiplier routinely produces values like
  `7827.988709`). `cols()` takes the DataFrame itself (dtypes only, never
  mutated) and checks each column with `pd.api.types.is_float_dtype` — a
  float column gets `st.column_config.NumberColumn(format="%.2f")` instead
  of the plain `Column` a string/int/bool column gets, uniformly across
  every float column rather than a hand-picked precision per column. The
  CLI mirrors this via `to_string(float_format=...)` (see below) — same
  cap, different mechanism since the CLI has no per-column config to hook
  into.
- **Per-cell hover tooltips need custom HTML, not `st.dataframe`.**
  `column_config`'s `help` text only tooltips the column *header*, not
  individual cells. Roster Value Analysis's `status` icons each need their
  own detail (e.g. the actual `injury_status` word), so that one table
  renders as plain HTML (`show_status_table()`) instead of the shared
  `show_df()`/`cols()` approach — a deliberate, scoped exception. Cell text
  is `html.escape()`d; the `status` column wraps each icon in
  `<span title="...">` using `dynasty_core.player_status_details()`'s
  (icon, description) pairs. Since this table bypasses `cols()` entirely,
  its own cell-rendering loop separately applies the same 2-decimal cap to
  any `float` cell value.
- **Methodology text lives in a closed "How this works" expander**, not a
  bare `st.caption`, on every tab/section that has one — keeps the actual
  data above the fold on a phone instead of pushing it down on every
  refresh. Bulleted term-definition lists rather than run-on prose —
  `st.caption` renders Markdown, including lists, same as `st.markdown`.

## CLI (`rookie_draft.py`)

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

`.github/workflows/ci.yml` runs `tests/test_dynasty_core.py` and
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
