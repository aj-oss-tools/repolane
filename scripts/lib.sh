#!/usr/bin/env bash
# shared helpers for the lane-* scripts
set -euo pipefail
AD="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Who this control plane belongs to. One line in registry/config.yml; a neutral word if unset,
# so a fresh clone nobody has configured yet still reads sensibly.
lane_owner(){ sed -n 's/^[[:space:]]*name:[[:space:]]*//p' "$AD/registry/config.yml" 2>/dev/null \
              | head -1 | tr -d '\042\047' ; }
OWNER="$(lane_owner)"; [ -n "$OWNER" ] || OWNER="the user"
source "$AD/scripts/env.sh"
LANES_DIR="$AD/registry/lanes"; LANES="$AD/lanes"; REPOS="$AD/repos"
die(){ echo "error: $*" >&2; exit 1; }
# A repo's integration branch comes from its definition in registry/repos.yaml, not from the
# remote: origin/HEAD goes stale (api still advertises master, the team uses develop).
# `compare_branch` overrides `default_branch` for repos where they differ. git is the last resort.
repo_default(){
  local b
  b=$(sed -n "/^  $1:\$/,/^  [a-z]/p" "$AD/registry/repos.yaml" | sed -n 's/^    compare_branch: //p' | head -1)
  [ -n "$b" ] || b=$(sed -n "/^  $1:\$/,/^  [a-z]/p" "$AD/registry/repos.yaml" | sed -n 's/^    default_branch: //p' | head -1)
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
# permission guard for a session rooted at $1: deny repos/ and every other lane
write_guard(){ # $1 = dir to write .claude/settings.local.json in, $2 = this lane id, $3 = memory dir
  local dir="$1" id="$2" mem="$3"; mkdir -p "$dir/.claude"
  python3 - "$dir" "$id" "$mem" "$AD" <<'PY'
import json,os,sys
d,id_,mem,ad=sys.argv[1:]
deny=[f"Read({ad}/repos/**)",f"Edit({ad}/repos/**)"]  # Edit covers Write/MultiEdit; Write() rules are ignored
for pat in ("**/.env","**/.env.local","**/.env.*.local","**/.env.development","**/.env.production","**/.env.staging","**/.env.test","**/*.pem","**/*.key",
            "**/*.p12","**/*.pfx","**/*.p8","**/*.jks","**/*.keystore","**/*.kdbx","**/id_rsa","**/id_ed25519","**/id_ecdsa","**/id_dsa",
            "**/.netrc","**/.npmrc","**/.pgpass","**/.git-credentials","**/.htpasswd","**/service-account*.json"):   # the same names guard.py's SECRET_FILE knows
    deny+=[f"Read({pat})",f"Edit({pat})"]
for o in sorted(os.listdir(f"{ad}/lanes")):
    if o!=id_ and os.path.isdir(f"{ad}/lanes/{o}"):
        deny+=[f"Read({ad}/lanes/{o}/**)",f"Edit({ad}/lanes/{o}/**)"]
p=f"{d}/.claude/settings.local.json"
cur=json.load(open(p)) if os.path.exists(p) else {}
perm=cur.setdefault("permissions",{})
keep=[x for x in perm.get("deny",[]) if f"{ad}/repos/" not in x and f"{ad}/lanes/" not in x]
seen=set(); perm["deny"]=[x for x in keep+deny if not (x in seen or seen.add(x))]   # order kept, never repeated
# Pre-approved means "runs without asking", so it is only for commands that read. lane-memory (file/rm/move write and delete
# markdown) and lane-workspace (rewrites the .code-workspace files) are NOT here; the read-only lane-memory verbs are.
READONLY_LANE=["lane-merge-plan","lane-status","lane-brief","lane-find","lane-menu","lane-sessions","lane-env-check","lane-env-keys",
               "lane-memory list","lane-memory show","lane-memory audit"]
OWN_WRITES=["lane-memory goal","lane-memory draft"]   # write this lane's Goal / a draft in the inbox, nothing else
RETIRED=("Bash(lane-memory:*)","Bash(lane-workspace:*)")   # earlier versions approved these; a refresh has to take that back
# A session in this lane records its Goal and Findings in registry/lanes/<id>.md, which sits in the control plane root,
# outside the lane's folder; Claude Code refuses a path outside the session's folder unless a rule allows it (the guard
# already does). Allow exactly this lane's file, nothing else under registry/. A leading // is an absolute path in a rule;
# a single / is relative to the project and would match nothing.
lf="/"+ad+"/registry/lanes/"+id_+".md"
# Reads of what the rules tell a session to open: memory/, knowledge/ and the draft inbox. Claude Code's Read rule also
# covers Glob and Grep, so a session can search them too. Writes there are NOT allowed here: a session that entered a worktree
# cannot use Edit/Write outside that folder at all (no setting lifts it), so they go through `lane-memory draft <slug> -` and
# `lane-memory goal`, which write only this lane's file and the inbox and run without asking.
OWN=(f"Read({lf})",f"Edit({lf})")+tuple(f"Read(/{ad}/{x}/**)" for x in ("memory","knowledge",".cache/memory-inbox"))
own_prefix=("Read(/"+ad+"/registry/lanes/","Edit(/"+ad+"/registry/lanes/")   # an earlier lane's rule, or one for another id, is dropped
perm["allow"]=sorted({x for x in perm.get("allow",[]) if x not in RETIRED and not x.startswith(own_prefix)}
                     |{f"Bash({c}:*)" for c in READONLY_LANE+OWN_WRITES}|set(OWN))
cur["autoMemoryDirectory"]=mem
g=f"{ad}/scripts/hooks/guard.py"
hk=lambda m=None,to=30:[{**({"matcher":m} if m else {}),"hooks":[{"type":"command","command":g,"timeout":to}]}]
cur["hooks"]={"SessionStart":[{"matcher":"startup|resume|clear|compact|fork","hooks":[{"type":"command","command":f"{ad}/scripts/session-start --worktree","timeout":60}]}],
  "PreToolUse":hk("Bash|Edit|Write|MultiEdit|NotebookEdit|Read|EnterWorktree|Glob|Grep"),"PostToolUse":hk("Edit|Write|MultiEdit|NotebookEdit"),
  "WorktreeCreate":hk(None,120),"WorktreeRemove":hk(),
  "UserPromptSubmit":hk(),"PreCompact":hk(),"SessionEnd":hk()}
json.dump(cur,open(p,"w"),indent=2)
PY
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
    grep -qx '.claude/settings.local.json' "$ex" 2>/dev/null || echo '.claude/settings.local.json' >> "$ex"
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

write_lane_claude(){ # $1 = id
  cat > "$LANES/$1/CLAUDE.md" <<EOT
# Lane: $1
Spec and state: \`$(lane_file "$1")\` — read it first. Repos in scope are its \`repos:\` list; nothing else.
Per-repo memory: \`$AD/memory/<repo>/MEMORY.md\`. Preferences: \`$AD/knowledge/preferences.md\`.
EOT
}
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
    write_guard "$w" "$id" "$AD/memory"
    for r in "$w"*/; do [ -f "$r/.git" ] && write_guard "$r" "$id" "$AD/memory/$(basename "$r")"; done
  done
  write_additional_dirs
}
# Claude Code only edits inside the session's folder plus "additionalDirectories". A dispatcher session enters one
# repo of a lane, so the sibling repos must be listed. Root local settings: every worktree (hook still denies
# other lanes). Each worktree's local settings: its siblings.
write_additional_dirs(){
  python3 - "$AD" <<'PY'
import json,os,glob
ad=sys.argv[1] if False else __import__("sys").argv[1]
wts=sorted(p for p in glob.glob(f"{ad}/lanes/*/*") if os.path.exists(f"{p}/.git"))
import re
def refs_of(lane):
    f=f"{ad}/registry/lanes/{lane}.md"
    if not os.path.exists(f): return []
    head=open(f).read().split("\n---\n",1)[0]
    return [m.group(1) for m in re.finditer(r"^  - path: (.+)$",head,re.M)]
def put(path,dirs):
    cur=json.load(open(path)) if os.path.exists(path) else {}
    cur.setdefault("permissions",{})["additionalDirectories"]=dirs
    os.makedirs(os.path.dirname(path),exist_ok=True); json.dump(cur,open(path,"w"),indent=2)
allrefs=sorted({r for w in set(os.path.dirname(x) for x in wts) for r in refs_of(os.path.basename(w))})
put(f"{ad}/.claude/settings.local.json",wts+allrefs)
for w in wts:
    lane=os.path.dirname(w); put(f"{w}/.claude/settings.local.json",[s for s in wts if os.path.dirname(s)==lane and s!=w]+refs_of(os.path.basename(lane)))
for lane in set(os.path.dirname(x) for x in wts):
    p=f"{lane}/.claude/settings.local.json"
    if os.path.exists(p): put(p,[s for s in wts if os.path.dirname(s)==lane]+refs_of(os.path.basename(lane)))
put_root=f"{ad}/.claude/settings.local.json"
PY
}
