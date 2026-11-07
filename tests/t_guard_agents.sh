#!/usr/bin/env bash
# The guard's cases, through every adapter. scripts/hooks/test-guard.sh runs under Claude Code in its own right; here it runs again
# through Antigravity's, by way of scripts/agents/translate.py. A difference is either listed below with its reason, or it fails:
# a listed one that stops happening fails too, so this list cannot go stale. A new agent gets a translator and a list of its own.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
# label pattern (grep -E, on the FAIL line) | why
EXPECTED='EnterWorktree from worktree$|No EnterWorktree tool on agy (no ENTER_LANE): the call reaches the guard as an unknown tool, naming no path, and gets ask, not deny
EnterWorktree name=<id>/<repo>$|same
EnterWorktree with nothing$|same
name=<id>/<repo> is not a thing$|same
name=<id>/<repo> unknown repo$|same
name=<unknown>/<repo>$|same
EnterWorktree path=own lane root$|same: its path is inside the lane, so the unknown-tool scan has nothing to refuse
EnterWorktree name=own lane$|same
EnterWorktree name=another lane$|same
EnterWorktree name is a list$|same: an unknown tool has no field types to check, so a list is scanned, not refused as malformed
Write .*/schema/generated/x.py$|A project rule says tool: Edit. On agy that means the WRITE kind, because write_file and edit_file are one rule to the person who wrote it, so it also refuses this Write. Stricter than Claude Code, on purpose'
out=$(LANE_GUARD_AGENT=antigravity bash "$PRODUCT/scripts/hooks/test-guard.sh" 2>&1)
fails=$(printf '%s\n' "$out" | grep '^  FAIL' | sed -E 's#/[^ ]*/lane-test-guard\.[A-Za-z0-9]+##g')
total=$(printf '%s\n' "$out" | grep -E '^[0-9]+/[0-9]+ cases passed' | cut -d' ' -f1)
assert_contains "the suite ran to its end" "$total" "/"
assert "it ran well over a thousand cases" test "${total#*/}" -gt 1000
n_fail=$(printf '%s' "$fails" | grep -c . || true)
assert_eq "the suite's own count agrees with the FAIL lines" "$n_fail" "$(( ${total#*/} - ${total%/*} ))"
left="$fails"
while IFS='|' read -r pat why; do
  [ -n "$pat" ] || continue
  if printf '%s\n' "$fails" | grep -Eq "$pat"; then ok "expected difference: $pat"
  else bad "a listed difference no longer happens, take it off the list: $pat"; fi
  left=$(printf '%s\n' "$left" | grep -Ev "$pat" || true)
done <<EOT
$EXPECTED
EOT
assert_eq "no difference that is not listed" "" "$left"
assert_not_contains "no fixture or section failed outright" "$out" "this section ran no cases"
finish
