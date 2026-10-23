# `.claude/` — the Claude Code wiring

This is what turns a folder of scripts into something Claude Code behaves differently inside. It is
the control plane's *own* configuration; every lane and worktree gets a generated
`.claude/settings.local.json` of its own, written by `write_guard` in `../scripts/lib.sh`.

| | |
|---|---|
| `settings.json` | hook wiring and the always-allowed read-only commands |
| `agents/` | subagents for jobs that deserve their own context |
| `commands/` | slash commands — mostly thin wrappers over a script |

## `settings.json`

Seven hook events, all pointed at the same dispatcher:

```json
"PreToolUse":       "$CLAUDE_PROJECT_DIR/scripts/hooks/guard.py"   // Bash|Edit|Write|MultiEdit|NotebookEdit|Read|EnterWorktree|Glob|Grep
"PostToolUse":      "…/guard.py"                                   // Edit|Write|MultiEdit|NotebookEdit
"UserPromptSubmit": "…/guard.py"
"PreCompact":       "…/guard.py"
"SessionEnd":       "…/guard.py"
"WorktreeCreate":   "…/guard.py"                                   // 120s: it may run lane-resume
"WorktreeRemove":   "…/guard.py"
"SessionStart":     "$CLAUDE_PROJECT_DIR/scripts/session-start"     // startup|resume|clear|compact|fork
```

`permissions.allow` lists the read-only `lane-*` commands, so a session can run `lane-status` or
`lane-brief` without a prompt. Everything that changes something is deliberately absent.

`lane init` also adds a `statusLine` entry pointing at `../scripts/statusline.sh`, which shows where
you are, how many lanes are active, and which repos need attention. It is added only if you have no
status line already — `wire-statusline.py` refuses to disturb an existing one, and bails out rather
than rewriting a `settings.json` it cannot parse.

## `session-start`

Not a hook rule but the first thing a session reads. It prints two things: `additionalContext` for
Claude, and a `systemMessage` shown to you on the startup screen.

- **At the control plane root** it prints the dispatcher board — every lane with its status, per-repo
  dirty and unpushed counts, and the first line of its resume note — plus the dispatcher
  instructions and the full command menu.
- **Inside a lane** it prints that lane's file in full and tells the session its scope is
  `lanes/<id>/` and nothing else.
- **On a resumed conversation** it works out which repo the transcript belongs to by finding which
  project folder holds `<session_id>.jsonl`, rather than trusting the hook's `transcript_path`,
  which is derived from the working directory and is wrong exactly when it matters.

## `agents/`

| | |
|---|---|
| `lane-manager` | starts, resumes, parks and finishes lanes |
| `context-loader` | assembles the brief for a lane — lane file, preferences, per-repo memory, the repo's own `CLAUDE.md`, domain notes — and returns it compactly |
| `branch-gardener` | triages local branches and stashes in a mirror using read-only git, and proposes deletions; never deletes without an approved list |

`context-loader` exists for a specific reason: assembling context is a lot of reading, and doing it
in the main session spends the window you wanted the context *for*. A subagent reads widely and
returns a page.

In a workspace (the installed package) these folders are not used: `lane init` copies the workspace's versions,
`../templates/claude/agents/` and `../templates/claude/commands/`, into the workspace's own `.claude/`, which call the
`lane-*` commands on PATH and name the `.repolane/` paths. Change both when you change one.

## `commands/`

Most are three lines — a description, an `allowed-tools` entry naming exactly one script, and the
invocation — so that `/lane-brief` costs no model reasoning at all. `lane-start` is the exception:
it is a real procedure, because naming a piece of work and deciding which repos it touches is a
judgement, so it proposes in one line, waits, and only then runs anything.

## `CLAUDE.md`

Not in this folder — it is generated at the control plane root from `../CLAUDE.md.template`, with
the owner's name substituted, when you run `lane init`. It is not tracked by git until you commit
it; it is yours, and so is everything else `lane init` writes. Edit the template to change what
every session is told, and re-run `lane init` (it is safe to re-run, and never overwrites something
you already have).
