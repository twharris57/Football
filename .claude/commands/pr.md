# /pr

Create (`/pr`) or update (`/pr update`) the pull request for the current branch.

## Instructions

1. **Check the branch.** Stop if on `main`. Stop and ask if the tree isn't clean.
   Read `git log main..HEAD` to see what the PR contains.
2. **Run the pre-PR gate** from the active git workflow convention (build, tests,
   versioning) plus: remove finished items from the project plan. Stop on any failure.
3. **Write the description** using the template in the git workflow convention.
   Checklist boxes record what was actually verified.
4. **Create or update:**
   - New: `gh pr create --base main --title "<title>" --body "<description>"`
   - Update: `gh pr edit --body "..."`, with a note at the top on what changed since review.
   - Never run `gh pr merge` without explicit user approval.
5. **Report** the URL, a whole-branch summary, and anything the reviewer should look at.
