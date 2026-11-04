"""Claude Code's files: the hooks and approvals in its settings, the status line, the slash commands and agents copied into
.claude/, CLAUDE.md and its import line, and what a lane's settings.local.json says. Behind ClaudeAdapter, which loads this
only when it has something to install; scripts/roots.py passes these names on to the callers it has always had."""
import json
import os
import re

from agents.claude import HOOK_EVENTS


def _write(path, text):
    tmp = f"{os.path.dirname(path)}/.{os.path.basename(path)}.{os.getpid()}"
    with open(tmp, "w") as fh: fh.write(text)
    os.replace(tmp, path)   # a session reading it never sees half a file


# ------------------------------------------------------------------------------------------------ hooks as commands
# A workspace's settings name only these commands, never a file in the
# product: the installed `lane` is found on PATH, and the workspace from the session's folder.
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
                   "Bash(lane-memory show:*)", "Bash(lane-memory audit:*)", "Bash(lane status:*)", "Bash(lane brief:*)",
                   # a dispatcher session that enters a lane with EnterWorktree keeps these root permissions (a lane's
                   # settings.local.json only applies to a session started inside it), and LANE.md tells it to save the
                   # Goal and draft memories with these two: they write only that lane's file and the draft inbox, and the
                   # command itself refuses another lane's Goal from inside a lane. `lane-memory file` still asks.
                   "Bash(lane-memory goal:*)", "Bash(lane-memory draft:*)"]


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


# ------------------------------------------------------------------------------ slash commands and agents
# Repolane's slash commands (/status, /lane-brief, …) and agents (lane-manager, …) for a workspace are the product's
# templates/claude/{commands,agents}/*.md, copied into the workspace's .claude/ by name. .claude/ is the user's folder,
# so a file is only ever written when it is missing, or when it is still exactly what Repolane wrote there before (a
# previous version, never edited): .repolane/claude-files.json records each file Repolane wrote, with a hash of its
# text. A file of the user's by the same name, or one of ours they edited, is kept; one they deleted stays deleted.
CLAUDE_KINDS = ("commands", "agents")
CLAUDE_RECORD = "claude-files.json"


def _sha(text):
    import hashlib
    return hashlib.sha256(text.encode()).hexdigest()


def claude_files(product):
    """{"commands/status.md": text, …}: what the installed version puts in a workspace's .claude/."""
    out = {}
    for kind in CLAUDE_KINDS:
        d = f"{product}/templates/claude/{kind}"
        try: names = sorted(os.listdir(d))
        except OSError: continue
        for n in names:
            if n.endswith(".md") and os.path.isfile(f"{d}/{n}"):
                with open(f"{d}/{n}") as fh: out[f"{kind}/{n}"] = fh.read()
    return out


def _claude_record(ad):
    try:
        with open(f"{ad}/.repolane/{CLAUDE_RECORD}") as fh: rec = json.load(fh)
        return {k: v for k, v in rec.items() if isinstance(k, str) and isinstance(v, str)} if isinstance(rec, dict) else {}
    except (OSError, ValueError):
        return {}


def claude_files_state(product, ad):
    """[(path under .claude/, state)], state one of:
      ours     the installed version's, word for word
      old      what an earlier version wrote, never edited: a refresh replaces it
      missing  never written here: a refresh writes it
      mine     a file of the user's by that name, or one of ours they edited: kept
      removed  written once, deleted since: left deleted
      retired  an earlier version's file this one no longer ships, never edited: a refresh removes it"""
    want, rec, out = claude_files(product), _claude_record(ad), []
    for rel, text in want.items():
        try:
            with open(f"{ad}/.claude/{rel}") as fh: cur = fh.read()
        except OSError:
            out.append((rel, "removed" if rel in rec else "missing")); continue
        out.append((rel, "ours" if cur == text else "old" if rec.get(rel) == _sha(cur) else "mine"))
    for rel, h in sorted(rec.items()):
        if rel in want or "/" not in rel or rel.split("/", 1)[0] not in CLAUDE_KINDS or ".." in rel.split("/"): continue
        try:
            with open(f"{ad}/.claude/{rel}") as fh:
                if _sha(fh.read()) == h: out.append((rel, "retired"))
        except OSError:
            pass
    return out


def install_claude_files(product, ad):
    """Bring the workspace's copies of Repolane's slash commands and agents up to the installed version, by the rules
    above. Returns (written, kept): the paths written or removed, and the user's files left in their place."""
    want, rec = claude_files(product), _claude_record(ad)
    before, written, kept = dict(rec), [], []
    for rel, st in claude_files_state(product, ad):
        p = f"{ad}/.claude/{rel}"
        if st in ("missing", "old"):
            os.makedirs(os.path.dirname(p), exist_ok=True)
            _write(p, want[rel]); rec[rel] = _sha(want[rel]); written.append(rel)
        elif st == "ours":
            rec[rel] = _sha(want[rel])
        elif st == "retired":
            os.remove(p); rec.pop(rel, None); written.append(rel)
        elif st == "mine":
            kept.append(rel)
    if rec != before and os.path.isdir(f"{ad}/.repolane"):
        _write(f"{ad}/.repolane/{CLAUDE_RECORD}", json.dumps(rec, indent=2, sort_keys=True) + "\n")
    return written, kept


# ---------------------------------------------------------------------------------------- CLAUDE.md's import line
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


# ---------------------------------------------------------------------------------------------- putting them in place
def install_workspace(product, ad, seed):
    seed(f"{ad}/CLAUDE.md", "# My workspace\n\nRepolane's rules for every session in this folder:\n\n" + CLAUDE_IMPORT + "\n",
         " (it imports .repolane/REPOLANE.md)")
    made = []
    if merge_settings(f"{ad}/.claude/settings.json", workspace_hooks(), WORKSPACE_ALLOW):
        made.append(".claude/settings.json (Repolane's hooks)")
    if set_statusline(ad, replace_stale=False):
        made.append(f".claude/settings.json (status line: {STATUSLINE_CMD})")
    written, _ = install_claude_files(product, ad)   # the user's own files of those names are kept (lane init says which)
    if written:
        made.append(f".claude/commands, .claude/agents (Repolane's {len(written)} slash command and agent file(s))")
    return made


def refresh_workspace(product, ad):
    install_claude_files(product, ad)
    try:   # Repolane's hooks and approvals in .claude/settings.json (the user's own keys and hooks kept)
        merge_settings(f"{ad}/.claude/settings.json", workspace_hooks(), WORKSPACE_ALLOW)
    except (ValueError, OSError):
        pass   # a broken settings.json is the user's to mend; lane doctor says so


def install_lane(layout, d, id_, mem):
    """The permission guard for a session rooted at d: deny repos/ and every other lane. (`write_guard` in lib.sh.)"""
    import shlex
    ad, prod, mode, repos, lanes_dir, memory, knowledge, cache = layout
    os.makedirs(f"{d}/.claude", exist_ok=True)
    deny=[f"Read({repos}/**)",f"Edit({repos}/**)"]  # Edit covers Write/MultiEdit; Write() rules are ignored
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
    keep=[x for x in perm.get("deny",[]) if f"{repos}/" not in x and f"{ad}/lanes/" not in x]
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
    lf="/"+lanes_dir+"/"+id_+".md"
    # Reads of what the rules tell a session to open: memory/, knowledge/ and the draft inbox. Claude Code's Read rule also
    # covers Glob and Grep, so a session can search them too. Writes there are NOT allowed here: a session that entered a worktree
    # cannot use Edit/Write outside that folder at all (no setting lifts it), so they go through `lane-memory draft <slug> -` and
    # `lane-memory goal`, which write only this lane's file and the inbox and run without asking.
    OWN=(f"Read({lf})",f"Edit({lf})")+tuple(f"Read(/{x}/**)" for x in (memory,knowledge,f"{cache}/memory-inbox"))
    own_prefix=("Read(/"+lanes_dir+"/","Edit(/"+lanes_dir+"/")   # an earlier lane's rule, or one for another id, is dropped
    perm["allow"]=sorted({x for x in perm.get("allow",[]) if x not in RETIRED and not x.startswith(own_prefix)}
                         |{f"Bash({c}:*)" for c in READONLY_LANE+OWN_WRITES}
                         |{f"Bash({prod}/scripts/{c}:*)" for c in READONLY_LANE+OWN_WRITES}|set(OWN))   # CLAUDE.md tells a session to call them by absolute path
    cur["autoMemoryDirectory"]=mem
    if mode=="workspace":
        # A workspace names no product path at all: `lane hook <event>` finds the installed product on PATH and the
        # workspace from the session's folder, so an upgrade or a reinstall never leaves a hook pointing at nothing.
        cur["hooks"]=workspace_hooks()
    else:
        # A hook runs in Claude Code's environment, not ours, so when the two roots differ the command itself names them. When
        # they are one folder (a clone) it stays the bare path it has always been.
        pre="" if prod==ad else f"LANE_PRODUCT={shlex.quote(prod)} LANE_WORKSPACE={shlex.quote(ad)} "
        g=f"{pre}{prod}/scripts/hooks/guard.py"
        hk=lambda m=None,to=30:[{**({"matcher":m} if m else {}),"hooks":[{"type":"command","command":g,"timeout":to}]}]
        cur["hooks"]={"SessionStart":[{"matcher":"startup|resume|clear|compact|fork","hooks":[{"type":"command","command":f"{pre}{prod}/scripts/session-start --worktree","timeout":60}]}],
          "PreToolUse":hk("Bash|Edit|Write|MultiEdit|NotebookEdit|Read|EnterWorktree|Glob|Grep"),"PostToolUse":hk("Edit|Write|MultiEdit|NotebookEdit"),
          "WorktreeCreate":hk(None,120),"WorktreeRemove":hk(),
          "UserPromptSubmit":hk(),"PreCompact":hk(),"SessionEnd":hk()}
    json.dump(cur,open(p,"w"),indent=2)
    return [".claude/settings.local.json"]   # the guard stays out of git status in the worktree


def install_lane_rules(layout, lane_dir, spec):
    _, _, _, _, _, memory, knowledge, _ = layout
    with open(f"{lane_dir}/CLAUDE.md", "w", encoding="utf-8", errors="surrogateescape") as fh:
        fh.write(f"# Lane: {os.path.basename(lane_dir)}\n"
                 f"Spec and state: `{spec}` — read it first. Repos in scope are its `repos:` list; nothing else.\n"
                 f"Per-repo memory: `{memory}/<repo>/MEMORY.md`. Preferences: `{knowledge}/preferences.md`.\n")


def grant_lane_folders(layout):
    """Claude Code only edits inside the session's folder plus "additionalDirectories". A dispatcher session enters one repo of
    a lane, so the sibling repos must be listed. Root local settings: every worktree (hook still denies other lanes). Each
    worktree's local settings: its siblings."""
    import glob
    ad, prod, _, _, lanes_dir = layout[:5]
    wts=sorted(p for p in glob.glob(f"{ad}/lanes/*/*") if os.path.exists(f"{p}/.git"))
    def refs_of(lane):
        f=f"{lanes_dir}/{lane}.md"
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
    # A dispatcher session at the root that enters a lane keeps the root's permissions, and is told to save the Goal and draft
    # memories with lane-memory goal / draft (they write only that lane's file and the inbox; `lane-memory file` still asks).
    # A clone's .claude/settings.json is tracked and edited by lane init, so the approvals go into the root's local settings,
    # by bare name and by the absolute path the rules give.
    cur=json.load(open(put_root))
    al=cur.setdefault("permissions",{}).setdefault("allow",[])
    for c in ("lane-memory goal","lane-memory draft"):
        for r in (f"Bash({c}:*)",f"Bash({prod}/scripts/{c}:*)"):
            if r not in al: al.append(r)
    json.dump(cur,open(put_root,"w"),indent=2)
