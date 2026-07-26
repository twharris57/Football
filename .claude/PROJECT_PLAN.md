# Project Plan

Tracks what's actively being worked on, what's queued up next, and longer-range
ideas for this project. When a task is completed, write it up as a design doc
in `docs/` (what was built and why, key decisions) and remove it from this file.

## Active

- **Rookie draft big board + web dashboard** (branch: `feature/rookie-draft-strategy`,
  PR open) — `dynasty_core.py` pulls the Sleeper league (rosters, draft,
  traded picks, players) plus FantasyCalc dynasty values, and produces a
  tiered board of available rookies cross-referenced against roster needs,
  plus which picks the user owns (including trades) and who's on the clock.
  Two front ends share that logic: `rookie_draft.py` (CLI, interactive
  refresh loop) and `streamlit_app.py` (web dashboard, sidebar refresh
  buttons), containerized (`Dockerfile`, `docker-compose*.yml`) and published
  to GHCR via GitHub Actions on merge to `main`, for deployment to the
  Synology NAS. Locally verified end-to-end against the real league (id
  `1324888291937386496`): CLI output unchanged after the `dynasty_core.py`
  extraction, Streamlit renders real data with no exceptions, Docker image
  builds/runs/passes its healthcheck, and the players cache survives a
  container restart. **Explainability requirement carried over from the
  "Web UI" item below is not yet addressed** — the dashboard still shows
  FantasyCalc's ranking as-is, no "why" surfaced per pick.
  Remaining before this is "done": merge, confirm the GHCR publish + NAS
  deploy work, use it through the actual live draft (next Sunday) to see
  whether the needs heuristic and tiering are useful in the moment, then
  write up `docs/rookie-draft-big-board.md` + `docs/dynasty-draft-web-app.md`
  and clear this item.

## Future Ideas

- **Trade targets & sells** — given the rebuild strategy, flag which of the
  user's veterans are sellable for picks, and which other teams' picks/young
  players might be realistically available.
- **League-wide power/timeline read** — place every team in the league on a
  rebuild-vs-contend spectrum, to identify good trade partners (contenders who
  overpay for immediate help, rebuilders who overpay for future assets).
- **Free agent / roster-moves evaluator** — a tool for right-now decisions
  outside the draft: which available free agents are worth an add, and which
  current roster players are droppable, given the rebuild timeline.

## Context

- Dynasty league (keep all players year to year; rookies only enter via the
  rookie draft).
- User's strategy since year one: accumulate young talent, accept being
  near the bottom of the league short-term, aiming to be competitive within
  ~2-3 years.

### Valuation approach and its known gaps

Player/rookie value currently comes entirely from FantasyCalc's public dynasty
rankings (`fantasycalc_api.py`) — this project has no valuation model of its
own. FantasyCalc's API only lets us tune for superflex (`numQbs=2`), league
size (`numTeams=12`), and PPR (`ppr=1.0`); it has **no parameter for this
league's other non-standard scoring settings**, so its rankings are a
generic superflex-PPR model, not this league's actual scoring:

- **6-point passing touchdowns** (`pass_td: 6.0`) instead of the far more
  common 4-point — this makes QBs worth more here than a generic superflex
  ranking assumes.
- **TE premium**: +0.5 per reception for tight ends on top of full PPR
  (`bonus_rec_te: 0.5`) — this makes TEs worth more here than a generic
  full-PPR ranking assumes.
- Bonus points for long touchdowns (40+/50+ yard, rush/pass/rec) and a
  first-down bonus (`rush_fd`/`rec_fd: 0.5`) — smaller effects, reward
  big-play and chain-moving players slightly more than raw yardage would.
- Not a scoring setting, but relevant to roster/pick strategy: taxi squad is
  unusually generous (5 slots, 3 years) vs. typical dynasty leagues — more
  room to stash rookies without a roster crunch.

None of this is corrected for yet — the big board currently shows FantasyCalc's
values as-is. Before or alongside the Web UI work, decide whether to
manually adjust (e.g., nudge QB/TE tiers) or at minimum make this mismatch
visible in whatever output the user sees, so recommendations aren't taken
as more precise than they are.
