"""Claude Code. The hook protocol is here; settings and installed files are in claude_setup, loaded only when needed
(the guard runs this module on every tool call and never installs anything)."""
import glob
import json
import os
import re

from agents.base import (AgentAdapter, Capability, Decision, Event, Reply, Session, ToolCall, ToolKind,
                         LANE_ENTER, OTHER, POST_TOOL, PRE_TOOL)

# hook_event_name -> the word `lane hook` takes, which is also the event kind
HOOK_EVENTS = {"SessionStart": "session-start", "PreToolUse": "pre-tool-use", "PostToolUse": "post-tool-use",
               "UserPromptSubmit": "user-prompt-submit", "PreCompact": "pre-compact", "SessionEnd": "session-end",
               "WorktreeCreate": "worktree-create", "WorktreeRemove": "worktree-remove"}
_EVENT_NAMES = {v: k for k, v in HOOK_EVENTS.items()}
TOOL_KINDS = {"Bash": ToolKind.SHELL, "Read": ToolKind.READ, "Edit": ToolKind.WRITE, "Write": ToolKind.WRITE,
              "MultiEdit": ToolKind.WRITE, "NotebookEdit": ToolKind.WRITE, "Grep": ToolKind.SEARCH, "Glob": ToolKind.LIST,
              "EnterWorktree": ToolKind.ENTER_LANE}
_PRE_TOOL_TEXT = re.compile(r'"hook_event_name"\s*:\s*"PreToolUse"')
_STRING_FIELDS = ("command", "file_path", "notebook_path", "path", "name", "pattern", "glob", "type")
_PATH_FIELDS = ("file_path", "notebook_path", "path")


def _plain(ti):
    return {k: (v if isinstance(v, (str, dict, list)) else str(v)) for k, v in ti.items()}


def _tool_call(name, ti):
    kind = TOOL_KINDS.get(name, ToolKind.OTHER) if isinstance(name, str) else ToolKind.OTHER
    return ToolCall(kind, name, ti.get("command", "") if kind is ToolKind.SHELL else "",
                    tuple(ti[k] for k in _PATH_FIELDS if ti.get(k)),
                    ti.get("file_path") or ti.get("notebook_path") or "", ti.get("path") or "",
                    ti.get("pattern") or "", ti.get("glob") or "", ti.get("type") or "",
                    ti.get("name") if isinstance(ti.get("name"), str) else "")


def _pre_tool(data):
    name, ti = data.get("tool_name"), data.get("tool_input")
    if not isinstance(name, str) or not (ti is None or isinstance(ti, dict)): return None
    ti = ti or {}
    if any(ti.get(k) is not None and not isinstance(ti[k], str) for k in _STRING_FIELDS): return None
    return _tool_call(name, _plain(ti))


def _post_tool(data):
    ti = data.get("tool_input") or {}
    if not isinstance(ti, dict): ti = {}
    ti = _plain(ti)
    if not isinstance(ti.get("file_path"), (str, type(None))) or not isinstance(ti.get("notebook_path"), (str, type(None))): return None
    return _tool_call(data.get("tool_name", ""), ti)


class ClaudeAdapter(AgentAdapter):
    name = "claude"
    capabilities = frozenset(Capability) - {Capability.CONVERSATION_LEDGER}
    rules_file = "CLAUDE.md"
    config_dir = ".claude"
    resume_hint = "launch claude inside its worktree, then `claude --resume <id>`"
    launch = "claude"

    def claims_pre_tool(self, raw):
        return bool(_PRE_TOOL_TEXT.search(raw))

    def parse_event(self, raw, hint=None):
        try: data = json.loads(raw)
        except Exception:
            return Event(PRE_TOOL, malformed=True) if self.claims_pre_tool(raw) else None
        if not isinstance(data, dict): return None
        name = data.get("hook_event_name")
        kind = HOOK_EVENTS.get(name, OTHER) if isinstance(name, str) else OTHER
        cwd = data.get("cwd")
        malformed = kind == PRE_TOOL and cwd is not None and (not isinstance(cwd, str) or "\x00" in cwd)
        cwd = cwd if isinstance(cwd, str) and cwd and "\x00" not in cwd else None
        tool = _pre_tool(data) if kind == PRE_TOOL else _post_tool(data) if kind == POST_TOOL else None
        return Event(kind, cwd, data.get("session_id"), tool, data.get("name", "") if kind == LANE_ENTER else "", malformed)

    def format_decision(self, event, d):
        if d.kind == Decision.REFUSE: return Reply(stderr=d.text, code=1)
        if d.kind == Decision.ENTER: return Reply(stdout=d.text, stderr=d.context)
        if d.kind == Decision.NONE: return Reply()
        out = {"hookEventName": _EVENT_NAMES[event]}
        if d.kind == Decision.DENY: out.update(permissionDecision="deny", permissionDecisionReason=d.text)
        elif d.kind == Decision.ALLOW:
            out["permissionDecision"] = "allow"
            if d.context: out["additionalContext"] = d.context
        elif d.kind == Decision.CONTEXT: out["additionalContext"] = d.text
        else: raise ValueError(d.kind)
        return Reply(stdout=json.dumps({"hookSpecificOutput": out}))

    def repo_rules(self, root):
        return (f"{root}/CLAUDE.md", f"{root}/.claude/CLAUDE.md"), f"{root}/.claude/rules"

    def is_session_config(self, realpath):
        return os.path.basename(realpath).startswith("settings") and os.path.basename(os.path.dirname(realpath)) == ".claude"

    def tidy_transcripts(self, session_id, ad, repos):
        # Keep every transcript in exactly one project folder, under its repo. A conversation resumed from the lane root
        # may get its continuation written under the root's project folder; if the same id also exists under a repos/<repo>
        # folder, move the newer file into the repo folder and park the older one.
        sid = session_id
        proj = os.path.expanduser("~/.claude/projects")
        root_f = f"{proj}/{_slug(ad)}/{sid}.jsonl"
        if not (sid and os.path.exists(root_f)): return None
        # a mirror's project folder: the slug of repos/<repo> (under .repolane/ in a workspace)
        others = glob.glob(f"{proj}/{_slug(repos)}-*/{sid}.jsonl")
        if len(others) != 1: return None
        repo_f = others[0]
        newer, older = (root_f, repo_f) if os.path.getmtime(root_f) >= os.path.getmtime(repo_f) else (repo_f, root_f)
        os.replace(older, older + ".superseded")
        if newer == root_f: os.replace(root_f, repo_f)
        return f"{sid}: kept newest under {os.path.dirname(repo_f)}; older -> .superseded"

    def session_dir(self, folder):
        return f"{os.path.expanduser('~')}/.claude/projects/{_slug(folder)}"

    def sessions(self, folders):
        import datetime
        rows = []
        for folder in folders:
            for f in glob.glob(f"{self.session_dir(folder)}/*.jsonl"):
                sid = os.path.basename(f)[:-6]; first = None; last = os.path.getmtime(f); turns = 0
                with open(f) as fh:
                    for l in fh:
                        try: d = json.loads(l)
                        except: continue
                        ts = d.get("timestamp")
                        if ts:
                            try: last = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
                            except Exception: pass
                        if d.get("type") == "user":
                            c = d.get("message", {}).get("content")
                            if isinstance(c, str) and not c.startswith("<"): turns += 1; first = first or c.strip().replace("\n", " ")[:90]
                if first: rows.append(Session(last, sid, turns, first))
        rows.sort(reverse=True)
        return rows

    def session_count(self, folder):
        return len(glob.glob(f"{self.session_dir(folder)}/*.jsonl"))

    def session_owner(self, session_id, repos):
        # the project folder is named after the mirror's path, so compute it rather than assume it. transcript_path in the
        # hook input is derived from cwd, not from where the file lives: do not use it.
        import locale
        pre = f"{os.path.expanduser('~')}/.claude/projects/{_slug(repos)}-"
        found = glob.glob(f"{glob.escape(pre)}*/{glob.escape(session_id)}.jsonl")
        if not found: return ""
        try: locale.setlocale(locale.LC_COLLATE, "")   # the order `ls` lists them in
        except locale.Error: pass
        return min(found, key=locale.strxfrm)[len(pre):].split("/")[0]

    def session_start_input(self, raw):
        try: d = json.loads(raw)
        except Exception: d = {}
        return d.get("source", "startup"), d.get("session_id", "-"), d.get("cwd", "-")

    def session_start_reply(self, context, screen):
        return json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}, "systemMessage": screen})

    def signature_dir(self, mirror):
        """The folder the board watches to see whether a mirror's sessions changed. It does not slug dots, unlike the folder
        Claude Code really uses: kept as it has always been read."""
        return os.path.expanduser("~/.claude/projects/") + mirror.replace("/", "-").replace("_", "-")

    # ---- installing: claude_setup holds the settings wiring
    def install_workspace(self, product, ad, seed):
        from agents import claude_setup
        return claude_setup.install_workspace(product, ad, seed)

    def refresh_workspace(self, product, ad):
        from agents import claude_setup
        claude_setup.refresh_workspace(product, ad)

    def install_lane(self, layout, folder, lane_id, memory):
        from agents import claude_setup
        return claude_setup.install_lane(layout, folder, lane_id, memory)

    def install_lane_rules(self, layout, lane_dir, spec):
        from agents import claude_setup
        claude_setup.install_lane_rules(layout, lane_dir, spec)

    def grant_lane_folders(self, layout):
        from agents import claude_setup
        claude_setup.grant_lane_folders(layout)


def _slug(path):
    """How Claude Code names a project folder: everything but letters, digits and "-" becomes "-"."""
    return re.sub(r"[^A-Za-z0-9-]", "-", path)
