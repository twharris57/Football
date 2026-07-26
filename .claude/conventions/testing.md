# Testing Guidelines

> **Project teams:** replace or extend this file with project-specific testing conventions.
> The guidance below reflects broadly applicable defaults.

## Scope

- Unit tests for services and domain logic.
- Integration tests for anything that crosses a real system boundary (database, file
  system, external API). Do not mock these boundaries — mocks that pass while production
  diverges are worse than no test.
- UI automation tests only when explicitly scoped — they are high maintenance and should
  not be the primary safety net.

## Default Frameworks

Start with the ecosystem default unless the project has a reason to deviate:

| Language | Default framework |
|----------|------------------|
| Python | pytest |
| C# / .NET | xUnit |
| Java | JUnit 5 |
| TypeScript / JavaScript | Vitest (or Jest for legacy projects) |

## Test Structure

- Tests live in a separate project or directory, not alongside production code.
- One test class (or module) per production class or module.
- Test names should communicate the scenario and expected outcome:
  `MethodName_Scenario_ExpectedResult` or an equivalent readable form.

## What Not to Mock

Do not mock at system boundaries you own. Integration tests must hit real implementations
(real database, real file I/O) to catch schema mismatches and serialization issues that
mocks cannot surface.

Mock only external services you do not control (third-party APIs, email providers,
payment processors, etc.).

## Timing in Tests

Use relative time offsets from "now" rather than hardcoded timestamps. This makes tests
timezone-agnostic and avoids date-sensitive failures as time passes. Most language
standard libraries provide utilities for this (e.g., adding/subtracting a duration from
the current instant).
