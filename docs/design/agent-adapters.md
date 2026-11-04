# Agent adapters: supporting more than Claude Code

**Status: proposed. Nothing here is built.** Trial run on 2026-11-04 with Antigravity CLI (`agy`) 1.5.0.

## Goal

Repolane works with Claude Code only. Add Antigravity CLI so that the next agent costs one new adapter, not another
round of changes across the product. A new agent counts as supported only when it passes the shared guard suite.

## Design

One small base class, one subclass per agent, no deeper inheritance.

```
 Claude Code ──> ClaudeAdapter ───────┐
                                      ├──> neutral event ──> guard and lane logic (no agent knowledge)
 Antigravity ──> AntigravityAdapter ──┘                       │
                                      <── neutral decision ───┘
```

```python
class AgentAdapter(ABC):
    name: str
    capabilities: set[Capability]        # PRE_COMPACT, ENTER_LANE, STATUS_LINE...

    def parse_event(self, raw) -> Event: ...             # stdin -> neutral event
    def format_decision(self, d: Decision) -> dict: ...  # allow/deny/ask -> the agent's format
    def install(self, workspace, lane=None): ...         # hooks, settings, rules file
    def sessions(self, lane) -> list[Session]: ...       # list and read past conversations
```

- The guard sees `ToolCall(kind=SHELL|READ|WRITE|SEARCH, command, paths)`, never `Bash` or `run_command`.
- Shared code asks about capabilities, never the agent's name.
- The bash scripts reach the adapter through a small `lane agent <action>` command.
- No plugin system or outside adapters until a third agent needs them.
- The base class is settled only after two real adapters exist.

## Trial results

Everything ran in a throwaway workspace with a probe hook.

| Question | Result |
|---|---|
| Hooks fire in print mode? | Yes: `SessionStart`, `PreInvocation`, `PreToolUse`, `PostToolUse`, `PostInvocation`, `Stop` |
| A `deny` stops shell and file reads? | Yes, the action did not happen, and the reason reaches the model |
| Hook exits non-zero, prints bad JSON or times out? | The tool call is blocked every time (fails closed) |
| Subagents? | Covered: both `invoke_subagent` and the subagent's own `run_command` reach the hook |
| Session at a lane root, `cd app && ...`? | Hook sees the whole command line; the guard's shell reader is what makes this safe |
| Editing `app/...` from the lane root? | Works; the hook sees the absolute path |
| Add context to a turn? | `userMessage` and `ephemeralMessage` reach the model. **`systemMessage` did not, in two tests** |
| `allow` from a hook skips agy's own prompt? | No. `auto_approve` does |
| Rules file | Root `AGENTS.md` is read from a subfolder of the same git repo, not across a worktree boundary |

**Hooks can silently not load. This is the main finding.**

| Session started in | Hooks in `.agents/hooks.json` at | Hooks fire? |
|---|---|---|
| workspace root | workspace root | yes |
| `lanes/t1`, workspace is a git repo | workspace root | yes (found by walking up) |
| `lanes/t1`, workspace is not a git repo | workspace root | **no** |
| `lanes/t1/app`, a git worktree | workspace root | **no, and the command ran unguarded** |
| `lanes/t1/app`, a git worktree | the worktree itself | yes |

So `install()` must write `.agents/hooks.json` and `AGENTS.md` into the lane root and every worktree, kept out of git with
`info/exclude`, and `lane doctor` must check they are there.

Other differences:
- The hook's working directory is the `.agents` folder that holds it, not the session's folder. Use `workspacePaths`.
- Tool names seen: `run_command` (`CommandLine`), `read_file` (`Path`), `write_file` (`Path`, `Content`),
  `invoke_subagent`, `send_message`. The docs name others, so the full list must be taken from a real run.
- Transcripts are JSONL at the hook's `transcriptPath`, with their own schema (`step_index`, `type`, `content`).
- agy's changelog mentions custom status line scripts that receive a JSON payload. Not tried.

## Still open

1. **`--dangerously-skip-permissions`:** do hooks still fire? Not run, because the trial's safety check refused the flag.
   If hooks do not fire, Repolane's rules do not hold in that mode, and the docs must say so.
2. **Compaction:** `/compact` did nothing in print mode, so a real compaction was not observed. There is no `PreCompact`
   event, but `PreInvocation` fires on every turn, so restating the rules each turn should hold regardless.
3. **Global hooks** (`~/.gemini/config/hooks.json`): a possible backstop for a session started anywhere. Not tried, because
   it means changing real global config. It would also run for every project on the machine.
4. **A repo with its own committed `.agents/hooks.json`:** it collides with the file Repolane writes into the worktree, and
   its commands run on the machine. Merging, and whether agy asks before trusting such a file, need a decision.
5. **Enter a lane by name:** no `WorktreeCreate` or `EnterWorktree`. A session starts inside the lane instead, so
   `ENTER_LANE` is a capability Antigravity lacks.
6. **Desktop app and IDE:** they share the hooks, but lanes were not tried there.

## Order of work

Rough estimates, 4 to 6 weeks in total.

1. Answer open items 1 to 4 (a few days).
2. Move Claude behind the adapter with no behaviour change and the existing tests green (1.5 to 2 weeks). This is the
   riskiest step, since the guard enforces the rules, so it ships by itself.
3. Add `AntigravityAdapter`: hooks, rules, sessions and the shared guard suite (1.5 to 2 weeks).
4. Board and docs (about a week).
