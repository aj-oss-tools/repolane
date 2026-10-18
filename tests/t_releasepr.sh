#!/usr/bin/env bash
# scripts/release-pr decides whether the pull request release -> main exists and what it says. The release
# workflow calls it after every push to release, so a change with no changelog entry (docs, CI, tests) still
# reaches main through a PR that waits for the checks, instead of waiting for someone to open it by hand.
# Everything runs against scratch repos and a fake `gh` that records what it is asked to do.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
T=$(mk_tmp); SANDBOXES="$SANDBOXES $T"; export HOME="$T/home"; mkdir -p "$HOME"
export GIT_CONFIG_GLOBAL="$HOME/.gitconfig"; : > "$GIT_CONFIG_GLOBAL"; git config --global init.defaultBranch main
SCRIPT="$PRODUCT/scripts/release-pr"

# a fake gh: logs every call; `pr list` answers with $FAKE_EXISTING (a PR number, or empty)
mkdir -p "$T/bin"; cat > "$T/bin/gh" <<'SH'
#!/usr/bin/env bash
echo "$*" >> "$FAKE_LOG"
case "$1 $2" in "pr list") echo "${FAKE_EXISTING:-}" ;; esac
SH
chmod +x "$T/bin/gh"; export FAKE_LOG="$T/gh.log"

# fresh_repo : origin (bare) with main, a clone on release one commit ahead when asked
fresh_repo(){
  rm -rf "$T/o.git" "$T/w"; git init -q --bare "$T/o.git"; git clone -q "$T/o.git" "$T/w" 2>/dev/null
  git -C "$T/w" checkout -q -b main; echo a > "$T/w/a"; echo 0.9.0 > "$T/w/VERSION"; git -C "$T/w" add a VERSION; git -C "$T/w" commit -q -m "first"
  git -C "$T/w" push -q origin main; git -C "$T/w" checkout -q -b release; git -C "$T/w" push -q origin release
}
ahead_commit(){ echo "$1" > "$T/w/$1"; git -C "$T/w" add "$1"; git -C "$T/w" commit -q -m "$2"; git -C "$T/w" push -q origin release; }
bump_version(){ echo "$1" > "$T/w/VERSION"; git -C "$T/w" add VERSION; git -C "$T/w" commit -q -m "release $1"; git -C "$T/w" push -q origin release; }
run(){ : > "$FAKE_LOG"; OUT=$(cd "$T/w" && GH="$T/bin/gh" GH_TOKEN=tok bash "$SCRIPT" "$@" 2>&1); RC=$?; }

echo "-- release has nothing main lacks"
fresh_repo; run
assert_eq "exits 0" 0 "$RC"; assert_contains "says so" "$OUT" "nothing"; assert_eq "no gh call" "" "$(cat "$FAKE_LOG")"

echo "-- release is ahead, no version (docs/CI only): a sync PR"
fresh_repo; ahead_commit f1 "docs: fix a typo"; ahead_commit f2 "ci: tighten a check"; run
assert_eq "exits 0" 0 "$RC"
assert_contains "asked for the open PRs first" "$(cat "$FAKE_LOG")" "pr list --base main --head release --state open"
assert_contains "creates the PR into main from release" "$(cat "$FAKE_LOG")" "pr create --base main --head release"
assert_contains "titled as a sync, not a release" "$(cat "$FAKE_LOG")" "--title Sync release into main"
assert_contains "the body lists the commits" "$(cat "$FAKE_LOG")" "docs: fix a typo"
assert_contains "and the second one" "$(cat "$FAKE_LOG")" "ci: tighten a check"
assert_contains "and says no new version" "$(cat "$FAKE_LOG")" "no new version"

echo "-- VERSION on release is ahead of main's: the release PR"
fresh_repo; ahead_commit f1 "docs: x"; bump_version 0.9.1; run
assert_contains "titled Release v0.9.1" "$(cat "$FAKE_LOG")" "--title Release v0.9.1"
assert_contains "mentions the tag" "$(cat "$FAKE_LOG")" "tags v0.9.1"

echo "-- a docs-only push while the release PR is open keeps it a release PR"
fresh_repo; bump_version 0.9.1; ahead_commit f9 "docs: later"; FAKE_EXISTING=19 run
assert_contains "edits #19" "$(cat "$FAKE_LOG")" "pr edit 19"
assert_contains "and still titles it Release v0.9.1" "$(cat "$FAKE_LOG")" "--title Release v0.9.1"
assert_not_contains "never renames it to a sync" "$(cat "$FAKE_LOG")" "Sync release into main"

echo "-- an open PR is updated, not duplicated"
fresh_repo; ahead_commit f1 "docs: x"; FAKE_EXISTING=42 run
assert_contains "edits #42" "$(cat "$FAKE_LOG")" "pr edit 42"
assert_not_contains "does not create a second one" "$(cat "$FAKE_LOG")" "pr create"

echo "-- squash-merged or merged back: no commits left, no PR"
fresh_repo; ahead_commit f1 "docs: y"; git -C "$T/w" checkout -q main; git -C "$T/w" merge -q --no-ff release -m "Merge release"; git -C "$T/w" push -q origin main; git -C "$T/w" checkout -q release
run; assert_contains "nothing to open once main contains release" "$OUT" "nothing"; assert_eq "no gh call" "" "$(cat "$FAKE_LOG")"

echo "-- release ahead only by a merge commit (main brought back in): no PR"
fresh_repo; git -C "$T/w" checkout -q main; echo m > "$T/w/m"; git -C "$T/w" add m; git -C "$T/w" commit -q -m "hotfix on main"; git -C "$T/w" push -q origin main
git -C "$T/w" checkout -q release; echo r > "$T/w/r"; git -C "$T/w" add r; git -C "$T/w" commit -q -m "feature on release"; git -C "$T/w" push -q origin release
git -C "$T/w" checkout -q main; git -C "$T/w" merge -q --no-ff release -m "Release PR"; git -C "$T/w" push -q origin main
git -C "$T/w" checkout -q release; git -C "$T/w" merge -q --no-ff main -m "Merge main into release"; git -C "$T/w" push -q origin release
run; assert_contains "a merge commit alone is not something to ship" "$OUT" "nothing"; assert_eq "no gh call" "" "$(cat "$FAKE_LOG")"

echo "-- no token: skip without failing the workflow"
fresh_repo; ahead_commit f1 "docs: z"; : > "$FAKE_LOG"
OUT=$(cd "$T/w" && env -u GH_TOKEN GH="$T/bin/gh" bash "$SCRIPT" 2>&1); RC=$?
assert_eq "exits 0" 0 "$RC"; assert_contains "names the missing secret" "$OUT" "RELEASE_PR_TOKEN"; assert_eq "no gh call" "" "$(cat "$FAKE_LOG")"

echo "-- --dry-run prints the decision and calls nothing"
fresh_repo; ahead_commit f1 "docs: w"; run --dry-run
assert_contains "prints the title" "$OUT" "Sync release into main"; assert_eq "no gh call" "" "$(cat "$FAKE_LOG")"

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" = 0 ]
