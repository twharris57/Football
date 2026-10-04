# Python Guidelines

Extends `code_conventions.md`.

## Style

- PEP 8 via a formatter (black/ruff), 88-char lines.
- `snake_case` modules/functions/variables, `PascalCase` classes, `UPPER_SNAKE` constants,
  `_leading_underscore` private.
- Type hints on every signature; return types always. Prefer `X | None`.
- Google-style docstrings, one line unless args/returns need explaining.
- Immutable models: `@dataclass(frozen=True)` or `NamedTuple`.

## Avoid

- Bare `except:`; exceptions for routine control flow.
- Mutable default args — use `None`.
- Comprehensions nested past two levels.
- `**kwargs` passed through layers unread.
- Mutating arguments without saying so.
- `print()` for diagnostics — use `logging.getLogger(__name__)`.

## pandas pitfalls

- **`value or default` doesn't catch `NaN`** (it's truthy). Use `pd.isna()`.
- **One `NULL` makes a whole integer column `float64`** when read through pandas.
  Cast with `int()` after an `isna` check wherever the value is shown.
- **Vectorized comparisons silently return `False` on `None`**; `strptime`/`int()`
  raise. Handle missing values explicitly when swapping one for the other.
