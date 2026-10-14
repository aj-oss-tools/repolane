# `scripts/hooks/` — the guard

This is the part of Repolane that makes the rules real. Everything else is convenience; this is the
thing that refuses.

| | |
|---|---|
| `guard.py` | the whole dispatcher — one file, no dependencies |
| `guard-check` | is it healthy? compiles it, fires nine named probes, checks every lane is wired, and lists lanes nobody has touched in `stale_days` with the command that clears each (`lane doctor`; `-v` also runs the suite) |
| `test-guard.sh` | 184 cases covering every rule, against a throwaway control plane it builds itself |

## How it is wired

`.claude/settings.json` at the control plane root points seven hook events at `guard.py`, and
`write_guard` in `../lib.sh` writes the same wiring into every lane and worktree. The script reads
the hook JSON on stdin, branches on `hook_event_name`, prints a JSON decision on stdout, and exits.

```
PreToolUse        allow / deny / add context, before the tool runs
PostToolUse       records every file edited, into lanes/<id>/.touched
UserPromptSubmit  injects the lane's state, and the memory index on first use
PreCompact        re-states the rules and the lane spec, so compaction cannot drop them
SessionEnd        appends a state line to the lane file; tidies transcripts
SessionStart      on `compact`, clears the per-session cache so briefs re-inject
WorktreeCreate    interprets EnterWorktree name="<id>" as "resume this lane"
WorktreeRemove    always refuses — worktrees are removed by lane-done
```

`AD` is derived from the script's own real path, so the guard always knows which control plane it
belongs to regardless of where the session was launched.

## What it actually checks

The important idea: **the guard reads the tool call, not the intention.** For Bash it splits the
command on `;`, `&&`, `||` and newlines and judges each segment separately, so a refused command
cannot be smuggled in as the second half of a chain.

- **Paths are judged as written, not as resolved.** `outside_ad()` works on the literal argument,
  so a symlink pointing out of the control plane is refused. Separately, `..` paths are collected
  and resolved, because for a while `../OTHER/file` slipped through while its absolute twin was
  refused.
- **Write targets are distinguished from reads.** `rm`, `touch`, `tee`, `sed -i` and friends treat
  every path as a target; `cp`, `mv`, `ln` treat only their *last* argument as one; `git -C <dir>`
  with a writing subcommand targets that directory; `>` and `>>` targets are collected too. This is
  why reading a mirror is fine and writing to one is not.
- **Secrets are denied by default.** `SECRET_SAFE_CMD` is a short allow-list of commands that only
  touch metadata (`ls`, `stat`, `wc`, `find`, `lane-env-keys`…). Anything else naming a secret path
  is refused. An earlier version listed the *readers* instead, and `dd`, `gpg -d` and
  `git show HEAD:.env` walked straight through.
- **`cd` is a door.** In Claude Code a `cd` moves the session, so `cd_targets()` extracts every
  directory a command would enter and applies the same rules as `EnterWorktree`.
- **Our own commands are exempt — narrowly.** A command made only of `lane-*` scripts is trusted,
  because they validate their own arguments. `lane-run` and `lane-gh` are explicitly *not* exempt:
  they carry someone else's command, and it is judged as if typed directly. Only a bare name or a
  path inside this folder counts, so `/tmp/lane-evil` is just another command.

It also adds context rather than only subtracting it: the first time a session touches a repo,
`rules_brief()` injects that repo's own `CLAUDE.md` and the list of its `.claude/rules/*`; the
first prompt in a lane carries `memory_brief()`. A small per-session cache under `.cache/sessions/`
stops it repeating itself.

## Failing open

`guard.py` exits 0 on malformed input, non-dict `tool_input`, or anything it does not recognise.
That is deliberate: a guard that crashes blocks every tool call, which is a worse failure than
letting an unusual call through. The cost is that a syntax error silently disables every rule —
which is exactly what `guard-check` exists to catch, and why `status-all` runs it before printing
anything and warns you not to trust the state below if it fails.

## Changing a rule

Run the suite:

```sh
bash scripts/hooks/test-guard.sh
```

It builds its own throwaway control plane under a temp directory — a lane with repos, a mirror,
an attached reference, a second lane to test reach-in against, an existing memory file — copies
`guard.py` into it (a copy, not a symlink: the guard finds the control plane from its own real
path) and runs every case there. So it asserts the same 184 cases on a fresh clone as on a machine
full of work, and it never reads or writes your real lanes, mirrors or memory. If the fixture
cannot be built the run fails; it never skips. The case count is itself an assertion, so adding
or losing a case fails until `EXPECTED_CASES` is changed deliberately.

A case is one line:

```bash
bash_case deny "rm $AD/lanes/$OTHER/app.ts"
file_case allow Read "$AD/lanes/docs/refs/client-docs/README.md"
expect deny "EnterWorktree with a path" "{...raw hook json...}"
```

`pass` means the guard returned no decision and normal permissions apply — which is different from
`allow`, which short-circuits them.

Add a case for whatever you change, in both directions: the thing that should now be refused, and
the near-miss that should still be allowed. Most of the regressions this file has caught were rules
that became *too* broad and started refusing ordinary work.
