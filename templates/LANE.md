# You are inside a lane

This session sits in a lane: `lanes/<id>/` of a Repolane workspace, one piece of work across the repos in it.
The lane's id, its file and the owner's name are given just above this text.

## What you cannot do here, and what to do instead
Claude Code does not let a session in a worktree use Edit or Write on anything outside the lane folder. It refuses
before any hook can help, so do not try. That includes the lane's own file under `.repolane/registry/lanes/` and the
memory folders. Use these commands instead (they run without asking):

- **Set or change the lane's Goal** — when the owner says what this lane is for ("the goal is …", "set the goal to …",
  "this lane is about …"), save it with:
      lane-memory goal "<the goal, in their words>"
  It replaces the `## Goal` section of this lane's file. Long text: `lane-memory goal -` and the text on stdin.
- **Remember something** (a fact, a decision, a preference worth keeping) — write a draft with:
      lane-memory draft <short-slug> "<what to remember>"
  then ask the owner which scope it belongs to (`lane` · `repo <repo>` · `cross` · `pref`) with a recommendation, and
  file it with `lane-memory file <short-slug> <scope>`. Never write memory files yourself.
- **A resume note or a status change** — `lane-park <id> "<note>"` when they say park or switch away.

## Rules inside a lane
1. Stay here. Never `cd` out of the lane; reach a repo with `<repo>/…` paths, `git -C <repo> …`,
   `lane-run <repo> <cmd…>` (builds, tests) and `lane-gh <repo> <args…>` (GitHub). Do not `cd` into a repo.
2. Only the repos in the lane file are in scope. Not the mirrors under `.repolane/repos/`, not other lanes, not
   anything else on the machine. Outside code or docs come in as a reference, once the owner agrees:
   `lane-ref <id> add <path> "why"`, then read it under `lanes/<id>/refs/<name>/`.
3. Never read `.env` or credential files. `lane-env-keys <path>` lists the names in one, never the values.
4. A missing repo is added with `lane-with <id> <repo>`; never create another worktree or lane from here.
5. Report git state only from the STATE block that arrives with each prompt.
6. Discuss before deciding: propose anything with judgment in one line with a recommendation, and wait.
