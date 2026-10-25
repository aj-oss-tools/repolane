#!/usr/bin/env bash
# Smoke test for lane-board: starts the real server.py on a free port against a throwaway plane
# (a copy of scripts/ and bin/ with one lane in it, under a throwaway HOME), checks every endpoint,
# then runs the regression suite. Every check is an assertion: any failure makes this script exit 1.
src="$(cd "$(dirname "$0")/../.." && pwd)"
unset LANE_PRODUCT LANE_WORKSPACE   # the throwaway plane is both roots, by its own location
tmp=$(mktemp -d "${TMPDIR:-/tmp}/board-smoke.XXXXXX") || exit 1
log="$tmp/board.log"; BP=""
cleanup(){ [ -z "$BP" ] || kill "$BP" 2>/dev/null; rm -rf "$tmp"; }
trap cleanup EXIT
fails=0
check(){ # check <name> <command...> : the command must succeed
  local n="$1"; shift
  if "$@" >/dev/null 2>&1; then echo "  ok    $n"; else echo "  FAIL  $n"; fails=$((fails+1)); fi
}
J(){ python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if ($1) else 1)"; }

plane="$tmp/plane"; export HOME="$tmp/home"; mkdir -p "$HOME" "$plane/registry/lanes" "$plane/repos/web" "$plane/memory" "$plane/knowledge" "$plane/.cache/memory-inbox"
cp -R "$src/scripts" "$plane/scripts"; cp -R "$src/bin" "$plane/bin"; rm -rf "$plane/scripts/__pycache__"
printf 'repos:\n  web:\n    short: web\n    default_branch: main\n' > "$plane/registry/repos.yaml"
printf 'owner:\n  name: smoke\n' > "$plane/registry/config.yml"
printf -- '---\nstatus: active\nticket: T-1\nupdated: 2026-01-01\nrepos:\n  - repo: web\n    branch: l1\n    base: main\n---\n\n## Goal\nsmoke\n' > "$plane/registry/lanes/SMOKE.md"
wt="$plane/lanes/SMOKE/web"; mkdir -p "$wt"
export GIT_CONFIG_GLOBAL="$HOME/.gitconfig" GIT_CONFIG_SYSTEM=/dev/null
git -C "$wt" init -q -b l1; git -C "$wt" config user.email s@example.com; git -C "$wt" config user.name s
printf 'hi\n' > "$wt/a.txt"; git -C "$wt" add -A; git -C "$wt" commit -q -m init
printf 'changed\n' >> "$wt/a.txt"; printf 'TOP=SECRET\n' > "$wt/.env"

PORT=$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1])')
WS_BOARD_NO_OPEN=1 WS_BOARD_PORT=$PORT python3 "$plane/scripts/board/server.py" > "$log" 2>&1 & BP=$!
URL="http://127.0.0.1:$PORT/"
for _ in $(seq 1 60); do curl -s -o /dev/null "$URL" && break; sleep 0.2; done
TOK=$(curl -s "$URL" | grep -o "__T='[^']*'" | cut -d"'" -f2)
echo "server: $URL"
check "token was served" test -n "$TOK"
H="X-Token: $TOK"
get(){ curl -s -H "$H" "$URL$1"; }

check "no token -> 403" test "$(curl -s -o /dev/null -w '%{http_code}' "${URL}api/board")" = 403
check "/api/board lists the lane" bash -c "curl -s -H '$H' '${URL}api/board' | python3 -c \"import json,sys; d=json.load(sys.stdin); sys.exit(0 if any(w['id']=='SMOKE' for w in d['lanes']) else 1)\""
R="api/lanes/SMOKE/repos/web"
get "$R" > "$tmp/repo.json"
check "/api/lanes/SMOKE/repos/web returns the changed files" J "any(f['file']=='a.txt' for f in d['files'])" < "$tmp/repo.json"
check "the repo resource marks .env secret" J "any(f['file']=='.env' and f['secret'] for f in d['files'])" < "$tmp/repo.json"
get "$R/diff?file=a.txt" > "$tmp/diff.json"
check "its diff shows the change" J "'+changed' in d['diff']" < "$tmp/diff.json"
get "$R/diff?file=.env" > "$tmp/env.json"
check "secret diff is withheld" J "d.get('secret') is True and d['diff']==''" < "$tmp/env.json"
check "secret value never appears" bash -c "! grep -q SECRET '$tmp/env.json' '$tmp/repo.json'"
check "/api/lanes/SMOKE/spec returns the lane" bash -c "curl -s -H '$H' '${URL}api/lanes/SMOKE/spec' | python3 -c \"import json,sys; sys.exit(0 if 'smoke' in json.load(sys.stdin)['spec'] else 1)\""
check "/api/sessions answers" J "isinstance(d.get('sessions'), dict)" < <(get "api/sessions")
check "fonts are served from the board itself" test "$(curl -s -o /dev/null -w '%{http_code} %{content_type}' "${URL}fonts/inter-var.woff2")" = "200 font/woff2"
check "only the bundled fonts are served" test "$(curl -s -o /dev/null -w '%{http_code}' "${URL}fonts/OFL.txt")" = 404
check "the page asks nothing of another host" bash -c "! curl -s '$URL' '${URL}board.css' | grep -Eq 'https?://[^\"]*(fonts\.|googleapis|gstatic|cdn)'"
check "path-like lane id is refused" test "$(curl -s -o /dev/null -w '%{http_code}' -H "$H" "${URL}api/lanes/..%2F..%2Fx/brief")" = 400
check "mirror path is refused" test "$(curl -s -o /dev/null -w '%{http_code}' -H "$H" "${URL}api/lanes/..%2Frepos/repos/web")" = 400
check "commit with nothing staged is refused" test "$(curl -s -o /dev/null -w '%{http_code}' -H "$H" -X POST -d '{"message":"x"}' "${URL}$R/commit")" = 400
check "unknown lane action is refused" test "$(curl -s -o /dev/null -w '%{http_code}' -H "$H" -X POST -d '{}' "${URL}api/lanes/SMOKE/nuke")" = 404
check "staging .env is refused" test "$(curl -s -o /dev/null -w '%{http_code}' -H "$H" -X POST -d '{"files":[".env"]}' "${URL}$R/stage")" = 400
check "a deep link serves the page" bash -c "curl -s '${URL}lanes/SMOKE/web/history?repos=all' | grep -q __T="
check "a commit deep link serves the page" test "$(curl -s -o /dev/null -w '%{http_code}' "${URL}lanes/SMOKE/web/commits/abc1234")" = 200
check "an unknown page is a 404" test "$(curl -s -o /dev/null -w '%{http_code}' "${URL}lanes/SMOKE/web/nope")" = 404
check "the old query endpoints are gone" test "$(curl -s -o /dev/null -w '%{http_code}' -H "$H" "${URL}api/repo?lane=SMOKE&repo=web")" = 404
check "the server is still running" kill -0 "$BP"

echo "--- regression suite (scratch plane, throwaway HOME) ---"
python3 -W ignore "$src/scripts/board/test_board.py" || fails=$((fails+1))
if [ "$fails" -gt 0 ]; then echo "smoke: $fails check(s) FAILED"; exit 1; fi
echo "done: all smoke checks passed"
