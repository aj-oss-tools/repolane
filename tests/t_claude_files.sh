#!/usr/bin/env bash
# Repolane's slash commands and agents reach a workspace: `lane init` copies templates/claude/{commands,agents} into the
# workspace's .claude/, by name, and records what it wrote (.repolane/claude-files.json). A refresh replaces only a file
# that is still exactly what an earlier version wrote; the user's own file of the same name, or one of ours they edited,
# is kept, and one they deleted stays deleted. `lane doctor` checks them and `--fix` brings them up to date.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
new_sandbox
install_product
unset -f lane
CLEAN_PATH=$(printf '%s' "$PATH" | tr ':' '\n' | while IFS= read -r d; do [ -n "$d" ] && [ ! -e "$d/lane" ] && printf '%s:' "$d"; done)
export PATH="$BIN:${CLEAN_PATH%:}"
L(){ local d="$1"; shift; OUT=$(cd "$d" && env -u LANE_WORKSPACE lane "$@" </dev/null 2>&1); RC=$?; }
TPL="$PROD/templates/claude"
n_tpl=$(ls "$TPL"/commands/*.md "$TPL"/agents/*.md | wc -l | tr -d ' ')
REC=.repolane/claude-files.json

echo "-- lane init installs them"
W="$T/ws"; mkdir -p "$W"
L "$W" init --owner Sam --yes --claude-home "$T/claude"; assert_eq "init" 0 "$RC"
for f in commands/status.md commands/lane-brief.md commands/lane-start.md agents/lane-manager.md agents/context-loader.md; do
  assert_eq "init wrote .claude/$f, the installed version's" "$(cat "$TPL/$f")" "$(cat "$W/.claude/$f" 2>/dev/null)"
done
assert_eq "every one of them" "$n_tpl" "$(ls "$W"/.claude/commands/*.md "$W"/.claude/agents/*.md 2>/dev/null | wc -l | tr -d ' ')"
assert "and recorded what it wrote" test -f "$W/$REC"
assert_contains "init says so" "$OUT" ".claude/commands, .claude/agents"
assert_not_contains "a workspace's slash commands run nothing by a clone's bin/ path" "$(cat "$W"/.claude/commands/*.md)" "/bin/lane-"
assert_contains "they call the commands on PATH" "$(cat "$W/.claude/commands/status.md")" '!`lane-status $ARGUMENTS'
assert_not_contains "the agents name no clone paths" "$(cat "$W"/.claude/agents/*.md)" '$AD/scripts'
L "$W" doctor --yes
assert_contains "doctor checks them" "$OUT" "Repolane's slash commands and agents are in .claude/ ($n_tpl file(s)"

echo "-- a file of the user's by the same name is never replaced"
U="$T/user"; mkdir -p "$U/.claude/commands"; printf 'my own status command\n' > "$U/.claude/commands/status.md"
L "$U" init --owner Sam --yes --claude-home "$T/claude"; assert_eq "init over a user's .claude/" 0 "$RC"
assert_eq "the user's status.md is kept" "my own status command" "$(cat "$U/.claude/commands/status.md")"
assert_contains "init says it kept it" "$OUT" ".claude/commands/status.md is yours: kept"
assert "and installs the rest" test -f "$U/.claude/commands/lane-brief.md"
L "$U" doctor
assert_contains "doctor notes the user's file" "$OUT" ".claude/commands/status.md is your own file"
L "$U" doctor --fix --yes
assert_eq "doctor --fix keeps it too" "my own status command" "$(cat "$U/.claude/commands/status.md")"

echo "-- a refresh replaces what an earlier version wrote, keeps what was edited, leaves a deleted one deleted"
python3 - "$W" <<'PY'
import hashlib, json, sys
w = sys.argv[1]; rec = json.load(open(f"{w}/.repolane/claude-files.json"))
def put(rel, text):
    open(f"{w}/.claude/{rel}", "w").write(text); rec[rel] = hashlib.sha256(text.encode()).hexdigest()
put("commands/lane-park.md", "what an earlier version wrote\n")              # old, unedited: replaced
put("commands/lane-done.md", "an earlier version\n")
open(f"{w}/.claude/commands/lane-done.md", "w").write("an earlier version, edited by the owner\n")   # edited: kept
put("commands/lane-gone.md", "a command a later version dropped\n")         # retired, unedited: removed
put("agents/old-agent.md", "an agent a later version dropped\n")
open(f"{w}/.claude/agents/old-agent.md", "w").write("dropped, but edited\n")  # retired, edited: kept
json.dump(rec, open(f"{w}/.repolane/claude-files.json", "w"))
PY
rm "$W/.claude/commands/lane-help.md"
L "$W" doctor
assert_eq "doctor fails while they are out of date" 1 "$RC"
assert_contains "and names the earlier version's file" "$OUT" "from an earlier version: commands/lane-park.md"
assert_contains "and the one no longer shipped" "$OUT" "no longer shipped: commands/lane-gone.md"
assert_contains "and notes the edited one" "$OUT" ".claude/commands/lane-done.md is your own file"
assert_contains "and the deleted one" "$OUT" ".claude/commands/lane-help.md was removed"
echo 0.0.1 > "$W/.repolane/version"          # an older version recorded: the next lane command refreshes the workspace
L "$W" status
assert_eq "the earlier version's file is replaced" "$(cat "$TPL/commands/lane-park.md")" "$(cat "$W/.claude/commands/lane-park.md")"
assert_eq "the edited one is kept" "an earlier version, edited by the owner" "$(cat "$W/.claude/commands/lane-done.md")"
assert "a dropped one, unedited, is removed" test ! -e "$W/.claude/commands/lane-gone.md"
assert_eq "a dropped one, edited, is kept" "dropped, but edited" "$(cat "$W/.claude/agents/old-agent.md")"
assert "a deleted one stays deleted" test ! -e "$W/.claude/commands/lane-help.md"
L "$W" doctor
assert_contains "doctor is satisfied after the refresh" "$OUT" "Repolane's slash commands and agents are in .claude/"
assert_not_contains "nothing to fix there" "$OUT" "are not the installed version's"

echo "-- doctor --fix writes a missing one that was never recorded"
python3 - "$W" <<'PY'
import json, sys
w = sys.argv[1]; p = f"{w}/.repolane/claude-files.json"; rec = json.load(open(p)); rec.pop("commands/lane-help.md", None); json.dump(rec, open(p, "w"))
PY
L "$W" doctor; assert_contains "a missing one is a problem" "$OUT" "missing: commands/lane-help.md"
L "$W" doctor --fix --yes
assert "doctor --fix writes it" test -f "$W/.claude/commands/lane-help.md"

echo "-- a git clone's own .claude/ is untouched"
init_plane >/dev/null 2>&1
assert_contains "a clone's commands still run its bin/" "$(cat "$PLANE/.claude/commands/status.md")" '"$CLAUDE_PROJECT_DIR"/bin/lane-status'
assert "and get no record" test ! -e "$PLANE/$REC"
finish
