# Project Plan

Grouped by theme; within each group, items are ordered by priority (most
important first). When a task is completed, remove its entry from this list
immediately — the commit/PR that closed it is the historical record (the
same principle the "Current branch — fix before merge" section already
applies, generalized to every item here). A durable design decision or
methodology worth keeping belongs in `CLAUDE.md`, `docs/`, or
`.claude/conventions/valuation_principles.md`, not in a completed item's
write-up here — this file is only what's left to do.

**Item IDs**: every open item carries a permanent `<SECTION>-<n>` tag in its
own heading (`NB` = Now — blocking, `RT` = Roster & trade tooling, `VA` =
Valuation & data accuracy, `CQ` = Code quality/tests/UX, `DL` = Deferred/low
priority, `SC` = Automated daily scout) — e.g. `RT-3`. Assigned once, in document order, and never reused
or renumbered, even after the item it names is completed and its entry
deleted — matching how `VA`'s items were already informally lettered A-E
before this convention was written down (`A`/`B`/`E` are done and gone; `D`
survives as `VA-1`). Cross-reference other items by this tag (`see RT-3`),
never by list position (`item 2`) — a positional reference silently points
at the wrong item the moment anything above it is inserted, reordered, or
removed. A new item gets the next unused number for its section's prefix,
appended wherever priority order actually puts it in the list — position and
ID are independent. Since a completed item's entry is deleted rather than
archived, the next-unused number per prefix can't be found by scanning the
file once nothing with that prefix remains — it's tracked explicitly in the
**ID tracker** below instead; bump the matching entry there the moment a new
item is filed, regardless of whether the file currently shows any item with
that prefix. Each item is a plain bullet (`- [ ]`), never a numbered list
entry — a numeric list marker is exactly the kind of position-dependent
detail this convention exists to avoid; the bold `<SECTION>-<n>:` lead-in is
the only identifier that matters, and it never needs renumbering when an
item above it is added or removed. The ephemeral "Current branch — fix
before merge" section is exempt from ID tagging (cleared on every merge, so
nothing outlives it to cross-reference) but still uses plain bullets.

**ID tracker** (last number assigned per prefix — bump this the moment a new
item is filed, whether or not any item with that prefix still appears
below): `NB-2`, `RT-31`, `VA-9`, `CQ-13`, `DL-9`, `SC-14`.

## Short list — actively prioritized right now

A small, hand-curated pointer into the backlog below — not a duplicate of
any item's content, just which `<SECTION>-<n>` tags are getting real
attention right now and why, so that's visible without reading the whole
file. Keep each tier to a handful of items; if either grows past ~5-6,
it's stopped being a "short" list — thin it back out to what's actually
active. Remove an item once it's done (its own full entry gets removed
too, per the convention above), don't let this become a history log.

**Initial-release build order** (user-set 2026-09-03; see "Automated
daily scout" below for each item's full description) — ordered so each
step only depends on ones before it:

0. **`SC-13`/`SC-14` — assumption validation, before any real build work**
   (added 2026-09-03; see each item's own entry below). These aren't
   ordinary backlog items — they're cheap checks that can invalidate or
   reshape the architecture everything below assumes, so they come before
   step 1, not folded into the numbered sequence:
   - `SC-13` — confirm the Claude GitHub App actually has repo access
     (clone *and* issue-write) for cloud routines against this repo.
   - `SC-14` — confirm the cloud routine can reach the NAS-deployed store
     from outside (spot-checked 2026-09-03, looks promising, needs a real
     outside-in confirmation), and resolve where `SC-1`'s script actually
     executes.
1. `SC-12` — POC: confirm a `/schedule` cloud routine can actually push a
   phone notification, and whether a run notifies automatically or only
   when the agent sends one. Cheap and independent of everything else;
   the whole feature is worthless if this doesn't pan out, so prove it
   right after `SC-13`/`SC-14`.
2. `SC-1` — headless `gather_state()` entrypoint.
3. `SC-2` — SQLite store + templated finding schema, with a real
   backup-covered volume mount.
4. `SC-11` — authenticated API endpoints so the cloud routine can
   actually reach `SC-2`'s store, plus the real outside-in reachability
   check `SC-14` only spot-checked.
5. `SC-8` — templated-storage-plus-double-check prompt-injection defense
   (needed before `SC-3` writes anything real to the store).
6. `SC-3` — Claude Scout research pass, bounded scope.
7. `SC-4` — dedup log, extended to trades/scout findings.
8. `RT-21` — transaction log (needed by `SC-7`; can build in parallel with
   `SC-3`/`SC-4`/`SC-5` as long as it lands before `SC-7`).
9. `SC-5` — materiality thresholds, quant/qual signals kept distinct.
10. `SC-7` — self-reflection pass, opens a GitHub issue on a miss.
11. `SC-6` — the nightly cloud routine that ties it all together.

Target: once `SC-13`/`SC-14` (validated), `SC-1`–`SC-8`, `SC-11`, `SC-12`
land, schedule the routine for 8pm local (user-confirmed 2026-09-03),
running a fixed in-season cadence.

**First buildable slice — the concrete next step once this PR merges
(user-directed 2026-09-03; planning only until then, no build/deploy
work starts on this before merge):** a minimal, real proof of concept
combining `SC-11`/`SC-12`/`SC-13`/`SC-14` into one small, end-to-end
test rather than each item's full scope:
1. Build one simple, authenticated API endpoint on the NAS-deployed
   dynasty app (a `SC-11` slice — a health/ping check, not real
   findings data yet) and deploy it through the existing CI/CD path.
2. Create a `/schedule` cloud routine that, once that's deployed, calls
   the endpoint and pushes a phone notification reporting whether it
   worked (`SC-12`/`SC-14`'s real outside-in confirmation, from the
   cloud sandbox specifically, not just the same-network spot check
   already done).
3. In the same POC, deliberately test `SC-13`'s dual-path design (see
   its own entry): have the routine attempt something GitHub-side, and
   confirm the durable-queue fallback actually gets flushed by the next
   local Claude Code session when the direct path is unavailable.
The point of bundling these into one slice rather than building each
item's full scope first is exactly the user's stated goal: prove the
whole pipeline works regardless of whether the desktop is up and
reachable, before investing further build time on top of it.

**Explicitly not required for initial release** (both still tracked
below, neither blocks the list above): `SC-9` (season-aware
ramp-up/throttle — needed before next year's rookie draft, not before
first ship) and `SC-10` (docs get written incrementally alongside each
item above; only the *final consolidated* pass waits until everything's
in).

**Nice to have (no deadline, worth doing when there's room):**

Empty right now — `RT-4` shipped 2026-08-29 (PR #67), `DL-7`/`DL-8`
shipped 2026-08-29 (PR #66).

## Current branch — fix before merge

Findings from reviewing the *active* branch's own not-yet-merged work —
kept separate from the thematic backlog below so "fix this before the PR
merges" is never mixed in with "someday" work. Ephemeral by design: cleared
out when the branch merges, not carried forward as history (the merged PR's
description is the historical record). A finding that gets explicitly
deferred rather than fixed moves down into the appropriate thematic section
below as a normal backlog item, same as any other deferred work.

Empty right now — cleared after PR #66 and PR #67 both merged
(2026-08-29/30). PR #67's finding (stale "phase is display-only" comments
in `power_timeline.py`/`roster_tab.py`) and PR #66's finding (DL-8 Phase
2's orphan-delete safety window being call-count-based rather than
wall-clock) were both fixed directly on their branches before merge; PR
#67's deferred methodology question (whether `PHASE_THRESHOLDS`'
calibration still holds up now that something acts on it) lives on as
`RT-30` below.

## Now — blocking

Empty right now — nothing blocking.

## Automated daily scout

Motivation (user-flagged 2026-09-03): keeping up with the NFL closely
enough to catch every real dynasty opportunity — a depth-chart bump, an
IR move that opens a value-add free agent, a trade window worth acting on
— takes being fully engaged daily, which isn't realistic every day. This
feature closes that gap: the app checks every day on its own and only
interrupts the user when something is actually worth acting on.

**Architecture (user-clarified 2026-09-03).** Two distinct scheduled
components, not one monolithic job:
- **Claude Scout** (`SC-3`) runs routine research queries (news, injury
  detail, depth-chart/trade-buzz context beyond Sleeper's structured
  fields — this is the "Claude Scout" `RT-6` speculated about, now
  confirmed and generalized from a single-player on-demand lookup to a
  scheduled pass) and writes templated findings into a persisted store
  (`SC-2`). Deliberately *not* a blind sweep of the entire player
  universe — see `SC-3`'s own entry below for the bounded-scope design
  (user-directed 2026-09-03).
- **The nightly `/schedule` cloud routine** (`SC-6`) is the reviewer: it
  runs the deterministic Sleeper/FantasyCalc-based checks (pickup alerts,
  suggested trades) directly, reads whatever Scout has stored since the
  last check via `SC-11`'s API, runs self-reflection (`SC-7`), and pushes
  a phone notification only when something clears the materiality bar
  (`SC-5`) and isn't already-reported (`SC-4`). A quiet night — nothing
  new, or nothing beyond what was already surfaced the day before — stays
  silent.

Cross-checked against the sibling `Finance-Dashboards` repo's "Claude
scout" (2026-09-03) on the assumption it might be a directly portable
pattern — it isn't: that repo uses APScheduler inside a long-running
Docker container, calling the raw Anthropic API directly, writing to a
DuckDB health table, and surfacing results passively as a UI status badge
(no push notifications, no Claude Code cloud routine at all). Its de-dup
pattern (a persisted per-day status log checked before acting, distinct
"checked/found nothing" vs. "failed" states, already-reported content fed
back into the prompt so it isn't re-flagged) is the one piece directly
worth reusing — see `SC-4`/`SC-6` below — but the scheduling/execution
model itself is being designed fresh for this repo.

**Persistence and reachability (user-decided 2026-09-03; spot-checked
same day).** SQLite is the confirmed store — already proven in-repo via
`confidence_pool/store.py`, and the natural fit for `SC-7`'s historical
querying. It lives with the NAS-deployed app, not inside the cloud
routine's own ephemeral checkout (a `/schedule` routine explicitly
"cannot access local files, local services" per the schedule skill's own
docs), so two things have to be true for this to actually work, filed as
their own items below rather than left implicit: the on-disk file needs
a real volume mount so it's covered by the NAS's existing backup scripts
the same way `docker-compose.deploy.yml`'s `confidence_pool_data` volume
already is (`SC-2`), and the cloud routine needs a network path — read
and write — to reach it, since direct file access isn't an option
(`SC-11`). `SC-2` and `SC-11` are a matched pair; neither is complete
without the other. This whole premise was unconfirmed when first
written — `nas-configs` (this repo's NAS deployment owner) has no reverse
proxy, tunnel, or other public-exposure setup for any stack, which read
as a real risk the NAS might not be reachable from outside at all. A
same-day spot check resolved it more favorably than that read suggested:
`twharris.synology.me` resolves to a real public IP against a public DNS
resolver (not a LAN address), and both `:8501` (dynasty) and `:8502`
(confidence-pool) return HTTP 200, consistent with port forwarding
actually being configured rather than LAN-only access — and the user
confirms routinely pulling both apps up on their phone while off-prem,
which is direct, real-world confirmation of external reachability, not
just a same-network artifact of the spot check. So the NAS being
reachable at all is no longer the open question; what's left for `SC-14`
is narrower and more mechanical — confirming a *cloud sandbox's* egress
path specifically can reach it too (a different network path than a
phone's, even if both ultimately hit the same forwarded port) and
resolving where `SC-1`'s script actually executes. Also surfaced by the
same spot check, not a new decision: both ports are currently plain HTTP
with no TLS, and Streamlit has no built-in auth — fine for the existing
read-only dashboards' current stakes, but `SC-11`'s API cannot piggyback
on that same unauthenticated exposure and needs real auth added
explicitly, which its own entry already anticipates.

Existing work this depends on or should be prioritized alongside (all
added to the short list above, 2026-09-03):
- **`RT-21`** (transaction log) — promoted from "revisit next year" to a
  real dependency; see its own entry above for why.
- **`RT-9`/`RT-19`/`RT-20`** (already shipped) — `pickup_snapshots.py`'s
  load/diff/persist shape (via `snapshot_io.py`'s shared shell) is the
  direct template `SC-4` extends; no new persistence design needed there,
  just more categories.
- **`RT-6`** — see its own entry above; effectively superseded in scope by
  `SC-3` for the routine case, kept open only for the narrower on-demand
  single-player trigger.
- **`RT-10`/`RT-28`** (FAAB comparable-sample thinness) — `SC-5`'s
  materiality gate needs to inherit this low-confidence-on-thin-sample
  caveat explicitly for any FAAB-bid-guidance finding, not treat it as
  just another threshold.

- [ ] **SC-1: Headless entrypoint for `gather_state()` outside Streamlit**
  — `gather_state()` is currently only ever called from
  `streamlit_app.py`'s cached `load_state()`. Add a plain script (e.g.
  `dynasty/scripts/daily_check.py`) that calls it directly (league ID
  from existing env/config, no `st.*` dependency) and returns a
  structured result. The foundation both `SC-3` and `SC-6` build on. Add
  pytest coverage alongside — nothing about this entrypoint needs a
  Streamlit workaround, so it should be as testable as everything else in
  `dynasty_core/`.
- [ ] **SC-2: Persistent research store for Claude Scout findings —
  SQLite, confirmed (user-decided 2026-09-03)** — a place for `SC-3`'s
  research output to land so `SC-6` can review it without re-running the
  research itself, and for `SC-4`/`SC-7` to query historically. Settled:
  SQLite, following `confidence_pool/store.py`'s already-established
  pattern in this same repo (versioned migrations under `db_schema/`) —
  this is dynasty's first real persistence beyond file-cached snapshots,
  so it's the migration-runner *shape* that gets reused, not shared code,
  per `CLAUDE.md`'s Architecture section (`dynasty`/`confidence_pool`
  still share none). Two things this item has to land together, not
  defer to later cleanup:
  - **A templated finding schema, not free text** — fixed columns
    (player_id, category, one-line summary, source, confidence,
    observed_at) rather than a blob of raw scraped text. This is also
    half of `SC-8`'s prompt-injection defense, not a separate concern
    from it — the schema itself is what keeps a later consumer (`SC-6`, a
    notification) from ever rendering or reasoning over raw untrusted
    text.
  - **A real volume mount for the SQLite file**, wired into the NAS's
    existing backup coverage the same way `docker-compose.deploy.yml`'s
    `confidence_pool_data` volume already is — needs to happen when the
    store is built, not retrofitted after data already exists in an
    unmounted container layer.
  Reachability from the cloud routine is `SC-11`, not this item — see the
  "Persistence and reachability" note above for why they're split. Needs
  pytest coverage on the schema/migrations and read/write paths, the same
  shape as `tests/confidence_pool/`'s store round-trip tests.
- [ ] **SC-3: Claude Scout — routine research pass, bounded scope (not a
  full free-agent-pool sweep, user-directed 2026-09-03)** (name and
  concept confirmed user 2026-09-03; generalizes `RT-6`) — runs on a
  schedule (own cadence, see `SC-9`), but deliberately does not research
  every free agent every night — that's unbounded cost for very little
  marginal signal on most nights, the general principle behind this
  design applying beyond just this one item. Two-tier scope instead:
  1. A cheap, bounded daily survey for notable events, built from
     structured status/depth-chart/roster-move changes already
     comparable via `pickup_snapshots.py`'s diff shape (and, once it
     exists, `RT-21`'s transaction log) — not a fresh research query per
     player.
  2. A real research pass only on the subset that's actually earned
     attention: players the notable-events survey flagged (or a relevant
     subset of it), plus anyone already surfaced by the app's own
     existing candidate-pool functions (`free_agent_board()`,
     `leaguewide_trade_candidates()`, pickup alerts) — reusing those
     rankings as the scope filter rather than re-deriving "worth a look"
     from scratch, the same reuse discipline
     `valuation_principles.md`'s "one valuation strategy, used everywhere"
     rule already asks for elsewhere in this codebase.
  Writes templated findings (`SC-2`'s schema) to the store rather than
  returning them inline to one question. Needs `SC-8`'s
  templated-storage-plus-double-check defense built in from the start —
  this is the component that actually touches unstructured external
  content, unlike the rest of the pipeline.
- [ ] **SC-4: Persisted "already reported" dedup log, extended beyond
  pickups** — `pickup_snapshots.py` already solves this for free-agent
  availability changes; extend the same load/diff/persist shape to
  `suggested_trades()`/`leaguewide_trade_candidates()` output (keyed by
  candidate/pairing) and to `SC-3`'s scout findings (keyed by player +
  category, using `SC-2`'s templated fields directly rather than parsing
  free text), so something found once doesn't re-notify every night it
  remains true — only when it's new or materially changed. Also the
  natural place multi-signal convergence gets detected for `SC-5` below —
  a second, independent signal landing on the same player is exactly the
  kind of thing this log is positioned to notice. Needs pytest coverage
  on the diff/dedup logic, mirroring `tests/dynasty_core/test_pickup_snapshots.py`'s
  existing shape.
- [ ] **SC-5: Materiality thresholds — quantitative and qualitative
  signals kept distinct, convergence treated as a positive signal
  (user-directed 2026-09-03)** — reuse existing, already-reviewed
  acceptance gates for the deterministic signals rather than invent new
  ones (`suggested_trades()`'s own tolerance-gated offer search; a
  minimum `marginal_value` delta matching `free_agent_board()`'s `> 0`
  convention), with the `RT-10`/`RT-28` FAAB caveat folded in explicitly
  rather than silently inherited. `SC-3`'s scout findings are a
  genuinely different kind of signal — qualitative, uncertain, sourced
  from unstructured text — and must not be forced through the same
  numeric bar or blended into one score with the quantitative side; per
  this project's own "one valuation strategy, used everywhere" principle,
  the fix isn't a second parallel *ranking* algorithm, it's keeping two
  clearly-labeled *signal types* that both feed the same
  worth-a-push decision explicitly rather than silently averaging into a
  number that means neither thing. When independent signals — a
  quantitative ranking and a scout finding, or two scout findings from
  different angles — point at the same player and the same action
  (add/drop/bid/trade), that convergence is itself worth surfacing with
  more confidence, not a conflict to resolve down to one number.
  Concretely: `SC-6`'s notification should be able to say "flagged by
  both the marginal-value ranking *and* tonight's scout research" as its
  own, higher-confidence category, distinct from either signal alone.
- [ ] **SC-6: The nightly `/schedule` cloud routine** — orchestrates: run
  `SC-1`'s script for the deterministic signals, read `SC-2` (via
  `SC-11`'s API) for anything Scout found since the last check, apply
  `SC-4`/`SC-5`, run `SC-7`'s self-reflection, push a phone notification
  only if something clears the bar. Notification mechanism: the
  `/schedule` cloud routine's own push-to-phone path — confirm this
  actually works via `SC-12`'s proof-of-concept before building this item
  out for real, since the whole feature's value depends on the
  notification actually reaching the user, not just a desktop/terminal
  one nobody's watching at 8pm. Needs an explicit "checked, found nothing
  new" vs. "check failed" distinction in its own logic (mirroring
  `Finance-Dashboards`' `ingest_health` status split) so a broken routine
  doesn't read as a quiet night. Target cadence: daily 8pm local
  in-season, per `SC-9`.
- [ ] **SC-7: Self-reflection pass — did we miss something, and why,
  files a GitHub issue on a miss (user-directed 2026-09-03)**
  (user-flagged 2026-09-03, the core "close the gap" ask) — a second pass
  in the same nightly routine that checks the scout's own recent output
  against what actually happened, using `RT-21`'s transaction log plus
  `pickup_snapshots.py`'s existing status/depth-chart diffs (example given
  by the user: a rostered-elsewhere player goes on IR, freeing a
  value-add free agent the scout should have flagged, and didn't). When a
  miss is found: identify the likely root cause, propose a concrete fix,
  and open a GitHub issue on this repo (`gh issue create`, tagged so it's
  findable later) describing the miss and the proposed fix — never a
  branch/commit/PR directly; the routine only ever proposes via an issue,
  consistent with `git_workflow_simple.md`'s "no direct main commits,
  nothing merges without explicit approval" — a human still decides
  whether and how to act on it. Also push-notifies that an issue was
  opened, with its own `SC-4`-style dedup keyed on the diagnosed gap so
  the same miss doesn't get a new issue every night before it's
  addressed. Genuinely new logic — no current code compares "what the
  scout said" against "what actually happened" after the fact.
- [ ] **SC-8: Prompt-injection defense — templated storage plus
  on-demand double-checking (user-directed 2026-09-03)** —
  Sleeper/FantasyCalc's structured API responses are low-risk, but `SC-3`'s
  research pass (and any later `RT-6` on-demand fold-in) pulls in
  less-structured content — news, injury reports, transaction notes.
  Two-part defense: (1) `SC-2`'s templated finding schema is the primary
  guard — the store never holds a raw untrusted blob a later consumer
  (`SC-6`, a notification) could render or reason over as instructions,
  only extracted fields; (2) when a finding looks borderline or
  high-stakes, the scout runs a second, independent web search to
  corroborate it before writing it to the store, rather than trusting a
  single source outright — the same spirit as `Finance-Dashboards`'
  `claude_scout.py` fenced/untrusted-content handling for its RSS
  sources, adapted to a search-based source instead of a feed. Build
  this in alongside `SC-3` rather than retrofitting after a real issue
  surfaces.
- [ ] **SC-9: Season-aware cadence — not required for initial release,
  but needed before next year's rookie draft ramp-up (user-directed
  2026-09-03: due before late summer 2027)** (user-flagged 2026-09-03) —
  full daily-8pm cadence only applies in-season; off-season, both `SC-6`'s
  nightly review and `SC-3`'s research pass should throttle back to
  roughly once every few weeks, then ramp back up to full cadence once
  the next rookie draft is scheduled — the ramp-up trigger needs to be as
  real/live as the throttle-down one, not a manual flip the user has to
  remember to make. Needs a live, not hardcoded, in-season/off-season
  signal — check what Sleeper's `league` object actually exposes for this
  (`status` — `pre_draft`/`drafting`/`in_season`/`complete` — is a
  plausible candidate, alongside the `league["settings"]["leg"]`
  current-week counter already used elsewhere per
  `valuation_principles.md`'s "anchor on the live current week" rule)
  rather than assuming, per this project's "document what you can't
  verify" pattern; `confidence_pool/picks_core.py`'s own current-week
  detection is a useful reference pattern to look at, though not shared
  code (`dynasty`/`confidence_pool` share none, per `CLAUDE.md`'s
  Architecture section — this would be independently derived). Default
  design: keep one fixed cron (fires daily year-round) and gate real work
  inside the routine/Scout logic based on the detected season state,
  checking a persisted "last off-season run" timestamp — stored in
  `SC-2`, reached the same way everything else is per `SC-11` — before
  doing anything during the off-season window; simpler and more robust
  than trying to reprogram the `/schedule` cron itself at season
  boundaries. Revisit that choice only if the fixed-cron-plus-internal-gate
  approach proves awkward in practice. Ship `SC-1`–`SC-8`/`SC-11`/`SC-12`
  with a fixed in-season cadence first; build the ramp/throttle logic
  once real season-transition data exists rather than guessing at it
  ahead of time.

  **Draft-date signal checked live, 2026-09-03** (user-flagged: this
  year's draft was itself pushed back a week from its original date,
  confirming the field is genuinely dynamic, not just theoretically so).
  `draft["start_time"]` (epoch ms, via `sleeper.get_draft(draft_id)`) is
  real and populated — confirmed against this league's own completed
  2026 draft. So "the next rookie draft is scheduled" *can* be a live
  signal, not a guess, but two things need to be designed in, not
  assumed: (1) re-read it every time rather than caching the first
  observed value, since it can change after being set, exactly like it
  did this year; (2) next season's draft doesn't live under this
  league's current `draft_id` at all — Sleeper creates a new league
  object (and a new `draft_id`) per season, chained via
  `previous_league_id` (the same chain `RT-25` already plans to walk for
  FAAB history) — so the ramp-up check first has to find *next* season's
  league/draft object before it can read a `start_time` off it, which
  won't exist at all until the commissioner sets up that season. Worth
  scoping that discovery step explicitly when this item is picked up,
  not assuming `draft_id` stays constant year to year.
- [ ] **SC-10: Documentation — written incrementally, final consolidated
  pass once everything ships (user-directed 2026-09-03)** — write
  `docs/dynasty-daily-scout.md` as each piece of this section lands,
  mirroring how the rest of the app's docs already get written alongside
  a feature rather than deferred entirely to the end. Once `SC-1` through
  `SC-9`/`SC-11`/`SC-12` are built and proven out, do one final pass over
  the whole doc for consistency and fold this section's intro/architecture
  notes into it, rather than leaving the rationale only here.
- [ ] **SC-11: API endpoints so the cloud routine can reach the
  NAS-deployed store (user-directed 2026-09-03)** — `SC-3`/`SC-6` run as
  `/schedule` cloud routines, a different execution environment than the
  NAS-hosted Docker container `SC-2`'s SQLite store lives in; the cloud
  routine has no direct filesystem access to it. Needs a small,
  authenticated API surface on the deployed app (read findings, write
  findings, mark reported, read/write dedup state — whatever
  `SC-4`/`SC-6`/`SC-7` actually need) that the cloud routine calls over
  the network instead. `SC-14` already spot-checked that the NAS is
  reachable from outside at all (confirmed low-risk — see the
  "Persistence and reachability" note above) and the user separately
  confirms routinely using both apps off-prem from their phone, so this
  item's own reachability check only needs to confirm the specific path
  that matters here: a request *from the cloud routine's own sandbox*
  actually hits the deployed service's endpoint — before anything else in
  this section builds on the assumption that it can. Needs pytest
  coverage for the endpoints' own request/response contract; the live
  reachability check itself can't be a unit test by nature — document it
  as a scripted check outside the pytest suite, the same role
  `scripts/check_scoring_correction_assumptions.py` already plays for a
  different live-data assumption.
- [ ] **SC-12: Proof-of-concept — confirm a `/schedule` cloud routine can
  actually push a phone notification, and whether that happens
  automatically or only when the agent sends one (user-directed
  2026-09-03)** — the whole feature's value depends on a notification
  reliably reaching the user's phone from an unattended nightly cloud
  routine, not a desktop/terminal notification nobody's watching at 8pm.
  Before building `SC-6` out for real: schedule a minimal `/schedule`
  routine that does nothing but send one push notification, confirm it
  actually lands on the phone, and note whatever setup that required
  (e.g. Remote Control connectivity, or whatever "cowork tasks" turns out
  to mean concretely — unconfirmed as of 2026-09-03) so `SC-6`'s real
  implementation doesn't discover this gap only after everything else is
  built. Also resolve a second, easy-to-miss question in the same test:
  does a routine *run completing* generate a phone notification on its
  own (via the platform's own task/run surfacing), independent of
  anything the agent explicitly does? If so, `SC-6`'s entire "stay silent
  on a quiet night" design (`SC-5`) needs to account for that — a
  materiality gate that only decides whether to *push* is pointless if
  every run notifies regardless of what it decided. Cheap and independent
  of the rest of the pipeline — do this right after `SC-13`/`SC-14`.
- [ ] **SC-13: Confirm the Claude GitHub App has repo access for cloud
  routines — clone and issue-write both (user-directed 2026-09-03)** —
  the `/schedule` skill's own setup check surfaced, unprompted, "Couldn't
  verify GitHub access for twharris57/Football (the check failed in a way
  that may be temporary) — if your routine needs this repo and this
  persists, install the Claude GitHub App." This is a live, currently
  unresolved gap, not a hypothetical: `SC-1` (clone the repo to run its
  script), `SC-3`, and `SC-6` all need at least read/clone access, and
  `SC-7` additionally needs write access to open issues (`gh issue
  create`) — a different, higher permission level than clone-only, worth
  confirming separately rather than assuming one implies the other.
  Action: visit
  https://claude.ai/code/onboarding?magic=github-app-setup (or run
  `/web-setup`) to install/verify the app on this repo, then re-check via
  the schedule skill. The cheapest, most foundational check in this whole
  section — every other cloud-routine item depends on it, so it goes
  first.

  **Resilience design, user-directed 2026-09-03: don't let `SC-7` depend
  on the cloud routine's GitHub access alone.** Rather than a single path
  that either works or silently doesn't, `SC-7`'s issue-opening action
  (and any future cloud-routine action that needs GitHub write access)
  should attempt it directly from the cloud routine first, but fall back
  to a durable queue when that fails or is unavailable: write the pending
  action (what issue to open, with what body) into `SC-2`'s store via
  `SC-11`'s API, and have it get flushed by whichever path becomes
  available first — the cloud routine itself on a later run, *or* the
  next local Claude Code session, at the desktop, with the user logged
  in. The local path is not hypothetical — this very session already has
  working `gh` access to this repo (it opened and commented on `PR #72`
  earlier in this conversation), so "flush the queue" from a local
  session is a real, already-proven capability, not something new to
  build. The point isn't redundancy for its own sake: the user's stated
  goal is confirming the whole pipeline works regardless of whether the
  desktop is up and reachable, and a single-path design (cloud-only, or
  desktop-only) can't demonstrate that — a dual-path design with a
  durable, inspectable queue can. Worth testing as an explicit part of
  the first proof-of-concept build (see the short list's "first
  buildable slice" note) rather than added later once `SC-7` is real:
  deliberately fail the cloud path in the POC and confirm the local
  fallback actually flushes the queue on the next session.
- [ ] **SC-14: Confirm the cloud routine can reach the NAS-deployed store,
  and resolve where `SC-1`'s script actually executes (user-directed
  2026-09-03, spot-checked same day)** — `/schedule` cloud routines run
  in Anthropic's cloud and, per the schedule skill's own docs, "cannot
  access local files, local services," so `SC-2`'s SQLite store is only
  reachable if the NAS is genuinely exposed, and `nas-configs` (this
  repo's NAS deployment owner) has no reverse proxy, tunnel, or other
  public-exposure setup documented for any stack — a real reason to
  doubt it going in. Spot-checked 2026-09-03: `twharris.synology.me`
  resolves to a real public IP via a public DNS resolver, both `:8501`
  (dynasty) and `:8502` (confidence-pool) return HTTP 200, and the user
  separately confirms routinely using both apps off-prem from their
  phone — real-world confirmation the NAS is genuinely reachable from
  outside, not just a same-network artifact of the spot check. So "is the
  NAS reachable at all" is resolved; what's left here is narrower: (1)
  confirm the *cloud sandbox's own* egress path can reach it too — a
  different network route than a phone's, even against the same forwarded
  port, and the only way to know for sure is having an actual routine try
  it (fold into `SC-11`'s own reachability check once it exists, or do a
  standalone curl-only routine first if `SC-11` isn't built yet); (2)
  decide where `SC-1`'s script is meant to run — inside the cloud
  sandbox directly (meaning it needs its own outbound access to Sleeper's
  and FantasyCalc's public APIs, and its own Python environment with this
  repo's dependencies installed) versus only ever running on the NAS side
  and being triggered/read remotely via `SC-11`'s API. This changes what
  `SC-11` actually needs to expose — a full "run `gather_state` and give
  me the result" trigger endpoint in the first case, versus just
  store-read/write endpoints in the second — so resolve it before
  finalizing `SC-11`'s design, not after. Also flag, not a new decision:
  both NAS ports are currently plain HTTP with no TLS and no auth (fine
  for the existing read-only dashboards' current stakes) — `SC-11`'s API
  cannot reuse that same unauthenticated exposure and needs real auth
  added explicitly.

## Roster & trade tooling

Originally scoped as explicitly post-draft (user-flagged 2026-07-26), then
briefly reordered 2026-07-30 to put trade targets & sells first given real
trade talk already happening pre-draft, then reordered again same day: the
user judged that shipping trade targets & sells before the positional-value
and team-power foundations it needs would produce a weak tool that has to
be redone once those land, so the foundations come first. Still bumped
ahead of Valuation & data accuracy below, which remains explicitly not
deadline-driven.

Deliberately out of v1, not forgotten:
- **Selling starters, not just depth** — the "sellable vs. just
  droppable" line for a position's own top-value players (not bench
  surplus) is a much bigger strategic call (trade away a good win-now
  asset for future value, core to a rebuild) than "there's unused depth
  here." Left for a human to judge directly against a specific offer,
  not modeled.
- **Draft-pick ownership beyond next season** — Sleeper's `traded_picks`
  has no fixed "how many years out" window, only entries for picks
  actually traded (`FUTURE_PICK_YEARS_AHEAD = 1` in `dynasty_core/picks.py`).
  Extending further is possible but was scoped out to avoid listing
  picks with zero real trade activity that far out.
- **Young non-rookie depth isn't protected the way `LOW_VALUE_YOUNG_AGE`
  protects it elsewhere** (assistant valuation review, 2026-08-01) —
  `sellable_players` excludes true rookies (`years_exp` falsy) but nothing
  younger than that; a promising 2nd-year breakout at a surplus position
  can show up as "sellable" even though `roster_value_analysis` elsewhere
  in this same rebuild-strategy codebase explicitly treats "low-value but
  young" as hold-not-sell, not drop-or-sell. Not necessarily wrong, given
  this list is explicitly framed as candidates for a human to judge
  against a specific offer, not a recommendation — but worth a deliberate
  decision (extend the exclusion, or leave it and rely on the human)
  rather than an unexamined inconsistency between the two features.

- [ ] **RT-16: Need-match tiebreaker in `find_trade_offers()` reuses
  `roster_needs_summary`'s rebuild-timeline "need" flag on the *partner's*
  roster, which may not mean what it implies for a partner not running the
  same rebuild strategy** (assistant valuation review, 2026-08-02) —
  `need` is specifically "fewer than `YOUNG_CORE_NEED_THRESHOLD` young
  players at this position" (`docs/rookie-draft-big-board.md`'s "two
  different signals" section), a rebuild-*timeline* question, not a
  general "does this team want more here" signal. `find_trade_offers()` is
  the first place `need_positions()` gets applied to someone *else's*
  roster to guess what they'd want, rather than the caller's own — a
  win-now partner might not care about "young core" at this position at
  all, or might specifically want to trade youth away for a proven
  veteran, the opposite of what the flag implies. The "need" flag itself
  is now phase-aware everywhere else it's read on a team's *own* roster
  (young-core while that team is rebuilding, VOR-based `weak` otherwise —
  see `roster_needs.py`'s `phase_aware_need_positions()`) — but
  `find_trade_offers()`'s tiebreaker was deliberately left calling the
  young-core-only `roster_needs_summary()` directly rather than converted,
  since a partner's own phase alone still might not answer this item's
  real question (a partner not running *any* rebuild strategy could
  contending-read as "roster-hole" and still not mean what a trade
  tiebreaker needs it to). Concrete next step if picked up: thread the
  partner's own `team_power_timeline` phase into `find_trade_offers()` and
  call `phase_aware_need_positions()` instead — low severity either way,
  since this is explicitly a ranking tiebreaker only (already noted in the
  function's own docstring, never the accept/reject gate).
- [ ] **RT-30: `PHASE_THRESHOLDS`' "revisit by feel" calibration now gates
  real recommendations, not just a display label — worth re-checking it's
  still an acceptable cutoff for that** (assistant valuation review,
  2026-08-29, PR #67) — `power_timeline.py`'s own comment on
  `PHASE_THRESHOLDS = (-0.3, 0.3)` says it was chosen "by feel" for a
  *display-only* phase label, explicitly stating downstream consumers
  should reason about the continuous `power_score` instead. PR #67 made
  `phase` itself decision-relevant for the first time: `need_positions`,
  `roster_value_analysis`'s drop-candidate `note`, and the draft plan's
  "flagged need" reasoning all now switch behavior at this exact boundary.
  This is the same shape as `valuation_principles.md`'s "dedicated-slot-only
  simplifications are fine for signals, not for action recommendations"
  rule, one level up: an already-accepted simplification tuned for a
  *display* bar (three-way visual bucketing, tolerant of imprecise
  boundaries since a user just reads a label) is now the actual switch
  behind three separate pieces of recommendation text. Nothing confirms
  the ±0.3 z-score cutoffs are still well-calibrated for that heavier use — a
  team sitting just inside one bucket by a hair (plausible in a 10-12 team
  league, where `power_score`'s std is well under 1 after averaging three
  z-scored components) gets a different "need"/"hold" read than an
  otherwise-identical team just across the line, with no hysteresis or
  buffer around the boundary. Concrete next step if picked up: either
  validate the current thresholds hold up under this use (e.g. check how
  often real teams sit within a small margin of ±0.3 across a season), or
  add a buffer band immediately around each threshold where `need`/`note`
  keep the *previous* phase's reading rather than flipping on a marginal
  crossing — low severity since `power_score` is shown alongside `phase`
  in the Roster tab (see PR #67's fix-before-merge item on the same
  branch), so a user reviewing a borderline case isn't flying fully blind.

  **Checked against real live data, 2026-08-30** (this league,
  `DEFAULT_LEAGUE_ID`, 12 teams): the concern is real, not hypothetical —
  6 of 12 teams currently sit within 0.2 of a `±0.3` boundary, 2 within
  0.1, against a league-wide `power_score` std of ~0.50. But this
  snapshot is itself incomplete: it's preseason, `games_played == 0`
  league-wide, so `win_pct_shrunk` is the identical neutral `0.5` for
  every team and contributes zero spread to `power_score` right now —
  once real records diverge, `power_score` will move more from week to
  week than today's number shows, if anything making a boundary flip more
  likely mid-season, not less. Given that, neither fix (validate the
  threshold / add a hysteresis buffer) is well-informed by a preseason-only
  read — user decision (2026-08-30): leave `PHASE_THRESHOLDS` and behavior
  unchanged for now, and re-run this same check (`team_power_timeline_scores()`'s
  `power_score` distribution vs. the ±0.3 boundary) once real win/loss
  records exist league-wide (a few weeks into the season, once
  `games_played > 0` for every team) before deciding between the two
  fixes with a representative sample. If a hysteresis buffer is the
  eventual choice, note it would add a new persisted-state layer (a
  per-team last-effective-phase cache, following `draft_snapshots.py`'s
  load/write pattern) to a module currently designed as "recomputed fresh
  every call... never cached" — a real architecture decision, not just a
  constant tweak, worth weighing against the cheaper "just widen the
  thresholds" alternative once real data is in hand.
- [ ] **RT-23: Suggested Trades - optional position-scope filter** (user-flagged
  2026-08-08, noted future option, not v1 scope, while building `RT-15`) —
  besides the single-target filter, also let the user scope leaguewide
  suggestions by position (e.g. "show me RB opportunities only") - a
  second, independent optional filter within the same section, not a
  replacement for the target filter. Not needed for the first cut; revisit
  now that leaguewide scanning itself is built and the section's filter UI
  exists to extend (see `docs/rookie-draft-big-board.md`'s "Suggested
  Trades" section).
- [ ] **RT-6: Contextual research check for news/hype beyond Sleeper's data**
  (user-flagged 2026-07-31, possibly via "Claude Scout" or similar — name
  unconfirmed) — a rare, explicitly user-triggered lookup (not a
  background job) for one *specific* named player: pull recent context an
  LLM-with-web-access can surface that Sleeper/FantasyCalc don't carry
  directly — real trade buzz, a beat-reporter note on a depth-chart
  change, injury detail beyond Sleeper's status field — to sit alongside,
  not replace, the stats-based `adj_value`/marginal-value numbers.
  Directly addresses a limitation named in the 2026-07-31 valuation
  review: the whole pipeline is market-value-plus-scoring-correction, so
  it has no way to react to a hype cycle or a fresh injury faster than
  FantasyCalc's own market already has. Needs investigating what's
  actually available and appropriate here before committing to an
  implementation — treat the specific tool name as unverified, just the
  user's working label for the idea. Natural entry points: RT-2's
  trade evaluator (checking one flagged trade idea) and RT-3's
  free-agent evaluator (checking one waiver target) — not a general
  always-on feed, and not a replacement for the stats-based ranking
  anywhere in the pipeline.

  **Name confirmed, scope generalized (user-clarified 2026-09-03):** "Claude
  Scout" is the real name, and it's no longer only the on-demand, one-player
  lookup described above — `SC-3` (see "Automated daily scout" section
  below) builds it as a routine, scheduled research pass across the whole
  relevant player pool, writing findings to a persisted store the nightly
  `SC-6` routine reads. This item stays open specifically for the narrower
  "check this one named player right now" on-demand trigger, which may end
  up cheap to add on top of `SC-3`'s infrastructure once it exists rather
  than needing its own separate design — revisit once `SC-3` ships.
- [ ] **RT-7: Use `points_for`/point differential as a steadier alternative
  to win/loss in the power/timeline read** (deferred from the small-sample
  shrinkage work above, 2026-08-02) — shrinkage toward `0.5` (done, see
  above) addresses the small-sample variance problem directly, but binary
  win/loss is still a noisier signal than point differential even at a
  full sample size, standard practice in sabermetric-style team-strength
  reads. Not picked up alongside the shrinkage fix because it's a bigger
  scope: `sleeper_api.py` has never pulled or verified Sleeper's
  points-for field (name, decimal-split format — Sleeper's own API splits
  `fpts` into a whole-number and a `_decimal` field for other objects, so
  the roster `settings` shape needs checking directly, not assumed), and
  it needs a real design decision on how to blend/weight it against (or
  replace) `win_pct` rather than just swapping the input.
- [ ] **RT-8: Model real taxi-squad eligibility for free-agent adds**
  (deferred from the free-agent evaluator v1 above, 2026-08-02) —
  `free_agent_board()` currently passes `taxi_eligible=False` to
  `roster_total_capacity()`/`rank_by_marginal_value()`, so an add is only
  ever suggested for an open active roster slot or via a drop, never an
  open taxi slot — correct for rookies (always taxi-eligible, the draft
  plan's own default) but overly conservative for veteran free agents who
  might genuinely qualify under Sleeper's real accrued-experience taxi
  rule. Needs that rule verified live (field name, exact threshold) before
  modeling it — not guessed at, per this project's "document what you
  can't verify" pattern. The `taxi_eligible` flag already threads through
  both functions; this is "verify the real rule and flip candidates that
  qualify to `taxi_eligible=True` on a per-candidate basis," not a
  rearchitecture.
- [ ] **RT-21: Sleeper's transaction log as a secondary data source —
  revisit before next year's draft** (assistant-flagged 2026-08-07, filed
  while scoping `RT-20`, user-flagged as worth keeping for later rather
  than acting on now) — `RT-20` was built as a roster-snapshot-and-diff
  design, but a live check against this league's real API during scoping
  found Sleeper's `/league/{id}/transactions/{leg}` endpoint already
  records every real roster move with a timestamp, including plain
  "drop to make room" cuts (`type: "free_agent"`, `adds: null`, a real
  `drops: {player_id: roster_id}`). Two distinct reasons this could be
  worth building out, not investigated further this pass given draft-day
  time pressure:
  - **Closing `RT-20`'s own gap.** Its `"ambiguous"` state exists because
    a roster-diff snapshot can't isolate which drop paired with which pick
    when two or more of the user's own picks complete in the same refresh
    gap. Sleeper's transaction log doesn't have this problem — it's
    timestamped and complete regardless of when this app happens to
    refresh — though it introduces a different gap instead: Sleeper
    doesn't timestamp individual draft picks, so pairing a transaction to
    a specific pick would still need a positional/count-based heuristic,
    not a hard fact. Unverified going into this: whether draft-day cuts
    always land as `type: "free_agent"` (vs. some other transaction type),
    and `league["settings"]["leg"]`'s bucketing behavior beyond the
    single `leg=1` value checked live (this league was still in
    `"pre_draft"` status with zero picks made at check time, so no
    real "cut immediately following a draft pick" example existed yet to
    validate against).
  - **Leaguewide visibility, not just the user's own roster** — the same
    endpoint returns every team's transactions, not just the user's,
    which `RT-20`'s snapshot design has no equivalent for (it only ever
    diffs the user's own roster). Could show what other teams are doing
    during the draft (real drops/adds leaguewide) as a genuinely new
    signal, not just a more-reliable version of `RT-20`'s existing one —
    worth scoping as its own feature rather than folding entirely into
    `RT-20`'s drop-attribution problem.
  Revisit ahead of next year's rookie draft, with time to verify the
  unconfirmed assumptions above against a real draft in progress before
  committing to a design — not urgent mid-draft the way `RT-20` was.

  **Promoted, 2026-09-03** — no longer just a next-draft revisit. `SC-7`'s
  self-reflection pass (see "Automated daily scout" below) needs exactly
  this endpoint: a reliable, timestamped, leaguewide record of what
  actually happened (adds/drops/IR moves), independent of this app's own
  refresh timing, to check the scout's prior output against. The
  leaguewide-visibility angle above is also now directly useful beyond the
  draft — it's what lets self-reflection notice a missed opportunity on
  *any* team's move, not just the user's own roster. Added to the short
  list alongside `SC-1`–`SC-6`; the unconfirmed assumptions above (cut
  transaction `type`, `leg` bucketing beyond a single observed value)
  still need live verification before implementation, same as before.
- [ ] **RT-31: Trade-block-style watchlist — track other teams' players
  worth a look, auto-remove once traded or dropped (user-flagged
  2026-09-03)** — periodically review who other managers have flagged as
  available (Sleeper's app-side "trade block"), add candidates to a
  tracked list for review, and drop them off it automatically once
  they're no longer relevant (rostered on a different team, or dropped
  outright — both already detectable via existing tooling, see below).
  **Checked live, 2026-09-03: Sleeper's public API does not expose trade
  block at all.** Confirmed two ways — this league's real
  `/league/{id}/rosters` response has no `trade_block`-shaped key
  anywhere in `metadata` (which is otherwise a real, populated free-form
  dict for this league, e.g. custom player nicknames — so it's not that
  metadata is empty/unused, trade block specifically isn't in it), and
  Sleeper's own API docs list only transactions/traded-picks/rosters as
  the trade-related surface, with no trade-block endpoint or field
  documented. So this can't be a Sleeper-sourced automated feed the way
  `RT-21`'s transaction log is — the "who's on the block" input has to
  come from somewhere else: most likely the user manually adding a
  player after seeing it mentioned in league chat/Discord/wherever
  trade-block talk actually happens in this league, not pulled from an
  API. Once a player's on the tracked list, though, removal *can* be
  fully automated — a rostered-elsewhere check (`rostered_player_ids`)
  or a dropped check (`pickup_snapshots.py`'s existing status diff)
  both already exist and are exactly what's needed, no new detection
  logic required there. Natural fit with this section's other work: a
  tracked player is a good candidate to feed into `SC-3`'s bounded scout
  scope (a manually-flagged player is at least as "earned attention" as
  one surfaced by the notable-events survey), and the list itself is
  another `SC-4`-shaped dedup/persistence problem, so this is worth
  scoping after `SC-2`'s store exists rather than as a standalone
  persistence design. Not part of the initial-release build order —
  files here as a real, scoped feature idea, not a vague "would be nice."
- [ ] **RT-25: Extend FAAB bid guidance to prior seasons via
  `previous_league_id`** (deliberately deferred from `RT-10`, 2026-08-20)
  — a real `previous_league_id` chain exists for this league and could
  substantially grow the comparable-bid sample beyond the current
  season's (still-thin, early-season) data. Two real complications
  user-flagged when this is picked up, not present in the current-season-
  only v1: **(1) league membership churn** — a `roster_id`/owner from a
  prior season may no longer be in the league (or a current owner may not
  have been), so pulling in their historical bids without accounting for
  that risks calibrating guidance partly on bidding behavior from people
  who aren't part of this negotiation anymore, or missing a real member's
  history if they joined more recently; needs the real owner/roster
  mapping checked per season, not assumed stable. **(2) recency bias** —
  older bids should count for less than recent ones (both because FAAB
  budgets/behavior can drift year to year, and because `won_bid_sample`
  already uses *current* `adj_value` as a proxy for a player's value at
  bid time — see `docs/rookie-draft-big-board.md`'s "Static assumptions"
  table — a proxy that gets progressively less accurate the further back
  a comparable bid is from).
  A weighted-by-recency sample (or a hard recency window) is likely
  needed, not a flat pool across all available seasons.
- [ ] **RT-26: Draft Board — a year selector, defaulting to the current
  year** (user-flagged 2026-08-20, future years) — once more than one
  rookie draft's worth of history exists, add a dropdown to the Draft
  Board tab (defaulting to the current/most-recent year) that lets the
  user look back at a prior year's board instead of only ever showing the
  latest. Not urgent yet (only one draft has happened so far) — revisit
  once a second season's draft data exists to actually browse back to.

## Valuation & data accuracy

Not deadline-driven the way the group above now is (see 2026-07-30 note) —
this is about improving accuracy for ongoing dynasty decisions, not a hard
cutoff.

- [ ] **VA-1 (formerly "D"): blend in KeepTradeCut as a second market source**, time
  permitting. `import_ids()` only gives a `ktc_id` crosswalk column, not
  actual KTC values — sourcing real KTC data is a separate,
  not-yet-investigated problem.

  **Extra motivation, not just a nice-to-have** (assistant valuation
  review, 2026-07-31): KTC publishes separate superflex-specific
  rankings, which could serve as a rough external cross-check on whether
  this project's own VOR/replacement-level signal still under-credits QB
  after the SUPER_FLEX/QB fix (Roster & trade tooling, done 2026-08-01) —
  not a substitute for that fix, which already landed, but a useful
  independent sanity check on how well-calibrated it turned out once KTC
  data exists to compare against.
- [ ] **VA-2: Derive `BASELINE_SCORING`'s `rec` value from the real `ppr` param
  instead of hardcoding `1.0`** (assistant valuation review, 2026-07-31) —
  `get_dynasty_values()` already sends this league's actual PPR
  (`league["scoring_settings"]["rec"]`) to FantasyCalc, so its returned
  market `value` is already calibrated to it. But `player_scoring.
  BASELINE_SCORING` hardcodes `"rec": 1.0` as "FantasyCalc's assumed
  baseline" regardless of what `ppr` was actually sent. Currently
  harmless — this league is full PPR, so `1.0` happens to be correct —
  but if the league's PPR setting is ever changed to anything else, the
  per-player correction ratio would silently start conflating the
  intended residual scoring-format delta with an unintended PPR delta
  that FantasyCalc's own API call already priced in. Cheap fix once
  picked up: thread the real `ppr` value into `BASELINE_SCORING`'s `rec`
  key instead of the literal `1.0`. Not urgent while the league stays
  full PPR — flagged in `docs/rookie-draft-big-board.md`'s "Static
  assumptions" table in the meantime so it isn't a silent trap.
- [ ] **VA-3: Automate `scripts/derive_position_multipliers.py` re-derivation.**
  It still has to be run by hand and its printed numbers manually copied
  into `POSITION_VALUE_MULTIPLIER`. The easy fix already done is making the
  *season selection* itself current-year-driven
  (`recent_complete_seasons_weekly_data()` looks back from the league's real
  current season, so it doesn't need editing next year). The harder
  remaining piece — fully automating this so it re-derives and applies
  itself with no manual step at all — is deliberately deferred: it would
  need a decision on *when* to trigger a re-derive (season rollover? a
  scheduled job?) and probably a sanity-check guard before auto-applying a
  new multiplier (e.g. reject a swing beyond some threshold vs. the current
  value), so a bad data pull can't silently skew live rankings. Now that B
  (per-player recompute) has landed, this multiplier is a last-resort
  fallback only — worth a proper look if it still seems to matter enough to
  justify the automation.

## Code quality, tests & UX polish

- [ ] **CQ-5: Represent draft-pick identity as structured fields at ingestion, not a
  display string re-parsed downstream** (user-suggested, 2026-08-07, filed while
  reviewing the RT-18 pick-callout season bug above) — `pick_trade_values()` already
  builds a formatted `"pick"` label per row (`"2026 Pick 1.01"` this season, `"2027
  1st"` next season) as effectively the only column that encodes season/round, so
  every downstream consumer that needs the season or round has to re-parse that label
  — `_pick_context_callouts()`'s now-fixed `" Pick "` split was one instance;
  `trade_tab.py`'s pick-selection/labeling helpers likely re-derive similarly. The
  general principle: parse an externally- or internally-generated composite string
  once, at the point it's produced, into real fields with a well-defined "unknown"
  case — not repeatedly downstream, where each call site can (and, once already did)
  parse it differently or incompletely. Concretely: give `pick_trade_values()`'s output
  real `season`/`round` (and `slot` where it exists) columns alongside the display
  `"pick"` label, and move every downstream consumer that currently
  slices/splits/matches the label for meaning (grouping by class, sorting by round)
  over to those columns instead — the label stays purely a rendering concern. Distinct
  from `pick_trade_values()`'s own name-string matching against FantasyCalc's data
  (`valuation_principles.md`'s "opaque keys" rule) — that's an external join key and
  has to stay a string match; this is about not re-deriving *this codebase's own*
  already-known structure from a string it built. Cleanup scope, not urgent — no
  known live bug beyond the one already fixed above.
- [ ] **CQ-7: `pick_value_by_name` dict-building + NaN-safe pick-value-sum
  pattern duplicated between `find_trade_offers()` and
  `improve_incoming_offer()`** (assistant valuation review, 2026-08-19) —
  both build `dict(zip(pick_value_table["pick"], pick_value_table["value"]))`
  and both sum a list of pick names against it with the same
  `pd.notna()`-filtered pattern (`improve_incoming_offer()`'s `_pick_value_sum`
  vs. `find_trade_offers()`'s inline `pick_value_by_name.get(...)` reads).
  Minor — no behavioral risk, both copies are already NaN-safe per
  `valuation_principles.md`'s NaN rule — but worth extracting a small shared
  helper (e.g. `_pick_value_lookup(pick_value_table)` returning both the
  dict and a `sum(names)` closure) next time either function is touched,
  rather than a third copy appearing.
- [ ] **CQ-13: Summary tab's "(+N more)" note has nowhere to send the user**
  (user-flagged 2026-09-03, seen live as "and 7 others") — `summary.py`'s
  `_capped()` caps each Attention Digest category to `top_n=3` and appends
  a plain-text `"(+N more)"` line (`summary_tab.py` renders it as an
  ordinary `st.caption`, no link, no expander), so a user seeing "(+7
  more)" has no way to find out what the other 7 are or where to look.
  Three of the four capped categories (`weekly_gaps`, `sellable`,
  `free_agents`) do have a fuller view elsewhere (Roster tab), so the fix
  there is straightforward — point the note at the right tab. The fourth,
  `pickup_alerts`, doesn't: grepped the whole `tabs/` package and it's
  rendered *only* in `summary_tab.py` — there is no other view of the
  full pickup-alert list to send anyone to yet, so fixing this category
  needs a real full-list view built first, not just a better link.
  Directly relevant to this section, not just a coincidental UX bug: `SC-6`'s
  push notification is going to face the identical "here's the top few,
  and N more" shape, and would hit the exact same dead end if it doesn't
  give the user somewhere to go — this is exactly what `SC-2`'s store
  (read via `SC-11`'s API, or eventually a dedicated view in the app) is
  positioned to be, so treat this old bug as an early warning for that
  design, not a separate concern to fix in isolation later.
- [ ] **CQ-8: Add signal handlers for graceful container shutdown**
  (user-flagged 2026-08-20) — `docker_guidelines.md`'s existing "Graceful
  Shutdown" section already covers half of this (`CMD` exec form so
  signals reach the process at all, confirmed already true for this
  repo's `Dockerfile`), but doesn't yet say anything about the *process
  itself* handling `SIGTERM` and shutting down cleanly within the
  orchestrator's grace period once it receives one. Likely belongs as an
  addition to that same convention section — but `docker_guidelines.md`
  may be AgentConfig-sourced (shared across projects, pulled via
  `/update-from-agentconfig`) rather than owned directly by this repo, so
  the fix might need to flow through AgentConfig rather than a direct
  edit here; confirm which before implementing. Deliberately deferred to
  its own branch, not bundled into unrelated work.

## Deferred / low priority

Judged not worth the time right now; revisit only if the underlying
assumption changes.

- [ ] **DL-1: Handcuff proxy false-positive risk** — depth-chart rank 2 has real
  false-positive risk in modern RB committees. Informational field only,
  not worth revisiting.
- [ ] **DL-2: Exclude a candidate from its own drop-simulation** in
  `recommend_drop` — theoretically possible, vanishingly unlikely to
  surface as a top pick.
- [ ] **DL-3: `team_power_timeline_scores`'s all-teams-missing weighted-age
  edge case** (assistant valuation review, 2026-08-01) —
  `weighted_age.fillna(mean)` only recovers if at least one team has a
  valid weighted age; if literally every roster in the league had zero
  players with a positive FantasyCalc value (never observed — same class
  of edge case the code already flags as "never observed, not
  impossible" for the single-team version), the column would stay
  all-`NaN` and silently propagate into every team's `power_score`. Not
  worth guarding given the odds.
- [ ] **DL-4: Duplicate `positional_strength_summary()` call for the user's own
  roster** (assistant valuation review, 2026-08-01) — now computed once
  via `team_roster_analysis` and again via `team_power_timeline_scores`
  each refresh. Trivial cost at this scale (`gather_state` still
  completes in ~4s); not worth restructuring.
- [ ] **DL-6: `team_name_by_roster_id` can show a duplicated name**
  (assistant valuation review, 2026-08-02) — if an owner's custom Sleeper
  `team_name` happens to equal their `display_name` (username), the
  combined label reads "Bob (Bob)" instead of collapsing to just "Bob".
  Cosmetic edge case, not worth guarding.
- [ ] **DL-5: Review "How this works" expanders for content to extract into the
  Glossary** (user-flagged 2026-08-01) — the Glossary dialog
  (`streamlit_app.py`'s `GLOSSARY`) currently only covers VOR, power
  score, and adj. value, added specifically for the power/timeline read.
  Other sections (Roster needs, Draft Plan) still explain their own terms
  inline inside per-section "How this works" expanders (e.g. Roster
  needs' VOR explanation predates the Glossary and was never migrated).
  Worth a pass to find which of those definitions are genuinely
  reusable/cross-cutting (glossary-appropriate) vs. section-specific
  walkthroughs that belong where they are.
- [ ] **DL-9: Non-fantasy-position filtering happens per-consumer, not once
  at ingest** (user-flagged 2026-08-08, verified during the RT-15 planning
  pass) — `sleeper_api.get_players()` caches Sleeper's full ~14MB/~10k-player
  dataset as-is (every NFL position, including defense/kicker/etc., which
  this league's `roster_positions` has no slot for at all). Audited every
  direct consumer of the raw `players` dict for a leak (`player_pools.py`'s
  `rookie_pool`/`free_agent_pool`/`roster_fantasy_players`/
  `fantasy_relevant_teamed_players`, `lineup.py`'s `player_value_rows`,
  `roster_needs.py`'s `position_replacement_levels`, `trade.py`'s
  candidate-building) — every one of them already checks
  `position in FANTASY_POSITIONS` before a player reaches any real
  computation, so no live bug was found. But the guarantee is enforced by
  convention at each call site, not structurally at the source — a new
  consumer that iterates the raw `players` dict and forgets the check
  would silently let an irrelevant position through. Worth consolidating
  to a single ingest-time (or single shared-helper) filter if a new
  consumer of raw `players` is ever added; not urgent since nothing is
  broken today.
