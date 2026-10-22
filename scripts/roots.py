"""Where everything is: the Python side of scripts/roots.sh (read that file's header first; the two must agree).

Imported by the guard and the board (with sys.dont_write_bytecode set, so the product never grows a __pycache__), and run
as a small command by the shell side:

  python3 -B roots.py refresh <product> <workspace>          rewrite the workspace's REPOLANE.md / LANE.md, migrate, record the version
  python3 -B roots.py make-workspace <product> <dir> [owner] an empty workspace layout (the guts of `lane init`, scripts/workspace.py)
  python3 -B roots.py paths [<start-dir>]                    the resolved roots and data paths, one `NAME=value` per line
  python3 -B roots.py lane-context <lane>                    what a session inside that lane is handed (LANE.md and its header)
"""
import json
import os
import sys

# The data folders, by what they are called in a clone (and in every message, doc and rule): in a workspace each of them
# sits under .repolane/, and .cache/ is called cache/ there because nothing inside .repolane/ needs hiding.
DATA_DIRS = ("registry", "memory", "knowledge", "repos")


def find_workspace(start):
    """The nearest folder at or above `start` that holds a .repolane/ folder, or None."""
    try:
        d = os.path.realpath(start)
    except (OSError, ValueError):
        return None
    while True:
        if os.path.isdir(os.path.join(d, ".repolane")):
            return d
        up = os.path.dirname(d)
        if up == d:
            return None
        d = up


class Roots:
    """PRODUCT, AD and every data path, decided exactly as lane_resolve_roots in roots.sh decides them. Real paths."""

    def __init__(self, product_default, env=None, start=None):
        env = os.environ if env is None else env
        self.product = os.path.realpath(env.get("LANE_PRODUCT") or product_default)
        ad = env.get("LANE_WORKSPACE") or None
        if not ad and env.get("LANE_PRODUCT"):
            if start is None:
                try: start = os.getcwd()
                except OSError: start = None
            ad = find_workspace(start) if start else None
        self.ad = os.path.realpath(ad or self.product)
        self.workspace = os.path.isdir(os.path.join(self.ad, ".repolane"))
        self.mode = "workspace" if self.workspace else "clone"
        self.data = f"{self.ad}/.repolane" if self.workspace else self.ad
        self.registry = f"{self.data}/registry"
        self.lanes_dir = f"{self.registry}/lanes"
        self.repos = f"{self.data}/repos"
        self.memory = f"{self.data}/memory"
        self.knowledge = f"{self.data}/knowledge"
        self.cache = f"{self.data}/cache" if self.workspace else f"{self.ad}/.cache"
        self.config = f"{self.data}/config.yml" if self.workspace else f"{self.registry}/config.yml"
        self.env_sh = f"{self.data}/env.sh" if self.workspace else f"{self.product}/scripts/env.sh"
        self.lanes = f"{self.ad}/lanes"

    def logical(self, rel):
        """A path relative to AD, renamed to what it is called in a clone, so one set of rules judges both layouts:
        .repolane/memory/x -> memory/x, .repolane/cache/x -> .cache/x, .repolane/config.yml -> registry/config.yml.
        Anything else under .repolane/ (REPOLANE.md, LANE.md, env.sh, version) keeps its name and is the plane's own."""
        if not self.workspace or not (rel == ".repolane" or rel.startswith(".repolane/")):
            return rel
        inner = rel[len(".repolane/"):] if rel != ".repolane" else ""
        top, _, rest = inner.partition("/")
        if top in DATA_DIRS:
            return inner
        if top == "cache":
            return ".cache" + (f"/{rest}" if rest else "")
        if inner == "config.yml":
            return "registry/config.yml"
        return rel

    def owner(self):
        """Who the workspace belongs to: owner: name: in the config file, or a neutral word."""
        import re
        try:
            with open(self.config) as fh:
                m = re.search(r"^owner:\s*$.*?^\s+name:\s*(.+?)\s*$", fh.read(), re.M | re.S)
            name = m.group(1).strip().strip("\"'") if m else ""
            return name if name and name != "YOUR NAME" else "the user"
        except OSError:
            return "the user"

    def lane_context(self, lane):
        """What a session inside lane `lane` is handed, by the hook after EnterWorktree and at SessionStart in the lane:
        who the owner is, where its file is, and LANE.md. The owner's name and the paths are filled in here, at run
        time, so the text files themselves never carry them."""
        try:
            with open(f"{self.data}/LANE.md") as fh: rules = fh.read()
        except OSError:
            try:
                with open(f"{self.product}/templates/LANE.md") as fh: rules = fh.read()
            except OSError:
                rules = ""
        head = (f"## Repolane: this session is in lane '{lane}'\n"
                f"Owner: {self.owner()} (the rules below and REPOLANE.md call them \"the owner\").\n"
                f"Lane folder: {self.lanes}/{lane}/  ·  lane file: {self.lanes_dir}/{lane}.md (read it; set its Goal with "
                f"`lane-memory goal \"<text>\"`, never Edit/Write).\n"
                f"If a bare lane-* command is not found, the same command is at {self.product}/scripts/<name>.\n")
        return head + "\n" + rules.strip() + "\n"

    def paths(self):
        return {"PRODUCT": self.product, "AD": self.ad, "LANE_MODE": self.mode, "DATA": self.data, "REGISTRY": self.registry,
                "LANES_DIR": self.lanes_dir, "REPOS": self.repos, "MEMORY_DIR": self.memory, "KNOWLEDGE_DIR": self.knowledge,
                "CACHE_DIR": self.cache, "CONFIG_FILE": self.config, "ENV_SH": self.env_sh, "LANES": self.lanes}


# ------------------------------------------------------------------------------------------------ hooks as commands
# hook_event_name -> the word `lane hook` takes. A workspace's settings name only these commands, never a file in the
# product: the installed `lane` is found on PATH, and the workspace from the session's folder.
HOOK_EVENTS = {"SessionStart": "session-start", "PreToolUse": "pre-tool-use", "PostToolUse": "post-tool-use",
               "UserPromptSubmit": "user-prompt-submit", "PreCompact": "pre-compact", "SessionEnd": "session-end",
               "WorktreeCreate": "worktree-create", "WorktreeRemove": "worktree-remove"}
HOOK_PREFIX = "lane hook "


def workspace_hooks():
    """The hooks block of a workspace's settings (its top .claude/settings.json and every lane's settings.local.json):
    the same events and matchers a clone wires, plus EnterWorktree after the fact, which is when LANE.md is handed in."""
    def hk(event, matcher=None, timeout=30):
        return [{**({"matcher": matcher} if matcher else {}),
                 "hooks": [{"type": "command", "command": HOOK_PREFIX + HOOK_EVENTS[event], "timeout": timeout}]}]
    return {"SessionStart": hk("SessionStart", "startup|resume|clear|compact|fork", 60),
            "PreToolUse": hk("PreToolUse", "Bash|Edit|Write|MultiEdit|NotebookEdit|Read|EnterWorktree|Glob|Grep"),
            "PostToolUse": hk("PostToolUse", "Edit|Write|MultiEdit|NotebookEdit|EnterWorktree"),
            "WorktreeCreate": hk("WorktreeCreate", None, 120), "WorktreeRemove": hk("WorktreeRemove"),
            "UserPromptSubmit": hk("UserPromptSubmit"), "PreCompact": hk("PreCompact"), "SessionEnd": hk("SessionEnd")}


# the read-only commands a dispatcher session at the workspace root may run without asking (a clone's settings.json
# lists the same, by its bin/ paths)
WORKSPACE_ALLOW = ["Bash(lane-merge-plan:*)", "Bash(lane-status:*)", "Bash(lane-brief:*)", "Bash(lane-menu:*)",
                   "Bash(lane-sessions:*)", "Bash(lane-env-check:*)", "Bash(lane-env-keys:*)", "Bash(lane-memory list:*)",
                   "Bash(lane-memory show:*)", "Bash(lane-memory audit:*)", "Bash(lane status:*)", "Bash(lane brief:*)"]


def is_repolane_hook(cmd):
    """A hook command Repolane owns: `lane hook <event>`, or a clone's guard / session-start by path (left in a workspace's
    settings by an earlier setup, it would run a second, possibly stale, guard)."""
    cmd = str(cmd or "")
    return (cmd.startswith(HOOK_PREFIX) or cmd.rstrip().endswith("scripts/hooks/guard.py")
            or "scripts/session-start" in cmd)


def repolane_hooks(settings):
    """Repolane's part of a settings dict's hooks, in the same shape as workspace_hooks(): what a check compares."""
    have = settings.get("hooks") if isinstance(settings.get("hooks"), dict) else {}
    out = {}
    for event, entries in have.items():
        for e in entries if isinstance(entries, list) else []:
            hs = [h for h in (e.get("hooks") or []) if isinstance(h, dict) and is_repolane_hook(h.get("command"))] if isinstance(e, dict) else []
            if hs: out.setdefault(event, []).append({**e, "hooks": hs})
    return out


def merge_settings(path, hooks, allow=()):
    """Put Repolane's hooks into a settings file without disturbing anything else in it: hook entries that run some other
    command, permissions, env, the status line. Ours are recognised by is_repolane_hook and replaced whole. The file is
    written only when that changes something, and a file that is not valid JSON is refused (ValueError), never replaced.
    Returns True when the file was written."""
    try:
        with open(path) as fh: raw = fh.read()
    except OSError:
        raw = None
    if raw is None or not raw.strip():
        cur = {}
    else:
        cur = json.loads(raw)   # ValueError: the user's file is broken, and is theirs to mend
        if not isinstance(cur, dict): raise ValueError(f"{path} is not a JSON object")
    before = json.loads(json.dumps(cur))
    have = cur.get("hooks") if isinstance(cur.get("hooks"), dict) else {}
    out = {}
    for event, entries in have.items():
        kept = []
        for e in entries if isinstance(entries, list) else []:
            hs = [h for h in (e.get("hooks") or []) if not (isinstance(h, dict) and is_repolane_hook(h.get("command")))] if isinstance(e, dict) else []
            if hs: kept.append({**e, "hooks": hs})
        if kept: out[event] = kept
    for event, entries in hooks.items():
        out[event] = out.get(event, []) + entries
    cur["hooks"] = out
    if allow:
        perm = cur.setdefault("permissions", {})
        perm["allow"] = sorted(set(perm.get("allow") or []) | set(allow))
    if raw is not None and cur == before:
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w") as fh: json.dump(cur, fh, indent=2); fh.write("\n")
    os.replace(tmp, path)
    return True


# ------------------------------------------------------------------------------------------------ the status line
# A workspace's status line is a command too, never a path into the product: `lane statusline` runs scripts/statusline.sh.
STATUSLINE_CMD = "lane statusline"


def is_repolane_statusline(cmd):
    """A status line Repolane wired: the workspace's command, or a clone's statusline.sh by path (left by an older setup)."""
    cmd = str(cmd or "")
    return cmd.strip() == STATUSLINE_CMD or "scripts/statusline.sh" in cmd


def statusline_state(ad):
    """'ours' (lane statusline), 'stale' (a clone's statusline.sh by path), 'mine' (the user's own command, left alone),
    'none' (neither settings file has one), or 'broken' (settings.json is not valid JSON)."""
    found = None
    for f in ("settings.json", "settings.local.json"):
        try:
            with open(f"{ad}/.claude/{f}") as fh: raw = fh.read()
        except OSError:
            continue
        try:
            cur = json.loads(raw) if raw.strip() else {}
        except ValueError:
            if f == "settings.json": return "broken"
            continue
        sl = cur.get("statusLine") if isinstance(cur, dict) else None
        if sl is not None and found is None: found = sl
    if found is None: return "none"
    cmd = found.get("command") if isinstance(found, dict) else ""
    if str(cmd or "").strip() == STATUSLINE_CMD: return "ours"
    return "stale" if is_repolane_statusline(cmd) else "mine"


def set_statusline(ad, replace_stale=True):
    """Wire `lane statusline` into .claude/settings.json when no status line is set (or, with replace_stale, when the one
    set is a clone's statusline.sh by path). The user's own status line is never replaced. True when the file was written."""
    st = statusline_state(ad)
    if st == "ours" or st == "mine" or st == "broken" or (st == "stale" and not replace_stale): return False
    path = f"{ad}/.claude/settings.json"
    try:
        with open(path) as fh: raw = fh.read()
    except OSError:
        raw = ""
    cur = json.loads(raw) if raw.strip() else {}
    if st == "stale" and not is_repolane_statusline((cur.get("statusLine") or {}).get("command") if isinstance(cur.get("statusLine"), dict) else ""):
        # the stale one is in settings.local.json: that file is machine-local and Repolane's to mend as well
        lpath = f"{ad}/.claude/settings.local.json"
        with open(lpath) as fh: loc = json.load(fh)
        loc["statusLine"] = {"type": "command", "command": STATUSLINE_CMD}
        _write(lpath, json.dumps(loc, indent=2) + "\n")
        return True
    cur["statusLine"] = {"type": "command", "command": STATUSLINE_CMD}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _write(path, json.dumps(cur, indent=2) + "\n")
    return True


# ------------------------------------------------------------------------------------ the rule files and migrations
RULE_FILES = ("REPOLANE.md", "LANE.md")


def product_version(product):
    try:
        with open(f"{product}/VERSION") as fh: return fh.read().strip() or "unknown"
    except OSError:
        return "unknown"


def _write(path, text):
    tmp = f"{os.path.dirname(path)}/.{os.path.basename(path)}.{os.getpid()}"
    with open(tmp, "w") as fh: fh.write(text)
    os.replace(tmp, path)   # a session reading it never sees half a file


# (applies(recorded, installed) -> bool, step(workspace)) pairs, run in order when the recorded version differs. A step changes the
# layout of the user's data; it may add and move, never overwrite or drop what the user wrote. None is needed yet.
MIGRATIONS = []


def rules_current(product, ad):
    """Are the workspace's rule files the installed version's, word for word? (what `lane doctor` checks)"""
    data = f"{ad}/.repolane"
    try:
        with open(f"{data}/version") as fh: have = fh.read().strip()
    except OSError:
        return False
    if have != product_version(product): return False
    for f in RULE_FILES:
        try:
            with open(f"{data}/{f}") as a, open(f"{product}/templates/{f}") as b:
                if a.read() != b.read(): return False
        except OSError:
            return False
    return True


def refresh(product, ad, force=False):
    """Bring a workspace's product-owned files up to the installed version: run the data migrations its recorded version
    needs, rewrite REPOLANE.md and LANE.md from the product's templates, then record the version. Everything else in the
    workspace is the user's and is left alone. Returns True when something was rewritten. `force` rewrites the rule files
    even at the same version (`lane doctor --fix`, after one was edited by hand)."""
    data = f"{ad}/.repolane"
    if not os.path.isdir(data): return False
    want = product_version(product)
    try:
        with open(f"{data}/version") as fh: have = fh.read().strip()
    except OSError:
        have = ""
    if force and rules_current(product, ad): return False
    if not force and have == want and all(os.path.isfile(f"{data}/{f}") for f in RULE_FILES): return False
    for applies, step in MIGRATIONS:
        if applies(have, want): step(ad)
    for f in RULE_FILES:
        with open(f"{product}/templates/{f}") as fh: _write(f"{data}/{f}", fh.read())
    _write(f"{data}/version", want + "\n")
    return True


# ------------------------------------------------------------------------------------------- an empty workspace
CLAUDE_IMPORT = "@.repolane/REPOLANE.md"


def has_import(ad):
    """Does the workspace's CLAUDE.md load REPOLANE.md? None when there is no CLAUDE.md at all."""
    try:
        with open(f"{ad}/CLAUDE.md") as fh: text = fh.read()
    except OSError:
        return None
    return CLAUDE_IMPORT in [l.strip() for l in text.splitlines()]


def add_import(ad):
    """Append the import line to the workspace's CLAUDE.md: only ever when the owner said yes (scripts/workspace.py)."""
    cm = f"{ad}/CLAUDE.md"
    with open(cm) as fh: text = fh.read()
    if CLAUDE_IMPORT in [l.strip() for l in text.splitlines()]: return False
    with open(cm, "a") as fh: fh.write(("" if text.endswith("\n") or not text else "\n") + "\n" + CLAUDE_IMPORT + "\n")
    return True


def make_workspace(product, ad, owner=""):
    """Create the workspace layout in `ad` (made if missing), filling only what is absent: it is safe to run again over a
    workspace in use, and never overwrites the user's data. CLAUDE.md is the user's file: a small one is written when there
    is none, and an existing one is never edited here (`lane init` and `lane doctor --fix` ask before adding the import
    line). Returns the list of what was made, by its path in the workspace: empty when everything was already there."""
    ad = os.path.realpath(ad)
    data = f"{ad}/.repolane"
    made = []
    for d in (f"{data}/registry/lanes", f"{data}/memory", f"{data}/knowledge", f"{data}/repos", f"{data}/cache", f"{ad}/lanes"):
        if not os.path.isdir(d):
            os.makedirs(d, exist_ok=True); made.append(os.path.relpath(d, ad) + "/")

    def seed(path, text, label=""):
        if not os.path.exists(path): _write(path, text); made.append(os.path.relpath(path, ad) + label)

    def template(name):
        with open(f"{product}/templates/{name}") as fh: return fh.read()

    seed(f"{data}/config.yml", template("config.yml").replace("{{owner}}", owner or "YOUR NAME"))
    seed(f"{data}/registry/repos.yaml", "# Source of truth for what this workspace manages.\n"
                                        "# Add repos with:  lane add <git-url> [name]\n# status: active | archived\nrepos:\n")
    seed(f"{data}/memory/MEMORY.md", "# Memory Index — applies everywhere (per-repo memory lives in the subfolders)\n")
    try:
        with open(f"{product}/knowledge/preferences.md.example") as fh: seed(f"{data}/knowledge/preferences.md", fh.read())
    except OSError:
        pass
    seed(f"{data}/env.sh", template("env.sh"))
    seed(f"{ad}/CLAUDE.md", "# My workspace\n\nRepolane's rules for every session in this folder:\n\n" + CLAUDE_IMPORT + "\n",
         " (it imports .repolane/REPOLANE.md)")
    if merge_settings(f"{ad}/.claude/settings.json", workspace_hooks(), WORKSPACE_ALLOW):
        made.append(".claude/settings.json (Repolane's hooks)")
    if set_statusline(ad, replace_stale=False):
        made.append(f".claude/settings.json (status line: {STATUSLINE_CMD})")
    if refresh(product, ad):
        made.append(f".repolane/REPOLANE.md, .repolane/LANE.md (version {product_version(product)})")
    return made


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "refresh" and len(argv) == 4:
        refresh(os.path.realpath(argv[2]), os.path.realpath(argv[3])); return 0
    if cmd == "make-workspace" and len(argv) in (4, 5):
        make_workspace(os.path.realpath(argv[2]), argv[3], argv[4] if len(argv) == 5 else ""); print(os.path.realpath(argv[3])); return 0
    if cmd == "lane-context" and len(argv) == 3:
        here = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
        sys.stdout.write(Roots(here).lane_context(argv[2])); return 0
    if cmd == "paths" and len(argv) in (2, 3):
        here = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
        for k, v in Roots(here, start=argv[2] if len(argv) == 3 else None).paths().items(): print(f"{k}={v}")
        return 0
    sys.stderr.write(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
