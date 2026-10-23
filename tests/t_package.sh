#!/usr/bin/env bash
# The Python package: the wheel carries every product file and none of the user's data, installs into a fresh venv, and the
# installed `lane` runs the bundled product (also after an installer dropped the scripts' +x bits). Needs uv or
# `python3 -m build`: skipped without one locally, required under CI. REPOLANE_WHEEL=<path> checks a wheel built
# elsewhere instead (publish.yml runs this against the exact wheel it uploads to PyPI).
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
new_sandbox
if [ -n "${REPOLANE_WHEEL:-}" ]; then
  case "$REPOLANE_WHEEL" in /*) ;; *) REPOLANE_WHEEL="$PWD/$REPOLANE_WHEEL" ;; esac
  [ -f "$REPOLANE_WHEEL" ] || { bad "REPOLANE_WHEEL names no file: $REPOLANE_WHEEL"; finish; exit 1; }
elif command -v uv >/dev/null 2>&1; then build(){ uv build --wheel -q -o "$1" "$PRODUCT"; }
elif python3 -c 'import build' >/dev/null 2>&1; then build(){ python3 -m build --wheel -o "$1" "$PRODUCT" >/dev/null; }
elif [ -n "${CI:-}" ]; then bad "a wheel builder (uv, or python3 -m build) is required under CI"; finish; exit 1
else echo "  skip  no uv and no python3 -m build here: the package test runs under CI"; ok "skipped (no wheel builder)"; finish; exit 0
fi

echo "-- build"
# from a copy, so the build never writes into the checkout (build/, *.egg-info) and sees only what is tracked or new
SRC="$T/src-tree"; mkdir -p "$SRC"; copy_product_tree "$SRC"
if [ -n "${REPOLANE_WHEEL:-}" ]; then
  mkdir -p "$T/dist"; cp "$REPOLANE_WHEEL" "$T/dist/"; ok "using the wheel in REPOLANE_WHEEL"
else
  PRODUCT="$SRC" build "$T/dist" >"$T/build.log" 2>&1; assert_eq "the wheel builds" 0 "$?"
fi
whl=$(ls "$T"/dist/repolane-*.whl 2>/dev/null | head -1)
assert "one wheel, named for VERSION" test "$(basename "$whl")" = "repolane-$(tr -d '[:space:]' < "$SRC/VERSION")-py3-none-any.whl"
names=$(python3 -c 'import sys,zipfile;print("\n".join(zipfile.ZipFile(sys.argv[1]).namelist()))' "$whl" 2>/dev/null)
P=repolane/_product
for f in repolane/__init__.py repolane/cli.py $P/lane $P/VERSION $P/LICENSE $P/NOTICE $P/CLAUDE.md.template \
         $P/scripts/lib.sh $P/scripts/init $P/scripts/env.sh $P/scripts/gitstate.sh $P/scripts/lane-start $P/scripts/session-start \
         $P/scripts/statusline.sh $P/scripts/lane-stable-dispatcher $P/scripts/lane-planes.py \
         $P/scripts/hooks/guard.py $P/scripts/hooks/guard-check $P/scripts/hooks/test-guard.sh \
         $P/scripts/board/server.py $P/scripts/board/index.html $P/scripts/board/board.js $P/scripts/board/board.css \
         $P/knowledge/preferences.md.example $P/.claude/settings.json $P/scripts/roots.sh $P/scripts/roots.py \
         $P/templates/REPOLANE.md $P/templates/LANE.md $P/templates/config.yml $P/templates/env.sh \
         $P/templates/claude/commands/status.md $P/templates/claude/commands/lane-start.md $P/templates/claude/agents/lane-manager.md; do
  assert_contains "wheel has $f" "$names" "$f"
done
# every script the dispatcher maps to must be in the wheel, or `lane <cmd>` dies on an installed copy
missing=""; cmds=$(sed -n 's/.*echo "\$S\/\([^|]*\)|.*/\1/p' "$SRC/lane" | sort -u)
assert "the dispatcher's command table was read" test "$(printf '%s\n' "$cmds" | wc -l)" -gt 20
for s in $cmds; do
  printf '%s\n' "$names" | grep -qxF "$P/scripts/$s" || missing="$missing $s"
done
assert_eq "wheel has every script a lane command runs" "" "$missing"
# a clone's own slash commands run bin/ by path, which a workspace has none of: the workspace's are templates/claude/
for x in tests/ docs/ .github/ registry/ memory/ repos/ lanes/ bin/ scripts/local/ scripts/release __pycache__ .git/ .claude/commands/ .claude/agents/; do
  assert_not_contains "wheel has no $x" "$names" "$P/$x"
done
assert_eq "knowledge/ carries only the template, no user notes" "$P/knowledge/preferences.md.example" "$(printf '%s\n' "$names" | grep "^$P/knowledge/")"

echo "-- install into a throwaway venv"
python3 -m venv "$T/venv" >/dev/null 2>&1; assert_eq "venv" 0 "$?"
"$T/venv/bin/python" -m pip install -q --no-index --disable-pip-version-check "$whl" >"$T/pip.log" 2>&1
assert_eq "pip installs the wheel, offline" 0 "$?"
out=$(cd "$T" && "$T/venv/bin/lane" --version 2>&1)
assert_eq "lane --version prints VERSION" "lane $(tr -d '[:space:]' < "$SRC/VERSION")" "$out"
inst=$("$T/venv/bin/python" -c 'import repolane.cli;print(repolane.cli.product_dir())')
assert_contains "lane help runs from the installed copy" "$(cd "$T" && "$T/venv/bin/lane" help 2>&1)" "lane"

for n in lane-memory lane-brief lane-status lane-run lane-gh lane-with lane-park guard-check; do
  assert "the long name $n is installed as a command" test -x "$T/venv/bin/$n"
done
out=$(cd "$T" && "$T/venv/bin/lane-memory" --help 2>&1)
assert_contains "lane-memory runs \`lane note\`" "$out" "lane note"

echo "-- the installed product still runs after an installer dropped the +x bits"
chmod -R a-x "$inst/scripts" "$inst/lane"; chmod -R u+X "$inst/scripts"   # directories stay enterable
WSX="$T/ws"; mkdir -p "$WSX/registry"; : > "$WSX/registry/repos.yaml"
out=$(cd "$T" && LANE_WORKSPACE="$WSX" "$T/venv/bin/lane" doctor 2>&1); rc=$?
assert_eq "lane doctor runs the bundled guard against a workspace" 0 "$rc"
assert_contains "and the guard answers its probes" "$out" "probes"
assert "the scripts got their +x back" test -x "$inst/scripts/hooks/guard-check"

finish
