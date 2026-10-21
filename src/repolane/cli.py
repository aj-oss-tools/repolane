"""`lane` from an installed package: run the bundled dispatcher, with LANE_PRODUCT naming where it was installed.

The package carries the same product files a clone runs (lane, scripts/, templates, VERSION) under _product/, so there is
one implementation, not two. This launcher only says where those files are; which workspace a command acts on is still
decided the way it is today (LANE_WORKSPACE, or the product folder itself).
"""
import os
import shutil
import stat
import sys


def product_dir():
    return os.path.join(os.path.dirname(os.path.realpath(__file__)), "_product")


def ensure_executable(root):
    """A wheel records file modes, but not every installer keeps them, and the dispatcher starts every script by path: one
    that lost its +x bit is a 'permission denied' halfway through a command. Give the bit back to every file that starts
    with a shebang (as far as its read bits go). An install that cannot be changed is left as it is."""
    for d, _, files in os.walk(root):
        for f in files:
            p = os.path.join(d, f)
            try:
                mode = os.stat(p).st_mode
                if mode & stat.S_IXUSR:
                    continue
                with open(p, "rb") as fh:
                    if fh.read(2) != b"#!":
                        continue
                os.chmod(p, mode | ((mode & 0o444) >> 2))
            except OSError:
                pass


def run(args):
    prod = product_dir()
    lane = os.path.join(prod, "lane")
    if not os.path.isfile(lane):
        sys.stderr.write(f"repolane: the bundled product is missing ({lane}); reinstall the package\n")
        return 1
    ensure_executable(prod)
    env = dict(os.environ, LANE_PRODUCT=prod)
    # through bash, not the file's own +x: the dispatcher runs even where ensure_executable could not help
    bash = shutil.which("bash") or "/bin/bash"
    os.execve(bash, [bash, lane, *args], env)


def main():
    return run(sys.argv[1:])


# The long names the rules and the lane settings use (lane-memory, lane-brief, …): each is `lane <short>`, installed as a
# command of its own so a session in a workspace can run what REPOLANE.md and LANE.md tell it to. The same table as
# `lane install`'s stubs.
LONGFORM = {"lane-add": "add", "lane-audit": "audit", "lane-board": "board", "lane-brief": "brief", "lane-done": "done",
            "lane-env-check": "env", "lane-env-keys": "keys", "lane-find": "find", "lane-gh": "gh", "lane-help": "help",
            "lane-import": "import", "lane-init": "init", "lane-memory": "note", "lane-menu": "menu", "lane-merge": "merge",
            "lane-merge-plan": "plan", "lane-nested": "nested", "lane-park": "park", "lane-ref": "ref", "lane-resume": "resume",
            "lane-run": "run", "lane-sessions": "sessions", "lane-start": "start", "lane-status": "status", "lane-with": "with",
            "lane-workspace": "workspace", "guard-check": "doctor"}


def longform():
    name = os.path.basename(sys.argv[0])
    short = LONGFORM.get(name)
    if not short:
        sys.stderr.write(f"repolane: '{name}' is not one of the lane commands\n")
        return 2
    return run([short, *sys.argv[1:]])
