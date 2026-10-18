#!/usr/bin/env bash
# Item 19: `lane upgrade` must work on a plane that `lane init` (or `lane init --private`) just
# dirtied, and must still refuse for real local edits.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
START_VERSION=$(tr -d '[:space:]' < "$(dirname "${BASH_SOURCE[0]}")/../VERSION")   # the version the sandbox plane starts at (a copy of this checkout)

# publish_update <message> : push a new commit (VERSION bump + changelog line) to ORIGIN
publish_update(){
  local w="$T/pub"; rm -rf "$w"; git clone -q "$ORIGIN" "$w"
  printf '9.9.9\n' > "$w/VERSION"
  printf '\n## [9.9.9] - 2026-01-01\n- %s\n' "$1" >> "$w/CHANGELOG.md"
  git -C "$w" add -A; git -C "$w" commit -q -m "$1"; git -C "$w" push -q origin HEAD:main
}

echo "-- after lane init"
new_sandbox; init_plane >/dev/null 2>&1
assert "init really dirtied the tree (premise)" test -n "$(git -C "$PLANE" status --porcelain)"
publish_update "update one"
lane upgrade
assert_eq "lane upgrade after lane init exits 0" 0 "$RC"
assert_contains "upgrade reports the new version" "$OUT" "9.9.9"
assert_eq "VERSION really moved" "9.9.9" "$(tr -d '[:space:]' < "$PLANE/VERSION")"
assert "init's own settings edit survived the upgrade" grep -q statusLine "$PLANE/.claude/settings.json"

echo "-- after lane init --private"
new_sandbox; init_plane --private >/dev/null 2>&1
git -C "$PLANE" diff --quiet -- .gitignore && bad ".gitignore was modified by init --private (premise)" || ok ".gitignore was modified by init --private (premise)"
publish_update "update two"
lane upgrade
assert_eq "lane upgrade after lane init --private exits 0" 0 "$RC"
assert_eq "VERSION moved (private)" "9.9.9" "$(tr -d '[:space:]' < "$PLANE/VERSION")"
assert_not_contains "no refusal text" "$OUT" "uncommitted changes in tracked files"

echo "-- still refuses real local edits"
new_sandbox; init_plane >/dev/null 2>&1
printf '\n# my local hack\n' >> "$PLANE/scripts/lane-done"
publish_update "update three"
lane upgrade
assert_eq "tracked edit outside the allowed paths still blocks (rc 1)" 1 "$RC"
assert_contains "names the offending file" "$OUT" "scripts/lane-done"
assert_eq "nothing moved" "$START_VERSION" "$(tr -d '[:space:]' < "$PLANE/VERSION")"
git -C "$PLANE" checkout -q -- scripts/lane-done 2>/dev/null || cp "$PRODUCT/scripts/lane-done" "$PLANE/scripts/lane-done"
printf 'x\n' > "$PLANE/untracked-notes.txt"
lane upgrade
assert_eq "an untracked scratch file does not block" 0 "$RC"

echo "-- private-only paths do not leak into the public case"
new_sandbox; init_plane >/dev/null 2>&1
printf '\n# my edit\n' >> "$PLANE/.gitignore"
publish_update "update four"
lane upgrade
assert_eq "hand-edited .gitignore on a public plane still blocks" 1 "$RC"

echo "-- upstream also changes .claude/settings.json (the usual conflict): the upgrade succeeds, init's edit survives"
new_sandbox; init_plane >/dev/null 2>&1
assert "init added statusLine (premise)" grep -q statusLine "$PLANE/.claude/settings.json"
w="$T/pub"; git clone -q "$ORIGIN" "$w"
python3 - "$w/.claude/settings.json" <<'PY'
import json, sys
p = sys.argv[1]; d = json.load(open(p))
d["permissions"]["allow"].append("Bash(upstream-new-thing:*)"); d["upstreamOnlyKey"] = True
json.dump(d, open(p, "w"), indent=2)
PY
printf '9.9.9\n' > "$w/VERSION"; git -C "$w" commit -q -am "touch settings"; git -C "$w" push -q origin HEAD:main
lane upgrade
assert_eq "settings.json changed upstream + dirty from init: upgrade exits 0" 0 "$RC"
assert_eq "VERSION moved" "9.9.9" "$(tr -d '[:space:]' < "$PLANE/VERSION")"
assert_not_contains "no git overwrite error" "$OUT" "would be overwritten"
assert_not_contains "no unusable --theirs recipe" "$OUT" "checkout --theirs"
assert "the upstream change landed" grep -q upstream-new-thing "$PLANE/.claude/settings.json"
assert "upstream-only key landed" grep -q upstreamOnlyKey "$PLANE/.claude/settings.json"
assert "init's statusLine edit was re-applied" grep -q statusLine "$PLANE/.claude/settings.json"
assert "the result is valid JSON" python3 -c "import json,sys;json.load(open(sys.argv[1]))" "$PLANE/.claude/settings.json"

echo "-- a registry file (registry/config.yml) dirty locally AND changed upstream: refused before anything moves, with a recipe that works"
new_sandbox; init_plane >/dev/null 2>&1
printf '\n# mine\n' >> "$PLANE/registry/config.yml"
w="$T/pub"; git clone -q "$ORIGIN" "$w"; printf '\n# theirs\n' >> "$w/registry/config.yml"; printf '9.9.9\n' > "$w/VERSION"
git -C "$w" commit -q -am "touch config"; git -C "$w" push -q origin HEAD:main
lane upgrade
assert_eq "dirty registry/config.yml that upstream also changes: rc 1" 1 "$RC"
assert_contains "names the file" "$OUT" "registry/config.yml"
assert_contains "gives a recipe that works (stash)" "$OUT" "git stash"
assert_eq "nothing moved" "$START_VERSION" "$(tr -d '[:space:]' < "$PLANE/VERSION")"
(cd "$PLANE" && git stash -q && ./lane upgrade >/dev/null 2>&1; git stash pop -q 2>/dev/null); 
assert_eq "following the recipe's first steps does upgrade" "9.9.9" "$(tr -d '[:space:]' < "$PLANE/VERSION")"

finish
