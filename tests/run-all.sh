#!/usr/bin/env bash
# bash tests/run-all.sh  : run every tests/t_*.sh in its own throwaway sandbox, then print totals.
# Exit status is nonzero when any case fails.
#
# CI splits the files across jobs; with no arguments it runs them all, as before:
#   --only <file>       run just this file (repeatable)
#   --exclude <file>    leave this file out (repeatable); --only and --exclude take the name, t_x.sh
#   --shard <i>/<n>     run the i-th of n shards of what is left, balanced by tests/timings.txt
#   --list              print the files that would run, one per line, and run nothing
# Every file lands in exactly one shard (tests/t_runall_shards.sh checks it), so a file added later is never dropped:
# one missing from timings.txt runs with the DEFAULT weight.
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
only=" "; exclude=" "; shard=""; list=0
while [ $# -gt 0 ]; do
  case "$1" in
    --only) only="$only$2 "; shift 2 ;;
    --exclude) exclude="$exclude$2 "; shift 2 ;;
    --shard) shard="$2"; shift 2 ;;
    --list) list=1; shift ;;
    *) echo "run-all.sh: unknown argument: $1" >&2; exit 2 ;;
  esac
done
for b in $only $exclude; do   # a misspelt or renamed name must not quietly run nothing, or everything
  [ -f "$here/$b" ] || { echo "run-all.sh: no such test file: $b" >&2; exit 2; }
done
files=""
for t in "$here"/t_*.sh; do
  [ -f "$t" ] || continue
  b=$(basename "$t")
  [ "$only" != " " ] && case "$only" in *" $b "*) ;; *) continue ;; esac
  case "$exclude" in *" $b "*) continue ;; esac
  files="$files $b"
done
if [ -n "$shard" ]; then
  si=${shard%/*}; sn=${shard#*/}
  case "$si$sn" in ''|*[!0-9]*) echo "run-all.sh: --shard wants <i>/<n>, got $shard" >&2; exit 2 ;; esac
  [ "$si" -ge 1 ] && [ "$si" -le "$sn" ] || { echo "run-all.sh: --shard $shard is out of range" >&2; exit 2; }
  def=$(awk '$1=="DEFAULT"{print $2}' "$here/timings.txt" 2>/dev/null); [ -n "$def" ] || def=20
  # longest first, each to the shard with the least so far (ties to the lower shard): the same split on every machine
  load=(); k=1; while [ "$k" -le "$sn" ]; do load[$k]=0; k=$((k+1)); done
  picked=""
  for row in $(for b in $files; do
                 w=$(awk -v f="$b" '$1==f{print $2}' "$here/timings.txt" 2>/dev/null); printf '%s:%s\n' "${w:-$def}" "$b"
               done | sort -t: -k1,1nr -k2,2); do
    w=${row%%:*}; b=${row#*:}; best=1; k=2
    while [ "$k" -le "$sn" ]; do [ "${load[$k]}" -lt "${load[$best]}" ] && best=$k; k=$((k+1)); done
    load[$best]=$((${load[$best]}+w))
    [ "$best" = "$si" ] && picked="$picked $b"
  done
  files=""; for t in "$here"/t_*.sh; do b=$(basename "$t"); case "$picked " in *" $b "*) files="$files $b" ;; esac; done
fi
if [ "$list" = 1 ]; then for b in $files; do echo "$b"; done; exit 0; fi
[ -n "$files" ] || { echo "run-all.sh: nothing selected to run" >&2; exit 1; }
total_pass=0; total_fail=0; bad_files=""
for b in $files; do
  t="$here/$b"
  echo "== $b"
  out=$(bash "$t" 2>&1); rc=$?
  printf '%s\n' "$out"
  line=$(printf '%s\n' "$out" | grep -E '^[0-9]+ passed, [0-9]+ failed$' | tail -1)
  p=${line%% passed*}; f=${line#*, }; f=${f%% failed*}
  case "$p" in ''|*[!0-9]*) p=0; rc=1 ;; esac
  case "$f" in ''|*[!0-9]*) f=0; rc=1 ;; esac
  total_pass=$((total_pass+p)); total_fail=$((total_fail+f))
  if [ "$rc" != 0 ]; then bad_files="$bad_files $b"; [ "$f" = 0 ] && total_fail=$((total_fail+1)); fi
done
echo
echo "TOTAL: $total_pass passed, $total_fail failed"
[ "$total_fail" = 0 ] || { echo "failing files:$bad_files"; exit 1; }
