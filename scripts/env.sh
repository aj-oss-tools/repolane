# source this: shared caches so worktrees do not each grow their own
# WS_HOME is the workspace (the caches are the user's data, not the product's): LANE_WORKSPACE when set, otherwise the
# folder this file sits in, which in a clone is both (scripts/lib.sh)
export WS_HOME="${LANE_WORKSPACE:-$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)}"
# Only meaningful for Nx projects: keeps one shared cache instead of one per worktree.
# Harmless otherwise; delete these two lines if you do not use Nx.
export NX_CACHE_DIRECTORY="$WS_HOME/.cache/nx"
export NX_DAEMON=false
