#!/usr/bin/env bash
# Dispatcher behaviour: items 18 (installed stubs), 22 (bare lane before init), 24 (EnterWorktree
# text), and `lane <cmd> --help` printing developer comments.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
new_sandbox

echo "-- before init"
lane;        assert_eq "bare lane before init exits 2" 2 "$RC"
assert_contains "bare lane before init says not set up" "$OUT" "not set up yet"
assert_not_contains "bare lane before init prints no raw git/sed errors" "$OUT" "fatal:"
assert_not_contains "no sed error either" "$OUT" "sed:"
lane status; assert_eq "lane status before init exits 2" 2 "$RC"
assert_contains "lane status before init says not set up" "$OUT" "not set up yet"
lane help;   assert_eq "lane help works before init" 0 "$RC"
lane --version; assert_eq "lane --version works before init" 0 "$RC"

init_plane >/dev/null 2>&1
echo "-- after init"
lane;        assert_eq "bare lane after init exits 0" 0 "$RC"

echo "-- installed long-form stubs (item 18)"
(cd "$PLANE" && ./lane install </dev/null) >"$T/install.out" 2>&1
assert "install wrote the stubs" test -x "$HOME/.local/bin/lane-env-keys"
assert_contains "install output says Claude can make mistakes" "$(cat "$T/install.out")" "Claude can make mistakes"
assert_contains "install output says the guard is not a sandbox and the licence is as-is" "$(cat "$T/install.out")" "not a sandbox"
export PATH="$HOME/.local/bin:$PATH"
printf 'FOO=bar\nexport BAZ=1\n' > "$T/e.env"
OUT=$(cd "$PLANE" && lane-env-keys "$T/e.env" 2>&1); RC=$?
assert_eq "installed lane-env-keys exits 0" 0 "$RC"
assert_contains "lane-env-keys lists names" "$OUT" "FOO"
assert_not_contains "lane-env-keys never prints values" "$OUT" "bar"
OUT=$(cd "$PLANE" && lane-env-check 2>&1); RC=$?
assert_eq "installed lane-env-check exits 0" 0 "$RC"
assert_not_contains "lane-env-check is not 'no command named'" "$OUT" "no command named"
# every stub must name a command the dispatcher knows
for stub in "$HOME"/.local/bin/lane-* "$HOME"/.local/bin/guard-check; do
  [ -f "$stub" ] || continue
  short=$(sed -n 's/^exec .*command -v lane)" \([a-z-]*\) .*/\1/p' "$stub")
  OUT=$(cd "$PLANE" && "$stub" --help 2>&1); RC=$?
  if [ "$RC" = 0 ] && [ -n "$short" ]; then ok "stub $(basename "$stub") -> lane $short resolves"
  else bad "stub $(basename "$stub") -> lane '$short' resolves" "rc=$RC $OUT"; fi
done

# first body-comment line (after the leading comment block) of a script that shows up in $2
body_comment_leak(){
  local l
  while IFS= read -r l; do
    case "$2" in *"$l"*) printf '%s\n' "$l"; return 0 ;; esac
  done < <(awk 'NR==1{next} hdr==0 && /^#/{next} {hdr=1} hdr==1 && /^[[:space:]]*#[[:space:]]+[A-Za-z]/ {sub(/^[[:space:]]*#[[:space:]]*/,""); if (length($0)>25) print}' "$1")
}
echo "-- lane <cmd> --help prints usage, not developer comments (item 23)"
for c in add start resume park done status brief with run gh ref note merge plan find sessions workspace env keys secrets sync rules upgrade import nested; do
  lane "$c" --help
  script=$(sed -n "s/^  $c) *echo \"\\\$S\\/\\([^|]*\\)|.*/\\1/p" "$PLANE/lane" | head -1)
  [ -n "$script" ] || continue
  f="$PLANE/scripts/$script"
  # comment lines that appear AFTER the header block (i.e. in the body) must never be in --help
  leak=$(body_comment_leak "$f" "$OUT")
  if [ "$RC" = 0 ] && [ -z "$leak" ]; then ok "lane $c --help shows only the header"
  else bad "lane $c --help shows only the header" "rc=$RC leaked: $leak"; fi
done
lane add --help;     assert_not_contains "add --help has no maintainer cross-reference" "$OUT" "Not to be confused"
lane upgrade --help; assert_not_contains "upgrade --help has no design-consult note" "$OUT" "design consult"
lane rules --help;   assert_not_contains "rules --help has no 'load-bearing' maintainer note" "$OUT" "load-bearing"
lane add --help;     assert_contains "add --help still shows the usage line" "$OUT" "lane-add <git-url"

echo "-- dispatcher text never advertises EnterWorktree path= (item 24)"
make_remote_repo api; add_repo api
lane start CHG-9 api; assert_eq "lane start for the text checks" 0 "$RC"
sess_in='{"source":"startup","session_id":"s1","cwd":"'"$PLANE"'"}'
OUT=$(cd "$PLANE" && printf '%s' "$sess_in" | LANE_PLAIN=1 ./scripts/session-start 2>&1)
assert_not_contains "session-start (root) has no path=" "$OUT" "path="
assert_contains "session-start (root) tells Claude name=\"<lane-id>\"" "$OUT" 'EnterWorktree name="<lane-id>"'
mkdir -p "$HOME/.claude/projects"
slug=$(printf '%s' "$PLANE" | sed 's#[^A-Za-z0-9-]#-#g')
mkdir -p "$HOME/.claude/projects/$slug-repos-api"
printf '{"type":"user","message":{"content":"hi"}}\n' > "$HOME/.claude/projects/$slug-repos-api/s2.jsonl"
[ -f "$PLANE/registry/old-checkouts.json" ] || echo '{}' > "$PLANE/registry/old-checkouts.json"
res_in='{"source":"resume","session_id":"s2","cwd":"'"$PLANE"'"}'
OUT=$(cd "$PLANE" && printf '%s' "$res_in" | LANE_PLAIN=1 ./scripts/session-start 2>&1)
assert_contains "resume branch offers the existing lane" "$OUT" "continue in existing lane 'CHG-9'"
assert_not_contains "resume branch has no path=" "$OUT" "path="
assert_contains "resume branch uses EnterWorktree name=\"CHG-9\"" "$OUT" 'EnterWorktree name="CHG-9"'
assert_not_contains "no repo-qualified name (guard refuses it)" "$OUT" 'name="CHG-9/'
assert_not_contains "no <id>/<repo> name advertised" "$OUT" 'name=<id>/'
for f in CLAUDE.md.template "$PLANE/CLAUDE.md"; do
  [ -f "$f" ] || f="$PRODUCT/$f"
  [ -f "$f" ] || { bad "$f exists"; continue; }
  hit=$(grep -nE 'EnterWorktree[^A-Za-z]{0,4}path|EnterWorktree[^.]{0,40}<repo>|EnterWorktree[^A-Za-z]{0,4}name[=:] *"?<id>/' "$f")
  assert_eq "$(basename "$f") does not advertise a path or repo to EnterWorktree" "" "$hit"
done
# init must fill the owner into CLAUDE.md: the template's placeholder is {{owner}}
if [ -f "$PLANE/CLAUDE.md" ]; then
  assert_not_contains "init-generated CLAUDE.md has no {{owner}} placeholder left" "$(cat "$PLANE/CLAUDE.md")" "{{owner}}"
else
  bad "init-generated CLAUDE.md exists"
fi
# the real product files too, not only the sandbox copies
for f in "$PRODUCT/CLAUDE.md.template" "$PRODUCT/scripts/session-start"; do
  hit=$(grep -nE 'EnterWorktree[^A-Za-z]{0,4}path|EnterWorktree name="?<id>/' "$f")
  assert_eq "$(basename "$f") (product tree) has no EnterWorktree path/<id>/<repo>" "" "$hit"
done

echo "-- item 31: absolute script paths after EnterWorktree"
OUT=$(cd "$PLANE" && printf '%s' "$sess_in" | LANE_PLAIN=1 ./scripts/session-start 2>&1)
assert_contains "dispatcher prints the real absolute scripts dir" "$OUT" "Scripts dir (absolute): $PLANE/scripts"
assert_contains "dispatcher says relative scripts/ exits 127 from the lane" "$OUT" "exits 127"
assert_not_contains "no placeholder path" "$OUT" "<control-plane>"
lane_in='{"source":"startup","session_id":"s3","cwd":"'"$PLANE/lanes/CHG-9/api"'"}'
OUT=$(cd "$PLANE/lanes/CHG-9" && printf '%s' "$lane_in" | LANE_PLAIN=1 "$PLANE/scripts/session-start" 2>&1)
assert_contains "lane session: absolute lane-park path" "$OUT" "$PLANE/scripts/lane-park CHG-9"
assert_contains "lane session: absolute lane-brief example" "$OUT" "$PLANE/scripts/lane-brief CHG-9"
assert_contains "lane session says relative exits 127" "$OUT" "exits 127"
assert_contains "CLAUDE.md.template says absolute path" "$(cat "$PRODUCT/CLAUDE.md.template")" "ABSOLUTE path"
assert_contains "CLAUDE.md.template mentions 127" "$(cat "$PRODUCT/CLAUDE.md.template")" "exits 127"

finish
