#!/usr/bin/env bash
# `lane migrate`: a REAL 0.9.2 install (that release's own files, its own `lane init` and `lane install`, a repo, two lanes,
# a commit in a worktree, a Goal, a memory, a finding, the owner's own CLAUDE.md line and settings key, files of their own)
# converted by the installed product (a built wheel when a builder is here, see install_product). The preview, a "no", no
# terminal and a live Claude Code session change nothing; --yes migrates; then everything the workspace needs is checked
# with real hook JSON and real git; a second run is a no-op; --undo brings the 0.9.2 install back and its own doctor
# passes; a migration stopped half way continues when run again. Throwaway HOME, temp dirs only.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
TAG=v0.9.2
if ! git -C "$PRODUCT" rev-parse -q --verify "$TAG^{commit}" >/dev/null 2>&1; then
  if [ -n "${CI:-}" ]; then bad "the $TAG tag is here (checkout with fetch-depth: 0)"; else echo "  skip  no $TAG tag in this checkout"; fi
  finish; exit
fi
new_sandbox
install_product
CLEAN_PATH=$(printf '%s' "$PATH" | tr ':' '\n' | while IFS= read -r d; do [ -n "$d" ] && [ ! -e "$d/lane" ] && printf '%s:' "$d"; done)
CLEAN_PATH="${CLEAN_PATH%:}"
export PATH="$BIN:$CLEAN_PATH"
CH="$HOME/.claude"; PLANES="$HOME/.local/share/lane/planes.json"
slug(){ printf '%s' "$1" | LC_ALL=C sed 's#[^A-Za-z0-9-]#-#g'; }

echo "-- the manifest of shipped files: the committed release history, and this release's list written at build time"
python3 "$PRODUCT/scripts/release-migrate-manifest" --check
assert_eq "scripts/migrate-manifest.json matches the v0.9.x tags (if not: python3 scripts/release-migrate-manifest, then commit)" 0 "$?"
# the paths this checkout ships, the way copy_product_tree takes them (tests/lib.sh), plus the manifest itself
want=$( { (cd "$PRODUCT" && git ls-files --cached --others --exclude-standard) \
          | grep -vxF -f <( (cd "$PRODUCT" && git ls-files --others --exclude-standard -- CLAUDE.md knowledge memory; echo scripts/migrate-head.json) ) \
          | while IFS= read -r f; do [ -e "$PRODUCT/$f" ] || [ -L "$PRODUCT/$f" ] && printf '%s\n' "$f"; done
        echo scripts/migrate-manifest.json; } | LC_ALL=C sort -u)
if [ -f "$PROD/scripts/migrate-head.json" ]; then
  got=$(python3 -c 'import json,sys;print("\n".join(json.load(open(sys.argv[1]))["paths"]))' "$PROD/scripts/migrate-head.json" | LC_ALL=C sort -u)
  assert_eq "the installed package's scripts/migrate-head.json lists exactly this tree's files" "$want" "$got"
else
  got=$(python3 -B -c 'import sys; sys.path.insert(0, sys.argv[1] + "/scripts"); import shipped; print("\n".join(shipped.head_paths(sys.argv[1])))' "$PROD" | LC_ALL=C sort -u)
  assert_eq "the product's shipped paths (taken from its tree) are exactly this tree's files" "$want" "$got"
fi

echo "-- a real $TAG install, made by that release's own commands"
OLD="$T/old"
git clone -q --bare "$PRODUCT" "$T/product.git" 2>/dev/null
git clone -q "$T/product.git" "$OLD" && git -C "$OLD" checkout -q -B main "$TAG"
git -C "$OLD" branch -q -u origin/main main 2>/dev/null || true
OV=$(git -C "$OLD" rev-parse HEAD)
# O <args…> : the 0.9.2 install's own lane, as its owner runs it (no installed product in the way)
O(){ OUT=$(cd "$OLD" && env -u LANE_PRODUCT -u LANE_WORKSPACE PATH="$CLEAN_PATH" ./lane "$@" </dev/null 2>&1); RC=$?; }
O init --owner Test --yes --claude-home "$CH"; assert_eq "$TAG lane init" 0 "$RC"
O install "$HOME/.local/bin"; assert_eq "$TAG lane install (the router in ~/.local/bin)" 0 "$RC"
assert "the router is there" grep -q "stable, multi-plane-aware dispatcher" "$HOME/.local/bin/lane"
make_remote_repo web
O add "$T/remotes/web.git" web; assert_eq "$TAG lane add" 0 "$RC"
printf 'SECRET=1\n' > "$OLD/repos/web/.env"
O start L1 web; assert_eq "$TAG lane start L1" 0 "$RC"
O start L2 web; assert_eq "$TAG lane start L2" 0 "$RC"
commit_in "$OLD/lanes/L1/web" feature.txt "work before the migration"
OUT=$(cd "$OLD/lanes/L1" && env -u LANE_PRODUCT -u LANE_WORKSPACE PATH="$CLEAN_PATH" "$OLD/scripts/lane-memory" goal "ship the login page" 2>&1)
assert_eq "$TAG: a Goal saved from inside the lane" 0 "$?"
OUT=$(cd "$OLD" && env -u LANE_PRODUCT -u LANE_WORKSPACE PATH="$CLEAN_PATH" ./scripts/lane-memory draft web-builds "web builds with make" 2>&1 \
      && env -u LANE_PRODUCT -u LANE_WORKSPACE PATH="$CLEAN_PATH" ./scripts/lane-memory file web-builds repo web 2>&1)
assert_eq "$TAG: a memory filed for web" 0 "$?"
OUT=$(cd "$OLD" && env -u LANE_PRODUCT -u LANE_WORKSPACE PATH="$CLEAN_PATH" ./scripts/lane-memory draft l1-finding "the login form posts twice" 2>&1 \
      && env -u LANE_PRODUCT -u LANE_WORKSPACE PATH="$CLEAN_PATH" ./scripts/lane-memory file l1-finding lane L1 2>&1)
assert_eq "$TAG: a finding filed for L1" 0 "$?"
printf '\n## My own notes\nAlways run make lint before a commit.\n' >> "$OLD/CLAUDE.md"
python3 - "$OLD/.claude/settings.json" <<'PY'
import json, sys
p = sys.argv[1]; d = json.load(open(p)); d["env"] = {"MY_KEY": "kept"}
d["hooks"].setdefault("Stop", []).append({"hooks": [{"type": "command", "command": "my-stop-hook"}]})
json.dump(d, open(p, "w"), indent=2)
PY
printf 'my notes\n' > "$OLD/notes.txt"; printf '#!/bin/sh\necho mine\n' > "$OLD/scripts/my-tool"; chmod +x "$OLD/scripts/my-tool"
mkdir -p "$OLD/scripts/local"; printf '#!/usr/bin/env bash\n# lane: say hello\necho "hello from local"\n' > "$OLD/scripts/local/hello"; chmod +x "$OLD/scripts/local/hello"
O doctor; assert_eq "$TAG lane doctor passes before" 0 "$RC"
LANEF_SUM=$(cksum < "$OLD/registry/lanes/L1.md")
MEM_SUM=$(cd "$OLD/memory" && find . -type f ! -path ./README.md | LC_ALL=C sort | xargs cksum)   # README.md is Repolane's placeholder
assert_contains "the Goal is in the lane file" "$(cat "$OLD/registry/lanes/L1.md")" "ship the login page"
assert_contains "the finding is in the lane file" "$(cat "$OLD/registry/lanes/L1.md")" "the login form posts twice"
assert "the memory is in memory/web" test -f "$OLD/memory/web/web-builds.md"
assert_eq "the root's memory is linked by $TAG" "$OLD/memory" "$(readlink "$CH/projects/$(slug "$OLD")/memory")"
assert_eq "the mirror's memory is linked by $TAG" "$OLD/memory/web" "$(readlink "$HOME/.claude/projects/$(slug "$OLD/repos/web")/memory")"
assert_contains "the clone is registered as a plane" "$(cat "$PLANES")" "$OLD"

# everything a migration could touch, inside and outside the folder
snap(){ (cd "$OLD" && find . -path ./.git -prune -o \( -type f -o -type l \) -print | LC_ALL=C sort | while IFS= read -r f; do
          if [ -L "$f" ]; then printf '%s -> %s\n' "$f" "$(readlink "$f")"; else printf '%s %s\n' "$f" "$(cksum < "$f")"; fi; done
        git -C "$OLD" rev-parse HEAD; git -C "$OLD" status --porcelain | LC_ALL=C sort
        find "$HOME/.claude" "$HOME/.local" \( -type f -o -type l \) -print | LC_ALL=C sort | while IFS= read -r f; do
          if [ -L "$f" ]; then printf '%s -> %s\n' "$f" "$(readlink "$f")"; else printf '%s %s\n' "$f" "$(cksum < "$f")"; fi; done; ) 2>/dev/null; }
BEFORE=$(snap)

# M <args…> : the installed product's lane migrate, no terminal; PM <a1,a2,…> <args…> : with a terminal, answering the
# prompts in turn (the last answer repeats)
M(){ OUT=$(cd "$OLD" && env -u LANE_WORKSPACE -u LANE_PRODUCT lane migrate "$@" </dev/null 2>&1); RC=$?; }
PM(){ local a="$1"; shift
  OUT=$(cd "$OLD" && env -u LANE_WORKSPACE -u LANE_PRODUCT TERM=dumb python3 - "$a" "$@" <<'PY'
import os, pty, select, sys, time
answers, cmd = [a.encode() + b"\n" for a in sys.argv[1].split(",")], ["lane", "migrate"] + sys.argv[2:]
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
        while seen < n: os.write(fd, answers[min(seen, len(answers) - 1)]); seen += 1
    if time.time() - t0 > 180:
        os.kill(pid, 9); out += b"\n[timed out]\n"; break
_, st = os.waitpid(pid, 0)
sys.stdout.write(out.decode(errors="replace").replace("\r", ""))
sys.exit(os.WEXITSTATUS(st) if os.WIFEXITED(st) else 1)
PY
); RC=$?; }

echo "-- the preview changes nothing"
M --dry-run; assert_eq "--dry-run exits 0" 0 "$RC"
for c in "registry/  ->  .repolane/registry" "repos/  ->  .repolane/repos" ".cache/  ->  .repolane/cache" "scripts/local/  ->  .repolane/scripts/local" \
         "git worktree repair: lanes/L1/web" "link lanes/L1/web/.env  ->  .repolane/repos/web/.env" "rewrite lanes/L1/.claude/settings.local.json" \
         "scripts/  (" "bin/  (the whole folder" "the folder stays for yours: my-tool" ".git is the Repolane repo's" \
         "the lines you added to it are kept" "lane hook" "$(slug "$OLD")/memory -> .repolane/memory" \
         "remove ~/.local/bin/lane" "the clone entry" "Backup first" "Dry run: nothing was changed"; do
  assert_contains "the preview shows: $c" "$OUT" "$c"
done
assert_not_contains "it never lists the owner's own file for removal" "$OUT" "notes.txt"
assert_eq "nothing changed after --dry-run (folder, .git, ~/.claude, ~/.local)" "$BEFORE" "$(snap)"
M; assert_eq "no terminal, no --yes: exit 0" 0 "$RC"
assert_contains "it says nothing was changed and how to go on" "$OUT" "Nothing was changed: there is no terminal to ask, and --yes was not given."
assert_eq "nothing changed without a terminal" "$BEFORE" "$(snap)"
PM n; assert_eq "answered n: exit 0" 0 "$RC"
assert_contains "it asked" "$OUT" "Migrate now? [y/N]"
assert_eq "nothing changed after n" "$BEFORE" "$(snap)"
assert "and no backup was written" test ! -d "$HOME/.local/share/lane/backups"

echo "-- a live Claude Code session in the folder stops it"
# a stand-in for Claude Code: a process called claude whose current folder is a lane (an interpreter running a file named
# claude, the way `node …/bin/claude` does)
mkdir -p "$T/fakebin"; printf '#!/bin/sh\nsleep 60\n' > "$T/fakebin/claude"; chmod +x "$T/fakebin/claude"
(cd "$OLD/lanes/L1" && exec /bin/sh "$T/fakebin/claude") & FAKE=$!
sleep 1
M --yes; assert_eq "refused: exit 1" 1 "$RC"
assert_contains "it names the session" "$OUT" "Claude Code is running inside"
assert_contains "and its folder" "$OUT" "$OLD/lanes/L1"
pkill -P "$FAKE" 2>/dev/null; kill "$FAKE" 2>/dev/null; wait "$FAKE" 2>/dev/null
assert_eq "nothing changed" "$BEFORE" "$(snap)"

echo "-- --yes migrates"
M --yes; assert_eq "lane migrate --yes" 0 "$RC"
BK=$(printf '%s\n' "$OUT" | sed -n 's/^  made  backup //p' | sed "s#^~#$HOME#")
assert "the backup path is printed and the file is there" test -f "$BK"
assert_contains "the backup is outside the folder" "$BK" "$HOME/.local/share/lane/backups/old-"
assert_contains "and the undo command is printed" "$OUT" "lane migrate --undo"
for d in registry memory knowledge repos cache; do assert ".repolane/$d/ is there" test -d "$OLD/.repolane/$d"; done
for f in config.yml env.sh REPOLANE.md LANE.md version; do assert ".repolane/$f is there" test -f "$OLD/.repolane/$f"; done
for d in registry memory knowledge repos .cache; do assert "the old $d/ is gone" test ! -e "$OLD/$d"; done
assert_eq "the lane file is byte for byte the same (Goal, finding, log)" "$LANEF_SUM" "$(cksum < "$OLD/.repolane/registry/lanes/L1.md")"
assert_contains "the Goal is intact" "$(cat "$OLD/.repolane/registry/lanes/L1.md")" "ship the login page"
assert_contains "the finding is intact" "$(cat "$OLD/.repolane/registry/lanes/L1.md")" "the login form posts twice"
assert_eq "every memory file is intact" "$MEM_SUM" "$(cd "$OLD/.repolane/memory" && find . -type f | LC_ALL=C sort | xargs cksum)"
assert "Repolane's unchanged placeholder memory/README.md is dropped" test ! -e "$OLD/.repolane/memory/README.md"
assert_contains "the owner is kept" "$(cat "$OLD/.repolane/config.yml")" "name: Test"
assert_contains "env.sh is the workspace's (it was unchanged)" "$(cat "$OLD/.repolane/env.sh")" ".repolane/cache/nx"
# CLAUDE.md
assert_contains "CLAUDE.md imports REPOLANE.md" "$(cat "$OLD/CLAUDE.md")" "@.repolane/REPOLANE.md"
assert_contains "the owner's own line is kept" "$(cat "$OLD/CLAUDE.md")" "Always run make lint before a commit."
assert_contains "with its heading" "$(cat "$OLD/CLAUDE.md")" "## My own notes"
assert_not_contains "Repolane's old text is gone from it" "$(cat "$OLD/CLAUDE.md")" "Rules for every session"
assert "no CLAUDE.md.pre-0.10 when only lines were added" test ! -e "$OLD/CLAUDE.md.pre-0.10"
# settings
S="$OLD/.claude/settings.json"
hooks_of(){ python3 -c 'import json,sys
for ev,es in json.load(open(sys.argv[1])).get("hooks",{}).items():
    for e in es:
        for h in e["hooks"]: print(ev+"\t"+h["command"])' "$1"; }
assert_contains "the owner's settings key is kept" "$(cat "$S")" '"MY_KEY": "kept"'
assert_contains "the owner's own hook is kept" "$(hooks_of "$S")" "Stop	my-stop-hook"
assert_eq "every other hook is a lane hook command" "" "$(hooks_of "$S" | grep -v 'my-stop-hook' | grep -v '	lane hook ')"
assert_not_contains "no hook names a path in the old clone" "$(cat "$S")" "CLAUDE_PROJECT_DIR"
assert_contains "the status line is lane statusline" "$(cat "$S")" '"command": "lane statusline"'
assert_not_contains "the old bin/ permission entries are gone" "$(cat "$S")" "*/bin/lane-status"
for L in "$OLD/lanes/L1/.claude/settings.local.json" "$OLD/lanes/L1/web/.claude/settings.local.json"; do
  assert_eq "${L#$OLD/}: hooks are lane hook commands" "" "$(hooks_of "$L" | grep -v '	lane hook ')"
  assert_not_contains "${L#$OLD/}: no path into the old layout" "$(cat "$L")" "$OLD/repos/"
  assert_not_contains "${L#$OLD/}: no old scripts path" "$(cat "$L")" "$OLD/scripts/"
done
assert_contains "the worktree's memory is the new folder" "$(cat "$OLD/lanes/L1/web/.claude/settings.local.json")" "\"autoMemoryDirectory\": \"$OLD/.repolane/memory/web\""
assert_contains "the lane's pointer file names the new paths" "$(cat "$OLD/lanes/L1/CLAUDE.md")" "$OLD/.repolane/registry/lanes/L1.md"
# product files gone, the owner's kept
for f in lane VERSION CLAUDE.md.template README.md CHANGELOG.md LICENSE .gitignore scripts/lib.sh scripts/hooks/guard.py bin docs tests .github \
         .claude/README.md; do assert "Repolane's $f is gone" test ! -e "$OLD/$f"; done
# the clone's slash commands and agents (which run bin/ by path) are replaced by the workspace's, by name
assert_not_contains "the clone's slash commands are gone" "$(cat "$OLD"/.claude/commands/*.md 2>/dev/null)" "/bin/lane-"
assert_eq "the workspace's are in their place" "$(cat "$PROD/templates/claude/commands/status.md")" "$(cat "$OLD/.claude/commands/status.md" 2>/dev/null)"
assert_eq "and its agents" "$(cat "$PROD/templates/claude/agents/lane-manager.md")" "$(cat "$OLD/.claude/agents/lane-manager.md" 2>/dev/null)"
assert ".git (the Repolane repo's) is gone" test ! -e "$OLD/.git"
assert_eq "the owner's notes.txt is kept" "my notes" "$(cat "$OLD/notes.txt")"
assert "the owner's scripts/my-tool is kept" test -x "$OLD/scripts/my-tool"
assert "scripts/local moved under .repolane/" test -x "$OLD/.repolane/scripts/local/hello"
assert "the root settings.local.json is kept" test -f "$OLD/.claude/settings.local.json"
# outside the folder
assert_eq "the root's memory link points at .repolane/memory" "$OLD/.repolane/memory" "$(readlink "$CH/projects/$(slug "$OLD")/memory")"
NEWP="$CH/projects/$(slug "$OLD/.repolane/repos/web")"
assert "the mirror's project folder follows the mirror" test -d "$NEWP"
assert "and the old one is gone" test ! -e "$CH/projects/$(slug "$OLD/repos/web")"
assert_eq "the mirror's memory link points at .repolane/memory/web" "$OLD/.repolane/memory/web" "$(readlink "$NEWP/memory")"
assert "the old router is removed" test ! -e "$HOME/.local/bin/lane"
assert "its lane-* stubs are removed" test ! -e "$HOME/.local/bin/lane-start"
assert "and its planes.py" test ! -e "$HOME/.local/share/lane/planes.py"
assert_not_contains "the clone entry is dropped from planes.json" "$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["planes"])' "$PLANES")" "$OLD"
assert_contains "the workspace is registered" "$(python3 -c 'import json,sys;print(list(json.load(open(sys.argv[1]))["workspaces"]))' "$PLANES")" "$OLD"

echo "-- the workspace works: git in the worktree, the hooks with real JSON, doctor, lane commands"
WT="$OLD/lanes/L1/web"
assert_eq "git status works in the worktree" 0 "$(git -C "$WT" status --porcelain >/dev/null 2>&1; echo $?)"
assert_eq "it is still on the lane's branch" "L1" "$(git -C "$WT" branch --show-current)"
assert_eq "the commit made before is there" "work before the migration" "$(git -C "$WT" show HEAD:feature.txt)"
commit_in "$WT" after.txt "work after the migration"
assert_eq "a commit in the worktree after the migration" "work after the migration" "$(git -C "$WT" show HEAD:after.txt)"
assert_contains "the mirror knows the worktree at its place" "$(git -C "$OLD/.repolane/repos/web" worktree list)" "$WT"
assert_eq "the worktree's .env link resolves through the moved mirror" "SECRET=1" "$(cat "$WT/.env")"
L(){ OUT=$(cd "$1" && shift && env -u LANE_WORKSPACE -u LANE_PRODUCT lane "$@" </dev/null 2>&1); RC=$?; }
L "$OLD" doctor; assert_eq "lane doctor exits 0" 0 "$RC"
assert_not_contains "and reports nothing wrong" "$OUT" "!!"
OUT=$(cd "$OLD/lanes/L1" && env -u LANE_WORKSPACE -u LANE_PRODUCT lane-memory goal "ship the login page, then the signup page" 2>&1)
assert_eq "lane-memory goal from inside the lane" 0 "$?"
assert_contains "the Goal is saved in .repolane/registry" "$(sed -n '/^## Goal/,/^## /p' "$OLD/.repolane/registry/lanes/L1.md")" "then the signup page"
L "$OLD" hello; assert_eq "the owner's scripts/local command still runs" "hello from local" "$OUT"
L "$OLD" status; assert_eq "lane status" 0 "$RC"; assert_contains "lists the lane" "$OUT" "L1"
assert_not_contains "and no clone reminder in a workspace" "$OUT" "git-clone install"
hook_cmd(){ python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["hooks"][sys.argv[2]][0]["hooks"][0]["command"])' "$1" "$2"; }
run_hook(){ local c; c=$(hook_cmd "$1" "$2")
  printf '%s' "$4" | (cd "$3" && env -u LANE_WORKSPACE -u LANE_PRODUCT CLAUDE_PROJECT_DIR="$3" sh -c "$c" 2>/dev/null); }
LS="$OLD/lanes/L1/.claude/settings.local.json"
verdict(){ # verdict <where: lane|root> <tool> <tool_input>
  local s cwd; if [ "$1" = lane ]; then s="$LS"; cwd="$OLD/lanes/L1"; else s="$S"; cwd="$OLD"; fi
  run_hook "$s" PreToolUse "$cwd" "$(printf '{"hook_event_name":"PreToolUse","tool_name":"%s","session_id":"m","cwd":"%s","tool_input":%s}' "$2" "$cwd" "$3")" \
    | python3 -c 'import json,sys
try: d=json.load(sys.stdin)["hookSpecificOutput"]["permissionDecision"]
except Exception: d="pass"
print("deny" if d=="deny" else "pass")'; }
D="$OLD/.repolane"
g(){ assert_eq "guard: $2" "$1" "$(verdict "$3" "$4" "$5")"; }
g deny "reading the mirror's .env"            lane Read  '{"file_path":"'"$D"'/repos/web/.env"}'
g deny "a shell printing .env in the lane"    lane Bash  '{"command":"cat web/.env"}'
g deny "writing a memory directly"            lane Write '{"file_path":"'"$D"'/memory/new.md"}'
g deny "editing another lane's file"          lane Edit  '{"file_path":"'"$D"'/registry/lanes/L2.md","old_string":"a","new_string":"b"}'
g pass "editing this lane's own file"         lane Edit  '{"file_path":"'"$D"'/registry/lanes/L1.md","old_string":"a","new_string":"b"}'
g deny "writing into another lane's worktree" lane Write '{"file_path":"'"$OLD"'/lanes/L2/web/x.txt"}'
g deny "a push to a default branch"           lane Bash  '{"command":"git -C web push origin main"}'
g deny "rewriting the git remote"             lane Bash  '{"command":"git -C web remote set-url origin x"}'
g deny "writing into the mirror"              lane Write '{"file_path":"'"$D"'/repos/web/README.md"}'
g pass "ordinary work in the lane"            lane Write '{"file_path":"'"$OLD"'/lanes/L1/web/a.txt"}'
g pass "git in a repo of the lane"            lane Bash  '{"command":"git -C web status"}'
g deny "the dispatcher reaching into a lane"  root Read  '{"file_path":"'"$OLD"'/lanes/L1/web/README.md"}'
out=$(run_hook "$LS" SessionStart "$OLD/lanes/L1" '{"hook_event_name":"SessionStart","source":"startup","session_id":"m1","cwd":"'"$OLD/lanes/L1"'"}')
assert_contains "SessionStart in the lane hands over LANE.md" "$out" "You are inside a lane"
assert_contains "and names the owner" "$out" "Owner: Test"
out=$(run_hook "$S" PostToolUse "$OLD" '{"hook_event_name":"PostToolUse","tool_name":"EnterWorktree","session_id":"m2","cwd":"'"$OLD"'","tool_input":{"name":"L1"},"tool_response":{}}')
assert_contains "PostToolUse after EnterWorktree hands over LANE.md" "$out" "in lane 'L1'"
out=$(run_hook "$S" SessionStart "$OLD" '{"hook_event_name":"SessionStart","source":"startup","session_id":"m3","cwd":"'"$OLD"'"}')
assert_contains "SessionStart at the root shows the lanes" "$out" "L1"

echo "-- a second run is a no-op"
AFTER=$(cd "$OLD" && find . \( -type f -o -type l \) -print | LC_ALL=C sort | xargs cksum 2>/dev/null)
M --yes; assert_eq "lane migrate again: exit 0" 0 "$RC"
assert_contains "it says so" "$OUT" "is already a workspace (migrated from 0.9.2"
assert_contains "and that nothing was changed" "$OUT" "nothing was changed"
assert_eq "nothing in the folder changed" "$AFTER" "$(cd "$OLD" && find . \( -type f -o -type l \) -print | LC_ALL=C sort | xargs cksum 2>/dev/null)"

echo "-- --undo brings the $TAG install back"
M --undo "$BK"; assert_eq "--undo with no terminal and no --yes: exit 0" 0 "$RC"
assert_contains "and changes nothing" "$OUT" "Nothing was changed"
assert "the workspace is still there" test -d "$OLD/.repolane"
M --undo "$BK" --yes; assert_eq "lane migrate --undo --yes" 0 "$RC"
for f in lane VERSION CLAUDE.md.template scripts/lib.sh scripts/hooks/guard.py bin/lane-start docs .github .claude/agents; do assert "$f is back" test -e "$OLD/$f"; done
for d in registry memory knowledge repos .cache; do assert "$d/ is back" test -d "$OLD/$d"; done
assert "no .repolane/ is left" test ! -e "$OLD/.repolane"
assert_eq ".git is back, at the release" "$OV" "$(git -C "$OLD" rev-parse HEAD)"
assert_eq "git status is as it was" "$(printf '%s\n' "$BEFORE" | grep -E '^( M|\?\?|M ) ' || true)" "$(git -C "$OLD" status --porcelain | LC_ALL=C sort)"
assert_contains "the old CLAUDE.md is back" "$(cat "$OLD/CLAUDE.md")" "Rules for every session"
assert_contains "with the owner's line" "$(cat "$OLD/CLAUDE.md")" "Always run make lint before a commit."
assert_contains "the old settings are back" "$(cat "$OLD/.claude/settings.json")" "scripts/hooks/guard.py"
assert_contains "with the owner's key" "$(cat "$OLD/.claude/settings.json")" '"MY_KEY": "kept"'
assert_contains "the Goal written in the workspace is kept" "$(cat "$OLD/registry/lanes/L1.md")" "then the signup page"
assert_eq "git works in the worktree again" "work after the migration" "$(git -C "$WT" show HEAD:after.txt)"
assert_contains "and it is the old mirror's worktree again" "$(cat "$WT/.git")" "$OLD/repos/web/.git/worktrees"
assert_eq "the .env link points at the old mirror" "$OLD/repos/web/.env" "$(readlink "$WT/.env")"
assert_contains "the lane's settings name the clone's guard again" "$(cat "$OLD/lanes/L1/.claude/settings.local.json")" "$OLD/scripts/hooks/guard.py"
assert_eq "the root's memory link is back" "$OLD/memory" "$(readlink "$CH/projects/$(slug "$OLD")/memory")"
assert_eq "the mirror's project folder is back" "$OLD/memory/web" "$(readlink "$CH/projects/$(slug "$OLD/repos/web")/memory")"
assert "the router is back" grep -q "stable, multi-plane-aware dispatcher" "$HOME/.local/bin/lane"
assert "with its stubs" test -x "$HOME/.local/bin/lane-start"
assert_contains "the clone entry is back in planes.json" "$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["planes"])' "$PLANES")" "$OLD"
assert_not_contains "and the workspace is not registered" "$(python3 -c 'import json,sys;print(list(json.load(open(sys.argv[1])).get("workspaces",{})))' "$PLANES")" "$OLD"
O doctor; assert_eq "$TAG's own lane doctor passes on the restored install" 0 "$RC"
O status; assert_eq "$TAG lane status works" 0 "$RC"

echo "-- the router stays while another clone install uses it"
cp "$PLANES" "$T/planes.saved"
python3 - "$PLANES" "$T/another-clone" <<'PY'
import json, sys
d = json.load(open(sys.argv[1])); d["planes"]["another"] = {"path": sys.argv[2], "registered": "x"}; json.dump(d, open(sys.argv[1], "w"))
PY
M --dry-run; assert_contains "the preview keeps it, and says why" "$OUT" "other clone installs still use it (another)"
assert_not_contains "and does not offer to remove it" "$OUT" "remove ~/.local/bin/lane"
cp "$T/planes.saved" "$PLANES"

echo "-- a migration stopped half way continues when run again (--git, CLAUDE.md with Repolane's text edited)"
sed -i.bak 's/^## Rules for every session$/## Rules for every session (mine)/' "$OLD/CLAUDE.md" && rm -f "$OLD/CLAUDE.md.bak"
export LANE_MIGRATE_STOP_AFTER=product
PM y,n,n --git; unset LANE_MIGRATE_STOP_AFTER
assert_eq "stopped half way: exit 1" 1 "$RC"
assert_contains "it asked about ~/.claude separately" "$OUT" "Make the changes under ~/.claude listed above? [Y/n]"
assert_contains "and about the router" "$OUT" "Remove the old router ~/.local/bin/lane? [Y/n]"
assert_contains "it says how to continue" "$OUT" "run lane migrate"
assert_contains "or undo" "$OUT" "lane migrate --undo"
assert "the state file is there" test -f "$OLD/.repolane/migrating.json"
assert "Repolane's files are already gone" test ! -e "$OLD/lane"
M; assert_eq "run again (no terminal): the plan, exit 0" 0 "$RC"
assert_contains "it knows the migration was interrupted" "$OUT" "A migration of this folder was interrupted"
assert "and changed nothing" test -f "$OLD/.repolane/migrating.json"
M --yes; assert_eq "run again with --yes: it finishes" 0 "$RC"
assert_contains "it continues with the same backup" "$OUT" "Continuing the interrupted migration"
assert "the state file is gone" test ! -e "$OLD/.repolane/migrating.json"
assert "--git from the first run: a fresh repo" test -d "$OLD/.git"
assert_eq "with nothing committed" 1 "$(git -C "$OLD" rev-parse -q --verify HEAD >/dev/null; echo $?)"
assert_eq "and none of the product's history" "" "$(git -C "$OLD" remote)"
st=$(git -C "$OLD" status --porcelain --untracked-files=all)
assert_not_contains "lanes/ is not offered to the new repo" "$st" "?? lanes/"
assert_contains "CLAUDE.md is" "$st" "CLAUDE.md"
assert "Repolane's text was edited, so the old CLAUDE.md is kept as CLAUDE.md.pre-0.10" test -f "$OLD/CLAUDE.md.pre-0.10"
assert_contains "and the new one still keeps the owner's line" "$(cat "$OLD/CLAUDE.md")" "Always run make lint before a commit."
assert_contains "the output says so" "$OUT" "CLAUDE.md.pre-0.10"
assert_eq "git in the worktree works" "work after the migration" "$(git -C "$WT" show HEAD:after.txt)"
commit_in "$WT" third.txt "third"; assert_eq "and commits" "third" "$(git -C "$WT" show HEAD:third.txt)"
assert_eq "answered n: the root's memory link under ~/.claude is untouched" "$OLD/memory" "$(readlink "$CH/projects/$(slug "$OLD")/memory")"
assert "and the mirror's project folder is not renamed" test -d "$CH/projects/$(slug "$OLD/repos/web")"
assert_contains "the output says nothing under ~/.claude was changed" "$OUT" "nothing under ~/.claude was changed"
assert "answered n: the router is kept" grep -q "stable, multi-plane-aware dispatcher" "$HOME/.local/bin/lane"
assert_contains "and the output says what that means" "$OUT" "the old router was kept"
L "$OLD" doctor; assert_eq "lane doctor: the memory links are a problem" 1 "$RC"
assert_contains "named" "$OUT" "(the workspace root) links to $OLD/memory"
L "$OLD" doctor --fix --yes; assert_eq "lane doctor --fix --yes repairs them" 0 "$RC"
assert_eq "the root's memory link points at .repolane/memory" "$OLD/.repolane/memory" "$(readlink "$CH/projects/$(slug "$OLD")/memory")"
L "$OLD" doctor; assert_eq "lane doctor exits 0" 0 "$RC"

echo "-- what lane migrate refuses, and a clone's reminder"
L "$T" migrate "$T/nowhere-$$"; assert_eq "a missing folder: 2" 2 "$RC"
mkdir -p "$T/plain"; L "$T" migrate "$T/plain"; assert_eq "a folder that is not a clone install: 2" 2 "$RC"
assert_contains "named" "$OUT" "is not a git-clone install of Repolane"
mkdir -p "$T/fresh"; L "$T/fresh" init --yes >/dev/null; L "$T/fresh" migrate; assert_eq "a workspace made by lane init: 0" 0 "$RC"
assert_contains "nothing to migrate" "$OUT" "Nothing to migrate"
init_plane >/dev/null 2>&1
OUT=$(cd "$PLANE" && ./lane migrate </dev/null 2>&1); assert_eq "lane migrate in a clone's own lane: 2" 2 "$?"
assert_contains "it says to run the installed package" "$OUT" "runs from the installed package"
(cd "$PLANE" && ./lane add "$T/remotes/web.git" web </dev/null >/dev/null 2>&1)
OUT=$(cd "$PLANE" && ./lane status </dev/null 2>&1); assert_contains "a clone's lane status mentions lane migrate" "$OUT" "\`lane migrate\` from it turns this folder into a workspace"
OUT=$(cd "$PLANE" && printf '{"source":"startup","session_id":"c1","cwd":"%s"}' "$PLANE" | ./scripts/session-start 2>&1)
assert_contains "so does its SessionStart screen" "$OUT" "lane migrate"
printf 'migrate_reminder: false\n' >> "$PLANE/registry/config.yml"
OUT=$(cd "$PLANE" && ./lane status </dev/null 2>&1); assert_not_contains "migrate_reminder: false silences it" "$OUT" "lane migrate"

finish
