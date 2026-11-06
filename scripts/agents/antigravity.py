"""Antigravity CLI (agy). Facts from real runs of 1.5.0 and the hook documentation inside the binary; docs/design/agent-adapters.md
has the evidence. What the code below rests on:
  - a hook's event is not in its body, so the hook command names it (`lane hook --agent antigravity <event>`, guard.py --event);
  - the hook's working directory is the .agents folder; the session's folder is workspacePaths[0];
  - exit 0 with EMPTY output on PreToolUse lets the tool run. `{}` and an unknown decision block it. So a tool call always gets a
    decision here, and "no objection" is `ask`, which leaves it to agy's own permission check;
  - `allow` does not skip agy's own check; `auto_approve` does;
  - PreInvocation fires before every model call. An ephemeralMessage reaches the model and is gone after that call, so it is
    restated each time; a userMessage stays in the conversation, so it would pile up; a systemMessage does not reach the model.
"""
import json
import os
import re

from agents.base import (AgentAdapter, Capability, Decision, Event, Reply, Session, ToolCall, ToolKind,
                         POST_TOOL, PRE_TOOL, PROMPT, SESSION_START)

HOOK_NAME = "repolane"
MARKER = "<!-- Written by Repolane; lane resume rewrites it. Put your own notes elsewhere. -->"
HOOK_FILE, RULES_FILE = ".agents/hooks.json", "AGENTS.md"
# (kind, the argument names that hold its path)
_READ = ("Path", "AbsolutePath", "File", "FilePath", "TargetFile")
_WRITE = ("Path", "AbsolutePath", "TargetFile", "File", "FilePath", "Source", "Destination")
TOOLS = {"read_file": (ToolKind.READ, _READ), "view_file": (ToolKind.READ, _READ), "view_file_outline": (ToolKind.READ, _READ),
         "view_code_item": (ToolKind.READ, _READ), "view_content_chunk": (ToolKind.READ, _READ), "read_notebook": (ToolKind.READ, _READ),
         "write_file": (ToolKind.WRITE, _WRITE), "edit_file": (ToolKind.WRITE, _WRITE), "write_to_file": (ToolKind.WRITE, _WRITE),
         "replace_file_content": (ToolKind.WRITE, _WRITE), "multi_replace_file_content": (ToolKind.WRITE, _WRITE),
         "edit_notebook": (ToolKind.WRITE, _WRITE), "file_change": (ToolKind.WRITE, _WRITE), "move": (ToolKind.WRITE, _WRITE),
         "delete_directory": (ToolKind.WRITE, _WRITE)}
_ROOT_KEYS = {"grep_search": ("SearchPath", "Path", "DirectoryPath"), "find": ("SearchDirectory", "Path", "DirectoryPath"),
              "list_directory": ("DirectoryPath", "Path", "SearchPath")}
# Tools whose arguments are prose or ids, named only so a sentence that mentions `.env` is not read as a path. Still `ask`.
# invoke_subagent runs in the folder `Workspace` names, so that one argument is judged.
_TEXT_TOOLS = {"ask_question": (), "send_message": (), "search_web": (), "define_subagent": (), "manage_subagents": (), "schedule": (),
               "list_resources": (), "invoke_subagent": ("Workspace",), "task_boundary": (), "notify_user": ()}
_PRE_APPROVED = ("lane-merge-plan", "lane-status", "lane-brief", "lane-find", "lane-menu", "lane-sessions", "lane-env-check", "lane-env-keys",
                 "lane-memory list", "lane-memory show", "lane-memory audit", "lane-memory goal", "lane-memory draft")
# What a rule in registry/rules.yaml may call a tool, beyond agy's own name and the neutral kind: Claude Code's names keep working.
_RULE_NAMES = {"Bash": ToolKind.SHELL, "Read": ToolKind.READ, "Edit": ToolKind.WRITE, "Write": ToolKind.WRITE, "MultiEdit": ToolKind.WRITE,
               "NotebookEdit": ToolKind.WRITE, "Grep": ToolKind.SEARCH, "Glob": ToolKind.LIST}
_WORDS = [(re.compile(p), r) for p, r in (
    (r'EnterWorktree name=\\?"<lane-id>\\?"', "a new session started in the lane (cd lanes/<lane-id> && agy)"),
    (r'EnterWorktree name=\\?"<id>\\?"', "a new session started in the lane (cd lanes/<id> && agy)"),
    (r'EnterWorktree name=\\?"([^"\\]+)\\?"', r"a new session started in the lane (cd lanes/\1 && agy)"),
    (r"NEVER ExitWorktree/EnterWorktree to change repo", "NEVER end the session to change repo"),
    (r"ExitWorktree keep", "end this session"),
    (r"EnterWorktree", "a new session started inside the lane"),
    (r"`?claude --resume <session-id>`?", "`agy --conversation <session-id>`"),
    (r"Claude Code", "Antigravity"), (r"CLAUDE\.md", "AGENTS.md"), (r"\.claude/settings\.json", ".agents/hooks.json"),
    (r"\bClaude\b", "the agent"), (r"\bcd lanes/(\S+) && claude\b", r"cd lanes/\1 && agy"))]
_INJECTED = "## lane"   # how session-start's text always begins
_TOKEN = re.compile(r"""[^\s=,;:"'`()<>\[\]{}|]+""")


def _strs(v, depth=0):
    if isinstance(v, str): yield v
    elif depth < 8 and isinstance(v, dict):
        for x in v.values(): yield from _strs(x, depth + 1)
    elif depth < 8 and isinstance(v, list):
        for x in v: yield from _strs(x, depth + 1)


def scan_paths(args, limit=500):
    """Everything in a tool's arguments that could be a path: a tool nobody has mapped is judged by what it names."""
    out = []
    for s in _strs(args):
        if re.match(r"[a-z][a-z0-9+.-]*://", s) and not s.startswith("file://"): continue
        for t in _TOKEN.findall(s.replace("file://", "") if s.startswith("file://") else s):
            if len(out) >= limit: return tuple(out)
            if "/" in t or t.startswith((".", "~")) or re.search(r"\.(pem|key|p12|pfx|p8|jks|keystore|kdbx)$|^id_(rsa|ed25519|ecdsa|dsa)$", t):
                out.append(t)
    return tuple(out)


def _tool_call(call):
    """None when it cannot be judged: then the guard refuses it."""
    if not isinstance(call, dict): return None
    name, args = call.get("name"), call.get("args")
    if not isinstance(name, str) or not (args is None or isinstance(args, dict)): return None
    args = args or {}
    def field(*keys):
        for k in keys:
            v = args.get(k)
            if v is not None and not isinstance(v, str): raise TypeError(k)
            if v: return v
        return ""
    try:
        if name == "run_command":
            cmd, cwd = field("CommandLine"), field("Cwd")
            if cwd: cmd = "(cd " + "'" + cwd.replace("'", "'\\''") + "' && " + cmd + "\n)"   # a working directory that moves nothing else
            return ToolCall(ToolKind.SHELL, name, cmd)
        if name in TOOLS:
            kind, keys = TOOLS[name]
            paths = tuple(args[k] for k in keys if isinstance(args.get(k), str) and args[k])
            field(*keys)
            return ToolCall(kind, name, "", paths, field(*keys))
        if name in _ROOT_KEYS:
            keys = _ROOT_KEYS[name]; root = field(*keys)
            pattern = field("Pattern") if name == "find" else ""
            includes = args.get("Includes")
            includes = " ".join(x for x in includes if isinstance(x, str)) if isinstance(includes, list) else includes if isinstance(includes, str) else ""
            kind = ToolKind.SEARCH if name == "grep_search" else ToolKind.LIST
            return ToolCall(kind, name, "", (root,) if root else (), "", root, pattern, includes, field("type"))
        if name in _TEXT_TOOLS:
            return ToolCall(ToolKind.UNKNOWN, name, "", tuple(args[k] for k in _TEXT_TOOLS[name] if isinstance(args.get(k), str) and args[k]))
    except TypeError:
        return None
    return ToolCall(ToolKind.UNKNOWN, name, "", scan_paths(args))


def _folder(paths):
    """The session's folder, or None when the body does not say."""
    if not isinstance(paths, list) or not paths or not isinstance(paths[0], str) or not paths[0] or "\x00" in paths[0]: return None
    return paths[0][len("file://"):] if paths[0].startswith("file://") else paths[0]


class AntigravityAdapter(AgentAdapter):
    name = "antigravity"
    capabilities = frozenset({Capability.RESUME, Capability.CONVERSATION_LEDGER})
    rules_file = RULES_FILE
    config_dir = ".agents"
    launch = "agy"
    label = "agy"
    resume_hint = "start agy in the lane's folder, then `agy --conversation <id>`"
    resume_command = "agy --conversation"
    cred_dirs = (".gemini",)
    protects_config_at_root = True
    pre_approved = _PRE_APPROVED

    def say(self, text):
        for p, r in _WORDS: text = p.sub(r, text)
        return text

    def claims_pre_tool(self, raw):
        return False   # the event is in the command, so the guard already knows

    def parse_event(self, raw, hint=None):
        kind = hint or ""
        try: data = json.loads(raw)
        except Exception: data = None
        if not isinstance(data, dict):
            return Event(PRE_TOOL, malformed=True) if kind == PRE_TOOL else None
        cwd = _folder(data.get("workspacePaths"))
        sid = data.get("rootConversationId") or data.get("conversationId")
        extra = {k: data.get(k) for k in ("invocationNum", "lastUserInput", "fullyIdle", "terminationReason")}
        if kind == PRE_TOOL:
            return Event(kind, cwd, sid, _tool_call(data.get("toolCall")), "", cwd is None, extra)
        return Event(kind, cwd, sid, _tool_call(data.get("toolCall")) if kind == POST_TOOL else None, "", False, extra)

    def format_decision(self, event, d):
        if d.kind == Decision.REFUSE: return Reply(stderr=d.text, code=1)
        if d.kind == Decision.ENTER: return Reply(stdout=d.text, stderr=d.context)
        if event == PRE_TOOL:
            if d.kind == Decision.DENY: return Reply(stdout=json.dumps({"decision": "deny", "reason": d.text}))
            if d.kind == Decision.ALLOW: return Reply(stdout=json.dumps({"decision": "auto_approve"}))
            if d.kind == Decision.NONE and d.context: return Reply(stdout=json.dumps({"decision": "auto_approve", "reason": "pre-approved"}))
            return Reply(stdout=json.dumps({"decision": "ask", "reason": "Repolane has no objection to this call."}))
        if d.kind == Decision.CONTEXT:
            return Reply(stdout=json.dumps({"injectSteps": [{"ephemeralMessage": d.text}]}))
        if d.kind == Decision.NONE: return Reply(stdout="{}")
        raise ValueError(d.kind)

    def rule_matches(self, word, tool):
        return AgentAdapter.rule_matches(self, word, tool) or _RULE_NAMES.get(word) is tool.kind

    def repo_rules(self, root):
        return (f"{root}/{RULES_FILE}", f"{root}/CLAUDE.md"), f"{root}/.agents/rules"

    def repo_rules_skip(self, path):
        return os.path.basename(path) == RULES_FILE and _is_ours(path)

    def is_session_config(self, realpath):
        if ".agents" in realpath.split("/"): return True
        return os.path.basename(realpath) == RULES_FILE and _is_ours(realpath)

    def tidy_transcripts(self, session_id, ad, repos):
        return None

    # ---- past conversations: not filed by folder, so the hook keeps a ledger under the workspace
    def record_session(self, event, lane, cache):
        x = event.extra or {}
        if x.get("invocationNum") not in (0, None) or not isinstance(event.session_id, str): return
        import time
        first = x.get("lastUserInput")
        # On a conversation's first step this is what session-start injected, not the person: session-start already recorded that turn.
        if isinstance(first, str) and first.startswith(_INJECTED) and event.kind == PROMPT: return
        rec = {"id": event.session_id, "lane": lane or "", "folder": event.cwd or "", "at": time.time(),
               "said": (first.strip().replace("\n", " ")[:90] if isinstance(first, str) else "")}
        try:
            with open(f"{cache}/conversations.jsonl", "a") as fh: fh.write(json.dumps(rec) + "\n")
        except OSError:
            pass

    def _ledger(self, folder):
        m = re.match(r"(.*)/lanes/([^/]+)", folder)
        if not m: return None, None
        return f"{m.group(1)}/.repolane/cache/conversations.jsonl", m.group(2)

    def session_dir(self, folder):
        return self._ledger(folder)[0] or ""

    def sessions(self, folders):
        rows = {}
        for path, lane in {self._ledger(f) for f in folders}:
            try:
                with open(path or "") as fh: lines = fh.readlines()
            except OSError:
                continue
            for l in lines:
                try: r = json.loads(l)
                except ValueError: continue
                if r.get("lane") != lane: continue
                s = rows.get(r["id"])
                rows[r["id"]] = Session(r.get("at", 0), r["id"], s.turns + 1 if s else 1, s.first if s else (r.get("said") or "(no text)"))
        return sorted(rows.values(), reverse=True)

    def session_count(self, folder):
        return len(self.sessions([folder]))

    def session_owner(self, session_id, repos):
        return ""

    def session_start_input(self, raw):
        try: d = json.loads(raw)
        except Exception: d = {}
        return "startup", d.get("conversationId", "-"), _folder(d.get("workspacePaths")) or "-"

    def session_start_reply(self, context, screen):
        # once per conversation, and it should stay: the one place a userMessage is right
        return json.dumps({"injectSteps": [{"userMessage": self.say(context)}]})

    def signature_dir(self, mirror):
        """The folder of the ledger: .repolane/repos/<repo> -> .repolane/cache. Every repo of the workspace shares it."""
        return f"{os.path.dirname(os.path.dirname(mirror))}/cache"

    # ---- installing
    def install_workspace(self, product, ad, seed):
        from agents import antigravity_setup
        antigravity_setup.exclude(ad, antigravity_setup.install_folder_files(product, ad, None, None, ad))
        return [".agents/hooks.json, AGENTS.md (Antigravity's hooks and rules)"]

    def refresh_workspace(self, product, ad):
        from agents import antigravity_setup
        antigravity_setup.exclude(ad, antigravity_setup.install_folder_files(product, ad, None, None, ad))

    def install_lane(self, layout, folder, lane_id, memory):
        from agents import antigravity_setup
        return antigravity_setup.install_folder_files(layout.product, layout.ad, lane_id, layout, folder.rstrip("/"))

    def install_lane_rules(self, layout, lane_dir, spec):
        pass   # install_lane writes AGENTS.md, in the lane root and every worktree

    def grant_lane_folders(self, layout):
        pass   # a lane root is the workspace agy starts in, and it reaches the repos below it

    def check_repo(self, mirror, ref):
        from agents import antigravity_setup
        return antigravity_setup.check_repo(mirror, ref)

    def check_folder(self, folder):
        from agents import antigravity_setup
        return antigravity_setup.check_folder(folder)


def _is_ours(path):
    """Repolane's AGENTS.md, or none yet (a missing one is ours to write, so not the session's to create). Not a repo's own."""
    try:
        with open(path) as fh: return fh.readline().strip() == MARKER
    except (OSError, UnicodeDecodeError):
        return True
