#!/usr/bin/env bash
# Items 20 (brief on a finished lane), 21 (park must not commit secrets; done on a local-only
# repo; done must not silently delete ignored secrets), 25 (done after a plain push).
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
new_sandbox; init_plane >/dev/null 2>&1
make_remote_repo api; make_remote_repo web; add_repo api; add_repo web
WT(){ echo "$PLANE/lanes/$1/$2"; }

echo "-- lane done after a plain 'git push origin <id>' (item 25)"
lane start L1 api web; assert_eq "start L1" 0 "$RC"
commit_in "$(WT L1 api)" a.txt one; commit_in "$(WT L1 web)" w.txt one
lane done L1 --keep-sessions
assert_eq "done refuses while nothing is pushed" 1 "$RC"
assert_contains "and says what is unpushed" "$OUT" "unpushed"
git -C "$(WT L1 api)" push -q origin L1 2>/dev/null
lane done L1 --keep-sessions
assert_eq "done still refuses while web is unpushed (all repos are checked)" 1 "$RC"
assert_contains "names web" "$OUT" "web"
assert "api worktree was not removed by the failed attempt" test -d "$(WT L1 api)"
git -C "$(WT L1 web)" push -q origin L1 2>/dev/null
lane done L1 --keep-sessions
assert_eq "done succeeds after plain pushes (no -u)" 0 "$RC"
assert_contains "done reports the archive" "$OUT" "done: L1"
assert "lane file archived" test -f "$PLANE/registry/lanes/done/L1.md"

echo "-- a commit made after the push is still caught"
lane start L2 api; commit_in "$(WT L2 api)" b.txt one; git -C "$(WT L2 api)" push -q origin L2
commit_in "$(WT L2 api)" b.txt two
lane done L2 --keep-sessions
assert_eq "one unpushed commit blocks" 1 "$RC"
assert_contains "count is reported" "$OUT" "1 unpushed"
git -C "$(WT L2 api)" push -q origin L2
lane done L2 --keep-sessions; assert_eq "pushed -> done" 0 "$RC"

echo "-- an empty lane (no commits) and push -u both still finish"
lane start L3 api web; lane done L3 --keep-sessions; assert_eq "empty lane finishes" 0 "$RC"
lane start L4 api; commit_in "$(WT L4 api)" c.txt one; git -C "$(WT L4 api)" push -q -u origin L4
lane done L4 --keep-sessions; assert_eq "push -u lane finishes" 0 "$RC"

echo "-- status / brief count unpushed against origin, not against the base"
lane start L5 api; commit_in "$(WT L5 api)" d.txt one
lane status
assert_contains "status shows 1 unpushed before the push" "$OUT" "api/L5: 0 dirty, 1 unpushed"
git -C "$(WT L5 api)" push -q origin L5
lane status
assert_contains "status shows 0 unpushed after a plain push" "$OUT" "api/L5: 0 dirty, 0 unpushed"
lane brief L5; assert_contains "brief shows unpushed: 0 after the push" "$OUT" "unpushed: 0"
lane done L5 --keep-sessions

echo "-- local-only repo (no origin), item 21"
make_local_repo solo; (cd "$PLANE" && ./lane add "$T/local/solo" solo </dev/null >/dev/null 2>&1)
assert "solo registered" test -d "$PLANE/repos/solo/.git"
lane start LS solo; assert_eq "start in a local-only repo" 0 "$RC"
commit_in "$(WT LS solo)" s.txt one
lane done LS --keep-sessions
assert_eq "done finishes a local-only repo" 0 "$RC"
assert_contains "and says plainly there is no origin to check" "$OUT" "no origin"
assert_not_contains "no misleading 'never pushed' failure" "$OUT" "never pushed"
assert "the branch survives in the mirror" git -C "$PLANE/repos/solo" rev-parse -q --verify refs/heads/LS
lane start LS2 solo; lane status
assert_not_contains "status does not call every local-only commit unpushed" "$OUT" "solo/LS2: 0 dirty, 1"

echo "-- lane brief on a finished lane (item 20)"
lane start L6 api; commit_in "$(WT L6 api)" e.txt one; git -C "$(WT L6 api)" push -q origin L6
mkdir -p "$PLANE/.cache/memory-inbox"; printf -- '---\nname: f1\ndescription: a finding about api\n---\nbody\n' > "$PLANE/.cache/memory-inbox/f1.md"
(cd "$PLANE" && ./scripts/lane-memory file f1 lane L6 </dev/null >/dev/null 2>&1)
lane done L6 --keep-sessions; assert_eq "L6 done" 0 "$RC"
lane brief L6
assert_eq "brief on a finished lane exits 0" 0 "$RC"
assert_not_contains "no sed errors" "$OUT" "sed:"
assert_not_contains "no 'No such file'" "$OUT" "No such file"
assert_contains "says it is archived" "$OUT" "finished lane"
assert_contains "lists the repo" "$OUT" "REPO api @ L6"
assert_contains "shows the finding from the archive" "$OUT" "a finding about api"
assert_contains "status reads done" "$OUT" "[done]"
lane brief NOPE; assert_eq "unknown lane still fails" 1 "$RC"
assert_contains "with the friendly message" "$OUT" "no lane 'NOPE'"
lane start L7 api; lane brief L7
assert_eq "brief on an active lane exits 0" 0 "$RC"
assert_contains "active lane shows its worktree" "$OUT" "worktree:"
lane done L7 --keep-sessions

echo "-- lane park never commits secrets (item 21)"
make_remote_repo leaky noignore
add_repo leaky
lane start P1 leaky; W="$(WT P1 leaky)"
mkdir -p "$W/config"
printf 'TOKEN=supersecret\n' > "$W/.env"
printf 'TOKEN=prod\n' > "$W/config/.env.production"
printf 'PEM\n' > "$W/server.pem"; printf 'K\n' > "$W/deploy.key"
printf '{"a":1}\n' > "$W/gcp-credentials.json"; printf 'x: 1\n' > "$W/secrets.yaml"
printf 'TOKEN=\n' > "$W/.env.example"
printf 'notes\n' > "$W/notes.txt"; printf 'changed\n' >> "$W/README.md"
lane park P1 "wip with secrets lying around in the tree"
assert_eq "park exits 0" 0 "$RC"
assert_contains "park says it committed" "$OUT" "wip commit in leaky"
files=$(git -C "$W" show --name-only --format= HEAD)
assert_contains "wip commit has the ordinary file" "$files" "notes.txt"
assert_contains "wip commit has the tracked edit" "$files" "README.md"
assert_contains "wip commit keeps .env.example (a template)" "$files" ".env.example"
for sec in .env config/.env.production server.pem deploy.key gcp-credentials.json secrets.yaml; do
  case "
$files
" in *"
$sec
"*) bad "wip commit must not contain $sec" ;; *) ok "wip commit does not contain $sec" ;; esac
done
assert "the secret stayed on disk" test "$(cat "$W/.env")" = "TOKEN=supersecret"
assert_contains "park tells the user what it left out" "$OUT" ".env"
assert_eq "the secrets are still untracked, not lost" "?? .env" "$(git -C "$W" status --porcelain | grep -F ' .env' | grep -v example | grep -v production | head -1)"
assert "the lane is parked" grep -q '^status: parked' "$PLANE/registry/lanes/P1.md"
echo "-- park: a secret that is already staged is refused before any commit"
printf 'more\n' >> "$W/notes.txt"; git -C "$W" add -f .env
head_before=$(git -C "$W" rev-parse HEAD)
lane park P1 "second park attempt with a staged secret"
assert_eq "park refuses with a staged secret" 1 "$RC"
assert_eq "and made no commit" "$head_before" "$(git -C "$W" rev-parse HEAD)"
git -C "$W" reset -q -- .env
echo "-- park when ONLY secrets changed: nothing is staged, nothing is committed"
lane start P3 leaky; W3="$(WT P3 leaky)"; printf 'S=1\n' > "$W3/.env"; printf 'K\n' > "$W3/a.pem"
h3=$(git -C "$W3" rev-parse HEAD)
lane park P3 "only secrets are dirty in this tree"
assert_eq "park exits 0" 0 "$RC"
assert_eq "no commit was made" "$h3" "$(git -C "$W3" rev-parse HEAD)"
assert_eq "nothing is staged" "" "$(git -C "$W3" diff --cached --name-only)"
assert_contains "it says what it left out" "$OUT" "a.pem"
echo "-- park on a clean lane and on ordinary files still works"
lane start P2 api; commit_in "$(WT P2 api)" ok.txt x; printf 'dirty\n' > "$(WT P2 api)/plain.txt"
lane park P2 "ordinary park with plain files ok"
assert_eq "ordinary park exits 0" 0 "$RC"
assert_contains "ordinary park commits" "$OUT" "wip commit in api"
assert_contains "parked" "$OUT" "parked P2"
lane park P2 "park again when nothing is dirty here"
assert_not_contains "clean tree: no wip commit" "$OUT" "wip commit"
lane park P2 "short"; assert_eq "short note still refused" 1 "$RC"

echo "-- lane done does not silently delete an ignored secret (item 21)"
lane start D1 api; WD="$(WT D1 api)"
printf 'SECRET=1\n' > "$WD/.env"            # ignored by the repo's .gitignore, a real file, not a link
git -C "$WD" push -q origin D1 2>/dev/null
lane done D1 --keep-sessions
assert_eq "done refuses when an ignored secret would be deleted" 1 "$RC"
assert_contains "and names it" "$OUT" ".env"
assert "worktree and secret are still there" test -f "$WD/.env"
lane done D1 --keep-sessions --discard-ignored
assert_eq "--discard-ignored lets it through" 0 "$RC"
assert "worktree removed" test ! -d "$WD"
# an env file that is a link (what lane start makes from the mirror) never blocks
printf 'LINKED=1\n' > "$PLANE/repos/api/.env"
lane start D2 api
assert "lane start linked the mirror's .env" test -L "$(WT D2 api)/.env"
lane done D2 --keep-sessions; assert_eq "a linked .env does not block done" 0 "$RC"
assert "the mirror's .env is untouched" test -f "$PLANE/repos/api/.env"
# ordinary ignored build output does not block either
lane start D3 api; mkdir -p "$(WT D3 api)/node_modules/x"; printf 'x\n' > "$(WT D3 api)/node_modules/x/i.js"
printf 'node_modules/\n' >> "$PLANE/repos/api/.git/info/exclude"
lane done D3 --keep-sessions; assert_eq "ignored non-secret output does not block done" 0 "$RC"

echo "-- item 27: done on a parked lane with the secrets park left out (no circular dead end)"
lane start Q1 api; WQ="$(WT Q1 api)"
commit_in "$WQ" q.txt one
printf 'S=1\n' > "$WQ/.env.local"; printf 'K\n' > "$WQ/id_rsa"; printf 'work\n' > "$WQ/plain.txt"
lane park Q1 "parked with untracked secrets left out"; assert_eq "park Q1" 0 "$RC"
git -C "$WQ" push -q origin Q1 2>/dev/null
lane status
assert_contains "status does not count the left-out secrets as dirty" "$OUT" "api/Q1: 0 dirty"
lane done Q1 --keep-sessions
assert_eq "done refuses until the secrets are dealt with" 1 "$RC"
assert_contains "refusal names .env.local" "$OUT" ".env.local"
assert_contains "refusal names id_rsa" "$OUT" "id_rsa"
assert_contains "refusal names the exact flag" "$OUT" "--discard-ignored"
assert_not_contains "never the circular 'is dirty' message" "$OUT" "is dirty"
assert_not_contains "never says lane park first" "$OUT" "lane park first"
assert_contains "says they are still on disk" "$OUT" "still on disk"
assert "nothing was removed" test -f "$WQ/id_rsa"
lane done Q1 --keep-sessions --discard-ignored
assert_eq "--discard-ignored finishes the parked lane" 0 "$RC"
assert_contains "and reports what is deleted with the worktree" "$OUT" "deleted with the worktree"
assert "worktree removed" test ! -d "$WQ"
echo "-- item 27: tracked-dirty work still blocks done, flag or not"
lane start Q2 api; WQ2="$(WT Q2 api)"; git -C "$WQ2" push -q origin Q2 2>/dev/null
printf 'S=1\n' > "$WQ2/.env.local"; printf 'edit\n' >> "$WQ2/README.md" 2>/dev/null || printf 'x\n' > "$WQ2/tracked_new.txt"
git -C "$WQ2" add -A -- . ':!.env.local'; printf 'more\n' > "$WQ2/untracked_plain.txt"
lane done Q2 --keep-sessions --discard-ignored
assert_eq "dirty tracked/plain files block even with --discard-ignored" 1 "$RC"
assert_contains "and say dirty" "$OUT" "is dirty"
assert "worktree kept" test -d "$WQ2"
echo "-- item 33: untracked secrets are not dirty work in lane brief / session-start / status-all"
lane start Q3 api; WQ3="$(WT Q3 api)"; printf 'S=1\n' > "$WQ3/.env.local"
lane brief Q3; assert_contains "brief: 0 dirty" "$OUT" "dirty: 0"
lane status; assert_contains "status: 0 dirty" "$OUT" "api/Q3: 0 dirty"
OUT=$(cd "$PLANE" && printf '{"source":"startup","session_id":"s1","cwd":"%s"}' "$PLANE" | LANE_PLAIN=1 ./scripts/session-start 2>&1)
assert_contains "session-start dispatcher: 0 dirty" "$OUT" "api/Q3 (0 dirty"
printf 'w\n' > "$WQ3/plain2.txt"
lane status; assert_contains "status counts real untracked work" "$OUT" "api/Q3: 1 dirty"
lane done Q3 --keep-sessions --discard-ignored >/dev/null 2>&1; lane done Q2 --keep-sessions >/dev/null 2>&1 || true

finish
