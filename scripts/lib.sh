#!/usr/bin/env bash
# shared helpers for the lane-* scripts
set -euo pipefail
# Two roots. PRODUCT holds Repolane's own files (scripts/, the hooks, templates, VERSION, the board); AD is the
# workspace, the user's data. A clone of the repo is both at once, so by default they are one folder: the one this file
# sits in. LANE_PRODUCT and LANE_WORKSPACE point either one somewhere else (an installed package, a separate
# workspace folder). scripts/roots.sh decides AD and every data path (REGISTRY, LANES_DIR, REPOS, MEMORY_DIR,
# KNOWLEDGE_DIR, CACHE_DIR, CONFIG_FILE, ENV_SH, LANES) for both layouts, the workspace one and a clone's.
PRODUCT="${LANE_PRODUCT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
source "$PRODUCT/scripts/roots.sh"
lane_resolve_roots

# Who this control plane belongs to. One line in the config file; a neutral word if unset,
# so a fresh clone nobody has configured yet still reads sensibly.
lane_owner(){ sed -n 's/^[[:space:]]*name:[[:space:]]*//p' "$CONFIG_FILE" 2>/dev/null \
              | head -1 | tr -d '\042\047' ; }
OWNER="$(lane_owner)"; [ -n "$OWNER" ] || OWNER="the user"
# a workspace's env.sh is its own (lane_make_workspace writes one); one deleted by hand is simply not there
[ -f "$ENV_SH" ] && source "$ENV_SH"
die(){ echo "error: $*" >&2; exit 1; }
# A repo's integration branch comes from its definition in registry/repos.yaml, not from the
# remote: origin/HEAD goes stale (api still advertises master, the team uses develop).
# `compare_branch` overrides `default_branch` for repos where they differ. git is the last resort.
repo_default(){
  local b
  b=$(sed -n "/^  $1:\$/,/^  [a-z]/p" "$REGISTRY/repos.yaml" | sed -n 's/^    compare_branch: //p' | head -1)
  [ -n "$b" ] || b=$(sed -n "/^  $1:\$/,/^  [a-z]/p" "$REGISTRY/repos.yaml" | sed -n 's/^    default_branch: //p' | head -1)
  [ -n "$b" ] || b=$(git -C "$REPOS/$1" symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##')
  # a mirror copied from an existing checkout has no origin/HEAD — clone sets it, `remote add` does not
  [ -n "$b" ] || b=$(git -C "$REPOS/$1" symbolic-ref -q --short HEAD 2>/dev/null)
  [ -n "$b" ] || for c in main master develop; do
    git -C "$REPOS/$1" show-ref -q --verify "refs/remotes/origin/$c" && { b=$c; break; }
  done
  echo "$b"
}
repo_exists(){ [ -d "$REPOS/$1/.git" ] || die "unknown repo '$1' (see registry/repos.yaml)"; }
# Claude Code keeps per-project data under ~/.claude/projects/<the absolute path with every character
# that is not a letter, digit or dash turned into ->  (so "/.boardshot" is "--boardshot", and spaces and
# "_" go the same way; checked against the real folder names there). Every script that needs that folder
# uses this, so the slugging rule only lives in one place. scripts/gitstate.sh redefines it identically
# for the scripts that source that file instead.
claude_project_dir(){ printf '%s' "$1" | LC_ALL=C sed 's#[^A-Za-z0-9-]#-#g'; }
# lane_valid_id <id> : a lane id is a file name ([A-Za-z0-9._-]+, not "." or ".."), never a path.
# Byte-wise (LC_ALL=C) so it agrees with the board for non-ASCII input; the @ sentinel keeps
# $(...) from eating a trailing newline.
lane_valid_id(){
  case "$1" in ''|.|..) return 1 ;; esac
  [ "$(printf '%s@' "$1" | LC_ALL=C tr -d 'A-Za-z0-9._-')" = @ ]
}

# lane_file: an unchecked id would build "$LANES_DIR/$1.md" from whatever it is given, so
# `lane brief ../x` read registry/x.md. An invalid id maps to a path that cannot exist, which every
# caller already reports as "no lane".
lane_file(){ if lane_valid_id "$1"; then echo "$LANES_DIR/$1.md"; else echo "$LANES_DIR/.invalid-lane-id"; fi; }
# yaml-ish frontmatter reader: value of "key:" in the lane file
lane_get(){ sed -n '/^---$/,/^---$/p' "$(lane_file "$1")" | sed -n "s/^$2: *//p" | head -1; }
# list "repo branch" pairs from the lane frontmatter
lane_repos(){ sed -n '/^---$/,/^---$/p' "$(lane_file "$1")" | awk '/^  - repo:/{r=$3} /^    branch:/{print r, $2}'; }
# list "url label" pairs from the optional links: block. url first because a label has spaces and a
# url does not, so `read -r url label` puts the whole label in the last field.
lane_links(){ sed -n '/^---$/,/^---$/p' "$(lane_file "$1")" | awk '/^  - label:/{l=substr($0,12)} /^    url:/{print $2, l}'; }
# In-place edit that works on both seds: BSD needs `-i ''`, GNU rejects it. Writing through a
# temporary file sidesteps the difference entirely, and keeps the original if sed fails.
lane_set_status(){
  local f t; f="$(lane_file "$1")"; t="$f.tmp.$$"
  sed "s/^status: .*/status: $2/; s/^updated: .*/updated: $(date +%F)/" "$f" > "$t" && mv "$t" "$f" || { rm -f "$t"; return 1; }
}
# LANE_AGENT : the agent a workspace opted in to (`agent:` in config.yml), empty for Claude Code alone. What is said to a person
# follows it; Claude Code's files stay in place either way. A session's own hook says which agent it is (LANE_HOOK_AGENT).
LANE_AGENT=""; [ "$LANE_MODE" = workspace ] && LANE_AGENT=$(sed -n 's/^agent:[[:space:]]*//p' "$CONFIG_FILE" 2>/dev/null | head -1 || true)
# lane_agent <action> : the adapter, for what bash needs from the agent (the same thing as `lane agent <action>`)
lane_agent(){ python3 -B "$PRODUCT/scripts/agents/cli.py" ${LANE_AGENT:+--agent "$LANE_AGENT"} "$@"; }
# lane_can <capability> : Claude Code alone can do all of them, and needs no process to say so
lane_can(){ [ -z "$LANE_AGENT" ] || lane_agent has "$1"; }
# lane_launch : the command that starts a session here
lane_launch(){ if [ -z "$LANE_AGENT" ]; then echo claude; else lane_agent launch; fi; }
# lane_install <action> : the adapter's installers for a lane (scripts/agents/install.py), told where everything is
lane_install(){ local a="$1"; shift; python3 -B "$PRODUCT/scripts/agents/install.py" "$a" "$AD" "$PRODUCT" "$LANE_MODE" "$REPOS" "$LANES_DIR" "$MEMORY_DIR" "$KNOWLEDGE_DIR" "$CACHE_DIR" "$@"; }
# permission guard for a session rooted at $1: deny repos/ and every other lane
write_guard(){ # $1 = dir to write the agent's local settings in, $2 = this lane id, $3 = memory dir
  local dir="$1" id="$2" mem="$3" kept
  kept=$(lane_install lane "$dir" "$id" "$mem")
  # keep the guard out of git status in the worktree
  if [ -d "$dir/.git" ] || [ -f "$dir/.git" ]; then
    # --git-common-dir answers relatively inside a plain repo and absolutely inside a worktree;
    # resolve it against $dir so the append never lands in the caller's directory.
    local gd ex
    gd="$(git -C "$dir" rev-parse --git-common-dir 2>/dev/null)" || gd=""
    [ -n "$gd" ] || return 0
    case "$gd" in /*) : ;; *) gd="$dir/$gd" ;; esac
    mkdir -p "$gd/info" 2>/dev/null
    ex="$gd/info/exclude"
    local p; for p in $kept; do grep -qx "$p" "$ex" 2>/dev/null || echo "$p" >> "$ex"; done
  fi
}
# A lane folder sits inside the control plane, which is a git repo — so git would claim it and a session
# could not live there. An empty repo of its own stops git looking upward. Nothing is ever committed to it:
# everything in it is ignored, and the repos inside carry their own .git.
lane_anchor(){ # $1 = lane id
  local d="$LANES/$1"
  [ -d "$d" ] || return 0
  if [ ! -e "$d/.git" ]; then
    git init -q -b lane "$d" 2>/dev/null || git init -q "$d"
    git -C "$d" config core.hooksPath /dev/null 2>/dev/null || true
    git -C "$d" config lane.anchor true
  fi
  cat > "$d/.gitignore" <<'EOT'
# This folder is a lane, not a project.
# The empty git repo beside this file exists for one reason: without it git would walk up and decide
# this folder belongs to the control plane, and a session could not sit here. Nothing is committed to it.
# The real work lives in the repo worktrees next to this file, each with its own .git.
*
EOT
}

write_lane_claude(){ lane_install rules "$LANES/$1" "$(lane_file "$1")"; } # $1 = id
# env files are gitignored, so a fresh worktree has none. Link every env-like file of the mirror into the
# worktree at the same relative path (symlink: one source of truth, edit it in repos/<repo>). Never reads them.
link_env(){ # $1 = repo, $2 = worktree dir
  local repo="$1" wt="$2" n=0 f rel
  while IFS= read -r f; do
    rel="${f#$REPOS/$repo/}"
    case "$rel" in *.example|*.sample|*.template|*.from-clone-*) continue;; esac
    [ -e "$wt/$rel" ] && continue
    git -C "$wt" ls-files --error-unmatch "$rel" >/dev/null 2>&1 && continue   # tracked: git provides it
    mkdir -p "$wt/$(dirname "$rel")"; ln -s "$f" "$wt/$rel"; n=$((n+1))
  done < <(find "$REPOS/$repo" -maxdepth 4 \( -name node_modules -o -name .git -o -name .nx -o -name dist -o -name target -o -name .venv -o -name venv \) -prune -o -type f \( -name '.env' -o -name '.env.*' -o -name '*.env' \) -print 2>/dev/null)
  [ "$n" -gt 0 ] && echo "  linked $n env file(s) from repos/$repo into $wt"
  return 0
}
refresh_guards(){ # re-write guards in every lane so new siblings are denied everywhere
  for w in "$LANES"/*/; do [ -d "$w" ] || continue; local id; id=$(basename "$w")
    lane_anchor "$id"
    write_guard "$w" "$id" "$MEMORY_DIR"
    for r in "$w"*/; do [ -f "$r/.git" ] && write_guard "$r" "$id" "$MEMORY_DIR/$(basename "$r")"; done
  done
  write_additional_dirs
}
# Each session folder may reach the rest of its lane, and the root every lane (the adapter says how).
write_additional_dirs(){ lane_install folders; }
