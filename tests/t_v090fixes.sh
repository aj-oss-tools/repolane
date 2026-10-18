#!/usr/bin/env bash
# v0.9.0 leftovers: init's memory link for a plane path with a dot and a space, `lane doctor -v`
# keeping the suite's exit status, `lane done --discard-ignored` with an untracked secret (and when
# worktree removal fails for another reason), and the per-prompt STATE block's dirty count.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

echo "-- init links memory for a plane path containing a dot and a space"
PLANE_DIR_NAME="my plane.v2"; new_sandbox; init_plane >/dev/null 2>&1
slug=$(printf '%s' "$PLANE" | LC_ALL=C sed 's#[^A-Za-z0-9-]#-#g')
assert "memory symlink is under the full-rule slug" test -L "$T/claude/projects/$slug/memory"
assert_eq "and points at the plane's memory" "$PLANE/memory" "$(readlink "$T/claude/projects/$slug/memory")"
unset PLANE_DIR_NAME

echo "-- lane doctor -v keeps the suite's exit status"
new_sandbox
HK="$T/p/scripts/hooks"; mkdir -p "$HK"; cp "$PRODUCT"/scripts/hooks/guard.py "$PRODUCT"/scripts/hooks/guard-check "$HK/"
printf '#!/usr/bin/env bash\necho "  FAIL  stub case"\nexit 3\n' > "$HK/test-guard.sh"
OUT=$(cd "$T" && bash "$HK/guard-check" -v 2>&1); RC=$?
assert_contains "the suite's output is shown" "$OUT" "FAIL  stub case"
assert_eq "a failing suite makes doctor -v fail" 1 "$([ "$RC" != 0 ] && echo 1 || echo 0)"
printf '#!/usr/bin/env bash\necho "  ok    stub"\nexit 0\n' > "$HK/test-guard.sh"
OUT=$(cd "$T" && bash "$HK/guard-check" -v 2>&1); RC=$?
assert_eq "a passing suite still exits 0" 0 "$RC"

echo "-- lane done --discard-ignored with an untracked secret leaves no stale worktree record"
new_sandbox; init_plane >/dev/null 2>&1
make_remote_repo api; add_repo api
WT(){ echo "$PLANE/lanes/$1/$2"; }
lane start U1 api; WU="$(WT U1 api)"; git -C "$WU" push -q origin U1 2>/dev/null
printf 'K\n' > "$WU/id_rsa"
lane done U1 --keep-sessions --discard-ignored
assert_eq "done succeeds" 0 "$RC"
assert "folder gone" test ! -d "$WU"
assert_eq "git has no worktree record for it" "" "$(git -C "$PLANE/repos/api" worktree list --porcelain | grep -F "$WU")"
assert "lane archived" test -f "$PLANE/registry/lanes/done/U1.md"

echo "-- worktree removal failing for another reason never archives the lane"
lane start U2 api; WU2="$(WT U2 api)"; git -C "$WU2" push -q origin U2 2>/dev/null
printf 'K\n' > "$WU2/id_rsa"
git -C "$PLANE/repos/api" worktree lock "$WU2"
lane done U2 --keep-sessions --discard-ignored
assert_eq "done fails" 1 "$RC"
assert "folder still there" test -f "$WU2/id_rsa"
assert "lane not archived" test ! -f "$PLANE/registry/lanes/done/U2.md"
assert "lane file still active" test -f "$PLANE/registry/lanes/U2.md"
git -C "$PLANE/repos/api" worktree unlock "$WU2"
lane done U2 --keep-sessions --discard-ignored; assert_eq "after the cause is fixed done succeeds" 0 "$RC"

echo "-- STATE block 'uncommitted' ignores untracked secrets, like lane status"
lane start U3 api; WU3="$(WT U3 api)"; printf 'S=1\n' > "$WU3/.env.local"
stb(){ printf '{"hook_event_name":"UserPromptSubmit","cwd":"%s","session_id":"u3"}' "$WU3" | python3 "$PLANE/scripts/hooks/guard.py" 2>/dev/null; }
assert_contains "untracked secret: uncommitted 0" "$(stb)" "uncommitted: 0"
printf 'w\n' > "$WU3/plain.txt"
assert_contains "a plain untracked file still counts" "$(stb)" "uncommitted: 1"

finish
