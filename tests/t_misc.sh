#!/usr/bin/env bash
# Item 23 leftovers and item 26: portability (mapfile, md5), project-folder slugs, exit codes of
# `lane import --list` / `lane sync`, unregistering a plane, `lane rules pull` overwriting a
# hand-written scripts/local file, and the SessionEnd log line.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

echo "-- portability: nothing bash 3.2 or Linux lacks (item 23)"
hits=$(cd "$PRODUCT" && grep -rnE '(^|[^A-Za-z_-])(mapfile|readarray)([^A-Za-z_-]|$)' lane scripts bin --include='*' -I 2>/dev/null \
       | grep -v '^scripts/hooks/test-guard.sh' | grep -v '^scripts/hooks/guard.py' | grep -vE ':[0-9]+:[[:space:]]*#' | grep -v '^scripts/board/')
assert_eq "no mapfile/readarray in product scripts" "" "$hits"
hits=$(cd "$PRODUCT" && grep -rnE '\|[[:space:]]*md5([[:space:]]|$)|\$\(md5 |[^a-z_]md5 +-' lane scripts bin -I 2>/dev/null | grep -v '^scripts/hooks/' | grep -vE ':[0-9]+:[[:space:]]*#')
assert_eq "no bare md5 in product scripts" "" "$hits"

new_sandbox; init_plane >/dev/null 2>&1
make_remote_repo api; add_repo api

echo "-- lane add, interactive candidate prompt (mapfile on bash 3.2)"
make_local_repo withtoken; printf 'x = 1\n' > "$T/local/withtoken/token_store.py"; git -C "$T/local/withtoken" add -A; git -C "$T/local/withtoken" commit -q -m tok
OUT=$(cd "$PLANE" && pty_run 60 y ./lane add "$T/local/withtoken" withtoken); RC=$?
assert_eq "lane add with a tty and 'y' exits 0" 0 "$RC"
assert_not_contains "no 'mapfile: command not found'" "$OUT" "mapfile"
assert_contains "the candidate was listed" "$OUT" "token_store.py"
assert "answering y denied the file (rule written)" grep -q 'token_store.py' "$PLANE/registry/rules.yaml"
make_local_repo notoken2; printf 'x = 1\n' > "$T/local/notoken2/password.py"; git -C "$T/local/notoken2" add -A; git -C "$T/local/notoken2" commit -q -m p
OUT=$(cd "$PLANE" && pty_run 60 n ./lane add "$T/local/notoken2" notoken2); RC=$?
assert_eq "lane add with a tty and 'n' exits 0" 0 "$RC"
assert "answering n wrote no rule for it" bash -c '! grep -q password.py "$1" 2>/dev/null' _ "$PLANE/registry/rules.yaml"

echo "-- lane ref: two attachments with the same name (md5 is absent on Linux)"
lane start R1 api
mkdir -p "$T/x/docs" "$T/y/docs"; echo a > "$T/x/docs/a.txt"; echo b > "$T/y/docs/b.txt"
mkdir -p "$T/shim"; printf '#!/bin/sh\nexit 127\n' > "$T/shim/md5"; chmod +x "$T/shim/md5"
OUT=$(cd "$PLANE" && PATH="$T/shim:$PATH" ./scripts/lane-ref R1 add "$T/x/docs" 2>&1); RC=$?; assert_eq "first ref added" 0 "$RC"
OUT=$(cd "$PLANE" && PATH="$T/shim:$PATH" ./scripts/lane-ref R1 add "$T/y/docs" 2>&1); RC=$?
assert_eq "second ref with the same basename added without md5" 0 "$RC"
refs=$(ls "$PLANE/lanes/R1/refs")
assert_contains "the first keeps the plain name" "$refs" "docs"
n=$(printf '%s\n' "$refs" | grep -cE '^docs-[0-9a-f]{6}$' || true)
assert_eq "the second is disambiguated with a 6-hex suffix" 1 "$n"
OUT=$(cd "$PLANE" && ./scripts/lane-ref R1 list 2>&1); assert_contains "list shows both" "$OUT" "$T/y/docs"
OUT=$(cd "$PLANE" && ./scripts/lane-ref R1 add "$T/y/docs" 2>&1); RC=$?
assert_eq "re-adding the same path is idempotent" 0 "$RC"
assert_eq "and does not create a third link" 2 "$(ls "$PLANE/lanes/R1/refs" | wc -l | tr -d ' ')"

echo "-- Claude project-folder slug (item 23)"
slug(){ (cd "$PLANE" && bash -c 'source scripts/lib.sh; source scripts/gitstate.sh; claude_project_dir "$1"' _ "$1"); }
assert_eq "slash and underscore" "-Users-me-my-proj" "$(slug /Users/me/my_proj)"
assert_eq "dot becomes dash" "-Users-me-my-proj-v2" "$(slug /Users/me/my.proj.v2)"
assert_eq "space becomes dash" "-Users-me-my-proj" "$(slug '/Users/me/my proj')"
assert_eq "existing dashes and digits kept" "-a-b-c1" "$(slug /a-b/c1)"

echo "-- session-start finds the repo's project folder when the path has a dot"
new_sandbox_dot(){ PLANE_DIR_NAME="my.plane" new_sandbox; }
new_sandbox_dot; init_plane >/dev/null 2>&1
make_remote_repo api; add_repo api; lane start CHG-1 api
slug=$(printf '%s' "$PLANE" | sed 's#[^A-Za-z0-9-]#-#g')
mkdir -p "$HOME/.claude/projects/$slug-repos-api"
printf '{"type":"user","message":{"content":"hi"}}\n' > "$HOME/.claude/projects/$slug-repos-api/s9.jsonl"
[ -f "$PLANE/registry/old-checkouts.json" ] || echo '{}' > "$PLANE/registry/old-checkouts.json"
OUT=$(cd "$PLANE" && printf '{"source":"resume","session_id":"s9","cwd":"%s"}' "$PLANE" | LANE_PLAIN=1 ./scripts/session-start 2>&1)
assert_contains "resume still maps the conversation to its repo" "$OUT" "it belongs to repo 'api'"

echo "-- lane import --list / lane sync exit codes (item 23)"
new_sandbox; init_plane >/dev/null 2>&1
make_remote_repo api; add_repo api
OUT=$(cd "$PLANE" && ./lane import --list --claude-home "$T/empty-claude" 2>&1); RC=$?
assert_eq "import --list with no ~/.claude/projects exits 1" 1 "$RC"
assert_contains "and says so" "$OUT" "No Claude conversations"
mkdir -p "$T/claude2/projects/-some-where"
OUT=$(cd "$PLANE" && ./lane import --list --claude-home "$T/claude2" 2>&1); RC=$?
assert_eq "import --list with an empty projects dir exits 1" 1 "$RC"
printf '{"type":"user","cwd":"/some/where/api","message":{"content":"fix the login bug"}}\n' > "$T/claude2/projects/-some-where/c1.jsonl"
OUT=$(cd "$PLANE" && ./lane import --list --claude-home "$T/claude2" 2>&1); RC=$?
assert_eq "import --list that found one exits 0" 0 "$RC"
assert_contains "and lists it" "$OUT" "fix the login bug"

# gh stand-in: never touches the network. GH_AUTH=1 -> authenticated; `gh api` prints two branches.
mkdir -p "$T/ghbin"
cat > "$T/ghbin/gh" <<'GH'
#!/bin/sh
case "$1" in
  auth) [ "${GH_AUTH:-0}" = 1 ] && exit 0; echo "not logged in" >&2; exit 1 ;;
  api)  printf 'main\nrelease\n'; exit 0 ;;
esac
exit 1
GH
chmod +x "$T/ghbin/gh"
sync_run(){ OUT=$(cd "$PLANE" && PATH="$T/ghbin:$PATH" GH_AUTH="$1" ./lane sync $2 2>&1 </dev/null); RC=$?; }
sync_run 0; assert_eq "sync with gh not authenticated exits nonzero" 1 "$RC"
assert_contains "and says why" "$OUT" "not authenticated"
sync_run 1; assert_eq "sync where every repo is local/non-GitHub exits nonzero (nothing was checked)" 1 "$RC"
assert_contains "and says nothing was checked" "$OUT" "nothing was checked"
python3 - "$PLANE/registry/repos.yaml" <<'PY'
import re,sys
p=sys.argv[1]; t=open(p).read()
t=re.sub(r"(  api:\n(?:    .*\n)*?    origin: ).*", r"\1https://github.com/acme/api.git", t, count=1)
open(p,"w").write(t)
PY
sync_run 1; assert_eq "sync that checked a GitHub repo exits 0" 0 "$RC"
assert_contains "and reports it" "$OUT" "acme/api"
assert "and recorded protected_branches" grep -q 'protected_branches' "$PLANE/registry/repos.yaml"
sync_run 1 nosuchrepo; assert_eq "sync of an unknown repo fails" 1 "$RC"

echo "-- unregistering a plane (item 23)"
PY="$HOME/.local/share/lane/planes.py"
(cd "$PLANE" && ./lane install </dev/null) >/dev/null 2>&1
P2="$T/plane2"; git clone -q "$ORIGIN" "$P2"
(cd "$P2" && ./lane install --as second </dev/null) >/dev/null 2>&1
LB="$HOME/.local/bin/lane"
OUT=$(cd "$T" && $LB use 2>&1); assert_contains "both planes are listed" "$OUT" "second"
OUT=$(cd "$T" && $LB use --remove second 2>&1); RC=$?
assert_eq "$LB use --remove exits 0" 0 "$RC"
assert_contains "it confirms" "$OUT" "second"
OUT=$(cd "$T" && $LB use 2>&1); assert_not_contains "the plane is gone from the registry" "$OUT" "second"
assert "its folder was NOT touched" test -d "$P2/.git"
OUT=$(cd "$T" && $LB use --remove second 2>&1); RC=$?; assert_eq "removing an unknown plane fails" 1 "$RC"
assert_contains "with a clear message" "$OUT" "no such plane"
act=$(cd "$T" && python3 "$PY" list "$T" | grep -c active || true)
assert_eq "the other plane is still registered and active" 1 "$act"
base=$(basename "$PLANE")
OUT=$(cd "$T" && $LB use --remove "$base" 2>&1); RC=$?
assert_eq "removing the active plane works" 0 "$RC"
assert_contains "and says nothing is active now" "$OUT" "no active plane"
OUT=$(cd "$T" && $LB use --remove 2>&1); RC=$?; assert_eq "--remove without a name is a usage error" 2 "$RC"

echo "-- lane rules pull does not overwrite a hand-written scripts/local file (item 22)"
new_sandbox; init_plane >/dev/null 2>&1
SH="$T/shared-rules"; mkdir -p "$SH/scripts.d"; git init -q -b main "$SH"
printf 'rules:\n  - id: demo\n    when: { tool: Bash, command: "zzz-never" }\n    deny: "no"\n    ref: "test"\n    example: "zzz-never"\n' > "$SH/rules.yaml"
printf '#!/bin/sh\necho SHARED\n' > "$SH/scripts.d/hello"; printf '#!/bin/sh\necho SHARED2\n' > "$SH/scripts.d/other"
git -C "$SH" add -A; git -C "$SH" commit -q -m shared
mkdir -p "$PLANE/scripts/local"; printf '#!/bin/sh\necho MINE\n' > "$PLANE/scripts/local/hello"; chmod +x "$PLANE/scripts/local/hello"
lane rules pull "$SH"
assert_eq "pull succeeds" 0 "$RC"
assert_contains "my file is untouched" "$(cat "$PLANE/scripts/local/hello")" "MINE"
assert_contains "the pull says it kept mine" "$OUT" "hello"
assert_contains "and why" "$OUT" "kept"
assert_contains "a new shared script is still copied" "$(cat "$PLANE/scripts/local/other" 2>/dev/null)" "SHARED2"
echo "-- ...and a script that an earlier pull put there is still updated by a later pull"
printf '#!/bin/sh\necho SHARED2-v2\n' > "$SH/scripts.d/other"; git -C "$SH" commit -q -am v2
lane rules pull --latest
assert_contains "previously pulled script is refreshed" "$(cat "$PLANE/scripts/local/other")" "SHARED2-v2"
assert_contains "mine is still mine" "$(cat "$PLANE/scripts/local/hello")" "MINE"

echo "-- SessionEnd does not pile up duplicate log lines (item 26)"
new_sandbox; init_plane >/dev/null 2>&1
make_remote_repo api; add_repo api; lane start E1 api
W="$PLANE/lanes/E1/api"; printf 'wip\n' > "$W/new.txt"
end_session(){ printf '{"hook_event_name":"SessionEnd","session_id":"%s","cwd":"%s"}' "$1" "$W" | python3 "$PLANE/scripts/hooks/guard.py" >/dev/null 2>&1; }
cnt(){ grep -c "session ended" "$PLANE/registry/lanes/E1.md" || true; }
end_session a; assert_eq "the first session end is logged" 1 "$(cnt)"
assert "and flags the unparked work" grep -q "UNPARKED" "$PLANE/registry/lanes/E1.md"
end_session b; end_session c; end_session d
assert_eq "three more identical, read-only session ends add nothing" 1 "$(cnt)"
printf 'more\n' > "$W/new2.txt"; end_session e
assert_eq "a session that changed the state is logged again" 2 "$(cnt)"
end_session f
assert_eq "and its repeat is not" 2 "$(cnt)"
git -C "$W" add -A; git -C "$W" commit -q -m c; end_session g
assert_eq "committing changes the state: logged" 3 "$(cnt)"
assert_eq "updated: is still maintained" "$(date +%F)" "$(sed -n 's/^updated: //p' "$PLANE/registry/lanes/E1.md" | head -1)"

finish
