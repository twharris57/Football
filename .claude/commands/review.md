# /review

Run a pre-commit checklist on staged changes before committing.

## Instructions

1. Run `git diff --staged` (or `git diff HEAD` if nothing is staged).

2. Check for:

   **Security**
   - Command injection, XSS, SQL injection, path traversal
   - Hardcoded secrets, API keys, or credentials
   - Insecure deserialization or unsafe use of user input
   - Exposed internal details in error messages

   **Data integrity**
   - Destructive operations without user confirmation
   - Silent data loss paths (unhandled exceptions that drop state)
   - Serialization changes that would corrupt or silently drop existing persisted data
   - Missing error handling at system boundaries (user input, external APIs, file I/O)

   **UX regressions**
   - Interactions that break or alter existing user flows
   - Form validation that no longer fires or fires in the wrong order
   - Missing error or empty states for new UI paths

   **Build**
   - Unresolved imports or missing dependencies visible in the diff
   - Type errors or obvious compilation issues

   **Conventions**
   - Patterns that conflict with the project's coding guidelines in `CLAUDE.md`
   - Commented-out code, TODO comments, or debug-level log calls in production paths

3. Report all findings before committing. Do not auto-fix without user confirmation.
