#!/usr/bin/env bash
# The upgrade path: an install made with the LATEST RELEASE, using that release's own `lane init`
# and its own `lane upgrade`, must be able to upgrade onto this checkout.
#
# The upgrader that runs is the one already on the user's machine, so a change that breaks it can
# only be caught by running the old one. tests/t_upgrade.sh covers the current upgrader; this covers
# the shipped one against whatever this branch is about to ship. It fails when, for example, the
# branch edits a file that `lane init` leaves modified in every install (a merge conflict), or
# changes something the released upgrader refuses on.
#
# Baseline: UPGRADE_BASELINE, else the newest v* tag. Releases before v0.9.0 refuse the upgrade
# once, because `lane init` modified .claude/settings.json (docs/troubleshooting.md has the
# one-time step), so they are skipped. A checkout without tags fails under CI (use
# `fetch-depth: 0`) and is skipped anywhere else.
#
# Everything lives in a temp dir with a throwaway HOME; the product checkout is only read.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

echo "-- upgrade path: latest release -> this checkout"
base_tag="${UPGRADE_BASELINE:-$(git -C "$PRODUCT" tag --list 'v[0-9]*' --sort=-v:refname 2>/dev/null | head -1)}"
if [ -z "$base_tag" ]; then
  if [ -n "${CI:-}" ]; then bad "a release tag to upgrade from exists (checkout with fetch-depth: 0)"; else echo "  skip  no v* tag in this checkout"; fi
  printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"; [ "$FAIL" = 0 ]; exit
fi
oldest_ok="v0.9.0"
if [ "$(printf '%s\n%s\n' "$oldest_ok" "$base_tag" | sort -V | head -1)" != "$oldest_ok" ]; then
  echo "  skip  baseline $base_tag predates the upgrader fix (one-time step in docs/troubleshooting.md)"
  printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"; exit 0
fi
base_sha=$(git -C "$PRODUCT" rev-parse "$base_tag^{commit}")

new_sandbox
rm -rf "$PLANE" "$ORIGIN"

# the candidate: this checkout's files (working tree included) as one commit on top of the release
CAND="$T/cand"
git clone -q --no-hardlinks "$PRODUCT" "$CAND" 2>/dev/null
git -C "$CAND" checkout -q --detach "$base_sha"
git -C "$CAND" rm -rq --ignore-unmatch . 2>/dev/null
copy_product_tree "$CAND"
git -C "$CAND" add -A && git -C "$CAND" commit -q --allow-empty -m "candidate"
cand_version=$(cat "$CAND/VERSION")
cand_matcher=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["hooks"]["PreToolUse"][0]["matcher"])' "$CAND/.claude/settings.json")

REMOTE="$T/remote.git"; git init -q --bare "$REMOTE"
git -C "$CAND" push -q "$REMOTE" "$base_sha:refs/heads/main"

for variant in public private; do
  echo "-- $base_tag install ($variant) upgrading to this checkout (VERSION $cand_version)"
  P="$T/plane-$variant"
  git -C "$CAND" push -q --force "$REMOTE" "$base_sha:refs/heads/main"   # the throwaway remote starts at the release again
  git clone -q "$REMOTE" "$P"; git -C "$P" config user.name t; git -C "$P" config user.email t@example.com
  mkdir -p "$P/repos" "$P/lanes" "$P/.cache"
  flags=""; [ "$variant" = private ] && flags="--private"
  (cd "$P" && ./lane init --owner Test --yes --claude-home "$T/claude-$variant" $flags </dev/null) >/dev/null 2>&1
  assert_eq "the release's own lane init succeeds" 0 "$?"
  assert_contains "init left .claude/settings.json modified, as in every install" "$(git -C "$P" status --short)" ".claude/settings.json"
  # now the candidate lands upstream, and the user upgrades with the scripts already on their machine
  git -C "$CAND" push -q "$REMOTE" "HEAD:refs/heads/main"
  OUT=$(cd "$P" && ./lane upgrade </dev/null 2>&1); RC=$?
  assert_eq "the release's own lane upgrade exits 0" 0 "$RC"
  [ "$RC" = 0 ] || printf '%s\n' "$OUT" | sed 's/^/        /'
  assert_eq "VERSION is now the candidate's" "$cand_version" "$(cat "$P/VERSION")"
  assert_eq "no merge conflict is left behind" "" "$(git -C "$P" status --short | grep -E '^(UU|AA|DU|UD) ')"
  got=$(python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));print(d["hooks"]["PreToolUse"][0]["matcher"]);print("statusLine" in d)' "$P/.claude/settings.json" 2>&1)
  assert_eq "settings.json is valid JSON with the candidate's hook matcher and the user's statusLine" "$cand_matcher
True" "$got"
  (cd "$P" && ./lane doctor </dev/null) >/dev/null 2>&1
  assert_eq "lane doctor is happy afterwards" 0 "$?"
  (cd "$P" && ./lane upgrade </dev/null) >/dev/null 2>&1
  assert_eq "a second lane upgrade is a clean no-op" 0 "$?"
done

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" = 0 ]
