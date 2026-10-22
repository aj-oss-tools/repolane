# Concepts

Six words carry the whole system.

## Workspace

The folder your work lives in: any folder where `lane init` ran. Repolane itself is an installed package
(`pipx install repolane`); the workspace is yours, and the package never ships it and never overwrites what you wrote
in it. `lane` finds the workspace by looking up from the current folder, so every command works from anywhere inside.

```
~/work/
  CLAUDE.md          yours; imports Repolane's rules with @.repolane/REPOLANE.md
  .claude/           Claude Code's settings, with Repolane's `lane hook …` commands
  lanes/             the work: one folder per lane
  .repolane/         everything else Repolane keeps: the registry, memory, knowledge, the mirrors, config
```

The registry (`.repolane/registry/`) is the source of truth: `repos.yaml` lists the repos, and
`registry/lanes/<id>.md` is one file per lane. The mirrors and the worktrees are machine state that the registry can
rebuild, so the parts worth keeping are small text files, and the workspace can be a git repo of your own
(`lane init --git`). [Installing Repolane, and your workspace](install.md) lists every file, says which are yours to
commit, and covers `lane doctor`, `lane upgrade` and moving from an older git-clone install.

Paths on these pages are written from the workspace root: `.repolane/repos/<name>`, `lanes/<id>/<repo>`.

## Repo

A repo you work on. It lives once, at `.repolane/repos/<name>`, and is a **mirror**: always on its default
branch, never edited, never switched. It exists so every piece of work can share one object store.
Add one with `lane add <git-url>` or `lane add <path-to-a-checkout-you-already-have>`.

**Adopting a checkout you already have** (`lane add <path>`) runs Repolane's `copy-repo.sh` under the
hood. What it actually does, verified from the script:

- It **copies** `.git` (`cp -a`), it never moves it — your original checkout is completely
  untouched, on whatever branch it was already on, and stays usable exactly as before.
- **All branches and stashes come along**, since they live in `.git` and the whole directory is
  copied — not just the current branch.
- Only the **default branch is checked out** into the new mirror at `.repolane/repos/<name>`, freshly reset
  to `origin/<default>` (or the source's own checked-out branch if there is no `origin/HEAD`).
- **Worktrees are dropped, not carried over**: `.git/worktrees` metadata is deleted after the copy,
  since a mirror never has worktrees of its own. Any worktree the original checkout had (including
  one for a branch you were actively using) is not recreated automatically — start a lane for that
  branch with `lane start <id> <repo>:<branch>` to get a worktree for it again.
- A short whitelist of meaningful gitignored files (`.env*`, `settings.local.json`,
  `*.code-workspace`) is copied over too, so local config isn't silently lost.

## Lane

**One piece of work**, which may span several repos. It has an id (a ticket key or a short name), a
branch of that name in each repo it touches, and a folder at `lanes/<id>/` holding a worktree of each.

```
lanes/ABC-123/
  web/     a worktree of .repolane/repos/web on branch ABC-123
  api/     a worktree of .repolane/repos/api on branch ABC-123
  refs/    anything you attached for reference
```

You run Claude from `lanes/<id>/`, not from inside a repo. No repo is the main one. Reach any of them
with `git -C <repo>`, `lane run <repo> <cmd>`, or by editing `<repo>/path/to/file` directly.

## Worktree

Git's own feature: a second working directory sharing one repository. It is why a lane costs
a checkout of files rather than a full clone, and why switching work is instant.

## Reference

Code or documents that are not one of your repos but matter to the work. `lane ref <id> add <path>`
makes it readable at `lanes/<id>/refs/<name>` and nowhere else.

A **link** is the lighter case: something that only needs a URL — a design doc, an RFC, a second
issue that is not *the* ticket. `ticket:` in the lane file covers the one tracker key; anything else
goes in an optional `links:` block you write by hand, next to `repos:`:

```yaml
links:
  - label: Promo pricing RFC
    url: https://docs.example.com/rfc/promo-pricing
```

`lane brief` prints them, so they reach the session's opening context, and the board shows them
under Goal & notes. Nothing else reads them — it is a breadcrumb list, not a tracker.

## Memory

What Claude has learned, kept in four scopes chosen by **how long it stays true**:

| scope | means | lives in |
|---|---|---|
| `pref` | how to work with you, always | `.repolane/knowledge/preferences.md` |
| `cross` | true in every repo | `.repolane/memory/` |
| `repo` | true for one repo after this work ships | `.repolane/memory/<repo>/` |
| `lane` | only while this lane is live | the lane file, `.repolane/registry/lanes/<id>.md` |

Memory is never written directly. `lane note` drafts it and asks you which scope it belongs in. A session inside a
lane uses `lane-memory draft` and `lane-memory goal`, because Claude Code refuses Edit and Write outside the lane
folder; see [how a lane session saves its Goal](install.md#how-a-lane-session-saves-its-goal-and-its-notes).
