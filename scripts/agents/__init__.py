"""Which agent this product is driving. One adapter per agent; shared code asks it, never the agent's name.

Claude Code is the default. A workspace opts in to another with one line in .repolane/config.yml (`agent: antigravity`, written
by `lane init --agent antigravity`). Claude's files stay in such a workspace too, so a `claude` started there is still guarded.
A hook names its agent in its own command, so what answers a session is never decided by a file a session could reach.
No plugin loading: a new agent is a new module and one line here.
"""
import importlib
import re

DEFAULT = "claude"
REGISTERED = {"claude": ("agents.claude", "ClaudeAdapter"), "antigravity": ("agents.antigravity", "AntigravityAdapter")}


def get(name=DEFAULT):
    module, cls = REGISTERED[name]
    return getattr(importlib.import_module(module), cls)()


def configured(config_file):
    """The name a workspace's config.yml opts in to, or "" (Claude only). A clone has no such key."""
    try:
        with open(config_file) as fh: m = re.search(r"^agent:[ \t]*([\w-]+)[ \t]*$", fh.read(), re.M)
    except OSError:
        return ""
    return m.group(1) if m and m.group(1) in REGISTERED else ""
