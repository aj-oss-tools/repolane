#!/usr/bin/env bash
# Every script that rewrites one section of a lane file (registry/lanes/<id>.md: Goal, Resume note, Findings, Log)
# changes that section's body only, up to the next `## ` heading, and never what comes after it. lane park once
# replaced everything from `## Resume note` to `## Log`, which deleted the `## Findings` lane start writes between them.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
new_sandbox; init_plane >/dev/null 2>&1
make_remote_repo api; add_repo api
lane start L1 api; assert_eq "start L1" 0 "$RC"
F="$PLANE/registry/lanes/L1.md"
lm(){ (cd "$PLANE/lanes/L1" && "$PLANE/scripts/lane-memory" "$@" </dev/null 2>&1); }

echo "-- lane park keeps the Findings"
lm draft keep-me "---
name: keep-me
description: the cache key includes the tenant
---
body of the finding" >/dev/null
lm file keep-me lane L1 >/dev/null
assert_contains "the finding was filed" "$(cat "$F")" "the cache key includes the tenant"
lane park L1 "parked after the first finding, next: write the test"; assert_eq "park" 0 "$RC"
t=$(cat "$F")
assert_contains "the Findings heading is still there" "$t" "## Findings"
assert_contains "the finding survives lane park" "$t" "the cache key includes the tenant"
assert_contains "the resume note is written" "$t" "parked after the first finding"
assert_contains "the Goal is still there" "$t" "## Goal"
assert_eq "one Resume note section" 1 "$(grep -c '^## Resume note' "$F")"
lane park L1 "second park replaces the note, keeps the rest"
t=$(cat "$F")
assert_not_contains "the old note is replaced" "$(sed -n '/^## Resume note/,/^## /p' "$F")" "after the first finding, next"
assert_contains "the finding survives a second park" "$t" "the cache key includes the tenant"

echo "-- a section the owner added after the Resume note is kept too"
python3 - "$F" <<'PY'
import sys; f=sys.argv[1]; t=open(f).read()
t=t.replace("## Findings","## Notes\nmy own words\n\n## Findings",1); open(f,"w").write(t)
PY
lane park L1 "third park with an extra section after the note"
assert_contains "the owner's section survives" "$(cat "$F")" "my own words"
assert_contains "and the finding" "$(cat "$F")" "the cache key includes the tenant"

echo "-- lane-memory goal replaces only the Goal"
lm goal "the new goal text" >/dev/null
t=$(cat "$F")
assert_contains "goal saved" "$t" "the new goal text"
assert_contains "the note survives the goal" "$t" "third park with an extra section"
assert_contains "the finding survives the goal" "$t" "the cache key includes the tenant"

echo "-- lane-memory file lane appends to Findings when it is the last section, with no newline at the end"
python3 - "$F" <<'PY'
import re,sys; f=sys.argv[1]; t=open(f).read()
head=t.split("\n## ",1)[0]
open(f,"w").write(head+"\n## Goal\ng\n\n## Log\n- started\n\n## Findings\n- earlier finding")
PY
lm draft second "---
name: second
description: a second finding at the end
---
x" >/dev/null
lm file second lane L1 >/dev/null
assert_contains "appended to the Findings at the end of the file" "$(sed -n '/^## Findings$/,$p' "$F")" "a second finding at the end"
assert_contains "the earlier finding is kept" "$(cat "$F")" "earlier finding"

echo "-- lane brief and lane done read a section up to the next heading, whatever it is"
python3 - "$F" <<'PY'
import sys; f=sys.argv[1]; t=open(f).read()
head=t.split("\n## ",1)[0]
open(f,"w").write(head+"\n## Goal\nthe goal line\n\n## Context\nctx line\n\n## Resume note\nnote line\n\n## Findings\n- a finding line\n\n## Extra\n- not a finding\n\n## Log\n- started\n")
PY
lane brief L1
g=$(printf '%s\n' "$OUT" | sed -n '/^GOAL/,/^RESUME NOTE/p')
assert_contains "brief shows the goal" "$g" "the goal line"
assert_not_contains "brief's GOAL stops at the next heading" "$g" "ctx line"
fs=$(printf '%s\n' "$OUT" | sed -n '/^FINDINGS/,/^LOG/p')
assert_contains "brief shows the finding" "$fs" "a finding line"
assert_not_contains "brief's FINDINGS stops at the next heading" "$fs" "not a finding"

echo "-- lane merge --as keeps a section that comes after the Log"
lane start L2 api:l2; assert_eq "start L2" 0 "$RC"
F2="$PLANE/registry/lanes/L2.md"
printf '\n## Decisions\n- keep the old API\n' >> "$F2"
lane merge L1 L2 --as L3 --run
assert_eq "merge ran" 0 "$RC"
F3="$PLANE/registry/lanes/L3.md"
assert_contains "the merged lane has B's section after the Log" "$(cat "$F3" 2>/dev/null)" "keep the old API"
assert_contains "and A's finding" "$(cat "$F3" 2>/dev/null)" "a finding line"
assert_contains "and A's goal" "$(cat "$F3" 2>/dev/null)" "the goal line"
finish
