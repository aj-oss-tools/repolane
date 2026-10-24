# Repolane workspace

This folder is a Repolane workspace: the owner's place for engineering work across their repos. These rules reach every
session started anywhere below it, through the `@.repolane/REPOLANE.md` line in the workspace's CLAUDE.md. Repolane
rewrites this file when it is upgraded; put your own notes in CLAUDE.md, never here. The owner's name arrives with the
first message of every session; wherever this file says "the owner", it means them.

## Layout
- `CLAUDE.md` — the owner's own file. It imports this one.
- `lanes/<lane>/<repo>/` — worktrees. All real work happens here. One session per lane.
- `.repolane/registry/repos.yaml` — the repos, where they live, default branch, stack.
- `.repolane/registry/lanes/<id>.md` — one file per piece of work. **This is the allow-list for a session**:
  only the repos and paths it names are in scope.
- `.repolane/knowledge/` — preferences, conventions, domain notes. Not auto-loaded; read
  `.repolane/knowledge/preferences.md` at the start of any session that will write code, and
  `.repolane/knowledge/domains/<x>.md` when the lane names it.
- `.repolane/memory/` — cross-repo memory; `.repolane/memory/<repo>/` — per-repo memory.
- `.repolane/repos/<repo>/` — the mirror: always on the default branch. **Read-only.** Never edit, never
  branch-switch here. Used for fetch, baseline diffs, and by the lane commands.
- `.repolane/config.yml` — who the owner is and how the workspace behaves. `.repolane/env.sh` — shared build settings.
- The lane commands are `lane <command>` (`lane help` lists them) and their long names (`lane-brief`, `lane-memory`, …),
  all on PATH. There is no scripts/ folder here.

## Rules for every session
1. Discuss before deciding. Run directly only what is mechanical, reversible and explicitly asked: read-only commands,
   entering the worktree they named, writing a resume note when they say park, edits they described. Everything with
   judgment is proposed in one or two sentences with a recommendation, then you wait: a new lane's id, branch
   or repo set; anything under `~/.claude`, shell rc files or other global config; deleting, renaming or pushing
   anything; scope, design or approach choices. One question at a time. Silence is not consent.
2. Stay in the lane you are in. Never `cd` out of it — a cd moves the session and the way back is
   EnterWorktree, so one cd for convenience strands you. The lane commands run from anywhere without a cd. Reach
   another repo of the lane with `git -C ../<repo>` or an absolute path; write temporary files by absolute
   path under /tmp. Moving around inside your own lane is fine.
3. From the dispatcher root, a lane's files are out of reach — no reading, no editing, no Bash touching
   `lanes/<id>/…`. Enter it (`EnterWorktree name="<id>"`) or ask the commands (`lane-brief <id>`, `lane-status`), which
   read it for you. Its registry file stays editable from the root. The rule is the same in both directions: the
   dispatcher does not reach into a lane, and a lane does not reach out.
4. Work only inside the current lane folder. Do not read or search `.repolane/repos/` or other `lanes/` folders
   unless the lane file lists that repo or the owner says so in this session.
5. Before starting code work in a lane, read its file in `.repolane/registry/lanes/`. Memory indexes (cross-repo
   and every repo in the lane) arrive with your first prompt; a repo's own CLAUDE.md and rules list arrive the
   first time you touch that repo. Open the memory files and rules that match what you are doing.
6. Nothing outside the workspace is yours to read. Not other repos, not `~/.claude`, not the old checkouts. If the work
   genuinely needs something out there, attach it once with `lane-ref <id> add <path> "why"` and read it at
   `lanes/<id>/refs/<name>/…` — the reference path, never the real one. The scratchpad under /tmp is fine for temporary
   files. The hook refuses the rest, for file tools and for Bash alike.
7. The remote and the default branches are not yours. Never `git remote add/set-url/rename/remove`. Never move or
   delete `main`/`master`/`develop`. A push that targets a default branch needs the owner's word first; they can then
   have you run it with the visible marker `ALLOW_DEFAULT_BRANCH_PUSH=1 git push …`.
8. Never read `.env` or credential files. Structure only: `.env.example`, key names in code, or `lane-env-keys <path>`
   (names, no values). The hook denies reads. Worktrees get them as symlinks into the mirror via lane start/resume; if
   one is missing, run `lane-resume <id>`, do not create one.
9. New branches start from the repo's default branch, never from whatever is checked out.
10. When parking or finishing, update the lane file (status, resume note). The file is the handoff.
11. If a repo needs shared build caches or environment settings, put them in `.repolane/env.sh` and
   `source .repolane/env.sh` (from the workspace root) before running its build.
12. Never write memory or preference files directly — the hook refuses it. Four scopes, decided by how long the thing
   stays true: `pref` (how to work with the owner, always) · `cross` (true in every repo) · `repo` (one repo, still true
   after this ticket ships) · `lane` (only while this lane is live, archived with it — its `## Findings`).
   `lane-memory draft <slug> "<draft>"` (or `-` and a heredoc), ask the owner which scope with a recommendation, then
   `lane-memory file <slug> lane|repo <repo>|cross|pref`. Editing a memory that already exists is allowed from a
   dispatcher session at the root (its scope is settled); creating one never is. Same for the workspace's own files
   (CLAUDE.md, `.repolane/`, `.claude/`): propose it, and change it from a dispatcher session, never from inside a lane.
   The one exception is your own lane file, `.repolane/registry/lanes/<id>.md`: you may read it, and you set its Goal
   with `lane-memory goal "<text>"` (Findings go in through `lane-memory file … lane`, the log and resume note through
   `lane park`). Do not try Edit or Write on it, or on anything outside your lane folder: Claude Code refuses those once
   a session is in a worktree. Nothing else under `.repolane/registry/` is yours.
13. One checkout exists for you: the worktree you are in. Report git state only in the STATE form that arrives
   with each prompt (where you are, branch, ahead/behind origin, uncommitted). Never mention the mirrors or the old
   checkouts; they are frozen and the hook blocks them. In a resumed conversation, translate old paths silently.
14. Inside a lane, the work stays in it. Never propose or create another worktree or lane from a
   worktree; if a repo is missing, `lane-with <id> <repo>`. Only when the owner themselves asks for separate, unrelated
   work: park this one, ExitWorktree keep, then start the new one from the root. The hook refuses the shortcuts.
15. Talk plainly: simple words, no jargon. Prefer an ASCII diagram to a long explanation. Never create an artifact
   without asking first.

## Sessions
- New work: `lane start <id> <repo>[:<branch>] [<repo>...]` then `cd lanes/<id> && claude`.
- Resume: `lane resume <id>`. Leaving: `lane park <id> "<note>"`. Finished: `lane done <id>`.
- Morning: `lane status`.

## Entering any conversation
Whatever the entry point (fresh `claude`, `claude --resume <id>`, the picker), the SessionStart hook tells you
where you are and, for a resumed conversation, which repo it belongs to and which lanes exist for it. Your first
message then does the managing, before answering anything else: name the repo, offer to continue in an existing
lane, start a new one, or stay read-only, recommend one, and wait for their answer. Do not enter or create a
worktree until they have chosen. Be a visible operator: every command you run, every worktree you enter or leave,
every lane file you change gets one line in your reply. Nothing about the system may be silent.

## Dispatcher mode (sessions started at the workspace root)
The owner starts `claude` here and says what they want. You do the navigation. Hooks in `.claude/settings.json`
enforce scope for the whole session, also after you move into a worktree.

**Getting into a lane** — EnterWorktree `name: "<lane-id>"`. Only that: no repo, no path, and never a
`cd` from outside. It puts you **in the lane itself**, not in one of its repos, and the lane's own rules arrive
right after it.
**A lane is one piece of work across its repos, and the session stays at its root.** You never enter a repo:
edit files at `<repo>/…`, run git with `git -C <repo> …`, run anything that must execute inside a repo with
`lane-run <repo> <cmd…>` (mvn, yarn, tests), and use `lane-gh <repo> <args…>` for GitHub. **`cd` into a repo is
refused.** **Never exit and re-enter to change repo.** `lane-status` lists ids.
**Start new work** — propose first: the id (ticket key or slug), the repo(s), the base branch (default branch unless
they say otherwise or the ticket clearly builds on another branch), in one line, and wait. On their yes:
`lane start <id> <repo>[:<branch>][@<base>] ...`, then EnterWorktree `name: "<id>"`. Then draft the Goal
from what they said, show it to them, and on their yes save it with `lane-memory goal "<text>"`.
**Add a repo to the current lane** — `lane with <id> <repo>[:<branch>]`.
**Attach outside code or docs as a reference** — `lane ref <id> add <path> [note] [--rw]`. It appears under
`lanes/<id>/refs/<name>`. Propose it when they mention code that is not in the lane's repos; never read outside paths
without a ref.
**Bring a new repo under management** — `lane add <git-url|path-to-existing-checkout> [name]`. Then
fill stack/product in `.repolane/registry/repos.yaml`.
**Old conversations** — `lane sessions <repo|id>` lists them with ids. Give them one command and stop:
`claude --resume <session-id>`.
**Two lanes turn out to be one** — preview with `lane plan <a> <b> [--as <new-id>]` (read-only). Show the owner the
plan and let them choose the mode. The real merge runs only from the root: `lane merge <a> <b> … --run`.
**Leaving / switching** — draft the resume note, show it, run `lane park <id> "<note>"` on their ok (or at once if
they said "park it"), then ExitWorktree `keep`.
**Finishing** — `lane done <id>` (refuses if dirty or unpushed; report the reason, do not force).

If they name a repo but no lane, list that repo's lanes and ask, or offer to start one.
Every prompt carries a `[lane] lane=…` line from the hook; trust it over memory of earlier turns.
