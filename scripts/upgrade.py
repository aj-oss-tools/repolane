#!/usr/bin/env python3
"""`lane upgrade` for an installed package: take the new release, then bring every registered workspace up to it.

  lane upgrade [--yes] [--drop-missing]
      1. upgrade the package the way it was installed: `pipx upgrade repolane` (a pipx install), `uv tool upgrade
         repolane` (a uv tool install); for any other install (pip in a venv) it prints the pip command to run
      2. refresh every workspace registered in ~/.local/share/lane/planes.json ("workspaces"), with the new version's
         files: the rule files and data migrations (the same refresh a workspace gets on its first use after an upgrade),
         Repolane's hooks in .claude/settings.json (your own keys and hooks kept), and every lane's settings.local.json
         and CLAUDE.md written again. Nothing you wrote is changed.
      A registered folder that is gone is skipped and reported, and you are asked whether to drop it from the registry
      (--yes or --drop-missing drops it; no terminal and neither flag keeps it). The exit status is non-zero when any
      workspace could not be refreshed, a missing one stays registered, or the package upgrade failed.
      Run inside a workspace that is not registered yet, it registers it first.
  lane upgrade --check
      the installed version against the newest on PyPI, and which registered workspaces are behind. Changes nothing.
  lane upgrade --refresh-only [--yes] [--drop-missing]
      step 2 only (what step 1 hands over to, run by the newly installed version)

In a git-clone install `lane upgrade` is scripts/lane-upgrade (a fast-forward of the clone).
"""
import json
import os
import shlex
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import roots  # noqa: E402
import workspace as ws  # noqa: E402
from workspace import say, tilde, can_ask, ask, G, Y, R, D, B, N  # noqa: E402

PRODUCT = ws.PRODUCT
PYPI_URL = os.environ.get("LANE_PYPI_URL") or "https://pypi.org/pypi/repolane/json"


def vkey(v):
    """A version as something sortable: 0.10.0 > 0.9.2 (numbers compared as numbers)."""
    out = []
    for p in str(v).replace("-", ".").split("."):
        out.append((0, int(p), "") if p.isdigit() else (1, 0, p))
    return out


# ------------------------------------------------------------------------------------------------ the package
def installer():
    """How this copy of Repolane was installed: ('pipx'|'uv'|'pip', the environment's folder). The launcher names the
    Python environment it runs in (LANE_PY_PREFIX): pipx leaves pipx_metadata.json there, uv tool leaves uv-receipt.toml."""
    prefix = os.environ.get("LANE_PY_PREFIX") or ""
    if prefix and os.path.isfile(os.path.join(prefix, "pipx_metadata.json")):
        return "pipx", prefix
    if prefix and os.path.isfile(os.path.join(prefix, "uv-receipt.toml")):
        return "uv", prefix
    return "pip", prefix


def pip_command(prefix):
    py = os.path.join(prefix, "bin", "python") if prefix and os.path.exists(os.path.join(prefix, "bin", "python")) else "python3"
    return f"{shlex.quote(py)} -m pip install --upgrade repolane"


def latest_on_pypi():
    """(version, None) or (None, why it could not be asked)."""
    try:
        with urllib.request.urlopen(PYPI_URL, timeout=10) as r:
            data = json.load(r)
        v = (data.get("info") or {}).get("version")
        if not v: return None, "PyPI's answer names no version"
        return str(v), None
    except (urllib.error.URLError, OSError, ValueError) as e:
        why = getattr(e, "reason", None) or e
        return None, f"could not reach PyPI ({why})"


def upgrade_package():
    """Run the matching upgrade command. Returns (ran_ok, what to tell the user)."""
    how, prefix = installer()
    if how == "pip":
        print("  This copy of Repolane was not installed with pipx or uv tool, so lane upgrade does not upgrade it itself.")
        print(f"  Upgrade it with the pip of the environment it is installed in:\n\n      {pip_command(prefix)}\n")
        print("  then run lane upgrade again to refresh your workspaces with the new version.\n")
        return True, ""
    cmd = ["pipx", "upgrade", "repolane"] if how == "pipx" else ["uv", "tool", "upgrade", "repolane"]
    if not shutil.which(cmd[0]):
        return False, f"{cmd[0]} is not on PATH, so it cannot upgrade Repolane: install it, or run `{' '.join(cmd)}` where it is"
    print(f"  {D}$ {' '.join(cmd)}{N}", flush=True)
    r = subprocess.run(cmd, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        return False, f"`{' '.join(cmd)}` failed (exit {r.returncode}); the installed version is unchanged"
    return True, ""


# ---------------------------------------------------------------------------------------------- the workspaces
def registered():
    try:
        return sorted((ws._load_planes().get("workspaces") or {}).keys())
    except (OSError, ValueError) as e:
        raise SystemExit(f"lane upgrade: cannot read {tilde(ws.planes_file())} ({e}); mend it by hand, then run lane upgrade again")


def forget(paths):
    data = ws._load_planes()
    w = data.get("workspaces") or {}
    for p in paths: w.pop(p, None)
    data["workspaces"] = w
    p = ws.planes_file(); tmp = f"{p}.tmp.{os.getpid()}"
    with open(tmp, "w") as fh:
        json.dump(data, fh, indent=2, sort_keys=True); fh.write("\n")
    os.replace(tmp, p)


def recorded_version(ad):
    try:
        with open(f"{ad}/.repolane/version") as fh: return fh.read().strip()
    except OSError:
        return ""


def rewrite_lanes(ad):
    """Every lane's settings.local.json and CLAUDE.md, written again by the same code `lane resume` uses (your own keys in
    settings.local.json are kept). Returns the number of lanes."""
    lanes = [d for d in sorted(os.listdir(f"{ad}/lanes")) if os.path.isdir(f"{ad}/lanes/{d}")] if os.path.isdir(f"{ad}/lanes") else []
    if not lanes: return 0
    env = {k: v for k, v in os.environ.items() if k not in ("LANE_PRODUCT", "LANE_WORKSPACE")}
    env.update(LANE_PRODUCT=PRODUCT, LANE_WORKSPACE=ad)
    script = ('source "$LANE_PRODUCT/scripts/lib.sh"; refresh_guards; '
              'for w in "$LANES"/*/; do i=$(basename "$w"); [ -f "$(lane_file "$i")" ] && write_lane_claude "$i"; done; true')
    r = subprocess.run(["bash", "-c", script], env=env, cwd=ad, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise RuntimeError("writing the lanes' settings failed: " + ((r.stderr or r.stdout).strip()[-300:] or f"exit {r.returncode}"))
    return len(lanes)


def refresh_one(ad):
    """Bring one workspace up to the installed version. Returns the line to report; raises on failure."""
    want = roots.product_version(PRODUCT)
    was = recorded_version(ad) or "none"
    parts = []
    if roots.refresh(PRODUCT, ad):
        parts.append(f"rule files rewritten for {want} (was {was})")
    else:
        parts.append(f"rule files already {want}'s")
    try:
        if roots.merge_settings(f"{ad}/.claude/settings.json", roots.workspace_hooks(), roots.WORKSPACE_ALLOW):
            parts.append("Repolane's hooks in .claude/settings.json updated (yours kept)")
    except ValueError as e:
        raise RuntimeError(f".claude/settings.json is not valid JSON ({str(e)[:80]}): mend it, then run lane upgrade --refresh-only")
    written, kept = roots.install_claude_files(PRODUCT, ad)
    if written: parts.append(f"{len(written)} of Repolane's slash command / agent file(s) in .claude/ updated")
    if kept: parts.append(f"kept your own {', '.join('.claude/' + k for k in kept)}")
    n = rewrite_lanes(ad)
    if n: parts.append(f"{n} lane(s)' settings written again")
    return "; ".join(parts)


def refresh_all(assume_yes, drop_missing):
    """Refresh every registered workspace. Returns the number of failures (a missing folder left registered is one)."""
    here = roots.find_workspace(os.environ.get("LANE_WORKSPACE") or os.getcwd())
    if here and not ws.is_registered(here):
        try:
            ws.register(here); say("made", G, f"registered {tilde(here)} (it is a workspace, and was not in {tilde(ws.planes_file())})")
        except (OSError, ValueError) as e:
            say("!!", R, f"could not register {tilde(here)} ({e})")
    names = registered()
    if not names:
        print("  No workspaces are registered: nothing to refresh (lane init makes one, and registers it).")
        return 0
    print(f"Refreshing {len(names)} registered workspace(s) with version {roots.product_version(PRODUCT)}:")
    failed, missing = 0, []
    for ad in names:
        if not os.path.isdir(f"{ad}/.repolane"):
            missing.append(ad)
            say("!!", R, f"{tilde(ad)}: " + ("the folder is gone" if not os.path.exists(ad) else "no longer a workspace (no .repolane/)") + ": skipped")
            continue
        try:
            say("ok", G, f"{tilde(ad)}: {refresh_one(ad)}")
        except (OSError, RuntimeError, ValueError) as e:
            failed += 1
            say("!!", R, f"{tilde(ad)}: not refreshed: {e}")
    if missing:
        drop = drop_missing or assume_yes
        if not drop and can_ask():
            drop = ask(f"\n  Drop the {len(missing)} missing folder(s) from {tilde(ws.planes_file())}? Nothing on disk is touched. [y/N] ").lower() in ("y", "yes")
        if drop:
            try:
                forget(missing); say("fixed", G, f"dropped {len(missing)} missing folder(s) from the registry")
                missing = []
            except (OSError, ValueError) as e:
                say("!!", R, f"could not change {tilde(ws.planes_file())} ({e})")
        else:
            print(f"  Kept in the registry. If the folder moved, run lane init in its new place; to drop the missing ones: lane upgrade --refresh-only --drop-missing")
    bad = failed + len(missing)
    print()
    if bad:
        print(f"{R}lane upgrade: {bad} workspace(s) not refreshed{N} (see above)")
    return bad


def check():
    cur = roots.product_version(PRODUCT)
    how, _ = installer()
    latest, why = latest_on_pypi()
    print(f"Installed: Repolane {cur} ({ {'pipx': 'pipx', 'uv': 'uv tool', 'pip': 'pip'}[how] } install)")
    rc = 0
    if latest is None:
        print(f"Latest:    unknown: {why}. Nothing was changed; try again when online.")
        rc = 1
    elif vkey(latest) > vkey(cur):
        print(f"Latest:    {latest} on PyPI: lane upgrade takes it")
    else:
        print(f"Latest:    {latest} on PyPI: up to date")
    try:
        names = registered()
    except SystemExit as e:
        print(str(e)); return 1
    behind = [a for a in names if os.path.isdir(f"{a}/.repolane") and not roots.rules_current(PRODUCT, a)]
    gone = [a for a in names if not os.path.isdir(f"{a}/.repolane")]
    print(f"Workspaces: {len(names)} registered" + (f", {len(behind)} not yet refreshed for {cur}" if behind else "")
          + (f", {len(gone)} missing" if gone else ""))
    for a in behind: print(f"  behind   {tilde(a)} (recorded {recorded_version(a) or 'none'})")
    for a in gone: print(f"  missing  {tilde(a)}")
    return rc


def main(argv):
    flags = set(argv)
    unknown = flags - {"--check", "--yes", "-y", "--drop-missing", "--refresh-only"}
    if unknown or "-h" in argv or "--help" in argv:
        if unknown and not ({"-h", "--help"} & flags): print(f"lane upgrade: unknown option {sorted(unknown)[0]}", file=sys.stderr)
        print(__doc__.split("\nIn a git-clone")[0], file=sys.stderr if unknown else sys.stdout)
        return 2 if unknown - {"-h", "--help"} else 0
    assume_yes = bool({"--yes", "-y"} & flags)
    if "--check" in flags:
        return check()
    rc = 0
    if "--refresh-only" not in flags:
        before = roots.product_version(PRODUCT)
        print(f"Upgrading Repolane (installed: {before}):")
        ok, why = upgrade_package()
        if not ok:
            say("!!", R, why); rc = 1
        elif installer()[0] != "pip":
            # the files this process was started from were just replaced: the new version refreshes the workspaces
            lane = os.path.join(os.environ.get("LANE_BIN") or "", "lane")
            if not os.path.isfile(lane): lane = shutil.which("lane") or ""
            if lane:
                sys.stdout.flush()
                args = [lane, "upgrade", "--refresh-only"] + [a for a in argv if a in ("--yes", "-y", "--drop-missing")]
                os.execve(lane, args, {**os.environ, "LANE_UPGRADED_FROM": before})
            say("!!", R, "cannot find the upgraded lane to finish with: run lane upgrade --refresh-only")
            return 1
    else:
        frm = os.environ.get("LANE_UPGRADED_FROM")
        now = roots.product_version(PRODUCT)
        if frm:
            print(f"  Repolane is now {now}" + (f" (was {frm})" if frm != now else " (already the newest)"))
    bad = refresh_all(assume_yes, "--drop-missing" in flags)
    return 1 if (bad or rc) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
