#!/usr/bin/env bash
# Shared helpers for the tests/ suite. Source this; never run it.
# Every case runs against a throwaway copy of the product under a throwaway HOME, with bare git
# repos in the temp dir as remotes. Nothing here touches the real ~/.lane, ~/.claude, the real
# repos/ folder or the network. Bash 3.2 + git + python3 only.

PRODUCT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PASS=0; FAIL=0; FAILED_NAMES=""
SANDBOXES=""

# a realpath under the system temp dir, no symlinked prefix
mk_tmp(){ local d; d=$(mktemp -d "${TMPDIR:-/tmp}/lane-test.XXXXXX") && (cd "$d" && pwd -P); }

cleanup_all(){ local d; for d in $SANDBOXES; do rm -rf "$d"; done; }
trap cleanup_all EXIT

# check <name> <expected-rc> <cmd...> : pass when rc matches
ok(){ PASS=$((PASS+1)); printf '  ok    %s\n' "$1"; }
bad(){ FAIL=$((FAIL+1)); FAILED_NAMES="$FAILED_NAMES
    $1"; printf '  FAIL  %s\n' "$1"; [ -n "${2:-}" ] && printf '%s\n' "$2" | sed 's/^/        /'; return 0; }
assert(){ # assert <name> <command...>  (command succeeds)
  local name="$1"; shift
  if "$@" >/dev/null 2>&1; then ok "$name"; else bad "$name"; fi
}
assert_eq(){ # assert_eq <name> <expected> <actual>
  if [ "$2" = "$3" ]; then ok "$1"; else bad "$1" "expected: [$2]
actual:   [$3]"; fi
}
assert_contains(){ # <name> <haystack> <needle>
  case "$2" in *"$3"*) ok "$1" ;; *) bad "$1" "missing: [$3]
in: $(printf '%s' "$2" | head -c 600)" ;; esac
}
assert_not_contains(){
  case "$2" in *"$3"*) bad "$1" "unexpected: [$3]
in: $(printf '%s' "$2" | head -c 600)" ;; *) ok "$1" ;; esac
}

# every sandbox plane is both roots by its own location (scripts/lib.sh); a caller's overrides must not reach it
unset LANE_PRODUCT LANE_WORKSPACE

# git identity and no host config leaking in
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.com GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.com
export GIT_CONFIG_NOSYSTEM=1 GIT_TERMINAL_PROMPT=0

# copy_product_tree <dir> : the product as tracked in git plus new unignored files, with working-tree contents (so
# uncommitted fixes are tested); per-machine files (registry/repos.yaml, *.local.json, repos/, lanes/) are deliberately
# absent. A checkout that is itself a control plane (the developer ran `lane init` in it) carries its own init state,
# and a copy must start un-initialized or every "before init" case is wrong: drop the files init creates, and put the
# files init edits back to what is committed.
copy_product_tree(){
  local dest="$1" f
  (cd "$PRODUCT" && git ls-files -z --cached --others --exclude-standard | tar -cf - --null -T - 2>/dev/null) | (cd "$dest" && tar -xf - 2>/dev/null)
  (cd "$PRODUCT" && git ls-files --others --exclude-standard -- CLAUDE.md knowledge memory) | while IFS= read -r f; do rm -rf "$dest/$f"; done
  for f in registry/config.yml .gitignore .claude/settings.json; do
    git -C "$PRODUCT" cat-file -e "HEAD:$f" 2>/dev/null && git -C "$PRODUCT" show "HEAD:$f" > "$dest/$f"
  done
}

# new_sandbox : sets T (temp root), HOME (throwaway), PLANE (copy of the product, a git repo),
# and ORIGIN (bare repo the plane was cloned from). Everything lives under T.
new_sandbox(){
  T=$(mk_tmp); SANDBOXES="$SANDBOXES $T"
  export HOME="$T/home"; mkdir -p "$HOME"
  export GIT_CONFIG_GLOBAL="$HOME/.gitconfig"; : > "$GIT_CONFIG_GLOBAL"
  git config --global init.defaultBranch main
  git config --global protocol.file.allow always
  unset CLAUDE_HOME CLAUDE_PROJECT_DIR
  local seed="$T/seed"; mkdir -p "$seed"
  copy_product_tree "$seed"
  mkdir -p "$seed/repos" "$seed/lanes"
  # the tests dir itself is not needed inside the plane
  (cd "$seed" && git init -q -b main && git add -A && git commit -q -m seed)
  ORIGIN="$T/origin.git"; git clone -q --bare "$seed" "$ORIGIN"
  PLANE="$T/${PLANE_DIR_NAME:-plane}"; git clone -q "$ORIGIN" "$PLANE"
  # the plane must never be able to push anywhere real
  git -C "$PLANE" config user.name t; git -C "$PLANE" config user.email t@example.com
  mkdir -p "$PLANE/repos" "$PLANE/lanes" "$PLANE/.cache"
}

# install_product : the product installed the way a user gets it, into the sandbox: a wheel built from a copy of this
# checkout and pip-installed into a venv when a builder (uv, or python3 -m build) is here; otherwise the checkout copy run
# through LANE_PRODUCT, exactly as the package's launcher runs it. Sets PROD (the installed product files) and BIN (the
# folder holding `lane` and the long names); the caller puts BIN on PATH. Under CI a builder is required.
install_product(){
  SRC="$T/src-tree"; mkdir -p "$SRC"; copy_product_tree "$SRC"
  if command -v uv >/dev/null 2>&1; then build(){ uv build --wheel -q -o "$1" "$SRC"; }
  elif python3 -c 'import build' >/dev/null 2>&1; then build(){ python3 -m build --wheel -o "$1" "$SRC" >/dev/null; }
  else build(){ return 1; }; fi
  if build "$T/dist" >"$T/build.log" 2>&1 && python3 -m venv "$T/venv" >/dev/null 2>&1 \
     && "$T/venv/bin/python" -m pip install -q --no-compile --no-index --disable-pip-version-check "$T"/dist/repolane-*.whl >"$T/pip.log" 2>&1; then
    BIN="$T/venv/bin"; PROD=$("$BIN/python" -c 'import repolane.cli as c;print(c.product_dir())')
    echo "  (the product is an installed wheel: $PROD)"
  else
    [ -n "${CI:-}" ] && { bad "a wheel builder is required under CI"; finish; exit 1; }
    # what the package's launcher does: run the product's own `lane` with LANE_PRODUCT naming it
    PROD="$SRC"; BIN="$T/bin"; mkdir -p "$BIN"
    printf '#!/usr/bin/env bash\nexec env LANE_PRODUCT=%q bash %q "$@"\n' "$PROD" "$PROD/lane" > "$BIN/lane"
    for n in lane-memory:note lane-brief:brief lane-status:status lane-park:park lane-with:with lane-run:run; do
      printf '#!/usr/bin/env bash\nexec %q %s "$@"\n' "$BIN/lane" "${n#*:}" > "$BIN/${n%%:*}"
    done
    chmod +x "$BIN"/*
    echo "  (no wheel builder here: the product is the checkout copy at $PROD, run through LANE_PRODUCT)"
  fi
}

# init_plane [flags] : run lane init non-interactively against the sandbox
init_plane(){ (cd "$PLANE" && ./lane init --owner "Test" --yes --claude-home "$T/claude" "$@" </dev/null); }

# make_remote_repo <name> [noignore] : bare remote with one commit on main, a seed checkout in
# $T/src/<name>. By default .env is gitignored; "noignore" leaves a repo that ignores nothing.
make_remote_repo(){
  local n="$1" src="$T/src/$1"
  mkdir -p "$src"; git init -q -b main "$src"
  printf 'hello %s\n' "$n" > "$src/README.md"
  if [ "${2:-}" = noignore ]; then : > "$src/.gitignore"; else printf '.env\n' > "$src/.gitignore"; fi
  git -C "$src" add -A; git -C "$src" commit -q -m init
  git clone -q --bare "$src" "$T/remotes/$n.git" 2>/dev/null || { mkdir -p "$T/remotes"; git clone -q --bare "$src" "$T/remotes/$n.git"; }
  git -C "$src" remote add origin "$T/remotes/$n.git"; git -C "$src" fetch -q origin
  git -C "$src" branch -q -u origin/main main
}

# add_repo <name> : register that remote with the plane
add_repo(){ (cd "$PLANE" && ./lane add "$T/remotes/$1.git" "$1" </dev/null >/dev/null 2>&1); }

# lane <args...> : run the sandbox plane's dispatcher; stdout+stderr merged into $OUT, rc into $RC
lane(){ OUT=$(cd "$PLANE" && ./lane "$@" </dev/null 2>&1); RC=$?; }

finish(){
  echo
  echo "$PASS passed, $FAIL failed"
  [ "$FAIL" = 0 ] || { printf 'failed:%s\n' "$FAILED_NAMES"; return 1; }
  return 0
}

# commit_in <dir> <file> <content> : write a file in a worktree and commit it
commit_in(){ printf '%s\n' "$3" > "$1/$2"; git -C "$1" add "$2"; git -C "$1" commit -q -m "edit $2"; }

# make_local_repo <name> : a checkout with NO origin remote, at $T/local/<name>
make_local_repo(){
  local d="$T/local/$1"; mkdir -p "$d"; git init -q -b main "$d"
  printf 'local %s\n' "$1" > "$d/README.md"; git -C "$d" add -A; git -C "$d" commit -q -m init
}

# pty_run <timeout-seconds> <answer> <cmd...> : run a command with a real terminal on stdin/stderr,
# answering "<answer>" + Enter every time it prints a "[y/N]" prompt. Output in stdout, rc as status.
pty_run(){
  python3 - "$@" <<'PY'
import os, pty, select, sys, time
to, ans, cmd = float(sys.argv[1]), (sys.argv[2] + "\n").encode(), sys.argv[3:]
pid, fd = pty.fork()
if pid == 0:
    os.execvp(cmd[0], cmd)
out, seen, t0 = b"", 0, time.time()
while True:
    r, _, _ = select.select([fd], [], [], 0.3)
    if r:
        try: d = os.read(fd, 4096)
        except OSError: break
        if not d: break
        out += d
        n = out.count(b"[y/N]") + out.count(b"[Y/n]")
        while seen < n: os.write(fd, ans); seen += 1
    if time.time() - t0 > to:
        os.kill(pid, 9); out += b"\n[pty_run: timed out]\n"; break
_, st = os.waitpid(pid, 0)
sys.stdout.write(out.decode(errors="replace"))
sys.exit(os.WEXITSTATUS(st) if os.WIFEXITED(st) else 1)
PY
}
