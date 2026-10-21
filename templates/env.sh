# source this: shared caches so worktrees do not each grow their own. This file is yours: Repolane writes it once, when
# the workspace is made, and never again.
# WS_HOME is the workspace: LANE_WORKSPACE when set, otherwise the folder above the .repolane/ this file sits in.
export WS_HOME="${LANE_WORKSPACE:-$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)}"
# Only meaningful for Nx projects: keeps one shared cache instead of one per worktree.
# Harmless otherwise; delete these two lines if you do not use Nx.
export NX_CACHE_DIRECTORY="$WS_HOME/.repolane/cache/nx"
export NX_DAEMON=false
