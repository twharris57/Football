# Project Plan — Dynasty

Open work only. Delete an item when it's done — git has the history. Long-lived
decisions go in `docs/` or `valuation_principles.md`.

**IDs:** each item has a permanent `<PREFIX>-<n>` tag; never reuse or renumber.
Cross-reference by tag, never by position. Prefixes: `SC` scout, `RT` roster & trade,
`VA` valuation, `CQ` code quality, `DL` deferred. Last assigned: `NB-2`, `RT-33`,
`VA-9`, `CQ-13`, `DL-10`, `SC-18`.

## Current branch — fix before merge

Empty.

## Now — blocking

Nothing.

## Automated daily scout

Goal: catch opportunities (depth-chart bump, IR move freeing a free agent, trade
window) on nights the user can't check, and stay quiet otherwise.

**Design:** one nightly cloud `/schedule` routine gathers state, researches, applies
materiality, notifies via `PushNotification`, and commits its state to the `scout-data`
branch (its only memory). A NAS job mirrors that branch into SQLite for a future
dashboard; it's off the notify path. **The cloud sandbox can't reach the NAS inbound —
don't revisit an inbound design.**

**Build order:** `SC-3` → `SC-6` → `RT-21` → `SC-7` → `SC-8`/`SC-9` → `SC-10`.
`SC-15`'s NAS deploy and `SC-16`'s staleness banner wait for a scout dashboard.

- [ ] **SC-1: Cloud environment setup.** `daily_check.py` works; still needs the
  network allowlist set on claude.ai (`api.sleeper.app`, `api.fantasycalc.com`,
  `github.com`, `raw.githubusercontent.com`). `nfl_data_py` cold-fetches every run
  (~1–2 min) — decide whether to accept that or skip bye/scoring enrichment nightly.
- [ ] **SC-3: Scout research pass.** Tier 1: cheap daily diff of structured data
  (pickup snapshots, `RT-21`'s log). Tier 2: research only what tier 1, existing
  candidate pools, or the trade block flagged — never a blind sweep. Write findings in
  the finding schema (whose categories are still first guesses). Build `SC-8`'s
  corroboration in from the start. **Open question:** the trade block lives in NAS
  SQLite, which the cloud routine can't read — decide how it gets there.
- [ ] **SC-5: Materiality thresholds.** Deterministic lane reuses existing gates
  (`free_agent_board()`'s `> 0`, `suggested_trades()`'s tolerance) and inherits the FAAB
  thin-sample caveat. A quantitative signal and a scout finding agreeing is its own
  higher-confidence category, not a blended score. Build alongside `SC-3`/`SC-6`.
- [ ] **SC-6: Nightly orchestrator.** Wire `SC-1` → `SC-3` → materiality → `SC-7` →
  notify → commit + prune (`SC-16`), writing a run record each night. Must distinguish
  "checked, nothing new" from "check failed." 8pm local, in season.
- [ ] **SC-7: Self-reflection.** Diff recent run records against `RT-21`'s transaction
  log; on a miss, open a deduped GitHub issue (never a commit/PR). If GitHub is
  unreachable, write the pending issue to `scout-data`. Blocked on `RT-21`.
- [ ] **SC-8: Prompt-injection defense.** The fixed-field finding schema is the
  structural half. Remaining: an independent corroboration search before writing any
  borderline or high-stakes finding.
- [ ] **SC-9: Season-aware cadence.** Fixed daily cron gated on Sleeper's
  `league["status"]`/`settings.leg`. Needed before summer 2027, not first release.
- [ ] **SC-10: Docs.** Write `docs/dynasty-daily-scout.md` as pieces land.
- [ ] **SC-15: Deploy the NAS-side sync.** `sync.py` is built, not deployed. When a
  scout dashboard is started: GitHub PAT, Task Scheduler entry with failure alerts,
  confirm the `scout_data` volume is backed up.
- [ ] **SC-16: 30-day pruning + staleness signal.** Pruning ships in `SC-6` (keeps
  `scout-data` under GitHub's 1,000-entry listing cap); staleness banner waits for a UI.

## Roster & trade tooling

**Not modeled, on purpose:** selling *starters* (a human judges that against a real
offer); pick ownership beyond next season (`FUTURE_PICK_YEARS_AHEAD = 1`).

- [ ] **RT-21: Sleeper transaction log.** `/league/{id}/transactions/{leg}` records
  every move leaguewide with timestamps — ground truth for `SC-7`, and a fix for the
  draft plan's "ambiguous drop" state. Verify live first: whether draft-day cuts are
  always `type: "free_agent"`, and how `leg` buckets across a season.
- [ ] **RT-30: `PHASE_THRESHOLDS` now gates recommendations.** The ±0.3 cutoffs were
  tuned for a display label but now switch `need`, drop notes, and draft-plan reasoning.
  Preseason data had 6 of 12 teams within 0.2 of a boundary. Re-check once every team
  has games played, then choose: validate, widen, or add hysteresis (which needs
  persisted per-team state).
- [ ] **RT-16: Trade tiebreaker reads the partner's rebuild-only `need`.** A contending
  partner may want the opposite. Fix: pass the partner's phase and use
  `phase_aware_need_positions()`. Low severity — tiebreaker only.
- [ ] **RT-33: Young non-rookie depth can show as "sellable"**, though elsewhere the app holds
  low-value young players. Decide: extend the exclusion, or leave it to human judgment.
- [ ] **RT-32: Show trade-block status in Manual Trade / Suggested Trades results**
  (tag listed players, optionally scope a scan to them). Reuse the existing ranking.
- [ ] **RT-23: Position filter for Suggested Trades**, alongside the target filter.
- [ ] **RT-6: On-demand Scout lookup for one named player.** Likely cheap once `SC-3`
  exists; revisit then.
- [ ] **RT-7: Point differential in the power read.** Steadier than win/loss. Verify
  Sleeper's `fpts`/`_decimal` fields live, then decide how to blend with `win_pct`.
- [ ] **RT-8: Real taxi eligibility for veteran free agents.** Verify Sleeper's
  accrued-experience rule live, then set `taxi_eligible` per candidate.
- [ ] **RT-25: FAAB guidance from prior seasons** via `previous_league_id`. Must handle
  league membership churn and weight recent bids more.
- [ ] **RT-26: Draft Board year selector** once a second draft's data exists.

## Valuation & data accuracy

- [ ] **VA-1: KeepTradeCut as a second market source.** Its superflex rankings would
  also cross-check the QB VOR calibration. Sourcing KTC values is uninvestigated.
- [ ] **VA-2: Derive `BASELINE_SCORING["rec"]` from the real `ppr`** instead of
  hardcoding `1.0`. Harmless while the league stays full PPR.
- [ ] **VA-3: Automate `derive_position_multipliers.py`.** Needs a trigger (season
  rollover?) and a swing guard. Low value now that it's only a fallback.

## Code quality, tests & UX

- [ ] **CQ-13: "(+N more)" in the Summary tab goes nowhere.** Link the Roster tab for
  gaps/sellable/free agents; pickup alerts need a full-list view first. `SC-6`'s
  notifications will hit the same problem.
- [ ] **CQ-5: Give `pick_trade_values()` real `season`/`round`/`slot` columns** so
  consumers stop re-parsing the display label.
- [ ] **CQ-7: Share the pick-value lookup/sum** between `find_trade_offers()` and
  `improve_incoming_offer()` next time either is touched.
- [ ] **CQ-8: Handle `SIGTERM` in-process for graceful shutdown.** The convention may
  belong upstream in AgentConfig.

## Deferred / low priority

Revisit only if the underlying assumption changes.

- [ ] **DL-1:** handcuff proxy (depth rank 2) misfires in RB committees. Informational only.
- [ ] **DL-2:** `recommend_drop` could drop the candidate being evaluated. Vanishingly rare.
- [ ] **DL-3:** if no team has a valid weighted age, `power_score` goes all-`NaN`. Never seen.
- [ ] **DL-4:** `positional_strength_summary()` runs twice for the user's roster. Trivial cost.
- [ ] **DL-5:** move reusable "How this works" definitions into the Glossary.
- [ ] **DL-6:** team label can read "Bob (Bob)". Cosmetic.
- [ ] **DL-9:** non-fantasy positions are filtered per consumer, not at ingest. No live
  bug; consolidate if a new raw-`players` consumer appears.
- [ ] **DL-10:** auto-detect the trade block from Sleeper's web UI. Needs a private,
  authenticated endpoint — fragile. Only worth it if manual entry becomes a burden.
