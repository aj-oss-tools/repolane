"""Bundle the product files into the wheel under repolane/_product/, as they sit in a clone.

hatchling's own include/exclude cannot do this: `sources` maps every path through one prefix, and force-include ignores
exclude patterns (so a developer's scripts/local/ or a __pycache__ would ship). This walks the paths listed in
pyproject.toml ([tool.hatch.build.targets.wheel.hooks.custom] include/exclude) and force-includes each file that is left.

It also writes scripts/migrate-head.json, the paths a git clone of the release being built ships (scripts/shipped.py says
where they come from), into the wheel and the source distribution, so no committed list has to follow every file added.
"""
import fnmatch
import os
import sys
import tempfile

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class ProductBundle(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def head_file(self):
        sys.path.insert(0, os.path.join(self.root, "scripts"))
        try:
            import shipped
        finally:
            sys.path.pop(0)
        d = tempfile.mkdtemp(prefix="repolane-build-")
        path = os.path.join(d, "migrate-head.json")
        with open(path, "w") as fh: fh.write(shipped.head_json(self.root))
        return path, shipped.HEAD_FILE

    def initialize(self, version, build_data):
        if self.target_name not in ("wheel", "sdist"):
            return
        head, rel_head = self.head_file()
        if self.target_name == "sdist":
            build_data["force_include"][head] = rel_head
            return
        build_data["force_include"][head] = f"repolane/_product/{rel_head}"
        include, exclude = self.config.get("include", []), self.config.get("exclude", [])
        dropped = lambda rel: any(fnmatch.fnmatch(rel, p) or rel.startswith(p.rstrip("/") + "/") for p in exclude)
        for top in include:
            src = os.path.join(self.root, top)
            if os.path.isfile(src):
                files = [top]
            elif os.path.isdir(src):
                files = [os.path.relpath(os.path.join(d, f), self.root) for d, _, fs in os.walk(src) for f in fs]
            else:
                raise FileNotFoundError(f"product file listed in pyproject.toml is missing: {top}")
            for rel in sorted(files):
                rel = rel.replace(os.sep, "/")
                if not dropped(rel):
                    build_data["force_include"][os.path.join(self.root, rel)] = f"repolane/_product/{rel}"
