# Commands

Every command is one word after `lane`. Run `lane` on its own for the board of what is going on
right now, and `lane help` for this list in your terminal.

## Setting up

| | |
|---|---|
| `lane init` | set this machine up (safe to re-run); `lane init --check` only verifies prerequisites (git, python3, gh, claude) and exits — changes nothing |
| `lane add <git-url\|path> [name]` | bring a repo under management — a local checkout with no `origin` remote is registered as local-only |
| `lane import` | bring past Claude conversations in — entirely optional; copies the conversation (original untouched); `--list` shows what was found and changes nothing |
| `./lane install [dest] [--as <name>] [--make-active] [--force\|-y]` | put the stable, multi-plane `lane` dispatcher and the long-form commands on your `PATH`, and register this checkout in `~/.local/share/lane/planes.json` under `<name>` (default: the directory's basename). Always safe to re-run, from any checkout — it only makes `active` this checkout's plane when nothing is active yet, or when `--make-active` is passed (and that switch is confirmed first if it would change an already-set `active`, unless `--force`/`-y`). Migrates an old, pre-registry install automatically. |
| `lane use [<name>]` | with no argument, lists every registered plane (path, which is `active`, which the current directory would resolve to); with a name, sets `active` to it |

## Doing the work

| | |
|---|---|
| `lane start <id> <repo> [<repo>…]` | start a piece of work: a branch and a worktree in each repo |
| `lane resume <id>` | pick work back up |
| `lane park <id> "<note>"` | leave work for later, with a note to your future self |
| `lane done <id> [--delete-branches] [--delete-sessions\|--keep-sessions]` | finish and clean up — refuses while anything is dirty or unpushed; asks what to do with each repo's leftover Claude sessions unless a flag says |
| `lane with <id> <repo>` | add a repo to work already started |

A lane id may carry a branch and a base per repo: `lane start ABC-123 web:feature/login api@release-2`
checks out `feature/login` in `web` and branches `api` from `release-2`.

`lane done` asks, per repo, whether to delete that repo's Claude sessions once its worktree is
gone (`registry/config.yml`'s `lanes: delete_sessions_on_done:` only sets which answer it defaults
to, never skips the question); `--delete-sessions`/`--keep-sessions` answer it up front, and a
non-interactive run never deletes, only reports what it found.

## Seeing where things stand

| | |
|---|---|
| `lane status` | every repo, every lane, any drift, and the control plane's own git state |
| `lane brief <id>` | catch up on one piece of work |
| `lane board` | the same thing in a browser — opens showing whichever plane it was started from/inside; a switcher in the command bar (when more than one plane is registered) loads another registered plane's data in place, without starting a second server or tab — see [`docs/board.md`](board.md) |
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
| `lane doctor` | check the safety rules are actually working |
| `lane nested` | find and repair nested worktrees |
| `lane workspace` | write an editor workspace file for the active lanes |
| `lane env [id-or-repo]` | check each worktree's `.env` files are linked in — names only, never values |
| `lane keys <path>` | list the key names in an env file, never the values |
| `lane secrets <repo> scan\|add\|ignore\|list\|ignored` | `scan` candidates; `add` **denies** a path (unreadable to every future session) — beyond the built-in set; `ignore` dismisses a false positive with no deny rule; `list`/`ignored` show what's been denied/dismissed |
| `lane sync [repo]` | check a repo's real GitHub branch protection (`gh api`) and record it for the guard |
| `lane upgrade` | take an update from upstream — fast-forwards if it can, refuses with the manual recipe if it can't |
| `lane rules pull [url\|--latest]` / `lane rules status` | pull a shared, SHA-pinned rules file from a team git repo — see [`docs/extending.md`](extending.md) |

Any executable in `scripts/local/` also becomes a `lane <name>` command of its own — see
[`docs/extending.md`](extending.md).

`lane doctor` is the one to run when something feels wrong. It compiles the guard, fires nine
named probes at it and prints each verdict — eight that must be refused and one ordinary command
that must not, because a guard that refuses everything is broken too — then checks that every lane
and worktree is still wired to it. It also lists any lane nobody has touched in `stale_days`
(`registry/config.yml`, 21 by default) — with its size on disk and the one command that clears it:
`lane done <id>` when the work is merged and pushed, `lane done <id> --delete-branches` when
nothing was ever done on it, `lane park <id> "<note>"` when there is work still in there. It also
lists any managed GitHub repo whose branch protection hasn't been checked with `lane sync` in
`protection: sync_days` (`registry/config.yml`, 7 by default) — with the command to clear it. It
only ever tells you; clearing a lane, or syncing a repo, is always a command you type — `lane sync`
is never run for you. It also checks, advisory-only like the rest of this list: whether the `lane`
on your `PATH` is actually the stable, multi-plane dispatcher rather than a stale, pre-registry
symlink (`lane install` if not); whether this checkout is registered in
`~/.local/share/lane/planes.json` at all (`lane install` if not); whether resolving `lane` from
inside this checkout actually picks it — a canary that should never fire if the resolver logic is
correct; whether `gh` is
installed and authenticated (`lane sync`, `lane gh` need it); per active lane, whether what its
spec file says it contains (`repo:`/`branch:` pairs) still matches what's actually checked out
under `lanes/<id>/` on disk; any repo with a candidate secret/credential filename nobody has
reviewed with `lane secrets` (neither denied with `add` nor dismissed with `ignore`); any
`scripts/local/<name>` shadowed by a built-in of the same name
(it will never run); and — printed first, more prominently than the rest — whether a configured
`lane rules pull` source has moved since it was last pinned. `lane doctor -v` adds every wiring
location and runs the full guard suite against a throwaway control plane it builds and deletes.
Any failure exits non-zero — none of the advisories above do, only a genuinely broken rule or
guard does.

`lane upgrade` automates the manual procedure in
[Troubleshooting → "Upgrade friction"](troubleshooting.md#upgrade-friction-the-clone-is-the-control-plane):
it refuses if tracked files outside `registry/`, `memory/`, `knowledge/`, `CLAUDE.md` and
`.claude/settings.local.json` are dirty, fetches, and fast-forwards onto upstream only if that is
a clean fast-forward. Any real divergence — local commits, a conflict — stops with no merge
attempted and prints the same manual recipe (including the `.claude/settings.json`
`git checkout --theirs` step if that's the conflict). Once you commit your own control-plane state
(which the manual recipe itself has you do), `lane upgrade` will always refuse from then on — a
local commit is never a clean fast-forward — so from that point on the manual recipe is how you
upgrade, not a fallback for when something went wrong. On a successful fast-forward it prints the
`VERSION` delta and the `CHANGELOG.md` sections that landed, then runs `lane doctor` automatically
— the one command this repo lets another command run for you, because doctor is read-only.

## Long-form names

Every command also exists as its own executable — `lane-start`, `lane-run`, `lane-memory` and so
on — written onto your `PATH` by `lane install`. They are what the guard messages and the agent
prompts tell you to type, and they run from any directory without a `cd`. Each one is a tiny stub
that routes through the same stable, multi-plane `lane` dispatcher — `lane-brief` is exactly
`lane brief`, `lane-env-check` is `lane env`, and so on — so they resolve to the same plane bare
`lane` would from the same spot, never a second, separate resolution path. Two names don't follow
the mechanical `lane-<word>` → `<word>` mapping: `lane-memory` routes to `lane note`, and
`guard-check` (no `lane-` prefix) routes to `lane doctor`.
