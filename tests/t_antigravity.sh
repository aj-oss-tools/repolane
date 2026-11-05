#!/usr/bin/env bash
# A workspace that opted in to Antigravity: what lane init, lane start and lane doctor write and check, and what the guard answers to
# agy's own hook bodies, on a throwaway HOME. tests/agy-integration.sh is the same thing against a real agy, by hand.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
new_sandbox
install_product
export PATH="$BIN:$PATH"; unset -f lane
WS="$T/ws"; mkdir -p "$WS"
L(){ OUT=$(cd "$1" && shift && env -u LANE_WORKSPACE -u LANE_PRODUCT lane "$@" </dev/null 2>&1); RC=$?; }

echo "-- lane init --agent"
L "$T" init "$WS" --owner Pat --yes --claude-home "$T/claude" --agent nobody; assert_eq "an unknown agent is refused" 2 "$RC"
L "$T" init "$WS" --owner Pat --yes --claude-home "$T/claude" --agent antigravity; assert_eq "init works" 0 "$RC"
assert_contains "the choice is one line in config.yml" "$(cat "$WS/.repolane/config.yml")" "agent: antigravity"
assert "root hooks" test -f "$WS/.agents/hooks.json"
assert "root rules" test -f "$WS/AGENTS.md"
assert "Claude Code's settings stay, so a claude started here is guarded too" test -f "$WS/.claude/settings.json"
assert "nothing under Claude's home: no memory links" test ! -e "$T/claude/projects"
assert_not_contains "it says agy next" "$OUT" "  claude
"
assert_contains "and names the command" "$OUT" "  agy"
for w in EnterWorktree ExitWorktree "claude --resume" "Claude Code" '`claude`'; do
  assert_not_contains "root AGENTS.md has no $w" "$(cat "$WS/AGENTS.md")" "$w"
done
hk=$(python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));print(d["repolane"]["PreToolUse"][0]["hooks"][0]["command"], d["repolane"]["PreToolUse"][0]["matcher"])' "$WS/.agents/hooks.json")
assert_eq "the hook names its agent, and every tool reaches it" "lane hook --agent antigravity pre-tool-use *" "$hk"
assert_not_contains "no event of Claude's in the hook file" "$(cat "$WS/.agents/hooks.json")" "SessionEnd"
L "$WS" agent name; assert_eq "lane agent names it" antigravity "$OUT"
L "$WS" agent has enter-lane; assert_eq "no ENTER_LANE" 1 "$RC"
L "$WS" agent has pre-compact; assert_eq "no PRE_COMPACT" 1 "$RC"
L "$WS" agent has status-line; assert_eq "no STATUS_LINE: agy keeps it in ~/.gemini, not per workspace" 1 "$RC"
L "$WS" agent has memory-link; assert_eq "no MEMORY_LINK" 1 "$RC"
L "$WS" agent has import-conversations; assert_eq "no conversation adoption" 1 "$RC"
L "$WS" agent install; assert_eq "lane agent still writes nothing" 2 "$RC"
L "$WS" import --list; assert_eq "lane import says no" 1 "$RC"; assert_contains "and why" "$OUT" "filed by folder"

echo "-- lane start: every folder is wired, kept out of git"
make_remote_repo api; make_remote_repo web
L "$WS" add "$T/remotes/api.git" api --yes; assert_eq "add" 0 "$RC"; assert "nothing under Claude's home after lane add" test ! -e "$T/claude/projects"
L "$WS" add "$T/remotes/web.git" web --yes
L "$WS" start L1 api; assert_eq "start" 0 "$RC"; assert_contains "next is agy" "$OUT" "&& agy"; assert_not_contains "not claude" "$OUT" "&& claude"
LR="$WS/lanes/L1"; WT="$LR/api"
for d in "$WS" "$LR" "$WT"; do
  for f in .agents/hooks.json AGENTS.md; do assert "${d#"$T"/}/$f" test -f "$d/$f"; done
done
assert_eq "a worktree's git status stays clean" "" "$(git -C "$WT" status --porcelain)"
assert_contains "excluded by a pattern anchored to the top" "$(cat "$(git -C "$WT" rev-parse --git-common-dir)/info/exclude")" "/.agents/hooks.json"
assert_contains "the lane's rules name it" "$(cat "$WT/AGENTS.md")" "# Lane L1"
L "$WS" with L1 web; assert_eq "with" 0 "$RC"; assert "lane with wires the new worktree" test -f "$LR/web/.agents/hooks.json"
L "$WS" doctor; DOC="$OUT"; assert_contains "doctor counts the folders" "$DOC" "antigravity's hooks and rules are in all 4 session folder(s)"
assert_not_contains "doctor does not ask for Claude's memory links" "$DOC" "memory is linked"
assert_contains "doctor's probes ran through agy's format" "$DOC" "9/9 probes"

echo "-- doctor fails loudly, resume repairs"
rm "$WT/.agents/hooks.json"
L "$WS" doctor; assert_eq "a missing hooks.json fails the doctor" 1 "$RC"; assert_contains "and says what it means" "$OUT" "UNGUARDED"; assert_contains "and the fix" "$OUT" "lane resume L1"
L "$WS" resume L1; assert "lane resume puts it back" test -f "$WT/.agents/hooks.json"
rm "$LR/AGENTS.md"
L "$WS" doctor; assert_eq "a missing AGENTS.md fails the doctor" 1 "$RC"
L "$WS" resume L1; assert "lane resume puts that back" test -f "$LR/AGENTS.md"
echo '{"mine":{}}' > "$WT/.agents/hooks.json"
L "$WS" doctor; assert_eq "somebody else's hooks.json fails the doctor" 1 "$RC"
L "$WS" resume L1; assert_eq "and is not overwritten" 3 "$RC"; assert_contains "resume says so" "$OUT" "does not guess at merging"
assert_eq "the file is untouched" '{"mine":{}}' "$(cat "$WT/.agents/hooks.json")"
rm "$WT/.agents/hooks.json"; L "$WS" resume L1; assert_eq "resume works again" 0 "$RC"

echo "-- a repo with its own files"
make_remote_repo hooked; s="$T/src/hooked"; mkdir -p "$s/.agents"; echo '{"theirs":{}}' > "$s/.agents/hooks.json"; git -C "$s" add -A; git -C "$s" commit -q -m h; git -C "$s" push -q origin main
L "$WS" add "$T/remotes/hooked.git" hooked --yes
L "$WS" start H1 hooked; assert_eq "a committed hooks.json refuses lane start" 1 "$RC"; assert_contains "with a reason" "$OUT" "has its own .agents/hooks.json"
assert "no lane left behind" test ! -e "$WS/lanes/H1"; assert "no lane file left behind" test ! -e "$WS/.repolane/registry/lanes/H1.md"
make_remote_repo told; s="$T/src/told"; printf '# their rules\n' > "$s/AGENTS.md"; git -C "$s" add -A; git -C "$s" commit -q -m a; git -C "$s" push -q origin main
L "$WS" add "$T/remotes/told.git" told --yes
L "$WS" start T1 told; assert_eq "a committed AGENTS.md does not refuse" 0 "$RC"; assert_contains "it says it kept it" "$OUT" "has its own AGENTS.md"
assert_eq "their AGENTS.md is untouched" "# their rules" "$(cat "$WS/lanes/T1/told/AGENTS.md")"
assert_eq "git status is clean" "" "$(git -C "$WS/lanes/T1/told" status --porcelain)"
assert "hooks are still wired" test -f "$WS/lanes/T1/told/.agents/hooks.json"

echo "-- the guard, as agy calls it"
: > "$WT/.env"; echo x > "$WT/a.txt"
H(){ (cd "$1/.agents" && printf '%s' "$3" | env -u LANE_WORKSPACE -u LANE_PRODUCT lane hook --agent antigravity "$2" 2>/dev/null); }
pre(){ python3 -c 'import json,sys;print(json.dumps({"conversationId":"c1","workspacePaths":[sys.argv[1]],"toolCall":{"name":sys.argv[2],"args":json.loads(sys.argv[3])},"stepIdx":1}))' "$1" "$2" "$3"; }
dec(){ python3 -c 'import json,sys
t=sys.stdin.read()
try: print(json.loads(t).get("decision") or "NODECISION")
except Exception: print("EMPTY" if not t.strip() else "NOTJSON")'; }
D(){ H "$1" pre-tool-use "$(pre "$1" "$2" "$3")" | dec; }
c(){ python3 -c 'import json,sys;print(json.dumps({"CommandLine":sys.argv[1]}))' "$1"; }
p(){ python3 -c 'import json,sys;print(json.dumps({"Path":sys.argv[1]}))' "$1"; }
assert_eq "a secret by command: deny" deny "$(D "$LR" run_command "$(c 'cat api/.env')")"
assert_eq "a push to main: deny" deny "$(D "$LR" run_command "$(c 'git -C api push origin main')")"
assert_eq "ordinary work: ask, agy's own check decides" ask "$(D "$LR" run_command "$(c 'git -C api status')")"
assert_eq "a read-only lane command: auto_approve" auto_approve "$(D "$LR" run_command "$(c 'lane-status')")"
assert_eq "a lane command that writes: ask" ask "$(D "$LR" run_command "$(c 'lane-memory file x lane')")"
assert_eq "a secret by read_file: deny" deny "$(D "$LR" read_file "$(p "$WT/.env")")"
assert_eq "a lane file by read_file: auto_approve" auto_approve "$(D "$LR" read_file "$(p "$WT/a.txt")")"
assert_eq "a lane file by write_file: auto_approve" auto_approve "$(D "$LR" write_file "$(p "$WT/a.txt")")"
assert_eq "a lane file by edit_file: auto_approve" auto_approve "$(D "$LR" edit_file "$(p "$WT/a.txt")")"
assert_eq "memory by read_file: auto_approve" auto_approve "$(D "$LR" read_file "$(p "$WS/.repolane/memory/MEMORY.md")")"
assert_eq "memory by write_file: deny" deny "$(D "$LR" write_file "$(p "$WS/.repolane/memory/new.md")")"
assert_eq "its own lane file by write_file: auto_approve" auto_approve "$(D "$LR" write_file "$(p "$WS/.repolane/registry/lanes/L1.md")")"
assert_eq "another lane from here: deny" deny "$(D "$LR" read_file "$(p "$WS/lanes/T1/told/AGENTS.md")")"
assert_eq "a worktree session reads the same way" deny "$(D "$WT" run_command "$(c 'cat .env')")"
assert_eq "the session's folder comes from workspacePaths, not the hook's cwd" auto_approve "$(D "$LR" read_file "$(p "$LR/web/README.md")")"
echo "-- agy's own config"
for a in "$LR/.agents/hooks.json" "$WT/.agents/hooks.json" "$WT/.agents/rules/x.md" "$WS/.agents/hooks.json" "$WT/AGENTS.md" "$LR/AGENTS.md" "$WS/AGENTS.md" "$WS/.repolane/config.yml"; do
  assert_eq "write_file ${a#"$WS"/} from a lane: deny" deny "$(D "$LR" write_file "$(p "$a")")"
  assert_eq "write_file ${a#"$WS"/} from the root: deny" deny "$(D "$WS" write_file "$(p "$a")")"
  assert_eq "a redirect onto ${a#"$WS"/} from a lane: deny" deny "$(D "$LR" run_command "$(c "echo x > $a")")"
  assert_eq "a redirect onto ${a#"$WS"/} from the root: deny" deny "$(D "$WS" run_command "$(c "echo x > $a")")"
done
assert_eq "the sed way onto config.yml from the root: deny" deny "$(D "$WS" run_command "$(c "sed -i '' s/antigravity/claude/ $WS/.repolane/config.yml")")"
assert_eq "lane init --agent from the root: deny" deny "$(D "$WS" run_command "$(c 'lane init --agent claude')")"
assert_eq "the repo's own AGENTS.md is editable" auto_approve "$(D "$WS/lanes/T1" edit_file "$(p "$WS/lanes/T1/told/AGENTS.md")")"
assert_eq "Claude's settings are off limits too" deny "$(D "$LR" write_file "$(p "$WT/.claude/settings.local.json")")"
G="$HOME/.gemini"; mkdir -p "$G"
for f in "$G/oauth_creds.json" "$G/antigravity-cli/settings.json" "$G/config/hooks.json" "~/.gemini/oauth_creds.json"; do
  assert_eq "read_file $f: deny" deny "$(D "$LR" read_file "$(p "$f")")"
  assert_eq "write_file $f: deny" deny "$(D "$LR" write_file "$(p "$f")")"
  assert_eq "cat $f: deny" deny "$(D "$LR" run_command "$(c "cat $f")")"
done
assert_eq "~/.gemini cannot become a reference" deny "$(D "$WS" run_command "$(c "lane-ref L1 add $G why")")"
echo "-- tools nobody mapped"
u(){ python3 -c 'import json,sys;print(json.dumps({sys.argv[1]:sys.argv[2]}))' "$1" "$2"; }
assert_eq "an unknown tool naming nothing: ask" ask "$(D "$LR" brand_new_tool '{"x":"hello there"}')"
assert_eq "an unknown tool naming a secret: deny" deny "$(D "$LR" brand_new_tool "$(u x "$WT/.env")")"
assert_eq "naming it deep in its arguments: deny" deny "$(D "$LR" brand_new_tool "$(python3 -c 'import json,sys;print(json.dumps({"a":{"b":["please read "+sys.argv[1]+" now"]}}))' "$WT/.env")")"
assert_eq "naming ~/.gemini: deny" deny "$(D "$LR" brand_new_tool '{"x":"~/.gemini/oauth_creds.json"}')"
assert_eq "naming another lane: deny" deny "$(D "$LR" brand_new_tool "$(u x "$WS/lanes/T1/told/x")")"
assert_eq "naming a place outside: deny" deny "$(D "$LR" brand_new_tool "$(u x "$HOME/x")")"
assert_eq "naming the hook file: deny" deny "$(D "$LR" call_mcp_tool "$(u Arguments "$WT/.agents/hooks.json")")"
assert_eq "naming a lane file: ask, never allow" ask "$(D "$LR" brand_new_tool "$(u x "$WT/a.txt")")"
assert_eq "a url is not a path" ask "$(D "$LR" read_url_content '{"Url":"https://example.com/a/.env"}')"
assert_eq "send_message that mentions .env: ask" ask "$(D "$LR" send_message '{"Message":"do not read .env or /etc/passwd","Recipient":"x"}')"
sub(){ python3 -c 'import json,sys;print(json.dumps({"Prompt":"read .env","Workspace":sys.argv[1]}))' "$1"; }
assert_eq "invoke_subagent in this lane: ask" ask "$(D "$LR" invoke_subagent "$(sub "$LR")")"
assert_eq "invoke_subagent in another lane: deny" deny "$(D "$LR" invoke_subagent "$(sub "$WS/lanes/T1")")"
cw(){ python3 -c 'import json,sys;print(json.dumps({"CommandLine":sys.argv[1],"Cwd":sys.argv[2]}))' "$1" "$2"; }
assert_eq "a working directory inside the lane: ask" ask "$(D "$LR" run_command "$(cw 'git status' "$WT")")"
assert_eq "a secret relative to that working directory: deny" deny "$(D "$LR" run_command "$(cw 'cat .env' "$WT")")"
assert_eq "a working directory in another lane: deny" deny "$(D "$LR" run_command "$(cw 'cat AGENTS.md' "$WS/lanes/T1/told")")"
echo "-- a tool call always gets a decision"
R(){ (cd "$LR/.agents" && printf "$1" | env -u LANE_WORKSPACE -u LANE_PRODUCT lane hook --agent antigravity pre-tool-use 2>/dev/null | dec); }
for body in '' 'not json' 'null' '[]' '{}' '{"workspacePaths":[]}' '{"workspacePaths":null,"toolCall":{"name":"run_command","args":{"CommandLine":"ls"}}}' \
            '{"workspacePaths":[5],"toolCall":{"name":"run_command","args":{"CommandLine":"ls"}}}' '\377\376' '{"x":"\377"}' \
            '{"toolCall":{"name":"run_command","args":{"CommandLine":"ls"}}}'; do
  assert_eq "body [$body] is refused" deny "$(R "$body")"
done
mal(){ python3 -c 'import json,sys;print(json.dumps({"workspacePaths":[sys.argv[1]],"toolCall":json.loads(sys.argv[2])}))' "$LR" "$1"; }
for tc in '5' 'null' '{"name":5}' '{"name":"read_file","args":[]}' '{"name":"read_file","args":{"Path":5}}' '{"name":"run_command","args":{"CommandLine":["ls"]}}' '{"args":{}}'; do
  assert_eq "toolCall $tc is refused" deny "$(H "$LR" pre-tool-use "$(mal "$tc")" | dec)"
done
assert_eq "the hook's exit status is 0 on a refusal, or agy reads it another way" 0 "$( (cd "$LR/.agents" && printf 'x' | env -u LANE_WORKSPACE -u LANE_PRODUCT lane hook --agent antigravity pre-tool-use >/dev/null 2>&1); echo $?)"
echo "-- when the adapter itself breaks"
CT="$T/crash"; mkdir -p "$CT/scripts/hooks" "$CT/registry/lanes" "$CT/lanes" "$CT/repos"; : > "$CT/registry/config.yml"; cp "$PROD/scripts/hooks/guard.py" "$CT/scripts/hooks/"; cp "$PROD/scripts/roots.py" "$CT/scripts/"
B='{"workspacePaths":["/tmp"],"toolCall":{"name":"run_command","args":{"CommandLine":"ls"}}}'
assert_eq "no adapter at all: deny" deny "$(printf '%s' "$B" | env -u LANE_WORKSPACE -u LANE_PRODUCT python3 -B "$CT/scripts/hooks/guard.py" --agent antigravity --event pre-tool-use 2>/dev/null | dec)"
cp -R "$PROD/scripts/agents" "$CT/scripts/agents"; echo 'def (' >> "$CT/scripts/agents/antigravity.py"
assert_eq "an adapter that does not parse: deny" deny "$(printf '%s' "$B" | env -u LANE_WORKSPACE -u LANE_PRODUCT python3 -B "$CT/scripts/hooks/guard.py" --agent antigravity --event pre-tool-use 2>/dev/null | dec)"
assert_eq "an agent nobody registered: deny, in the only form left" NODECISION "$(printf '%s' "$B" | env -u LANE_WORKSPACE -u LANE_PRODUCT python3 -B "$CT/scripts/hooks/guard.py" --agent nobody --event pre-tool-use 2>/dev/null | dec)"
echo "-- project rules"
cat > "$WS/.repolane/registry/rules.yaml" <<'YML'
rules:
  - id: by-agy-name
    when: { tool: run_command, matches: 'agyname' }
    deny: no
    ref: docs/x.md
  - id: by-claude-name
    when: { tool: Bash, matches: 'claudename' }
    deny: no
    ref: docs/x.md
  - id: by-kind
    when: { tool: shell, matches: 'kindname' }
    deny: no
    ref: docs/x.md
  - id: edit-covers-writes
    when: { tool: Edit, path: 'gen/**' }
    deny: no
    ref: docs/x.md
YML
for w in agyname claudename kindname; do assert_contains "a rule by $w fires" "$(H "$LR" pre-tool-use "$(pre "$LR" run_command "$(c "$w x")")")" "project rule"; done
assert_contains "tool: Edit covers write_file" "$(H "$LR" pre-tool-use "$(pre "$LR" write_file "$(p "$WT/gen/x")")")" "edit-covers-writes"
assert_contains "and edit_file" "$(H "$LR" pre-tool-use "$(pre "$LR" edit_file "$(p "$WT/gen/x")")")" "edit-covers-writes"
rm "$WS/.repolane/registry/rules.yaml"
echo "-- context, each step"
inv(){ python3 -c 'import json,sys;print(json.dumps({"conversationId":sys.argv[2],"workspacePaths":[sys.argv[1]],"invocationNum":int(sys.argv[3]),"lastUserInput":"fix the login"}))' "$1" "$2" "$3"; }
ctx(){ H "$1" user-prompt-submit "$(inv "$1" "$2" "$3")" | python3 -c 'import json,sys;d=json.load(sys.stdin);print(sys.argv[1] if "systemMessage" in str(d.keys()) else "\n".join(s["ephemeralMessage"] for s in d["injectSteps"]))' SYSTEM; }
c1=$(ctx "$LR" c1 0); c2=$(ctx "$LR" c1 1)
assert_contains "the lane's state" "$c1" "STATE of lane L1"
assert_contains "the rules, each step, with no PreCompact to lean on" "$c1" "work only under lanes/L1/"
assert_contains "memory" "$c1" "MEMORY"
assert_contains "and again on the next step" "$c2" "STATE of lane L1"
assert_contains "the rules again" "$c2" "work only under lanes/L1/"
assert_contains "memory again: yesterday's ephemeral message is gone" "$c2" "MEMORY"
ctxroot=$(ctx "$WS" c9 0); assert_contains "at the root too" "$ctxroot" "dispatcher root"
for t in "$c1" "$ctxroot"; do for w in EnterWorktree ExitWorktree "claude --resume" Claude; do assert_not_contains "context has no $w" "$t" "$w"; done; done
assert_contains "a first touch of a repo brings its rules on the next step" "$(printf '%s' x >/dev/null; D "$LR" edit_file "$(p "$WS/lanes/L1/web/README.md")" >/dev/null; ctx "$LR" c1 2)" "RULES for web"
ss=$(H "$LR" session-start "$(inv "$LR" c1 0)")
assert_contains "SessionStart injects a userMessage" "$ss" '"userMessage"'
assert_not_contains "never a systemMessage" "$ss" "systemMessage"
for w in EnterWorktree ExitWorktree "claude --resume"; do assert_not_contains "the session-start text has no $w" "$ss" "$w"; done
ss=$(H "$WS" session-start "$(inv "$WS" c9 0)")
for w in EnterWorktree ExitWorktree "claude --resume"; do assert_not_contains "the dispatcher text has no $w" "$ss" "$w"; done
assert_contains "the dispatcher text is the board" "$ss" "L1"
echo "-- past conversations"
L "$WS" sessions L1; assert_contains "a conversation is filed under its lane" "$OUT" "c1"; assert_contains "it says how to resume" "$OUT" "agy --conversation"; assert_contains "with what was said" "$OUT" "fix the login"
assert_not_contains "not claude" "$OUT" "claude --resume"
L "$WS" sessions api; assert_contains "and under the repo" "$OUT" "c1"
L "$WS" sessions T1; assert_not_contains "not under another lane" "$OUT" "c1  "
assert "the ledger is under the workspace" test -f "$WS/.repolane/cache/conversations.jsonl"
echo "-- the end of a turn"
stop(){ python3 -c 'import json,sys;print(json.dumps({"conversationId":"c1","workspacePaths":[sys.argv[1]],"fullyIdle":sys.argv[2]=="y","terminationReason":"NO_TOOL_CALL"}))' "$1" "$2"; }
post(){ python3 -c 'import json,sys;print(json.dumps({"conversationId":"c1","workspacePaths":[sys.argv[1]],"toolCall":{"name":"edit_file","args":{"Path":sys.argv[2]}}}))' "$1" "$2"; }
assert_eq "PostToolUse answers {}" "{}" "$(H "$LR" post-tool-use "$(post "$LR" "$WT/a.txt")")"
assert "and records the file" test -s "$LR/.touched"
assert_eq "Stop, still busy: answers {}" "{}" "$(H "$LR" turn-end "$(stop "$LR" n)")"
assert_not_contains "and logs nothing" "$(cat "$WS/.repolane/registry/lanes/L1.md")" "turn ended"
assert_eq "Stop, idle: answers {}" "{}" "$(H "$LR" turn-end "$(stop "$LR" y)")"
assert_contains "and writes the state line" "$(cat "$WS/.repolane/registry/lanes/L1.md")" "turn ended"
echo "-- a claude session in the same workspace"
cl(){ python3 -c 'import json,sys;print(json.dumps({"hook_event_name":"PreToolUse","session_id":"x","cwd":sys.argv[1],"tool_name":sys.argv[2],"tool_input":json.loads(sys.argv[3])}))' "$1" "$2" "$3"; }
CH(){ (cd "$1" && printf '%s' "$2" | env -u LANE_WORKSPACE -u LANE_PRODUCT CLAUDE_PROJECT_DIR="$1" lane hook pre-tool-use 2>/dev/null); }
fp(){ python3 -c 'import json,sys;print(json.dumps({"file_path":sys.argv[1]}))' "$1"; }
assert_contains "it answers in Claude Code's format" "$(CH "$LR" "$(cl "$LR" Read "$(fp "$WT/.env")")")" '"permissionDecision": "deny"'
assert_contains "it cannot rewrite agy's hooks" "$(CH "$LR" "$(cl "$LR" Write "$(fp "$WT/.agents/hooks.json")")")" '"permissionDecision": "deny"'
assert_contains "or the choice of agent, from the root" "$(CH "$WS" "$(cl "$WS" Edit "$(fp "$WS/.repolane/config.yml")")")" '"permissionDecision": "deny"'
assert_contains "its session-start still speaks Claude" "$(cd "$LR" && printf '{"source":"startup","session_id":"s","cwd":"%s"}' "$LR" | env -u LANE_WORKSPACE -u LANE_PRODUCT CLAUDE_PROJECT_DIR="$LR" lane hook session-start 2>/dev/null)" "hookSpecificOutput"
echo "-- a workspace that never opted in, and a clone"
W2="$T/ws2"; mkdir -p "$W2"; L "$T" init "$W2" --owner Pat --yes --claude-home "$T/claude2"
assert "no agy files" test ! -e "$W2/.agents"; assert "no AGENTS.md" test ! -e "$W2/AGENTS.md"; assert_not_contains "no agent line" "$(cat "$W2/.repolane/config.yml")" "agent:"
L "$W2" agent name; assert_eq "it is Claude" claude "$OUT"
assert_eq "a root Claude session may still edit config.yml, as always" "" "$(CH "$W2" "$(cl "$W2" Edit "$(fp "$W2/.repolane/config.yml")")" | grep deny)"
L "$W2" init --agent antigravity --yes; assert_eq "opting in later works" 0 "$RC"; assert "and wires the root" test -f "$W2/.agents/hooks.json"
init_plane >/dev/null 2>&1; OUT=$(cd "$PLANE" && env -u LANE_PRODUCT -u LANE_WORKSPACE ./lane init --agent antigravity --yes </dev/null 2>&1); assert_contains "a clone does not take --agent" "$OUT" "unknown option --agent"
finish
