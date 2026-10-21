# Where everything is. Sourced (never run) by lane, scripts/lib.sh, scripts/init, scripts/statusline.sh and guard-check;
# scripts/roots.py is the same resolver for the Python side (guard.py, the board). The two must agree, and
# tests/t_workspace.sh checks that they do.
#
# Two roots:
#   PRODUCT  Repolane's own files: lane, scripts/, the hooks, templates/, VERSION. The caller sets it before sourcing.
#   AD       the workspace, the user's data. Decided here:
#              1. LANE_WORKSPACE, when set;
#              2. otherwise, when the product was named by LANE_PRODUCT (an installed package always is), the nearest
#                 folder at or above the start folder ($1, default the current one) that holds a .repolane/ folder;
#              3. otherwise the product folder itself: a git clone of Repolane, which is product and workspace at once.
#            A clone running its own files never looks around: whatever folder it is run from, it acts on itself.
#
# Two layouts, told apart by one thing, whether AD has a .repolane/ folder:
#   workspace  AD/CLAUDE.md (the user's), AD/.claude/, AD/lanes/ at the top; everything else Repolane keeps under
#              AD/.repolane/: REPOLANE.md, LANE.md, config.yml, env.sh, version, registry/, memory/, knowledge/, repos/,
#              cache/.
#   clone      today's layout: registry/ (config.yml inside it), memory/, knowledge/, repos/, .cache/, lanes/ and
#              scripts/env.sh, all at AD.
# Every script reads the data paths from the variables below and never builds them from AD itself.
lane_find_workspace(){ # lane_find_workspace <start-dir> : print the nearest folder at or above it with a .repolane/
  local d
  d=$(cd "$1" 2>/dev/null && pwd -P) || return 1
  while :; do
    [ -d "$d/.repolane" ] && { printf '%s\n' "$d"; return 0; }
    [ "$d" = / ] && return 1
    d=$(dirname "$d")
  done
}
lane_resolve_roots(){ # lane_resolve_roots [start-dir] : sets AD, LANE_MODE and every data path from PRODUCT
  local w
  if [ -n "${LANE_WORKSPACE:-}" ]; then AD="$LANE_WORKSPACE"
  elif [ -n "${LANE_PRODUCT:-}" ] && w=$(lane_find_workspace "${1:-.}"); then AD="$w"
  else AD="$PRODUCT"; fi
  LANES="$AD/lanes"
  if [ -d "$AD/.repolane" ]; then
    LANE_MODE=workspace; DATA="$AD/.repolane"
    CACHE_DIR="$DATA/cache"; CONFIG_FILE="$DATA/config.yml"; ENV_SH="$DATA/env.sh"
    # every script this one starts acts on the same workspace, whichever folder it is started from
    export LANE_WORKSPACE="$AD"
  else
    LANE_MODE=clone; DATA="$AD"
    CACHE_DIR="$AD/.cache"; CONFIG_FILE="$AD/registry/config.yml"; ENV_SH="$PRODUCT/scripts/env.sh"
  fi
  REGISTRY="$DATA/registry"; LANES_DIR="$REGISTRY/lanes"; REPOS="$DATA/repos"
  MEMORY_DIR="$DATA/memory"; KNOWLEDGE_DIR="$DATA/knowledge"
}

# ---------------------------------------------------------------- the workspace's own copy of the rules
# REPOLANE.md and LANE.md are the product's text, copied into the workspace so CLAUDE.md can import one and a hook can
# hand out the other. They are rewritten (and any data migration the version step needs is run) whenever the installed
# version differs from the one recorded in .repolane/version, or one of them is missing; nothing else in the workspace
# is ever overwritten. The check is here, cheap, on every `lane` run; the work is roots.py's `refresh`.
lane_refresh_workspace(){ # quiet; a refresh that cannot be done is retried on the next run, it never fails the caller
  [ "${LANE_MODE:-}" = workspace ] || return 0
  local have want
  want=$( (tr -d '[:space:]' < "$PRODUCT/VERSION") 2>/dev/null ); [ -n "$want" ] || want=unknown
  have=$( (tr -d '[:space:]' < "$DATA/version") 2>/dev/null )
  [ "$have" = "$want" ] && [ -f "$DATA/REPOLANE.md" ] && [ -f "$DATA/LANE.md" ] && return 0
  python3 -B "$PRODUCT/scripts/roots.py" refresh "$PRODUCT" "$AD" </dev/null >/dev/null 2>&1 || true
  return 0
}
# lane_make_workspace <dir> [owner] : an empty workspace layout in <dir>, filling only what is missing (roots.py)
lane_make_workspace(){ python3 -B "$PRODUCT/scripts/roots.py" make-workspace "$PRODUCT" "$@" </dev/null; }
