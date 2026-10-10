# Project Plan — Confidence Pool

Open work only. Delete an item when it's done — git has the history. Long-lived
decisions go in `docs/` or `confidence_pool_principles.md`.

**IDs:** permanent `CP-<n>` tags; never reuse or renumber. Last assigned: `CP-35`.

## Current branch — fix before merge

Branch `feature/rename-legionpool-fantasytools`, opened early; implementation waits until
the NAS hostname setup is finished.

- [ ] **Rename "confidence pool" to "Legion pool"** to match its public hostname
  (`legionpool.`). Paired with the dynasty → "fantasy tools" rename (see the dynasty
  plan). Agree on scope first: UI titles, compose service and image names, `VERSION` tag
  prefixes, and whether directories/modules move. New image names change the deploy
  reference, so `nas-configs` needs a re-sync.

## Now — blocking

Nothing.

## Backlog

- [ ] **CP-3: Season standings.** Sum per-week `score_picks()` results (algorithm vs.
  actual) across a season. Wait until there's real multi-week data.
- [ ] **CP-12: Better de-vig and a backtest.** Proportional de-vig distorts extreme
  favorites (beyond ±300); consider Shin's method and consensus/closing lines. Backtest
  against last season's real picks first (needs `CP-3`). Also add a deterministic
  tiebreaker to `rank_games`'s sort.
- [ ] **CP-30: Import the pool's score sheet** (PDF) to fill `reported_score`
  automatically.
- [ ] **CP-5: Pick-history API** (small FastAPI over the same SQLite) once a second
  consumer exists.
- [ ] **CP-6: More signals** (injuries, weather, sentiment) if odds alone stop being
  enough. Low priority — odds alone placed 7th of 100+ last season.
