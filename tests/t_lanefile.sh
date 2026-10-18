#!/usr/bin/env bash
# A session inside a lane must be able to read and edit its OWN lane file (registry/lanes/<id>.md:
# the Goal, Findings and log) and nothing else under registry/. The file lives in the control plane
# root, outside the lane's folder, and Claude Code only lets a session touch paths outside its
# folder when its settings allow them by rule. The guard already allowed the edit; without the
# rules, Claude Code itself refused ("you haven't granted it yet") and the session could not save
# its Goal. In a rule, a leading // means an absolute path; a single / is relative to the project
# and matches nothing here, so the form of the rule is part of what is tested.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
new_sandbox; init_plane >/dev/null 2>&1
make_remote_repo api; make_remote_repo web; add_repo api; add_repo web

# allow_rules <settings.json> : the Read/Edit rules that name something under registry/
allow_rules(){ python3 -c '
import json,sys
d=json.load(open(sys.argv[1]))
print("\n".join(sorted(x for x in d.get("permissions",{}).get("allow",[]) if x.startswith(("Read(","Edit(")) and "registry" in x)))' "$1"; }
guard_decision(){ # <tool> <file> <lane> : prints "deny" or "no deny", judged from inside lane <lane>
  local out; out=$(printf '{"hook_event_name":"PreToolUse","tool_name":"%s","tool_input":{"file_path":"%s","old_string":"x","new_string":"y","content":"y"},"cwd":"%s/lanes/%s","session_id":"s1"}' \
    "$1" "$2" "$PLANE" "$3" | CLAUDE_PROJECT_DIR="$PLANE/lanes/$3" python3 "$PLANE/scripts/hooks/guard.py" 2>/dev/null)
  case "$out" in *'"deny"'*) echo deny ;; *) echo "no deny" ;; esac; }

lane start L1 api; assert_eq "start L1" 0 "$RC"
lane start L2 web; assert_eq "start L2" 0 "$RC"
F1="$PLANE/registry/lanes/L1.md"; F2="$PLANE/registry/lanes/L2.md"
S1="$PLANE/lanes/L1/.claude/settings.local.json"

echo "-- the lane's settings allow its own lane file, by an absolute-path rule"
want=$(printf 'Edit(/%s)\nRead(/%s)' "$F1" "$F1")        # "/" + an absolute path = the // form
assert_eq "lane root: Read and Edit of registry/lanes/L1.md, and only that" "$want" "$(allow_rules "$S1")"
assert_contains "the rule starts with // (absolute), not a single /" "$(allow_rules "$S1")" "Read(//"
assert_not_contains "no rule for another lane's file" "$(allow_rules "$S1")" "L2.md"
assert_not_contains "no rule for the whole registry/lanes folder" "$(allow_rules "$S1")" "lanes/**"
assert_eq "a session rooted in a worktree gets the same rules" "$want" "$(allow_rules "$PLANE/lanes/L1/api/.claude/settings.local.json")"
assert_not_contains "L2 is allowed its own file, not L1's" "$(allow_rules "$PLANE/lanes/L2/.claude/settings.local.json")" "L1.md"

echo "-- a refresh puts the rule back, and drops a stale one"
python3 - "$S1" "$F1" "$F2" <<'EOF'
import json,sys
p,f1,f2=sys.argv[1:]; d=json.load(open(p)); a=d["permissions"]["allow"]
a[:]=[x for x in a if "registry" not in x]+[f"Read(/{f2})"]          # an install from before: no rule, plus a rule for the wrong lane
json.dump(d,open(p,"w"),indent=2)
EOF
lane resume L1 --keep-sessions >/dev/null 2>&1 || lane resume L1 >/dev/null 2>&1
assert_eq "after lane resume: its own file again" "$want" "$(allow_rules "$S1")"

echo "-- the guard still holds the line inside the lane"
assert_eq "Edit of its own lane file is not denied" "no deny" "$(guard_decision Edit "$F1" L1)"
assert_eq "Write of its own lane file is not denied" "no deny" "$(guard_decision Write "$F1" L1)"
assert_eq "Edit of another lane's file is denied" "deny" "$(guard_decision Edit "$F2" L1)"
assert_eq "Edit of the repo list is denied" "deny" "$(guard_decision Edit "$PLANE/registry/repos.yaml" L1)"

echo "-- the CLAUDE.md template names the one exception"
assert_contains "template rule 12 carves out the lane's own file" "$(cat "$PRODUCT/CLAUDE.md.template")" "your own"
assert_contains "and says nothing else under registry/ is theirs" "$(cat "$PRODUCT/CLAUDE.md.template")" "Nothing else under \`registry/\` is yours"

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" = 0 ]
