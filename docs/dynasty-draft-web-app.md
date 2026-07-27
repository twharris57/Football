# Dynasty Draft Web App — Streamlit + Docker

The web presentation layer for the logic in `docs/rookie-draft-big-board.md`.
Built so the draft tool is usable from a phone during the live draft instead
of requiring a terminal, and deployable to the user's Synology NAS.

## Streamlit app (`streamlit_app.py`)

Four tabs, all reading from one `dynasty_core.gather_state()` call per refresh:

1. **Draft Plan** — the round-by-round marginal-value simulation, backup
   alternates in expanders, weekly-gap impact.
2. **Lineup** — current optimal starters/bench.
3. **Draft Board** — the full rookie class, tiered, with draft attribution.
4. **Your Roster** — capacity, needs, value analysis, bye conflicts, weekly
   gaps, handcuffs.

An earlier "Strategy" tab (a single top-pick recommendation, computed by a
*different* algorithm than the round-by-round plan) was merged into Draft
Plan after the two turned out to disagree with each other on what to pick
next — two answers to the same question was a real bug, not a feature; there
is now exactly one ranking method, used everywhere.

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

Two conventions applied consistently across every tab:

- **Human-readable column labels.** Every table's underlying DataFrame
  keeps its plain snake_case column names (so the rest of the codebase and
  its tests can keep referring to them normally) — only the *displayed*
  header is relabeled, via `st.dataframe`'s `column_config` and a small
  `cols()` helper (`streamlit_app.py`) that builds a `{column: st.column_config.Column(label, help=...)}`
  dict from `(key, label)`/`(key, label, help_text)` tuples. The special
  `"_index"` key relabels an index-as-column table's header too (e.g.
  Roster Needs' `pos` index shows as "Pos").
- **Per-cell hover tooltips need custom HTML, not `st.dataframe`.**
  `column_config`'s `help` text only tooltips the column *header*, not
  individual cells. Roster Value Analysis's `status` icons each need their
  own detail (e.g. the actual `injury_status` word), so that one table
  renders as plain HTML (`show_status_table()`) instead of the shared
  `show_df()`/`cols()` approach — a deliberate, scoped exception, not the
  general pattern. Cell text is `html.escape()`d; the `status` column
  specifically wraps each icon in `<span title="...">` using
  `dynasty_core.player_status_details()`'s (icon, description) pairs.
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
