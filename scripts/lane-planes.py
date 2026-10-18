#!/usr/bin/env python3
"""Repolane's multi-plane registry helper.

Installed to ~/.local/share/lane/planes.py by `lane install` (see the `install)` case in this
checkout's own `lane`). Invoked by the stable ~/.local/bin/lane dispatcher — the one file that,
once installed, is never repointed at a specific checkout again (docs/concepts.md — "the clone
is the control plane" — describes the one-checkout model this sits alongside; a machine can now
have several registered planes at once, and this is what tells them apart). Safe to run by hand
too, but nothing depends on that.

The registry itself lives at ~/.local/share/lane/planes.json:

  {"planes": {"<name>": {"path": "<absolute-checkout-path>", "registered": "<ISO date>"}},
   "active": "<name-or-null>"}

Subcommands: resolve, list, use, register, unregister, doctor, find-by-path.

Resolution order (see resolve_ad and CONTRIBUTING.md's incident writeup): the plane whose path
contains the caller's cwd wins outright, over whatever is "active" — being physically inside a
project's directory tree always wins, which is the actual fix for the cross-contamination bug
this file exists to close.
"""
import datetime
import json
import os
import sys

REG_DIR = os.path.expanduser("~/.local/share/lane")
REG_FILE = os.path.join(REG_DIR, "planes.json")


def load():
    if not os.path.exists(REG_FILE):
        return {"planes": {}, "active": None}
    try:
        with open(REG_FILE) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"planes": {}, "active": None}
    data.setdefault("planes", {})
    data.setdefault("active", None)
    return data


def save(data):
    os.makedirs(REG_DIR, exist_ok=True)
    tmp = REG_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, REG_FILE)


def norm(p):
    return os.path.realpath(os.path.expanduser(p))


def inside(cwd, plane_path):
    cwd = norm(cwd)
    plane_path = norm(plane_path)
    return cwd == plane_path or cwd.startswith(plane_path + os.sep)


def cwd_matches(data, cwd):
    """The registered plane whose path contains cwd, preferring the deepest (most specific)
    match when more than one does (nested checkouts)."""
    best = None
    for name, info in data["planes"].items():
        p = info.get("path", "")
        if p and inside(cwd, p):
            if best is None or len(norm(p)) > len(norm(data["planes"][best]["path"])):
                best = name
    return best


def cmd_resolve(cwd):
    data = load()
    name = cwd_matches(data, cwd)
    if name:
        print(data["planes"][name]["path"])
        return 0
    active = data.get("active")
    if active and active in data["planes"]:
        print(data["planes"][active]["path"])
        return 0
    sys.stderr.write(
        "lane: no repolane control plane found here, and none is set active — "
        "run `lane install` from one, or `lane use <name>`\n"
    )
    return 1


def cmd_list(cwd):
    data = load()
    if not data["planes"]:
        print("no planes registered — run `lane install` from a checkout")
        return 0
    cwd_name = cwd_matches(data, cwd)
    active = data.get("active")
    for name in sorted(data["planes"]):
        info = data["planes"][name]
        flags = []
        if name == active:
            flags.append("active")
        if name == cwd_name:
            flags.append("cwd")
        flag = " [" + ", ".join(flags) + "]" if flags else ""
        print(f"  {name}{flag}\n    {info['path']}")
    return 0


def cmd_use(name, cwd):
    data = load()
    if name not in data["planes"]:
        sys.stderr.write(f"lane: no such plane '{name}' registered — run `lane use` for the list\n")
        return 1
    data["active"] = name
    save(data)
    print(f"active plane set to '{name}' ({data['planes'][name]['path']})")
    return 0


def cmd_unregister(name):
    """Forget a plane. Only the registry entry goes: the checkout itself is never touched. If it
    was the active plane there is none afterwards (guessing a replacement is how the wrong
    project's data got used once) -- `lane use <name>` picks one."""
    data = load()
    if name not in data["planes"]:
        sys.stderr.write(f"lane: no such plane '{name}' registered — `lane use` lists them\n")
        return 1
    path = data["planes"].pop(name).get("path", "")
    was_active = data.get("active") == name
    if was_active:
        data["active"] = None
    save(data)
    print(f"unregistered plane '{name}' ({path}) — the folder itself was not touched")
    if was_active:
        print("no active plane now — run `lane use <name>` to choose one")
    return 0


def cmd_register(name, path, make_active, force=False):
    data = load()
    path = norm(path)
    is_first = not data["planes"]
    existing = data["planes"].get(name)
    # Two different checkouts sharing a name (usually the auto-derived directory basename) used
    # to silently overwrite one another's registry entry -- the exact "wrong project's data"
    # failure this whole feature exists to close, just moved from the symlink axis to the name
    # axis. A name collision with a DIFFERENT path now refuses unless --force says otherwise.
    if existing and norm(existing.get("path", "")) != path and not force:
        print(f"COLLISION: '{name}' is already registered -> {existing.get('path')}", file=sys.stderr)
        print(f"           this would repoint it to -> {path}", file=sys.stderr)
        return 2
    data["planes"][name] = {
        "path": path,
        "registered": datetime.datetime.now().astimezone().isoformat(),
    }
    if is_first or make_active:
        data["active"] = name
    save(data)
    suffix = " (active)" if data["active"] == name else ""
    print(f"registered plane '{name}' -> {path}{suffix}")
    return 0


def cmd_find_by_path(path):
    """Used by `lane install`: is this checkout already registered under some name? Re-running
    install from the same checkout should update that entry, not pile up a duplicate under a
    second name."""
    data = load()
    path = norm(path)
    for name, info in data["planes"].items():
        if norm(info.get("path", "")) == path:
            print(name)
            return 0
    return 1


def cmd_doctor(cwd, this_path):
    """Piece 3's sanity checks: is this checkout registered at all, and if it is, does
    directory-aware resolution from inside it actually pick it (it always should — a mismatch
    here is a canary for a resolver bug, not something a normal user should ever see)."""
    data = load()
    this_path = norm(this_path)
    registered_name = None
    for name, info in data["planes"].items():
        if norm(info.get("path", "")) == this_path:
            registered_name = name
            break
    if registered_name is None:
        print("NOT_REGISTERED")
        return 0
    resolved_name = cwd_matches(data, cwd) or data.get("active")
    if resolved_name == registered_name:
        print("OK:" + registered_name)
    else:
        print(f"MISMATCH:{registered_name}:{resolved_name}")
    return 0


def main():
    args = sys.argv[1:]
    if not args:
        return cmd_resolve(os.getcwd())
    sub = args[0]
    if sub == "resolve":
        return cmd_resolve(args[1] if len(args) > 1 else os.getcwd())
    if sub == "list":
        return cmd_list(args[1] if len(args) > 1 else os.getcwd())
    if sub == "use":
        if len(args) < 2:
            sys.stderr.write("usage: planes.py use <name> [cwd]\n")
            return 2
        return cmd_use(args[1], args[2] if len(args) > 2 else os.getcwd())
    if sub == "unregister":
        if len(args) < 2:
            sys.stderr.write("usage: planes.py unregister <name>\n")
            return 2
        return cmd_unregister(args[1])
    if sub == "register":
        if len(args) < 3:
            sys.stderr.write("usage: planes.py register <name> <path> [--make-active] [--force]\n")
            return 2
        return cmd_register(args[1], args[2], "--make-active" in args[3:], "--force" in args[3:])
    if sub == "doctor":
        cwd = args[1] if len(args) > 1 else os.getcwd()
        this_path = args[2] if len(args) > 2 else os.getcwd()
        return cmd_doctor(cwd, this_path)
    if sub == "find-by-path":
        if len(args) < 2:
            sys.stderr.write("usage: planes.py find-by-path <path>\n")
            return 2
        return cmd_find_by_path(args[1])
    sys.stderr.write(f"planes.py: unknown subcommand {sub}\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
