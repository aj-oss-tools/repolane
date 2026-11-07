"""Antigravity's files in a folder: .agents/hooks.json and AGENTS.md, at the workspace root, in each lane root and in every worktree.
Hooks silently do not load otherwise: agy does not walk up across a worktree boundary, or out of a folder that is not in a git repo.
A file that is not Repolane's is never overwritten."""
import json
import os
import subprocess
import sys

from agents.antigravity import HOOK_FILE, HOOK_NAME, MARKER, RULES_FILE, _is_ours
from agents.base import AgentRefusal

CMD = "lane hook --agent antigravity "


def hooks():
    def h(event, timeout=30): return {"type": "command", "command": CMD + event, "timeout": timeout}
    def grouped(event): return [{"matcher": "*", "hooks": [h(event)]}]
    return {HOOK_NAME: {"SessionStart": [h("session-start", 60)], "PreToolUse": grouped("pre-tool-use"), "PostToolUse": grouped("post-tool-use"),
                        "PreInvocation": [h("user-prompt-submit")], "Stop": [h("turn-end")]}}


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w") as fh: fh.write(text)
    os.replace(tmp, path)


def _tracked(folder, rel):
    if not os.path.exists(f"{folder}/.git"): return False
    return subprocess.run(["git", "-C", folder, "ls-files", "--error-unmatch", rel], capture_output=True).returncode == 0


def _ours_hooks(path):
    try:
        with open(path) as fh: d = json.load(fh)
    except (OSError, ValueError):
        return False
    return isinstance(d, dict) and set(d) == {HOOK_NAME}


REFUSE_HOOKS = ("{where} has its own .agents/hooks.json. Repolane has to write that file for the guard to load, and it does not guess at "
                "merging someone else's hooks, whose commands would run on this machine. Nothing was overwritten. "
                "Remove it from the branch, or keep this repo out of an Antigravity workspace.")


def check_repo(mirror, ref):
    """Before a worktree is made: why this ref cannot be one, or None."""
    r = subprocess.run(["git", "-C", mirror, "cat-file", "-e", f"{ref}:{HOOK_FILE}"], capture_output=True)
    return REFUSE_HOOKS.format(where=f"{os.path.basename(mirror)} at {ref}") if r.returncode == 0 else None


def rules_text(product, lane_id, layout):
    with open(f"{product}/templates/antigravity/{'LANE' if lane_id else 'AGENTS'}.md") as fh: text = fh.read()
    if lane_id:
        head = (f"# Lane {lane_id}\nLane file: `{layout.lanes_dir}/{lane_id}.md`. Lane folder: `{layout.ad}/lanes/{lane_id}/`. "
                f"Memory: `{layout.memory}/<repo>/MEMORY.md`. Preferences: `{layout.knowledge}/preferences.md`.\n\n")
        text = head + text
    return f"{MARKER}\n{text}"


def install_folder_files(product, ad, lane_id, layout, folder):
    hp, rp = f"{folder}/{HOOK_FILE}", f"{folder}/{RULES_FILE}"
    if _tracked(folder, HOOK_FILE) or (os.path.exists(hp) and not _ours_hooks(hp)):
        raise AgentRefusal(REFUSE_HOOKS.format(where=folder))
    _write(hp, json.dumps(hooks(), indent=2) + "\n")
    # A repo's own AGENTS.md stays as it is. Its session still gets Repolane's rules, each turn, from the hook.
    if not _tracked(folder, RULES_FILE) and _is_ours(rp):
        _write(rp, rules_text(product, lane_id, layout))
    else:
        print(f"note: {folder} has its own {RULES_FILE}, which is kept. A session there gets Repolane's rules from the hook, each step, "
              f"and not up front.", file=sys.stderr)
    return [f"/{HOOK_FILE}", f"/{RULES_FILE}"]


def exclude(folder, rels):
    """Keep them out of git status, in a folder that is a repo of its own (a lane or worktree does this in lib.sh)."""
    if not os.path.exists(f"{folder}/.git"): return
    r = subprocess.run(["git", "-C", folder, "rev-parse", "--git-common-dir"], capture_output=True, text=True)
    gd = r.stdout.strip()
    if r.returncode or not gd: return
    ex = f"{os.path.join(folder, gd)}/info/exclude"
    os.makedirs(os.path.dirname(ex), exist_ok=True)
    try:
        with open(ex) as fh: have = fh.read().splitlines()
    except OSError:
        have = []
    with open(ex, "a") as fh:
        for x in rels:
            if x not in have: fh.write(x + "\n")


def check_folder(folder):
    """What is wrong with this folder's wiring, as sentences. Hooks that are not there fail silently, so this is the only alarm."""
    out = []
    hp, rp = f"{folder}/{HOOK_FILE}", f"{folder}/{RULES_FILE}"
    if not os.path.exists(hp):
        out.append(f"{HOOK_FILE} is missing: a session started here runs UNGUARDED")
    else:
        try:
            with open(hp) as fh: have = json.load(fh)
        except (OSError, ValueError):
            have = None
        if have != hooks(): out.append(f"{HOOK_FILE} is not the one Repolane wrote: a session started here may run unguarded")
    if not os.path.exists(rp): out.append(f"{RULES_FILE} is missing: a session started here does not get Repolane's rules up front")
    return out
