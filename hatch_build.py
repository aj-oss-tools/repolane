"""Bundle the product files into the wheel under repolane/_product/, as they sit in a clone.

hatchling's own include/exclude cannot do this: `sources` maps every path through one prefix, and force-include ignores
exclude patterns (so a developer's scripts/local/ or a __pycache__ would ship). This walks the paths listed in
pyproject.toml ([tool.hatch.build.targets.wheel.hooks.custom] include/exclude) and force-includes each file that is left.
"""
import fnmatch
import os

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class ProductBundle(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version, build_data):
        if self.target_name != "wheel":
            return
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
