# Design Docs

One doc per completed feature area: a current-state reference for how it
works and why it's built that way — not a change log. Blow-by-blow history
(what changed, when, who found it) belongs in commit messages and PR
descriptions, per `.claude/conventions/git_workflow_simple.md`; these docs
should only ever describe present behavior plus durable rationale (a format
quirk, a proof of optimality, a deliberate tradeoff), so a fact lives in
exactly one place instead of drifting out of sync with itself over time.
When a task in that subsystem's project plan (`.claude/PROJECT_PLAN_DYNASTY.md`
or `.claude/PROJECT_PLAN_CONFIDENCE_POOL.md`) is finished, fold its outcome
into the relevant doc here (updating existing sections rather than
appending a dated entry) and remove it from the plan's Active section.

Docs are grouped by which of the two independent subsystems
(`CLAUDE.md`'s "Architecture") they cover — the two share no code, and
their docs and project plans are kept separate on purpose so neither
accumulates the other's items by mistake.

### Dynasty (`dynasty/`)

| Doc | Covers |
|---|---|
| [`rookie-draft-big-board.md`](rookie-draft-big-board.md) | Valuation and ranking methodology: FantasyCalc + real-scoring correction, marginal-lineup-value ranking, all dashboard features, known limitations/gaps |
| [`dynasty-draft-web-app.md`](dynasty-draft-web-app.md) | The Streamlit + Docker presentation layer on top of the above: tabs, refresh model, Docker/CI setup |
| [`dynasty-data-model.md`](dynasty-data-model.md) | How state persists and stays fresh: the four caching/persistence layers, the raw-import/cached-derived/cheap-derived/on-demand split, and why not a real DB (yet) |

### Confidence pool (`confidence_pool/`)

| Doc | Covers |
|---|---|
| [`confidence-pool-web-app.md`](confidence-pool-web-app.md) | Game-selection rules derived from the Legion pool bylaws, the picks/persistence design, lock-in behavior, season configuration |
