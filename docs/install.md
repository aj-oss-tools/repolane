# Installing Repolane, and your workspace

Repolane is a Python package. It puts `lane` on your PATH; your repos, lanes, memory and notes live in a
**workspace**, a folder of your own that the package never ships and never overwrites.

## Install

```sh
pipx install repolane          # or: uv tool install repolane
```

You need **git**, **python3** (3.9 or later, standard library only) and **bash**. `gh` is optional (pull request
status, `lane gh`, `lane sync`); so is Claude Code (the commands work on their own, the hooks matter when Claude is
driving). Tested on macOS and Linux; on Windows use WSL. Nothing phones home.

The package also installs the long command names next to `lane` (`lane-memory`, `lane-brief`, `lane-run`,
`lane-with`, …). They are what the rules tell a Claude session to run, and each is the same as `lane <command>`.

## Make a workspace

```sh
mkdir ~/work && cd ~/work
lane init                       # or: lane init ~/work
lane add <git-url>              # or: lane add ~/path/to/a/checkout/you/already/have
lane start ABC-123 web api
cd lanes/ABC-123 && claude
```

Any folder where `lane init` ran is a workspace. `lane` finds it by looking up from the current folder, the way git
finds a repo, so every command works from anywhere inside it. `LANE_WORKSPACE=<folder>` names one directly.

### What `lane init` asks

| | |
|---|---|
| your name | used when the hooks address you ("ask Sam first"); the default is git's `user.name`. `--owner <name>` answers it. Once `.repolane/config.yml` names you, `lane init` keeps that name |
| the import line | only when the folder already has a `CLAUDE.md`. It shows the line `@.repolane/REPOLANE.md` and asks "Add it? [Y/n]". A folder without a `CLAUDE.md` gets a short one with the line in it. Your `CLAUDE.md` is never edited without a yes |
| the memory links | Claude Code keeps a project's memory in `~/.claude/projects/<folder>/memory`. Repolane links that folder to `.repolane/memory`, so memory is kept in the workspace. `lane init` shows each link and asks "Make these links under ~/.claude? [Y/n]". Notes already in Claude Code's folder are copied in first. Nothing under `~/.claude` changes without a yes |

The status line is not a question: when `.claude/settings.json` has no status line, `lane init` sets it to
`lane statusline`. A status line of your own is never replaced.

Flags:

| | |
|---|---|
| `--owner <name>` | your name, without asking |
| `--yes` | ask nothing: take the defaults, add the import line, make the memory links |
| `--git` | make the workspace a git repo, with a `.gitignore` for what is machine-local (see below) |
| `--claude-home <dir>` | Claude Code's folder, if it is not `~/.claude` (or set `CLAUDE_HOME`) |

With no terminal to ask and no `--yes`, `lane init` changes neither your `CLAUDE.md` nor anything under `~/.claude`,
and prints what to run instead. A link you said no to is recorded in `.repolane/declined.json` and not offered again
by `lane init` or `lane add`; `lane doctor` shows it as a note with the command to make it later, and
`lane doctor --fix` offers it once more.

`lane init` is safe to run again. Over a workspace in use it changes nothing and says so. It adds Repolane's hooks to
an existing `.claude/settings.json` without touching your own keys or hooks, and records the workspace in
`~/.local/share/lane/planes.json`, which is how `lane upgrade` finds every workspace on the machine. A workspace
cannot sit inside another one.

## What is in a workspace

Three things at the top are yours and Claude Code's; everything Repolane keeps is under `.repolane/`.

```
~/work/
  CLAUDE.md                  yours. It imports Repolane's rules with the line  @.repolane/REPOLANE.md
  .claude/settings.json      Claude Code's settings: Repolane's `lane hook …` commands, `lane statusline`,
                             and anything of your own
  lanes/<id>/<repo>/         the worktrees: one folder per piece of work
  .repolane/
    REPOLANE.md              the rules every session here gets (through the import line in CLAUDE.md)
    LANE.md                  the rules a session inside a lane gets, handed to it as it enters
    version                  which Repolane version wrote REPOLANE.md and LANE.md
    config.yml               your name, the ticket tracker URL, stale-lane and sync reminders
    env.sh                   shared build caches and environment settings, sourced before a repo's build
    registry/repos.yaml      the repos, where they came from, default branch, stack
    registry/lanes/<id>.md   one file per lane: goal, resume note, findings, log, the repos in scope
    registry/rules.yaml      rules of your own (optional; see rules.md)
    memory/                  cross-repo memory; memory/<repo>/ per repo (Claude Code's memory links point here)
    knowledge/               preferences.md and your notes; knowledge/shared/ is what `lane rules pull` brings
    repos/<repo>/            the mirrors: one clone of each repo, always on its default branch, never edited
    cache/                   machine-local caches
    scripts/local/           your own `lane <name>` commands (optional; see extending.md)
    declined.json            the memory links you said no to (only when there are some)
```

`REPOLANE.md`, `LANE.md` and `version` are Repolane's: they are written again on the first `lane` command or hook after
the installed version changes, so do not edit them. Nothing else in the workspace is ever overwritten. Neither rule
file carries your name; the hooks name you when a session starts.

The hooks in `.claude/settings.json` and in every lane's settings are commands (`lane hook pre-tool-use`,
`lane hook session-start`, …), not paths into the installed package. That is why `lane` has to be on PATH for the
hooks to work (see [Troubleshooting](troubleshooting.md#the-hooks-fail-because-lane-is-not-on-path)).

## Keep your workspace in your own git repo

The workspace is where your registry, memory and notes live, so it is worth versioning and backing up. Repolane
never pushes it anywhere; the repo and its remote are yours.

```sh
lane init --git                 # git init, plus a .gitignore for the machine-local parts
git add -A && git commit -m "my workspace"
git remote add origin <your-private-repo> && git push -u origin main
```

`lane init --git` ignores what is rebuilt on each machine: `/lanes/`, `/.repolane/repos/`, `/.repolane/cache/`,
`/.claude/settings.local.json` and the editor workspace file `/lane.code-workspace`. If you use `lane rules pull`, add
`/.repolane/registry/.shared-cache/` too.

| commit these: they are yours | Repolane refreshes these: commit them, never edit them |
|---|---|
| `CLAUDE.md` | `.repolane/REPOLANE.md` |
| `.claude/settings.json` | `.repolane/LANE.md` |
| `.repolane/config.yml`, `.repolane/env.sh` | `.repolane/version` |
| `.repolane/knowledge/`, `.repolane/memory/` | |
| `.repolane/registry/repos.yaml` and `registry/lanes/` | |

### On another machine

Clone your workspace repo, install Repolane, and run `lane init` in it:

```sh
pipx install repolane
git clone <your-private-repo> ~/work && cd ~/work
lane init                       # makes lanes/, the mirrors folder and the cache, links memory, registers it
lane add <git-url>              # once per repo in .repolane/registry/repos.yaml: clones its mirror again
lane resume <id>                # recreates a lane's worktrees on their recorded branches
```

`lane add` keeps the entry `repos.yaml` already has for the repo. A branch that only ever existed on the other machine
is not on the remote, so push lane branches you want to continue elsewhere.

## Check it: `lane doctor`

`lane doctor` checks that the workspace is wired the way the hooks expect:

- `lane` is on PATH the way the hooks call it. If it is not, every hook fails and Claude Code runs tools **unguarded**;
  the doctor says so loudly and prints the `PATH` line to add.
- `CLAUDE.md` imports `.repolane/REPOLANE.md`. Without it Repolane's rules do not load in sessions here.
- `.claude/settings.json` runs the expected `lane hook` commands, and every lane's settings run the current ones.
- `REPOLANE.md` and `LANE.md` are the installed version's, and the workspace is registered in `planes.json`.
- Claude Code's memory links for the root and every mirror point into `.repolane/memory` (one you declined is a note,
  not a failure).
- The status line: `lane statusline`, your own, or none (a note).

Then it compiles the guard, fires its named probes at it, and checks every lane is wired to it. Each problem comes
with its fix. `lane doctor --fix` repairs what it safely can, asking before it edits `CLAUDE.md` or anything under
`~/.claude` (`--yes` answers yes). It exits non-zero while anything is wrong, so it is safe to put in a script. It
reports an outdated workspace; refreshing it is `lane upgrade`'s job.

## Upgrade: `lane upgrade`

```sh
lane upgrade --check            # installed version, newest on PyPI, which workspaces are behind; changes nothing
lane upgrade                    # upgrade the package, then refresh every registered workspace
```

`lane upgrade` upgrades the package the way it was installed (`pipx upgrade repolane`, or `uv tool upgrade repolane`;
for a pip install it prints the `pip` command to run), then refreshes every workspace in `planes.json` with the new
version: the rule files and data migrations, Repolane's hooks in `.claude/settings.json` (your own keys and hooks
kept), and every lane's `settings.local.json` and `CLAUDE.md`. Nothing you wrote is changed. It reports each
workspace and exits non-zero if one could not be refreshed.

A registered folder that is gone is skipped and reported, and you are asked whether to drop it from the registry
(`--drop-missing` or `--yes` drops it). Run inside a workspace that is not registered, it registers it.
`--refresh-only` skips the package step. A workspace you did not upgrade this way refreshes itself on its first `lane`
command or hook after the installed version changes.

## Moving from a git-clone install

A git-clone install is a clone of the Repolane repo that is also your control plane, with `registry/`, `memory/`,
`knowledge/` and `repos/` at its top. `lane migrate` turns such a clone into a workspace, in place, keeping every
lane, branch, memory and note.

1. In the clone, take the last clone update: `lane upgrade`. Its `lane doctor` then spells out the next two steps.
2. Install the package: `pipx install repolane` (or `uv tool install repolane`).
3. Run the installed `lane`: `lane migrate ~/path/to/the/clone` (or `lane migrate` from inside it).

`lane migrate` shows everything it would do first and changes nothing until you confirm ("Migrate now? [y/N]", or
`--yes`). `--dry-run`, or no terminal and no `--yes`, only shows the plan (`--verbose` lists every file). It refuses
while Claude Code is running inside the folder: end those sessions first. Before the first change it writes a backup
of everything it changes or removes to `~/.local/share/lane/backups/<folder>-<time>.tar.gz`, and
`lane migrate --undo <backup>` puts the clone install back (what was written in the workspace since is kept aside).

What it does:

- Your data moves under `.repolane/`: `registry/`, `memory/`, `knowledge/`, `repos/`, `.cache/` (as `cache/`),
  `registry/config.yml` (as `config.yml`), `scripts/env.sh` (as `env.sh`) and `scripts/local/`. The worktrees stay in
  `lanes/` and are repaired with `git worktree repair`, and their `.env` links follow the mirrors.
- Repolane's own files are removed: only paths a release shipped, never anything else in the folder. The clone's
  `.git` is Repolane's repo, so it goes too (it is in the backup); `--git` starts a fresh, empty one for your
  workspace.
- The generated `CLAUDE.md` becomes a short one that imports `.repolane/REPOLANE.md`, keeping every line you added.
  If you edited lines of Repolane's own text, the old file is also kept as `CLAUDE.md.pre-0.10`.
- `.claude/settings.json` runs `lane hook …` commands and `lane statusline`, keeping your own keys and hooks; every
  lane's settings are written again.
- Outside the folder, each asked first: the memory links under `~/.claude/projects` point into `.repolane/memory`, and
  the router `lane install` wrote to `~/.local/bin/lane` is removed when no other clone install uses it.

A migration that stops half way continues when you run it again; on a workspace it says there is nothing to do.

**The `~/.local/bin` router.** `lane install` wrote a small router to `~/.local/bin/lane`, and pipx links its own
`lane` into the same folder. Until `lane migrate` removes the router, `lane` there may still be the old one: run the
installed `lane` by its full path (pipx prints where it put it), and after the migration run `pipx reinstall repolane`
if pipx skipped linking `lane` because the router was in the way.

## How a lane session saves its Goal and its notes

Inside a lane, Claude Code refuses Edit and Write on any path outside the lane folder ("This session is isolated in the
worktree"), before any hook runs and whatever the settings say. The lane's own file
(`.repolane/registry/lanes/<id>.md`) and the memory folders are outside it. So a session in a lane writes them through
commands, which run without a prompt:

```sh
lane-memory goal "<the goal, in the owner's words>"     # replaces the lane file's ## Goal (refuses another lane's)
lane-memory goal -                                       # the same, with the text on stdin
lane-memory draft <slug> "<what to remember>"            # a memory draft in the inbox (or - for stdin)
lane-memory file <slug> lane|repo <repo>|cross|pref      # file it, once you have picked the scope
```

`LANE.md` tells every session that enters a lane exactly this, and reads of `.repolane/memory/` and
`.repolane/knowledge/` are allowed from every lane. Memory is never filed without you choosing the scope; see
[Concepts](concepts.md#memory).
