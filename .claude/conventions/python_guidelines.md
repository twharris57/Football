# Python Coding Guidelines

See `code_conventions.md` for universal hygiene rules (no commented-out code, no TODO
comments, no debug logs in production, logging philosophy, immutability principle).

> **Project teams:** this file provides structural defaults. Extend it with
> project-specific conventions as they are established.

## Style

- Follow PEP 8. Use a formatter (black or ruff) rather than enforcing style manually.
- Maximum line length: 88 characters (black default) unless the project overrides this.

## Naming

- Modules and packages: `snake_case`
- Classes: `PascalCase`
- Functions, methods, variables: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Private members: `_leading_underscore`

## Type Hints

- Add type hints to all function signatures. Return types are mandatory; parameter
  types are mandatory for public interfaces.
- Use `from __future__ import annotations` for forward references in Python < 3.10.
- Prefer `X | None` over `Optional[X]` in Python 3.10+.

## Docstrings

Use docstrings on public modules, classes, and functions. One-line docstrings for
obvious functions; multi-line for anything with non-trivial behavior, parameters, or
return semantics. Google style is recommended:

```python
def fetch_items(user_id: int, limit: int = 100) -> list[Item]:
    """Return items owned by the given user.

    Args:
        user_id: The owner's database ID.
        limit: Maximum number of items to return.

    Returns:
        Items in descending creation order, capped at limit.
    """
```

Do not document what the code does — name identifiers well. Document preconditions,
return semantics, and non-obvious side effects.

## Immutability

Prefer immutable data for domain models and DTOs. The idiomatic approach is
`@dataclass(frozen=True)`:

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class OrderSummary:
    id: str
    total: Decimal
```

`NamedTuple` is also a good option for lightweight immutable value types.

## Code Smells

See `code_conventions.md` for universal design principles. Python-specific additions:

- **Avoid nested comprehensions beyond two levels.** A list comprehension inside a list
  comprehension is usually readable; a third level is not. Extract the inner logic to a
  named function.
- **Don't use exceptions for control flow** in normal code paths. `try/except` for an
  expected, routine condition (e.g., checking whether a key exists) is slower and
  obscures intent compared to an explicit check. Reserve exceptions for genuinely
  exceptional conditions.
- **`**kwargs` forwarded through multiple layers** without being inspected hides what a
  function actually depends on. Prefer explicit parameters for anything the function uses.
- **Avoid mutating arguments in place** without documenting it clearly. Callers expect
  functions to return new values, not silently modify their inputs.

## Code Hygiene

Universal rules (no commented-out code, no TODO comments, no debug logs) are in
`code_conventions.md`. Python-specific additions:

- No bare `except:` clauses — always catch a specific exception type.
- No mutable default arguments: use `None` as the default and assign inside the
  function body (`items = items or []`), not `def f(items=[])`.
- No `print()` for diagnostics in committed code — use `logging`.

## Logging

Use the standard `logging` module. Never use `print()` for diagnostics in committed code.

```python
import logging
logger = logging.getLogger(__name__)
```

Follow the philosophy in `code_conventions.md`. Python level identifiers: `DEBUG`,
`INFO`, `WARNING`, `ERROR`, `CRITICAL`.

| Level | When |
|-------|------|
| `INFO` | User-initiated actions or significant application events |
| `WARNING` | Unexpected-but-recoverable conditions |
| `ERROR` | Exceptions and failures |
| `DEBUG` | Development diagnostics only — must not appear in committed production code |
