# Design Docs

One doc per completed feature area: a current-state reference for how it
works and why it's built that way — not a change log. Blow-by-blow history
(what changed, when, who found it) belongs in commit messages and PR
descriptions, per `.claude/conventions/git_workflow_simple.md`; these docs
should only ever describe present behavior plus durable rationale (a format
quirk, a proof of optimality, a deliberate tradeoff), so a fact lives in
exactly one place instead of drifting out of sync with itself over time.
When a task in `.claude/PROJECT_PLAN.md` is finished, fold its outcome into
the relevant doc here (updating existing sections rather than appending a
dated entry) and remove it from the plan's Active section.

| Doc | Covers |
|---|---|
| [`rookie-draft-big-board.md`](rookie-draft-big-board.md) | Valuation and ranking methodology: FantasyCalc + real-scoring correction, marginal-lineup-value ranking, all dashboard features, known limitations/gaps |
| [`dynasty-draft-web-app.md`](dynasty-draft-web-app.md) | The Streamlit + Docker presentation layer on top of the above: tabs, refresh model, Docker/CI setup |
