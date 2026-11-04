"""Which agent this product is driving. One adapter per agent; shared code asks it, never the agent's name.

Claude Code is the default and the only one registered. No plugin loading: a new agent is a new module and one line here.
"""
import importlib

DEFAULT = "claude"
REGISTERED = {"claude": ("agents.claude", "ClaudeAdapter")}


def get(name=DEFAULT):
    module, cls = REGISTERED[name]
    return getattr(importlib.import_module(module), cls)()
