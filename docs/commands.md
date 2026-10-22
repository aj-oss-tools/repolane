# Commands

Every command is one word after `lane`. Run `lane` on its own for the board of what is going on
right now, and `lane help` for this list in your terminal.

## Setting up

| | |
|---|---|
| `lane init [<folder>] [--owner <name>] [--yes] [--git] [--claude-home <dir>]` | make the folder (default: the current one) a workspace, or check that it already is one; safe to re-run. Asks for your name, whether to add the import line to an existing `CLAUDE.md`, and whether to link Claude Code's memory under `~/.claude` into `.repolane/memory`. `--git` makes the workspace a git repo with a `.gitignore` for the machine-local parts. See [Installing Repolane](install.md#make-a-workspace) |
| `lane add <git-url\|path> [name] [--yes]` | bring a repo under management: its mirror goes to `.repolane/repos/<name>`. A local checkout with no `origin` remote is registered as local-only. Asks before linking the mirror's Claude Code memory (`--yes` accepts; with no terminal it changes nothing under `~/.claude` and prints the command) |
| `lane import` | bring past Claude conversations in — entirely optional; copies the conversation (original untouched); `--list` shows what was found and changes nothing |
| `lane migrate [<folder>] [--dry-run] [--yes] [--git] [--verbose]` / `lane migrate --undo <backup>` | turn a git-clone install into a workspace, in place, with a preview, a backup and an undo. See [Moving from a git-clone install](install.md#moving-from-a-git-clone-install) |

## Doing the work

| | |
|---|---|
| `lane start <id> <repo> [<repo>…]` | start a piece of work: a branch and a worktree in each repo |
| `lane resume <id>` | pick work back up |
| `lane park <id> "<note>"` | leave work for later, with a note to your future self |
| `lane done <id> [--delete-branches] [--delete-sessions\|--keep-sessions] [--discard-ignored] [--pushed-to <remote>]` | finish and clean up — refuses while anything is dirty or unpushed (or while a worktree holds a secret file removing it would delete, unless `--discard-ignored`); asks what to do with each repo's leftover Claude sessions unless a flag says |
| `lane with <id> <repo>` | add a repo to work already started |

A lane id may carry a branch and a base per repo: `lane start ABC-123 web:feature/login api@release-2`
checks out `feature/login` in `web` and branches `api` from `release-2`.

`lane done` asks, per repo, whether to delete that repo's Claude sessions once its worktree is
gone (`.repolane/config.yml`'s `lanes: delete_sessions_on_done:` only sets which answer it defaults
to, never skips the question); `--delete-sessions`/`--keep-sessions` answer it up front, and a
non-interactive run never deletes, only reports what it found.

## Seeing where things stand

| | |
|---|---|
| `lane status` | every repo, every lane, any drift, and the workspace's own git state |
| `lane brief <id>` | catch up on one piece of work |
| `lane board` | the same thing in a browser — see [`docs/board.md`](board.md) |
| `lane audit` | branches that look finished or stale |
| `lane sessions <repo\|id>` | past Claude conversations — for a repo, unions every live and finished lane worktree, and notes conversations still sitting at its pre-Repolane checkout, not yet `lane import`ed |
| `lane find <text>` | which lane touched this file, branch, commit or note |

## Reaching into a repo

You never `cd` into one. These work from wherever you are:

| | |
|---|---|
| `lane run <repo> <cmd…>` | run a command inside one repo of the lane |
| `lane gh <repo> <args…>` | the GitHub CLI, scoped to one repo |
| `lane ref <id> add <path>` | attach outside code or docs as a read-only reference |

`lane run` and `lane gh` are a shortcut, not a bypass: whatever they carry is judged by exactly the
same rules as a command you typed yourself.

## Memory and knowledge

| | |
|---|---|
| `lane note` | write something worth remembering — you pick the scope |

Nothing is written silently. Claude drafts the memory, then asks whether it belongs in `pref`,
`cross`, `repo` or `lane`, chosen by how long it stays true. See
[Concepts](concepts.md).

## Housekeeping

| | |
|---|---|
| `lane merge <a> <b>` | two pieces of work turned out to be one |
| `lane plan <a> <b>` | preview that merge without doing it |
| `lane doctor [--fix] [--yes] [-v]` | check the workspace is wired and the safety rules are actually working; `--fix` repairs what it safely can |
| `lane nested` | find and repair nested worktrees |
| `lane workspace` | write an editor workspace file for the active lanes |
| `lane env [id-or-repo]` | check each worktree's `.env` files are linked in — names only, never values |
| `lane keys <path>` | list the key names in an env file, never the values |
| `lane secrets <repo> scan\|add\|ignore\|list\|ignored` | `scan` candidates; `add` **denies** a path (unreadable to every future session) — beyond the built-in set; `ignore` dismisses a false positive with no deny rule; `list`/`ignored` show what's been denied/dismissed |
| `lane sync [repo]` | check a repo's real GitHub branch protection (`gh api`) and record it for the guard |
| `lane upgrade [--check] [--refresh-only] [--drop-missing] [--yes]` | upgrade the package the way it was installed, then refresh every registered workspace; `--check` only reports |
| `lane rules pull [url\|--latest]` / `lane rules status` | pull a shared, SHA-pinned rules file from a team git repo — see [`docs/extending.md`](extending.md) |

Any executable in `.repolane/scripts/local/` also becomes a `lane <name>` command of its own — see
[`docs/extending.md`](extending.md).

`lane doctor` is the one to run when something feels wrong. It starts with the workspace: `lane` on PATH the way the
hooks call it (if not, every hook fails and Claude Code runs tools unguarded), the import line in `CLAUDE.md`, the
`lane hook` commands in `.claude/settings.json` and in every lane, the rule files at the installed version, the
registration in `planes.json`, the memory links and the status line — each problem with its fix, and
`lane doctor --fix` repairs what it safely can, asking before it edits `CLAUDE.md` or anything under `~/.claude`
(`--yes` answers). Then it compiles the guard, fires its named probes at it and prints each verdict — ten that must be
refused and one ordinary command that must not, because a guard that refuses everything is broken too — and checks
that every lane and worktree is still wired to it.

It also lists, advisory-only: any lane nobody has touched in `stale_days` (`.repolane/config.yml`, 21 by default),
with its size on disk and the one command that clears it (`lane done <id>` when the work is merged and pushed,
`lane done <id> --delete-branches` when nothing was ever done on it, `lane park <id> "<note>"` when there is work still
in there); any managed GitHub repo whose branch protection hasn't been checked with `lane sync` in
`protection: sync_days` (7 by default); whether `gh` is installed and authenticated; per active lane, whether what its
file says it contains still matches what is checked out under `lanes/<id>/`; any repo with a candidate
secret/credential filename nobody has reviewed with `lane secrets`; any `.repolane/scripts/local/<name>` shadowed by a
built-in of the same name; and — printed first, more prominently than the rest — whether a configured
`lane rules pull` source has moved since it was last pinned. It only ever tells you; clearing a lane or syncing a repo
is always a command you type. `lane doctor -v` adds every wiring location and runs the full guard suite against a
throwaway one it builds and deletes. A broken workspace or guard exits non-zero; the advisories do not.

`lane upgrade` upgrades the package (`pipx upgrade repolane`, `uv tool upgrade repolane`, or for a pip install the
`pip` command to run), then refreshes every workspace registered in `~/.local/share/lane/planes.json`: the rule files
and data migrations, Repolane's hooks in `.claude/settings.json` (your own keys and hooks kept), and every lane's
settings and `CLAUDE.md`. Nothing you wrote is changed. `lane upgrade --check` shows the installed version against the
newest on PyPI and which workspaces are behind, and changes nothing. See
[Installing Repolane](install.md#upgrade-lane-upgrade).

## Long-form names

Every command also exists as its own executable — `lane-start`, `lane-run`, `lane-memory` and so on — installed next to
`lane` by the package. They are what the guard messages and the agent prompts tell a session to type, and they run
from any directory without a `cd`. Each one is exactly `lane <command>`: `lane-brief` is `lane brief`,
`lane-env-check` is `lane env`. Two names don't follow the mechanical `lane-<word>` → `<word>` mapping: `lane-memory`
runs `lane note` (and has the `goal` and `draft` subcommands a lane session uses, see
[Installing Repolane](install.md#how-a-lane-session-saves-its-goal-and-its-notes)), and `guard-check` (no `lane-`
prefix) runs `lane doctor`.
