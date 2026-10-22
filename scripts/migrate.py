#!/usr/bin/env python3
"""`lane migrate`: turn a git-clone install of Repolane (a 0.9.x control plane) into a workspace, in place.

  lane migrate [<folder>] [--yes] [--dry-run] [--git] [--claude-home <dir>] [--verbose]
      <folder>        the clone install (default: the current folder)
      --dry-run       show what would change, change nothing
      --yes           ask nothing: migrate, and accept the changes under ~/.claude and ~/.local/bin
      --git           make the workspace a fresh git repo afterwards (the clone's own .git is Repolane's, never kept)
      --claude-home   Claude Code's folder (default ~/.claude, or CLAUDE_HOME)
      --verbose       list every file in the preview, not one line per folder
  lane migrate --undo <backup.tar.gz> [--yes]
      put the clone install back exactly as the backup holds it (what was written in the workspace since is kept aside)

It always shows the whole plan first and changes nothing until you confirm ("Migrate now? [y/N]", or --yes). With no
terminal to ask and no --yes it only shows the plan. Before the first change it writes a backup of everything it will
change or remove to ~/.local/share/lane/backups/<folder>-<time>.tar.gz and prints its path; `lane migrate --undo
<that file>` restores from it.

What happens, in order (each step is recorded in .repolane/migrating.json, so an interrupted run continues where it
stopped when started again):
  data       registry/, memory/, knowledge/, repos/, .cache/ (as cache/), registry/config.yml, scripts/env.sh and
             scripts/local/ move under .repolane/; the lane worktrees under lanes/ stay where they are and are repaired
             (git worktree repair) so git in them keeps working, and their .env links follow the mirrors
  product    Repolane's own files are removed: exactly the paths a release shipped (scripts/migrate-manifest.json, made
             from the release trees); anything else in the folder is yours and stays
  git        the folder's .git is the Repolane repo's, so it goes (it is in the backup); --git starts a fresh one
  CLAUDE.md  the generated one becomes yours: a short file that imports .repolane/REPOLANE.md, plus every line you
             added to it; if lines of Repolane's text were edited, the old file is also kept as CLAUDE.md.pre-0.10
  settings   .claude/settings.json runs `lane hook …` commands (your own keys and hooks are kept); every lane's
             settings.local.json is written again
  outside    ~/.claude/projects/*/memory links point at .repolane/memory (asked first); ~/.local/bin/lane, the old
             router `lane install` wrote, is removed when no other clone uses it (asked first); planes.json records the
             workspace instead of the clone
"""
import datetime
import difflib
import hashlib
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import roots  # noqa: E402
import workspace as ws  # noqa: E402
from workspace import say, tilde, can_ask, ask, G, Y, R, D, B, N  # noqa: E402

PRODUCT = ws.PRODUCT
STATE = ".repolane/migrating.json"
DONE_MARK = ".repolane/migrated.json"

# (from, to) relative to the folder, in the order they are moved. registry/config.yml leaves registry/ before it moves.
MOVES = [("registry/config.yml", ".repolane/config.yml"), ("registry", ".repolane/registry"), ("memory", ".repolane/memory"),
         ("knowledge", ".repolane/knowledge"), ("repos", ".repolane/repos"), (".cache", ".repolane/cache"),
         ("scripts/local", ".repolane/scripts/local"), ("scripts/env.sh", ".repolane/env.sh")]
# paths a release ships that are the user's data, not product files to remove: handled by the moves and the rewrites
DATA_TOPS = ("registry/", "memory/", "knowledge/", "scripts/local/")
DATA_FILES = {"scripts/env.sh", ".claude/settings.json", "registry/config.yml"}
# what the old layout called things, under the folder: a path into one of these is a path the move changed
OLD_DATA = ("repos", "registry", "memory", "knowledge", ".cache", "scripts", "bin")
JUNK = {".DS_Store", "__pycache__"}
STUB = '#!/usr/bin/env bash\nexec "$(command -v lane)" {} "$@"\n'
LONGFORM = {"lane-add": "add", "lane-audit": "audit", "lane-board": "board", "lane-brief": "brief", "lane-done": "done",
            "lane-env-check": "env", "lane-env-keys": "keys", "lane-find": "find", "lane-gh": "gh", "lane-help": "help",
            "lane-import": "import", "lane-init": "init", "lane-memory": "note", "lane-menu": "menu", "lane-merge": "merge",
            "lane-merge-plan": "plan", "lane-nested": "nested", "lane-park": "park", "lane-ref": "ref", "lane-resume": "resume",
            "lane-run": "run", "lane-sessions": "sessions", "lane-start": "start", "lane-status": "status", "lane-with": "with",
            "lane-workspace": "workspace", "guard-check": "doctor"}
ROUTER_MARK = "stable, multi-plane-aware dispatcher"


def manifest():
    with open(os.path.join(HERE, "migrate-manifest.json")) as fh:
        return json.load(fh)


def blob_id(path):
    """The git blob id of a file (or of a symlink's target text), the way the release trees record it."""
    data = os.readlink(path).encode() if os.path.islink(path) else open(path, "rb").read()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def unchanged(man, rel, path):
    """Is the file at `path` (shipped as `rel`) byte for byte what some release shipped there?"""
    try:
        sha = blob_id(path)
    except OSError:
        return False
    if sha in man["files"].get(rel, ()):
        return True
    alt = os.path.join(PRODUCT, rel)
    try:
        return os.path.lexists(alt) and blob_id(alt) == sha
    except OSError:
        return False


def git(d, *a, check=False):
    r = subprocess.run(["git", "-C", d, *a], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git -C {d} {' '.join(a)}: {(r.stderr or r.stdout).strip()}")
    return r


def slug(p):
    return ws.project_slug(p)


def now_ts():
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


def write_json(path, data):
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w") as fh: json.dump(data, fh, indent=2, sort_keys=True); fh.write("\n")
    os.replace(tmp, path)


def load_json(path, default=None):
    try:
        with open(path) as fh: return json.load(fh)
    except (OSError, ValueError):
        return default


# ------------------------------------------------------------------------------------------- what is there
def is_clone(ad):
    return os.path.isfile(f"{ad}/lane") and os.path.isfile(f"{ad}/scripts/lib.sh") and os.path.isdir(f"{ad}/scripts/hooks")


def clone_version(ad):
    try:
        with open(f"{ad}/VERSION") as fh: return fh.read().strip()
    except OSError:
        return ""


def vtuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3]) or (0,)


def owner_of(ad):
    """owner: name: from the config file, wherever it is now (registry/config.yml, or .repolane/config.yml once moved)."""
    for p in (f"{ad}/.repolane/config.yml", f"{ad}/registry/config.yml"):
        try:
            with open(p) as fh:
                m = re.search(r"^owner:\s*$.*?^\s+name:\s*(.+?)\s*$", fh.read(), re.M | re.S)
        except OSError:
            continue
        o = m.group(1).strip().strip("\"'") if m else ""
        if o and o not in ("YOUR NAME", "the user"): return o
    return ""


def live_sessions(ad):
    """Claude Code processes whose current folder is inside `ad`: (pid, folder). Empty when it cannot be told."""
    try:
        out = subprocess.run(["ps", "-A", "-o", "pid=,args="], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    pids = []
    for line in out.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2 or not parts[0].isdigit() or int(parts[0]) == os.getpid(): continue
        args = parts[1]
        # the native binary (`claude …`), or an interpreter running it (`node …/bin/claude …`)
        heads = [os.path.basename(a) for a in args.split()[:2]]
        if "claude" in heads or "@anthropic-ai/claude-code" in args or "/claude-code/" in args:
            pids.append(parts[0])
    found = []
    for pid in pids:
        cwd = ""
        if os.path.exists(f"/proc/{pid}/cwd"):
            try: cwd = os.readlink(f"/proc/{pid}/cwd")
            except OSError: cwd = ""
        elif shutil.which("lsof"):
            try:
                r = subprocess.run(["lsof", "-a", "-p", pid, "-d", "cwd", "-Fn"], capture_output=True, text=True, timeout=10)
                cwd = next((l[1:] for l in r.stdout.splitlines() if l.startswith("n")), "")
            except (OSError, subprocess.SubprocessError):
                cwd = ""
        if cwd:
            real = os.path.realpath(cwd)
            if real == ad or real.startswith(ad + "/"):
                found.append((pid, real))
    return found


def recent_sessions(ad, minutes=30):
    """Session files the guard touched in the last `minutes` (a session that ended cleanly removes its own)."""
    out = []
    for base in (f"{ad}/.cache/sessions", f"{ad}/.repolane/cache/sessions"):
        try:
            for f in os.listdir(base):
                p = f"{base}/{f}"
                if f.endswith(".json") and time.time() - os.path.getmtime(p) < minutes * 60: out.append(f[:-5])
        except OSError:
            pass
    return out


def git_info(ad):
    """Is the folder's .git the Repolane repo's, and does it hold anything that is not on a remote?"""
    info = {"present": os.path.lexists(f"{ad}/.git"), "product": False, "dir": os.path.isdir(f"{ad}/.git"), "unpushed": 0,
            "dirty": [], "remote": ""}
    if not info["present"]:
        return info
    top = git(ad, "rev-parse", "--show-toplevel").stdout.strip()
    if not top or os.path.realpath(top) != ad:
        return info
    info["product"] = all(git(ad, "cat-file", "-e", f"HEAD:{p}").returncode == 0 for p in ("lane", "scripts/hooks/guard.py"))
    info["remote"] = git(ad, "remote", "get-url", "origin").stdout.strip()
    try: info["unpushed"] = int(git(ad, "rev-list", "--count", "HEAD", "--not", "--remotes").stdout.strip() or 0)
    except ValueError: info["unpushed"] = 0
    # what lane init itself edits is expected; any other tracked edit is the owner's own work in Repolane's files
    for line in git(ad, "status", "--porcelain", "--untracked-files=no").stdout.splitlines():
        p = line[3:]
        if p not in (".claude/settings.json", "registry/config.yml", ".gitignore"): info["dirty"].append(p)
    return info


# ---------------------------------------------------------------------------------------------- CLAUDE.md
CLAUDE_BASE = "# My workspace\n\nRepolane's rules for every session in this folder:\n\n" + roots.CLAUDE_IMPORT + "\n"


def analyse_claude_md(text, owner, templates):
    """Compare a clone's CLAUDE.md with what each released template would have made of it. Returns (mode, additions,
    edited_lines): mode is 'generated' (exactly a template), 'additions' (a template plus lines of the user's own),
    'edited' (lines of Repolane's text changed or removed too: unsure), or 'own' (it does not look generated at all)."""
    lines = text.splitlines()
    norm = [l.rstrip() for l in lines]
    best = None
    for t in templates:
        tl = [l.rstrip() for l in t.replace("{{owner}}", owner or "the user").splitlines()]
        sm = difflib.SequenceMatcher(None, tl, norm, autojunk=False)
        r = sm.ratio()
        if best is None or r > best[0]: best = (r, sm.get_opcodes(), tl)
    if best is None or best[0] < 0.5:
        return "own", [], 0
    _, ops, tl = best
    adds, edited = [], 0
    for tag, i1, i2, j1, j2 in ops:
        if tag in ("insert", "replace"):
            block = lines[j1:j2]
            if any(l.strip() for l in block): adds.append("\n".join(block).strip("\n"))
        if tag in ("delete", "replace"):
            edited += sum(1 for l in tl[i1:i2] if l.strip())
    if not adds and not edited: return "generated", [], 0
    return ("edited" if edited else "additions"), adds, edited


def new_claude_md(mode, adds, old):
    if mode == "own":
        return old if roots.CLAUDE_IMPORT in [l.strip() for l in old.splitlines()] else \
            old + ("" if old.endswith("\n") or not old else "\n") + "\n" + roots.CLAUDE_IMPORT + "\n"
    return CLAUDE_BASE + ("\n" + "\n\n".join(adds) + "\n" if adds else "")


# ------------------------------------------------------------------------------------------------ the plan
class Plan:
    """Everything a migration of `ad` would do, worked out from what is on disk now (so it is also right for a migration
    that was interrupted half way)."""

    def __init__(self, ad, given, claude_home, want_git):
        self.ad, self.man = ad, manifest()
        self.forms = sorted({ad, os.path.abspath(given)})        # the clone may have written its paths unresolved
        self.state = load_json(f"{ad}/{STATE}", None)
        self.done = set((self.state or {}).get("done", []))
        self.claude_home, self.want_git = claude_home, want_git
        self.owner = owner_of(ad)
        man = self.man
        # data moves
        self.moves = [(a, b) for a, b in MOVES if os.path.lexists(f"{ad}/{a}")]
        self.clash = [(a, b) for a, b in self.moves if os.path.lexists(f"{ad}/{b}")]
        self.env_template = os.path.isfile(f"{ad}/scripts/env.sh") and unchanged(man, "scripts/env.sh", f"{ad}/scripts/env.sh")
        # product files: every shipped path that is here, outside the data
        self.remove, self.changed = [], []
        for rel in man["files"]:
            if rel in DATA_FILES or rel.startswith(DATA_TOPS): continue
            p = f"{ad}/{rel}"
            if os.path.lexists(p) and not (os.path.isdir(p) and not os.path.islink(p)):
                self.remove.append(rel)
                if not unchanged(man, rel, p): self.changed.append(rel)
        # product files inside the data folders (READMEs, .gitkeep, the example): dropped after the move when unchanged
        self.data_product = []
        for rel in man["files"]:
            if rel.startswith(DATA_TOPS) and rel != "registry/config.yml":
                for p in (f"{ad}/{rel}", f"{ad}/.repolane/{rel}"):
                    if os.path.isfile(p) and unchanged(man, rel, p): self.data_product.append(rel); break
        rm = set(self.remove)
        self.kept = {}                     # top folder -> the user's files left in it
        self.whole = []                    # top folders that go entirely
        tops = sorted({r.split("/", 1)[0] for r in self.remove if "/" in r})
        for top in tops:
            mine = []
            for d, dirs, files in os.walk(f"{ad}/{top}"):
                dirs[:] = [x for x in dirs if x not in JUNK]
                rel_d = os.path.relpath(d, ad)
                if rel_d in ("scripts/local",) or rel_d.startswith("scripts/local/"): dirs[:] = []; continue
                for f in files:
                    r = f"{rel_d}/{f}"
                    if r not in rm and f not in JUNK and r not in DATA_FILES: mine.append(r)
                for x in list(dirs):
                    if os.path.islink(f"{d}/{x}"):
                        r = f"{rel_d}/{x}"
                        if r not in rm: mine.append(r)
            if mine:
                self.kept[top] = mine
            else:
                self.whole.append(top)
        self.git = git_info(ad) if "git" not in self.done else {"present": False, "product": False}
        # CLAUDE.md
        self.claude = None
        if "claude-md" not in self.done and os.path.isfile(f"{ad}/CLAUDE.md"):
            with open(f"{ad}/CLAUDE.md") as fh: old = fh.read()
            if roots.CLAUDE_IMPORT not in [l.strip() for l in old.splitlines()]:
                mode, adds, edited = analyse_claude_md(old, self.owner, man["claude_templates"])
                self.claude = {"mode": mode, "adds": adds, "edited": edited, "old": old, "new": new_claude_md(mode, adds, old)}
        # settings
        self.settings_ok = True
        try:
            if os.path.exists(f"{ad}/.claude/settings.json"):
                cur = json.load(open(f"{ad}/.claude/settings.json"))
                if not isinstance(cur, dict): raise ValueError("not a JSON object")
        except ValueError as e:
            self.settings_ok = str(e)
        self.lane_settings = [rel for _, p in ws.lane_settings(ad) for rel in [os.path.relpath(p, ad)] if os.path.exists(p)]
        self.lane_ids = sorted(x for x in (os.listdir(f"{ad}/lanes") if os.path.isdir(f"{ad}/lanes") else [])
                               if os.path.isdir(f"{ad}/lanes/{x}"))
        # worktrees under lanes/, by the mirror that owns them
        self.worktrees = []
        for base in (f"{ad}/repos", f"{ad}/.repolane/repos"):
            for r in sorted(os.listdir(base)) if os.path.isdir(base) else []:
                wtd = f"{base}/{r}/.git/worktrees"
                for w in sorted(os.listdir(wtd)) if os.path.isdir(wtd) else []:
                    try:
                        with open(f"{wtd}/{w}/gitdir") as fh: gd = fh.read().strip()
                    except OSError:
                        continue
                    if not os.path.isabs(gd): gd = os.path.normpath(os.path.join(wtd, w, gd))
                    self.worktrees.append((r, w, os.path.dirname(gd)))
        self.links = self.old_links(f"{ad}/lanes")
        # outside the folder
        self.claude_changes = self.claude_plan()
        self.router = self.router_plan()

    # symlinks under lanes/ (the .env links lane start made, refs) that point into a data folder that moves
    def old_links(self, top):
        out = []
        prune = {".git", "node_modules", ".venv", "venv", "dist", "target", ".nx", "__pycache__"}
        for d, dirs, files in os.walk(top):
            if d[len(top):].count("/") > 7: dirs[:] = []; continue
            for x in list(dirs) + files:
                p = f"{d}/{x}"
                if not os.path.islink(p): continue
                t = os.readlink(p)
                nt = self.new_target(t)
                if nt: out.append((os.path.relpath(p, self.ad), t, nt))
            dirs[:] = [x for x in dirs if x not in prune and not os.path.islink(f"{d}/{x}")]
        return out

    def new_target(self, t):
        """Where an absolute path into the old layout lives after the move, or None when the move does not change it."""
        for f in self.forms:
            for a, b in MOVES:
                if a in ("registry/config.yml", "scripts/env.sh"):
                    if t == f"{f}/{a}": return f"{self.ad}/{b}"
                    continue
                if t == f"{f}/{a}" or t.startswith(f"{f}/{a}/"):
                    return f"{self.ad}/{b}" + t[len(f"{f}/{a}"):]
        return None

    def claude_plan(self):
        """The changes under Claude Code's folder: memory links to repoint, mirror project folders to rename."""
        proj = f"{self.claude_home}/projects"
        out = {"relink": [], "rename": [], "make": []}
        if not os.path.isdir(proj): return out
        new_repos_slug = slug(f"{self.ad}/.repolane/repos")
        for name in sorted(os.listdir(proj)):
            d = f"{proj}/{name}"
            for f in self.forms:
                pre = slug(f"{f}/repos") + "-"
                if name.startswith(pre) and not name.startswith(new_repos_slug):
                    out["rename"].append((d, f"{proj}/{new_repos_slug}-{name[len(pre):]}")); break
            m = f"{d}/memory"
            if os.path.islink(m):
                t = os.readlink(m)
                nt = self.new_target(os.path.normpath(os.path.join(d, t)) if not os.path.isabs(t) else t)
                if nt: out["relink"].append((m, t, nt))
        root = f"{proj}/{slug(self.ad)}/memory"
        if not os.path.lexists(root) and not any(m == root for m, _, _ in out["relink"]):
            out["make"].append((root, f"{self.ad}/.repolane/memory"))
        return out

    def router_plan(self):
        home = os.path.expanduser("~")
        planes = load_json(ws.planes_file(), None)
        mine, others = [], []
        if isinstance(planes, dict):
            for name, e in (planes.get("planes") or {}).items():
                p = (e or {}).get("path", "") if isinstance(e, dict) else ""
                (mine if p and os.path.realpath(p) == self.ad else others).append(name)
        binp = f"{home}/.local/bin"
        router = f"{binp}/lane"
        is_router = False
        if os.path.isfile(router) and not os.path.islink(router):
            try: is_router = ROUTER_MARK in open(router, errors="replace").read()
            except OSError: pass
        stubs = [f"{binp}/{n}" for n, short in LONGFORM.items()
                 if os.path.isfile(f"{binp}/{n}") and not os.path.islink(f"{binp}/{n}") and _read(f"{binp}/{n}") == STUB.format(short)]
        py = f"{home}/.local/share/lane/planes.py"
        return {"planes": planes if isinstance(planes, dict) else None, "planes_broken": os.path.exists(ws.planes_file()) and not isinstance(planes, dict),
                "mine": mine, "others": others, "router": router if is_router else None, "stubs": stubs,
                "planes_py": py if os.path.isfile(py) else None, "remove": bool(is_router or stubs) and not others}

    def ask_claude(self):
        c = self.claude_changes
        return bool(c["relink"] or c["rename"] or c["make"]) and "claude-home" not in self.done

    def ask_router(self):
        return self.router["remove"] and "router" not in self.done

    # ---------------------------------------------------------------------------------------- the preview
    def show(self, verbose=False, backup=None):
        ad = self.ad
        print(f"{B}lane migrate{N}: {tilde(ad)} (a git-clone install, version {clone_version(ad) or '?'}) becomes a workspace.\n")
        if self.state:
            print(f"  {Y}A migration of this folder was interrupted.{N} Running it again continues it; done so far: "
                  f"{', '.join(sorted(self.done)) or 'nothing'}. Backup: {tilde(self.state.get('backup', '?'))}\n")
        print(f"  {B}Backup first{N}: everything below that is changed or removed goes into")
        print(f"      {tilde(backup or self.backup_path())}\n")
        if self.moves:
            print(f"  {B}Move into .repolane/{N} (your data; nothing in it is changed):")
            for a, b in self.moves:
                extra = ""
                if a == "scripts/env.sh":
                    extra = (" (unchanged from a release: the workspace's env.sh template is written instead)" if self.env_template
                             else " (yours: moved as it is; any .cache/ path in it is .repolane/cache/ now)")
                print(f"      {a}{'/' if os.path.isdir(f'{ad}/{a}') else ''}  ->  {b}{extra}")
            if self.data_product:
                print(f"    and drop Repolane's own placeholders in them (unchanged): {', '.join(self.data_product)}")
            print()
        if self.worktrees or self.links or self.lane_ids:
            print(f"  {B}Lanes{N} stay in lanes/; what points into the old layout is repointed:")
            for r, w, wt in self.worktrees:
                print(f"      git worktree repair: {os.path.relpath(wt, ad) if wt.startswith(ad) else wt} (a worktree of the {r} mirror)")
            for rel, t, nt in self.links:
                print(f"      link {rel}  ->  {os.path.relpath(nt, ad)}")
            for rel in self.lane_settings:
                print(f"      rewrite {rel} (lane hook commands, the new paths)")
            for i in self.lane_ids:
                print(f"      rewrite lanes/{i}/CLAUDE.md (the lane's pointer file)")
            print()
        if self.remove:
            print(f"  {B}Remove Repolane's own files{N} ({len(self.remove)}; only paths a release shipped, so nothing of yours):")
            for top in self.whole:
                n = sum(1 for r in self.remove if r.startswith(top + "/"))
                print(f"      {top}/  (the whole folder: {n} files, all Repolane's)")
            for top, mine in sorted(self.kept.items()):
                n = sum(1 for r in self.remove if r.startswith(top + "/"))
                print(f"      {top}/  ({n} of Repolane's files; the folder stays for yours: {', '.join(os.path.relpath(m, top) for m in mine)})")
                if verbose:
                    for r in self.remove:
                        if r.startswith(top + "/"): print(f"          {r}")
            singles = [r for r in self.remove if "/" not in r]
            if singles: print(f"      {', '.join(singles)}")
            if verbose:
                for top in self.whole:
                    for r in self.remove:
                        if r.startswith(top + "/"): print(f"          {r}")
            if self.changed:
                print(f"    {Y}changed locally{N} (removed too; they are in the backup): {', '.join(self.changed)}")
            print()
        g = self.git
        if g.get("present") and g.get("product"):
            print(f"  {B}.git{N} is the Repolane repo's (origin: {g.get('remote') or 'none'}), not your workspace's: it is removed "
                  "(it is in the backup)." + (" A fresh, empty git repo is made instead (--git)." if self.want_git else
                                               " Pass --git to start a fresh repo for the workspace."))
            if g.get("unpushed"): print(f"      {Y}it has {g['unpushed']} commit(s) on no remote{N}: they are only in the backup afterwards")
            if g.get("dirty"): print(f"      {Y}uncommitted edits to Repolane's files{N}: {', '.join(g['dirty'][:8])}")
            print()
        elif g.get("present"):
            print(f"  {B}.git{N} is a repo of your own, not Repolane's: it is kept.\n")
        elif self.want_git and "git" not in self.done:
            print(f"  {B}git{N}: a fresh, empty git repo is made for the workspace (--git).\n")
        c = self.claude
        if c:
            print(f"  {B}CLAUDE.md{N} becomes yours, importing Repolane's rules ({roots.CLAUDE_IMPORT}):")
            if c["mode"] == "generated": print("      it is exactly what lane init generated: replaced by a short file with the import line")
            elif c["mode"] == "additions": print(f"      the lines you added to it are kept ({len(c['adds'])} block(s)); Repolane's text is replaced by the import line")
            elif c["mode"] == "edited":
                print(f"      the lines you added are kept ({len(c['adds'])} block(s)), but {c['edited']} line(s) of Repolane's text were edited")
                print("      too, so the old file is also kept beside it as CLAUDE.md.pre-0.10: compare the two and keep what you need")
            else: print("      it does not look like the generated one, so it is kept as it is and the import line is added at its end")
            print()
        elif "claude-md" not in self.done and not os.path.isfile(f"{ad}/CLAUDE.md"):
            print(f"  {B}CLAUDE.md{N}: made (it imports .repolane/REPOLANE.md)\n")
        print(f"  {B}.claude/settings.json{N}: Repolane's hooks become `lane hook …` commands and the status line `lane statusline`;")
        print("      your own keys, hooks and permissions are kept. .repolane/REPOLANE.md, LANE.md and version are written.\n")
        cc = self.claude_changes
        if self.ask_claude():
            print(f"  {B}Under {tilde(self.claude_home)}{N} (asked separately):")
            for m, t, nt in cc["relink"]:
                for a, b in cc["rename"]:
                    if m.startswith(a + "/"): m = b + m[len(a):]
                print(f"      {tilde(m)} -> {os.path.relpath(nt, ad)}   (it pointed at {os.path.relpath(t, ad) if t.startswith(ad) else t})")
            for a, b in cc["rename"]: print(f"      rename {tilde(a)}  ->  {os.path.basename(b)}   (a mirror's project folder: its path changed)")
            for m, t in cc["make"]: print(f"      {tilde(m)} -> {os.path.relpath(t, ad)}   (new link)")
            print()
        rt = self.router
        print(f"  {B}~/.local{N}:")
        if rt["planes_broken"]:
            print(f"      {tilde(ws.planes_file())} is not valid JSON: left alone (mend it, then lane doctor --fix registers the workspace)")
        else:
            print(f"      {tilde(ws.planes_file())}: " + (f"the clone entry {', '.join(rt['mine'])} is dropped, " if rt["mine"] else "")
                  + "the workspace is recorded")
        if rt["router"] or rt["stubs"]:
            what = ", ".join(tilde(x) for x in ([rt["router"]] if rt["router"] else []) + (["the lane-* stubs beside it"] if rt["stubs"] else []))
            if rt["remove"]:
                print(f"      remove {what} (the router `lane install` wrote; asked separately), and {tilde(rt['planes_py'] or 'planes.py')}")
            else:
                print(f"      keep {what}: other clone installs still use it ({', '.join(rt['others'])})")
        print()

    def backup_path(self):
        if self.state and self.state.get("backup"): return self.state["backup"]
        if not hasattr(self, "_bp"):
            self._bp = os.path.expanduser(f"~/.local/share/lane/backups/{os.path.basename(self.ad)}-{now_ts()}.tar.gz")
        return self._bp


def _read(p):
    try:
        with open(p) as fh: return fh.read()
    except (OSError, UnicodeDecodeError):
        return None


# ---------------------------------------------------------------------------------------------- the backup
def make_backup(plan, path):
    """Everything the migration changes or removes, in one tar.gz, with a manifest of what was outside the folder."""
    ad = plan.ad
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.part"
    skip_top = {"lanes", "repos", ".repolane"}

    def keep(ti):
        n = ti.name[len("ws/"):] if ti.name.startswith("ws/") else ti.name
        if n == ".cache/nx" or n.startswith(".cache/nx/"): return None      # a build cache, made again by the build
        return ti
    ext = []
    # the top-level entries a migration touches: Repolane's own, the data that moves, and what is rewritten. The owner's
    # other files at the top are never changed, so they are not copied.
    touched = ({r.split("/", 1)[0] for r in plan.remove} | {a.split("/", 1)[0] for a, _ in MOVES}
               | {"CLAUDE.md", "CLAUDE.md.pre-0.10", ".claude", ".git", ".gitignore"})
    with tarfile.open(tmp, "w:gz") as tf:
        for e in sorted(os.listdir(ad)):
            if e in skip_top or e not in touched: continue
            tf.add(f"{ad}/{e}", arcname=f"ws/{e}", filter=keep)
        small = []
        for rel in plan.lane_settings: small.append(rel)
        for i in plan.lane_ids:
            if os.path.isfile(f"{ad}/lanes/{i}/CLAUDE.md"): small.append(f"lanes/{i}/CLAUDE.md")
        for r, w, wt in plan.worktrees:
            for base in ("repos", ".repolane/repos"):
                if os.path.isfile(f"{ad}/{base}/{r}/.git/worktrees/{w}/gitdir"):
                    small.append(f"{base}/{r}/.git/worktrees/{w}/gitdir"); break
            g = f"{wt}/.git"
            if os.path.isfile(g) and g.startswith(ad + "/"): small.append(os.path.relpath(g, ad))
        for rel, _, _ in plan.links: small.append(rel)
        for rel in sorted(set(small)):
            tf.add(f"{ad}/{rel}", arcname=f"ws/{rel}", recursive=False)
        # outside the folder: files by content, links by target
        rt = plan.router
        for i, p in enumerate([x for x in [rt["router"], rt["planes_py"], *rt["stubs"], ws.planes_file()] if x and os.path.isfile(x)]):
            tf.add(p, arcname=f"ext/{i}"); ext.append({"path": p, "member": f"ext/{i}"})
        links = []
        proj = f"{plan.claude_home}/projects"
        if os.path.isdir(proj):
            for name in sorted(os.listdir(proj)):
                m = f"{proj}/{name}/memory"
                if os.path.islink(m): links.append({"path": m, "target": os.readlink(m)})
        meta = {"format": 1, "ad": ad, "forms": plan.forms, "created": datetime.datetime.now().astimezone().isoformat(),
                "version": clone_version(ad), "product": PRODUCT, "claude_home": plan.claude_home, "moves": plan.moves,
                "env_template": plan.env_template, "external": ext, "claude_links": links,
                "renames": plan.claude_changes["rename"], "planes_mine": plan.router["mine"],
                "active": (plan.router["planes"] or {}).get("active"), "git": bool(plan.git.get("product"))}
        data = json.dumps(meta, indent=2).encode()
        ti = tarfile.TarInfo("manifest.json"); ti.size = len(data); ti.mtime = time.time()
        tf.addfile(ti, io.BytesIO(data))
    with tarfile.open(tmp, "r:gz") as tf:          # readable, whole, before anything relies on it
        tf.getmembers()
    os.replace(tmp, path)
    return path


# ------------------------------------------------------------------------------------------------- the steps
class Migration:
    def __init__(self, plan, backup, yes_claude, yes_router):
        self.p, self.ad, self.backup = plan, plan.ad, backup
        self.state = plan.state or {"backup": backup, "done": [], "started": datetime.datetime.now().astimezone().isoformat()}
        self.state.setdefault("answers", {})
        if "claude" not in self.state["answers"]: self.state["answers"]["claude"] = yes_claude
        if "router" not in self.state["answers"]: self.state["answers"]["router"] = yes_router
        self.state["git"] = self.state.get("git", plan.want_git)
        self.notes = []

    def save(self):
        write_json(f"{self.ad}/{STATE}", self.state)

    def step(self, name, fn):
        if name in self.state["done"]: return
        fn()
        self.state["done"].append(name); self.save()
        # tests stop a migration half way with this, to prove a second run continues it
        if os.environ.get("LANE_MIGRATE_STOP_AFTER") == name:
            raise RuntimeError(f"stopped after the {name} step (LANE_MIGRATE_STOP_AFTER)")

    def run(self):
        os.makedirs(f"{self.ad}/.repolane", exist_ok=True)
        self.save()
        self.step("data", self.move_data)
        self.step("worktrees", self.repair_worktrees)
        self.step("links", self.repoint_links)
        self.step("product", self.remove_product)
        self.step("git", self.git_step)
        self.step("claude-md", self.claude_md)
        self.step("settings", self.settings)
        self.step("lanes", self.lanes)
        self.step("claude-home", self.claude_home)
        self.step("router", self.router)
        self.step("planes", self.planes)
        write_json(f"{self.ad}/{DONE_MARK}", {"from": clone_version(self.ad) or self.state.get("from", ""), "backup": self.backup,
                                               "at": datetime.datetime.now().astimezone().isoformat()})
        os.remove(f"{self.ad}/{STATE}")

    def move_data(self):
        ad, p = self.ad, self.p
        self.state["from"] = clone_version(ad); self.save()
        for a, b in MOVES:
            src, dst = f"{ad}/{a}", f"{ad}/{b}"
            if not os.path.lexists(src): continue
            if os.path.lexists(dst):
                raise RuntimeError(f"both {a} and {b} exist; move one aside by hand, then run lane migrate again")
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if a == "scripts/env.sh" and p.env_template:
                with open(f"{PRODUCT}/templates/env.sh") as fh: roots._write(dst, fh.read())
                os.remove(src)
            else:
                os.rename(src, dst)
            say("moved", G, f"{a} -> {b}")
        for rel in p.data_product:
            q = f"{ad}/.repolane/{rel}"
            if os.path.isfile(q) and unchanged(p.man, rel, q): os.remove(q)

    def repair_worktrees(self):
        ad = self.ad
        mirrors = f"{ad}/.repolane/repos"
        for r, w, wt in self.p.worktrees:
            if not os.path.isdir(wt): continue
            res = git(f"{mirrors}/{r}", "worktree", "repair", wt)
            ok = git(wt, "rev-parse", "--git-dir").returncode == 0
            if res.returncode != 0 or not ok:
                say("warn", Y, f"git worktree repair {wt}: {(res.stderr or res.stdout).strip() or 'failed'}")
                self.notes.append(f"repair the worktree by hand: git -C {mirrors}/{r} worktree repair {wt}")
            else:
                say("fixed", G, f"worktree {os.path.relpath(wt, ad)} (git works there)")

    def repoint_links(self):
        for rel, t, nt in self.p.links:
            p = f"{self.ad}/{rel}"
            if os.path.islink(p) and os.readlink(p) == t:
                os.remove(p); os.symlink(nt, p)
        if self.p.links: say("fixed", G, f"{len(self.p.links)} link(s) under lanes/ now point into .repolane/")

    def remove_product(self):
        ad = self.ad
        dirs = set()
        for rel in self.p.remove:
            p = f"{ad}/{rel}"
            if os.path.lexists(p) and not (os.path.isdir(p) and not os.path.islink(p)):
                os.remove(p)
            d = os.path.dirname(rel)
            while d:
                dirs.add(d); d = os.path.dirname(d)
        # generated leftovers inside Repolane's folders, then every folder the removal emptied, deepest first
        for d in sorted(dirs, key=lambda x: -x.count("/")):
            full = f"{ad}/{d}"
            if not os.path.isdir(full) or os.path.islink(full): continue
            for j in JUNK:
                jp = f"{full}/{j}"
                if os.path.isdir(jp) and not os.path.islink(jp): shutil.rmtree(jp, ignore_errors=True)
                elif os.path.isfile(jp): os.remove(jp)
            try: os.rmdir(full)
            except OSError: pass
        say("removed", G, f"{len(self.p.remove)} of Repolane's own files" +
            (f" (kept yours in: {', '.join(t + '/' for t in sorted(self.p.kept))})" if self.p.kept else ""))

    def git_step(self):
        ad = self.ad
        if self.p.git.get("present") and self.p.git.get("product"):
            g = f"{ad}/.git"
            shutil.rmtree(g) if os.path.isdir(g) and not os.path.islink(g) else os.remove(g)
            say("removed", G, ".git (the Repolane repo's; it is in the backup)")
        if self.state.get("git"):
            for m in ws.make_git(ad): say("made", G, m)

    def claude_md(self):
        c = self.p.claude
        cm = f"{self.ad}/CLAUDE.md"
        if not c: return
        if c["mode"] == "edited":
            roots._write(f"{cm}.pre-0.10", c["old"])
            self.notes.append("CLAUDE.md.pre-0.10 is your old CLAUDE.md: lines of Repolane's text in it were edited, so compare it "
                              "with the new CLAUDE.md, keep what you need, then delete it")
        roots._write(cm, c["new"])
        say("made", G, "CLAUDE.md (imports .repolane/REPOLANE.md" + (f"; your {len(c['adds'])} block(s) kept)" if c["adds"] else ")"))

    def settings(self):
        ad = self.ad
        path = f"{ad}/.claude/settings.json"
        cur = load_json(path, {}) if os.path.exists(path) else {}
        if isinstance(cur, dict) and cur:
            old_allow = set(self.p.man["settings_allow"])
            perm = cur.get("permissions") if isinstance(cur.get("permissions"), dict) else None
            if perm and isinstance(perm.get("allow"), list):
                perm["allow"] = [a for a in perm["allow"] if a not in old_allow]
            sl = cur.get("statusLine")
            if isinstance(sl, dict) and roots.is_repolane_statusline(sl.get("command")):
                sl["command"] = roots.STATUSLINE_CMD
            roots._write(path, json.dumps(cur, indent=2) + "\n")
        made = roots.make_workspace(PRODUCT, ad, self.p.owner)
        roots.set_statusline(ad)
        for m in made: say("made", G, m)

    def lanes(self):
        ad = self.ad
        bad = tuple(f"{f}/{t}" for f in self.p.forms for t in OLD_DATA)
        for rel in self.p.lane_settings:
            p = f"{ad}/{rel}"
            cur = load_json(p, None)
            if not isinstance(cur, dict): continue
            perm = cur.get("permissions") if isinstance(cur.get("permissions"), dict) else {}
            for k in ("allow", "deny"):
                if isinstance(perm.get(k), list):
                    perm[k] = [x for x in perm[k] if not any(b + "/" in str(x) or str(x).rstrip(")").endswith(b) for b in bad)]
            cur.pop("hooks", None); cur.pop("autoMemoryDirectory", None)
            write_json(p, cur)
        if self.p.lane_ids:
            env = {k: v for k, v in os.environ.items() if k not in ("LANE_PRODUCT", "LANE_WORKSPACE")}
            env.update(LANE_PRODUCT=PRODUCT, LANE_WORKSPACE=ad)
            script = ('source "$LANE_PRODUCT/scripts/lib.sh"; refresh_guards; '
                      'for w in "$LANES"/*/; do i=$(basename "$w"); [ -f "$(lane_file "$i")" ] && write_lane_claude "$i"; done; true')
            r = subprocess.run(["bash", "-c", script], env=env, cwd=ad, capture_output=True, text=True, stdin=subprocess.DEVNULL)
            if r.returncode != 0:
                raise RuntimeError("rewriting the lanes' settings failed: " + (r.stderr or r.stdout).strip()[-400:])
            say("fixed", G, f"every lane's settings.local.json and CLAUDE.md written again ({len(self.p.lane_ids)} lane(s))")

    def claude_home(self):
        cc = self.p.claude_changes
        if not (cc["relink"] or cc["rename"] or cc["make"]): return
        if not self.state["answers"].get("claude"):
            self.notes.append(f"nothing under {tilde(self.p.claude_home)} was changed: lane doctor --fix links Claude Code's memory "
                              "into .repolane/memory (it asks first)")
            return
        for a, b in cc["rename"]:
            if os.path.isdir(a) and not os.path.lexists(b):
                os.rename(a, b); say("moved", G, f"{tilde(a)} -> {os.path.basename(b)}")
            elif os.path.isdir(a):
                self.notes.append(f"{tilde(a)} was not renamed: {tilde(b)} exists already; move its conversations over by hand")
        for m, t, nt in cc["relink"]:
            m2 = m
            for a, b in cc["rename"]:
                if m.startswith(a + "/"): m2 = b + m[len(a):]
            if os.path.islink(m2) or not os.path.lexists(m2):
                if os.path.lexists(m2): os.remove(m2)
                os.makedirs(os.path.dirname(m2), exist_ok=True); os.makedirs(nt, exist_ok=True)
                os.symlink(nt, m2); say("fixed", G, f"{tilde(m2)} -> {os.path.relpath(nt, self.ad)}")
        os.environ["CLAUDE_HOME"] = self.p.claude_home
        for proj, target, label, st, det in ws.pending_links(self.ad):
            try:
                ws.make_link(proj, target); say("made", G, f"memory of {label} linked: {tilde(proj)}/memory")
            except OSError as e:
                self.notes.append(f"could not link {tilde(proj)}/memory ({e}): lane doctor --fix")

    def router(self):
        rt = self.p.router
        if not rt["remove"]: return
        if not self.state["answers"].get("router"):
            self.notes.append("the old router was kept: " + ", ".join(tilde(x) for x in ([rt["router"]] if rt["router"] else []) + rt["stubs"])
                              + " — while it comes first on PATH, the hooks reach it instead of the installed lane (lane doctor says so)")
            return
        for x in ([rt["router"]] if rt["router"] else []) + rt["stubs"] + ([rt["planes_py"]] if rt["planes_py"] else []):
            try: os.remove(x)
            except OSError: pass
        say("removed", G, f"the old router {tilde(rt['router'] or '~/.local/bin/lane')} and its lane-* stubs")
        self.notes.append("if pipx (or uv) skipped linking `lane` because the old router was in the way: pipx reinstall repolane")

    def planes(self):
        rt = self.p.router
        if rt["planes_broken"]:
            self.notes.append(f"{tilde(ws.planes_file())} is not valid JSON: mend it, then run lane doctor --fix"); return
        data = load_json(ws.planes_file(), None)
        if isinstance(data, dict) and rt["mine"]:
            for n in rt["mine"]: (data.get("planes") or {}).pop(n, None)
            if data.get("active") in rt["mine"]: data["active"] = None
            os.makedirs(os.path.dirname(ws.planes_file()), exist_ok=True); write_json(ws.planes_file(), data)
        ws.register(self.ad)
        say("made", G, f"registered the workspace in {tilde(ws.planes_file())}" + (f" (the clone entry {', '.join(rt['mine'])} dropped)" if rt["mine"] else ""))


# --------------------------------------------------------------------------------------------------- undo
def safe_member(name):
    return not (name.startswith("/") or ".." in name.split("/"))


def undo(path, assume_yes):
    path = os.path.abspath(os.path.expanduser(path))
    try:
        tf = tarfile.open(path, "r:gz")
        meta = json.load(tf.extractfile("manifest.json"))
    except (OSError, KeyError, ValueError, tarfile.TarError) as e:
        print(f"lane migrate --undo: {path} is not a migration backup ({e})", file=sys.stderr); return 2
    ad = meta["ad"]
    members = [m for m in tf.getmembers() if m.name.startswith("ws/") and safe_member(m.name)]
    if not os.path.isdir(ad):
        print(f"lane migrate --undo: {ad} is not there any more", file=sys.stderr); return 2
    aside = os.path.splitext(os.path.splitext(path)[0])[0] + f"-undone-{now_ts()}"
    print(f"{B}lane migrate --undo{N}: put {tilde(ad)} back as the clone install (version {meta.get('version') or '?'}) the backup holds.\n")
    print(f"  move back: " + ", ".join(f"{b} -> {a}" for a, b in meta["moves"]))
    print(f"  restore from {tilde(path)}: Repolane's files, .git, CLAUDE.md, .claude/, each lane's settings and worktree links")
    print("  your data keeps what was written in the workspace since; the workspace's own files (CLAUDE.md, .claude/settings.json,")
    print(f"  REPOLANE.md, …) are kept aside in {tilde(aside)}")
    print(f"  outside: the memory links under {tilde(meta.get('claude_home', '~/.claude'))}, the router in ~/.local/bin, planes.json\n")
    if not assume_yes:
        if not can_ask():
            print("Nothing was changed: there is no terminal to ask. Run again with --yes to restore."); return 0
        if ask("Restore now? [y/N] ").lower() not in ("y", "yes"):
            print("Nothing was changed."); return 0
    os.makedirs(aside, exist_ok=True)
    # 1. the data back where the clone keeps it (what is in it now, so nothing written since is lost)
    for a, b in reversed(meta["moves"]):
        src, dst = f"{ad}/{b}", f"{ad}/{a}"
        if a == "scripts/env.sh" and meta.get("env_template"):
            if os.path.lexists(src): shutil.move(src, f"{aside}/env.sh")
            continue
        if os.path.lexists(src) and not os.path.lexists(dst):
            os.makedirs(os.path.dirname(dst), exist_ok=True); os.rename(src, dst)
    # 2. what the workspace made, aside
    if os.path.isdir(f"{ad}/.repolane"): shutil.move(f"{ad}/.repolane", f"{aside}/.repolane")
    for rel in ("CLAUDE.md", "CLAUDE.md.pre-0.10", ".claude/settings.json", ".gitignore", ".git"):
        p = f"{ad}/{rel}"
        if os.path.lexists(p) and (rel != ".gitignore" or any(m.name == "ws/.gitignore" for m in members)):
            os.makedirs(os.path.dirname(f"{aside}/{rel}"), exist_ok=True); shutil.move(p, f"{aside}/{rel}")
    # 3. the backup: the data folders only where something is missing, everything else as it was
    data = ("registry", "memory", "knowledge", ".cache", "scripts/local")
    for m in members:
        rel = m.name[3:]
        if not rel: continue
        dst = f"{ad}/{rel}"
        in_data = any(rel == d or rel.startswith(d + "/") for d in data)
        if m.isdir():
            os.makedirs(dst, exist_ok=True); continue
        if in_data and os.path.lexists(dst): continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.lexists(dst) and not (os.path.isdir(dst) and not os.path.islink(dst)): os.remove(dst)
        if m.issym():
            os.symlink(m.linkname, dst)
        elif m.isfile():
            with tf.extractfile(m) as src, open(dst, "wb") as out: shutil.copyfileobj(src, out)
            os.chmod(dst, m.mode & 0o7777)
    for m in members:      # folder modes last, once their files are in
        if m.isdir(): os.chmod(f"{ad}/{m.name[3:]}" if m.name[3:] else ad, m.mode & 0o7777)
    # 4. worktrees: every mirror repairs its own, the .env links follow the mirrors back
    repos = f"{ad}/repos"
    for r in sorted(os.listdir(repos)) if os.path.isdir(repos) else []:
        wtd = f"{repos}/{r}/.git/worktrees"
        for w in sorted(os.listdir(wtd)) if os.path.isdir(wtd) else []:
            gd = (_read(f"{wtd}/{w}/gitdir") or "").strip()
            if gd: git(f"{repos}/{r}", "worktree", "repair", os.path.dirname(gd))
    newp = f"{ad}/.repolane/repos/"
    for d, dirs, files in os.walk(f"{ad}/lanes"):
        dirs[:] = [x for x in dirs if x not in (".git", "node_modules") and not os.path.islink(f"{d}/{x}")]
        for x in files + dirs:
            p = f"{d}/{x}"
            if os.path.islink(p) and os.readlink(p).startswith(newp):
                t = f"{ad}/repos/" + os.readlink(p)[len(newp):]; os.remove(p); os.symlink(t, p)
    # 5. every lane's settings, by the clone's own scripts
    if os.path.isfile(f"{ad}/scripts/lib.sh") and os.path.isdir(f"{ad}/lanes"):
        env = {k: v for k, v in os.environ.items() if k not in ("LANE_PRODUCT", "LANE_WORKSPACE")}
        subprocess.run(["bash", "-c", 'source "$0/scripts/lib.sh"; refresh_guards; for w in "$LANES"/*/; do i=$(basename "$w"); '
                        '[ -f "$(lane_file "$i")" ] && write_lane_claude "$i"; done; true', ad],
                       env=env, cwd=ad, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    # 6. outside the folder
    for a, b in meta.get("renames", []):
        if os.path.isdir(b) and not os.path.lexists(a): os.rename(b, a)
    for l in meta.get("claude_links", []):
        p = l["path"]
        if os.path.islink(p) or not os.path.lexists(p):
            if os.path.lexists(p): os.remove(p)
            os.makedirs(os.path.dirname(p), exist_ok=True); os.symlink(l["target"], p)
    planes_saved = None
    for e in meta.get("external", []):
        f = tf.extractfile(e["member"]).read()
        if e["path"] == ws.planes_file():
            planes_saved = json.loads(f.decode() or "{}"); continue
        if not os.path.exists(e["path"]):
            os.makedirs(os.path.dirname(e["path"]), exist_ok=True)
            with open(e["path"], "wb") as out: out.write(f)
            os.chmod(e["path"], 0o755)
    cur = load_json(ws.planes_file(), None)
    if isinstance(cur, dict):
        (cur.get("workspaces") or {}).pop(ad, None)
        for n in meta.get("planes_mine", []):
            if planes_saved and n in (planes_saved.get("planes") or {}):
                cur.setdefault("planes", {})[n] = planes_saved["planes"][n]
        if meta.get("active") in meta.get("planes_mine", []) and not cur.get("active"): cur["active"] = meta["active"]
        write_json(ws.planes_file(), cur)
    elif planes_saved is not None and not os.path.exists(ws.planes_file()):
        os.makedirs(os.path.dirname(ws.planes_file()), exist_ok=True); write_json(ws.planes_file(), planes_saved)
    tf.close()
    print(f"\nRestored {tilde(ad)} as the clone install. What the workspace had made is in {tilde(aside)}.")
    print("Check it: cd " + shlex.quote(ad) + " && ./lane doctor")
    return 0


# --------------------------------------------------------------------------------------------------- main
def main(argv):
    target, assume_yes, dry, want_git, verbose, undo_from = None, False, False, False, False, None
    claude_home = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--yes", "-y"): assume_yes = True
        elif a == "--dry-run": dry = True
        elif a == "--git": want_git = True
        elif a in ("-v", "--verbose"): verbose = True
        elif a == "--claude-home":
            if i + 1 >= len(argv): print("lane migrate: --claude-home needs a folder", file=sys.stderr); return 2
            claude_home = argv[i + 1]; i += 1
        elif a == "--undo":
            if i + 1 >= len(argv): print("lane migrate: --undo needs the backup file", file=sys.stderr); return 2
            undo_from = argv[i + 1]; i += 1
        elif a in ("-h", "--help"):
            print(__doc__.split("\nWhat happens")[0].rstrip()); return 0
        elif a.startswith("-"):
            print(f"lane migrate: unknown option {a}", file=sys.stderr); return 2
        elif target is None: target = a
        else:
            print("lane migrate: one folder at most", file=sys.stderr); return 2
        i += 1
    if claude_home: os.environ["CLAUDE_HOME"] = os.path.abspath(os.path.expanduser(claude_home))
    if undo_from:
        return undo(undo_from, assume_yes)
    given = os.path.abspath(os.path.expanduser(target or os.environ.get("PWD") or os.getcwd()))
    if not os.path.isdir(given):
        print(f"lane migrate: {given} is not a folder", file=sys.stderr); return 2
    ad = os.path.realpath(given)
    if ad == PRODUCT or ad.startswith(PRODUCT + "/"):
        print(f"lane migrate: {ad} is the installed package itself; name the clone install to migrate", file=sys.stderr); return 2
    state = load_json(f"{ad}/{STATE}", None)
    if os.path.isdir(f"{ad}/.repolane") and state is None:
        mark = load_json(f"{ad}/{DONE_MARK}", None)
        print(f"{tilde(ad)} is already a workspace" + (f" (migrated from {mark.get('from') or 'a clone'}; backup: {tilde(mark.get('backup', '?'))})"
                                                     if isinstance(mark, dict) else "") + ". Nothing to migrate, and nothing was changed.")
        print("  lane doctor checks it.")
        return 0
    if state is None:
        if not is_clone(ad):
            print(f"lane migrate: {ad} is not a git-clone install of Repolane (no lane, scripts/lib.sh there)", file=sys.stderr)
            return 2
        v = clone_version(ad)
        if vtuple(v) < (0, 9, 0):
            print(f"lane migrate: {ad} is version {v or 'unknown'}; bring it to 0.9.2 first (./lane upgrade there), then migrate", file=sys.stderr)
            return 2
        if not (os.path.isfile(f"{ad}/registry/repos.yaml") or os.path.isfile(f"{ad}/CLAUDE.md")):
            print(f"lane migrate: {ad} is a copy of Repolane that was never set up (no registry/repos.yaml): there is nothing to "
                  "migrate. Make a workspace somewhere else with lane init.", file=sys.stderr)
            return 2
    claude_home = os.path.realpath(os.path.expanduser(os.environ.get("CLAUDE_HOME") or "~/.claude"))
    plan = Plan(ad, given, claude_home, want_git or bool((state or {}).get("git")))
    live = live_sessions(ad)
    if live:
        print(f"lane migrate: Claude Code is running inside {tilde(ad)}:", file=sys.stderr)
        for pid, d in live: print(f"    pid {pid} in {d}", file=sys.stderr)
        print("  Its hooks would vanish under it. End those sessions (/exit), then run lane migrate again, from a terminal.", file=sys.stderr)
        return 1
    if plan.clash and "data" not in plan.done:
        for a, b in plan.clash: print(f"lane migrate: both {a} and {b} exist; move one aside, then run again", file=sys.stderr)
        return 1
    if plan.settings_ok is not True:
        print(f"lane migrate: .claude/settings.json is not valid JSON ({plan.settings_ok}); mend it first", file=sys.stderr); return 1
    plan.show(verbose)
    recent = recent_sessions(ad)
    if recent:
        print(f"  {Y}warn{N}  {len(recent)} Claude Code session(s) used this folder in the last 30 minutes ({', '.join(recent[:3])}"
              f"{' …' if len(recent) > 3 else ''}). If one is still open, end it first: its hooks change under it.\n")
    if dry:
        print("Dry run: nothing was changed."); return 0
    if not assume_yes and not can_ask():
        print("Nothing was changed: there is no terminal to ask, and --yes was not given.")
        print(f"  Run it again from a terminal, or: lane migrate {shlex.quote(given)} --yes")
        return 0
    if not assume_yes and ask("Migrate now? [y/N] ").lower() not in ("y", "yes"):
        print("Nothing was changed."); return 0
    yes_claude = yes_router = assume_yes
    if not assume_yes and plan.ask_claude():
        yes_claude = ask(f"Make the changes under {tilde(claude_home)} listed above? [Y/n] ").lower() in ("", "y", "yes")
    if not assume_yes and plan.ask_router():
        yes_router = ask(f"Remove the old router {tilde(plan.router['router'] or '~/.local/bin/lane')}? [Y/n] ").lower() in ("", "y", "yes")
    backup = plan.backup_path()
    if not plan.state:
        print(f"\nBacking up to {tilde(backup)} …")
        make_backup(plan, backup)
        say("made", G, f"backup {tilde(backup)}")
    else:
        print(f"\nContinuing the interrupted migration (backup: {tilde(backup)})")
    mig = Migration(plan, backup, yes_claude, yes_router)
    try:
        mig.run()
    except (OSError, RuntimeError, ValueError) as e:
        print(f"\n{R}lane migrate stopped{N}: {e}", file=sys.stderr)
        print(f"  Nothing is lost: run lane migrate {shlex.quote(ad)} again to continue, or put the clone back with:", file=sys.stderr)
        print(f"  lane migrate --undo {shlex.quote(backup)}", file=sys.stderr)
        return 1
    print(f"\n{G}Done{N}: {tilde(ad)} is a workspace.")
    for n in mig.notes: print(f"  {Y}note{N}  {n}")
    print(f"  Backup: {tilde(backup)}   (undo: lane migrate --undo {shlex.quote(backup)})")
    print("  Check it: lane doctor")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
