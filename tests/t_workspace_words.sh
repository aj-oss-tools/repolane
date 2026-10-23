#!/usr/bin/env bash
# What a session in a workspace is told speaks of the workspace: every hook's output (SessionStart at the root and in a
# lane, a resumed conversation, UserPromptSubmit, EnterWorktree, PreCompact, the Worktree hooks and the guard's
# refusals) and lane-memory's, with the real paths (.repolane/…), commands by the name the package puts on PATH, and
# REPOLANE.md / LANE.md for the rules. Nothing a clone says about itself: scripts/lane-*, "control plane", registry/
# or memory/ at the top, a relative scripts/<name> that "exits 127", the product's own scripts folder.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
new_sandbox
install_product
unset -f lane   # lib.sh's lane() runs a clone; here it is the installed command
CLEAN_PATH=$(printf '%s' "$PATH" | tr ':' '\n' | while IFS= read -r d; do [ -n "$d" ] && [ ! -e "$d/lane" ] && printf '%s:' "$d"; done)
export PATH="$BIN:${CLEAN_PATH%:}"
W="$T/ws"; mkdir -p "$W"
(cd "$W" && lane init --owner "Sam Owner" --yes --claude-home "$T/claude" </dev/null) > "$T/init.log" 2>&1 || cat "$T/init.log"
assert "the workspace is made" test -d "$W/.repolane"
make_remote_repo api; make_remote_repo web
(cd "$W" && lane add "$T/remotes/api.git" api --yes </dev/null >/dev/null 2>&1)
(cd "$W" && lane add "$T/remotes/web.git" web --yes </dev/null >/dev/null 2>&1)
(cd "$W" && lane start L1 api web </dev/null >/dev/null 2>&1)
(cd "$W" && lane start L2 api:l2 </dev/null >/dev/null 2>&1)
assert "lane L1 is started" test -d "$W/lanes/L1/api"
D="$W/.repolane"
ALL="$T/all-output.txt"; : > "$ALL"
# H <label> <event> <cwd> <json-body-without-braces> : run `lane hook <event>` the way Claude Code does, keep the output
H(){ local label="$1" ev="$2" cwd="$3" body="$4" o
  o=$(cd "$cwd" && printf '{"hook_event_name":"%s","cwd":"%s","session_id":"s-%s"%s}' "$5" "$cwd" "$RANDOM" "$body" \
      | CLAUDE_PROJECT_DIR="$6" lane hook "$ev" 2>&1)
  printf '\n=== %s\n%s\n' "$label" "$o" >> "$ALL"; LAST="$o"; }
pre(){ H "$1" pre-tool-use "$2" ",\"tool_name\":\"$3\",\"tool_input\":$4" PreToolUse "${5:-$W}"; }
assert_deny(){ assert_contains "refused: $1" "$LAST" '"deny"'; }

echo "-- SessionStart, at the root and in a lane"
H "session-start root" session-start "$W" ',"source":"startup"' SessionStart "$W"
assert_contains "the root's SessionStart names the owner" "$LAST" "Sam Owner"
assert_contains "and points at REPOLANE.md for the details" "$LAST" "REPOLANE.md"
H "session-start lane" session-start "$W/lanes/L1" ',"source":"startup"' SessionStart "$W/lanes/L1"
assert_contains "a lane's SessionStart shows the lane" "$LAST" "session in lane 'L1'"
assert_contains "and the real path of its file" "$LAST" "$D/registry/lanes/L1.md"
# a resumed conversation that belongs to a mirror
slug=$(printf '%s' "$D/repos" | LC_ALL=C sed 's#[^A-Za-z0-9-]#-#g')
mkdir -p "$HOME/.claude/projects/$slug-api"; : > "$HOME/.claude/projects/$slug-api/s-old.jsonl"
o=$(cd "$W" && printf '{"hook_event_name":"SessionStart","source":"resume","session_id":"s-old","cwd":"%s"}' "$W" | CLAUDE_PROJECT_DIR="$W" lane hook session-start 2>&1)
printf '\n=== session-start resume root\n%s\n' "$o" >> "$ALL"
assert_contains "a resumed conversation is placed" "$o" "belongs to repo 'api'"
o=$(cd "$W/lanes/L2" && printf '{"hook_event_name":"SessionStart","source":"resume","session_id":"s-old","cwd":"%s"}' "$W/lanes/L2" | CLAUDE_PROJECT_DIR="$W/lanes/L2" lane hook session-start 2>&1)
printf '\n=== session-start resume in a lane without that repo\n%s\n' "$o" >> "$ALL"

echo "-- UserPromptSubmit, PostToolUse EnterWorktree, PreCompact, the Worktree hooks"
H "prompt root" user-prompt-submit "$W" ',"prompt":"hi"' UserPromptSubmit "$W"
H "prompt lane" user-prompt-submit "$W/lanes/L1" ',"prompt":"hi"' UserPromptSubmit "$W/lanes/L1"
assert_contains "the lane's state names the real lane file" "$LAST" "$D/registry/lanes/L1.md"
H "enter worktree" post-tool-use "$W/lanes/L1" ',"tool_name":"EnterWorktree","tool_input":{"name":"L1"}' PostToolUse "$W"
assert_contains "EnterWorktree hands over LANE.md" "$LAST" "You are inside a lane"
H "pre-compact" pre-compact "$W/lanes/L1" ',"trigger":"auto"' PreCompact "$W/lanes/L1"
H "worktree-create in lane" worktree-create "$W/lanes/L1" ',"name":"L2"' WorktreeCreate "$W/lanes/L1"
H "worktree-create repo" worktree-create "$W" ',"name":"L9/api"' WorktreeCreate "$W"
H "worktree-remove" worktree-remove "$W" ',"worktree_path":"x"' WorktreeRemove "$W"

echo "-- the guard's refusals"
pre "edit other lane" "$W/lanes/L1" Edit "{\"file_path\":\"$W/lanes/L2/api/README.md\",\"old_string\":\"a\",\"new_string\":\"b\"}" "$W/lanes/L1"
assert_deny "another lane's file"
assert_not_contains "it names lane-with by the command on PATH" "$LAST" "scripts/lane-with"
pre "glob other lane" "$W/lanes/L1" Glob "{\"pattern\":\"*\",\"path\":\"$W/lanes/L2\"}" "$W/lanes/L1"
pre "write mirror" "$W/lanes/L1" Write "{\"file_path\":\"$D/repos/api/x.txt\",\"content\":\"x\"}" "$W/lanes/L1"
assert_deny "a write in a mirror"
pre "write memory" "$W" Write "{\"file_path\":\"$D/memory/new-note.md\",\"content\":\"x\"}"
assert_deny "a memory written directly"
assert_contains "the scopes table names the real memory folder" "$LAST" ".repolane/memory/<slug>.md"
pre "edit registry from lane" "$W/lanes/L1" Edit "{\"file_path\":\"$D/registry/repos.yaml\",\"old_string\":\"a\",\"new_string\":\"b\"}" "$W/lanes/L1"
assert_deny "the registry edited from a lane"
pre "edit lane from root" "$W" Edit "{\"file_path\":\"$W/lanes/L1/api/README.md\",\"old_string\":\"a\",\"new_string\":\"b\"}"
assert_deny "a lane reached into from the root"
pre "read outside" "$W" Read "{\"file_path\":\"$T/src/api/README.md\"}"
pre "bash mirror checkout" "$W" Bash "{\"command\":\"git -C $D/repos/api checkout -b x\"}"
pre "bash rm worktree" "$W" Bash "{\"command\":\"rm -rf $W/lanes/L1\"}"
pre "bash cd other lane" "$W/lanes/L1" Bash "{\"command\":\"cd $W/lanes/L2/api && ls\"}" "$W/lanes/L1"
pre "bash merge run" "$W/lanes/L1" Bash "{\"command\":\"lane-merge L1 L2 --run\"}" "$W/lanes/L1"
pre "bash stash" "$W/lanes/L1" Bash "{\"command\":\"git -C api stash\"}" "$W/lanes/L1"
pre "bash plane script" "$W/lanes/L1" Bash "{\"command\":\"lane-add $T/remotes/web.git web2\"}" "$W/lanes/L1"
cat > "$D/registry/rules.shared.yaml" <<'YML'
rules:
  - id: shared-no-deploy
    when: { tool: Bash, matches: "deploy-now" }
    deny: "Deploys go through the pipeline."
    ref: "memory/deploys.md"
YML
pre "shared rule" "$W" Bash '{"command":"deploy-now prod"}'
assert_deny "a shared project rule"
assert_contains "the shared rule's refusal names the file it came from" "$LAST" ".repolane/registry/rules.shared.yaml"
assert_contains "and calls it a rule of this workspace" "$LAST" "project rule of this workspace"

echo "-- lane-memory"
o=$(cd "$W/lanes/L1" && lane-memory draft note1 "---
name: note1
description: d
---
x" 2>&1; lane-memory list 2>&1; lane-memory file note1 lane L1 2>&1; lane-memory draft note2 "x" 2>&1; lane-memory file note2 bogus 2>&1)
o2=$(cd "$W" && lane-memory draft c1 "x" >/dev/null 2>&1; lane-memory file c1 cross 2>&1; lane-memory draft r1 "x" >/dev/null 2>&1; lane-memory file r1 repo api 2>&1; lane-memory draft p1 "x" >/dev/null 2>&1; lane-memory file p1 pref 2>&1)
assert_contains "lane-memory file cross names where it filed it" "$o2" "filed: .repolane/memory/c1.md"
assert_contains "lane-memory file repo too" "$o2" "filed: .repolane/memory/api/r1.md"
assert_contains "and pref" "$o2" "appended to .repolane/knowledge/preferences.md"
o="$o
$o2"
(cd "$W" && lane help) >> "$ALL" 2>&1
printf '\n=== lane-memory\n%s\n' "$o" >> "$ALL"

echo "-- none of it is a clone's wording"
for s in "scripts/lane-" "control plane" " registry/" "\`registry/" " memory/" "\`memory/" " knowledge/" " repos/" "exits 127" "exit 127" \
         "$PROD/scripts" "details in CLAUDE.md" "CLAUDE.md \"Dispatcher mode\"" "scripts/sessions" "scripts/env.sh"; do
  hits=$(grep -nF -- "$s" "$ALL" | head -3)
  if [ -z "$hits" ]; then ok "no '$s' in any output"; else bad "no '$s' in any output" "$hits"; fi
done

echo "-- the editor workspace files hide the mirrors and the cache where they are"
excl(){ python3 -c 'import json,sys; d=json.load(open(sys.argv[1]))["settings"]; print(" ".join(sorted(k for k in d["files.exclude"] if not k.startswith("**"))), "|", " ".join(sorted(k for k in d["search.exclude"] if not k.startswith("**"))))' "$1"; }
assert_eq "lane.code-workspace hides .repolane/repos and .repolane/cache" ".repolane/cache .repolane/repos lanes | .repolane/cache .repolane/repos lanes" "$(excl "$W/lane.code-workspace")"
assert_eq "and so does a lane's" ".repolane/cache .repolane/repos lanes | .repolane/cache .repolane/repos lanes" "$(excl "$W/lanes/L1/L1.code-workspace")"
echo "-- the package describes itself as a workspace"
assert_not_contains "pyproject.toml's description" "$(grep '^description' "$PRODUCT/pyproject.toml")" "control plane"
assert_not_contains "README's first paragraph" "$(sed -n '1,12p' "$PRODUCT/README.md")" "control plane"
assert_not_contains "extending.md's opening" "$(sed -n '1,5p' "$PRODUCT/docs/extending.md")" "control plane"

echo "-- a git clone keeps a clone's words"
init_plane >/dev/null 2>&1
(cd "$PLANE" && ./lane add "$T/remotes/api.git" api </dev/null >/dev/null 2>&1; ./lane start C1 api </dev/null >/dev/null 2>&1; ./lane start C2 api:c2 </dev/null >/dev/null 2>&1)
assert "the clone's lane is started" test -d "$PLANE/lanes/C1/api"
o=$(cd "$PLANE" && printf '{"hook_event_name":"SessionStart","source":"startup","session_id":"c","cwd":"%s"}' "$PLANE" | env -u LANE_PRODUCT -u LANE_WORKSPACE "$PLANE/scripts/session-start" 2>&1)
assert_contains "the clone's SessionStart names its scripts dir" "$o" "Scripts dir (absolute): $PLANE/scripts"
assert_contains "and its instructions name scripts/lane-resume" "$o" "scripts/lane-resume <id>"
assert_contains "and CLAUDE.md for the details" "$o" 'details in CLAUDE.md'
o=$(printf '{"hook_event_name":"PreToolUse","tool_name":"Edit","tool_input":{"file_path":"%s","old_string":"a","new_string":"b"},"cwd":"%s","session_id":"c"}' "$PLANE/lanes/C2/api/README.md" "$PLANE/lanes/C1" \
    | CLAUDE_PROJECT_DIR="$PLANE/lanes/C1" env -u LANE_PRODUCT -u LANE_WORKSPACE python3 "$PLANE/scripts/hooks/guard.py" 2>&1)
assert_contains "the clone's refusal names scripts/lane-with" "$o" "scripts/lane-with C1 <repo>"
o=$(printf '{"hook_event_name":"PreToolUse","tool_name":"Write","tool_input":{"file_path":"%s","content":"x"},"cwd":"%s","session_id":"c"}' "$PLANE/memory/x.md" "$PLANE" \
    | CLAUDE_PROJECT_DIR="$PLANE" env -u LANE_PRODUCT -u LANE_WORKSPACE python3 "$PLANE/scripts/hooks/guard.py" 2>&1)
assert_contains "the clone's scopes table names memory/" "$o" "cross-repo   memory/<slug>.md"
assert_eq "a clone's lane.code-workspace still hides repos and .cache" ".cache lanes repos | .cache lanes repos" "$(excl "$PLANE/lane.code-workspace")"
finish
