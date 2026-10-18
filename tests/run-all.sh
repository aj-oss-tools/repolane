#!/usr/bin/env bash
# bash tests/run-all.sh  : run every tests/t_*.sh in its own throwaway sandbox, then print totals.
# Exit status is nonzero when any case fails.
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
total_pass=0; total_fail=0; bad_files=""
for t in "$here"/t_*.sh; do
  [ -f "$t" ] || continue
  echo "== $(basename "$t")"
  out=$(bash "$t" 2>&1); rc=$?
  printf '%s\n' "$out"
  line=$(printf '%s\n' "$out" | grep -E '^[0-9]+ passed, [0-9]+ failed$' | tail -1)
  p=${line%% passed*}; f=${line#*, }; f=${f%% failed*}
  case "$p" in ''|*[!0-9]*) p=0; rc=1 ;; esac
  case "$f" in ''|*[!0-9]*) f=0; rc=1 ;; esac
  total_pass=$((total_pass+p)); total_fail=$((total_fail+f))
  if [ "$rc" != 0 ]; then bad_files="$bad_files $(basename "$t")"; [ "$f" = 0 ] && total_fail=$((total_fail+1)); fi
done
echo
echo "TOTAL: $total_pass passed, $total_fail failed"
[ "$total_fail" = 0 ] || { echo "failing files:$bad_files"; exit 1; }
