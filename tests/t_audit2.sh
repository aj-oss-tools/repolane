#!/usr/bin/env bash
# Second-audit regressions: R1 (park pathspecs), R3 (upgrade), R5 (done), R6 (BSD sed), R8, S1-S3, M26, M35.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
new_sandbox; init_plane >/dev/null 2>&1
make_remote_repo api; make_remote_repo leaky noignore; add_repo api; add_repo leaky
WT(){ echo "$PLANE/lanes/$1/$2"; }

echo "-- R1: park uses literal pathspecs (glob-named files must not drag a secret in)"
lane start G1 leaky; W="$(WT G1 leaky)"
printf 'TOKEN=a\n' > "$W/.env"; git -C "$W" add -f .env; git -C "$W" commit -q -m "track env"
printf 'TOKEN=changed\n' > "$W/.env"
printf 'glob\n' > "$W/.env*"
lane park G1 "park with a glob named file next to env"
files=$(git -C "$W" show --name-only --format= HEAD)
case "
$files
" in *"
.env
"*) bad "R1 .env must not be committed by a .env* pathspec" ;; *) ok "R1 .env not committed by a .env* pathspec" ;; esac
assert_eq "R1 the tracked .env edit is still a local change" " M .env" "$(git -C "$W" status --porcelain | grep -F ' .env' | grep -v '\*' | head -1)"
lane start G2 leaky; W2="$(WT G2 leaky)"
printf '{"k":1}\n' > "$W2/secrets.json"; git -C "$W2" add -f secrets.json; git -C "$W2" commit -q -m "track s"
printf '{"k":2}\n' > "$W2/secrets.json"; printf 'x\n' > "$W2/s*.json"
lane park G2 "park with s star json glob file"
assert_eq "R1 secrets.json not in the wip commit" "" "$(git -C "$W2" show --name-only --format= HEAD | grep -x 'secrets.json')"
lane start G3 leaky; W3="$(WT G3 leaky)"
printf 'TOKEN=a\n' > "$W3/.env"; git -C "$W3" add -f .env; git -C "$W3" commit -q -m "track env"
printf 'TOKEN=b\n' > "$W3/.env"; printf 'star\n' > "$W3/*"
lane park G3 "park with a file literally named star"
assert_eq "R1 .env not committed via a '*' file" "" "$(git -C "$W3" show --name-only --format= HEAD | grep -x '.env')"

echo "-- R8: lane ids are names, never paths"
printf -- '---\nstatus: active\nrepos:\n---\n## Goal\nLEAKED-GOAL\n## Resume note\nx\n## Log\n' > "$PLANE/registry/outside.md"
mkdir -p "$PLANE/registry/lanes/done"
printf -- '---\nstatus: done\n---\n## Goal\nLEAKED-ARCHIVE\n' > "$PLANE/registry/outside2.md"
for bad in ../outside ../../registry/outside . .. "a/b" "../outside2"; do
  lane brief "$bad"
  assert_eq "brief '$bad' is refused" 1 "$RC"
  assert_not_contains "brief '$bad' reads nothing outside" "$OUT" "LEAKED"
  for verb in done park resume; do
    lane $verb "$bad" "a long enough resume note"
    assert_eq "$verb '$bad' is refused" 1 "$RC"
  done
  lane ref "$bad" list; assert_eq "ref '$bad' is refused" 1 "$RC"
  lane with "$bad" api; assert_eq "with '$bad' is refused" 1 "$RC"
  (cd "$PLANE" && ./scripts/lane-memory file x lane "$bad" </dev/null >/dev/null 2>&1); assert_eq "memory file lane '$bad' is refused" 1 "$?"
done
lane brief "$(printf 'G1\nx')"; assert_eq "an id with a newline is refused" 1 "$RC"
lane brief G1; assert_eq "a real id still works" 0 "$RC"

echo "-- R11: lane-memory names are ASCII in every locale"
for loc in C en_US.UTF-8 de_DE.UTF-8; do
  for nm in "é" "caf$(printf '\303\251')" $'a\nb' "ａ"; do
    (cd "$PLANE" && LC_ALL=$loc ./scripts/lane-memory draft "$nm" </dev/null >/dev/null 2>&1); assert_eq "draft '$nm' refused under $loc" 1 "$?"
  done
done
(cd "$PLANE" && ./scripts/lane-memory draft fine-1.0_x </dev/null >/dev/null 2>&1); assert_eq "an ASCII slug still works" 0 "$?"

echo "-- S3: lane-memory never writes through a symlinked memory directory"
mkdir -p "$T/elsewhere"; rm -rf "$PLANE/memory/api"; ln -s "$T/elsewhere" "$PLANE/memory/api"
(cd "$PLANE" && ./scripts/lane-memory draft sl1 </dev/null >/dev/null 2>&1)
printf -- '---\nname: sl1\ndescription: d\n---\nb\n' > "$PLANE/.cache/memory-inbox/sl1.md"
(cd "$PLANE" && ./scripts/lane-memory file sl1 repo api </dev/null >/dev/null 2>&1); assert_eq "file into a symlinked dir is refused" 1 "$?"
assert_eq "nothing landed outside" "" "$(ls "$T/elsewhere")"
assert "the draft is kept" test -f "$PLANE/.cache/memory-inbox/sl1.md"
printf -- '---\nname: mv1\ndescription: d\n---\nb\n' > "$PLANE/memory/mv1.md"
(cd "$PLANE" && ./scripts/lane-memory move mv1 repo api </dev/null >/dev/null 2>&1); assert_eq "move into it is refused" 1 "$?"
assert_eq "and nothing landed outside" "" "$(ls "$T/elsewhere")"
rm "$PLANE/memory/api"

echo "-- R6: lane-env-keys on BSD and GNU sed"
printf 'A=1\nexport B=2\n  export   C=3\nexportD=4\n# E=5\nexport\tF=6\n' > "$T/envfile"
# sort in the C locale so the expectation does not depend on the platform's collation
keys=$("$PLANE/scripts/lane-env-keys" "$T/envfile" | tail -n +2 | tr -d ' ' | LC_ALL=C sort | tr '\n' ',')
assert_eq "export-prefixed and plain names are all listed" "A,B,C,F,exportD," "$keys"
assert_not_contains "no values leak" "$("$PLANE/scripts/lane-env-keys" "$T/envfile")" "=1"
assert_eq "no BRE GNU-isms (backslash plus, question, pipe) in shell scripts' sed/grep" "" "$(cd "$PRODUCT" && grep -nE '(sed|grep)[^|]*\\[+?|]' scripts/lane-* scripts/status-all scripts/statusline.sh scripts/session-start scripts/sessions scripts/gitstate.sh 2>/dev/null | grep -v "s/|/")"

echo "-- R5: ignored secret-named files inside dependency/build trees do not block lane done"
printf 'node_modules/\nvendor/\n.venv/\nvenv/\ntarget/\ndist/\nbuild/\n__pycache__/\n*.pem\n' >> "$PLANE/repos/api/.git/info/exclude"
lane start D5 api; WD="$(WT D5 api)"
for d in node_modules/pkg/test vendor/x .venv/lib venv/lib target/debug dist build/out src/__pycache__; do
  mkdir -p "$WD/$d"; printf 'k\n' > "$WD/$d/fixture.pem"
done
lane done D5 --keep-sessions; assert_eq "dependency-tree secrets do not block done" 0 "$RC"
lane start D6 api; WD="$(WT D6 api)"
mkdir -p "$WD/node_modules/pkg"; printf 'k\n' > "$WD/node_modules/pkg/fixture.pem"; printf 'SECRET=1\n' > "$WD/.env"
lane done D6 --keep-sessions; assert_eq "a top-level ignored .env still blocks" 1 "$RC"
assert_contains "and names .env" "$OUT" ".env"
assert_not_contains "but not the node_modules file" "$OUT" "fixture.pem"
mkdir -p "$WD/config"; printf 'k\n' > "$WD/config/real.pem"; rm "$WD/.env"
lane done D6 --keep-sessions; assert_eq "an ignored pem in an ordinary dir still blocks" 1 "$RC"
assert_contains "names it" "$OUT" "config/real.pem"
lane done D6 --keep-sessions --discard-ignored >/dev/null

echo "-- S1: fork workflow, pushed only to a non-origin remote"
lane start F1 api; WF="$(WT F1 api)"; commit_in "$WF" f.txt one
git init -q --bare "$T/fork.git"; git -C "$WF" remote add fork "$T/fork.git"; git -C "$WF" push -q fork F1
lane done F1 --keep-sessions
assert_eq "default stays safe: not on origin -> refused" 1 "$RC"
assert_contains "and the message names the way out" "$OUT" "--pushed-to"
lane done F1 --keep-sessions --pushed-to nosuch; assert_eq "an unknown remote is refused" 1 "$RC"
assert "worktree still there" test -d "$WF"
lane done F1 --keep-sessions --pushed-to fork; assert_eq "--pushed-to fork lets a fork-only push finish" 0 "$RC"
lane start F2 api; commit_in "$(WT F2 api)" g.txt one; git -C "$(WT F2 api)" remote add fork "$T/fork.git"
lane done F2 --keep-sessions --pushed-to fork; assert_eq "--pushed-to still refuses what is not on that remote" 1 "$RC"
lane done F2 --keep-sessions --pushed-to; assert_eq "--pushed-to without a value is a usage error" 1 "$RC"

echo "-- S2: detached and unborn HEAD get accurate messages"
WF2="$(WT F2 api)"; git -C "$WF2" checkout -q --detach
lane done F2 --keep-sessions
assert_eq "detached HEAD with unpushed commits is refused" 1 "$RC"
assert_contains "and says it is detached" "$OUT" "detached"
assert_not_contains "without the misleading 'git push origin F2'" "$OUT" "git push origin F2"
git -C "$WF2" checkout -q --orphan unborn1; git -C "$WF2" rm -rfq . 2>/dev/null
lane done F2 --keep-sessions
assert_contains "unborn HEAD says it has no commits" "$OUT" "no commits"
assert_not_contains "and not 'could not tell'" "$OUT" "could not tell"
git -C "$WF2" checkout -q -f F2; lane done F2 --keep-sessions --discard-ignored --pushed-to fork >/dev/null 2>&1; git -C "$WF2" push -q fork F2 2>/dev/null

echo "-- R4: unpushed counts agree everywhere after a plain push (statusline, status, lane-start base)"
lane start U1 api; WU="$(WT U1 api)"; commit_in "$WU" u.txt one
sl(){ printf '{"cwd":"%s","model":{"display_name":"M"}}' "$WU" | bash "$PLANE/scripts/statusline.sh" 2>&1; }
assert_contains "statusline shows 1 to push before the push" "$(sl)" "↑1"
git -C "$WU" push -q origin U1
assert_not_contains "statusline shows nothing to push after a plain push" "$(sl)" "↑"
git -C "$PLANE/repos/api" branch -q U2 origin/main; git -C "$PLANE/repos/api" push -q -u origin U2
lane start U2 api
assert_contains "base recorded for an existing pushed branch is the repo default, not the branch itself" "$(grep -A3 'repo: api' "$PLANE/registry/lanes/U2.md")" "base: main"
git -C "$PLANE" commit -q --allow-empty -m cp1
lane status; assert_eq "control plane counts its unpushed commit" "1" "$(printf '%s\n' "$OUT" | sed -n 's/^  [0-9]* dirty, \([0-9]*\) unpushed,.*/\1/p' | head -1)"
git -C "$PLANE" push -q origin HEAD:refs/heads/cp-side
lane status; assert_eq "and counts 0 once any origin branch has it" "0" "$(printf '%s\n' "$OUT" | sed -n 's/^  [0-9]* dirty, \([0-9]*\) unpushed,.*/\1/p' | head -1)"

echo "-- M26: lane sync with no gh on PATH exits 1 and says so"
mkdir -p "$T/nogh"; for tool in bash git python3 sed awk grep tr cat head sort dirname basename mkdir rm mktemp date wc cut tail ls env readlink uname; do
  p=$(command -v "$tool" 2>/dev/null) && [ -x "$p" ] && ln -sf "$p" "$T/nogh/$tool"; done
OUT=$(cd "$PLANE" && PATH="$T/nogh" /bin/bash ./scripts/lane-sync </dev/null 2>&1); RC=$?
assert_eq "lane sync without gh exits 1" 1 "$RC"
assert_contains "and says gh is not installed" "$OUT" "gh is not installed"

echo "-- M35: the pre-approved allow list holds only read-only verbs"
lane start A1 api; AL="$(WT A1 api)/.claude/settings.local.json"
[ -f "$AL" ] || AL="$PLANE/lanes/A1/.claude/settings.local.json"
python3 - "$AL" <<'PY'
import json, sys
p = sys.argv[1]; d = json.load(open(p)); d["permissions"]["allow"] += ["Bash(lane-memory:*)", "Bash(lane-workspace:*)"]; json.dump(d, open(p, "w"))
PY
lane start A2 api    # any refresh of the guards
allow=$(python3 -c "import json,sys;print('\n'.join(json.load(open(sys.argv[1]))['permissions']['allow']))" "$AL")
assert_contains "read-only lane-memory verbs are approved" "$allow" "Bash(lane-memory list:*)"
assert_not_contains "no blanket lane-memory approval (file/rm/move write)" "$allow" "Bash(lane-memory:*)"
assert_not_contains "no lane-memory file" "$allow" "lane-memory file"
assert_not_contains "no lane-memory rm/move/drop" "$allow" "lane-memory rm"
assert_not_contains "lane-workspace is not approved" "$allow" "lane-workspace"
shipped=$(python3 -c "import json,sys;print('\n'.join(json.load(open(sys.argv[1]))['permissions']['allow']))" "$PLANE/.claude/settings.json")
assert_not_contains "the shipped settings.json has no lane-workspace approval" "$shipped" "lane-workspace"
assert_not_contains "nor a blanket lane-memory one" "$shipped" "Bash(lane-memory:*)"

finish
