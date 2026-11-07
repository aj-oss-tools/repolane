#!/usr/bin/env python3
"""translate.py <guard.py> : a hook call written for Claude Code on stdin, put to the guard as Antigravity would send it, and the
answer written back in Claude Code's words. One set of guard cases and probes (scripts/hooks/test-guard.sh, `lane doctor`) then
judges both adapters, and a new agent inherits them with a translator of its own.

Events Antigravity does not have (PreCompact, SessionEnd, WorktreeCreate, WorktreeRemove) go to the guard as they came, under
Claude Code's adapter: there is nothing of agy's to compare.
"""
import json
import re
import subprocess
import sys

TOOLS = {"Bash": "run_command", "Read": "read_file", "Edit": "edit_file", "Write": "write_file", "MultiEdit": "edit_file",
         "NotebookEdit": "edit_file", "Grep": "grep_search", "Glob": "find"}
ARGS = {"Bash": {"command": "CommandLine"}, "Read": {"file_path": "Path", "notebook_path": "Path", "path": "Path"},
        "Edit": {"file_path": "Path", "notebook_path": "Path", "path": "Path"}, "Write": {"file_path": "Path", "notebook_path": "Path", "path": "Path"},
        "MultiEdit": {"file_path": "Path", "notebook_path": "Path", "path": "Path"}, "NotebookEdit": {"file_path": "Path", "notebook_path": "Path", "path": "Path"},
        "Grep": {"path": "SearchPath", "pattern": "Query", "glob": "Includes", "type": "type"}, "Glob": {"path": "SearchDirectory", "pattern": "Pattern"}}
EVENTS = {"PreToolUse": "pre-tool-use", "PostToolUse": "post-tool-use", "UserPromptSubmit": "user-prompt-submit"}


def body(d):
    out = {"conversationId": d.get("session_id"), "workspacePaths": [d["cwd"]] if "cwd" in d and d["cwd"] is not None else []}
    if d.get("hook_event_name") == "UserPromptSubmit": out["invocationNum"] = 0
    name, ti = d.get("tool_name"), d.get("tool_input")
    if "tool_name" in d or "tool_input" in d:
        args = ti
        if isinstance(ti, dict) and isinstance(name, str) and name in ARGS:
            args = {}
            for k, v in ti.items():
                args.setdefault(ARGS[name].get(k, k), v) if v is not None else None
        out["toolCall"] = {"name": TOOLS.get(name, name) if isinstance(name, str) else name, "args": args}
    return out


def back(event, stdout):
    if not stdout.strip(): return stdout
    try: a = json.loads(stdout)
    except ValueError: return stdout
    name = {v: k for k, v in EVENTS.items()}[event]
    d = a.get("decision") if isinstance(a, dict) else None
    if event == "pre-tool-use":
        if d == "deny": return json.dumps({"hookSpecificOutput": {"hookEventName": name, "permissionDecision": "deny", "permissionDecisionReason": a.get("reason", "")}}) + "\n"
        if d == "auto_approve" and a.get("reason") != "pre-approved": return json.dumps({"hookSpecificOutput": {"hookEventName": name, "permissionDecision": "allow"}}) + "\n"
        if d in ("ask", "auto_approve"): return ""   # no objection, which Claude Code says with no decision at all
        return "BAD ANSWER FROM THE ADAPTER: " + stdout
    steps = a.get("injectSteps") if isinstance(a, dict) else None
    if steps: return json.dumps({"hookSpecificOutput": {"hookEventName": name, "additionalContext": steps[0].get("ephemeralMessage", "")}}) + "\n"
    return ""


def main():
    guard = sys.argv[1]
    raw = sys.stdin.buffer.read()
    text = raw.decode("utf-8", "replace")
    try: d = json.loads(text)
    except Exception: d = None
    event = EVENTS.get(d.get("hook_event_name")) if isinstance(d, dict) and isinstance(d.get("hook_event_name"), str) else None
    if d is None and re.search(r'"hook_event_name"\s*:\s*"PreToolUse"', text): event = "pre-tool-use"
    py = [sys.executable, "-B", guard]
    if event is None:
        r = subprocess.run(py + sys.argv[2:], input=raw, capture_output=True)
        sys.stdout.buffer.write(r.stdout); sys.stderr.buffer.write(r.stderr); return r.returncode
    send = json.dumps(body(d)).encode() if d is not None else raw
    r = subprocess.run(py + ["--agent", "antigravity", "--event", event] + sys.argv[2:], input=send, capture_output=True)
    sys.stderr.buffer.write(r.stderr)
    sys.stdout.write(back(event, r.stdout.decode()))
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
