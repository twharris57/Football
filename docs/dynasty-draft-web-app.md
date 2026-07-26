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

### Refresh model

Streamlit reruns the whole script top-to-bottom on any widget interaction, so
a naive port would refetch on every unrelated click. `st.cache_data` is keyed
on an explicit `refresh_token` in `st.session_state`, bumped only by the
Refresh/Force-full-refresh buttons — mirroring the CLI's Enter-vs-`f` prompt.
Refresh re-pulls league/rosters/draft/picks (cheap, always live); Force full
refresh also busts the on-disk 14MB players-dataset cache.

Network/parsing errors surface as `st.error` with a retry hint instead of a
raw traceback — this needs to stay usable on a phone mid-draft, not just
technically correct.

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
- **Named volume** (`players_cache`) for the on-disk players-dataset cache,
  so it survives container restarts instead of re-downloading ~14MB every
  time — matches `docker_guidelines.md`'s "named volumes for data that
  should persist" directly.

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
