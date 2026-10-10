# Fantasy Tools Web App

Streamlit UI over `dynasty_core.gather_state()`, built to be usable from a phone during
a live draft. Methodology is in `dynasty-methodology.md`; caching in
`dynasty-data-model.md`.

## Tabs

| Tab | What it answers |
|---|---|
| Draft Plan | Round-by-round picks by marginal value, alternates, full candidate lookup |
| Lineup | Optimal lineup by dynasty value or this week's Sleeper projections |
| Draft Board | The whole rookie class, tiered, with who drafted whom |
| League | One row per team (value, biggest need, capacity, phase); pick trade values |
| Roster | One team in depth — Overview, Value & Handcuffs, Free Agents (+ FAAB guidance), Schedule |
| Trade Evaluator | Manual Trade (+ "Suggest an improvement"), Suggested Trades, Trade Block |
| Summary | Attention digest |

Summary moves to the front once the draft is complete.

- **Any team, one code path.** Per-roster functions take a generic roster;
  `team_roster_analysis()` bundles them. The Roster tab reuses the cached bundle for
  the user's team and computes others on demand (under a second).
- **The League tab avoids `team_roster_analysis()` per team** because its free-agent board
  is ~12× too expensive for a summary row. It uses the cheaper underlying signals.
- **Expensive searches sit behind a button or a selection:** the leaguewide trade scan,
  offer improvement, FAAB guidance for one candidate, and the full drop search for one
  alternate. Cached results are dropped when the state version or the selection changes.

## Refresh

Streamlit reruns the script on every click, so `load_state()` is `st.cache_data`-wrapped
(1h TTL) and keyed on a `token` that only changes when you refresh.

- **Refresh** sets `token` to the current timestamp. Before any click, it's the current
  minute.
- **The token parameter must not start with `_`.** `st.cache_data` leaves underscore-named
  arguments out of the cache key, so Refresh would silently stop working.
  `tests/test_streamlit_refresh_cache.py` guards this.
- **Advanced refresh** can bust the players/market caches (seconds) and, as a separate
  opt-in, recompute scoring multipliers (1–2 min). A routine refresh never does the
  slow one.
- **Nothing auto-refreshes.** The sidebar shows "Last refreshed," stamped inside the cached
  function. Refresh right before your pick.

## Errors and warnings

- Network failures name the service ("Couldn't reach Sleeper/FantasyCalc") and show
  `st.error` with a retry hint, not a traceback.
- Optional enrichments (byes, handcuffs, multipliers, bid history, projections) fall back
  without breaking the page and add a line to `data_warnings`, shown as `st.warning`.
- Both API clients retry GETs three times with backoff on connection errors, 429s, and 5xx.

## Tables

- `cols()` gives readable labels and 2-decimal floats; DataFrames keep snake_case.
- Roster Value Analysis renders HTML (`show_status_table()`), because Streamlit has no
  per-cell tooltips.
- Methodology text goes in a closed "How this works" expander. Shared terms go in the
  Glossary dialog (`tabs/components.py`).

## Version footer

`v{VERSION} · build {GIT_SHA}`. CI passes `GIT_SHA` as a build arg. If a NAS deploy shows
`dev`, the image wasn't built by CI.

## Docker

- `python:3.12-slim`, non-root (uid 1000), stdlib `urllib` health check (no curl).
- CI pushes `:latest`, `:<sha>`, and `:v<VERSION>` to GHCR; the NAS only pulls.
- Volumes: `nfl_data_cache` → `.cache/`, `dynasty_data` → trade block DB.
- Before shipping a Docker change: build, confirm healthy on `:8501`, run
  `gather_state()` inside the container, and restart to confirm the cache persists.
