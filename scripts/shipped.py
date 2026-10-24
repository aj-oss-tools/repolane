"""The paths a git clone of this release ships, which `lane migrate` removes from a clone (scripts/migrate.py).

The release history (every 0.9.x tree, with its blob ids) is committed in scripts/migrate-manifest.json; the paths of the
release being built are not, so adding or removing a file never needs a regenerated manifest. They are written at build
time (hatch_build.py) into the package as scripts/migrate-head.json, from:
  1. `git ls-files` (tracked, plus new files git does not ignore) when the build runs in a git checkout of Repolane;
  2. otherwise a scripts/migrate-head.json already in the tree (a source distribution carries the one its build wrote);
  3. otherwise every file in the tree (a copy of the checkout's files, as the tests build from).
Run from a checkout, migrate.py takes the same list straight from the tree (head_paths).
"""
import json
import os
import subprocess

HEAD_FILE = "scripts/migrate-head.json"
MANIFEST = "scripts/migrate-manifest.json"
SKIP_DIRS = {".git", "__pycache__", "dist", "build", ".venv", "node_modules"}
SKIP_FILES = {".DS_Store", HEAD_FILE}


def _git_paths(root):
    try:
        top = subprocess.run(["git", "-C", root, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
        if top.returncode != 0 or os.path.realpath(top.stdout.strip()) != os.path.realpath(root):
            return None
        out = subprocess.run(["git", "-C", root, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                             capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return {p for p in out.split("\0") if p}


def _walk_paths(root):
    out = set()
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS and not x.endswith(".egg-info")]
        for f in files:
            if f.endswith(".pyc"): continue
            out.add(os.path.relpath(os.path.join(d, f), root).replace(os.sep, "/"))
    return out


def head_paths(root):
    """Sorted list of the paths this release ships, decided as the module docstring says."""
    paths = _git_paths(root)
    if paths is None:
        try:
            with open(os.path.join(root, HEAD_FILE)) as fh: return json.load(fh)["paths"]
        except (OSError, ValueError, KeyError, TypeError):
            paths = _walk_paths(root)
    paths = {p for p in paths if os.path.basename(p) not in SKIP_FILES and p not in SKIP_FILES}
    paths.add(MANIFEST)
    return sorted(paths)


def head_json(root):
    return json.dumps({"paths": head_paths(root)}, indent=1) + "\n"
