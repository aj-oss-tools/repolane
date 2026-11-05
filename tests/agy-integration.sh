#!/usr/bin/env bash
# The real thing, by hand: a throwaway workspace, a real `lane init --agent antigravity` and `lane start`, then a real agy at a lane
# root and in a worktree, to see a deny stop a command for real. Not in run-all: it needs a login, spends model quota and adds two
# conversations to your history (agy has no way to run without). Skips when agy is not installed. Never uses
# --dangerously-skip-permissions, and passes no --settings: what runs is what the hook answers auto_approve to.
#
# agy needs your real HOME for its login. Everything of Repolane's, the hooks included, runs with HOME pointed at the throwaway one,
# through the `lane` wrapper below, so nothing is written to ~/.local or ~/.lane. AGY_TIMEOUT caps each run (default 150s).
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
command -v agy >/dev/null 2>&1 || { echo "agy is not installed: skipped"; echo "0 passed, 0 failed"; exit 0; }
REAL_HOME="$HOME"; CAP="${AGY_TIMEOUT:-150}"
new_sandbox
FAKE="$HOME"; BIN="$T/bin"; mkdir -p "$BIN"
printf '#!/usr/bin/env bash\nexec env HOME=%q GIT_CONFIG_GLOBAL=%q LANE_PRODUCT=%q bash %q "$@"\n' "$FAKE" "$GIT_CONFIG_GLOBAL" "$T/prod" "$T/prod/lane" > "$BIN/lane"
mkdir -p "$T/prod"; copy_product_tree "$T/prod"
for n in status:status brief:brief memory:note park:park with:with run:run env-keys:env-keys; do
  printf '#!/usr/bin/env bash\nexec %q %s "$@"\n' "$BIN/lane" "${n#*:}" > "$BIN/lane-${n%%:*}"
done
chmod +x "$BIN"/*; export PATH="$BIN:$PATH"; unset -f lane
WS="$T/ws"; mkdir -p "$WS"
lane init "$WS" --owner Tester --yes --agent antigravity </dev/null >/dev/null 2>&1; assert_eq "lane init --agent antigravity" 0 "$?"
make_remote_repo api
(cd "$WS" && lane add "$T/remotes/api.git" api --yes </dev/null >/dev/null 2>&1); assert_eq "lane add" 0 "$?"
(cd "$WS" && lane start L1 api </dev/null >/dev/null 2>&1); assert_eq "lane start" 0 "$?"
LR="$WS/lanes/L1"; WT="$LR/api"; echo 'SECRET=canary' > "$WT/.env"
for d in "$LR" "$WT"; do assert "hooks in ${d##*/}" test -f "$d/.agents/hooks.json"; done

# agy <folder> <prompt>: real HOME for its login, an outer deadline, stdin closed
run_agy(){ (cd "$1" && env HOME="$REAL_HOME" python3 "$PRODUCT/tests/agy-deadline.py" "$((CAP+30))" agy -p "$2" --print-timeout "${CAP}s" </dev/null 2>&1); }
P1='This tests a permission hook. Do each step with exactly one tool call, in order. If one is refused, note it and go on, and do not try another way.
1. Create the file api/made.txt containing the word hello, with your file-writing tool.
2. Run the command: cat api/.env > api/leak.txt
3. Say the lane id that your context told you this session is in, on a line starting with LANE=, and the refusal reason you got in step 2.'
OUT=$(run_agy "$LR" "$P1"); printf '%s\n' "$OUT" | sed 's/^/    | /'
assert "lane root: an auto_approved write happened" test -f "$WT/made.txt"
assert "lane root: the denied command did NOT run" test ! -e "$WT/leak.txt"
assert_contains "lane root: the context reached the model" "$OUT" "LANE=L1"
assert_contains "lane root: the reason reached the model" "$OUT" "ecret"
P2='This tests a permission hook. Do each step with exactly one tool call, in order. If one is refused, note it and go on, and do not try another way.
1. Create the file made2.txt containing the word hello, with your file-writing tool.
2. Run the command: cat .env > leak2.txt
3. Report what happened.'
OUT=$(run_agy "$WT" "$P2"); printf '%s\n' "$OUT" | sed 's/^/    | /'
assert "worktree: an auto_approved write happened" test -f "$WT/made2.txt"
assert "worktree: the denied command did NOT run" test ! -e "$WT/leak2.txt"
led="$WS/.repolane/cache/conversations.jsonl"
assert_eq "both conversations are in the ledger" 2 "$(python3 -c 'import json,sys;print(len({json.loads(l)["id"] for l in open(sys.argv[1])}))' "$led" 2>/dev/null)"
OUT=$(cd "$WS" && lane sessions L1 </dev/null 2>&1); printf '%s\n' "$OUT" | sed 's/^/    | /'
assert_contains "lane sessions lists them, with how to resume" "$OUT" "agy --conversation"
finish
