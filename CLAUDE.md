# Project guidelines for Claude

## Git & GitHub — the user does all of it

**Claude must never perform any git write or GitHub action in this repo.** The
user performs every commit, push, pull, merge, rebase, branch/tag change, and
all GitHub (`gh` / PR / release) operations themselves.

- **Do not** run: `git commit`, `git push`, `git pull`, `git fetch`,
  `git merge`, `git rebase`, `git reset`, `git revert`, `git cherry-pick`,
  `git tag`, `git add`, `git rm`, `git restore`, `git checkout`, `git switch`,
  `git branch`, `git stash`, `git remote`, `git clone`, `git worktree`,
  `git apply`, `git am`, or any `gh` command.
- **Allowed:** read-only inspection only — `git status`, `git log`, `git diff`,
  `git show`, `git blame`, `git ls-files`, `git for-each-ref`, etc.
- When work is done, **leave changes uncommitted** in the working tree and tell
  the user what to commit. Never stage or commit on their behalf.
- Never add a `Co-Authored-By: Claude` trailer or any Claude attribution to
  commits or PRs (attribution is also disabled in `.claude/settings.json`).

This is enforced mechanically by `.claude/settings.json` (permission `deny`
rules + a `PreToolUse` hook, `.claude/hooks/git-guard.sh`) — the guard blocks
these commands even in compound form. Treat this document as the intent behind
that enforcement, not a soft suggestion.
