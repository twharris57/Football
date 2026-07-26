# Project Plan

Tracks what's actively being worked on, what's queued up next, and longer-range
ideas for this project. When a task is completed, write it up as a design doc
in `docs/` (what was built and why, key decisions) and remove it from this file.

## Active

- **Rookie draft big board** (branch: `feature/rookie-draft-strategy`) — pull
  the user's Sleeper dynasty league (rosters, draft picks, league settings) and
  produce a tiered rookie big board cross-referenced against roster needs.
  Blocked on: Sleeper league ID from the user.

## Next

- Nothing queued yet — depends on how the rookie draft big board lands.

## Future Ideas

- **Trade targets & sells** — given the rebuild strategy, flag which of the
  user's veterans are sellable for picks, and which other teams' picks/young
  players might be realistically available.
- **League-wide power/timeline read** — place every team in the league on a
  rebuild-vs-contend spectrum, to identify good trade partners (contenders who
  overpay for immediate help, rebuilders who overpay for future assets).

## Context

- Dynasty league (keep all players year to year; rookies only enter via the
  rookie draft).
- User's strategy since year one: accumulate young talent, accept being
  near the bottom of the league short-term, aiming to be competitive within
  ~2-3 years.
