<div align="center">

<img src="docs/assets/icon.svg" alt="" width="64" height="64">

# Repolane

**One piece of work at a time, across all your repos.**

A control plane for multi-repo development — and a set of rules that keeps an AI coding session
inside the work it was actually asked to do.

The command is `lane`.

**[repolane.dev](https://repolane.dev)**

[Install](#install) · [How it works](#how-it-works) · [The rules](#why-it-refuses-things) · [Docs](https://repolane.dev/docs/concepts/) · [Apache 2.0](LICENSE)

</div>

---

## The problem

Your product is six repos. A ticket touches three of them. You have four tickets in flight.

So you keep four checkouts of `web`, two of `api`, and a `web-hotfix` you are afraid to delete.
Monday's branch is checked out in a directory you last opened on Thursday. Two of those checkouts
have uncommitted work in them. You stash something and lose track of which clone it landed in.

Then you point Claude Code at one of those folders, and it makes it worse: the session only sees
one repo, so cross-repo work becomes a sequence of context-free single-repo sessions. Ask it to fix
one bug and it wanders into three other repos looking for context, filling its window with code
nobody asked about. It learns something useful about your deploy process and writes it down as a
permanent global preference. It commits when you wanted to look first.

Repolane fixes the layout *and* the behaviour, because neither one works on its own.

## The idea

**A lane is one piece of work.** It may span any number of repos.

```sh
lane start ABC-123 web api
```

That gives you a branch named `ABC-123` in both repos and a folder holding a worktree of each:

```
lanes/ABC-123/
  web/     a worktree of repos/web on branch ABC-123
  api/     a worktree of repos/api on branch ABC-123
  refs/    anything you attached for reference
```

Each repo is cloned **once**, into `repos/<name>`, and that copy is a mirror: always on its default
branch, never edited, never switched. Every lane's worktrees share its object store, so the second
piece of work costs a checkout of files rather than a full clone, and switching between them is
instant. Ten lanes across six repos is still six clones on disk.

You run Claude from `lanes/<id>/` — the lane itself, not one of the repos inside it. No repo is the
main one. That single detail is what keeps multi-repo work from collapsing back into single-repo
work.

```sh
cd lanes/ABC-123 && claude       # opens knowing what this work is
lane park ABC-123 "waiting on review for the api side"
lane done ABC-123                # removes the folders once everything is pushed
```

`lane park` writes a resume note *and* wip-commits anything dirty, so nothing is left loose in a
worktree. `lane done` refuses while any repo is dirty or holds unpushed commits — and it checks
every repo before it removes any of them, so a lane whose second repo has unpushed work does not
lose the first repo's worktree on the way to failing.

## Install

```sh
git clone https://github.com/aj-oss-tools/repolane.git && cd repolane
./lane install        # puts `lane` and the long-form commands on your PATH
lane init             # asks two questions, sets the machine up
lane add <git-url>    # or: lane add ~/path/to/a/checkout/you/already/have
```

Just want to see if this would work before committing to it? `lane init --check` verifies the
prerequisites (git, python3, optionally gh and claude) and exits — it changes nothing on your
machine.

| | |
|---|---|
| **git** | required — worktrees are the whole mechanism |
| **python3** | required — the hook dispatcher and the board are stdlib Python, no packages |
| **bash** | required — every command is a bash script |
| **gh** | optional — pull request status and `lane gh` |
| **Claude Code** | optional — the commands work on their own; the hooks only matter when Claude is driving |

Nothing is compiled, nothing is published to a package registry, and nothing phones home. Repolane
is a folder of scripts. Tested on macOS and Linux; on Windows use WSL.

`lane add` takes a checkout you already have, not just a URL — it adopts the existing `.git`, keeps
the origin, and remembers where it came from so `lane import` can find the Claude conversations you
already had about that repo.

`lane import` is entirely optional and safe to poke at: `lane import --list` only shows what was
found on this machine and changes nothing, and bringing a conversation in **copies** it into the
lane's folder — the original conversation, wherever it was, is left exactly where it was.

## How it works

Three pieces, each doing one job.

### 1. The layout

`repos/` holds clean mirrors. `lanes/` holds the work. `registry/` is the source of truth that
describes both — `repos.yaml` lists the repos, and `registry/lanes/<id>.md` is one file per lane
carrying its goal, resume note, findings, log, and the list of repos in scope.

That registry file is also **the allow-list for a session**: the repos it names are the repos the
work may touch. `repos/` and `lanes/` are gitignored, because they are machine state that the
registry can rebuild. Deleted a worktree by hand? `lane resume <id>` prunes the stale registration
and recreates it.

### 2. The guard

`scripts/hooks/guard.py` is a hook dispatcher wired into Claude Code's `PreToolUse`, `PostToolUse`,
`UserPromptSubmit`, `PreCompact`, `SessionEnd`, `SessionStart` and worktree events. It reads the
hook JSON on stdin and answers allow, deny, or "here is some context you are missing."

It is not a prompt asking nicely. It inspects the actual tool call — including the text of every
Bash command, each segment of a chain, and every path any of them names — and it judges paths by
what was *written*, so a symlink or a `..` that climbs out of the lane is refused exactly like its
absolute twin. It fails open on malformed input, because a crashed guard that blocks everything is
worse than one that lets an odd call through.

It also *adds* context rather than only removing options: the first time a session touches a repo
it injects that repo's own `CLAUDE.md` and rules list, and the first prompt in a lane carries the
memory index for every repo in scope.

`lane doctor` compiles it and fires nine named probes at it — eight that must be refused and one
ordinary command that must not — so you find out when the rules stop being enforced. Behind that
there is a 184-case suite in `scripts/hooks/test-guard.sh`, which `lane doctor -v` runs.

### 3. The board

`lane board` serves a local web page: every lane, what each one touches, the files you changed, the
diff of the one you picked, a commit box, history across all repos of a lane at once, notes, refs
and the memory browser. It is plain HTML, CSS and JavaScript with no build step, served by a stdlib
Python server bound to `127.0.0.1` with a per-run token. Secret files are dropped by path before git
is ever asked for their content.

## Why it refuses things

Every rule below exists because the alternative went wrong at least once. `docs/rules.md` tells
each story.

- **A session stays in its lane.** It cannot read another lane, the mirrors, or anything outside the
  control plane. Need something from outside? `lane ref <id> add <path>` attaches it once, and it is
  readable at `lanes/<id>/refs/<name>`. A reference is read-only to a Claude session — the hook
  refuses writes through it unless you pass `--rw`. On disk it is a symlink, so your own editor can
  still write to it.
- **Nobody enters a repo.** The session sits at the lane root. `lane run <repo> <cmd>`,
  `lane gh <repo> <args>`, `git -C <repo>` and editing `<repo>/file` all work without moving, and a
  `cd` into a repo is refused — in Claude Code a `cd` moves the session itself, so one `cd` for
  convenience strands it.
- **Secrets are never read.** Not `.env`, not `*.pem`, not `credentials.json` — not even with
  permission, because the read itself is the problem: the values end up in a transcript. Structure
  comes from `.env.example` or `lane keys <path>`, which lists names and never values. Denial is the
  default: `cp .env /tmp/x && cat /tmp/x` is the whole attack, so copying and linking are refused
  too.
- **Default branches are protected.** Pushing to `main`, `master` or `develop` needs a marker you
  can see — `ALLOW_DEFAULT_BRANCH_PUSH=1 git push …`. Remotes may never be added, changed or
  removed. Destructive `gh` calls (`repo delete`, writing `gh api`) are refused outright.
- **Memory is never written silently.** Claude drafts it, then asks which of four scopes it belongs
  in, chosen by *how long it stays true*: `pref` (always), `cross` (every repo), `repo` (that repo,
  after this ships) or `lane` (only while this work is live). Left alone, everything becomes a
  permanent global preference, and within a month the system is full of things that were true once.
- **The control plane is edited from the root.** A lane cannot change the scripts or the rules that
  constrain it.
- **Commits are proposed, not made.** And new branches start from the default branch, not from
  whatever happened to be checked out.

## The commands

```
lane status     where everything stands        lane board    the same thing in a browser
lane brief      catch up on one piece of work  lane audit    branches that look finished or stale
lane find       which lane touched this file, branch or commit
lane run/gh     run something in one repo without leaving the lane
lane ref        attach outside code or docs    lane note     write something worth remembering
lane merge      two pieces of work turned out to be one
lane import     adopt past Claude conversations
lane doctor     check the safety rules are working, and what needs attention
lane sync       check a repo's real GitHub branch protection
lane rules      pull a team's shared, SHA-pinned rules.yaml
lane upgrade    pull the latest release, ff-only, never an automatic merge
lane help       the full list
```

Every command also exists as its own executable — `lane-start`, `lane-run`, `lane-memory` — so they
run from any directory with no `cd`. Full reference in [`docs/commands.md`](docs/commands.md).
Your own commands work the same way: anything executable in `scripts/local/` becomes `lane <name>`
with no dispatcher edit needed — see [`docs/extending.md`](docs/extending.md).

## Using it without Claude

Nothing above requires an AI. `lane start`, `lane status`, `lane brief`, `lane board` and the rest
are a perfectly ordinary multi-repo worktree manager, and plenty of the value — one clone per repo,
a folder per piece of work, a resume note you wrote to yourself — has nothing to do with a model.
The hooks simply do not fire when Claude is not the one running.

## Documentation

Everything is readable on the site at **[repolane.dev/docs](https://repolane.dev/docs/concepts/)**,
and in this repo:

| | |
|---|---|
| [`docs/concepts.md`](docs/concepts.md) | the five words the whole system is built from — **start here** |
| [`docs/rules.md`](docs/rules.md) | every refusal, and the failure behind it |
| [`docs/commands.md`](docs/commands.md) | the full command reference |
| [`docs/board.md`](docs/board.md) | the web board |
| [`docs/troubleshooting.md`](docs/troubleshooting.md) | the ways it actually breaks, and how to recover |
| [`docs/releasing.md`](docs/releasing.md) | how a merged PR actually becomes a release |
| [`docs/extending.md`](docs/extending.md) | `scripts/local/` custom commands, and `lane rules pull` for shared rules |

Each folder has its own README explaining what lives there:
[`scripts/`](scripts/README.md) · [`scripts/hooks/`](scripts/hooks/README.md) ·
[`scripts/board/`](scripts/board/README.md) · [`registry/`](registry/README.md) ·
[`memory/`](memory/README.md) · [`knowledge/`](knowledge/README.md) ·
[`.claude/`](.claude/README.md)

## What your clone becomes

The folder you clone *is* your control plane — see
[`docs/concepts.md`](docs/concepts.md#the-clone-is-the-control-plane) for what that means and why.
After `lane init` it is no longer just a copy of this repository: `registry/` fills up with your
repos and lanes, `memory/` and `knowledge/` with what Claude has learned about your work, and
`CLAUDE.md` is generated with your name in it. Those are yours to commit — and if you want them
backed up, point the clone at a private remote of your own.

That means `git status` is dirty right after setup, by design. It also means taking an update from
upstream is a `git pull` that may want a merge, most often in `.claude/settings.json` — see
[`docs/troubleshooting.md`](docs/troubleshooting.md#upgrade-friction-the-clone-is-the-control-plane)
for how to resolve it.
Nothing in `repos/` or `lanes/` is ever committed: they are machine state, gitignored, and
rebuildable from the registry.

## Status and contributing

Repolane is used daily by its author and is stable for that use. It is early software: the layout on
disk is settled, the command names are settled, and the guard has a real test suite — but expect
rough edges outside the paths that get walked every day. The current version is whatever
[`VERSION`](VERSION) says — run `lane --version`, which also reports how far a given checkout has
drifted past that release's tag; see [`CHANGELOG.md`](CHANGELOG.md) for what changed.

Issues, discussions and pull requests are welcome, and used: if something is broken, unclear, or
missing, filing it is the useful thing to do. [Issues](https://github.com/aj-oss-tools/repolane/issues)
are for bugs and feature requests — there are templates asking for the command you ran and what it
did. [Discussions](https://github.com/aj-oss-tools/repolane/discussions) are open for everything
more open-ended: questions, "is this a bug or am I holding it wrong", and feedback on where this
should go.

Pull requests are welcome too — see [`CONTRIBUTING.md`](CONTRIBUTING.md) for how to run the
guard's test suite, what the project expects of a change, and how to propose one. The short version:
if you change `scripts/hooks/guard.py`, run `bash scripts/hooks/test-guard.sh` (it builds its own
throwaway control plane, so it runs anywhere and never touches your lanes) and add a case for
whatever you changed. A rule with no test is a rule that will quietly stop working.

Participation is covered by the [Code of Conduct](CODE_OF_CONDUCT.md).

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

## ⚠️ Workflow Safety & Git Integrity

This tool automates local Git operations, file synchronization, and `git worktree` management
across repositories.

* **Commit or Stash Your Work:** Before running multi-repo orchestration tasks, ensure all
  repositories have clean working trees or that your active work is committed or stashed.
* **Non-Destructive by Design:** This framework creates local branches and isolated worktrees.
  It does not automatically run force-push, and never runs a destructive reset against a checkout
  you point it at — the one hard reset that happens automatically is on the mirror `lane add`
  creates for itself, a fresh copy it made moments earlier, never your own working tree.
* **Review Generated Worktrees:** Stale or abandoned worktrees can be reviewed at any time using
  `git worktree list` and cleaned up manually or via `git worktree prune` — or with `lane nested
  --fix` and `lane resume`, which do the same thing with the lane's own state in view; see
  [`docs/troubleshooting.md`](docs/troubleshooting.md).
