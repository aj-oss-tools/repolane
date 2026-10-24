#!/usr/bin/env bash
# .github/workflows/publish.yml: the assumptions PyPI's trusted publisher depends on (environment pypi, id-token
# write on the upload job only, no API token), the trigger that actually fires (a push to main that changes VERSION,
# not the tag tag-release.yml pushes with GITHUB_TOKEN), and the guards before the upload. Parses the YAML with PyYAML
# (or uv's copy of it); runs actionlint as well when it is installed.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
WF="$PRODUCT/.github/workflows/publish.yml"
assert "publish.yml exists" test -f "$WF"

if python3 -c 'import yaml' >/dev/null 2>&1; then py(){ python3 "$@"; }
elif command -v uv >/dev/null 2>&1; then py(){ uv run -q --no-project --with pyyaml python3 "$@"; }
elif [ -n "${CI:-}" ]; then bad "PyYAML (or uv) is required under CI"; finish; exit 1
else echo "  skip  no PyYAML and no uv here"; ok "skipped (no YAML parser)"; finish; exit 0
fi

out=$(py - "$WF" <<'EOF'
import re, sys, yaml
src = open(sys.argv[1]).read()
wf = yaml.safe_load(src)
on = wf.get("on", wf.get(True))          # YAML 1.1 reads a bare `on` as true
jobs = wf["jobs"]
pub = jobs.get("publish", {})
build = jobs.get("build", {})
steps = lambda j: j.get("steps", [])
uses = [s.get("uses", "") for j in jobs.values() for s in steps(j)]
runs = "\n".join(s.get("run", "") for s in steps(build))
pypa = [s for s in steps(pub) if s.get("uses", "").startswith("pypa/gh-action-pypi-publish@")]
env = pub.get("environment")
env = env.get("name") if isinstance(env, dict) else env
checks = {
  "triggers on a push to main": on.get("push", {}).get("branches") == ["main"],
  "only when VERSION changes": on.get("push", {}).get("paths") == ["VERSION"],
  "not on a tag push (GITHUB_TOKEN tags start no workflow)": "tags" not in on.get("push", {}),
  "workflow_dispatch asks for the version": on.get("workflow_dispatch", {}).get("inputs", {}).get("version", {}).get("required") is True,
  "the workflow's default token is read-only": wf.get("permissions") == {"contents": "read"},
  "the upload job runs in the pypi environment": env == "pypi",
  "the upload job may mint an OIDC token": pub.get("permissions", {}).get("id-token") == "write",
  "and reads contents only": pub.get("permissions", {}).get("contents") == "read",
  "no other job gets id-token": all("id-token" not in j.get("permissions", {}) for n, j in jobs.items() if n != "publish"),
  "upload waits for the build": pub.get("needs") in ("build", ["build"]),
  "upload is skipped when the version is on PyPI": "needs.build.outputs.publish == 'true'" in str(pub.get("if", "")),
  "one pypa/gh-action-pypi-publish step": len(pypa) == 1,
  "pinned to a commit sha": bool(pypa) and re.fullmatch(r"pypa/gh-action-pypi-publish@[0-9a-f]{40}", pypa[0]["uses"]) is not None,
  "no password or token given to it": bool(pypa) and not ({"password", "user"} & set(pypa[0].get("with", {}))),
  "no secret is referenced anywhere": "secrets." not in src,
  "every action is pinned to a version": all("@" in u for u in uses if u),
  "builds the sdist and the wheel with uv": "uv build" in runs,
  "checks them with twine": "twine check" in runs,
  "tests the built wheel": "REPOLANE_WHEEL=" in runs and "tests/t_package.sh" in runs,
  "compares the wanted version with VERSION": "VERSION" in runs and "WANTED" in runs,
  "asks PyPI whether the version exists": "pypi.org/pypi/repolane/" in runs,
}
for name, good in checks.items():
    print(("PASS " if good else "FAIL ") + name)
EOF
)
assert_eq "the workflow parses" 0 "$?"
while IFS= read -r line; do
  case "$line" in PASS\ *) ok "${line#PASS }" ;; FAIL\ *) bad "${line#FAIL }" ;; esac
done <<< "$out"
assert "every check reported" test "$(printf '%s\n' "$out" | grep -c '^PASS \|^FAIL ')" -ge 20

if command -v actionlint >/dev/null 2>&1; then
  actionlint "$WF" >/dev/null 2>&1; assert_eq "actionlint accepts publish.yml" 0 "$?"
fi

finish
