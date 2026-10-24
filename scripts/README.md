# `scripts/` — the commands

Every Repolane command is a script in here. There is no framework and no build: `../lane` is a
dispatcher that maps a one-word command to one of these files and `exec`s it.

```
lane start ABC-123 web        →  scripts/lane-start ABC-123 web
```

The package installs each one under its long-form name (`lane-start`, `lane-run`, …) next to `lane`
(`[project.scripts]` in `pyproject.toml`); in a git clone, `../bin/` holds those names as symlinks. That is why the guard messages and the agent prompts
can tell you to type `lane-brief <id>` and have it work from any directory.

## What is in here

**The lane lifecycle**

| | |
|---|---|
| `lane-start` | create the branch, the worktree in each repo, and the registry file |
| `lane-resume` | recreate missing worktrees, refresh the guards, print the state |
| `lane-park` | wip-commit anything dirty, record the resume note, mark it parked |
| `lane-done` | verify every repo is clean and pushed, then remove and archive |
| `lane-with` | add a repo to a lane that already exists (`lane-start` on an existing id) |
| `lane-merge`, `lane-merge-plan` | join two lanes; the `-plan` twin can never change anything |

**Looking at things**

| | |
|---|---|
| `status-all` | repos, lanes and drift — what `lane status` runs |
| `lane-brief` | everything needed to pick one lane back up, with no model involved |
| `lane-board` | one line: hands over to `board/server.py` |
| `branch-audit` | writes `registry/branch-audit.md` — branches with no upstream or unpushed work |
| `lane-nested` | find (and with `--fix`, remove) worktrees sitting inside another worktree |
| `sessions` | past Claude conversations for a repo, newest first |
| `lane-find` | which lane touched a file, branch, commit or note — across every lane |

**Reaching into a repo without moving the session**

| | |
|---|---|
| `lane-run` | run a command in one repo of the lane |
| `lane-gh` | four lines; hands over to `lane-run … gh …` |

**Everything else**

| | |
|---|---|
| `init` | set a machine up — prerequisites, config, folders, hooks, status line |
| `lane-add` | bring a repo under management (`lane add`) |
| `copy-repo.sh` | adopt an existing checkout's `.git` instead of cloning it again |
| `lane-ref` | attach and detach outside references |
| `lane-memory` | the only way memories and preferences get written |
| `lane-import` | adopt past Claude conversations into a lane |
| `lane-workspace` | write editor workspace files for the active lanes |
| `lane-env-check` | are the mirror's env files linked into each worktree? names only |
| `lane-env-keys` | variable names in an env file, never the values |
| `leak-scan.py` | check a folder you are about to publish for anything identifying |
| `statusline.sh`, `wire-statusline.py` | the Claude Code status line |
| `session-start` | the `SessionStart` hook: what a new session is told |
| `hooks/` | the guard — see [`hooks/README.md`](hooks/README.md) |
| `board/` | the web board — see [`board/README.md`](board/README.md) |

## `lib.sh`

Everything except the standalone helpers starts with the same line:

```bash
source "$(python3 -c 'import os,sys;print(os.path.dirname(os.path.realpath(sys.argv[1])))' "$0")/lib.sh"
```

That resolves through symlinks, so a script invoked as `~/.local/bin/lane-start` still finds its
siblings. `lib.sh` then sets `set -euo pipefail` and defines the shared vocabulary:

| | |
|---|---|
| `AD` | the control plane root |
| `LANES`, `REPOS`, `LANES_DIR` | `lanes/`, `repos/`, `registry/lanes/` |
| `OWNER` | the name from `registry/config.yml`, or "the user" |
| `die` | print to stderr and exit 1 |
| `repo_default <repo>` | the integration branch: `compare_branch`, then `default_branch`, then git |
| `repo_exists <repo>` | fail with a useful message if it is not registered |
| `lane_file <id>` | path to `registry/lanes/<id>.md` |
| `lane_get <id> <key>` | one value from the frontmatter |
| `lane_repos <id>` | the `repo branch` pairs in the lane |
| `lane_set_status <id> <status>` | rewrite `status:` and `updated:` |
| `lane_anchor <id>` | give the lane folder an empty git repo of its own (see below) |
| `write_guard <dir> <id> <mem>` | write the per-session `.claude/settings.local.json` |
| `refresh_guards` | rewrite every lane's guard, so new siblings are denied everywhere |
| `link_env <repo> <worktree>` | symlink the mirror's env files into a fresh worktree |
| `write_lane_claude <id>` | the small `CLAUDE.md` at the lane root |

Two of those are worth understanding:

**`lane_anchor`** gives `lanes/<id>/` an empty git repo whose `.gitignore` is `*`. Without it, git
walks up from the lane folder, decides it belongs to the control plane's own repository, and Claude
Code refuses to sit there. Nothing is ever committed to it; the real work is in the repo worktrees
beside it, each with its own `.git`.

**`write_guard`** is the belt to the hook's braces. It writes a `.claude/settings.local.json` that
denies `repos/**` and every *other* lane by absolute path, denies every env and key pattern, allows
the read-only `lane-*` commands, points `autoMemoryDirectory` at the right folder, and wires the
hooks. `refresh_guards` re-runs it everywhere, because starting a fourth lane has to teach the
other three that it exists.

## Adding a command

1. Write `scripts/lane-<name>`, `chmod +x`, source `lib.sh`, and keep the usage in a comment block
   at the top — several commands print it with `sed` when called wrong.
2. Symlink it: `ln -s ../scripts/lane-<name> bin/lane-<name>`.
3. Add a line to the `map()` case and to `ORDER` in `../lane`, so it appears in `lane help`.
4. Add it to `scripts/menu` if a person should discover it there.
5. If it only ever reads, add it to `READONLY_LANE` in `lib.sh` so sessions may run it without a
   permission prompt.

Two conventions worth keeping. **Check everything before changing anything** — `lane-done` verifies
every repo before it removes any worktree, because the version that checked and removed in one pass
destroyed work. And **write through a temporary file rather than `sed -i`**, which needs an
argument on BSD and refuses one on GNU; `lane_set_status` shows the pattern.
