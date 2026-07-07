#!/usr/bin/env bash
# PreToolUse(Bash) guard: block Claude from running git write/remote or GitHub
# (gh) commands. The user performs ALL commits, pushes, merges, and GitHub
# actions themselves. Read-only git (status/log/diff/show/…) stays allowed.
#
# Catches compound/prefixed forms too (e.g. `git add -A && git commit`,
# `cd x && git push`, `GIT_EDITOR=true git commit`).
input=$(cat)
cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // ""' 2>/dev/null)
[ -z "$cmd" ] && exit 0

GITW='(^|[^[:alnum:]_])git[[:space:]]+(add|commit|push|pull|fetch|merge|rebase|cherry-pick|revert|reset|restore|checkout|switch|branch|tag|stash|am|apply|remote|clone|worktree|rm|mv|update-ref)([[:space:]]|[;&|)]|$)'
GH='(^|[^[:alnum:]_])gh([[:space:]]|$)'

if printf '%s' "$cmd" | grep -qiE "$GITW" || printf '%s' "$cmd" | grep -qiE "$GH"; then
  jq -n '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:"Blocked by project policy (.claude/hooks/git-guard.sh): Claude does not run git write/remote or GitHub (gh) commands. You perform all commits, pushes, merges, and GitHub actions yourself. Read-only git (status/log/diff/show) is allowed."}}'
fi
exit 0
