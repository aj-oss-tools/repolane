#!/usr/bin/env bash
# The product root and the workspace root are separate, not just named apart: with LANE_PRODUCT at a copy of the product
# files and LANE_WORKSPACE at an empty folder, init / add / start / brief / status write the user's data only into the
# workspace, never into the product, and the guard (run the way a session's hook runs it) judges the workspace.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
new_sandbox
# the product under the (throwaway) home, as an installed package is, where the guard refuses whatever is not the plane's
PROD="$HOME/.local/share/repolane-product"; WS="$T/workspace"; mkdir -p "$PROD" "$WS"
copy_product_tree "$PROD"; rm -rf "$PROD/tests" "$PROD/docs" "$PROD/.github" "$PROD/.git"
before=$(cd "$PROD" && find . -type f | LC_ALL=C sort | xargs cksum)
L(){ OUT=$(cd "$T" && LANE_PRODUCT="$PROD" LANE_WORKSPACE="$WS" "$PROD/lane" "$@" </dev/null 2>&1); RC=$?; }

echo "-- init fills the workspace from the product's templates"
L init --owner "Test" --yes --claude-home "$T/claude"; assert_eq "init succeeds" 0 "$RC"
for f in registry/config.yml registry/repos.yaml memory/MEMORY.md knowledge/preferences.md CLAUDE.md; do
  assert "workspace has $f" test -f "$WS/$f"
done
assert_contains "CLAUDE.md came from the product's template, with the owner filled in" "$(cat "$WS/CLAUDE.md")" "Test"
assert "the status line points at the product, naming the workspace" grep -q "LANE_WORKSPACE=$WS $PROD/scripts/statusline.sh" "$WS/.claude/settings.json"
assert "memory linked from Claude's project folder to the workspace" test "$(readlink "$T/claude/projects/$(printf '%s' "$WS" | LC_ALL=C sed 's#[^A-Za-z0-9-]#-#g')/memory")" = "$WS/memory"

echo "-- add / start / brief / status act on the workspace"
make_remote_repo web
L add "$T/remotes/web.git" web; assert_eq "add succeeds" 0 "$RC"
assert "the mirror is in the workspace" test -d "$WS/repos/web/.git"
L start L1 web; assert_eq "start succeeds" 0 "$RC"
assert "the worktree is in the workspace" test -e "$WS/lanes/L1/web/.git"
assert "the lane file is in the workspace" test -f "$WS/registry/lanes/L1.md"
L brief L1; assert_eq "brief succeeds" 0 "$RC"; assert_contains "brief names the lane's repo" "$OUT" "web"
L status; assert_eq "status succeeds" 0 "$RC"; assert_contains "status lists the lane" "$OUT" "L1"
L --version; assert_eq "version is the product's" "lane $(tr -d '[:space:]' < "$PROD/VERSION")" "$OUT"
after=$(cd "$PROD" && find . -type f -not -path '*/__pycache__/*' | LC_ALL=C sort | xargs cksum)
assert_eq "nothing was written into the product" "$before" "$after"

echo "-- the guard, run the way the lane's hook runs it"
S="$WS/lanes/L1/.claude/settings.local.json"
cmd=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["hooks"]["PreToolUse"][0]["hooks"][0]["command"])' "$S" 2>/dev/null)
assert_contains "the hook runs the product's guard" "$cmd" "$PROD/scripts/hooks/guard.py"
assert_contains "and names the workspace itself (a hook does not get our environment)" "$cmd" "LANE_WORKSPACE=$WS"
assert_contains "lane scripts are pre-approved at the product's path" "$(cat "$S")" "Bash($PROD/scripts/lane-brief:*)"
decide(){ # decide <tool> <cwd> <tool_input-json> : deny, or pass (allowed or undecided), through the hook command as written
  printf '{"hook_event_name":"PreToolUse","tool_name":"%s","cwd":"%s","tool_input":%s}' "$1" "$2" "$3" \
    | env -u LANE_PRODUCT -u LANE_WORKSPACE sh -c "$cmd" 2>/dev/null \
    | python3 -c 'import json,sys
try: d=json.load(sys.stdin)["hookSpecificOutput"]["permissionDecision"]
except Exception: d="pass"
print("deny" if d=="deny" else "pass")'; }
LW="$WS/lanes/L1"
printf 'K=1\n' > "$WS/repos/web/.env"
assert_eq "reading the workspace mirror's .env is refused" deny "$(decide Read "$LW" "{\"file_path\":\"$WS/repos/web/.env\"}")"
assert_eq "writing a workspace memory directly is refused" deny "$(decide Write "$LW" "{\"file_path\":\"$WS/memory/new.md\"}")"
assert_eq "writing the product's scripts from a lane is refused" deny "$(decide Write "$LW" "{\"file_path\":\"$PROD/scripts/lib.sh\"}")"
assert_eq "reading the product's scripts is not refused" pass "$(decide Read "$LW" "{\"file_path\":\"$PROD/scripts/lib.sh\"}")"
assert_eq "ordinary work in the lane is not refused" pass "$(decide Write "$LW" "{\"file_path\":\"$LW/web/a.txt\"}")"
assert_eq "a lane script by the product's absolute path is not refused" pass "$(decide Bash "$LW" "{\"command\":\"$PROD/scripts/lane-brief L1\"}")"

echo "-- and the default is unchanged: one folder, the one the product sits in"
init_plane >/dev/null 2>&1; add_repo web
lane start L2 web; assert_eq "start in a clone succeeds" 0 "$RC"
assert "a clone's lane hook is still the bare path" python3 -c '
import json,sys; s=json.load(open(sys.argv[1]))
c=s["hooks"]["PreToolUse"][0]["hooks"][0]["command"]; sys.exit(0 if c==sys.argv[2] else 1)' "$PLANE/lanes/L2/.claude/settings.local.json" "$PLANE/scripts/hooks/guard.py"

finish
