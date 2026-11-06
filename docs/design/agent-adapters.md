# Agent adapters: supporting more than Claude Code

**Status: steps 2 to 4 built (`scripts/agents/`, the board, `docs/antigravity.md`).** Trial run on 2026-11-04 with Antigravity CLI (`agy`) 1.5.0.

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

## What building it found (agy 1.5.0, step 3)

Six real runs in throwaway folders, plus the hook documentation inside the binary.

| Question | Result |
|---|---|
| Exit 0 with **empty** output on `PreToolUse` | **The tool runs**, if agy's own check allows it. So a tool call always gets a decision |
| `{}` on `PreToolUse` | Blocked, with an empty reason |
| An unknown decision (`banana`) | Blocked |
| `allow` | Does not skip agy's own check. In `-p`, a tool that needs a prompt is auto-denied and the run ends |
| `ask` | Goes by agy's own check: ran with an allow rule, and on a read in the workspace. An interactive prompt was not tried |
| `auto_approve` | Runs with no allow rule. Not in agy's docs, but it works |
| `ephemeralMessage` from `PreInvocation` | Reaches the model, once. `PreInvocation` fires before every model call, so nine times in one turn of the test |
| `userMessage` from `PreInvocation` | Reaches the model and stays, so it piles up. Used only once, from `SessionStart` |
| `ephemeralMessage` from `SessionStart` | Did not reach the model |
| `lastUserInput` | On the first step it holds what `SessionStart` injected. The `SessionStart` body itself still has the real prompt |
| `cd sub`, then `pwd` | Back at the start: a `cd` does not last between commands, unlike Claude Code |
| Hook body | No event name, so the hook command names it. `conversationId`, `workspacePaths`, `transcriptPath` under `~/.gemini` |

The tools the model listed in 1.5.0: `run_command` (`CommandLine`, `IsDaemon`, `WaitMsBeforeAsync`, `toolSummary`), `read_file` (`Path`…),
`write_file` (`Path`, `Content`…), `edit_file` (`Path`, `Target`, `Replacement`…), `manage_task`, `search_web`, `ask_question`,
`invoke_subagent` (`Workspace`…), `define_subagent`, `send_message`, `manage_subagents`, `schedule`, `list_resources`, `read_resource`,
`call_mcp_tool`. There is no search or list tool: those go through the shell. The older names in the binary (`view_file`, `grep_search`,
`find`, `list_directory`, `replace_file_content`…) are mapped too, from the step types; those were not seen in a real run.

Status line: `statusLine` and `/statusline` exist, but only in `~/.gemini` (or `--settings` for one session). No per-workspace file, so
`STATUS_LINE` is off.

### What was chosen

- **Selecting:** `agent: antigravity` in `.repolane/config.yml`, written by `lane init --agent antigravity`, workspaces only. Claude Code's
  files stay, so a `claude` started there is guarded too; agy's files are added. The line decides what is installed and said to a person. A
  hook names its own agent in its command, so a session's answers never depend on that line. No session can change it: the guard refuses
  writes to it from anywhere, and `lane init --agent`.
- **A tool call with no objection** is `ask`, what the owner pre-approves is `auto_approve`, and a refusal is `deny`. An unmapped tool is judged by
  every path in its arguments as if it wrote them, then `ask`.
- **A repo's own `.agents/hooks.json`** refuses `lane start`. **A repo's own `AGENTS.md`** is kept and stays editable; a session in that worktree gets
  Repolane's rules from the hook, each step, and not up front. An untracked `hooks.json` that is not ours is not overwritten either.
- **`registry/rules.yaml`:** `tool:` may be agy's name, a neutral kind (`shell`, `read`, `write`, `search`, `list`), or Claude Code's name. On agy, `Edit`
  means the whole write kind, so it is stricter there.
- **`Stop`** is not a session end: it fires each turn. When `fullyIdle` it writes the lane's state line, and nothing else.
- **`.gemini`** is added to the credential folders in an agy session. `~/.gemini` is already refused as outside the workspace.

### Still not known

1. **`--dangerously-skip-permissions`:** never run. Whether hooks fire in that mode is still open, and until then the rules are not known to hold there.
2. **`/btw`:** agy's changelog says side questions do not run hooks, and that they can call read tools. If so, `/btw` can read a secret with no guard. Not tried.
3. **Interactive `ask`:** only `-p` was run. How often a person is prompted is not known.
4. **Artifacts:** agy can write plans into its `brain` folder under `~/.gemini`. The guard refuses that as outside the workspace; the model then has to write elsewhere.
5. **`manage_task` with `Input`** can type into a running background command. It is judged by the paths it names, not read as shell.
6. **`SessionStart` on `--conversation`** and real compaction were not observed.
7. **`cd` is still refused the way it is for Claude Code,** though on agy it does not last. Stricter than it has to be, kept so both run the same rules.

## Order of work

Rough estimates, 4 to 6 weeks in total.

1. Answer open items 1 to 4 (a few days).
2. Move Claude behind the adapter with no behaviour change and the existing tests green (1.5 to 2 weeks). This is the
   riskiest step, since the guard enforces the rules, so it ships by itself.
3. Add `AntigravityAdapter`: hooks, rules, sessions and the shared guard suite (1.5 to 2 weeks).
4. Board and docs (about a week).
