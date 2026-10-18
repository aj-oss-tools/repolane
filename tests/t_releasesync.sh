#!/usr/bin/env bash
# scripts/release-sync keeps release from falling behind main. Merging release into main with a merge commit
# leaves that commit on main only; the workflow runs this after every push to main to bring it back. Scratch repos only.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
T=$(mk_tmp); SANDBOXES="$SANDBOXES $T"; export HOME="$T/home"; mkdir -p "$HOME"
export GIT_CONFIG_GLOBAL="$HOME/.gitconfig"; : > "$GIT_CONFIG_GLOBAL"; git config --global init.defaultBranch main
SCRIPT="$PRODUCT/scripts/release-sync"

# fresh: origin with main and release equal; W is a working clone (the workflow's checkout)
fresh(){
  rm -rf "$T/o.git" "$T/w" "$T/dev"; git init -q --bare "$T/o.git"; git clone -q "$T/o.git" "$T/dev" 2>/dev/null
  (cd "$T/dev"; git checkout -q -b main; echo base > f; git add f; git commit -q -m base; git push -q origin main; git checkout -q -b release; git push -q origin release)
}
dev_commit(){ ( cd "$T/dev"; git checkout -q "$1"; echo "$3" > "$2"; git add "$2"; git commit -q -m "$3"; git push -q origin "$1" ); }
# release_to_main: what merging the release PR does, a plain merge commit on main
release_to_main(){ ( cd "$T/dev"; git checkout -q main; git merge -q --no-ff origin/release -m "Release PR"; git push -q origin main ); }
run(){ rm -rf "$T/w"; git clone -q "$T/o.git" "$T/w" 2>/dev/null; OUT=$(cd "$T/w" && bash "$SCRIPT" 2>&1); RC=$?; }
tip(){ git -C "$T/o.git" rev-parse "$1"; }
behind(){ git -C "$T/o.git" rev-list --count "$1..$2"; }

echo "-- main and release already equal"
fresh; run; assert_eq "exits 0" 0 "$RC"; assert_contains "says release already has main" "$OUT" "already contains main"

echo "-- a release PR was merged (release has not moved): fast-forward, release == main"
fresh; dev_commit release a1 "release 0.9.1"; release_to_main
assert_eq "before: main has a commit release lacks" 1 "$(behind release main)"
run; assert_eq "exits 0" 0 "$RC"; assert_contains "fast-forwarded" "$OUT" "fast-forwarded"
assert_eq "after: release is not behind main" 0 "$(behind release main)"; assert_eq "release == main" "$(tip main)" "$(tip release)"

echo "-- release moved on meanwhile: a merge commit, nothing lost"
fresh; dev_commit release a1 "release 0.9.1"; release_to_main; dev_commit release a2 "docs: later work"; main_before=$(tip main)
run; assert_eq "exits 0" 0 "$RC"; assert_contains "merged main into release" "$OUT" "merged main into release"
assert_eq "release is not behind main" 0 "$(behind release main)"
assert_contains "the later work is still on release" "$(git -C "$T/o.git" log --format=%s release)" "docs: later work"
assert_eq "main is untouched" "$main_before" "$(tip main)"

echo "-- a conflict is reported, never resolved, and nothing is pushed"
fresh; dev_commit main f "main edit"; dev_commit release f "release edit"; before=$(tip release)
run; assert_eq "exits non-zero" 1 "$RC"; assert_contains "names the conflicting file" "$OUT" "conflicts: f"
assert_eq "release is exactly as it was" "$before" "$(tip release)"
assert_eq "the working copy is left clean, no half-done merge" "" "$(git -C "$T/w" status --porcelain)"
assert "no merge in progress" test ! -e "$T/w/.git/MERGE_HEAD"

echo "-- release-sync never forces"
assert_not_contains "no --force in the script" "$(grep -v '^#' "$SCRIPT")" "--force"
assert_not_contains "no -f push flag" "$(grep -v '^#' "$SCRIPT" | grep 'git push')" " -f"

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" = 0 ]
