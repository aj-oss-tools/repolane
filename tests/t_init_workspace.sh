#!/usr/bin/env bash
# `lane init` and `lane doctor` for an installed product (a built wheel when a builder is here, see install_product):
# init in an empty folder, over the user's own CLAUDE.md (answered y, n, --yes, and with no terminal) and settings.json,
# again over a live workspace, with --git; the planes.json registration; each problem the doctor knows, found, and
# repaired by --fix, with the exit codes; and one realistic flow from init to a Goal saved from inside a lane.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
new_sandbox
install_product
# the sandbox's PATH, with every folder that holds some other `lane` taken out (the real ~/.local/bin among them)
CLEAN_PATH=$(printf '%s' "$PATH" | tr ':' '\n' | while IFS= read -r d; do [ -n "$d" ] && [ ! -e "$d/lane" ] && printf '%s:' "$d"; done)
CLEAN_PATH="${CLEAN_PATH%:}"
export PATH="$BIN:$CLEAN_PATH"
assert_eq "lane on PATH is the installed product's" "$BIN/lane" "$(type -P lane)"
VER=$(tr -d '[:space:]' < "$PROD/VERSION")
PLANES="$HOME/.local/share/lane/planes.json"
IMPORT='@.repolane/REPOLANE.md'

# L <dir> <args…> : lane from <dir>, no terminal; P <answer> <dir> <args…> : the same with a real terminal, answering
# every [Y/n] / [y/N] prompt with <answer>
L(){ local d="$1"; shift; OUT=$(cd "$d" && env -u LANE_WORKSPACE -u LANE_PRODUCT lane "$@" </dev/null 2>&1); RC=$?; }
P(){ local a="$1" d="$2"; shift 2
  OUT=$(cd "$d" && env -u LANE_WORKSPACE -u LANE_PRODUCT TERM=dumb python3 - "$a" "$@" <<'PY'
import os, pty, select, sys, time
ans, cmd = (sys.argv[1] + "\n").encode(), ["lane"] + sys.argv[2:]
pid, fd = pty.fork()
if pid == 0:
    os.execvp(cmd[0], cmd)
out, seen, t0 = b"", 0, time.time()
while True:
    r, _, _ = select.select([fd], [], [], 0.3)
    if r:
        try: d = os.read(fd, 4096)
        except OSError: break
        if not d: break
        out += d
        n = out.count(b"[Y/n]") + out.count(b"[y/N]")
        while seen < n: os.write(fd, ans); seen += 1
    if time.time() - t0 > 120:
        os.kill(pid, 9); out += b"\n[timed out]\n"; break
_, st = os.waitpid(pid, 0)
sys.stdout.write(out.decode(errors="replace").replace("\r", ""))
sys.exit(os.WEXITSTATUS(st) if os.WIFEXITED(st) else 1)
PY
); RC=$?; }
tree_sum(){ (cd "$1" && find . -path ./.git -prune -o -type f -print | LC_ALL=C sort | xargs cksum); }
ws_registered(){ python3 -c 'import json,sys; sys.exit(0 if sys.argv[2] in json.load(open(sys.argv[1])).get("workspaces",{}) else 1)' "$PLANES" "$1"; }
hooks_of(){ python3 -c 'import json,sys
d=json.load(open(sys.argv[1]))
for ev,es in d.get("hooks",{}).items():
    for e in es:
        for h in e["hooks"]: print(ev+"\t"+h["command"])' "$1"; }
expected_hooks(){ python3 -B -c 'import json,sys; sys.path.insert(0,sys.argv[1]); import roots; print(json.dumps(roots.workspace_hooks(),sort_keys=True))' "$PROD/scripts"; }
hooks_json(){ python3 -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1])).get("hooks"),sort_keys=True))' "$1"; }
WANT_HOOKS=$(expected_hooks)

echo "-- init in an empty folder"
A="$T/a"; mkdir -p "$A"
L "$A" init --owner "Sam Owner"; assert_eq "init succeeds" 0 "$RC"
for p in .repolane/registry/lanes .repolane/memory .repolane/knowledge .repolane/repos .repolane/cache lanes; do assert "made $p/" test -d "$A/$p"; done
for f in REPOLANE.md LANE.md config.yml env.sh version registry/repos.yaml memory/MEMORY.md; do assert "made .repolane/$f" test -f "$A/.repolane/$f"; done
assert_eq "a new CLAUDE.md imports REPOLANE.md" 1 "$(grep -cx "$IMPORT" "$A/CLAUDE.md")"
assert_contains "the owner is recorded" "$(cat "$A/.repolane/config.yml")" "name: Sam Owner"
assert_eq "the top settings hold exactly Repolane's hooks" "$WANT_HOOKS" "$(hooks_json "$A/.claude/settings.json")"
assert "registered in planes.json" ws_registered "$A"
assert "no git repo without --git" test ! -e "$A/.git"
assert_contains "init names the next step" "$OUT" "lane add"
assert_not_contains "and finds lane on PATH for the hooks" "$OUT" "UNGUARDED"
CH="$HOME/.claude"; slug(){ printf '%s' "$1" | LC_ALL=C sed 's#[^A-Za-z0-9-]#-#g'; }
assert_contains "no terminal: the memory link is shown, not made" "$OUT" "$(slug "$A")/memory -> .repolane/memory"
assert_contains "and it says nothing under ~/.claude changed" "$OUT" "Nothing under ~/.claude was changed"
assert "and nothing was made there" test ! -e "$CH/projects/$(slug "$A")"
assert_contains "the status line is wired" "$(cat "$A/.claude/settings.json")" '"command": "lane statusline"'
L "$A" doctor; assert_eq "doctor fails while the memory link is missing" 1 "$RC"
assert_contains "and names it" "$OUT" "$(slug "$A")/memory (the workspace root) not linked"
L "$A" doctor --fix --yes; assert_eq "doctor --fix --yes links it" 0 "$RC"
assert_eq "the root's memory is linked to .repolane/memory" "$A/.repolane/memory" "$(readlink "$CH/projects/$(slug "$A")/memory")"
L "$A" doctor; assert_eq "doctor passes right after init" 0 "$RC"
for c in "runs this workspace's hooks" "CLAUDE.md imports .repolane/REPOLANE.md" "runs Repolane's lane hook commands" \
         "LANE.md are version $VER's" "registered in" "memory is linked into .repolane/memory" "status line: lane statusline"; do assert_contains "doctor: $c" "$OUT" "$c"; done
assert_not_contains "doctor reports nothing wrong" "$OUT" "!!"

echo "-- init with a folder named, from somewhere else"
L "$T" init "$T/named/ws" --yes; assert_eq "init <folder> succeeds" 0 "$RC"
assert "the named folder is made a workspace" test -d "$T/named/ws/.repolane"
assert "registered by its real path" ws_registered "$T/named/ws"
assert "nothing was made in the folder init ran from" test ! -e "$T/.repolane"
L "$T/named/ws/lanes" init --yes; assert_eq "init inside a workspace is refused" 2 "$RC"
assert_contains "and says which workspace it is in" "$OUT" "inside the workspace $T/named/ws"
assert "and makes nothing there" test ! -e "$T/named/ws/lanes/.repolane"

echo "-- re-init over a live workspace changes nothing"
before=$(tree_sum "$A"); pbefore=$(cksum < "$PLANES")
L "$A" init --owner "Sam Owner"; assert_eq "re-init succeeds" 0 "$RC"
assert_contains "and says nothing was changed" "$OUT" "nothing was changed"
assert_not_contains "and lists nothing as made" "$OUT" "made"
assert_eq "no file in the workspace changed" "$before" "$(tree_sum "$A")"
assert_eq "planes.json unchanged" "$pbefore" "$(cksum < "$PLANES")"
L "$A" init --owner "Someone Else" --yes
assert_contains "a different --owner is not written over the recorded one" "$OUT" "already names Sam Owner"
assert_eq "config.yml unchanged" "$before" "$(tree_sum "$A")"
rm -rf "$A/lanes"; L "$A" init --yes
assert_contains "a folder removed by hand is made again" "$OUT" "made  lanes/"
assert "lanes/ is back" test -d "$A/lanes"

echo "-- an existing CLAUDE.md: asked, and only edited on yes"
mk_claude(){ mkdir -p "$1"; printf '# My own notes\n\nkeep me\n' > "$1/CLAUDE.md"; }
ORIG=$(printf '# My own notes\n\nkeep me\n')
B="$T/cy"; mk_claude "$B"
P y "$B" init --owner X; assert_eq "init with a terminal, answered y" 0 "$RC"
assert_contains "the exact line is shown" "$OUT" "      $IMPORT"
assert_contains "and the question asked" "$OUT" "Add it? [Y/n]"
assert_eq "y adds the line, once" 1 "$(grep -cx "$IMPORT" "$B/CLAUDE.md")"
assert_contains "the user's text is kept" "$(cat "$B/CLAUDE.md")" "keep me"
assert_eq "the line is added at the end" "$IMPORT" "$(tail -1 "$B/CLAUDE.md")"
B="$T/cn"; mk_claude "$B"
P n "$B" init --owner X; assert_eq "answered n, init still succeeds" 0 "$RC"
assert_eq "n leaves CLAUDE.md byte for byte" "$ORIG" "$(cat "$B/CLAUDE.md")"
assert_contains "and says the rules will not load" "$OUT" "will not load"
assert_contains "and that lane doctor --fix can add it" "$OUT" "lane doctor --fix"
P "" "$T/cn" init --owner X
assert_eq "re-init asks again; Enter means yes" 1 "$(grep -cx "$IMPORT" "$T/cn/CLAUDE.md")"
B="$T/cyes"; mk_claude "$B"
L "$B" init --yes; assert_eq "--yes" 0 "$RC"
assert_eq "--yes adds the line" 1 "$(grep -cx "$IMPORT" "$B/CLAUDE.md")"
assert_contains "and keeps the text" "$(cat "$B/CLAUDE.md")" "keep me"
B="$T/ctty"; mk_claude "$B"
L "$B" init --owner X; assert_eq "no terminal and no --yes still succeeds" 0 "$RC"
assert_eq "no terminal: CLAUDE.md untouched" "$ORIG" "$(cat "$B/CLAUDE.md")"
assert_contains "and it says how to add the line" "$OUT" "Add the line above to CLAUDE.md yourself"
assert_contains "or with lane doctor --fix" "$OUT" "lane doctor --fix"
L "$B" doctor; assert_eq "doctor fails while the line is missing" 1 "$RC"
assert_contains "and names it" "$OUT" "CLAUDE.md does not import .repolane/REPOLANE.md"

echo "-- the user's settings.json is merged, not replaced"
C="$T/settings"; mkdir -p "$C/.claude"
cat > "$C/.claude/settings.json" <<'EOF'
{
  "env": {"MINE": "1"},
  "model": "opus",
  "statusLine": {"type": "command", "command": "my-status"},
  "permissions": {"allow": ["Bash(make:*)"], "deny": ["Read(./secret/**)"]},
  "hooks": {
    "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "my-pre-check"}]}],
    "Stop": [{"hooks": [{"type": "command", "command": "echo done"}]}]
  }
}
EOF
L "$C" init --yes; assert_eq "init over the user's settings" 0 "$RC"
S="$C/.claude/settings.json"
for k in '"MINE": "1"' '"model": "opus"' '"command": "my-status"' '"Bash(make:*)"' '"Read(./secret/**)"'; do
  assert_contains "the user's $k is kept" "$(cat "$S")" "$k"
done
assert_contains "the user's PreToolUse hook is kept" "$(hooks_of "$S")" "PreToolUse	my-pre-check"
assert_contains "the user's Stop hook is kept" "$(hooks_of "$S")" "Stop	echo done"
assert_contains "and Repolane's PreToolUse hook is added beside it" "$(hooks_of "$S")" "PreToolUse	lane hook pre-tool-use"
assert_contains "Repolane's read-only commands are allowed" "$(cat "$S")" '"Bash(lane-status:*)"'
s1=$(cksum < "$S"); L "$C" init --yes
assert_eq "init again leaves the merged file alone" "$s1" "$(cksum < "$S")"
assert_eq "no hook is doubled" 10 "$(hooks_of "$S" | wc -l | tr -d ' ')"
Cb="$T/badjson"; mkdir -p "$Cb/.claude"; printf '{"env": {' > "$Cb/.claude/settings.json"
L "$Cb" init --yes; assert_eq "a broken settings.json stops init" 1 "$RC"
assert_contains "and says to mend it" "$OUT" "not valid JSON"
assert_eq "and is not replaced" '{"env": {' "$(cat "$Cb/.claude/settings.json")"

echo "-- --git"
Gd="$T/g"; mkdir -p "$Gd"; printf 'node_modules/\n' > "$Gd/.gitignore"
L "$Gd" init --yes --git; assert_eq "init --git" 0 "$RC"
assert "the workspace is a git repo" test -d "$Gd/.git"
assert_eq "nothing is committed" 1 "$(git -C "$Gd" rev-parse -q --verify HEAD >/dev/null; echo $?)"
assert_contains "the user's .gitignore line is kept" "$(cat "$Gd/.gitignore")" "node_modules/"
for l in /lanes/ /.repolane/repos/ /.repolane/cache/ /.claude/settings.local.json /lane.code-workspace; do assert "ignored: $l" grep -qxF "$l" "$Gd/.gitignore"; done
mkdir -p "$Gd/lanes/x" "$Gd/.repolane/repos/r" "$Gd/.repolane/cache/c"; : > "$Gd/lanes/x/f"; : > "$Gd/.repolane/repos/r/f"; : > "$Gd/.repolane/cache/c/f"
st=$(git -C "$Gd" status --porcelain --untracked-files=all)
assert_not_contains "lanes/ is not offered to git" "$st" "lanes/x"
assert_not_contains "mirrors are not offered to git" "$st" ".repolane/repos"
assert_not_contains "the cache is not offered to git" "$st" ".repolane/cache"
assert_contains "the registry and memory are" "$st" ".repolane/registry/repos.yaml"
assert_contains "and CLAUDE.md" "$st" "CLAUDE.md"
g1=$(cksum < "$Gd/.gitignore"); L "$Gd" init --yes --git
assert_eq "--git again changes nothing" "$g1" "$(cksum < "$Gd/.gitignore")"
assert_contains "and says so" "$OUT" "nothing was changed"

echo "-- planes.json keeps the clone planes beside the workspaces"
mkdir -p "$HOME/.local/share/lane"
python3 - "$PLANES" "$T/someclone" <<'PY'
import json, sys
d = json.load(open(sys.argv[1])); d["planes"]["mine"] = {"path": sys.argv[2], "registered": "x"}; d["active"] = "mine"
json.dump(d, open(sys.argv[1], "w"))
PY
H="$T/h"; mkdir -p "$H"; L "$H" init --yes
assert "the new workspace is registered" ws_registered "$H"
assert_eq "the clone plane and active are kept" "mine $T/someclone" "$(python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));print(d["active"],d["planes"]["mine"]["path"])' "$PLANES")"
PPY="$PROD/scripts/lane-planes.py"
OUT=$(cd "$H" && python3 "$PPY" resolve "$H" 2>&1)
assert_eq "the clone dispatcher's resolver never routes to a workspace" "$T/someclone" "$OUT"
python3 "$PPY" register other "$T/otherclone" >/dev/null 2>&1
assert "registering a clone plane keeps the workspaces" ws_registered "$H"
printf '{broken' > "$PLANES"
L "$T/a" init --yes; assert_eq "an unreadable planes.json does not fail init" 0 "$RC"
assert_eq "and is not replaced" '{broken' "$(cat "$PLANES")"
assert_contains "init says it could not register" "$OUT" "could not register"
python3 - "$PLANES" "$A" "$T/named/ws" "$T/cy" "$T/cn" "$T/cyes" "$T/ctty" "$C" "$Gd" "$H" <<'PY'
import json, sys
json.dump({"planes": {}, "active": None, "workspaces": {p: {"registered": "x"} for p in sys.argv[2:]}}, open(sys.argv[1], "w"))
PY

echo "-- doctor: each problem is found, --fix repairs it, the exit code says which"
L "$A" doctor; assert_eq "clean: exit 0" 0 "$RC"

# the import line
grep -vx "$IMPORT" "$A/CLAUDE.md" > "$T/cm" && cat "$T/cm" > "$A/CLAUDE.md"; NOLINE=$(cat "$A/CLAUDE.md")
L "$A" doctor; assert_eq "no import line: exit 1" 1 "$RC"; assert_contains "named" "$OUT" "does not import .repolane/REPOLANE.md"
assert_contains "with its fix" "$OUT" "fix: add the line $IMPORT to CLAUDE.md, or run: lane doctor --fix"
L "$A" doctor --fix; assert_eq "--fix with no terminal and no --yes: still 1" 1 "$RC"
assert_eq "and CLAUDE.md is untouched" "$NOLINE" "$(cat "$A/CLAUDE.md")"
P n "$A" doctor --fix; assert_eq "--fix answered n: 1" 1 "$RC"
assert_contains "it asked" "$OUT" "Add it? [Y/n]"
assert_eq "and CLAUDE.md is untouched" "$NOLINE" "$(cat "$A/CLAUDE.md")"
P y "$A" doctor --fix; assert_eq "--fix answered y: 0" 0 "$RC"
assert_eq "the line is back, once" 1 "$(grep -cx "$IMPORT" "$A/CLAUDE.md")"
cat "$T/cm" > "$A/CLAUDE.md"
L "$A" doctor --fix --yes; assert_eq "--fix --yes: 0" 0 "$RC"
assert_eq "--yes puts the line back" 1 "$(grep -cx "$IMPORT" "$A/CLAUDE.md")"

# lane not on PATH, as the hooks call it
OUT=$(cd "$A" && env -u LANE_WORKSPACE -u LANE_PRODUCT PATH="$CLEAN_PATH" "$BIN/lane" doctor </dev/null 2>&1); RC=$?
assert_eq "lane not on PATH: exit 1" 1 "$RC"
assert_contains "loudly: every hook fails" "$OUT" "every hook fails and Claude Code runs tools UNGUARDED"
assert_contains "named as not on PATH" "$OUT" "\`lane\` is not on PATH"
if [ -f "$BIN/python" ]; then assert_contains "the fix names the folder to put on PATH" "$OUT" "export PATH=\"$BIN:\$PATH\""; fi
OUT=$(cd "$A" && env -u LANE_WORKSPACE -u LANE_PRODUCT PATH="$CLEAN_PATH" "$BIN/lane" doctor --fix --yes </dev/null 2>&1); RC=$?
assert_eq "--fix cannot put it on PATH: still 1" 1 "$RC"
# a clone's `lane install` dispatcher first on PATH: hooks would run against the clone
init_plane >/dev/null 2>&1
(cd "$PLANE" && ./lane install "$HOME/.local/bin" </dev/null >/dev/null 2>&1)
OUT=$(cd "$A" && env -u LANE_WORKSPACE -u LANE_PRODUCT PATH="$HOME/.local/bin:$BIN:$CLEAN_PATH" "$BIN/lane" doctor </dev/null 2>&1); RC=$?
assert_eq "a clone's dispatcher in the way: exit 1" 1 "$RC"
assert_contains "it says the hooks would run against the clone" "$OUT" "runs hooks against $PLANE, not this workspace"
mkdir -p "$T/fake"; printf '#!/bin/sh\necho "lane: something else"; exit 3\n' > "$T/fake/lane"; chmod +x "$T/fake/lane"
OUT=$(cd "$A" && env -u LANE_WORKSPACE -u LANE_PRODUCT PATH="$T/fake:$CLEAN_PATH" "$BIN/lane" doctor </dev/null 2>&1); RC=$?
assert_eq "some other lane first on PATH: exit 1" 1 "$RC"
assert_contains "it cannot run the hooks" "$OUT" "cannot run this workspace's hooks"

# wrong hooks
python3 - "$A/.claude/settings.json" <<'PY'
import json, sys
p = sys.argv[1]; d = json.load(open(p))
d["hooks"]["PreToolUse"][0]["hooks"][0]["command"] = "lane hook nonsense"
del d["hooks"]["SessionEnd"]
d["hooks"].setdefault("Stop", []).append({"hooks": [{"type": "command", "command": "/old/clone/scripts/hooks/guard.py"}]})
d["hooks"]["Notification"] = [{"hooks": [{"type": "command", "command": "my-notify"}]}]
d["env"] = {"KEEP": "yes"}
json.dump(d, open(p, "w"), indent=2)
PY
L "$A" doctor; assert_eq "wrong hooks: exit 1" 1 "$RC"
assert_contains "names what is wrong" "$OUT" "missing: SessionEnd"
assert_contains "and what differs" "$OUT" "not as expected: PreToolUse"
assert_contains "and the stale clone hook" "$OUT" "unexpected: Stop"
L "$A" doctor --fix; assert_eq "--fix: 0" 0 "$RC"
assert_eq "the hooks are Repolane's again" "$WANT_HOOKS" "$(python3 -B -c 'import json,sys;sys.path.insert(0,sys.argv[2]);import roots;print(json.dumps(roots.repolane_hooks(json.load(open(sys.argv[1]))),sort_keys=True))' "$A/.claude/settings.json" "$PROD/scripts")"
assert_contains "the user's own hook is kept" "$(hooks_of "$A/.claude/settings.json")" "Notification	my-notify"
assert_contains "and the user's env" "$(cat "$A/.claude/settings.json")" '"KEEP": "yes"'
assert_not_contains "the stale clone hook is gone" "$(cat "$A/.claude/settings.json")" "/old/clone/"

# stale version, and a rule file edited at the same version
printf '0.0.1\n' > "$A/.repolane/version"
L "$A" doctor; assert_eq "stale version: exit 1" 1 "$RC"
assert_contains "names both versions" "$OUT" "recorded version is 0.0.1, installed is $VER"
assert_eq "doctor reports it instead of quietly refreshing" "0.0.1" "$(tr -d '[:space:]' < "$A/.repolane/version")"
L "$A" doctor --fix; assert_eq "--fix: 0" 0 "$RC"
assert_eq "the version is recorded" "$VER" "$(tr -d '[:space:]' < "$A/.repolane/version")"
printf 'my edit\n' >> "$A/.repolane/REPOLANE.md"
L "$A" doctor; assert_eq "an edited REPOLANE.md: exit 1" 1 "$RC"; assert_contains "named" "$OUT" "edited by hand"
L "$A" doctor --fix; assert_eq "--fix: 0" 0 "$RC"
assert "REPOLANE.md is the template again" cmp -s "$PROD/templates/REPOLANE.md" "$A/.repolane/REPOLANE.md"

# unregistered
python3 - "$PLANES" "$A" <<'PY'
import json, sys
d = json.load(open(sys.argv[1])); del d["workspaces"][sys.argv[2]]; json.dump(d, open(sys.argv[1], "w"))
PY
L "$A" doctor; assert_eq "unregistered: exit 1" 1 "$RC"; assert_contains "named" "$OUT" "not registered in"
L "$A" doctor --fix; assert_eq "--fix: 0" 0 "$RC"
assert "registered again" ws_registered "$A"
assert "the other workspaces are kept" ws_registered "$H"

echo "-- Claude Code's memory linked into .repolane/memory: shown, asked, made only on yes"
M="$T/m1"; mkdir -p "$M"
P y "$M" init --owner X; assert_eq "init with a terminal, answered y" 0 "$RC"
assert_contains "the link is shown" "$OUT" "$(slug "$M")/memory -> .repolane/memory"
assert_contains "and asked about" "$OUT" "Make these links under ~/.claude? [Y/n]"
assert_eq "y makes the link" "$M/.repolane/memory" "$(readlink "$CH/projects/$(slug "$M")/memory")"
M="$T/m2"; mkdir -p "$M"
P n "$M" init --owner X; assert_eq "answered n, init still succeeds" 0 "$RC"
assert "n makes no link" test ! -e "$CH/projects/$(slug "$M")/memory"
assert_contains "and says doctor --fix can link it later" "$OUT" "lane doctor --fix can link it later"
assert_eq "the no is recorded in .repolane/declined.json" '["memory"]' "$(python3 -c 'import json,sys;print(json.dumps(json.load(open(sys.argv[1]))["memory_links"]))' "$M/.repolane/declined.json")"
L "$M" doctor; assert_eq "doctor: a declined link is a note, not a failure (0)" 0 "$RC"
assert_contains "the note says it was declined" "$OUT" "you said no to linking it"
assert_contains "and how to make it later" "$OUT" "To link it later: lane doctor --fix, or: mkdir -p"
assert_not_contains "and nothing is reported as a problem" "$OUT" "!!"
P y "$M" init; assert_eq "init again with a terminal: 0" 0 "$RC"
assert_not_contains "init does not ask again" "$OUT" "Make these links"
assert_contains "it says the declined link is not offered again" "$OUT" "you said no to are not offered again"
L "$M" doctor --fix; assert_eq "--fix with no terminal: still 0 (declined)" 0 "$RC"
assert "and still no link" test ! -e "$CH/projects/$(slug "$M")/memory"
assert_contains "--fix still offers it: it prints the commands to do it by hand" "$OUT" "ln -sfn $M/.repolane/memory"
P n "$M" doctor --fix; assert_eq "--fix answered n: 0 (declined again)" 0 "$RC"
assert_contains "--fix asked" "$OUT" "Make these links under ~/.claude? [Y/n]"
assert "and still no link" test ! -e "$CH/projects/$(slug "$M")/memory"
P y "$M" doctor --fix; assert_eq "--fix answered y: 0" 0 "$RC"
assert_eq "the link is made" "$M/.repolane/memory" "$(readlink "$CH/projects/$(slug "$M")/memory")"
assert_eq "and the no is cleared" '[]' "$(python3 -c 'import json,sys;print(json.dumps(json.load(open(sys.argv[1]))["memory_links"]))' "$M/.repolane/declined.json")"
rm "$CH/projects/$(slug "$M")/memory"
L "$M" doctor; assert_eq "a missing link nobody declined is a failure again: 1" 1 "$RC"
L "$M" doctor --fix --yes; assert_eq "--fix --yes links it: 0" 0 "$RC"
M="$T/m3"; mkdir -p "$M" "$CH/projects/$(slug "$M")/memory"
printf 'an old note\n' > "$CH/projects/$(slug "$M")/memory/old-note.md"
printf '# theirs\n' > "$CH/projects/$(slug "$M")/memory/MEMORY.md"
L "$M" init --yes; assert_eq "--yes over a memory folder of Claude Code's own" 0 "$RC"
assert_contains "it says the notes are copied in first" "$OUT" "copied in first, nothing is lost"
assert_eq "the note is moved into .repolane/memory" "an old note" "$(cat "$M/.repolane/memory/old-note.md")"
assert_contains "the workspace's own index is not overwritten" "$(cat "$M/.repolane/memory/MEMORY.md")" "Memory Index"
assert "the folder is a link now" test -L "$CH/projects/$(slug "$M")/memory"
ln -sfn "$T/elsewhere" "$CH/projects/$(slug "$M")/memory"
L "$M" doctor; assert_eq "a link pointing elsewhere: 1" 1 "$RC"
assert_contains "named, with where it points" "$OUT" "links to $T/elsewhere"
L "$M" doctor --fix --yes; assert_eq "--fix --yes: 0" 0 "$RC"
assert_eq "repointed" "$M/.repolane/memory" "$(readlink "$CH/projects/$(slug "$M")/memory")"
M="$T/m4"; mkdir -p "$M"
L "$M" init --yes --claude-home "$T/ch2"; assert_eq "--claude-home" 0 "$RC"
assert "the link goes under the folder named" test -L "$T/ch2/projects/$(slug "$M")/memory"
assert "and not under ~/.claude" test ! -e "$CH/projects/$(slug "$M")"
OUT=$(cd "$M" && env -u LANE_WORKSPACE -u LANE_PRODUCT CLAUDE_HOME="$T/ch2" lane doctor </dev/null 2>&1); assert_eq "doctor with CLAUDE_HOME naming it: 0" 0 "$?"

echo "-- the status line"
SL="$M/.claude/settings.json"
sl_cmd(){ python3 -c 'import json,sys;print((json.load(open(sys.argv[1])).get("statusLine") or {}).get("command",""))' "$1"; }
assert_eq "init wires lane statusline" "lane statusline" "$(sl_cmd "$SL")"
OUT=$(printf '{"cwd":"%s","model":{"display_name":"Opus"},"context_window":{"used_percentage":12}}' "$M" \
      | (cd "$M" && env -u LANE_WORKSPACE -u LANE_PRODUCT CLAUDE_PROJECT_DIR="$M" sh -c "$(sl_cmd "$SL")" 2>&1))
assert_contains "it runs, through sh, from PATH" "$OUT" "active lanes"
assert_contains "and reads the status JSON" "$OUT" "ctx 12%"
python3 - "$SL" <<'PY'
import json, sys
d = json.load(open(sys.argv[1])); d["statusLine"]["command"] = '"$CLAUDE_PROJECT_DIR"/scripts/statusline.sh'; json.dump(d, open(sys.argv[1], "w"))
PY
export CLAUDE_HOME="$T/ch2"
L "$M" doctor; assert_eq "a clone's statusline.sh path: 1" 1 "$RC"
assert_contains "named" "$OUT" "runs a clone's scripts/statusline.sh"
L "$M" doctor --fix; assert_eq "--fix: 0" 0 "$RC"
assert_eq "it runs lane statusline again" "lane statusline" "$(sl_cmd "$SL")"
python3 - "$SL" <<'PY'
import json, sys
d = json.load(open(sys.argv[1])); del d["statusLine"]; json.dump(d, open(sys.argv[1], "w"))
PY
L "$M" doctor; assert_eq "no status line: a note, not a problem" 0 "$RC"
assert_contains "the note says --fix adds it" "$OUT" "no status line set (optional)"
L "$M" doctor --fix; assert_eq "--fix: 0" 0 "$RC"
assert_eq "--fix adds it" "lane statusline" "$(sl_cmd "$SL")"
python3 - "$SL" <<'PY'
import json, sys
d = json.load(open(sys.argv[1])); d["statusLine"] = {"type": "command", "command": "my-status"}; json.dump(d, open(sys.argv[1], "w"))
PY
L "$M" doctor --fix; assert_eq "the user's own status line: 0" 0 "$RC"
assert_contains "named as theirs" "$OUT" "your own command (left alone)"
assert_eq "and never replaced" "my-status" "$(sl_cmd "$SL")"
unset CLAUDE_HOME

echo "-- a realistic flow: init, add, start, the hooks with real JSON, a Goal from inside the lane"
R="$T/real"; mkdir -p "$R"; printf '# Team notes\n' > "$R/CLAUDE.md"
P y "$R" init --owner "Rae" --git; assert_eq "init (answered y)" 0 "$RC"
make_remote_repo web
L "$R" add "$T/remotes/web.git" web --yes; assert_eq "lane add a local bare repo (--yes: link its memory)" 0 "$RC"
assert "the mirror is under .repolane/repos" test -d "$R/.repolane/repos/web/.git"
L "$R" start L1 web; assert_eq "lane start L1 web" 0 "$RC"
assert "the worktree is under lanes/" test -e "$R/lanes/L1/web/.git"
L "$R" doctor; assert_eq "doctor passes with a lane" 0 "$RC"
assert_contains "and checked the lane's settings" "$OUT" "every lane's settings.local.json runs the current hooks (2 file(s))"
ML="$CH/projects/$(slug "$R/.repolane/repos/web")/memory"
assert_eq "lane add linked the mirror's memory" "$R/.repolane/memory/web" "$(readlink "$ML")"
assert_contains "doctor checks the root and the mirror" "$OUT" "memory is linked into .repolane/memory (2 folder(s)"
rm "$ML"
L "$R" doctor; assert_eq "the mirror's link missing: 1" 1 "$RC"; assert_contains "named" "$OUT" "(the web mirror) not linked"
L "$R" doctor --fix --yes; assert_eq "--fix --yes: 0" 0 "$RC"
assert_eq "linked again" "$R/.repolane/memory/web" "$(readlink "$ML")"
echo "-- lane add in a workspace asks before linking a mirror's memory"
make_local_repo nolink; L "$R" add "$T/local/nolink"; assert_eq "lane add with no terminal: 0" 0 "$RC"
NL="$CH/projects/$(slug "$R/.repolane/repos/nolink")/memory"
assert "no terminal: the mirror's memory is not linked" test ! -e "$NL"
assert_contains "and it prints the command" "$OUT" "ln -sfn $R/.repolane/memory/nolink"
L "$R" doctor; assert_eq "an undeclined missing mirror link fails doctor: 1" 1 "$RC"
assert_contains "named" "$OUT" "(the nolink mirror) not linked"
make_local_repo declined; P n "$R" add "$T/local/declined"; assert_eq "lane add answered n: 0" 0 "$RC"
assert_contains "it asked" "$OUT" "Make these links under ~/.claude? [Y/n]"
assert "n: not linked" test ! -e "$CH/projects/$(slug "$R/.repolane/repos/declined")/memory"
assert_contains "the no is recorded" "$(cat "$R/.repolane/declined.json")" '"memory/declined"'
make_local_repo yes1; P y "$R" add "$T/local/yes1"; assert_eq "lane add answered y: 0" 0 "$RC"
assert_eq "y: linked" "$R/.repolane/memory/yes1" "$(readlink "$CH/projects/$(slug "$R/.repolane/repos/yes1")/memory")"
L "$R" doctor --fix --yes >/dev/null; L "$R" doctor; assert_eq "after --fix --yes every link is made: 0" 0 "$RC"
assert_eq "the declined one too (a yes clears the no)" "$R/.repolane/memory/declined" "$(readlink "$CH/projects/$(slug "$R/.repolane/repos/declined")/memory")"
LS="$R/lanes/L1/.claude/settings.local.json"
hook_cmd(){ python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["hooks"][sys.argv[2]][0]["hooks"][0]["command"])' "$1" "$2"; }
run_hook(){ # run_hook <settings> <event> <project-dir> <json> : the command as written, through sh, the way Claude Code runs it
  local c; c=$(hook_cmd "$1" "$2")
  printf '%s' "$4" | (cd "$3" && env -u LANE_WORKSPACE -u LANE_PRODUCT CLAUDE_PROJECT_DIR="$3" sh -c "$c" 2>/dev/null); }
assert_eq "the lane's PreToolUse hook is a lane hook command" "lane hook pre-tool-use" "$(hook_cmd "$LS" PreToolUse)"
printf 'K=1\n' > "$R/.repolane/repos/web/.env"
out=$(run_hook "$LS" PreToolUse "$R/lanes/L1" '{"hook_event_name":"PreToolUse","tool_name":"Read","session_id":"r1","cwd":"'"$R/lanes/L1"'","tool_input":{"file_path":"'"$R/.repolane/repos/web/.env"'"}}')
assert_contains "PreToolUse: reading the mirror's .env is denied" "$out" '"permissionDecision": "deny"'
out=$(run_hook "$LS" PreToolUse "$R/lanes/L1" '{"hook_event_name":"PreToolUse","tool_name":"Write","session_id":"r1","cwd":"'"$R/lanes/L1"'","tool_input":{"file_path":"'"$R/lanes/L1/web/a.txt"'"}}')
assert_not_contains "PreToolUse: ordinary work is not denied" "$out" '"deny"'
out=$(run_hook "$LS" SessionStart "$R/lanes/L1" '{"hook_event_name":"SessionStart","source":"startup","session_id":"r1","cwd":"'"$R/lanes/L1"'"}')
assert_contains "SessionStart in the lane hands over LANE.md" "$out" "You are inside a lane"
assert_contains "and names the owner" "$out" "Owner: Rae"
out=$(run_hook "$R/.claude/settings.json" PostToolUse "$R" '{"hook_event_name":"PostToolUse","tool_name":"EnterWorktree","session_id":"r2","cwd":"'"$R"'","tool_input":{"name":"L1"},"tool_response":{}}')
assert_contains "PostToolUse after EnterWorktree hands over LANE.md" "$out" "in lane 'L1'"
OUT=$(cd "$R/lanes/L1/web" && env -u LANE_WORKSPACE -u LANE_PRODUCT lane-memory goal "ship the login page" 2>&1); assert_eq "lane-memory goal from inside the lane" 0 "$?"
assert_contains "the Goal is saved under .repolane/registry/lanes/" "$(sed -n '/^## Goal/,/^## /p' "$R/.repolane/registry/lanes/L1.md")" "ship the login page"
assert "and nothing at the top called registry" test ! -e "$R/registry"
st=$(git -C "$R" status --porcelain --untracked-files=all)
assert_not_contains "the worktree is not offered to the workspace's git" "$st" "?? lanes/"
assert_not_contains "nor the editor workspace file (machine paths)" "$st" "lane.code-workspace"
assert_not_contains "nor the mirror" "$st" ".repolane/repos/"

# a lane's settings gone stale
python3 - "$LS" <<'PY'
import json, sys
d = json.load(open(sys.argv[1])); d["hooks"]["PreToolUse"][0]["matcher"] = "Bash"; json.dump(d, open(sys.argv[1], "w"))
PY
perm=$(python3 -c 'import json,sys;print(json.dumps(json.load(open(sys.argv[1]))["permissions"],sort_keys=True))' "$LS")
L "$R" doctor; assert_eq "a stale lane settings file: exit 1" 1 "$RC"
assert_contains "named" "$OUT" "lanes/L1/.claude/settings.local.json does not run the current lane hook commands"
L "$R" doctor --fix; assert_eq "--fix: 0" 0 "$RC"
assert_eq "its hooks are current" "$WANT_HOOKS" "$(hooks_json "$LS")"
assert_eq "and its permissions untouched" "$perm" "$(python3 -c 'import json,sys;print(json.dumps(json.load(open(sys.argv[1]))["permissions"],sort_keys=True))' "$LS")"
rm "$R/lanes/L1/web/.claude/settings.local.json"
L "$R" doctor; assert_eq "a missing worktree settings file: exit 1" 1 "$RC"
assert_contains "with lane resume as the fix" "$OUT" "run: lane resume L1"

echo "-- a clone keeps its own init and doctor"
OUT=$(cd "$PLANE" && ./lane init --owner Test --yes --claude-home "$T/claude" </dev/null 2>&1); RC=$?
assert_eq "clone init still succeeds" 0 "$RC"
assert "and keeps the clone layout" test -f "$PLANE/registry/config.yml"
assert "with no .repolane/" test ! -e "$PLANE/.repolane"
lane doctor; assert_eq "clone doctor" 0 "$RC"
assert_not_contains "clone doctor runs no workspace checks" "$OUT" "Workspace "

finish
