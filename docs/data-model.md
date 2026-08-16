# Dynasty Data Model — Persistence & Freshness

How state actually flows through the dynasty tools today: what's cached
where, on what freshness policy, and which layer a new feature's data
should live in. Written up as part of `CQ-6` (`.claude/PROJECT_PLAN.md`),
prompted by a 2026-08-16 investigation into a "the app forgets recent picks"
bug on the Synology deployment — the real root cause turned out to be a
single mis-named Streamlit cache argument (see
`dynasty-draft-web-app.md`'s "Refresh model" section for that story), but
tracing it required reconstructing exactly this map, which didn't exist
anywhere as a single reference before now.

## The four persistence layers today

| Layer | Holds | Where | Freshness policy | Busted by |
|---|---|---|---|---|
| Streamlit process cache | The entire `gather_state()` output | In-process memory (`st.cache_data` on `load_state`, `streamlit_app.py`) | `ttl="1h"` backstop; otherwise keyed on exact args | A Refresh/Advanced-refresh click (changes `token`), or either force flag |
| 12h TTL disk cache | Sleeper's players reference dataset; FantasyCalc dynasty values | `CACHE_DIR` (`.cache/`, the Docker named volume) — `players.json`, `fantasycalc_values_{num_qbs}_{num_teams}_{ppr}.json` | Age-checked on every read (`mtime` vs. TTL) | TTL expiry, or Advanced refresh's `force_full_refresh` |
| No-TTL disk cache | Real-scoring multipliers (`player_scoring.py`) | `CACHE_DIR` — `scoring_multipliers.json` | Never auto-expires — historical data, changes only once a year | Only the Advanced-refresh "Recompute scoring multipliers" checkbox (`force_scoring_refresh`), or running `scripts/derive_position_multipliers.py` directly |
| Ad hoc JSON accumulator snapshots | Cross-refresh diff state: real draft-drop attribution (`draft_snapshots.py`), player team/depth-chart/status history (`pickup_snapshots.py`) | `CACHE_DIR` — `draft_snapshots_{draft_id}.json`, `pickup_snapshots_{league_id}_{season}.json` | No TTL concept at all, by design — the whole point is remembering across refreshes | Never "busted" — only ever merged/appended to, via `snapshot_io.py`'s shared load/write shell |

All four share one physical directory (`CACHE_DIR`, defined once in
`cache_dir.py` and re-exported through `dynasty_core/constants.py`), mounted
as a single Docker named volume (`nfl_data_cache`) in both
`docker-compose.deploy.yml` and `docker-compose.yml` — there is no real
database anywhere in this stack today, just five-ish independently-managed
JSON files sharing a folder.

## The conceptual split: import vs. cached-derived vs. cheap-derived vs. on-demand

This is the split the app already follows in practice, made explicit:

1. **Raw imported data** — league/rosters/draft/picks (Sleeper, no caching
   at all: cheap, always live, by design, per `streamlit_app.py`'s own
   module docstring), players (Sleeper, 12h), market values (FantasyCalc,
   12h). Pulled fresh at the top of every `gather_state()` call, subject
   only to their own layer's TTL above.
2. **Expensive derived data, genuinely needs real caching** — real-scoring
   multipliers only. A 1-2 minute synchronous `nfl_data_py` pull
   (`player_scoring._derive_multipliers`), which is why it gets its own
   no-TTL cache and its own separate opt-in trigger rather than living on
   the fast path.
3. **Cheap derived data, recomputed fresh every single refresh, no caching
   at all** — everything else `gather_state()` computes: the big board,
   marginal-value rankings, team power/timeline, replacement levels,
   Suggested Trades' Stage 1 candidate list, the draft plan. This is
   already, in practice, "a deterministic function of the current raw
   data" — confirmed this session: nothing in this bucket has its own
   cache, and the whole `gather_state()` call (raw pulls plus all of this)
   completes in ~4s (`.claude/PROJECT_PLAN.md`'s `DL-4`). The user-facing
   goal of "UI calcs that are fast and deterministic given the current
   state" is *already true* for this bucket — the bug that prompted this
   doc was never about this layer being slow or nondeterministic, it was
   about the process cache above it silently serving an old fetch.
4. **Accumulated cross-refresh state** — `draft_snapshots.py`/
   `pickup_snapshots.py`. Structurally different from the other three: not
   re-derivable from a single snapshot, since the whole point is comparing
   against what was true on a *previous* refresh (which real draft-pick
   pairs with which real drop; which player just changed teams). Genuinely
   needs persistence, not just caching.
5. **On-demand, UI-triggered, session-scoped results** — as of this
   session, exactly one exists: Suggested Trades' leaguewide offer scan
   (`trade_tab.py`'s `_render_leaguewide_scan`, stored in
   `st.session_state["suggested_trades_results"]`). Every other tab
   recomputes everything fresh on every rerun with no session_state stash
   (confirmed by an explicit search of `tabs/*.py` this session) — this
   bucket is small today but is exactly where `RT-14` (evaluate/improve an
   incoming offer) and any future on-demand search feature will land.

## The versioned on-demand-result pattern

Bucket 5 above has a real failure mode distinct from buckets 1-4: a result
computed on demand and stashed in `st.session_state` has no natural
connection to *which* fetch of bucket-1/2/3 data it was computed against.
`RT-24` (`.claude/PROJECT_PLAN.md`) was exactly this: a Suggested Trades scan
could silently keep showing offers computed against an earlier roster/market
snapshot after a real refresh moved the world on.

Fixed (this branch) by giving bucket-1's cached state a cheap identity:
`load_state()` now stamps `state["version"] = token` — `token` is already a
fresh, real timestamp on every genuine re-fetch (see `dynasty-draft-web-app.md`),
so it's already exactly the right shape for this with no new mechanism
needed. Any bucket-5 consumer stores its result as
`{"state_version": state["version"], "results": ...}` instead of a bare
value, and checks the stamp on read — a mismatch means "this was computed
against a state that no longer exists," and the stale entry is dropped
rather than silently displayed. `trade_tab.py`'s `_render_leaguewide_scan` is
the reference implementation; any future bucket-5 feature (`RT-14`, a
free-agent search result, etc.) should follow the same shape rather than
inventing its own staleness convention.

## Why not a real database (SQLite or otherwise) right now

Worth stating explicitly since it was an open question going into this
review, not an oversight: this app is a single Python process, run by one
user, with no concurrent writers, modest data volumes (the largest file,
`players.json`, is ~14MB and already isn't loaded into anything more
structured than a dict), and no query need beyond simple key lookups —
nothing here currently benefits from indexes, joins, or transactions. A real
embedded DB would add a dependency, a migration story, and connection
lifecycle management with no corresponding win yet. The JSON-file approach
already in use for buckets 2-4 is the simpler correct tool for this scale
(`code_conventions.md`'s "prefer the simplest correct solution").

**Revisit this if:** the app ever needs genuine cross-season historical
queries (not just "the current draft's snapshot"), multiple concurrent
writers (a second real user, not just multiple browser tabs), or the
accumulator files in bucket 4 grow complex enough to need real joins between
them — none of which is true today.

## Open follow-up work (not attempted in this pass)

Logged as `CQ-6` in `.claude/PROJECT_PLAN.md`, which this doc supersedes as
the "what's the current state" reference (the backlog item tracks what's
still open, not a duplicate description):

- **Consolidate `draft_snapshots.py`/`pickup_snapshots.py`** into one
  schematized store instead of two structurally-similar-but-independent
  JSON files sharing only a load/write shell.
- **`DL-9`**: move non-fantasy-position filtering from "every consumer
  checks it" to a single ingest-time filter.
- **`CQ-5`**: give draft-pick identity real structured fields at the point
  `pick_trade_values()` produces them, instead of a display string
  re-parsed downstream.
