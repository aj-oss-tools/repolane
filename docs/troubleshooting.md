# When something goes wrong

Every failure on this page has been reproduced against a real workspace, and every command
shown was run. Where the tool's own advice is wrong, this page says so.

Start with `lane doctor` and `lane status`. Between them they detect most of what follows, and
`lane doctor` exits non-zero when anything is actually broken, so it is safe to put in a script.

---

## A `lane start` that stopped half way

`lane start` validates the id and every repo name before it touches the disk, then creates the
worktrees one at a time. A base that does not exist is only discovered when its repo's turn comes —
so the repos before it in the list already have worktrees, and the ones after it do not:

```
$ lane start SHOP-431 api web@no-such-base
worktree /…/lanes/SHOP-431/api on new branch SHOP-431 (from origin/main)
base 'no-such-base' not found in web. Closest branches:
error: cannot start web: no such base
```

### What is on disk

The lane folder exists and holds only the repos that got as far as being created. The lane file in
`.repolane/registry/lanes/<id>.md` exists too, and lists only those repos — the one that failed was never
written to it, because registration happens after the worktree succeeds.

What is *missing* is everything that runs after the loop: the lane's `CLAUDE.md`, the anchor repo
that stops git claiming the folder, the workspace file, and — the one that matters — the permission
guards. So the half-made lane is **unguarded**:

```
$ lane doctor
Workspace ~/work:
  …
  !!    lanes/SHOP-431: a settings.local.json is missing, so a session there is unguarded
        fix: run: lane resume SHOP-431
  …
guard.py compiles; 11/11 probes answered as they should:
  …
7/9 places point at guard.py: 3 lane(s), 5 worktree(s), the root
!! the guard is healthy but NOT in force everywhere:
     lanes/SHOP-431: no .claude/settings.local.json — run `lane resume` to rewrite it
     lanes/SHOP-431/api: no .claude/settings.local.json — run `lane resume` to rewrite it
```

Do not start a session in that folder until this is fixed. `lane status` will not warn you: it
reads the lane file, so it shows the lane as ordinary and active, listing only the repo that
worked. The repo that failed is invisible to it, because as far as the lane file is concerned you
never asked for it.

### Finishing it

Fix the reason the base was rejected, then add the missing repo. This is the normal path, and it
also writes everything the interrupted run skipped:

```
lane with SHOP-431 web           # or: lane with SHOP-431 web@develop
lane doctor                      # back to 0
```

If you only wanted the repos you got, run `lane resume <id>`. It is the same repair: it rewrites
the guards, the `CLAUDE.md` and the anchor for whatever the lane file says it contains.

### Unwinding it

`lane done <id>` removes the worktrees and archives the lane file — but it refuses while anything
is dirty or unpushed, which a lane made seconds ago usually is. For a lane with nothing in it:

```
lane done SHOP-431 --delete-branches
```

`--delete-branches` is what stops a half-made lane leaving a branch behind. If you drop the lane
without it, the branch stays in the mirror and the next `lane start <same-id>` silently checks the
old branch out instead of creating one — which looks like the base you asked for being ignored,
because it is. `git -C .repolane/repos/<repo> branch --list` shows what is there.

---

## A worktree that was deleted or moved behind git's back

Deleting `lanes/<id>/<repo>` with `rm -rf`, or moving it, does not tell git. Git keeps the
registration in `.repolane/repos/<repo>/.git/worktrees/`, so the path is still claimed and nothing can be
created there again:

```
$ git -C .repolane/repos/api worktree list
/…/.repolane/repos/api       5a5171c [main]
/…/lanes/SHOP-431/api        0d94433 [SHOP-431] prunable
```

`lane status` reports it in the lane's own terms and tells you the fix:

```
  SHOP-431 [active] updated 2026-09-18 ticket=
     api/SHOP-431: no worktree (lane-resume recreates)
```

### `lane resume`, not `lane nested`

**`lane resume <id>` is the tool.** It runs `git worktree prune` across every mirror *first* —
which is what clears the stale registration — and then recreates the missing worktrees on their
recorded branches, relinks the env files, and rewrites the guards:

```
lane resume SHOP-431
```

Because it prunes every mirror, not just the lane's, one `lane resume` on any lane clears stale
entries left anywhere in the workspace.

**`lane nested` is for a different problem** and will not help here. It finds worktrees that sit
*inside* another worktree — a genuinely broken state, because the outer repo then sees the inner
one's files as its own untracked mess:

```
$ lane nested
  lanes/SHOP-431/web/inner  [TRY-NEST]  inside  lanes/SHOP-431/web  (0 uncommitted)
```

`lane nested --fix` removes them, and refuses any that have uncommitted work:

```
$ lane nested --fix
  lanes/SHOP-431/web/inner  [TRY-NEST]  inside  lanes/SHOP-431/web  (1 uncommitted)
     skipped — it has uncommitted work; deal with that first
```

Removing a worktree never deletes its branch, so nothing is lost either way.

Running `git worktree prune` yourself is safe and does the same clearing that `lane resume` does
first — but on its own it only forgets the dead path. It does not bring the worktree back. Prefer
`lane resume`, which does both.

---

## `lane doctor` is failing

`lane doctor` makes four separate claims, and a failure in each has a different repair. Read which
section the `!!` line is in.

The stale-lane list at the bottom is not one of them: it never fails the command, and it is
describing untidiness, not breakage. What each line means, and what the command it suggests will
do, is in [rules.md](rules.md), under "Rules of your own".

### 0. The workspace is not wired

The first block, `Workspace <folder>:`, checks what the hooks depend on. Each `!!` line carries its fix, and
`lane doctor --fix` applies the safe ones (it asks before editing `CLAUDE.md` or anything under `~/.claude`;
`--yes` answers yes).

#### The hooks fail because `lane` is not on PATH

```
  !!    `lane` is not on PATH: every hook in this workspace runs `lane hook …`, so every hook fails and Claude Code runs tools UNGUARDED
        fix: put the folder lane is installed in on PATH (in your shell profile), then open a new terminal: export PATH="…:$PATH"
```

This is the most serious line the doctor can print. Every hook in `.claude/settings.json` and in every lane is a
`lane hook …` command, run by Claude Code through your shell's PATH. When `lane` cannot be found, the hook cannot
start, and Claude Code treats a hook that fails to start as no objection: **the guard fails open**, every tool call
goes through, and nothing on screen says so. No refusals, no `[lane]` line on prompts, no SessionStart text: if a
session is suddenly that quiet, this is why.

It happens after a pipx install whose bin folder (usually `~/.local/bin`) is not on PATH (`pipx ensurepath` adds
it), or when Claude Code is started from an app or launcher that does not read your shell profile. Add the `export`
line the doctor prints to your shell profile, open a new terminal, start Claude Code from it, and run `lane doctor`
again. Running the doctor itself by full path (`~/.local/bin/lane doctor`) works when `lane` is not on PATH.

#### Repolane's rules do not load: the import line is missing

```
  !!    CLAUDE.md does not import .repolane/REPOLANE.md: Repolane's rules do not load here
        fix: add the line @.repolane/REPOLANE.md to CLAUDE.md, or run: lane doctor --fix (it asks first)
```

The hooks still guard every tool call, but the session never reads the rules: it does not know about lanes, the
`lane-*` commands or how to save memory, and works against the refusals instead of with them. `lane init` adds the
line to an existing `CLAUDE.md` only after you say yes, and with no terminal and no `--yes` it leaves the file
alone, so this is what you see after `lane init` ran in a script, or after you answered no. Add the line anywhere in
`CLAUDE.md` yourself, or run `lane doctor --fix`.

#### The other workspace lines

| what it says | what to run |
|---|---|
| `.claude/settings.json does not run the expected lane hook commands` | `lane doctor --fix` (Repolane's hooks rewritten, your own keys and hooks kept) |
| `REPOLANE.md and LANE.md are version X's`, not the installed one | `lane upgrade --refresh-only` (or any `lane` command, which refreshes them) |
| not registered in `planes.json` | `lane doctor --fix`; `lane upgrade` only refreshes registered workspaces |
| `lanes/<id>: a settings.local.json is missing` or runs old hooks | `lane resume <id>` |
| Claude Code's memory is not linked into `.repolane/memory` | `lane doctor --fix` (asks first). One you declined is a note, not a failure |
| the status line runs a clone's `scripts/statusline.sh` | `lane doctor --fix` (sets `lane statusline`) |

### 1. The guard does not compile

```
!! scripts/hooks/guard.py does not compile — EVERY rule is currently off:
       File "/…/scripts/hooks/guard.py", line 772
         def (
             ^
     SyntaxError: invalid syntax
```

This is the worst of the three and the most urgent: a hook that cannot start cannot refuse
anything, so every rule in [`docs/rules.md`](rules.md) is off right now. The guard is part of the
installed package, so this means the package's files were changed or damaged. Put them back:

```
pipx reinstall repolane          # or: uv tool install --reinstall repolane
lane doctor -v
```

`lane doctor -v` runs the full guard suite against a throwaway one it builds under `$HOME` and deletes on exit,
so it is safe to run at any time.

### 2. A probe answered wrongly

```
!! guard.py compiles but is not enforcing — 1/11 probes answered as they should:
  !! pass reading a .env — wanted deny
  !! pass a push to a default branch — wanted deny
  …
  pass   ordinary work is untouched
   a rule that stopped refusing is a rule that is gone. Check recent edits to scripts/hooks/guard.py.
```

The guard runs, but a rule has stopped firing. The probes are named after the rule they check, so
the failing line tells you which. With the package as it was released, every probe passes, so either the
package's files were edited (reinstall it, as above) or a rule of your own in `.repolane/registry/rules.yaml`
changed what an ordinary command gets.

One of the eleven is a control: *"ordinary work is untouched"* must come back `pass`. If it is the one
that failed, the guard has become too strict rather than too loose, and every ordinary command in
every session is being refused.

Run `lane doctor -v` for the detail — well over a thousand cases against the same guard will say
far more than eleven probes will.

### 3. Something is not pointing at the guard

This is the common one.

```
9/10 places point at guard.py: 3 lane(s), 6 worktree(s), the root
!! the guard is healthy but NOT in force everywhere:
     lanes/SHOP-412/web: hooks do not point at guard.py — this session is UNGUARDED
   fix with: lane resume <id>   (rewrites the guard for that lane)
```

Each lane folder and each worktree inside it has a generated `.claude/settings.local.json` holding
the `lane hook` commands that call the guard. It is generated, machine-local, and rewritten by `lane start`,
`lane resume`, `lane with`, `lane ref` and `lane upgrade`. A session whose copy is missing, emptied, or overwritten
by something that writes that file without preserving its `hooks` block is unguarded, even though
`guard.py` itself is in perfect health. `lane doctor` distinguishes three states:

| what it says | what happened |
|---|---|
| `no .claude/settings.local.json` | the file was deleted, or was never written (an interrupted `lane start`) |
| `hooks do not point at guard.py` | valid JSON, but the `hooks` block was dropped or replaced |
| `settings.local.json is not valid JSON` | the file was truncated or clobbered mid-write |

For the first two, the advice on screen is right:

```
lane resume SHOP-412
```

**For the third it is not.** `lane resume` reads the existing file so it can merge into it, and on
invalid JSON it dies with a Python traceback rather than repairing anything:

```
$ lane resume SHOP-412
Traceback (most recent call last):
  …
json.decoder.JSONDecodeError: Expecting property name enclosed in double quotes: line 1 column 2
```

Delete the unreadable file first — nothing in it is yours, it is entirely generated — and then
resume:

```
rm lanes/SHOP-412/web/.claude/settings.local.json
lane resume SHOP-412
```

#### When it is the root that is unwired

```
!! the guard is healthy but NOT in force everywhere:
     the control plane root: hooks do not point at guard.py
   fix with: lane resume <id>   (rewrites the guard for that lane)
```

**Ignore that advice here.** The root's hooks live in `.claude/settings.json`, which is your file, not a lane's,
so `lane resume` does not touch it. The workspace block above it says the same thing with the right fix:

```
lane doctor --fix
```

It rewrites Repolane's hooks in `.claude/settings.json` and keeps every key and hook of your own. If the file is not
valid JSON, the doctor says so and leaves it alone; mend it (or move it aside), then run `lane doctor --fix`.

---

## A refusal you think is wrong

### Is it the guard, or is it Claude Code?

They look similar in the transcript and come from different places.

**An ordinary Claude Code permission prompt** asks you, offers to allow it once or always, and
names a tool and a pattern. Approving it is the whole answer.

**A guard refusal** never asks. The tool call is denied outright, and the message explains itself in
this tool's vocabulary — lanes, mirrors, the owner's name from `.repolane/config.yml` — and usually
names the command that would make it legitimate:

```
That pushes to a default branch (main/master/develop). Ask John Doe first. If they agree,
run it with the marker they can see: ALLOW_DEFAULT_BRANCH_PUSH=1 git push …
```

```
'SHOP-418' is a different lane. This session is in 'SHOP-412'. Ask John Doe to add that repo
with scripts/lane-with SHOP-412 <repo>, or switch lanes.
```

If you see wording like that, no amount of approving prompts will help: the refusal is not a
permission question. Every one of them, and the failure that caused it, is in
[`docs/rules.md`](rules.md). To see a refusal for yourself without a session, feed the guard a
hook event on stdin:

```
printf '{"hook_event_name":"PreToolUse","tool_name":"Bash","cwd":"'$PWD'","tool_input":{"command":"git push origin main"}}' \
  | lane hook pre-tool-use
```

Run it from the workspace (or a lane). Empty output means the guard has no objection.

### The documented ways through

Each of these is a deliberate opening, not a workaround.

**You need code or documents that live outside the repos.** Attach them to the lane. They appear at
`lanes/<id>/refs/<name>` and are readable from then on:

```
lane ref SHOP-412 add ~/specs/checkout-v2
```

Refs are read-only to the session by default — a write comes back with
*"This is a read-only reference of lane 'SHOP-412'. Read it, do not change it."* If the session
genuinely should edit them, re-add with `--rw`, which replaces the existing entry:

```
lane ref SHOP-412 add ~/specs/checkout-v2 --rw
```

This constrains the session, not you: underneath it is a symlink, and your own editor is unaffected.

**You genuinely mean to push to `main`.** Prefix the command with the marker. It is deliberately
visible in the transcript, so the push is something you can see was chosen:

```
ALLOW_DEFAULT_BRANCH_PUSH=1 git push origin main
```

**The session needs to know what is in a `.env`.** This one has no override, by design: the read
itself is the problem, and approving it does not make the secret un-read. There are two sanctioned
answers. For the *names*, which is what is almost always actually wanted:

```
$ lane keys .repolane/repos/api/.env
variables in .repolane/repos/api/.env (names only):
  API_KEY
  DATABASE_URL
```

For the *shape* — names, comments, expected formats — use the repo's `.env.example`, which is not a
secret and is not refused. If a repo has no `.env.example`, writing one is usually the real fix, and
it helps every human who clones the repo too. For *behaviour*, run the app and read its output.

---

## Upgrading

`lane upgrade` upgrades the package and then refreshes every registered workspace; `lane upgrade --check` shows what
it would do. What can go wrong:

- **It printed a `pip` command instead of upgrading.** The package was installed with pip (into a venv, say), not
  pipx or uv. Run the command it printed, then `lane upgrade --refresh-only`.
- **"PyPI cannot be reached".** `--check` needs the network; nothing was changed.
- **A workspace "is gone".** A registered folder was moved or deleted. It is skipped, and you are asked whether to
  drop it from `~/.local/share/lane/planes.json` (`--drop-missing` drops it). A moved workspace registers itself again
  the next time you run `lane init` or `lane upgrade` inside it.
- **A workspace could not be refreshed.** Usually a `.claude/settings.json` that is not valid JSON. Mend it, then
  `lane upgrade --refresh-only`. The exit status stays non-zero until every workspace is refreshed.

A workspace that was not refreshed by `lane upgrade` still catches up on its own: the first `lane` command or hook
after the installed version changes rewrites `REPOLANE.md` and `LANE.md`.

---

## Moving from a git-clone install

The steps are in [Installing Repolane](install.md#moving-from-a-git-clone-install). The ways it stops:

**`lane migrate` refuses while Claude Code is running.**

```
lane migrate: Claude Code is running inside ~/repolane:
    pid 4242 in /Users/you/repolane/lanes/SHOP-412
  Its hooks would vanish under it. End those sessions (/exit), then run lane migrate again, from a terminal.
```

A running session's hooks point into the clone, and the migration removes those files, so a session left running
would go on unguarded. End every session in the folder and its lanes, then run `lane migrate` again from a plain
terminal (not from a Claude Code shell).

**`lane migrate` "runs from the installed package, not from the clone itself".** The `lane` you ran is still the
clone's (the router `lane install` wrote to `~/.local/bin/lane` sends every call to the clone). Run the installed one
by its full path; pipx prints where it put it, and `pipx list` shows it again. After the migration has removed the
router, `pipx reinstall repolane` links the package's own `lane` there if pipx skipped it before.

**"both X and Y exist".** The folder already has a `.repolane/<name>` next to the clone's `<name>`, from an earlier
attempt or by hand. Move one aside, then run `lane migrate` again.

**`.claude/settings.json is not valid JSON`.** Mend it first; the migration only ever merges into it.

**It stopped half way** (the terminal closed, the machine slept). Run `lane migrate` again: each step is recorded,
and it continues where it stopped.

**You want the clone back.** `lane migrate --undo <backup>` with the backup path it printed
(`~/.local/share/lane/backups/<folder>-<time>.tar.gz`) restores the clone install; what was written in the
workspace since is kept aside.

### Upgrade friction: if the clone's own `lane upgrade` refuses

Moving over starts with `lane upgrade` inside the clone, and that is the clone's own upgrader, which only
fast-forwards. It refuses when tracked files outside `registry/`, `memory/`, `knowledge/`, `CLAUDE.md` and
`.claude/settings*.json` are dirty, and when the clone has commits of its own (a fast-forward is then impossible).
Its recipe:

```
git add registry knowledge memory CLAUDE.md && git commit -m "my control plane"   # keep your state
git pull                                                                          # a real merge
```

The usual conflict is `.claude/settings.json`. Take upstream's version (`git checkout --theirs .claude/settings.json`,
`git add .claude/settings.json`, `git commit`), then `lane doctor`. `git merge --abort` returns you to where you were;
none of this touches `lanes/` or `repos/`. If the refusal names `.claude/settings.json` as modified by `lane init`,
run `git checkout -- .claude/settings.json`, then `lane upgrade`, then `lane init --yes`.

Once the clone is up to date, continue with `pipx install repolane` and `lane migrate`.

---

## `lane done` refuses to finish a lane

`lane done` checks **every** repo in the lane before removing **any** of them, and prints all the
problems at once. Nothing has been touched when you see this:

```
$ lane done SHOP-431
not finishing SHOP-431 — nothing was removed:
  web/SHOP-431 was never pushed — push it, or delete the branch first
  api/SHOP-431 has 1 unpushed commit(s)
```

The check-everything-first order is deliberate: checking and removing in one pass once lost a first
repo's worktree before failing on the second.

There are four things it complains about.

**`<repo> is dirty — commit it, or lane park first`** — uncommitted changes in that worktree.
Commit them, or `lane park <id> "<note>"`, which wip-commits every dirty worktree on its own
branch, records the note and marks the lane parked. The note has to be at least ten characters —
where things stand, the next step, the blockers — because a one-word note is no use to the you who
comes back.
 `git -C lanes/<id>/<repo> status` shows what it found; a stray build artefact is the
usual culprit, and belongs in that repo's `.gitignore`.

**`<repo>/<branch> has N unpushed commit(s)`** — push them:

```
lane run --lane <id> <repo> git push -u origin <branch>
```

`lane run <repo> <cmd>` on its own works only from inside a lane folder; from the control-plane
root it answers *"not inside a lane — name one"*, so pass `--lane <id>`.

**`<repo>/<branch> was never pushed — push it, or delete the branch first`** — the branch has no
upstream at all, so there is nothing to compare against and the tool will not guess. Either push it
as above, or, if the work is genuinely being abandoned, tell `lane done` to take the branch with it:

```
lane done SHOP-431 --delete-branches
```

Note that a branch created by `lane start` usually tracks the base it came from, often
`origin/main` — so "unpushed" is measured against that base until you push the branch itself. A lane
with real work in it can therefore report `0 unpushed` and still have a branch that exists nowhere
but your machine. `lane run --lane <id> <repo> git push -u origin <branch>` sets this straight.

**`the worktree is missing and the branch is not fully pushed — lane resume <id> first`** — the
worktree folder is gone, so the check cannot be made from inside it, and the branch it named still
holds commits that are not on the remote. This is exactly the case that once archived a lane with
unpushed commits on a branch nobody could see. `lane resume <id>` brings the worktree back so you
can look at what is on it and decide.

---

## Smaller traps

**`lane env [id-or-repo]` accepts either.** `lane env` with no argument checks every lane:

```
$ lane env
  SHOP-412/api       0/1 env files   MISSING: .env  (run: lane-resume SHOP-412)
  SHOP-412/web       0/0 env files
```

Env files are gitignored, so a fresh worktree has none; `lane start` and `lane resume` symlink them
in from the mirror. A worktree created *before* you added a `.env` to `.repolane/repos/<repo>` will not have
the link — `lane resume <id>` adds it.

**Nothing works outside a workspace.** Any command other than `init` and `help`, run in a folder
that is not inside a workspace, stops with:

```
lane: this control plane is not set up yet
  run:  lane init
```

`lane` looks for `.repolane/` in the current folder and every folder above it. `cd` into your workspace (or set
`LANE_WORKSPACE`), or run `lane init` to make this folder one. `lane init` is safe to re-run at any time.

**Commands the docs mention are "command not found".** The guard's messages and the agent prompts
use the long-form names — `lane-start`, `lane-run`, `lane-memory`. The package installs them next to `lane`, so
if `lane` works and they do not, an old install is in the way: `pipx reinstall repolane`. If `lane` is not found
either, see [the hooks fail because `lane` is not on PATH](#the-hooks-fail-because-lane-is-not-on-path).

**A lane session cannot save its Goal or a memory.** Inside a lane, Claude Code refuses Edit and Write on any path
outside the lane folder ("This session is isolated in the worktree"), and the lane file and the memory folders are
outside it. That refusal is Claude Code's own and no setting turns it off. The session should run
`lane-memory goal "<text>"` and `lane-memory draft <slug> "<text>"` instead; `LANE.md` tells it so. If it keeps
trying Edit, check that the import line is in `CLAUDE.md` (above).

**`!! oversized guard files (rules are repeating)`** in `lane status` means a generated
`settings.local.json` has grown past 20 KB because deny rules accumulated instead of being replaced.
`lane resume <id>` rewrites it from scratch.

**`!! worktree outside lanes/`** in `lane status` means a worktree of one of your mirrors exists
somewhere this tool does not manage. It is not dangerous, but it is invisible to every lane command,
and it is usually a checkout that predates the workspace. Either move the work into a lane, or
remove it with `git -C .repolane/repos/<repo> worktree remove <path>`.

**A mirror is dirty or off its default branch.** `lane status` flags both:

```
  api: SHOP-412, behind origin by 0, worktrees=2 !! not on main !! dirty (mirror must stay clean)
```

Every worktree shares the mirror's object store, so the mirror is not a place to work. Move the
changes into a lane, then put the mirror back:

```
git -C .repolane/repos/api stash
git -C .repolane/repos/api checkout main
```

---

## Reporting something

If none of this covers it, open an issue at
<https://github.com/aj-oss-tools/repolane/issues> with the output of:

```
lane --version
lane doctor -v
lane status
```

`lane doctor -v` prints every wiring location and runs the full guard suite, so it is the single
most useful thing to paste. None of these three commands prints the contents of a secret file; check
the paths before you post, since they include your own directory names.
