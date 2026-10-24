#!/usr/bin/env bash
# The installed package is not a clone: `lane help` does not offer a clone's `install` / `use`, and both refuse with a
# pointer to `lane init` / `lane migrate` (a clone keeps them). A session inside a lane is refused `lane migrate`,
# `lane init` and `lane upgrade`: the owner runs those from a terminal at the root.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
new_sandbox
install_product
unset -f lane
CLEAN_PATH=$(printf '%s' "$PATH" | tr ':' '\n' | while IFS= read -r d; do [ -n "$d" ] && [ ! -e "$d/lane" ] && printf '%s:' "$d"; done)
export PATH="$BIN:${CLEAN_PATH%:}"
L(){ local d="$1"; shift; OUT=$(cd "$d" && env -u LANE_WORKSPACE lane "$@" </dev/null 2>&1); RC=$?; }
W="$T/ws"; mkdir -p "$W"
L "$W" init --owner "Sam" --yes --claude-home "$T/claude"; assert_eq "init" 0 "$RC"

echo "-- lane help from the package"
L "$W" help
assert_not_contains "help does not list install" "$OUT" "install    "
assert_not_contains "help does not list use" "$OUT" "use        "
assert_contains "help lists migrate" "$OUT" "migrate"
L "$T" help
assert_not_contains "nor outside a workspace" "$OUT" "install    "

echo "-- lane install and lane use from the package refuse"
L "$W" install; assert_eq "lane install exits 2" 2 "$RC"
assert_contains "and says the package is on PATH already" "$OUT" "already"
assert_contains "and points at lane init" "$OUT" "lane init"
assert "and writes no router into ~/.local/bin" test ! -e "$HOME/.local/bin/lane"
assert "nor a registry helper" test ! -e "$HOME/.local/share/lane/planes.py"
L "$W" use; assert_eq "lane use exits 2" 2 "$RC"
assert_contains "and says the package acts on the workspace you are in" "$OUT" "workspace you are in"
L "$W" use other; assert_eq "lane use <name> exits 2" 2 "$RC"

echo "-- a clone keeps them"
OUT=$(cd "$PLANE" && ./lane help 2>&1)
assert_contains "a clone's help lists install" "$OUT" "install"
assert_contains "and use" "$OUT" "use        switch"

echo "-- a lane session is refused lane migrate, lane init, lane upgrade"
make_remote_repo api
L "$W" add "$T/remotes/api.git" api --yes
L "$W" start L1 api; assert_eq "start" 0 "$RC"
g(){ printf '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"%s"},"cwd":"%s","session_id":"s"}' "$1" "$2" \
     | (cd "$2" && CLAUDE_PROJECT_DIR="$2" lane hook pre-tool-use) 2>&1; }
for c in "lane migrate" "lane migrate $W" "lane init" "lane upgrade" "lane-init" "lane upgrade --refresh-only"; do
  o=$(g "$c" "$W/lanes/L1")
  assert_contains "in a lane: $c is refused" "$o" '"deny"'
  assert_contains "  and the owner runs it from a terminal" "$o" "from a terminal at the workspace root"
done
o=$(g "lane migrate --dry-run" "$W/lanes/L1/api"); assert_contains "from a repo of the lane too" "$o" '"deny"'
o=$(g "lane status" "$W/lanes/L1"); assert_not_contains "lane status is not refused" "$o" '"deny"'
init_plane >/dev/null 2>&1
(cd "$PLANE" && ./lane add "$T/remotes/api.git" api </dev/null >/dev/null 2>&1; ./lane start C1 api </dev/null >/dev/null 2>&1)
o=$(printf '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"lane migrate"},"cwd":"%s","session_id":"s"}' "$PLANE/lanes/C1" \
    | CLAUDE_PROJECT_DIR="$PLANE/lanes/C1" env -u LANE_PRODUCT -u LANE_WORKSPACE python3 "$PLANE/scripts/hooks/guard.py" 2>&1)
assert_contains "a clone's lane session is refused lane migrate too" "$o" '"deny"'
assert_contains "  in a clone's words" "$o" "control plane root"

echo "-- a clone's lane install over the package's lane on PATH refuses, and registers no venv as a plane"
PLANES="$HOME/.local/share/lane/planes.json"
CI(){ OUT=$(cd "$PLANE" && env -u LANE_PRODUCT -u LANE_WORKSPACE ./lane install "$@" </dev/null 2>&1); RC=$?; }
mkdir -p "$HOME/.local/bin" "$T/pipx/venvs/repolane/bin"
printf '#!%s/pipx/venvs/repolane/bin/python\nimport sys\nfrom repolane.cli import main\nsys.exit(main())\n' "$T" > "$T/pipx/venvs/repolane/bin/lane"
chmod +x "$T/pipx/venvs/repolane/bin/lane"
ln -sf "$T/pipx/venvs/repolane/bin/lane" "$HOME/.local/bin/lane"
CI; assert_eq "lane install over pipx's lane exits 2" 2 "$RC"
assert_contains "it says that lane is the installed package's" "$OUT" "is the installed Repolane package's lane"
assert_contains "and points at lane migrate" "$OUT" "lane migrate"
assert_eq "pipx's link is left as it was" "$T/pipx/venvs/repolane/bin/lane" "$(readlink "$HOME/.local/bin/lane")"
assert_not_contains "no venv bin/ is registered as a plane" "$(cat "$PLANES" 2>/dev/null)" "venvs"
if head -c 4096 "$BIN/lane" | grep -q 'repolane'; then
  ln -sf "$BIN/lane" "$HOME/.local/bin/lane"
  CI; assert_eq "the same over the real installed package's launcher" 2 "$RC"
  assert_eq "  which is left in place" "$BIN/lane" "$(readlink "$HOME/.local/bin/lane")"
fi
rm -f "$HOME/.local/bin/lane"; printf '#!/usr/bin/env python3\nfrom repolane.cli import main\n' > "$HOME/.local/bin/lane"
CI; assert_eq "and over pip's plain launcher file" 2 "$RC"
echo "-- an old link to something that is not a clone is replaced, but not registered"
mkdir -p "$T/notaclone"; printf '#!/bin/sh\necho hi\n' > "$T/notaclone/lane"; chmod +x "$T/notaclone/lane"
rm -f "$HOME/.local/bin/lane"; ln -s "$T/notaclone/lane" "$HOME/.local/bin/lane"
CI; assert_eq "lane install succeeds" 0 "$RC"
assert_contains "it says why it does not register it" "$OUT" "it is not a git clone of Repolane"
assert_not_contains "planes.json has no entry for it" "$(cat "$PLANES" 2>/dev/null)" "notaclone"
assert_contains "the clone itself is registered" "$(cat "$PLANES" 2>/dev/null)" "$PLANE"
finish
