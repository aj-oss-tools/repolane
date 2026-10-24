#!/usr/bin/env bash
# A dispatcher session started at the root that enters a lane with EnterWorktree keeps the root's permissions (a lane's
# settings.local.json only applies to a session started inside the lane). LANE.md tells it to save the Goal with
# `lane-memory goal` and draft memories with `lane-memory draft`, so the root pre-approves exactly those two, in a
# workspace's .claude/settings.json and in a clone's root settings.local.json. `lane-memory file` still asks, and
# lane-memory still refuses another lane's Goal from inside a lane.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
new_sandbox
install_product
unset -f lane
CLEAN_PATH=$(printf '%s' "$PATH" | tr ':' '\n' | while IFS= read -r d; do [ -n "$d" ] && [ ! -e "$d/lane" ] && printf '%s:' "$d"; done)
export PATH="$BIN:${CLEAN_PATH%:}"
L(){ local d="$1"; shift; OUT=$(cd "$d" && env -u LANE_WORKSPACE lane "$@" </dev/null 2>&1); RC=$?; }
allow(){ python3 -c 'import json,sys; print("\n".join(json.load(open(sys.argv[1])).get("permissions",{}).get("allow",[])))' "$1"; }

echo "-- a workspace's root settings pre-approve lane-memory goal and draft"
W="$T/ws"; mkdir -p "$W"
L "$W" init --owner Sam --yes --claude-home "$T/claude"; assert_eq "init" 0 "$RC"
a=$(allow "$W/.claude/settings.json")
assert_contains "Bash(lane-memory goal:*)" "$a" "Bash(lane-memory goal:*)"
assert_contains "Bash(lane-memory draft:*)" "$a" "Bash(lane-memory draft:*)"
assert_not_contains "lane-memory file still asks" "$a" "lane-memory file"
assert_not_contains "and no blanket lane-memory approval" "$a" "Bash(lane-memory:*)"

echo "-- a workspace set up before is brought up to date: by lane doctor --fix, and by the refresh after an upgrade"
python3 - "$W/.claude/settings.json" <<'PY'
import json,sys; p=sys.argv[1]; d=json.load(open(p))
d["permissions"]["allow"]=[x for x in d["permissions"]["allow"] if "goal" not in x and "draft" not in x]+["Bash(my-own:*)"]
json.dump(d,open(p,"w"),indent=2)
PY
L "$W" doctor; assert_eq "doctor fails while they are missing" 1 "$RC"
assert_contains "and names them" "$OUT" "does not pre-approve Bash(lane-memory draft:*), Bash(lane-memory goal:*)"
L "$W" doctor --fix --yes
assert_contains "doctor --fix adds goal" "$(allow "$W/.claude/settings.json")" "Bash(lane-memory goal:*)"
assert_contains "and keeps the user's own" "$(allow "$W/.claude/settings.json")" "Bash(my-own:*)"
python3 - "$W/.claude/settings.json" <<'PY'
import json,sys; p=sys.argv[1]; d=json.load(open(p))
d["permissions"]["allow"]=[x for x in d["permissions"]["allow"] if "goal" not in x and "draft" not in x]
json.dump(d,open(p,"w"),indent=2)
PY
echo 0.0.1 > "$W/.repolane/version"
L "$W" status
assert_contains "the refresh after an upgrade adds goal" "$(allow "$W/.claude/settings.json")" "Bash(lane-memory goal:*)"
assert_contains "and draft" "$(allow "$W/.claude/settings.json")" "Bash(lane-memory draft:*)"
assert_contains "and keeps the user's own" "$(allow "$W/.claude/settings.json")" "Bash(my-own:*)"

echo "-- a root-started session that entered L1 saves L1's Goal, and is refused L2's"
make_remote_repo api
L "$W" add "$T/remotes/api.git" api --yes
L "$W" start L1 api; L "$W" start L2 api:l2
g(){ printf '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"%s"},"cwd":"%s","session_id":"s"}' "$1" "$W/lanes/L1" \
     | (cd "$W/lanes/L1" && CLAUDE_PROJECT_DIR="$W" lane hook pre-tool-use) 2>&1; }
assert_not_contains "the guard lets lane-memory goal through" "$(g 'lane-memory goal \"compare the two\"')" '"deny"'
o=$(cd "$W/lanes/L1" && CLAUDE_PROJECT_DIR="$W" lane-memory goal "compare the two repos" 2>&1); rc=$?
assert_eq "lane-memory goal from inside L1 saves it" 0 "$rc"
assert_contains "  in L1's file" "$(cat "$W/.repolane/registry/lanes/L1.md")" "compare the two repos"
o=$(cd "$W/lanes/L1" && CLAUDE_PROJECT_DIR="$W" lane-memory goal L2 "not yours" 2>&1); rc=$?
assert_eq "L2's Goal from inside L1 is refused" 1 "$rc"
assert_contains "  and says why" "$o" "can only set that lane's Goal"
assert_not_contains "  and L2's file is untouched" "$(cat "$W/.repolane/registry/lanes/L2.md")" "not yours"

echo "-- a clone's root settings.local.json pre-approves them too (its settings.json is lane init's to edit)"
init_plane >/dev/null 2>&1
a=$(allow "$PLANE/.claude/settings.local.json" 2>/dev/null)
assert_contains "clone: Bash(lane-memory goal:*)" "$a" "Bash(lane-memory goal:*)"
assert_contains "clone: by absolute path" "$a" "Bash($PLANE/scripts/lane-memory goal:*)"
assert_contains "clone: Bash(lane-memory draft:*)" "$a" "Bash(lane-memory draft:*)"
assert_not_contains "clone: lane-memory file still asks" "$a" "lane-memory file"
assert_eq "clone: .claude/settings.json's allow list is as shipped" "$(git -C "$PLANE" show HEAD:.claude/settings.json | python3 -c 'import json,sys;print(json.load(sys.stdin)["permissions"]["allow"])')" \
  "$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["permissions"]["allow"])' "$PLANE/.claude/settings.json")"
finish
