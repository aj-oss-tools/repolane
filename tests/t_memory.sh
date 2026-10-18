#!/usr/bin/env bash
# Item 1: lane-memory must never touch a file outside the memory dirs.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
new_sandbox; init_plane >/dev/null 2>&1
make_remote_repo api; add_repo api
M="$PLANE/scripts/lane-memory"
INBOX="$PLANE/.cache/memory-inbox"; mkdir -p "$INBOX"

canary(){ printf 'CANARY-CONTENT\n' > "$1"; }
run(){ OUT=$("$M" "$@" 2>&1 </dev/null); RC=$?; }

# --- drop ----------------------------------------------------------------------------------
echo "-- drop"
for bad in "../../../canary" "../x" "a/b" "$T/canary" "/etc/hosts" ".." "" "a b" 'a;b'; do
  canary "$T/canary.md"; canary "$PLANE/x.md"; canary "$PLANE/.cache/x.md"
  run drop "$bad"
  [ "$bad" = "" ] && continue   # the empty slug is the "usage" case, covered below
  if [ -f "$T/canary.md" ] && [ -f "$PLANE/x.md" ] && [ -f "$PLANE/.cache/x.md" ] && [ "$RC" != 0 ]; then
    ok "drop rejects '$bad' (rc=$RC) and leaves the canaries"
  else bad "drop rejects '$bad' and leaves the canaries" "rc=$RC out=$OUT"; fi
done
run drop; assert_eq "drop with no slug fails" 1 "$RC"
# a valid draft still drops
run draft good-slug_1.2; assert_eq "draft with a valid slug works" 0 "$RC"
run drop good-slug_1.2; assert_eq "drop of a valid slug works" 0 "$RC"
assert "valid drop removed the draft" test ! -e "$INBOX/good-slug_1.2.md"

# --- show / draft ---------------------------------------------------------------------------
echo "-- show / draft"
canary "$T/canary.md"
run show "../../../canary"; assert_eq "show rejects traversal" 1 "$RC"
assert_not_contains "show does not print the canary" "$OUT" "CANARY-CONTENT"
run draft "../../../evil"; assert_eq "draft rejects traversal" 1 "$RC"
assert "draft did not create a file outside" test ! -e "$T/evil.md"

# --- file -----------------------------------------------------------------------------------
echo "-- file"
for bad in "../../../moved" "../../memory/pwn" "a/b" "$T/abs"; do
  # plant a real file at the place the traversal would reach, so a missing guard visibly moves it
  canary "$T/moved.md"; canary "$T/abs.md"; mkdir -p "$PLANE/memory/a"; canary "$INBOX/../../../moved.md" 2>/dev/null
  canary "$PLANE/memory/pwn.md"; mkdir -p "$INBOX/a"; canary "$INBOX/a/b.md"
  run file "$bad" cross
  if [ "$RC" != 0 ] && [ -f "$T/moved.md" ] && [ -f "$INBOX/a/b.md" ] && [ "$(cat "$PLANE/memory/pwn.md")" = CANARY-CONTENT ] \
     && [ ! -e "$PLANE/memory/moved.md" ] && [ ! -e "$PLANE/memory/b.md" ] && [ ! -e "$PLANE/memory/$(basename "$bad").md" -o "$bad" = "../../memory/pwn" ]; then
    ok "file rejects slug '$bad' (rc=$RC) without moving anything"
  else bad "file rejects slug '$bad' without moving anything" "rc=$RC out=$OUT"; fi
  rm -rf "$INBOX/a" "$PLANE/memory/pwn.md"
done
# a draft planted outside the inbox by an earlier traversal must not be moved INTO memory either
canary "$T/stolen.md"
run file "../../../stolen" cross
assert "file never moves a file from outside the inbox" test -f "$T/stolen.md"
# repo and lane-id arguments are names too
printf -- '---\nname: y\ndescription: d\n---\nbody\n' > "$INBOX/ok2.md"
run file ok2 repo "../.."; assert_eq "file rejects a traversing repo name" 1 "$RC"
assert "no memory file written outside memory/ via repo" test ! -e "$PLANE/ok2.md"
# must still work
printf -- '---\nname: ok2\ndescription: a fine memory\n---\nbody\n' > "$INBOX/ok2.md"
run file ok2 repo api; assert_eq "file repo works" 0 "$RC"
assert "memory landed in memory/api/" test -f "$PLANE/memory/api/ok2.md"
assert "index line written" grep -q 'ok2.md' "$PLANE/memory/api/MEMORY.md"
printf -- '---\nname: cr.oss-1\ndescription: cross one\n---\nbody\n' > "$INBOX/cr.oss-1.md"
run file cr.oss-1 cross; assert_eq "file cross with dots/dashes works" 0 "$RC"
assert "cross memory landed" test -f "$PLANE/memory/cr.oss-1.md"

# --- move / rm ------------------------------------------------------------------------------
echo "-- move / rm"
canary "$PLANE/victim.md"
run rm "../victim"; 
if [ -f "$PLANE/victim.md" ] && [ "$RC" != 0 ]; then ok "rm rejects ../victim"; else bad "rm rejects ../victim" "rc=$RC out=$OUT"; fi
canary "$T/victim2.md"
run rm "../../victim2"
if [ -f "$T/victim2.md" ] && [ "$RC" != 0 ]; then ok "rm rejects ../../victim2"; else bad "rm rejects ../../victim2" "rc=$RC out=$OUT"; fi
canary "$PLANE/victim3.md"
run move "../victim3" cross
if [ -f "$PLANE/victim3.md" ] && [ ! -e "$PLANE/memory/victim3.md" ]; then ok "move rejects ../victim3"; else bad "move rejects ../victim3" "rc=$RC out=$OUT"; fi
run rm ok2 repo api; assert_eq "rm of a real memory still works" 0 "$RC"
assert "rm removed it" test ! -e "$PLANE/memory/api/ok2.md"

finish
