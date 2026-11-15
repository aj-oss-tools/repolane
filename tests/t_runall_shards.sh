#!/usr/bin/env bash
# run-all.sh --shard: CI runs the suite split across jobs, so every file must land in exactly one of them, and the CI
# matrix (.github/workflows/tests.yml) must cover the whole set. A file that fell between shards would never run anywhere.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
RA="$PRODUCT/tests/run-all.sh"
all=$(bash "$RA" --list | sort)
assert "--list names every t_*.sh" test "$(printf '%s\n' "$all" | grep -c .)" -eq "$(ls "$PRODUCT"/tests/t_*.sh | wc -l | tr -d ' ')"
assert_eq "no arguments selects every file" "$(cd "$PRODUCT/tests" && ls t_*.sh | sort)" "$all"
for n in 1 2 3 5; do
  got=""; i=1
  while [ "$i" -le "$n" ]; do got="$got
$(bash "$RA" --exclude t_guard_agents.sh --shard "$i/$n" --list)"; i=$((i+1)); done
  got=$(printf '%s\n' "$got" | grep . | sort)
  assert_eq "$n shard(s) plus the excluded file are exactly the whole set" "$all" "$(printf '%s\nt_guard_agents.sh\n' "$got" | sort)"
  assert_eq "$n shard(s): no file in two shards" "" "$(printf '%s\n' "$got" | uniq -d)"
done
assert_eq "--only runs just that file" "t_memory.sh" "$(bash "$RA" --only t_memory.sh --list)"
assert_eq "the same split every time" "$(bash "$RA" --shard 1/2 --list)" "$(bash "$RA" --shard 1/2 --list)"
out=$(bash "$RA" --only t_nope.sh --list 2>&1); rc=$?
assert_eq "a misspelt name is refused, not run as nothing" 2 "$rc"
out=$(bash "$RA" --exclude t_nope.sh --list 2>&1); rc=$?
assert_eq "a misspelt exclusion is refused, not ignored" 2 "$rc"
out=$(bash "$RA" --shard 3/2 --list 2>&1); rc=$?
assert_eq "a shard out of range is refused" 2 "$rc"

# the CI matrix runs each shard of the same n once, plus every file it excludes on its own
wf="$PRODUCT/.github/workflows/tests.yml"
n=$(grep -oE -- '--shard [0-9]+/[0-9]+' "$wf" | head -1 | cut -d/ -f2)
assert "the workflow shards the lane suite" test -n "$n"
shards=$(grep -oE -- '--shard [0-9]+/[0-9]+' "$wf" | sort -u | grep -c .)
assert_eq "the workflow runs shards 1..$n of $n, each once" "$n" "$shards"
excl=$(grep -oE -- '--exclude [^ "]+' "$wf" | awk '{print $2}' | sort -u)
for e in $excl; do
  assert_contains "the workflow runs the excluded $e on its own" "$(cat "$wf")" "--only $e"
done
finish
