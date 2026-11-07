# Using Repolane with Antigravity

Repolane drives Claude Code by default. A workspace can opt in to Antigravity CLI (`agy`) as well, and the same guard
then judges every tool call `agy` makes. This has been run against `agy` 1.5.0.

```sh
lane init --agent antigravity     # a new workspace, or an existing one
lane add <git-url>
lane start ABC-123 web api
cd lanes/ABC-123 && agy
```

The choice is one line in `.repolane/config.yml`, `agent: antigravity`. It works in a workspace only. A session cannot
change it: the guard refuses writes to that file and refuses `lane init --agent`.

## What gets written

`.agents/hooks.json` and `AGENTS.md` go in the workspace root, in each lane and in every worktree, because `agy` does not
load hooks from further up. In a worktree they are kept out of git through `info/exclude`, so they never show in
`git status`. Repolane rewrites them when it is upgraded, so keep your own notes elsewhere.

Claude Code's files (`CLAUDE.md`, `.claude/`) stay too, so a `claude` started in the same workspace is guarded as well.

`lane doctor` checks those files in each folder and says what to run. A missing `hooks.json` means a session started there
runs unguarded, and `agy` gives no sign of it. After opting in an existing workspace, `lane resume <lane>` wires a lane that
was already there.

## What is shared

Lanes, worktrees, the registry, `.repolane/registry/rules.yaml`, memory and preferences, the lane commands and the board
all work the same way. In `rules.yaml`, `tool:` can be `agy`'s tool name, a neutral kind (`shell`, `read`, `write`,
`search`, `list`) or Claude Code's name. On `agy`, `Edit` means the whole write kind, so it is stricter there.

## What is different

| | With `agy` |
|---|---|
| A tool call nothing objects to | Left to `agy`'s own permission check. What Repolane pre-approves runs without it |
| A tool Repolane does not know | Judged by every path in its arguments, as if it wrote them, then left to `agy`'s check |
| Rules | Up front from `AGENTS.md`, and restated by the hook before each model call |
| The lane's goal, note and findings | Sent by the hook before each model call, and kept out of the chat. There is no automatic brief at the start of a session. At the workspace root, the board shows in the chat once, as if you had typed it |
| Past conversations | `agy` does not file them by folder, so the hook records them in `.repolane/cache/conversations.jsonl`. `lane sessions` and the board list them, and `agy --conversation <id>` resumes one |
| A `cd` | Refused the same way as in Claude Code, although in `agy` a `cd` does not last between commands |

## A repo with its own files

- **A committed `.agents/hooks.json`:** `lane start` refuses the branch. Repolane has to write that file for the guard to
  load, and does not merge someone else's hooks, whose commands would run on your machine.
- **A committed `AGENTS.md`:** kept, and still editable. A session there gets Repolane's rules from the hook before each
  step, not up front.

## What is not supported

- **`agy` in a workspace that did not opt in:** no hooks are there, so nothing guards it, and Repolane cannot detect it.
- **Status line:** `agy` only reads that setting from `~/.gemini` or per session, and Repolane does not change `~/.gemini`.
- **Memory links and `lane import`:** both depend on Claude Code keeping things in a folder per project. Memory stays in
  `.repolane/memory/` and is reached directly.
- **Moving a session into a lane by name:** start `agy` in the lane's folder.
- **Conversation clean-up:** `lane done` does not delete `agy`'s conversations.
- **Listing both agents:** an `agy` workspace lists only `agy`'s conversations, so a `claude` session there does not show on
  the board or in `lane sessions`.

## What real sessions show

Tested in interactive sessions with `agy` 1.5.0:

- **Default mode:** an ordinary shell command prompts you, with "Repolane has no objection to this call." A write Repolane
  pre-approves runs with no prompt.
- **Auto mode:** a shell command the guard refuses is refused. Edits and commands nothing objects to run with no prompt,
  and a read outside the workspace still prompts. `agy` saves this mode in its own settings, so it carries over to later
  sessions.
- **Always allow, for this conversation:** a longer command that starts the same way is still refused by the guard, and
  does not run. The option that saves to your settings was not tried.
- **`/btw` side questions:** `agy`'s changelog says these do not run hooks, but a `/btw` read of a file refused by a
  workspace rule came back as "tool call denied by pre-tool hook" with the rule's message, and no contents. Only
  `read_file` was tested.

## What is not known

- **`--dangerously-skip-permissions`:** not tested. Do not rely on your rules in that mode.
- **Compaction, and `SessionStart` on a resumed conversation:** not observed in a real run.
