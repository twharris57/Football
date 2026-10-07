# Project Plan — Dynasty

Open work only. Delete an item when it's done — git has the history. Long-lived
decisions go in `docs/` or `valuation_principles.md`.

**IDs:** each item has a permanent `<PREFIX>-<n>` tag; never reuse or renumber.
Cross-reference by tag, never by position. Prefixes: `SC` scout, `RT` roster & trade,
`VA` valuation, `CQ` code quality, `DL` deferred. Last assigned: `NB-2`, `RT-33`,
`VA-9`, `CQ-14`, `DL-11`, `SC-21`.

## Current branch — fix before merge

Empty.

## Now — blocking

Nothing.

## Automated daily scout

Goal: run the team competitively without the user following football day to day. The
scout watches for opportunities and tells the user what to do: pickups, trade targets
and offers, taxi moves (stash or promote), and players to unload (drop or trade). Stay
quiet when nothing is worth acting on.

**Design:** three parts, with SQLite on the NAS as the single store.

- **Collector** (NAS, scheduled ~7:30pm): pulls Sleeper, FantasyCalc, and `nfl_data_py`
  into SQLite and runs the cheap structured diffs (tier 1). No AI.
- **API** (`/api` routes in the dynasty Streamlit app): token-protected. Reads: league
  state and tier-1 candidates, the trade block, recent runs and findings, and the collector's `collected_at`. Writes
  are append-only (`POST` run records and findings), validated by the existing strict
  schemas. Nothing updates or deletes.
- **Scout** (cloud `/schedule` routine, ~8pm): reads the API, researches only what was
  flagged (tier 2), applies materiality, notifies via `PushNotification`, and `POST`s
  its run record and findings. Needs only `curl`/stdlib Python, no packages.

The NAS is on the notify path, so the scout must notify when the API is unreachable or
`collected_at` is stale, then stop — never a silent night.

**Cloud → NAS calls work** (verified from a routine, curl and Python): HTTPS on 443 to a
subdomain of the NAS's DDNS host behind the DSM reverse proxy, with a wildcard cert
assigned only to that rule. The host goes on the environment's **Custom** allowlist; the
bearer token is a **network secret**, which the proxy attaches and the session never
sees. Egress IPs vary, so authenticate by token, not IP.

**Build order:** `SC-20` (skeleton) → `SC-1` → `SC-21` → `SC-3` → `SC-5` → `SC-6` →
`RT-21` → `SC-7` → `SC-8`/`SC-9` → `SC-10`.

- [ ] **SC-20: NAS API.** Serve `/api/*` from the dynasty app via Streamlit's `st.App`
  custom routes (Starlette, already installed), calling `trade_block_store` and
  `dynasty_core` directly. Start with `/api/health` and the trade block, then add
  endpoints as `SC-21`/`SC-6` need them. Bearer token from `football.secrets.env`; cap
  request bodies. Reuse `finding_schema.py`/`run_record_schema.py` for write validation.
  Retire the `scout-api` image and the `scout-data` branch path: `sync.py`, the
  `scout_data_files` mirror table, and their references in `CLAUDE.md`, compose, and CI.
  Deploy: a `fantasytools.` subdomain rule in the DSM reverse proxy → 8501 and the
  router's 443 forward (removed after the connectivity test). Deployment files change —
  flag the `nas-configs` re-sync in the PR.
- [ ] **SC-21: Collector.** Grow `daily_check.py`'s snapshot into a collector script that
  writes to SQLite: league state, pickup snapshots, `RT-21`'s log, and tier-1 candidates
  from existing gates. Stamps `collected_at`. Runs inside the dynasty container from
  Synology Task Scheduler (`docker exec`), which emails on failure. `nfl_data_py`'s
  1–2 min fetch is fine here.
- [ ] **SC-1: Scout cloud environment.** Custom allowlist with the API host, the token as
  a network secret, no setup script. Verify the research tools (web search/fetch) work
  under the Custom allowlist. If a package is ever needed: pip can't reach PyPI from
  the VM (`from versions: none`; `pypi.org` is on `NO_PROXY`), the setup script runs
  before the repo is cloned, and the VM runs Python 3.11.
- [ ] **SC-3: Scout research pass.** Tier 2 only: research what the collector flagged,
  existing candidate pools, or the trade block — never a blind sweep. Write findings in
  the finding schema (whose categories are still first guesses). Build `SC-8`'s
  corroboration in from the start.
- [ ] **SC-5: Materiality thresholds.** Deterministic lane runs in the collector and
  reuses existing gates (`free_agent_board()`'s `> 0`, `suggested_trades()`'s tolerance),
  inheriting the FAAB thin-sample caveat. A quantitative signal and a scout finding
  agreeing is its own higher-confidence category, not a blended score.
- [ ] **SC-6: Nightly scout routine.** Health/staleness check → read state → `SC-3` →
  materiality → `SC-7` → notify → `POST` the run record. Must distinguish "checked,
  nothing new" from "check failed." In season.
- [ ] **SC-7: Self-reflection.** Diff recent run records against `RT-21`'s transaction
  log; on a miss, open a deduped GitHub issue (never a commit/PR). If GitHub is
  unreachable, save the pending issue through the API. Blocked on `RT-21`.
- [ ] **SC-8: Prompt-injection defense.** The fixed-field finding schema is the
  structural half. Remaining: an independent corroboration search before writing any
  borderline or high-stakes finding.
- [ ] **SC-9: Season-aware cadence.** Fixed daily cron gated on Sleeper's
  `league["status"]`/`settings.leg`. Needed before summer 2027, not first release.
- [ ] **SC-10: Docs.** Write `docs/dynasty-daily-scout.md` as pieces land, including
  the three-part design and the cloud → NAS setup above. Confirm the `scout_data`
  volume is in NAS backups.

## Roster & trade tooling

**Not modeled, on purpose:** selling *starters* (a human judges that against a real
offer); pick ownership beyond next season (`FUTURE_PICK_YEARS_AHEAD = 1`).

- [ ] **RT-21: Sleeper transaction log.** `/league/{id}/transactions/{leg}` records
  every move leaguewide with timestamps — collected by `SC-21`, ground truth for
  `SC-7`, and a fix for the draft plan's "ambiguous drop" state. Verify live first: whether draft-day cuts are
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
- [ ] **CQ-14: Split the remaining 120+ line functions** — `multi_round_plan` (~186),
  `improve_incoming_offer` and `find_trade_offers` (~145 each), `render_plan_tab` (~128),
  `_render_manual_evaluator` (~119). Dense logic, so do each with targeted tests first.
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
- [ ] **DL-11:** login for the Streamlit UIs (e.g. `st.login`). Both are public with no
  auth, accepted as low value; note that the confidence-pool UI can edit saved picks,
  which the deadline lock submits.
