# Testing

- **pytest** for Python. Tests live in `tests/`, one module per production module.
- Name tests for scenario and outcome: `test_<function>_<scenario>_<result>`.
- Unit-test domain logic. Hit real boundaries you own (SQLite, files) — don't mock them.
  Mock only third-party services.
- Use times relative to now, not hardcoded timestamps.
- Cover every input shape a producer can emit, including mixed present/missing data —
  not just the case the change was written for.
