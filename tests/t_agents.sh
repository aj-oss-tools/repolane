#!/usr/bin/env bash
# The agent adapter (scripts/agents/): the neutral event and decision, what ClaudeAdapter reads and writes, `lane agent`, and
# the guard failing closed when the adapter itself is what breaks.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
new_sandbox; init_plane >/dev/null 2>&1
S="$PLANE/scripts"
# py <code> [args…] : python with scripts/ importable; the adapter as a, the neutral types in scope
py(){ local c="$1"; shift; python3 -B -c "import sys,json; sys.path.insert(0,'$S'); import agents; from agents.base import *; from agents.base import ToolKind as K; a=agents.get()
$c" "$@"; }
# event <json> <expr over e> : parse and print
event(){ py "e=a.parse_event(sys.argv[1]); print($2)" "$1"; }

echo "-- selecting: Claude is the default, nothing else is registered"
assert_eq "the default" claude "$(py 'print(a.name)')"
assert_eq "one agent registered" "['claude']" "$(py 'print(list(agents.REGISTERED))')"
assert_eq "an unknown name is an error" KeyError "$(py 'try: agents.get("nobody")
except KeyError: print("KeyError")')"
assert_eq "an adapter missing a method cannot be built" TypeError "$(py 'class X(AgentAdapter): pass
try: X()
except TypeError: print("TypeError")')"
assert_eq "it has every capability today" "$(py 'print(len(Capability))')" "$(py 'print(len(a.capabilities))')"

echo "-- parse_event: events"
for pair in SessionStart:session-start PreToolUse:pre-tool-use PostToolUse:post-tool-use UserPromptSubmit:user-prompt-submit \
            PreCompact:pre-compact SessionEnd:session-end WorktreeCreate:worktree-create WorktreeRemove:worktree-remove; do
  body="{\"hook_event_name\":\"${pair%%:*}\",\"tool_name\":\"Read\"}"
  assert_eq "${pair%%:*} is ${pair##*:}" "${pair##*:}" "$(event "$body" 'e.kind')"
done
assert_eq "an event nobody knows has no kind" "''" "$(event '{"hook_event_name":"Stop"}' 'repr(e.kind)')"
assert_eq "an event name that is not a string has no kind" "''" "$(event '{"hook_event_name":5}' 'repr(e.kind)')"
assert_eq "session id and cwd come through" "s1 /x" "$(event '{"hook_event_name":"SessionEnd","session_id":"s1","cwd":"/x"}' 'e.session_id,e.cwd' | tr -d "(),'")"
assert_eq "WorktreeCreate's name comes through as sent" "[1]" "$(event '{"hook_event_name":"WorktreeCreate","name":[1]}' 'e.target')"

echo "-- parse_event: what cannot be read is refused, or has nothing to decide"
for body in 'not json' '' '[1' ; do assert_eq "body '$body' is nothing to decide" None "$(event "$body" 'e')"; done
for body in null '[1]' '5' '"x"'; do assert_eq "JSON that is not an object ($body) is nothing to decide" None "$(event "$body" 'e')"; done
assert_eq "not JSON, but plainly a tool call: malformed" "pre-tool-use True" "$(event '{"hook_event_name" : "PreToolUse", oops' 'e.kind,e.malformed' | tr -d "(),'")"
for c in 5 true '[]' '"a\u0000b"'; do
  body="{\"hook_event_name\":\"PreToolUse\",\"tool_name\":\"Read\",\"cwd\":$c}"
  assert_eq "cwd $c on a tool call is malformed" True "$(event "$body" 'e.malformed')"
  body="{\"hook_event_name\":\"UserPromptSubmit\",\"cwd\":$c}"
  assert_eq "cwd $c on any other event is ignored" "False None" "$(event "$body" 'e.malformed,e.cwd' | tr -d "(),'")"
done
assert_eq "a null cwd is not malformed" False "$(event '{"hook_event_name":"PreToolUse","tool_name":"Read","cwd":null}' 'e.malformed')"
for body in '"tool_input":{}' '"tool_name":5' '"tool_name":"Read","tool_input":[]' '"tool_name":"Read","tool_input":"x"'; do
  j="{\"hook_event_name\":\"PreToolUse\",$body}"
  assert_eq "{$body} has no tool call" None "$(event "$j" 'e.tool')"
done
for f in command file_path notebook_path path name pattern glob type; do for v in 5 true '[]' '{}'; do
  j="{\"hook_event_name\":\"PreToolUse\",\"tool_name\":\"Foo\",\"tool_input\":{\"$f\":$v}}"
  assert_eq "PreToolUse $f=$v has no tool call" None "$(event "$j" 'e.tool')"
done; done
assert_eq "PostToolUse with a file_path that is a list is ignored" None "$(event '{"hook_event_name":"PostToolUse","tool_name":"Edit","tool_input":{"file_path":[]}}' 'e.tool')"
assert_eq "PostToolUse with no usable input still has a tool" other "$(event '{"hook_event_name":"PostToolUse","tool_name":[],"tool_input":5}' 'e.tool.kind.value')"

echo "-- parse_event: tool calls"
for pair in Bash:shell Read:read Edit:write Write:write MultiEdit:write NotebookEdit:write Grep:search Glob:list EnterWorktree:enter-lane Task:other; do
  body="{\"hook_event_name\":\"PreToolUse\",\"tool_name\":\"${pair%%:*}\"}"
  assert_eq "${pair%%:*} is ${pair##*:}" "${pair##*:}" "$(event "$body" 'e.tool.kind.value')"
done
t(){ local j="{\"hook_event_name\":\"PreToolUse\",\"tool_name\":\"$1\",\"tool_input\":$2}"; event "$j" "$3"; }
assert_eq "a shell call carries its command" "ls -a" "$(t Bash '{"command":"ls -a"}' 'e.tool.command')"
assert_eq "another tool's command field is not a command" "" "$(t Read '{"command":"ls -a"}' 'e.tool.command')"
assert_eq "paths, in the order they are judged" "('/a', '/b', '/c')" "$(t Edit '{"path":"/c","notebook_path":"/b","file_path":"/a"}' 'e.tool.paths')"
assert_eq "file prefers file_path" /a "$(t Edit '{"notebook_path":"/b","file_path":"/a"}' 'e.tool.file')"
assert_eq "file falls back to notebook_path" /b "$(t NotebookEdit '{"notebook_path":"/b"}' 'e.tool.file')"
assert_eq "path is a root, not a file" "|/c" "$(t Grep '{"path":"/c"}' 'e.tool.file+"|"+e.tool.root')"
assert_eq "search fields" "*.py|py|p*" "$(t Grep '{"glob":"*.py","type":"py","pattern":"p*"}' 'e.tool.glob+"|"+e.tool.filetype+"|"+e.tool.pattern')"
assert_eq "a move names its target" L1 "$(t EnterWorktree '{"name":"L1"}' 'e.tool.target')"
assert_eq "the agent's own tool name is kept, for project rules" MultiEdit "$(t MultiEdit '{}' 'e.tool.name')"
assert_eq "a null field reads as it always has" None "$(t Bash '{"command":null}' 'e.tool.command')"

echo "-- format_decision: the bytes Claude Code receives"
fd(){ py "r=a.format_decision($1,$2); print(r.stdout); print(r.stderr); print(r.code)"; }
assert_eq "deny" '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "no"}}
None
0' "$(fd PRE_TOOL 'Decision.deny("no")')"
assert_eq "allow" '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}
None
0' "$(fd PRE_TOOL 'Decision.allow()')"
assert_eq "allow with context" '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow", "additionalContext": "c"}}
None
0' "$(fd PRE_TOOL 'Decision.allow("c")')"
assert_eq "context, on the event it answers" '{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "c"}}
None
0' "$(fd PROMPT 'Decision.add_context("c")')"
assert_eq "context on PreCompact" '{"hookSpecificOutput": {"hookEventName": "PreCompact", "additionalContext": "c"}}
None
0' "$(fd PRE_COMPACT 'Decision.add_context("c")')"
assert_eq "refuse goes to stderr with status 1" 'None
no
1' "$(fd LANE_LEAVE 'Decision.refuse("no")')"
assert_eq "enter prints the folder, the note to stderr" '/x
n
0' "$(fd LANE_ENTER 'Decision.enter("/x","n")')"
assert_eq "a kind nobody knows is an error, not an empty answer" ValueError "$(py 'try: a.format_decision(PRE_TOOL, Decision("maybe"))
except ValueError: print("ValueError")')"
assert_eq "the session-start reply" '{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "c"}, "systemMessage": "s"}' "$(py 'print(a.session_start_reply("c","s"))')"

echo "-- the guard reads neutral types only"
G="$S/hooks/guard.py"
for word in tool_name tool_input hookSpecificOutput\" '"Bash"' '"Edit"' '"Read"' '"Glob"' '"Grep"' '"EnterWorktree"' '~/.claude'; do
  n=$(grep -cF "$word" "$G"); case "$word" in hookSpecificOutput*) want=1 ;; *) want=0 ;; esac
  assert_eq "guard.py names $word only as the last resort ($want)" "$want" "$n"
done
assert_eq "guard.py names hook_event_name only to fail closed with no adapter" 1 "$(grep -c "hook_event_name" "$G")"

echo "-- the guard fails closed when the adapter is what breaks"
crash_tree(){ # a plane of the guard and roots.py, with whatever scripts/agents it is given
  local d="$T/crash-$1"; mkdir -p "$d/scripts/hooks" "$d/registry/lanes" "$d/lanes" "$d/repos"; : > "$d/registry/config.yml"
  cp "$G" "$d/scripts/hooks/guard.py"; cp "$S/roots.py" "$d/scripts/roots.py"; [ "$2" = none ] || cp -R "$S/agents" "$d/scripts/agents"; echo "$d"; }
PRE='{"hook_event_name":"PreToolUse","tool_name":"Bash","cwd":"/tmp","tool_input":{"command":"ls"}}'
judged(){ OUT=$(printf '%s' "$2" | python3 -B "$1/scripts/hooks/guard.py" 2>/dev/null); RC=$?; }
d=$(crash_tree missing none); judged "$d" "$PRE"
assert_eq "no adapter at all: exit 0" 0 "$RC"; assert_contains "no adapter at all: a deny" "$OUT" '"permissionDecision": "deny"'
assert_contains "no adapter at all: says why" "$OUT" "internal error (ModuleNotFoundError)"
judged "$d" '{"hook_event_name":"UserPromptSubmit","cwd":"/tmp"}'; assert_eq "no adapter, another event: a hook error" 1 "$RC"; assert_eq "no adapter, another event: says nothing" "" "$OUT"
d=$(crash_tree syntax); echo 'def (' >> "$d/scripts/agents/claude.py"; judged "$d" "$PRE"
assert_eq "an adapter with a syntax error: exit 0" 0 "$RC"; assert_contains "an adapter with a syntax error: a deny" "$OUT" '"permissionDecision": "deny"'
d=$(crash_tree parse); printf '\n    def parse_event(self, raw): raise RuntimeError("boom")\n' > "$T/snip"
python3 -B - "$d/scripts/agents/claude.py" "$T/snip" <<'PY'
import sys
s = open(sys.argv[1]).read(); s = s.replace('    def claims_pre_tool(self, raw):', open(sys.argv[2]).read() + '\n    def claims_pre_tool(self, raw):', 1)
s = s.replace('    def parse_event(self, raw):\n        try: data', '    def _old_parse(self, raw):\n        try: data', 1); open(sys.argv[1], "w").write(s)
PY
judged "$d" "$PRE"
assert_eq "parse_event blows up on a tool call: exit 0" 0 "$RC"; assert_contains "parse_event blows up on a tool call: a deny" "$OUT" 'internal error (RuntimeError)'
judged "$d" '{"hook_event_name":"UserPromptSubmit","cwd":"/tmp"}'; assert_eq "parse_event blows up on another event: a hook error" 1 "$RC"
d=$(crash_tree format); python3 -B - "$d/scripts/agents/claude.py" <<'PY'
import sys
s = open(sys.argv[1]).read(); s = s.replace('        if d.kind == Decision.REFUSE:', '        raise RuntimeError("boom")\n        if d.kind == Decision.REFUSE:', 1); open(sys.argv[1], "w").write(s)
PY
judged "$d" '{"hook_event_name":"PreToolUse","tool_name":"Bash","cwd":"/tmp","tool_input":{"command":5}}'
assert_eq "format_decision blows up: exit 0" 0 "$RC"; assert_contains "format_decision blows up: still a deny" "$OUT" '"permissionDecision": "deny"'
assert_contains "format_decision blows up: says why" "$OUT" "internal error (RuntimeError)"

echo "-- the guard's startup stays cheap"
assert_eq "no slow module comes with the adapter" "[]" "$(py 'print([m for m in ("dataclasses","typing","inspect","pathlib","asyncio","importlib.metadata") if m in sys.modules])')"
assert_eq "the guard does not load the settings code" False "$(py 'print("agents.claude_setup" in sys.modules)')"

echo "-- lane agent"
A(){ OUT=$(cd "$PLANE" && ./lane agent "$@" </dev/null 2>&1); RC=$?; }
A name; assert_eq "name" claude "$OUT"; assert_eq "name exits 0" 0 "$RC"
A has status-line; assert_eq "has what it has" 0 "$RC"
A has telepathy; assert_eq "has not what it has not" 1 "$RC"
A capabilities; assert_contains "capabilities lists them" "$OUT" "pre-compact"
A rules-file; assert_eq "rules file" CLAUDE.md "$OUT"
A session-dir "/a/b.c_d"; assert_eq "session dir" "$HOME/.claude/projects/-a-b-c-d" "$OUT"
A session-count "/a/b.c_d"; assert_eq "no sessions" 0 "$OUT"
A sessions 5 myrepo; assert_contains "no sessions, the same words" "$OUT" "  none"; assert_contains "and how to resume" "$OUT" "claude --resume <id>"
A nonsense; assert_eq "an unknown action exits 2" 2 "$RC"; assert_contains "and shows the actions" "$OUT" "session-dir"
A install; assert_eq "writing is not one of its actions" 2 "$RC"
OUT=$(printf '{"source":"resume","session_id":"s","cwd":"/x"}' | (cd "$PLANE" && ./lane agent session-start-input)); assert_eq "session-start-input" "resume s /x" "$OUT"
OUT=$(printf 'junk' | (cd "$PLANE" && ./lane agent session-start-input)); assert_eq "session-start-input on junk" "startup - -" "$OUT"
P="$HOME/.claude/projects/$(cd "$PLANE" && ./lane agent session-dir "$PLANE/repos/api" | sed 's#.*/##')"
mkdir -p "$P"; : > "$P/s7.jsonl"
assert_eq "session-owner finds the mirror" api "$(cd "$PLANE" && ./lane agent session-owner s7 "$PLANE/repos")"
assert_eq "session-owner: nobody's" "" "$(cd "$PLANE" && ./lane agent session-owner s8 "$PLANE/repos")"
rm -rf "$P"
assert "lane agent grows no __pycache__" test ! -e "$S/agents/__pycache__"

echo "-- the lane's files, through the adapter"
make_remote_repo api; add_repo api
lane start L1 api; assert_eq "lane start works" 0 "$RC"
W="$PLANE/lanes/L1/api"
assert_contains "the worktree's settings wire the guard" "$(cat "$W/.claude/settings.local.json")" "$S/hooks/guard.py"
assert_contains "the lane's rules file" "$(cat "$PLANE/lanes/L1/CLAUDE.md")" "# Lane: L1"
assert_contains "the settings file stays out of git" "$(cat "$(git -C "$W" rev-parse --git-common-dir)/info/exclude")" ".claude/settings.local.json"
assert_eq "git status does not show it" "" "$(git -C "$W" status --porcelain)"
L="$HOME/.claude/projects/$(cd "$PLANE" && ./lane agent session-dir "$W" | sed 's#.*/##')"; mkdir -p "$L"
printf '{"type":"user","timestamp":"2026-01-02T03:04:05Z","message":{"content":"fix the login"}}\n' > "$L/abc.jsonl"
lane sessions L1; assert_contains "lane sessions reads a transcript" "$OUT" "abc    1 turns  fix the login"
lane sessions api; assert_contains "and by repo" "$OUT" "abc    1 turns  fix the login"
assert_eq "a moved name still answers through roots.py" "lane statusline" "$(python3 -B -c "import sys; sys.path.insert(0,'$S'); import roots; print(roots.STATUSLINE_CMD)")"
assert_eq "a name nobody moved is still an error" AttributeError "$(python3 -B -c "import sys; sys.path.insert(0,'$S'); import roots
try: roots.nonsense
except AttributeError: print('AttributeError')")"
assert "importing them grows no __pycache__" test ! -e "$S/agents/__pycache__"

finish
