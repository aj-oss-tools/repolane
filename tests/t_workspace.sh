#!/usr/bin/env bash
# A workspace: the product installed once (a built wheel when a builder is here, otherwise the checkout named by
# LANE_PRODUCT, the way the package's launcher names it), and a folder with .repolane/ holding the user's data. Every
# check below runs the real commands from the workspace's own folders, through `lane` on PATH, and pipes real hook JSON
# into the hook commands exactly as written in the generated settings.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
new_sandbox

# ------------------------------------------------------------------------------------------- the installed product
install_product
export PATH="$BIN:$PATH"
assert_eq "lane on PATH is the installed product's" "$BIN/lane" "$(type -P lane)"
PROD_SUM(){ (cd "$PROD" && find . -type f | LC_ALL=C sort | xargs cksum); }
prod_before=$(PROD_SUM)
WS="$T/ws"; D="$WS/.repolane"
W(){ local d="$1"; shift; OUT=$(cd "$d" && env -u LANE_WORKSPACE -u LANE_PRODUCT lane "$@" </dev/null 2>&1); RC=$?; }

echo "-- an empty workspace layout"
mkdir -p "$WS/.claude"
printf '# My notes\n\nkeep this line\n' > "$WS/CLAUDE.md"
printf '{"env":{"MINE":"1"},"hooks":{"Stop":[{"hooks":[{"type":"command","command":"echo mine"}]}]}}\n' > "$WS/.claude/settings.json"
out=$(python3 -B "$PROD/scripts/roots.py" make-workspace "$PROD" "$WS" "Test Owner" 2>&1); assert_eq "the layout is made" 0 "$?"
for p in .repolane/registry/lanes .repolane/memory .repolane/knowledge .repolane/repos .repolane/cache lanes; do
  assert "workspace has $p/" test -d "$WS/$p"
done
for f in REPOLANE.md LANE.md config.yml env.sh version registry/repos.yaml memory/MEMORY.md knowledge/preferences.md; do
  assert "workspace has .repolane/$f" test -f "$D/$f"
done
for p in registry memory knowledge repos .cache scripts; do assert "nothing at the top called $p" test ! -e "$WS/$p"; done
assert_eq "the recorded version is the installed one" "$(tr -d '[:space:]' < "$PROD/VERSION")" "$(tr -d '[:space:]' < "$D/version")"
assert "REPOLANE.md is the product's text" cmp -s "$PROD/templates/REPOLANE.md" "$D/REPOLANE.md"
assert "LANE.md is the product's text" cmp -s "$PROD/templates/LANE.md" "$D/LANE.md"
assert_not_contains "REPOLANE.md carries no owner name" "$(cat "$D/REPOLANE.md" "$D/LANE.md")" "Test Owner"
assert_contains "the owner is in config.yml" "$(cat "$D/config.yml")" "name: Test Owner"
assert_eq "the user's CLAUDE.md is not edited by the layout" "$(printf '# My notes\n\nkeep this line\n')" "$(cat "$WS/CLAUDE.md")"
W "$WS" init --yes; assert_eq "lane init --yes over the layout" 0 "$RC"
assert_contains "the user's CLAUDE.md is kept" "$(cat "$WS/CLAUDE.md")" "keep this line"
assert_eq "and imports REPOLANE.md, once" 1 "$(grep -cx '@.repolane/REPOLANE.md' "$WS/CLAUDE.md")"
python3 -B "$PROD/scripts/roots.py" make-workspace "$PROD" "$WS" >/dev/null 2>&1
W "$WS" init --yes
assert_eq "making it again adds nothing to CLAUDE.md" 1 "$(grep -cx '@.repolane/REPOLANE.md' "$WS/CLAUDE.md")"
assert_contains "and keeps the owner" "$(cat "$D/config.yml")" "name: Test Owner"
TOP="$WS/.claude/settings.json"
hooks_of(){ python3 -c 'import json,sys
d=json.load(open(sys.argv[1]))
for ev,es in d.get("hooks",{}).items():
    for e in es:
        for h in e["hooks"]: print(ev+"\t"+h["command"])' "$1"; }
assert_contains "the user's own hook is kept" "$(hooks_of "$TOP")" "Stop	echo mine"
assert_contains "and the user's env" "$(cat "$TOP")" '"MINE": "1"'
ours=$(hooks_of "$TOP" | grep -v 'echo mine')
assert_eq "every Repolane hook at the top is a lane hook command" "" "$(printf '%s\n' "$ours" | grep -v '	lane hook [a-z-]*$')"
assert_eq "eight events are wired" 8 "$(printf '%s\n' "$ours" | wc -l | tr -d ' ')"
assert_not_contains "no hook names a file of the product" "$(cat "$TOP")" "$PROD"
assert_contains "PostToolUse also fires after EnterWorktree" "$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["hooks"]["PostToolUse"][0]["matcher"])' "$TOP")" "EnterWorktree"

echo "-- the shell and the Python resolver agree"
for start in "$WS" "$WS/lanes" "$D/memory"; do
  sh_paths=$(cd "$start" && env -u LANE_WORKSPACE LANE_PRODUCT="$PROD" bash -c 'PRODUCT="$LANE_PRODUCT"; source "$PRODUCT/scripts/roots.sh"; lane_resolve_roots
    for v in PRODUCT AD LANE_MODE DATA REGISTRY LANES_DIR REPOS MEMORY_DIR KNOWLEDGE_DIR CACHE_DIR CONFIG_FILE ENV_SH LANES; do eval "echo $v=\$$v"; done')
  py_paths=$(cd "$start" && env -u LANE_WORKSPACE LANE_PRODUCT="$PROD" python3 -B "$PROD/scripts/roots.py" paths)
  assert_eq "same roots from ${start#$T/}" "$sh_paths" "$py_paths"
done
assert_contains "found from a folder deep inside it" "$(cd "$D/memory" && env -u LANE_WORKSPACE LANE_PRODUCT="$PROD" python3 -B "$PROD/scripts/roots.py" paths)" "AD=$WS
LANE_MODE=workspace"

echo "-- add / start / brief / status, from the workspace folder"
make_remote_repo web; make_remote_repo api
W "$WS" add "$T/remotes/web.git" web --yes; assert_eq "add web" 0 "$RC"
W "$WS" add "$T/remotes/api.git" api --yes; assert_eq "add api" 0 "$RC"
assert "the mirror is under .repolane/repos/" test -d "$D/repos/web/.git"
assert_contains "the repo is registered in .repolane/registry/" "$(cat "$D/registry/repos.yaml")" "  web:"
assert "its memory folder is under .repolane/memory/" test -f "$D/memory/web/MEMORY.md"
W "$WS" start L1 web api; assert_eq "start L1" 0 "$RC"
W "$WS" start L2 web; assert_eq "start L2" 0 "$RC"
assert "the worktrees are under lanes/" test -e "$WS/lanes/L1/web/.git"
assert "and the second repo too" test -e "$WS/lanes/L1/api/.git"
assert "the lane file is under .repolane/registry/lanes/" test -f "$D/registry/lanes/L1.md"
for p in registry memory knowledge repos .cache; do assert "still nothing at the top called $p" test ! -e "$WS/$p"; done
W "$WS/lanes/L1" brief L1; assert_eq "brief from inside the lane" 0 "$RC"; assert_contains "names the lane's repos" "$OUT" "api"
W "$WS" status; assert_eq "status" 0 "$RC"; assert_contains "lists L1" "$OUT" "L1"
W "$T" status; assert_eq "outside any workspace there is none to act on" 2 "$RC"
assert_contains "and it says so" "$OUT" "not a workspace yet"

echo "-- the lane's settings run lane hook commands"
LS="$WS/lanes/L1/.claude/settings.local.json"
lane_hooks=$(hooks_of "$LS")
assert_eq "every hook of the lane is a lane hook command" "" "$(printf '%s\n' "$lane_hooks" | grep -v '	lane hook [a-z-]*$')"
assert_eq "eight events in the lane" 8 "$(printf '%s\n' "$lane_hooks" | wc -l | tr -d ' ')"
assert_not_contains "no lane hook names the product" "$(python3 -c 'import json,sys;print(json.dumps(json.load(open(sys.argv[1]))["hooks"]))' "$LS")" "$PROD"
assert_contains "the mirror is denied at its .repolane path" "$(cat "$LS")" "\"Read($D/repos/**)\""
assert_contains "the other lane is denied" "$(cat "$LS")" "\"Read($WS/lanes/L2/**)\""
assert_contains "the lane's own file is allowed at its .repolane path" "$(cat "$LS")" "\"Edit(/$D/registry/lanes/L1.md)\""
assert_contains "the draft inbox is readable at its .repolane path" "$(cat "$LS")" "\"Read(/$D/cache/memory-inbox/**)\""
assert_contains "the worktree's settings are lane hooks too" "$(hooks_of "$WS/lanes/L1/web/.claude/settings.local.json")" "PreToolUse	lane hook pre-tool-use"
W "$WS" doctor; assert_eq "lane doctor passes in the workspace" 0 "$RC"
assert_contains "and finds every place wired" "$OUT" "6/6 places point at guard.py: 2 lane(s), 3 worktree(s), the root"

hook_cmd(){ python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["hooks"][sys.argv[2]][0]["hooks"][0]["command"])' "$1" "$2"; }
run_hook(){ # run_hook <settings-file> <event> <session-dir> <cwd> <json> : the hook command as written, in Claude Code's way
  local c; c=$(hook_cmd "$1" "$2")
  printf '%s' "$5" | (cd "$4" && env -u LANE_WORKSPACE -u LANE_PRODUCT CLAUDE_PROJECT_DIR="$3" sh -c "$c" 2>/dev/null); }
ctx(){ python3 -c 'import json,sys
try: d=json.load(sys.stdin); print(d["hookSpecificOutput"].get("additionalContext",""))
except Exception: pass'; }

echo "-- LANE.md is handed to a session that enters a lane, and to one started in it"
ev='{"hook_event_name":"PostToolUse","tool_name":"EnterWorktree","session_id":"s1","cwd":"'"$WS"'","tool_input":{"name":"L1"},"tool_response":{}}'
out=$(run_hook "$TOP" PostToolUse "$WS" "$WS" "$ev" | ctx)
assert_contains "after EnterWorktree: LANE.md" "$out" "# You are inside a lane"
assert_contains "after EnterWorktree: the Goal command, plainly" "$out" 'lane-memory goal "<the goal, in their words>"'
assert_contains "after EnterWorktree: the draft command" "$out" 'lane-memory draft <short-slug>'
assert_contains "after EnterWorktree: the lane named" "$out" "in lane 'L1'"
assert_contains "after EnterWorktree: the owner named at run time" "$out" "Owner: Test Owner"
assert_contains "after EnterWorktree: the lane file's real path" "$out" "$D/registry/lanes/L1.md"
ev2='{"hook_event_name":"PostToolUse","tool_name":"EnterWorktree","session_id":"s1","cwd":"'"$WS/lanes/L2"'","tool_input":{"name":"L2/web"},"tool_response":{}}'
assert_contains "the cwd already in the lane names it" "$(run_hook "$TOP" PostToolUse "$WS" "$WS/lanes/L2" "$ev2" | ctx)" "in lane 'L2'"
ev3='{"hook_event_name":"PostToolUse","tool_name":"EnterWorktree","session_id":"s1","cwd":"'"$WS"'","tool_input":{"name":"nope"},"tool_response":{}}'
assert_eq "no lane, no text" "" "$(run_hook "$TOP" PostToolUse "$WS" "$WS" "$ev3")"
ev4='{"hook_event_name":"PostToolUse","tool_name":"EnterWorktree","session_id":"s1","cwd":"'"$WS"'","tool_input":{"name":"../../x"},"tool_response":{}}'
assert_eq "a path for a name, no text" "" "$(run_hook "$TOP" PostToolUse "$WS" "$WS" "$ev4")"
ss='{"hook_event_name":"SessionStart","source":"startup","session_id":"s2","cwd":"'"$WS/lanes/L1"'"}'
out=$(run_hook "$LS" SessionStart "$WS/lanes/L1" "$WS/lanes/L1" "$ss" | ctx)
assert_contains "SessionStart in the lane: the lane file" "$out" "## lane — session in lane 'L1'"
assert_contains "SessionStart in the lane: LANE.md" "$out" "# You are inside a lane"
assert_contains "SessionStart in the lane: the owner" "$out" "Owner: Test Owner"
ssr='{"hook_event_name":"SessionStart","source":"startup","session_id":"s3","cwd":"'"$WS"'"}'
out=$(run_hook "$TOP" SessionStart "$WS" "$WS" "$ssr" | ctx)
assert_contains "SessionStart at the root: the dispatcher board" "$out" "## lane dispatcher"
assert_contains "SessionStart at the root: the owner, at run time" "$out" "Owner of this workspace: Test Owner"
assert_not_contains "SessionStart at the root: no LANE.md" "$out" "# You are inside a lane"
ups='{"hook_event_name":"UserPromptSubmit","session_id":"s2","cwd":"'"$WS/lanes/L1"'","prompt":"hi"}'
out=$(run_hook "$LS" UserPromptSubmit "$WS/lanes/L1" "$WS/lanes/L1" "$ups" | ctx)
assert_contains "UserPromptSubmit in the lane: the state block" "$out" "STATE of lane L1"
assert_contains "and the memory index from .repolane/memory" "$out" "$D/memory/web/MEMORY.md"
assert "the guard's session cache is under .repolane/cache" test -d "$D/cache/sessions"
assert_eq "an unknown hook event is an error, not a silent pass" 1 "$(cd "$WS" && command lane hook nonsense </dev/null >/dev/null 2>&1; echo $?)"

echo "-- lane-memory from inside the lane writes under .repolane/"
OUT=$(cd "$WS/lanes/L1/web" && env -u LANE_WORKSPACE -u LANE_PRODUCT lane-memory goal "compare the two repos" 2>&1); assert_eq "lane-memory goal runs from the lane" 0 "$?"
assert_contains "the Goal is saved in .repolane/registry/lanes/L1.md" "$(sed -n '/^## Goal/,/^## /p' "$D/registry/lanes/L1.md")" "compare the two repos"
assert_not_contains "and only in L1's file" "$(cat "$D/registry/lanes/L2.md")" "compare the two repos"
OUT=$(cd "$WS/lanes/L1" && env -u LANE_WORKSPACE -u LANE_PRODUCT lane-memory goal L2 "not mine" 2>&1)
assert_contains "another lane's Goal is refused from inside L1" "$OUT" "can only set that lane's Goal"
OUT=$(cd "$WS/lanes/L1" && env -u LANE_WORKSPACE -u LANE_PRODUCT lane-memory draft ws-fact "the api repo pins node 20" 2>&1); assert_eq "lane-memory draft" 0 "$?"
assert_contains "the draft is in .repolane/cache/memory-inbox" "$(cat "$D/cache/memory-inbox/ws-fact.md" 2>/dev/null)" "node 20"
W "$WS" note file ws-fact repo api; assert_eq "filing it from the root" 0 "$RC"
assert "the memory is under .repolane/memory/api/" test -f "$D/memory/api/ws-fact.md"
assert_contains "and indexed there" "$(cat "$D/memory/api/MEMORY.md")" "ws-fact"

echo "-- the guard refuses the same things in a workspace as in a clone"
init_plane >/dev/null 2>&1; add_repo web; add_repo api
lane start L1 web api >/dev/null; lane start L2 web >/dev/null
printf 'K=1\n' > "$D/repos/web/.env"; printf 'K=1\n' > "$PLANE/repos/web/.env"
CLS="$PLANE/lanes/L1/.claude/settings.local.json"; CTOP="$PLANE/.claude/settings.json"
# @A the workspace (clone: the plane), @D where the data is (.repolane/ or the plane), @C the cache, @P the product
sub(){ case "$1" in
  ws)    sed -e "s#@A#$WS#g" -e "s#@D#$D#g" -e "s#@C#$D/cache#g" -e "s#@P#$PROD#g" ;;
  clone) sed -e "s#@A#$PLANE#g" -e "s#@D#$PLANE#g" -e "s#@C#$PLANE/.cache#g" -e "s#@P#$PLANE#g" ;; esac; }
verdict(){ # verdict <mode> <where: lane|root> <tool> <tool_input json with tokens>
  local s top a cwd j
  if [ "$1" = ws ]; then s="$LS"; top="$TOP"; a="$WS"; else s="$CLS"; top="$CTOP"; a="$PLANE"; fi
  if [ "$2" = lane ]; then cwd="$a/lanes/L1"; else cwd="$a"; s="$top"; fi
  j=$(printf '{"hook_event_name":"PreToolUse","tool_name":"%s","session_id":"g","cwd":"%s","tool_input":%s}' "$3" "$cwd" "$4" | sub "$1")
  run_hook "$s" PreToolUse "$cwd" "$cwd" "$j" | python3 -c 'import json,sys
try: d=json.load(sys.stdin)["hookSpecificOutput"]["permissionDecision"]
except Exception: d="pass"
print("deny" if d=="deny" else "pass")'; }
gcase(){ # gcase <want> <label> <where> <tool> <tool_input>
  local w c; w=$(verdict ws "$3" "$4" "$5"); c=$(verdict clone "$3" "$4" "$5")
  assert_eq "$2 — clone: $1" "$1" "$c"; assert_eq "$2 — workspace: $1" "$1" "$w"; }
gcase deny "reading the mirror's .env"                  lane Read  '{"file_path":"@D/repos/web/.env"}'
gcase deny "a shell printing .env in the lane"          lane Bash  '{"command":"cat web/.env"}'
gcase deny "writing a memory directly"                  lane Write '{"file_path":"@D/memory/new.md"}'
gcase deny "writing a repo memory directly"             lane Write '{"file_path":"@D/memory/web/new.md"}'
gcase deny "writing preferences directly"               lane Edit  '{"file_path":"@D/knowledge/preferences.md","old_string":"a","new_string":"b"}'
gcase deny "a shell writing a memory"                   lane Bash  '{"command":"echo x > @D/memory/x.md"}'
gcase deny "editing another lane's file"                lane Edit  '{"file_path":"@D/registry/lanes/L2.md","old_string":"a","new_string":"b"}'
gcase pass "editing this lane's own file"               lane Edit  '{"file_path":"@D/registry/lanes/L1.md","old_string":"a","new_string":"b"}'
gcase deny "writing the repo registry from a lane"      lane Write '{"file_path":"@D/registry/repos.yaml"}'
gcase deny "writing the config from a lane"             lane Write '{"file_path":"@D/registry/config.yml"}'
gcase deny "writing the session's own settings"         lane Write '{"file_path":"@A/lanes/L1/.claude/settings.local.json"}'
gcase deny "writing the top settings from a lane"       lane Write '{"file_path":"@A/.claude/settings.json"}'
gcase deny "writing the top CLAUDE.md from a lane"      lane Write '{"file_path":"@A/CLAUDE.md"}'
gcase deny "writing the product's scripts"              lane Write '{"file_path":"@P/scripts/lib.sh"}'
gcase pass "reading the product's scripts"              lane Read  '{"file_path":"@P/scripts/lib.sh"}'
gcase deny "writing into another lane's worktree"       lane Write '{"file_path":"@A/lanes/L2/web/x.txt"}'
gcase deny "reading another lane's worktree"            lane Read  '{"file_path":"@A/lanes/L2/web/README.md"}'
gcase pass "ordinary work in the lane"                  lane Write '{"file_path":"@A/lanes/L1/web/a.txt"}'
gcase pass "git in a repo of the lane"                  lane Bash  '{"command":"git -C web status"}'
gcase deny "a push to a default branch"                 lane Bash  '{"command":"git -C web push origin main"}'
gcase deny "rewriting the git remote"                   lane Bash  '{"command":"git -C web remote set-url origin x"}'
gcase deny "cd into the mirror"                         lane Bash  '{"command":"cd @D/repos/web && ls"}'
gcase deny "writing into the mirror"                    lane Write '{"file_path":"@D/repos/web/README.md"}'
gcase pass "lane-memory goal from the lane"             lane Bash  '{"command":"lane-memory goal \"x\""}'
gcase pass "a draft into the inbox"                     lane Write '{"file_path":"@C/memory-inbox/x.md"}'
gcase deny "the guard's own state in the cache"         lane Write '{"file_path":"@C/sessions/x.json"}'
gcase deny "reading a key outside the workspace"        lane Read  '{"file_path":"'"$HOME"'/.ssh/id_rsa"}'
gcase deny "another worktree from inside a lane"        lane EnterWorktree '{"name":"L2"}'
gcase deny "the dispatcher reaching into a lane"        root Read  '{"file_path":"@A/lanes/L1/web/README.md"}'
gcase deny "a worktree with no lane named"              root EnterWorktree '{}'
gcase deny "a worktree opened by path"                  root EnterWorktree '{"path":"@A/lanes/L1"}'
gcase pass "the dispatcher editing a lane's file"       root Edit  '{"file_path":"@D/registry/lanes/L1.md","old_string":"a","new_string":"b"}'
gcase deny "the dispatcher creating a memory"           root Write '{"file_path":"@D/memory/brand-new.md"}'
gcase deny "the dispatcher reading a mirror's .env"     root Read  '{"file_path":"@D/repos/web/.env"}'
# a hook runs in the session's current folder; a cd out of the workspace must not switch the guard off
j=$(printf '{"hook_event_name":"PreToolUse","tool_name":"Write","session_id":"g","cwd":"%s","tool_input":{"file_path":"%s"}}' "$WS/lanes/L1" "$D/memory/x.md")
assert_contains "the guard still judges the workspace when the hook's folder is elsewhere" "$(run_hook "$LS" PreToolUse "$WS/lanes/L1" "$T" "$j")" '"permissionDecision": "deny"'

# a guard that has lost its resolver must refuse, not pass
G2="$T/broken/scripts/hooks"; mkdir -p "$G2"; cp "$PROD/scripts/hooks/guard.py" "$G2/"
out=$(printf '{"hook_event_name":"PreToolUse","tool_name":"Bash","cwd":"%s","tool_input":{"command":"ls"}}' "$T" | python3 -B "$G2/guard.py" 2>/dev/null); rc=$?
assert_eq "a guard without roots.py exits 0 with a decision" 0 "$rc"
assert_contains "and the decision is deny" "$out" '"permissionDecision": "deny"'

echo "-- a clone keeps acting on itself, even when run from inside a workspace"
OUT=$(cd "$WS" && "$PLANE/lane" status </dev/null 2>&1)
assert_contains "the clone's status lists its own lanes" "$OUT" "L1"
assert "and the clone's lanes are where they always were" test -e "$PLANE/lanes/L1/web/.git"
assert "the clone still has its data at the top" test -f "$PLANE/registry/lanes/L1.md"
assert_eq "a clone's lane hooks are still the bare guard path" "$PLANE/scripts/hooks/guard.py" "$(hook_cmd "$CLS" PreToolUse)"

echo "-- a version change refreshes the rule files and nothing else"
data_sum(){ (cd "$D" && find registry memory knowledge repos config.yml env.sh -type f -not -path 'repos/*/.git/*' | LC_ALL=C sort | xargs cksum); (cd "$WS" && cksum CLAUDE.md); }
before=$(data_sum)
printf 'stale\n' >> "$D/REPOLANE.md"; rm -f "$D/LANE.md"
W "$WS" status
assert "a missing LANE.md is put back" cmp -s "$PROD/templates/LANE.md" "$D/LANE.md"
printf 'a local note\n' >> "$D/LANE.md"
W "$WS" status
assert_contains "the same version leaves an edited rule file alone" "$(cat "$D/LANE.md")" "a local note"
printf '0.0.1\n' > "$D/version"
W "$WS" status; assert_eq "status after the version change" 0 "$RC"
assert "REPOLANE.md is the installed version's again" cmp -s "$PROD/templates/REPOLANE.md" "$D/REPOLANE.md"
assert "LANE.md is the installed version's again" cmp -s "$PROD/templates/LANE.md" "$D/LANE.md"
assert_eq "the new version is recorded" "$(tr -d '[:space:]' < "$PROD/VERSION")" "$(tr -d '[:space:]' < "$D/version")"
assert_eq "memory, registry, knowledge, config, env.sh and CLAUDE.md are untouched" "$before" "$(data_sum)"
printf '0.0.1\n' > "$D/version"; printf 'stale\n' >> "$D/LANE.md"
run_hook "$LS" UserPromptSubmit "$WS/lanes/L1" "$WS/lanes/L1" "$ups" >/dev/null
assert "a hook run refreshes too" cmp -s "$PROD/templates/LANE.md" "$D/LANE.md"
assert_eq "and records the version" "$(tr -d '[:space:]' < "$PROD/VERSION")" "$(tr -d '[:space:]' < "$D/version")"
assert_eq "still nothing of the user's changed" "$before" "$(data_sum)"

echo "-- the board shows the workspace"
PORT=$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1])')
(cd "$WS" && WS_BOARD_NO_OPEN=1 WS_BOARD_PORT=$PORT exec lane board >"$T/board.log" 2>&1) & BP=$!
URL="http://127.0.0.1:$PORT/"
for _ in $(seq 1 75); do curl -s -o /dev/null "$URL" && break; sleep 0.2; done
TOK=$(curl -s "$URL" | grep -o "__T='[^']*'" | cut -d"'" -f2)
assert "the board serves a token" test -n "$TOK"
b=$(curl -s -H "X-Token: $TOK" "${URL}api/board")
assert_contains "the board lists L1" "$b" '"id": "L1"'
assert_contains "the board lists the mirrors from .repolane/repos" "$b" '"api"'
assert_contains "the board reads the Goal from .repolane/registry" "$(curl -s -H "X-Token: $TOK" "${URL}api/spec?lane=L1")" "compare the two repos"
assert_contains "the board's memory view reads .repolane/memory" "$(curl -s -H "X-Token: $TOK" "${URL}api/memory")" "ws-fact"
{ kill "$BP"; wait "$BP"; } 2>/dev/null

echo "-- the product was only read"
assert_eq "no file in the product changed" "$prod_before" "$(PROD_SUM)"
assert_eq "no __pycache__ in the product" "" "$(find "$PROD" -name __pycache__)"

finish
