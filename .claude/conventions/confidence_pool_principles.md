# Confidence Pool Principles

Domain rules for the confidence-pool app (`confidence_pool/`). Generic lessons live in
`code_conventions.md`; the design itself is in `docs/confidence-pool.md`.

The app exists as a reliable fallback for weeks the user can't check in. Behavior
while nobody is watching is what matters most.

- **Unattended actions reuse the last reviewed state.** The deadline lock persists the
  saved picks — values *and* timestamps — and only recomputes from live odds when
  nothing was saved (`resolve_week_lock()`).
- **A safety net that does nothing says so.** If the lock can't save (e.g. odds not
  posted), show a warning.
- **Late-season rules are defaults verified every season.** Which weeks count every
  game changes with the bylaws (`store.KNOWN_LATE_SEASON_WEEKS`). Weeks must still pick
  correctly before anyone visits Settings.
- **Record the card as submitted.** The bylaws resolve duplicate points (rule 7), blank
  points (15), and unmarked winners (16). Store and flag these; don't reject them.
- **Scores can be 0 or negative** (all picks wrong; late-card penalty, rule 2), so 0
  can't mean "not entered."
- **Kickoff times can be missing** for flex-scheduled games. `'standard'` weeks exclude
  an unknown kickoff; `'all_games'` weeks include it.
- **Save every evaluated game with its `included` flag** (`games_with_included_flags()`),
  so an excluded game stays excluded on reload.
