#!/usr/bin/env bash
# `lane upgrade` for the package install, and the whole road from a 0.9.2 clone to an upgraded workspace.
#
# Two wheels are built from this checkout, one as 0.10.0 and one as 0.10.1, and installed into a throwaway venv. Fake
# pipx / uv on PATH record how they are called, and "upgrade" by pip-installing the second wheel into that venv (so the
# new version really runs the refresh). Covered: the installer detection (pipx, uv tool, plain pip); two registered
# workspaces with stale rule files refreshed with every byte of the owner's data unchanged; a registered folder that is
# gone (reported, the others still refreshed, the exit code, --drop-missing); a broken settings.json; an unregistered
# workspace registered from inside; --check against a stubbed PyPI answer and offline; a clone upgraded onto 0.10 by the
# released 0.9.2 upgrader and by this one, which prints the pipx + migrate steps and keeps working; then the full chain:
# 0.9.2 install -> its own lane upgrade -> the wheel -> lane migrate --yes -> lane doctor -> lane upgrade to 0.10.1.
# Throwaway HOME and temp dirs only; nothing real is installed or upgraded.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
TAG=v0.9.2
new_sandbox
CLEAN_PATH=$(printf '%s' "$PATH" | tr ':' '\n' | while IFS= read -r d; do [ -n "$d" ] && [ ! -e "$d/lane" ] && printf '%s:' "$d"; done)
CLEAN_PATH="${CLEAN_PATH%:}"
PLANES="$HOME/.local/share/lane/planes.json"
V1=0.10.0; V2=0.10.1

# the two wheels: this checkout's files, VERSION set
if command -v uv >/dev/null 2>&1; then build(){ uv build --wheel -q -o "$2" "$1"; }
elif python3 -c 'import build' >/dev/null 2>&1; then build(){ python3 -m build --wheel -o "$2" "$1" >/dev/null; }
else build(){ return 1; }; fi
for v in $V1 $V2; do mkdir -p "$T/src-$v"; copy_product_tree "$T/src-$v"; printf '%s\n' "$v" > "$T/src-$v/VERSION"; done
if ! { build "$T/src-$V1" "$T/dist1" && build "$T/src-$V2" "$T/dist2"; } >"$T/build.log" 2>&1; then
  if [ -n "${CI:-}" ]; then bad "a wheel builder is required under CI" "$(tail -5 "$T/build.log")"; else echo "  skip  no wheel builder here"; fi
  finish; exit
fi
W1=$(ls "$T"/dist1/repolane-*.whl); W2=$(ls "$T"/dist2/repolane-*.whl)
VENV="$T/venv"
python3 -m venv "$VENV" >/dev/null 2>&1 && "$VENV/bin/python" -m pip install -q --no-compile --no-index --disable-pip-version-check "$W1" >"$T/pip.log" 2>&1
assert_eq "the $V1 wheel is installed in a venv" 0 "$?"
BIN="$VENV/bin"
reinstall_v1(){ "$VENV/bin/python" -m pip install -q --no-compile --no-index --disable-pip-version-check --force-reinstall --no-deps "$W1" >>"$T/pip.log" 2>&1; }

# fake pipx and uv: record the call; `pipx upgrade repolane` / `uv tool upgrade repolane` install $UPGRADE_WHEEL
SHIMS="$T/shims"; mkdir -p "$SHIMS"; CALLS="$T/calls.log"; : > "$CALLS"
for tool in pipx uv; do
  cat > "$SHIMS/$tool" <<EOT
#!/usr/bin/env bash
echo "$tool \$*" >> "$CALLS"
[ "\${FAKE_RC:-0}" = 0 ] || { echo "$tool: fake failure" >&2; exit "\$FAKE_RC"; }
case "\$*" in "upgrade repolane"|"tool upgrade repolane")
  [ -n "\${UPGRADE_WHEEL:-}" ] && "$VENV/bin/python" -m pip install -q --no-compile --no-index --disable-pip-version-check --no-deps --upgrade "\$UPGRADE_WHEEL" >/dev/null 2>&1
  echo "upgraded package repolane" ;;
esac
EOT
  chmod +x "$SHIMS/$tool"
done
export PATH="$BIN:$SHIMS:$CLEAN_PATH"
assert_eq "lane on PATH is the venv's" "$BIN/lane" "$(type -P lane)"
mark(){ rm -f "$VENV/pipx_metadata.json" "$VENV/uv-receipt.toml"; case "$1" in pipx) echo '{}' > "$VENV/pipx_metadata.json" ;; uv) : > "$VENV/uv-receipt.toml" ;; esac; }

L(){ local d="$1"; shift; OUT=$(cd "$d" && env -u LANE_WORKSPACE -u LANE_PRODUCT lane "$@" </dev/null 2>&1); RC=$?; }
ws_list(){ python3 -c 'import json,sys; print("\n".join(sorted(json.load(open(sys.argv[1])).get("workspaces",{}))))' "$PLANES"; }
# every file the owner's data is in: registry, memory, knowledge, config, env.sh, CLAUDE.md, the settings' own keys
user_sum(){ (cd "$1" && find .repolane/registry .repolane/memory .repolane/knowledge .repolane/config.yml .repolane/env.sh CLAUDE.md notes.txt -type f 2>/dev/null \
             | LC_ALL=C sort | xargs cksum; python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));d.pop("hooks",None);print(json.dumps(d,sort_keys=True))' .claude/settings.json); }
PROD=$("$BIN/python" -c 'import repolane.cli as c;print(c.product_dir())')

echo "-- two registered workspaces with stale rule files"
make_remote_repo web
WS1="$T/ws one"; WS2="$T/ws2"; mkdir -p "$WS1" "$WS2"
L "$WS1" init --owner Test --yes; assert_eq "init ws one" 0 "$RC"
L "$WS2" init --owner Test --yes; assert_eq "init ws2" 0 "$RC"
L "$WS1" add "$T/remotes/web.git" web; assert_eq "lane add in ws one" 0 "$RC"
L "$WS1" start L1 web; assert_eq "lane start L1" 0 "$RC"
OUT=$(cd "$WS1/lanes/L1" && env -u LANE_WORKSPACE -u LANE_PRODUCT lane-memory goal "the goal before the upgrade" 2>&1); assert_eq "a Goal from inside the lane" 0 "$?"
for w in "$WS1" "$WS2"; do
  printf '\n## Mine\nmy own line\n' >> "$w/CLAUDE.md"; printf 'mine\n' > "$w/notes.txt"; printf 'a note\n' > "$w/.repolane/memory/mine.md"
  printf 'old rules\n' > "$w/.repolane/REPOLANE.md"; printf 'old lane text\n' > "$w/.repolane/LANE.md"; printf '0.9.9\n' > "$w/.repolane/version"
  python3 - "$w/.claude/settings.json" <<'PY'
import json, sys
p = sys.argv[1]; d = json.load(open(p)); d["env"] = {"MY_KEY": "kept"}; d["hooks"].pop("PreCompact", None); json.dump(d, open(p, "w"), indent=2)
PY
done
LS="$WS1/lanes/L1/web/.claude/settings.local.json"
python3 - "$LS" <<'PY'
import json, sys
p = sys.argv[1]; d = json.load(open(p)); d.pop("hooks"); d["myLocalKey"] = 1; json.dump(d, open(p, "w"), indent=2)
PY
S1=$(user_sum "$WS1"); S2=$(user_sum "$WS2")
assert_eq "both are registered" "$T/ws one
$WS2" "$(ws_list)"

echo "-- --check: a newer release on PyPI, the same one, and offline (changes nothing)"
mark pipx
printf '{"info":{"version":"%s"}}' "$V2" > "$T/pypi.json"
BEFORE_CHECK=$(user_sum "$WS1"; cat "$WS1/.repolane/version" "$WS1/.repolane/REPOLANE.md"; cat "$CALLS")
OUT=$(cd "$WS1" && env -u LANE_WORKSPACE LANE_PYPI_URL="file://$T/pypi.json" lane upgrade --check </dev/null 2>&1); RC=$?
assert_eq "--check exits 0" 0 "$RC"
assert_contains "it shows the installed version and how" "$OUT" "Installed: Repolane $V1 (pipx install)"
assert_contains "and the newer one on PyPI" "$OUT" "Latest:    $V2 on PyPI: lane upgrade takes it"
assert_contains "and the workspaces that are behind" "$OUT" "2 registered, 2 not yet refreshed for $V1"
printf '{"info":{"version":"%s"}}' "$V1" > "$T/pypi.json"
OUT=$(cd "$WS1" && env -u LANE_WORKSPACE LANE_PYPI_URL="file://$T/pypi.json" lane upgrade --check </dev/null 2>&1)
assert_contains "the same version: up to date" "$OUT" "Latest:    $V1 on PyPI: up to date"
OUT=$(cd "$WS1" && env -u LANE_WORKSPACE LANE_PYPI_URL="http://127.0.0.1:9/pypi/repolane/json" lane upgrade --check </dev/null 2>&1); RC=$?
assert_eq "--check offline exits 1" 1 "$RC"
assert_contains "and says it could not reach PyPI" "$OUT" "could not reach PyPI"
assert_contains "and that nothing was changed" "$OUT" "Nothing was changed"
assert_not_contains "no traceback" "$OUT" "Traceback"
assert_eq "--check changed nothing and ran no installer" "$BEFORE_CHECK" "$(user_sum "$WS1"; cat "$WS1/.repolane/version" "$WS1/.repolane/REPOLANE.md"; cat "$CALLS")"

echo "-- lane upgrade (pipx): the package, then both workspaces"
OUT=$(cd "$T" && env -u LANE_WORKSPACE UPGRADE_WHEEL="$W2" lane upgrade </dev/null 2>&1); RC=$?
assert_eq "lane upgrade exits 0" 0 "$RC"
[ "$RC" = 0 ] || printf '%s\n' "$OUT" | sed 's/^/        /'
assert_eq "it ran pipx upgrade repolane" "pipx upgrade repolane" "$(cat "$CALLS")"
assert_eq "the package is now $V2" "lane $V2" "$("$BIN/lane" --version)"
assert_contains "it says so" "$OUT" "Repolane is now $V2 (was $V1)"
assert_contains "it reports ws one" "$OUT" "ws one: rule files rewritten for $V2 (was 0.9.9)"
assert_contains "it reports ws2" "$OUT" "ws2: rule files rewritten for $V2 (was 0.9.9)"
for w in "$WS1" "$WS2"; do
  n=${w#$T/}
  assert_eq "$n: version recorded" "$V2" "$(cat "$w/.repolane/version")"
  assert "$n: REPOLANE.md is $V2's" cmp -s "$w/.repolane/REPOLANE.md" "$PROD/templates/REPOLANE.md"
  assert "$n: LANE.md is $V2's" cmp -s "$w/.repolane/LANE.md" "$PROD/templates/LANE.md"
  assert_contains "$n: the missing hook is back in settings.json" "$(cat "$w/.claude/settings.json")" "lane hook pre-compact"
done
assert_eq "ws one: the owner's data is byte for byte the same" "$S1" "$(user_sum "$WS1")"
assert_eq "ws2: the owner's data is byte for byte the same" "$S2" "$(user_sum "$WS2")"
assert_contains "the lane's settings.local.json runs the hooks again" "$(cat "$LS")" "lane hook pre-tool-use"
assert_contains "and keeps the owner's own key" "$(cat "$LS")" '"myLocalKey": 1'
L "$WS1" doctor; assert_eq "lane doctor in ws one exits 0 afterwards" 0 "$RC"
L "$WS2" doctor; assert_eq "lane doctor in ws2 exits 0 afterwards" 0 "$RC"
L "$T" upgrade --refresh-only; assert_eq "again: exit 0" 0 "$RC"
assert_contains "and nothing to rewrite" "$OUT" "ws one: rule files already $V2's"

echo "-- uv tool and plain pip installs"
reinstall_v1; : > "$CALLS"; mark uv
OUT=$(cd "$T" && env -u LANE_WORKSPACE UPGRADE_WHEEL="$W2" lane upgrade </dev/null 2>&1); RC=$?
assert_eq "uv tool: exit 0" 0 "$RC"
assert_eq "uv tool: it ran uv tool upgrade repolane" "uv tool upgrade repolane" "$(cat "$CALLS")"
assert_eq "uv tool: the package is $V2" "lane $V2" "$("$BIN/lane" --version)"
reinstall_v1; : > "$CALLS"; mark pip
L "$T" upgrade; assert_eq "plain pip: exit 0" 0 "$RC"
assert_contains "plain pip: it prints the pip command" "$OUT" "$VENV/bin/python -m pip install --upgrade repolane"
assert_eq "plain pip: no installer was run" "" "$(cat "$CALLS")"
assert_contains "plain pip: the workspaces are still refreshed with the installed version" "$OUT" "ws one: rule files rewritten for $V1"
reinstall_v1; : > "$CALLS"; mark pipx
OUT=$(cd "$T" && env -u LANE_WORKSPACE FAKE_RC=3 lane upgrade </dev/null 2>&1); RC=$?
assert_eq "pipx fails: exit 1" 1 "$RC"
assert_contains "it says pipx failed" "$OUT" "\`pipx upgrade repolane\` failed (exit 3)"

echo "-- a registered folder that is gone, and a broken settings.json"
mark pipx
WS3="$T/ws3"; mkdir -p "$WS3"; L "$WS3" init --owner Test --yes; rm -rf "$WS3"
for w in "$WS1" "$WS2"; do printf '0.9.9\n' > "$w/.repolane/version"; done
L "$T" upgrade --refresh-only; assert_eq "a missing folder: exit 1" 1 "$RC"
assert_contains "it is reported" "$OUT" "ws3: the folder is gone: skipped"
assert_contains "the others are still refreshed" "$OUT" "ws2: rule files rewritten for $V1"
assert_eq "ws one is refreshed" "$V1" "$(cat "$WS1/.repolane/version")"
assert_contains "it says how to drop it" "$OUT" "--drop-missing"
assert_contains "ws3 is still registered" "$(ws_list)" "$WS3"
L "$T" upgrade --refresh-only --drop-missing; assert_eq "--drop-missing: exit 0" 0 "$RC"
assert_not_contains "ws3 is dropped from the registry" "$(ws_list)" "$WS3"
printf '{ broken' > "$WS2/.claude/settings.json"; printf '0.9.9\n' > "$WS1/.repolane/version"
L "$T" upgrade --refresh-only; assert_eq "a broken settings.json: exit 1" 1 "$RC"
assert_contains "it is reported" "$OUT" "ws2: not refreshed: .claude/settings.json is not valid JSON"
assert_eq "the broken file is left as it was" "{ broken" "$(cat "$WS2/.claude/settings.json")"
assert_eq "ws one is still refreshed" "$V1" "$(cat "$WS1/.repolane/version")"
rm -rf "$WS2"; L "$T" upgrade --refresh-only --drop-missing

echo "-- run inside a workspace that is not registered"
python3 - "$PLANES" <<'PY'
import json, sys
p = sys.argv[1]; d = json.load(open(p)); d["workspaces"] = {}; json.dump(d, open(p, "w"))
PY
L "$WS1/lanes/L1" upgrade --refresh-only; assert_eq "exit 0" 0 "$RC"
assert_contains "it registers it" "$OUT" "registered $T/ws one"
assert_eq "planes.json has it" "$T/ws one" "$(ws_list)"
L "$T" upgrade --bogus; assert_eq "an unknown option: exit 2" 2 "$RC"

echo "-- a $TAG clone, upgraded onto 0.10 by its own lane upgrade, then by this one"
if ! git -C "$PRODUCT" rev-parse -q --verify "$TAG^{commit}" >/dev/null 2>&1; then
  if [ -n "${CI:-}" ]; then bad "the $TAG tag is here (checkout with fetch-depth: 0)"; else echo "  skip  no $TAG tag in this checkout"; fi
  finish; exit
fi
reinstall_v1
base_sha=$(git -C "$PRODUCT" rev-parse "$TAG^{commit}")
CAND="$T/cand"
git clone -q --no-hardlinks "$PRODUCT" "$CAND" 2>/dev/null
git -C "$CAND" checkout -q --detach "$base_sha"
git -C "$CAND" rm -rq --ignore-unmatch . 2>/dev/null
copy_product_tree "$CAND"; printf '%s\n' "$V1" > "$CAND/VERSION"
git -C "$CAND" add -A && git -C "$CAND" commit -q -m "candidate $V1"
REMOTE="$T/remote.git"; git init -q --bare "$REMOTE"
git -C "$CAND" push -q "$REMOTE" "$base_sha:refs/heads/main"
OLD="$T/old"; git clone -q "$REMOTE" "$OLD"
O(){ OUT=$(cd "$OLD" && env -u LANE_PRODUCT -u LANE_WORKSPACE PATH="$CLEAN_PATH" ./lane "$@" </dev/null 2>&1); RC=$?; }
mkdir -p "$OLD/repos" "$OLD/lanes" "$OLD/.cache"
O init --owner Test --yes; assert_eq "$TAG lane init" 0 "$RC"
O add "$T/remotes/web.git" web; assert_eq "$TAG lane add" 0 "$RC"
O start L1 web; assert_eq "$TAG lane start L1" 0 "$RC"
OUT=$(cd "$OLD/lanes/L1" && env -u LANE_PRODUCT -u LANE_WORKSPACE PATH="$CLEAN_PATH" "$OLD/scripts/lane-memory" goal "ship the login page" 2>&1)
assert_eq "$TAG: a Goal from inside the lane" 0 "$?"
OUT=$(cd "$OLD" && env -u LANE_PRODUCT -u LANE_WORKSPACE PATH="$CLEAN_PATH" ./scripts/lane-memory draft web-builds "web builds with make" 2>&1 \
      && env -u LANE_PRODUCT -u LANE_WORKSPACE PATH="$CLEAN_PATH" ./scripts/lane-memory file web-builds repo web 2>&1)
assert_eq "$TAG: a memory filed for web" 0 "$?"
git -C "$CAND" push -q "$REMOTE" "HEAD:refs/heads/main"
O upgrade; assert_eq "$TAG's own lane upgrade onto $V1 exits 0" 0 "$RC"
[ "$RC" = 0 ] || printf '%s\n' "$OUT" | sed 's/^/        /'
assert_eq "the clone is at $V1" "$V1" "$(cat "$OLD/VERSION")"
assert_contains "the next steps name pipx install" "$OUT" "1. pipx install repolane"
assert_contains "and lane migrate of this folder" "$OUT" "2. lane migrate $OLD"
O doctor; assert_eq "the clone still works: lane doctor exits 0" 0 "$RC"
assert_contains "and doctor says the same steps" "$OUT" "lane migrate $OLD"
O status; assert_eq "lane status works" 0 "$RC"
# this branch's own clone upgrader, onto a later 0.10
w="$T/pub"; git clone -q "$REMOTE" "$w"; printf '0.10.9\n' > "$w/VERSION"; git -C "$w" commit -qam "0.10.9"; git -C "$w" push -q origin HEAD:main
O upgrade; assert_eq "this lane upgrade in a clone onto 0.10.9 exits 0" 0 "$RC"
assert_contains "it prints the steps too" "$OUT" "1. pipx install repolane"
assert_eq "the clone is at 0.10.9" "0.10.9" "$(cat "$OLD/VERSION")"
git -C "$OLD" reset -q --hard "HEAD~1"   # back to the $V1 candidate, which the installed wheel matches

echo "-- the chain: the wheel, lane migrate --yes, lane doctor, lane upgrade to $V2"
OUT=$(cd "$OLD" && env -u LANE_WORKSPACE -u LANE_PRODUCT lane migrate --yes </dev/null 2>&1); RC=$?
assert_eq "lane migrate --yes" 0 "$RC"
[ "$RC" = 0 ] || printf '%s\n' "$OUT" | tail -20 | sed 's/^/        /'
assert_contains "the workspace is registered" "$(ws_list)" "$OLD"
L "$OLD" doctor; assert_eq "lane doctor exits 0 after the migration" 0 "$RC"
[ "$RC" = 0 ] || printf '%s\n' "$OUT" | grep '!!' | sed 's/^/        /'
GOAL_SUM=$(cksum < "$OLD/.repolane/registry/lanes/L1.md"); MEM_SUM=$(cd "$OLD/.repolane/memory" && find . -type f | LC_ALL=C sort | xargs cksum)
: > "$CALLS"; mark pipx
OUT=$(cd "$OLD" && env -u LANE_WORKSPACE -u LANE_PRODUCT UPGRADE_WHEEL="$W2" lane upgrade </dev/null 2>&1); RC=$?
assert_eq "lane upgrade to $V2 exits 0" 0 "$RC"
[ "$RC" = 0 ] || printf '%s\n' "$OUT" | sed 's/^/        /'
assert_eq "via pipx" "pipx upgrade repolane" "$(cat "$CALLS")"
assert_contains "the migrated workspace is refreshed" "$OUT" "old: rule files rewritten for $V2 (was $V1)"
assert_eq "its version is recorded" "$V2" "$(cat "$OLD/.repolane/version")"
assert_eq "the lane file (Goal) is intact" "$GOAL_SUM" "$(cksum < "$OLD/.repolane/registry/lanes/L1.md")"
assert_eq "every memory file is intact" "$MEM_SUM" "$(cd "$OLD/.repolane/memory" && find . -type f | LC_ALL=C sort | xargs cksum)"
L "$OLD" doctor; assert_eq "lane doctor exits 0 after the upgrade" 0 "$RC"
OUT=$(cd "$OLD/lanes/L1" && env -u LANE_WORKSPACE -u LANE_PRODUCT lane-memory goal "ship the login page, then signup" 2>&1)
assert_eq "lane-memory goal from inside the lane after the upgrade" 0 "$?"
assert_contains "the Goal is saved" "$(sed -n '/^## Goal/,/^## /p' "$OLD/.repolane/registry/lanes/L1.md")" "then signup"

finish
