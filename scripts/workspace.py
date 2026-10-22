#!/usr/bin/env python3
"""`lane init` and the workspace half of `lane doctor`, for an installed product (a workspace with a .repolane/ folder).

  lane init [<folder>] [--owner <name>] [--yes] [--git]
      Make <folder> (default: the current one) a Repolane workspace, or check that it already is one. Safe to run again:
      over a workspace in use it changes nothing and says so.
        --owner <name>  who the hooks address (asked for otherwise; with --yes, git's user.name)
        --yes           ask nothing: take the defaults, and add the import line to an existing CLAUDE.md
        --claude-home <dir>  Claude Code's folder (default ~/.claude, or CLAUDE_HOME), where the memory links go
        --git           make the folder a git repo, with a .gitignore for what is machine-local (lanes/, mirrors, cache)

The pieces (roots.py holds the layout itself: make_workspace, the hooks, the rule files):
  python3 -B workspace.py init [args]            what `lane init` runs in package mode (the dispatcher routes it here)
  python3 -B workspace.py doctor <ws> [--fix] [--yes] [--quiet]
                                                 the workspace checks `lane doctor` (scripts/hooks/guard-check) runs first
  python3 -B workspace.py link-mirror <ws> <repo> [--yes]
                                                 what `lane add` runs in a workspace: the mirror's memory link, asked first

CLAUDE.md is the user's file. A missing one is created with the import line; an existing one is only ever edited after
the owner says yes ("Add it? [Y/n]", or --yes). With no terminal to ask and no --yes it is left alone, and the output
says how to add the line by hand or with `lane doctor --fix`.

Every workspace is recorded in ~/.local/share/lane/planes.json (the registry `lane install` keeps for clones, under its
own "workspaces" key, so the clone dispatcher never routes to one), so `lane upgrade` can refresh each of them.
"""
import datetime
import json
import os
import re
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import roots  # noqa: E402

PRODUCT = os.path.realpath(os.environ.get("LANE_PRODUCT") or os.path.dirname(HERE))
TTY = sys.stdout.isatty()
G, Y, R, D, B, N = (("\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[1m", "\033[0m") if TTY else ("",) * 6)


def say(tag, color, text):
    print(f"  {color}{tag:<5}{N} {text}")


def can_ask():
    try:
        return sys.stdin.isatty() and sys.stderr.isatty()
    except (OSError, ValueError):
        return False


def ask(prompt):
    sys.stderr.write(prompt); sys.stderr.flush()
    line = sys.stdin.readline()
    return line.strip() if line else ""


def tilde(p):
    h = os.path.expanduser("~")
    return "~" + p[len(h):] if h and (p == h or p.startswith(h + os.sep)) else p


# ---------------------------------------------------------------------------------------------- the registry
def planes_file():
    return os.path.expanduser("~/.local/share/lane/planes.json")


def _load_planes():
    """planes.json as it is, or a fresh one. A file that is there but unreadable raises ValueError: it holds the clone
    planes too, and is never replaced by a guess."""
    p = planes_file()
    if not os.path.exists(p):
        return {"planes": {}, "active": None}
    with open(p) as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{p} is not a JSON object")
    data.setdefault("planes", {}); data.setdefault("active", None)
    return data


def is_registered(ad):
    try:
        return ad in (_load_planes().get("workspaces") or {})
    except (OSError, ValueError):
        return False


def register(ad):
    """Record the workspace (same file, same atomic write and layout as scripts/lane-planes.py). True when it was added."""
    data = _load_planes()
    ws = data.get("workspaces")
    if not isinstance(ws, dict): ws = data["workspaces"] = {}
    if ad in ws: return False
    ws[ad] = {"registered": datetime.datetime.now().astimezone().isoformat()}
    p = planes_file()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = f"{p}.tmp.{os.getpid()}"
    with open(tmp, "w") as fh:
        json.dump(data, fh, indent=2, sort_keys=True); fh.write("\n")
    os.replace(tmp, p)
    return True


# ------------------------------------------------------------------------------------ CLAUDE.md's import line
def offer_import(ad, assume_yes, from_doctor=False):
    """The one place CLAUDE.md is edited: show the line, ask (or take --yes), and say what happens if it is not added.
    Returns True when CLAUDE.md now imports REPOLANE.md."""
    state = roots.has_import(ad)
    if state is None:
        roots._write(f"{ad}/CLAUDE.md", "# My workspace\n\nRepolane's rules for every session in this folder:\n\n"
                     + roots.CLAUDE_IMPORT + "\n")
        say("made", G, "CLAUDE.md (it imports .repolane/REPOLANE.md)")
        return True
    if state:
        return True
    print(f"\n  Your CLAUDE.md does not load Repolane's rules yet. This line would be added at its end:\n\n"
          f"      {roots.CLAUDE_IMPORT}\n")
    if assume_yes:
        yes = True
    elif not can_ask():
        print("  Not added: there is no terminal to ask, and --yes was not given. Add the line above to CLAUDE.md yourself,")
        print("  or run: lane doctor --fix (it asks first). Until then Repolane's rules do not load in sessions here.\n")
        return False
    else:
        yes = ask("  Add it? [Y/n] ").lower() in ("", "y", "yes")
    if yes:
        roots.add_import(ad)
        say("fixed" if from_doctor else "made", G, f"CLAUDE.md now imports .repolane/REPOLANE.md (one line added at the end)")
        return True
    print("  Not added. Repolane's rules will not load in sessions here until CLAUDE.md has that line;")
    print("  lane doctor --fix can add it later.\n")
    return False


# ------------------------------------------------------------------------- Claude Code's memory folders, linked here
# Claude Code keeps a project's memory in ~/.claude/projects/<slug>/memory, the slug being the folder's path with every
# character outside A-Za-z0-9- turned into "-". Pointing that folder at the workspace keeps memory in .repolane/memory
# (versioned with the workspace) instead of in Claude Code's cache: the workspace root's, and each mirror's (lane add
# links those). Lanes need no link: their settings.local.json names autoMemoryDirectory. Anything under ~/.claude is
# outside the workspace, so it is only ever changed after the owner says yes (or --yes), never silently.


def claude_home():
    return os.path.realpath(os.path.expanduser(os.environ.get("CLAUDE_HOME") or "~/.claude"))


def project_slug(path):
    return re.sub(r"[^A-Za-z0-9-]", "-", path)


def wanted_links(ad):
    """(project folder, memory folder it should link to, label) for the root and every mirror."""
    proj = f"{claude_home()}/projects"
    out = [(f"{proj}/{project_slug(ad)}", f"{ad}/.repolane/memory", "the workspace root")]
    repos = f"{ad}/.repolane/repos"
    for r in sorted(os.listdir(repos)) if os.path.isdir(repos) else []:
        if os.path.exists(f"{repos}/{r}/.git"):
            out.append((f"{proj}/{project_slug(f'{repos}/{r}')}", f"{ad}/.repolane/memory/{r}", f"the {r} mirror"))
    return out


def link_state(proj, target):
    """('ok'|'missing'|'elsewhere'|'folder', detail)"""
    m = f"{proj}/memory"
    if os.path.islink(m):
        cur = os.readlink(m)
        full = os.path.realpath(os.path.join(proj, cur))
        return ("ok", cur) if full == os.path.realpath(target) else ("elsewhere", cur)
    if os.path.isdir(m):
        return "folder", ""
    if os.path.exists(m):
        return "elsewhere", "a file"
    return "missing", ""


def make_link(proj, target):
    """Link <proj>/memory to target. A real folder there has its notes copied in first (never over one that exists),
    exactly as a clone's `lane init` does; a link pointing elsewhere is replaced."""
    m = f"{proj}/memory"
    os.makedirs(proj, exist_ok=True)
    os.makedirs(target, exist_ok=True)
    if os.path.isdir(m) and not os.path.islink(m):
        for d, _, files in os.walk(m):
            rel = os.path.relpath(d, m)
            for f in files:
                dst = os.path.normpath(os.path.join(target, rel, f))
                if not os.path.exists(dst):
                    os.makedirs(os.path.dirname(dst), exist_ok=True); shutil.copy2(os.path.join(d, f), dst)
        shutil.rmtree(m)
    elif os.path.lexists(m):
        os.remove(m)
    os.symlink(target, m)


def pending_links(ad):
    return [(p, t, label, st, det) for p, t, label in wanted_links(ad) for st, det in [link_state(p, t)] if st != "ok"]


# A link the owner said no to is recorded in .repolane/declined.json ({"memory_links": ["memory", "memory/<repo>"]}, each
# the link's target under .repolane/), so lane init and lane add do not ask again and lane doctor shows a note instead of
# a failure. lane doctor --fix still offers it; a yes clears the entry.
DECLINED = ".repolane/declined.json"


def link_key(ad, target):
    return os.path.relpath(target, f"{ad}/.repolane")


def declined(ad):
    try:
        with open(f"{ad}/{DECLINED}") as fh: d = json.load(fh)
        return set(d.get("memory_links") or []) if isinstance(d, dict) else set()
    except (OSError, ValueError):
        return set()


def set_declined(ad, targets, on):
    """Record (on) or clear the owner's no for the links to these targets. A failure to write it only means asking again."""
    try:
        with open(f"{ad}/{DECLINED}") as fh: d = json.load(fh)
        if not isinstance(d, dict): d = {}
    except (OSError, ValueError):
        d = {}
    cur = set(d.get("memory_links") or [])
    keys = {link_key(ad, t) for t in targets}
    new = (cur | keys) if on else (cur - keys)
    if new == cur: return
    d["memory_links"] = sorted(new)
    try:
        roots._write(f"{ad}/{DECLINED}", json.dumps(d, indent=2, sort_keys=True) + "\n")
    except OSError:
        pass


def link_commands(pending):
    return [f"mkdir -p {shq(p)} && ln -sfn {shq(t)} {shq(p + '/memory')}" for p, t, *_ in pending]


def offer_links(ad, assume_yes, from_doctor=False, pending=None):
    """Show every memory link that is missing or wrong, ask once (or take --yes), and make them. Returns the number left
    undone (0 when everything is linked)."""
    pending = pending_links(ad) if pending is None else pending
    if not pending:
        return 0
    what = {"missing": "new link", "elsewhere": "replaces a link to {det}", "folder": "a folder of notes today: they are copied in first, nothing is lost"}
    print(f"\n  Claude Code keeps memory under {tilde(claude_home())}/projects. Repolane links it into the workspace, so it lives here:\n")
    for p, t, label, st, det in pending:
        print(f"      {tilde(p)}/memory -> {os.path.relpath(t, ad)}   ({label}; {what[st].format(det=det)})")
    print()
    if assume_yes:
        yes = True
    elif not can_ask():
        print(f"  Not linked: there is no terminal to ask, and --yes was not given. Nothing under {tilde(claude_home())} was changed.")
        print("  Run lane doctor --fix (it asks first), or link them yourself:")
        for c in link_commands(pending):
            print(f"      {c}")
        print()
        return len(pending)
    else:
        yes = ask(f"  Make these links under {tilde(claude_home())}? [Y/n] ").lower() in ("", "y", "yes")
    if not yes:
        set_declined(ad, [t for _, t, *_ in pending], True)
        print(f"  Not linked, and not asked again (lane doctor shows a note). Claude Code's memory for these folders stays in its")
        print(f"  own cache; lane doctor --fix can link it later.\n")
        return len(pending)
    set_declined(ad, [t for _, t, *_ in pending], False)
    left = 0
    for p, t, label, st, det in pending:
        try:
            make_link(p, t)
            say("fixed" if from_doctor else "made", G, f"memory of {label} linked: {tilde(p)}/memory -> {os.path.relpath(t, ad)}")
        except OSError as e:
            left += 1; say("warn", Y, f"could not link {tilde(p)}/memory ({e})")
    return left


def shq(s):
    import shlex
    return shlex.quote(s)


# ------------------------------------------------------------------------------------- the hooks reach lane?
def hook_reach(product, ad):
    """Run `lane hook ping` exactly as Claude Code runs a hook (through sh, from PATH, in the workspace, with
    CLAUDE_PROJECT_DIR and none of our own variables). Returns (ok, problem, fix)."""
    env = {k: v for k, v in os.environ.items() if k not in ("LANE_WORKSPACE", "LANE_PRODUCT", "LANE_BIN")}
    env["CLAUDE_PROJECT_DIR"] = ad
    found = shutil.which("lane", path=env.get("PATH", ""))
    loud = "every hook in this workspace runs `lane hook …`, so every hook fails and Claude Code runs tools UNGUARDED"
    if not found:
        bin_dir = os.environ.get("LANE_BIN", "")
        if bin_dir and os.path.isfile(os.path.join(bin_dir, "lane")):
            fix = f'put the folder lane is installed in on PATH (in your shell profile), then open a new terminal: export PATH="{bin_dir}:$PATH"'
        else:
            fix = "install Repolane so `lane` is on PATH (pipx install repolane, or uv tool install repolane)"
        return False, f"`lane` is not on PATH: {loud}", fix
    try:
        r = subprocess.run(["sh", "-c", "lane hook ping"], cwd=ad, env=env, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=60)
        out = r.stdout.strip().splitlines()
        parts = out[-1].split(" ", 3) if out else []
    except (OSError, subprocess.SubprocessError) as e:
        r, parts = None, []; detail = str(e)
    if r is None or r.returncode != 0 or len(parts) != 4 or parts[0] != "lane-hook":
        detail = ((r.stderr or r.stdout).strip().splitlines() or ["no answer"])[-1][:160] if r is not None else detail
        return (False, f"the `lane` on PATH ({found}) cannot run this workspace's hooks ({detail}): {loud}",
                "put the installed package's `lane` first on PATH (a clone's `lane install` dispatcher or an older install is in the way)")
    _, ver, mode, where = parts
    if mode != "workspace" or os.path.realpath(where) != ad:
        return (False, f"the `lane` on PATH ({found}) runs hooks against {where}, not this workspace: sessions here would be judged by the wrong rules",
                "put the installed package's `lane` first on PATH (a clone's `lane install` dispatcher is in the way)")
    want = roots.product_version(product)
    if ver != want:
        return (False, f"the `lane` on PATH ({found}) is version {ver}, but this is {want}: the hooks run {ver}",
                "upgrade or reinstall so there is one Repolane on PATH")
    return True, f"`lane` on PATH runs this workspace's hooks ({tilde(found)}, version {ver})", ""


# --------------------------------------------------------------------------------------------- the doctor
def lane_settings(ad):
    """Every settings.local.json a lane's sessions read: the lane folder's, and each worktree's in it."""
    out = []
    lanes = f"{ad}/lanes"
    for w in sorted(os.listdir(lanes)) if os.path.isdir(lanes) else []:
        d = f"{lanes}/{w}"
        if not os.path.isdir(d): continue
        out.append((w, f"{d}/.claude/settings.local.json"))
        for r in sorted(os.listdir(d)):
            if os.path.exists(f"{d}/{r}/.git"):
                out.append((w, f"{d}/{r}/.claude/settings.local.json"))
    return out


def doctor(ad, fix=False, assume_yes=False, quiet=False):
    """The workspace checks. Prints one line per check, with the fix for each failure; with `fix`, repairs what it safely
    can first. Returns the number of problems left."""
    ad = os.path.realpath(ad)
    problems = 0
    lines = []

    def report(ok, text, how=""):
        nonlocal problems
        if ok:
            lines.append(("ok", G, text, ""))
        else:
            problems += 1
            lines.append(("!!", R, text, how))

    def flush():
        if quiet: return
        for tag, color, text, how in lines:
            say(tag, color, text)
            if how: print(f"        {D}fix:{N} {how}")
        lines.clear()

    if not quiet: print(f"Workspace {tilde(ad)}:")
    # 1. the hook path: the loudest failure, so it comes first
    ok, text, how = hook_reach(PRODUCT, ad)
    report(ok, (text if ok else f"{B}{text}{N}"), how)
    flush()

    # 2. CLAUDE.md imports REPOLANE.md
    state = roots.has_import(ad)
    if state:
        report(True, "CLAUDE.md imports .repolane/REPOLANE.md")
    elif fix and not quiet:
        flush()
        if offer_import(ad, assume_yes, from_doctor=True): report(True, "CLAUDE.md imports .repolane/REPOLANE.md")
        else: report(False, "CLAUDE.md does not import .repolane/REPOLANE.md: Repolane's rules do not load here",
                     f"add the line {roots.CLAUDE_IMPORT} to CLAUDE.md, or run: lane doctor --fix")
    else:
        report(False, "CLAUDE.md does not import .repolane/REPOLANE.md: Repolane's rules do not load here" if state is False
               else "there is no CLAUDE.md: Repolane's rules do not load here",
               f"add the line {roots.CLAUDE_IMPORT} to CLAUDE.md, or run: lane doctor --fix (it asks first)")
    flush()

    # 3. the top settings run the expected `lane hook` commands
    top = f"{ad}/.claude/settings.json"
    want = roots.workspace_hooks()
    try:
        with open(top) as fh: cur = json.load(fh)
        if not isinstance(cur, dict): raise ValueError("not a JSON object")
        have, broken = roots.repolane_hooks(cur), ""
    except OSError:
        have, broken = {}, ""
    except ValueError as e:
        have, broken = None, str(e)
    if broken:
        report(False, f".claude/settings.json is not valid JSON ({broken[:80]}): no hook runs", "mend the file by hand, then run: lane doctor --fix")
    elif have == want:
        report(True, ".claude/settings.json runs Repolane's lane hook commands")
    elif fix:
        roots.merge_settings(top, want, roots.WORKSPACE_ALLOW)
        report(True, ".claude/settings.json: Repolane's hooks rewritten (your own keys and hooks kept)")
    else:
        missing = sorted(set(want) - set(have)); odd = sorted(e for e in have if have.get(e) != want.get(e) and e in want)
        extra = sorted(set(have) - set(want))
        detail = "; ".join(x for x in (missing and "missing: " + ", ".join(missing), odd and "not as expected: " + ", ".join(odd),
                                       extra and "unexpected: " + ", ".join(extra)) if x)
        report(False, f".claude/settings.json does not run the expected lane hook commands ({detail})", "run: lane doctor --fix")

    # 4. the rule files are the installed version's
    ver = roots.product_version(PRODUCT)
    if roots.rules_current(PRODUCT, ad):
        report(True, f".repolane/REPOLANE.md and LANE.md are version {ver}'s")
    elif fix:
        roots.refresh(PRODUCT, ad, force=True)
        report(True, f".repolane/REPOLANE.md and LANE.md rewritten from version {ver}")
    else:
        try:
            with open(f"{ad}/.repolane/version") as fh: rec = fh.read().strip() or "none"
        except OSError:
            rec = "none"
        what = (f"recorded version is {rec}, installed is {ver}" if rec != ver else "missing or edited by hand")
        report(False, f".repolane/REPOLANE.md / LANE.md are not the installed version's ({what})", "run: lane doctor --fix")

    # 5. registered, so `lane upgrade` refreshes it
    if is_registered(ad):
        report(True, f"registered in {tilde(planes_file())}")
    else:
        done = False
        if fix:
            try: register(ad); done = True
            except (OSError, ValueError) as e:
                report(False, f"could not register in {tilde(planes_file())} ({e})", "mend that file by hand, then run: lane doctor --fix")
        if done: report(True, f"registered in {tilde(planes_file())}")
        elif not fix: report(False, f"not registered in {tilde(planes_file())}: lane upgrade would not refresh it", "run: lane doctor --fix")

    # 6. each lane's sessions run the same hooks
    stale, missing_f, n = [], set(), 0
    for lane, p in lane_settings(ad):
        n += 1
        rel = os.path.relpath(p, ad)
        try:
            with open(p) as fh: cur = json.load(fh)
            if not isinstance(cur, dict): raise ValueError
        except OSError:
            missing_f.add(lane); continue
        except ValueError:
            stale.append((lane, rel, None)); continue
        if cur.get("hooks") != want: stale.append((lane, rel, cur))
    left = []
    for lane, rel, cur in stale:
        if fix and cur is not None:
            cur["hooks"] = want
            path = f"{ad}/{rel}"; tmp = f"{path}.tmp.{os.getpid()}"
            with open(tmp, "w") as fh: json.dump(cur, fh, indent=2)
            os.replace(tmp, path)
        else:
            left.append((lane, rel))
    fixed = len(stale) - len(left)
    if not n:
        report(True, "no lanes yet: no lane settings to check")
    elif not left and not missing_f:
        report(True, f"every lane's settings.local.json runs the current hooks ({n} file(s)" + (f", {fixed} rewritten)" if fixed else ")"))
    for lane, rel in left:
        report(False, f"{rel} does not run the current lane hook commands", f"run: lane doctor --fix (or: lane resume {lane})")
    for lane in sorted(missing_f):
        report(False, f"lanes/{lane}: a settings.local.json is missing, so a session there is unguarded", f"run: lane resume {lane}")

    # 7. Claude Code's memory for the root and each mirror is linked into .repolane/memory (asks before touching ~/.claude)
    # A link the owner declined (.repolane/declined.json) is a note, not a failure; --fix still offers it.
    pend = pending_links(ad)
    if not pend:
        n = len(wanted_links(ad))
        report(True, f"Claude Code's memory is linked into .repolane/memory ({n} folder(s) under {tilde(claude_home())}/projects)")
    else:
        left = len(pend)
        if fix and not quiet:
            flush()
            left = offer_links(ad, assume_yes, from_doctor=True, pending=pend)
        if not left:
            report(True, "Claude Code's memory is linked into .repolane/memory")
        else:
            no = declined(ad)
            for item in pending_links(ad):
                p, t, label, st, det = item
                why = {"missing": "not linked", "elsewhere": f"links to {det}", "folder": "is a folder of its own"}[st]
                if link_key(ad, t) in no:
                    lines.append(("note", Y, f"{tilde(p)}/memory ({label}) {why}: you said no to linking it. To link it later: "
                                  f"lane doctor --fix, or: {link_commands([item])[0]}", ""))
                else:
                    report(False, f"{tilde(p)}/memory ({label}) {why}: Claude Code's memory for it is not kept in the workspace",
                           "run: lane doctor --fix (it asks before changing anything under ~/.claude)")

    # 8. the status line (optional: missing is a note, a clone's stale path is a problem, the user's own is left alone)
    st = roots.statusline_state(ad)
    if st in ("stale", "none") and fix and roots.set_statusline(ad):
        report(True, f"status line: {roots.STATUSLINE_CMD} " + ("(a clone's statusline.sh path replaced)" if st == "stale" else "(added)"))
    elif st == "ours":
        report(True, f"status line: {roots.STATUSLINE_CMD}")
    elif st == "mine":
        report(True, "status line: your own command (left alone)")
    elif st == "stale":
        report(False, "the status line runs a clone's scripts/statusline.sh by path, which a workspace does not have",
               "run: lane doctor --fix")
    elif st == "none":
        lines.append(("note", Y, f"no status line set (optional): lane doctor --fix adds {roots.STATUSLINE_CMD}", ""))

    flush()
    if quiet and problems:
        print(f"!! workspace: {problems} problem(s) — run: lane doctor")
    elif not quiet:
        print()
    return problems


# ------------------------------------------------------------------------------------------------ lane init
GITIGNORE = ["/lanes/", "/.repolane/repos/", "/.repolane/cache/", "/.repolane/registry/.shared-cache/", "/.claude/settings.local.json", "/lane.code-workspace"]


def config_owner(ad):
    o = roots.Roots(PRODUCT, env={"LANE_WORKSPACE": ad}).owner()
    return "" if o == "the user" else o


def git_default_name():
    try:
        return subprocess.run(["git", "config", "user.name"], capture_output=True, text=True).stdout.strip()
    except OSError:
        return ""


def make_git(ad):
    made = []
    if not os.path.exists(f"{ad}/.git"):
        r = subprocess.run(["git", "init", "-q", ad], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("git init failed: " + (r.stderr.strip() or "?"))
        made.append("a git repo (nothing committed)")
    gi = f"{ad}/.gitignore"
    try:
        with open(gi) as fh: text = fh.read()
    except OSError:
        text = None
    have = set(l.strip() for l in (text or "").splitlines())
    add = [l for l in GITIGNORE if l not in have and l.rstrip("/") not in have and l.lstrip("/") not in have]
    if add:
        head = "" if text is None else ("" if text.endswith("\n") or not text else "\n") + "\n"
        with open(gi, "a") as fh:
            fh.write(head + "# Repolane: machine-local, made again by lane commands\n" + "\n".join(add) + "\n")
        made.append(".gitignore (" + ", ".join(add) + ")")
    return made


def init(argv):
    target, owner, assume_yes, want_git = None, None, False, False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--owner":
            if i + 1 >= len(argv): print("lane init: --owner needs a name", file=sys.stderr); return 2
            owner = argv[i + 1]; i += 1
        elif a == "--claude-home":
            if i + 1 >= len(argv): print("lane init: --claude-home needs a folder", file=sys.stderr); return 2
            os.environ["CLAUDE_HOME"] = os.path.abspath(os.path.expanduser(argv[i + 1])); i += 1
        elif a in ("--yes", "-y"): assume_yes = True
        elif a == "--git": want_git = True
        elif a in ("-h", "--help"):
            print(__doc__.split("\n\nThe pieces")[0]); return 0
        elif a.startswith("-"):
            print(f"lane init: unknown option {a}", file=sys.stderr); return 2
        elif target is None: target = a
        else:
            print("lane init: one folder at most", file=sys.stderr); return 2
        i += 1
    if not shutil.which("git"):
        print("lane init: git is required — install it, then run this again", file=sys.stderr); return 1
    target = os.path.abspath(os.path.expanduser(target or os.getcwd()))
    if os.path.exists(target) and not os.path.isdir(target):
        print(f"lane init: {target} is not a folder", file=sys.stderr); return 2
    os.makedirs(target, exist_ok=True)
    ad = os.path.realpath(target)
    outer = roots.find_workspace(ad)
    if outer and outer != ad:
        print(f"lane init: {ad} is inside the workspace {outer}; a workspace cannot hold another one.", file=sys.stderr)
        print(f"  run lane init {outer} (or lane doctor there), or pick a folder outside it", file=sys.stderr)
        return 2
    if ad == PRODUCT or (os.path.isfile(f"{ad}/lane") and os.path.isfile(f"{ad}/scripts/roots.sh")):
        print(f"lane init: {ad} is a copy of Repolane itself; run its own ./lane init there, or pick another folder", file=sys.stderr)
        return 2
    live = os.path.isdir(f"{ad}/.repolane")

    # who the hooks address: what config.yml already says wins; a different --owner does not silently rewrite it
    have_owner = config_owner(ad) if live else ""
    if have_owner:
        if owner and owner != have_owner:
            say("note", Y, f".repolane/config.yml already names {have_owner}; edit its owner: name: to change it")
        owner = have_owner
    elif not owner:
        d = git_default_name()
        if assume_yes or not can_ask(): owner = d or "the user"
        else: owner = ask(f"Your name, used when the hooks address you{f' [{d}]' if d else ''}: ") or d or "the user"

    print(("Checking" if live else "Setting up") + f" the workspace {tilde(ad)} for {owner}:")
    try:
        made = roots.make_workspace(PRODUCT, ad, owner)
    except ValueError as e:
        print(f"lane init: {ad}/.claude/settings.json is not valid JSON ({e}); mend it, then run lane init again", file=sys.stderr)
        return 1
    for m in made: say("made", G, m)
    imported = offer_import(ad, assume_yes)
    no = declined(ad)
    pend = [x for x in pending_links(ad) if link_key(ad, x[1]) not in no]
    skipped = len(pending_links(ad)) - len(pend)
    if skipped:
        say("note", Y, f"{skipped} memory link(s) you said no to are not offered again: lane doctor --fix offers them")
    unlinked = offer_links(ad, assume_yes, pending=pend)
    if len(pend) > unlinked: made.append("memory links")
    if want_git:
        try:
            for m in make_git(ad): say("made", G, m); made.append(m)
        except RuntimeError as e:
            say("warn", Y, str(e))
    try:
        if register(ad):
            m = f"registered in {tilde(planes_file())} (lane upgrade refreshes every registered workspace)"
            say("made", G, m); made.append(m)
    except (OSError, ValueError) as e:
        say("warn", Y, f"could not register in {tilde(planes_file())} ({e}); lane doctor --fix retries")
    if live and not made:
        print(f"  {D}nothing to do: {tilde(ad)} is already a workspace, and nothing was changed{N}")

    ok, text, how = hook_reach(PRODUCT, ad)
    if not ok:
        print(f"\n  {R}!!{N}    {B}{text}{N}\n        {D}fix:{N} {how}")
    print()
    if not live:
        print("Next: bring a repo in, then start a piece of work:\n\n"
              "  lane add https://github.com/<org>/<repo>.git\n  lane start <id> <repo>\n  claude\n")
        print("note: Claude can make mistakes. The hooks are a guardrail, not a sandbox: review what Claude changes.")
    if not imported:
        print("Repolane's rules will not load here until CLAUDE.md imports them: lane doctor --fix")
    if unlinked:
        print(f"Claude Code's memory is not linked into .repolane/memory yet: lane doctor --fix")
    return 0


def link_mirror(ad, name, assume_yes):
    """`lane add` in a workspace: link the new mirror's Claude Code memory into .repolane/memory/<name>, by the same rule as
    lane init (shown and asked; --yes accepts; no terminal changes nothing and prints the command; a recorded no is kept)."""
    ad = os.path.realpath(ad)
    target = f"{ad}/.repolane/memory/{name}"
    pend = [x for x in pending_links(ad) if os.path.realpath(x[1]) == os.path.realpath(target)]
    if not pend:
        return 0
    if link_key(ad, target) in declined(ad) and not assume_yes:
        print(f"  memory of the {name} mirror not linked under {tilde(claude_home())}: you said no before. lane doctor --fix offers it again.")
        return 0
    offer_links(ad, assume_yes, pending=pend)
    return 0


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "init":
        return init(argv[2:])
    if cmd == "link-mirror" and len(argv) >= 4:
        return link_mirror(argv[2], argv[3], bool({"--yes", "-y"} & set(argv[4:])))
    if cmd == "doctor" and len(argv) >= 3:
        flags = argv[3:]
        unknown = [f for f in flags if f not in ("--fix", "--yes", "-y", "--quiet")]
        if unknown:
            print(f"workspace.py doctor: unknown option {unknown[0]}", file=sys.stderr); return 2
        n = doctor(argv[2], fix="--fix" in flags, assume_yes=bool({"--yes", "-y"} & set(flags)), quiet="--quiet" in flags)
        return 1 if n else 0
    sys.stderr.write(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
