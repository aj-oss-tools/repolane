# Changelog

Notable changes to Repolane. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the version numbers follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

`lane --version` reports the version in [`VERSION`](VERSION), which is the only place the number is
written down. Inside a git checkout it also says how far past the release tag you are.

## [Unreleased]

Nothing yet.

## [0.11.0] — 2026-10-25

### Changed

- **The board has a new look.** A left rail (Active lanes, Parked, Memory, and the lanes in flight). Home lists the
  active lanes as dense rows: ticket, title, status and one next-action button; the Goal and resume note on one line;
  one line per repo with its branch, status chips and last activity. Parked lanes are single lines in a section that
  folds away. Home's right column has what to do next, memory drafts waiting for a scope (File it, Discard) and recent
  Claude conversations (click to copy `claude --resume <id>`). A lane opens on its repos, the changes split into
  staged and unstaged, the diff beside them and the commit box underneath; About this lane is one scrolling side
  panel (Goal, resume note, Findings, repos, references with Reveal and Detach, sessions, the lane file). Dialogs,
  the palette, toasts and dark mode follow the same design.
- The board looks like repolane.dev: the same warm paper and amber palette (and its dark counterpart), Inter, JetBrains
  Mono and Instrument Serif. The fonts ship in the package and are served by the board, so it makes no outbound
  requests at all. It is also a little denser than before.
- **Every board screen has a real address.** `/lanes/<lane>/<repo>` (with `?file=` for an open diff),
  `/lanes/<lane>/<repo>/history`, `/lanes/<lane>/<repo>/commits/<sha>`, `/memory/<scope>`, and `/w/<name>/…` for
  another workspace. Back and Forward step through screens, a reload or a pasted link lands on the same one, and an
  old `/#lane=…` link still works. The board's API moved to the same shape (`/api/lanes/<lane>/repos/<repo>/stage`
  and so on); its old query-string endpoints are gone. Nothing outside the board called them.

### Added

- `GET /api/sessions` on the board server: the recent conversations it already caches per repo, for Home.

## [0.10.0] — 2026-10-24

### Added

- **Workspaces.** A folder with a `.repolane/` folder in it is a workspace: your own `CLAUDE.md`, `.claude/` and
  `lanes/` stay at the top, and everything else Repolane keeps (`registry/`, `memory/`, `knowledge/`, `repos/`,
  `cache/`, `config.yml`, `env.sh`) lives under `.repolane/`. An installed `lane` finds the workspace by looking up
  from the current folder; `LANE_WORKSPACE` still names one directly. A git clone of Repolane keeps its layout and
  keeps acting on itself, whatever folder you run it from.
- A workspace's hooks are `lane hook <event>` commands (`lane hook pre-tool-use`, `lane hook session-start`, …), in
  `.claude/settings.json` and in every lane's settings, so no hook names a file inside the installed product.
- `.repolane/REPOLANE.md` holds the rules every session gets (your `CLAUDE.md` imports it with
  `@.repolane/REPOLANE.md`) and `.repolane/LANE.md` the rules for a session inside a lane. Neither carries your
  name: the hooks name the owner when a session starts. Both are rewritten on the first `lane` command or hook after
  the installed version changes; your data is never overwritten.
- A session that enters a lane with `EnterWorktree`, or starts inside one, is handed `LANE.md` right away. It says
  plainly that Edit and Write outside the lane folder are refused, and to save the Goal with
  `lane-memory goal "<text>"` and memories with `lane-memory draft <slug> "<text>"`.
- The Python package installs the long command names (`lane-memory`, `lane-brief`, `lane-run`, …) next to `lane`.
- `lane init` from the installed package makes a workspace in the current folder, or in the folder you name
  (`lane init ~/work`). It asks for your name (`--owner`, or `--yes` to ask nothing), and `--git` makes the workspace
  a git repo with a `.gitignore` for what is machine-local (`lanes/`, `.repolane/repos/`, `.repolane/cache/`). It
  adds Repolane's hooks to an existing `.claude/settings.json` without touching your own keys or hooks, and records
  the workspace in `~/.local/share/lane/planes.json` so `lane upgrade` can refresh every workspace. Running it again
  over a workspace in use changes nothing and says so. `lane init` in a git clone of Repolane works as before.
- `lane doctor` in a workspace checks that `lane` is on PATH the way the hooks call it (if it is not, every hook
  fails and Claude Code runs tools unguarded, and the doctor says so loudly), that `CLAUDE.md` imports
  `.repolane/REPOLANE.md`, that `.claude/settings.json` runs the expected `lane hook` commands, that the rule files
  are the installed version's, that the workspace is registered, and that every lane's settings run the current
  hooks. Each problem comes with its fix, and `lane doctor --fix` repairs what it safely can (`--yes` answers its
  question). It exits non-zero while anything is wrong. It reports an outdated workspace instead of refreshing it.
- `lane init` in a workspace links Claude Code's memory for the workspace root
  (`~/.claude/projects/<folder>/memory`) to `.repolane/memory`, the way a clone's `lane init` links it to
  `memory/`; `lane add` links each mirror's to `.repolane/memory/<repo>`. Nothing under `~/.claude` is changed
  without asking: init shows each link and asks "Make these links under ~/.claude? [Y/n]" (`--yes` accepts; with no
  terminal and no `--yes` nothing is changed and it prints the commands). Notes already in Claude Code's own memory
  folder are copied in first. `--claude-home <dir>` (or `CLAUDE_HOME`) names a different Claude Code folder.
  `lane doctor` checks the links of the root and every mirror, and `lane doctor --fix` repairs them after asking.
  When you answer no, that is recorded in `.repolane/declined.json`: `lane init` and `lane add` do not ask again, and
  `lane doctor` shows a note with how to make the link later instead of a failure (`lane doctor --fix` still offers
  it, and a yes clears the record). A missing link nobody declined is still a failure. In a workspace `lane add`
  follows the same rule for the new mirror's link: it asks, `--yes` accepts, and with no terminal it changes nothing
  under `~/.claude` and prints the command.
- A workspace's status line is `lane statusline`, added to `.claude/settings.json` by `lane init` when no status line
  is set (your own is never replaced). `lane doctor` reports one that still runs a clone's
  `scripts/statusline.sh` by path, and `--fix` replaces it; a workspace with no status line gets a note, not a failure.
- **`lane migrate` turns a git-clone install (a 0.9.x control plane) into a workspace, in place.** Run it from the
  installed package: `lane migrate [folder]` (default: the current one). It first shows everything it would do and
  changes nothing until you confirm ("Migrate now? [y/N]", or `--yes`; with no terminal and no `--yes`, or with
  `--dry-run`, it only shows the plan). It refuses while Claude Code is running inside the folder. Before the first
  change it writes a backup of everything it changes or removes to `~/.local/share/lane/backups/<folder>-<time>.tar.gz`,
  and `lane migrate --undo <backup>` puts the clone install back (keeping what was written in the workspace since).
  - Your data moves under `.repolane/` (`registry/`, `memory/`, `knowledge/`, `repos/`, `.cache/` as `cache/`,
    `registry/config.yml`, `scripts/env.sh`, `scripts/local/`); the worktrees stay in `lanes/` and are repaired with
    `git worktree repair`, and their `.env` links follow the mirrors.
  - Repolane's own files are removed: only the paths a release shipped (the 0.9.x releases are listed in
    `scripts/migrate-manifest.json`, made from their tags by `scripts/release-migrate-manifest`; the installed
    release's own list is written into the package when it is built), never anything else in the folder. The
    clone's `.git` is Repolane's repo, so it is removed too (it is in the backup); `--git` starts a fresh, empty one.
  - The generated `CLAUDE.md` becomes a short one that imports `.repolane/REPOLANE.md`, keeping every line you added.
    If lines of Repolane's own text were edited, the old file is also kept as `CLAUDE.md.pre-0.10`.
  - `.claude/settings.json` runs `lane hook …` commands and `lane statusline`, keeping your own keys and hooks, and
    every lane's `settings.local.json` is written again.
  - Outside the folder, each asked first: the memory links under `~/.claude/projects` (and a mirror's project folder,
    whose path changed) point into `.repolane/memory`; the router `lane install` wrote in `~/.local/bin` is removed
    when no other clone install uses it. `planes.json` records the workspace instead of the clone.
  - A migration that stops half way continues when you run it again; running it on a workspace says there is nothing
    to do and changes nothing.
- A git-clone install that has been set up shows one line on SessionStart and in `lane status`: Repolane installs as a
  package now, and `lane migrate` converts the folder. `migrate_reminder: false` in `registry/config.yml` turns it off.
- **`lane upgrade` from the installed package** upgrades it the way it was installed (`pipx upgrade repolane` for a
  pipx install, `uv tool upgrade repolane` for a uv tool install; for any other install it prints the `pip` command to
  run), then refreshes every workspace registered in `planes.json` with the new version: the rule files and data
  migrations, Repolane's hooks in `.claude/settings.json` (your own keys and hooks kept), and every lane's
  `settings.local.json` and `CLAUDE.md`. It reports each workspace; nothing you wrote is changed. A registered folder
  that is gone is skipped and reported, and you are asked whether to drop it from the registry (`--drop-missing` or
  `--yes` drops it). It exits non-zero when a workspace could not be refreshed. Run inside a workspace that is not
  registered, it registers it. `lane upgrade --check` shows the installed version against the newest on PyPI and
  which workspaces are behind, and changes nothing (it says so when PyPI cannot be reached); `--refresh-only` skips
  the package step.

- A workspace gets Repolane's slash commands (`/status`, `/lane-brief`, `/lane-start`, …) and agents (`lane-manager`,
  `context-loader`, `branch-gardener`): `lane init`, the refresh after an upgrade and `lane upgrade` copy them into the
  workspace's `.claude/commands/` and `.claude/agents/`, by name, in versions that run the `lane-*` commands on PATH and
  name the `.repolane/` paths. `.repolane/claude-files.json` records what Repolane wrote, so only a file that is still
  exactly that is ever replaced: your own file of the same name, or one of Repolane's you edited, is kept, and one you
  delete stays deleted. `lane doctor` checks them, and `lane doctor --fix` brings them up to date. `lane migrate`
  replaces a clone's (which ran `bin/` by path) with them. The package no longer carries a clone's own `.claude/agents`
  and `.claude/commands`.

- Each release is published to PyPI as `repolane` (`pipx install repolane`, `uv tool install repolane`) by
  `.github/workflows/publish.yml`, with trusted publishing and no stored token, from the wheel the package test has
  just checked.

### Changed

- Repolane's own files (`lane`, `scripts/`, templates, `VERSION`) and your data (`registry/`, `lanes/`, `repos/`,
  `memory/`, `knowledge/`) are located through two separate roots, which are the same folder in a clone, so nothing
  behaves differently. The repo also builds a Python package (`repolane`) whose `lane` runs the bundled product.
- Your `CLAUDE.md` is only edited when you say so. A workspace without one gets a small `CLAUDE.md` that imports
  `.repolane/REPOLANE.md`; for an existing one, `lane init` shows the line and asks "Add it? [Y/n]" (`--yes` adds it;
  with no terminal and no `--yes` it is left alone, and the output says how to add it). Until the line is there,
  Repolane's rules do not load, and `lane doctor --fix` can add it later.
- `lane upgrade` in a git clone still fast-forwards the clone when the new version is 0.10 or later, so it keeps
  working, and `lane doctor` in such a clone then spells out the two steps that move it over: `pipx install repolane`
  (or `uv tool install repolane`), then `lane migrate <folder>`.
- `lane status` in a workspace heads its first section "workspace" instead of describing a clone.
- `lane doctor` no longer writes a `__pycache__` folder into Repolane's own files, and the guard refuses a tool call
  (instead of letting it through) if its path resolver is missing.

### Fixed

- In a workspace, a resumed conversation started in a mirror is found again: the hooks look for its project folder
  under the mirror's real path (`.repolane/repos/<repo>`), not under `repos/<repo>`.
- `lane park` no longer deletes a lane's `## Findings`: it replaces the Resume note's own text, up to the next heading,
  and keeps every other section. `lane-memory file … lane`, `lane merge`, `lane brief` and `lane done` also read and
  write one section up to the next heading, so a section you add to a lane file, or a Findings at the end of it, is
  kept and shown where it belongs.
- In a workspace, what a session is told speaks of the workspace: SessionStart (at the root and in a lane), a resumed
  conversation, UserPromptSubmit, PreCompact, the Worktree hooks, the guard's refusals, the MEMORY SCOPES table, the
  menu, `lane-memory file` and the Findings placeholder `lane start` writes into a lane file name the real paths (`.repolane/registry/…`, `.repolane/memory/…`, the mirrors under
  `.repolane/repos/`), the commands by the name on PATH (`lane-with`, `lane sessions`), "the workspace", and
  `.repolane/REPOLANE.md` for the details, and no longer a clone's `scripts/` folder, a relative path that "exits 127"
  or the product's own files. A shared project rule's refusal names the file it came from
  (`registry/rules.shared.yaml`), not `registry/rules.yaml`. A git clone's text is unchanged.
- In a workspace the editor workspace files (`lane.code-workspace`, `lanes/<id>/<id>.code-workspace`) hide the mirrors
  and the cache where they are, `.repolane/repos` and `.repolane/cache`, instead of a clone's `repos` and `.cache`.
- The README, the package's description and `docs/extending.md` describe Repolane as a workspace, not a control plane.
- `lane help` from the installed package no longer lists a clone's `install` and `use`, and `lane install` / `lane use`
  refuse with what to do instead (`lane init [folder]`, `lane migrate <clone-folder>`); they wrote a clone's router
  into `~/.local/bin` and switched between clones. A git clone keeps both.
- A session started at the root that enters a lane with `EnterWorktree` can save the Goal and draft a memory without
  being asked for approval: the root pre-approves `lane-memory goal` and `lane-memory draft` (a lane's own settings
  only apply to a session started inside it). A workspace gets them in `.claude/settings.json` from `lane init`,
  `lane migrate`, the refresh after an upgrade and `lane upgrade`, and `lane doctor` reports them missing
  (`--fix` adds them); a git clone gets them in the root's `.claude/settings.local.json`. `lane-memory file` still
  asks, and `lane-memory goal` still refuses another lane's Goal from inside a lane.
- A clone's `./lane install` no longer takes over a `lane` the installed package put on PATH: when `~/.local/bin/lane`
  is the package's launcher (pipx, uv tool or pip) it refuses, changes nothing and points at `lane migrate`. It used to
  write its router over it and register the pipx venv's `bin/` as a plane named "bin"; an old link that does not lead
  to a git clone of Repolane is no longer registered at all. `lane migrate` keeps the router only for registered
  entries that are real clone installs, not for a venv or a folder that is gone.
- A session inside a lane is refused `lane migrate`, `lane init` and `lane upgrade`, with a message that the owner runs
  them from a terminal at the root.

## [0.9.2] — 2026-10-19

### Fixed

- **A session that entered a lane through `EnterWorktree` can now save its Goal, draft a memory, and
  read `memory/` and `knowledge/`.** 0.9.1 let such a session read and edit its own lane file by
  permission rule, but Claude Code has a second check that no setting turns off: once a session is
  inside a worktree, its Edit and Write tools refuse any path outside that folder ("This session is
  isolated in the worktree … Edit the worktree copy"), and the lane file and the draft inbox live in
  the control plane root. Those writes now go through `lane-memory`, which runs from inside the lane
  without asking: `lane-memory goal "<text>"` sets the lane's own Goal (and refuses another lane's),
  and `lane-memory draft <slug> "<draft>"` (or `-` with the text on stdin) fills the inbox. Reads of
  `memory/`, `knowledge/` and the inbox are allowed in every lane's settings (Claude Code applies a Read
  rule to its search tools too, which the headless test here could not exercise). The control plane's `CLAUDE.md` and the hook's reminders say to use these
  commands instead of Edit or Write. `tests/t_lanefile.sh` covers the commands, the rules and the guard,
  and a real Claude Code session that entered a worktree saved a Goal and a draft and read both folders.
  The same trace found that `CLAUDE.md` tells a session to call the `lane-*` scripts by absolute path while
  the pre-approved rules named only the bare commands, so following the instructions meant an approval prompt for
  every call; the rules now cover both forms. `lane-status`, `lane-menu` and `lane-sessions` also exist under
  `scripts/` now, so the absolute path `CLAUDE.md` gives no longer ends in "No such file" (exit 127).
  A lane made earlier picks the rules up the next time `lane start`, `with`, `resume`, `done`, `merge` or `ref` refreshes it.

## [0.9.1] — 2026-10-18

### Fixed

- **A session inside a lane can now save its Goal and Findings.** The dispatcher text and the control
  plane's `CLAUDE.md` tell a lane session to write its lane file (`registry/lanes/<id>.md`), and the
  guard allows exactly that edit, but the file sits in the control plane root, outside the lane's
  folder, and Claude Code refuses a path outside the session's folder unless a rule allows it: the
  session could not even read its own lane file ("you haven't granted it yet") and had to suggest
  leaving the lane to write the Goal from the root. `lane start`, `lane with` and every refresh now write an
  allow rule for that one file (`Read` and `Edit`, as an absolute `//` path, which is the form Claude
  Code accepts) into the lane's settings. Nothing else under `registry/` is reachable from a lane, and
  another lane's file stays refused by both layers; `tests/t_lanefile.sh` covers the rules, the refresh
  and the guard, and the edit was checked with real Claude Code. A lane made earlier picks the rule up the
  next time `lane start`, `resume`, `done`, `merge` or `ref` refreshes it. The `CLAUDE.md` template now
  names this exception to "change the control plane from the root" (rule 12); an existing control
  plane keeps the `CLAUDE.md` it already has, so add that sentence by hand if you want it there.

## [0.9.0] — 2026-10-18

### Added

- **Test suites that run on their own throwaway control plane, and a CI workflow that runs them.**
  `tests/run-all.sh` runs the eight `tests/t_*.sh` suites (dispatcher, memory, upgrade, lifecycle —
  park / done / brief —, secret names, portability and exit codes, and the second audit's fixes),
  each in its own sandbox with a temporary `HOME` and local bare repos as remotes, so nothing needs
  installing, logging in or reaching the network. `scripts/board/test_board.py` is a stdlib
  `unittest` suite that starts the real board server on a scratch plane (`smoke.sh` now runs it).
  `scripts/hooks/test-guard.sh` grew from 184 to well over a thousand cases, and no longer asserts a
  hard-coded case count (nobody notices when that number is edited to match a suite that lost half
  its cases): every section must run at least one case, every case must also see the guard exit 0,
  and the totals must add up. The guard now runs against a fake `HOME` inside the fixture, so the
  result no longer depends on whether the real `$HOME` or `$TMPDIR` is under `/Users`, `/home`,
  `/tmp` or macOS's `/var/folders` (before, the same suite scored 184, 179 or 157 depending on
  where it ran). `.github/workflows/tests.yml` runs all three on every push and pull request on
  `ubuntu-latest` and on `macos-latest` pinned to `/bin/bash` (3.2). The three suites pass on macOS
  (bash 3.2) and in an Ubuntu 24.04 container run as an ordinary user from a clean clone; the workflow
  file itself has not yet run on GitHub.
- **`lane use --remove <name>`** forgets a registered plane. Only the registry entry goes; the
  checkout is never touched. If it was the active plane there is none afterwards (the command says
  so) and `lane use <name>` picks one: no replacement is guessed, because guessing the wrong plane is
  how the wrong project's data got used once. Unknown names exit 1.
- **`lane done --discard-ignored` and `lane done --pushed-to <remote>`**, described under Changed.
- **`scripts/gitstate.sh`**, one shared definition of "unpushed", "dirty", "secret-named" and a valid
  lane id, sourced by the lane scripts that used to each count their own way. `tests/` fails if its
  secret-name pattern ever differs from `guard.py`'s or the board's.
- **The board accepts `WS_BOARD_REFRESH` (seconds, default 3)** for how often it re-reads git state.

### Changed

- **The guard (`scripts/hooks/guard.py`) was rewritten around a small shell reader instead of
  regular expressions over the raw command line.** It now understands quotes (including `$'…'` and
  `$"…"`), `;` `&` `|` and newlines, `$( )`, backticks, `( )`, redirect targets, and follows
  `bash -c`, `eval`, `env -S` and `su -c`. A heredoc, here-string or what `echo`/`printf` pipe in is
  data for `cat` or `git commit -F -` and code for a shell or interpreter. The old regexes were
  quadratic: a ~24 KB command took about 12 seconds and ~96 KB more than 30, past the hook's
  timeout; a 96 KB command now costs the same as a short one. What is now **denied** that passed
  before:
  - Secret reads through a substitution or a reader flag: `ls $(cat .env)`, ``basename "`cat .env`" ``,
    `file -f .env`, `wc --files0-from=.env`. The allow-list of metadata-only commands (`ls`, `stat`,
    `wc`, `find`, `lane-env-keys`, …) is matched as the exact command word and only without the options
    that turn them into readers. Names are judged after the shell would have read them: earlier
    variables in the same command (`f=.en; cat ${f}v`), brace expansion, `$'\x2eenv'`, `$(echo .env)`.
    A `.env.example` that is a symlink to `.env` is treated as the secret. Lane references
    (`lanes/<id>/refs/…`) are now secret-checked; they returned "allowed" before the check ran.
  - Whole-folder reads over a folder that holds a secret: `grep -r`, `rg --hidden`/`-uu`, `tar c`,
    `zip -r`, `cp -r`, `rsync`, `scp -r`, `diff -r`, `find … -exec <reader>`, and the **Grep** tool
    (the PreToolUse matcher now includes `Glob|Grep`; `Glob` lists names only and is left alone).
    Lists of names piped into a reader (`ls .env | xargs cat`) are judged as if typed after `cat`.
    Interpreter one-liners (`python3 -c`, `node -e`, …) are searched for secret names, common ways
    of assembling one (`'.'+'env'`, `chr(46)`, base64) and out-of-plane paths.
  - Pushes to a protected branch in every spelling the old whitespace-sensitive check missed:
    `git push origin main;`, `main&&…`, `+main`, `'main'`, `HEAD:refs/heads/main`, `:main`,
    `--delete main`, `--all`, `--mirror`, and a bare `git push` while a protected branch is checked
    out, including inside `bash -c`, `eval`, heredocs, `xargs` and `env -S`. A `git <word>` git does
    not ship may be a user alias for `push`, so one naming a protected branch is refused (`git lg`
    and `git co feature` are not).
  - Git config that would run code or change where hooks come from: `-c alias.*`,
    `core.hooksPath`, `include.path`, `GIT_CONFIG_*`, `GIT_EXEC_PATH`, `GIT_TEMPLATE_DIR`,
    `git config` setting any of those or any program-valued setting (`core.editor`, `core.pager`,
    `core.sshCommand`, `credential.helper`, …), and writes to `.git/config` or `.git/hooks`.
  - `cd` escapes: `pushd`, `builtin cd`, `\cd`, `{ cd /; }`, `eval cd /`, a bare `cd`. The working
    directory is now simulated statement by statement, so `cd ..; cd ..; cd ..` leaves a lane on
    the second step and `cd app && cat ../../../../x` is judged from `app`.
  - `$HOME` itself (`~`, `$HOME`, `${HOME}`), which was never expanded: `rm -rf ~`,
    `grep -r token ~`. Symlinks inside a lane are resolved before the path rules apply (except a
    lane's own attached reference).
  - Writes to the control plane from inside a lane that the old list missed: `lane`, `VERSION`,
    `CLAUDE.md.template`, `.github/`, `.cache/` (except the memory inbox), `registry/` (except the
    lane's own spec), every `.claude/settings*`, writes through `bin/*` symlinks, and
    `git -C <plane> checkout|reset|clean|apply`. Control-plane commands (`lane upgrade`, `init`,
    `install`, `add`, `use`, `rules pull`, `secrets add|ignore`) are for the dispatcher session;
    `lane-done|park|resume|with` act only on the lane you are in; `lane-ref <other lane> add|rm` is
    refused; `lane-ref add` refuses `/`, the home directory, system and credential directories and
    secret files.
  - More `gh` writes: `api` with a body or a non-GET method (including lowercase/quoted `-X`,
    `--method=PUT`, implicit POST), `pr merge|close`, `secret|variable set|delete`, `alias set`,
    `extension install|exec`, `ssh-key|gpg-key add`, `release|issue|label|run|cache delete`,
    `workflow disable`, `repo edit --visibility|--default-branch|--name`, `auth token`.
  - More write verbs treated as writing every path they name: `perl -i`, `ruby -i`, `awk -i inplace`,
    `patch`, `ed`, `ex`, `vi`/`vim`, `sponge`, `tar`, `unzip`, `zip`, `curl -o`, `wget -O`.

  What is now **allowed** that was falsely denied: `gh repo edit --delete-branch-on-merge`;
  text that merely mentions a secret's name (`echo`/`printf` output, a commit message with `-m`/`-am`,
  `gh --body`/`--title`, a grep pattern, an `--exclude=`/`-g '!…'`/`find -name` pattern, a heredoc
  body); `git rm --cached`, `git check-ignore` and `git ls-files`; `cp .env.example .env` into the
  lane (only a source that is a template by name and by where it leads); `GIT_EDITOR=true git rebase
  --continue`; `git lg` / `git co feature`; and a `.venv/bin/python` that points into a version
  manager (the program being run is not followed through its links).

  **Things that may surprise you.** A recursive `grep -r` (or `rg`, `tar`, `cp -r`, the Grep tool)
  over a lane whose repo has a `.env` is now denied unless it excludes it: add
  `--exclude='.env*'` (and `--exclude='*.pem' --exclude='id_*'`), `rg -g '!.env*'`, an `--include`, or
  search a subfolder. The denial text says so, per tool. `rg` and `ag` skip hidden files by default,
  so they trip only on `--hidden`/`-uu` or a non-hidden `server.pem`. A folder with more than
  100,000 files is refused as too big to vouch for; `.git`, `node_modules` and virtualenvs are not
  searched for secrets. A `cd` sequence is judged step by step, and a `cd` to a computed target, in a
  loop or in a function is refused inside a lane. `git -c alias.x=push x origin main` and anything
  setting `core.hooksPath` is denied outright. The guard now **fails closed** for `PreToolUse`: a
  payload it cannot make sense of (non-string `command`, non-path `cwd`) or an unexpected exception
  while judging a tool call is answered with a deny that says why, because a hook that crashes exits
  non-zero without a decision and Claude Code then runs the tool. Every other event (`UserPromptSubmit`,
  `PreCompact`, `SessionEnd`, `PostToolUse`, `Worktree*`) still fails open. Denials also read
  better: writing a secret-named file now gets write wording instead of "never reads"; writing a lane's
  `.env` symlink says it is a symlink into the read-only mirror and what to do (`rm` the link, copy the
  template, ask the owner for values); `rm` of just that link is the suggested route.
- **`ALLOW_DEFAULT_BRANCH_PUSH=1` is now documented as advisory, and works per statement.** It
  records that the human agreed to a push to a protected branch; it never overrides a force-push, and
  because Claude can type it as easily as a person can, it does not prove consent. A hard version
  needs something the model cannot produce, for example exporting the variable in the environment
  Claude Code is launched from. That is not implemented.
- **What the guard still does not see** is listed in `scripts/hooks/README.md`: the contents of a script
  run by name (`bash build.sh`, `source x`), a variable set elsewhere (`cat $f`), the output of
  commands other than `echo`/`printf`/`cat`, interpreter code that builds a name by arbitrary
  computation, what `git diff --cached` / `git log -p` print from history, and whether an `rg` run
  is stopped by a `.gitignore`. Input it cannot read at all (`curl … | sh`, `bash -c "$(…)"`, nesting
  past 4 levels, more than 8 programs in one command) is refused, not ignored.
- **`lane done` counts "unpushed" against `origin/*`, not against the branch's upstream.** `lane start`
  cuts a lane branch from `origin/<base>`, so its upstream is the base branch, and a plain
  `git push origin <id>` (no `-u`) never changed that: `lane done` kept saying "unpushed commit(s)"
  after a push, and counted base-branch commits as pushed work before one. The same definition now
  drives `lane status`, `lane brief`, `lane resume`, `lane doctor`, the board, the status line and
  SessionStart: commits on `HEAD` that no `origin/*` branch has. `lane start` also stops treating
  `origin/<id>` as a lane's base after a `git push -u`.
- **`lane done` rewrites, in detail.** `--pushed-to <remote>` checks against that remote's branches
  instead of `origin` (for a fork); the refusal text suggests it. A repo with no `origin` is
  local-only: it used to make `lane done` refuse (it required `@{u}`); now it is noted ("nothing to
  push, the branch stays in repos/<repo>") and the lane finishes. A repo with no commits is noted
  too; a detached `HEAD` carrying commits no remote has is refused with how to fix it. Refusals
  name the exact `git push` to run. `lane done` also refuses while a worktree holds **ignored or
  untracked secret-named files** that deleting the worktree would destroy, naming them, unless you
  pass **`--discard-ignored`** (symlinks that `lane start` made into the mirror are skipped, since
  deleting them loses nothing, and so is anything inside `node_modules`, `.venv`, `vendor`, `dist`,
  `build`, `.git`, etc.). The previous behaviour deleted ignored files silently. For a parked lane,
  untracked secrets that `lane park` deliberately left out are no longer reported as "dirty — commit it,
  or lane park first" (a dead end: park will never commit them); they are named with what to do.
  The board, `lane status` and SessionStart likewise stop counting them as dirty.
- **`lane park` never commits a file whose name says secret.** It used `git add -A`, which committed
  untracked `.env`-style files. It now stages by explicit literal path, leaves secret-named files on
  disk, and says which: `left out of the commit (secret file names, still on disk): …`. The names
  are `.env` and `.env.*`, `id_rsa`/`id_ed25519`/`id_ecdsa`/`id_dsa`, `.netrc`, `.npmrc`, `.pgpass`,
  `.git-credentials`, `.htpasswd`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, `*.p8`, `*.jks`, `*.keystore`,
  `*.kdbx`, `*credentials*.json`, `service-account*.json` and `secrets.{json,yaml,yml,toml}`; templates
  ending `.example`, `.sample`, `.template` or `.dist` are not secrets. A secret someone already
  staged stops the park with nothing committed (`git reset -- <file>` and run it again), and renames
  and copies are checked on both sides.
- **Existing lanes keep the old hook matcher until `lane resume`.** The new `Glob|Grep` matcher and the
  larger per-lane deny list are written into a lane's `.claude/settings.local.json` by `write_guard`;
  lanes created earlier still have the old ones, so the Grep tool skips the guard there. `lane doctor`
  now flags such a lane ("the PreToolUse matcher predates Glob/Grep") and so does its check of the
  control plane's own `.claude/settings.json`; `lane resume <id>` rewrites it. The per-lane Claude Code
  deny rules now cover the same secret names as the guard, not only `.env*`, `*.pem` and `*.key`.
- **The pre-approved (no-prompt) `lane-*` list got shorter.** `lane-memory` and `lane-workspace` were
  approved wholesale although `lane-memory file|rm|move` write and delete markdown and
  `lane-workspace` rewrites the `.code-workspace` files. Now only `lane-memory list|show|audit`
  stay pre-approved (in `.claude/settings.json` and in every lane's settings); the write verbs and
  `lane-workspace` prompt. A refresh removes the old entries from existing lanes. As before, the list only
  applies once the workspace has accepted Claude Code's trust dialog; an untrusted headless run ignores
  it. (The dialog path itself was not exercised in the trials.)
- **Dispatcher text.** SessionStart and `CLAUDE.md.template` told Claude `EnterWorktree
  path=<plane>/lanes/<id>/<repo>`, which the guard denies (one way in: `name`); Claude recovered by
  retrying, now it is told `EnterWorktree name="<lane-id>"` (no path, no repo; you land at the lane
  root and reach each repo at `<repo>/…`). The same text now says to call lane scripts by **absolute
  path** (it prints the scripts directory) because a relative `scripts/lane-brief` does not exist from
  the lane root and exits 127.
- **`lane sync` and `lane import` exit codes tell the truth.** `lane sync` exits 1 when `gh` is missing
  or not logged in, when there are no repos, when any repo failed, and when nothing could be checked at
  all (every repo local-only or not on GitHub); 0 only when at least one repo was read from GitHub and
  none failed. `lane import --list` exits 1 when there are no conversations to show. Scripts that
  chained on a 0 from these will now stop.
- **`lane upgrade` after `lane init`.** `lane init` edits `.claude/settings.json` (and `.gitignore` and
  `scripts/local/` on a `private: true` fork), which made `lane upgrade` refuse. Those are now allowed
  to be dirty, and untracked files never block. If upstream also changes `.claude/settings.json`, it is
  put back to `HEAD`, fast-forwarded, and your local top-level keys re-applied (a key changed on both
  sides keeps upstream's value and says so). Any other dirty file that upstream also touches is
  refused up front with a `git stash` / `lane upgrade` / `git stash pop` recipe, instead of a failed merge.
- **Board hardening** (`lane board`, `scripts/board/README.md`):
  - Every request, `GET /` and static files included, must carry a `Host` (and `Origin`, when sent)
    of `127.0.0.1` or `localhost` on the server's own port, else 403. Before, `GET /` served the
    token to any Host, so DNS rebinding could read it and drive the whole API. One token still
    covers every registered plane. The token has never been printed at start; the docs that said it
    was are corrected.
  - Every git call runs with `--literal-pathspecs`; `/api/stage` and the diff endpoint accept only
    exact changed files (or a directory holding changed files). `.`, globs, `..` and option-like
    names are refused 400. `.` used to stage `.env`, and a file named `s*.json` used to leak
    `secrets.json`'s diff through `/api/show`.
  - Amend and commit refuse while a secret is staged; renames and copies are checked on **both**
    sides (`git mv .env notes.txt` used to look harmless), including in a commit's file list.
  - Secret names match case-insensitively (`.ENV`) and cover the guard's full list.
  - Request bodies over 1 MiB get 413, a non-numeric `Content-Length` 400, a body that is not a JSON
    object 400; lane ids and memory names outside `[A-Za-z0-9._-]+` are refused with 400; a stalled
    client times out after 20 seconds. The refresh loop sets `GIT_OPTIONAL_LOCKS=0` so it no longer
    makes your own `git add` fail with `index.lock exists`.
  - The board's "ahead" uses the same origin-based count as `lane status`.
- **`lane status` says it fetches.** It has always run `git fetch -q origin` in every repo under
  `repos/`; its help line and header comment now say so.
- **Smaller:** `lane <cmd> --help` prints only the usage comment directly under the shebang (some
  commands used to print developer notes); `lane-env-keys` and `lane-env-check` as installed stubs now
  map to the right dispatcher commands (`keys`, `env`) instead of failing; the "184 more cases" line in
  `lane doctor` no longer states a count.

### Fixed

- **Path traversal in `lane-memory` (and the board's `/api/memory`).** `drop`, `file`, `move` and `rm`
  built paths from an unvalidated slug, so `lane-memory drop ../../anything` deleted, and `file`/`move`
  could move, any `.md` file you own, with no prompt because the command was pre-approved. Slugs, repo
  names, lane ids and memory names must now match `[A-Za-z0-9._-]+` (not `.` or `..`, checked
  byte-wise so a locale cannot let `é` through), and `lane-memory` refuses to write through a
  symlinked memory folder. `lane brief ../x` used to read `registry/x.md`; invalid lane ids now just
  report "no lane".
- **`lane brief` on a finished lane** printed `sed` errors and dropped repos, findings and references
  because it read the live lane file; it reads the archive throughout and says "worktree removed when
  the lane finished".
- **Bare `lane` before `lane init`** printed raw `sed:` / `fatal:` and exited 128; it now says "this
  control plane is not set up yet" and exits 2 like the others.
- **`lane rules pull` overwrote a same-named file in `scripts/local/`**, which is yours. It now keeps your file
  and says so, unless an earlier pull put it there (tracked in `.cache/scripts-pulled`), in which
  case it is still updated.
- **macOS and Linux portability:** `lane add`'s candidate prompt used `mapfile` (absent on macOS bash
  3.2); `lane ref add` used `md5` (absent on Linux; now a short SHA-1 via Python); `lane-env-keys`' `sed`
  used `\+`, which BSD sed lacks. The Claude project-folder name is now computed as every
  character other than letters, digits and `-` turned into `-`, as Claude Code does, so a path
  with a `.` or a space (`/.boardshot`) finds its sessions; it used to map only `/` and `_`.
- **SessionEnd no longer piles up duplicate log lines** in the lane file: a line identical to the last
  one except for its timestamp is skipped, so read-only and denied runs stop filling the log.
- `lane status` with no repos yet no longer iterates over a literal `repos/*/`.
- **`lane init` filled the wrong placeholder in `CLAUDE.md`**, so `{{owner}}` stayed literal; it now fills it.
- **`lane init` linked memory under the wrong Claude project folder** for a control plane whose path has a `.` or a space (it still mapped only `/` and `_`); it uses the same slug rule as everything else.
- **`lane doctor -v` exited 0 when the guard suite failed**; it now exits with the suite's status.
- **The board linked tickets to `lanes:`** when `tracker.url` was blank; a blank or missing URL now means plain-text keys, no link.
- **`lane done --discard-ignored` with an untracked secret file** removed the folder by hand after `git worktree remove` refused, leaving a stale worktree record, and archived the lane. It now passes `--force` only when that flag was given and nothing but those files is in the way; if the worktree still cannot be removed (locked, in use) the lane is not archived and the command exits 1.
- **The per-prompt STATE block's `uncommitted` count** included untracked secret-named files, which `lane status` leaves out; both use the same definition now.
- **README and CONTRIBUTING.md** said `lane init` asks two questions (it asks up to five), and CONTRIBUTING.md still described a 184-case suite with `EXPECTED_CASES` and nine probes; both and the other stale counts in `docs/` now match the code.

### Security

- Closes the leak and destruction paths above: `lane-memory` path traversal; the board's staging,
  amend and show-by-glob secret leaks; the board's missing Host/Origin check; `lane park` committing
  untracked secrets; the guard bypasses listed under Changed (command substitution and reader flags,
  `.example` symlink exemption, lane references skipping the secret check, push-refspec spellings,
  unexpanded `$HOME`, `cd` variants, malformed input crashing the guard open, Glob/Grep outside the
  matcher, control-plane self-protection gaps). Most of these were found by independent audits and
  two live trials against Claude Code 2.1.299 in headless (`claude -p`) mode, the second with the
  `haiku` model; each fix has a regression case.
- **Limits that remain** (so this section is not read as a guarantee): the guard reads commands, it
  does not run a shell, and the list of what it cannot see is in `scripts/hooks/README.md`. Stronger
  models, interactive permission prompts, the trust dialog, live Claude Code sessions on Linux, Windows, the hook timeout and a
  subagent calling Grep/Glob/WebFetch/MCP were not tested. A hook `allow` skips Claude Code's own
  permission prompt, as observed in the trials. WebFetch, the Agent tool call itself and MCP tools
  remain outside the matcher (a subagent's own Bash/Read/Edit/Write calls do reach the guard).

## [0.8.1] — 2026-09-22

### Fixed

- **Two findings from the multi-plane registry's own adversarial audit, before it ever reached
  `main`.** Registering a second checkout under a name already used by a different one (usually
  an auto-derived directory basename collision) silently overwrote the first plane's registered
  path — the exact "wrong project's data" failure the registry exists to close, reintroduced via
  the name axis instead of the old symlink axis. `lane install` now refuses a name collision with
  a different path, confirming interactively or refusing outright with no terminal to ask.
  Separately, `lane install` writing `~/.local/share/lane/planes.py` used a plain `cp` with no
  `rm -f` first, unlike every other destination write in the same install step — the identical
  symlink-clobber class of bug the rest of the install logic was already hardened against, just
  missed in this one spot. Both caught by adversarial testing against the real change before it
  merged, not found in the wild.

## [0.8.0] — 2026-09-22

### Added

- **A machine can now register more than one control plane at once.** `~/.local/share/lane/planes.json`
  holds every checkout `lane install` has registered and which one is `active`; a new `lane use [<name>]`
  lists them (with which is `active` and which the current directory resolves to) or switches `active`.
  `~/.local/bin/lane` is now a small, stable, generic dispatcher that is never repointed at one specific
  checkout again — on every call it resolves which registered plane applies (being physically inside a
  project's directory tree always wins over `active`) and `exec`s that checkout's own real `lane`. `lane
  install` writes this dispatcher and registers the current checkout, and only changes `active` when
  nothing is active yet or `--as`/`--make-active` say so — installing from a second or third project no
  longer silently steals `active` away from whatever you were already using. An old, pre-registry install
  is detected and migrated automatically. The 27 long-form commands (`lane-start`, `lane-brief`, …) are
  now tiny stubs that route through the same stable dispatcher rather than each resolving independently.
- `lane board` gained a plane switcher: with more than one registered plane, a dropdown in the command
  bar loads another registered plane's data in place — no second server process, no second tab — while
  defaulting to whichever plane the server was started from/inside. The page `<title>` now names the
  plane currently shown, instead of the static `"lane-board"`.
- `lane doctor` checks the new mechanism: whether the installed `lane` is the stable dispatcher (not a
  stale pre-registry symlink), whether this checkout is registered at all, and whether resolving from
  inside it actually picks it.

### Fixed

- **The general form of the cross-contamination bug described in `v0.7.2` above.** That fix covered one
  specific symptom (slash commands resolving `lane-*` through a plain `PATH` lookup instead of
  `$CLAUDE_PROJECT_DIR`). The underlying cause was broader and is now closed at the root: before this
  change, `~/.local/bin/lane` (and every long-form command) was a symlink directly at ONE specific
  checkout, machine-wide — only one project could ever be "installed" at a time, and running `lane
  install` from a second project silently broke the first. On the machine this was found on, that caused
  three separate incidents in one session: `lane-brief` run inside one project reported a completely
  unrelated project's lanes because `PATH` pointed elsewhere; `lane upgrade` was reported "no such
  command" because `PATH` pointed at a checkout that predated the command; and `lane board` opened empty
  because `PATH` had since been repointed to a third, currently lane-less checkout. The multi-plane
  registry above is the fix: a checkout is chosen by being physically inside its directory tree, never by
  whatever a single machine-wide symlink happened to be pointed at last.

## [0.7.2] — 2026-09-22

### Fixed

- **Slash commands could silently report a completely different repolane installation's state.**
  Every `.claude/commands/*.md` file (`lane-brief`, `lane-done`, `lane-help`, `lane-park`,
  `lane-resume`, `lane-sessions`, `lane-start`, `status`) invoked its script as `/bin/<name>` (a
  leading slash) or, for `lane-start`, as `$AD/bin/lane-start` — `$AD` was never an actual
  exported environment variable, only ever computed locally inside each script. On a machine
  with more than one repolane install, both forms resolve through a plain `PATH` lookup instead
  of the current project, landing on whichever installation happens to be on `PATH` — reported
  live: a fresh `lane-start`'d lane, then `/lane-brief` on the very same id, said "no lane
  'pr-review'. Active lanes: SHOP-412 SHOP-418" — a real, unrelated repolane checkout's lanes,
  reported as if they were the current project's. Both forms now use `$CLAUDE_PROJECT_DIR`
  (Claude Code's own, actually-exported signal for "which project is this"), the same variable
  every hook in `.claude/settings.json` already uses correctly. `permissions.allow`'s patterns
  for the affected read-only commands (`lane-status`, `lane-brief`, `lane-menu`,
  `lane-sessions`) updated to match the new invocation text (Bash permission rules match literal
  command text, not the resolved program).

## [0.7.1] — 2026-09-21

### Fixed

- **`knowledge/shared/` (written by `lane rules pull`'s `knowledge.d/`) was never read by
  anything.** It landed on disk and stayed invisible to a session unless someone wired a pointer
  to it by hand. Every `.md` file there is now injected into every session's context
  automatically, the same way `knowledge/preferences.md` already is — same "applies to every
  session, forever" shape as your own preferences, so shared team knowledge actually reaches a
  session without extra setup.

## [0.7.0] — 2026-09-21

### Added

- **`lane rules pull` also carries `knowledge.d/`**: the shared repo's optional layout gains a
  `knowledge.d/` directory alongside `rules.yaml` and `scripts.d/` — plain markdown, copied
  (never symlinked) under the same SHA pin. Unlike rules/scripts, these files aren't validated or
  executed, just read by a session — but they still can't silently overwrite something you typed
  by hand, so they land in a new `knowledge/shared/` namespace, never directly in `knowledge/`.
  `lane rules status` reports what's loaded there too.

### Fixed

- **`lane init` never disabled the template's own push remote**: after cloning this public
  template, `origin` still pointed at `github.com/aj-oss-tools/repolane` — a plain `git push`
  from inside the control plane would have published `registry/config.yml` (can hold a private
  tracker URL) and `registry/old-checkouts.json` (local filesystem paths) to that public repo.
  `lane init` now disables the push side of `origin` (`git remote set-url --push origin
  DISABLED-set-a-private-remote-first`) whenever it still demonstrably points at the known
  public template — never a remote you've already pointed somewhere of your own. Idempotent, and
  `lane doctor` now flags it too, as a safety net for anyone who set up before this fix existed.
- **`lane secrets <repo> add` reads as bookkeeping but is destructive**: every user-facing
  touchpoint (`scripts/repo-secrets`'s own help text, `lane doctor`'s undeclared-secrets advisory,
  `lane add`'s interactive/non-interactive prompts, `docs/rules.md`, `docs/commands.md`) used
  "declare"/"protect" language that read as passive bookkeeping. `add` actually writes deny rules
  that make the named file(s) unreadable and unwritable to every future Claude Code session — that
  is now said plainly everywhere the command is offered.

### Added

- **`lane status` now reports the control plane's own git state**: `memory/`, `knowledge/`,
  `CLAUDE.md` were invisible to `git status`-checking users forever — after `lane init` they're
  real uncommitted files with nowhere shown to check. A new `== control plane` section (reusing
  `status-all`'s existing dirty/unpushed-counting logic) reports uncommitted file count, unpushed
  commit count, and whether a push remote is configured (or disabled, per the fix above).
- **`private: true` in `registry/config.yml`**: upgrades the documented `git add -f` workaround
  (`docs/extending.md`, "Tracking your control plane's own files in a private fork") into a real
  mode. `lane init` asks about it interactively (like the tracker/stale-days questions), or takes
  `--private`/`--public`, and rewrites `.gitignore` so `registry/repos.yaml`,
  `registry/rules.yaml` and `scripts/local/` are tracked instead of ignored — every other ignore
  rule (`repos/`, `lanes/`, `memory/`, `knowledge/`, `registry/rules.shared.yaml`,
  `registry/.shared-cache/`, `registry/secrets-ignored.yaml`) is untouched. Idempotent, and safe
  to flip retroactively by editing `config.yml` and re-running `lane init`.
- **`lane secrets <repo> ignore <path-or-glob>...`**: marks a `scan` candidate as
  reviewed-and-not-actually-a-secret, without writing any deny rule. Most candidates from `scan`
  turn out to be ordinary source, not secrets, and previously the only way to make `lane doctor`
  stop mentioning one was to deny it. Ignored paths live in a new gitignored
  `registry/secrets-ignored.yaml`, are excluded by `scan` (and therefore by `lane doctor`'s
  advisory), and are listed with the new `lane secrets <repo> ignored` command so a dismissal is
  visible, not silently forgotten.

## [0.6.0] — 2026-09-20

### Added

- **`scripts/local/<name>`**: any executable file there becomes a `lane <name>` subcommand,
  without ever editing the tracked `lane` dispatcher again. Gitignored, a full peer of built-in
  commands (can `source scripts/lib.sh` itself), listed in `lane help` under "your commands:",
  and flagged by `lane doctor` if a name collides with — and is therefore shadowed by — a real
  built-in. See [`docs/extending.md`](docs/extending.md).
- **`lane rules pull`**: a shared, git-backed source for `registry/rules.yaml`-style rules and
  `scripts/local/` scripts, for a team that wants the same guard rules everywhere. SHA-pinned —
  a plain re-pull re-verifies the pin and refuses to advance past it, `lane rules pull --latest`
  is required to intentionally move; files are always copied, never symlinked, into
  `registry/rules.shared.yaml` (a separate file from `registry/rules.yaml`, never merged into
  it) and `scripts/local/`; rule ids are namespaced to the shared repo. `guard.py`'s
  `load_rules()` now unions every `registry/rules.*.yaml` file through the identical
  parse/validate/deny-only path, so a shared rule is checked exactly like a local one. `lane
  doctor` gets a new, more prominent advisory when the pinned SHA has drifted from the shared
  repo's real HEAD. `lane rules status` inspects the configured source without changing
  anything. See [`docs/extending.md`](docs/extending.md).

## [0.5.0] — 2026-09-20

### Added

- **`lane install` refuses or confirms before repointing an existing symlink**, instead of
  silently repointing it. Running it again — a second checkout, a moved clone — used to relink
  `dest/lane` with zero visibility into what it used to point at. A terminal now shows both paths
  and asks; a non-interactive run (an agent, a script) refuses unless `--force` is passed.
- **`lane doctor` checks three more things, advisory-only like its existing reports**: whether the
  `lane` resolved on `PATH` actually points at this checkout (the exact bug the `lane install` fix
  above surfaces, instead of a confusing downstream symptom), whether `gh` is installed and
  authenticated (`lane sync`/`lane gh` need it), and whether each active lane's spec file
  (`repo:`/`branch:`) still matches what's actually checked out under `lanes/<id>/` on disk.
- **`lane upgrade`** automates the manual procedure documented in Troubleshooting's "Upgrade
  friction" section: refuses if tracked files outside `registry/`, `memory/`, `knowledge/`,
  `CLAUDE.md` and `.claude/settings.local.json` are dirty, fetches, and fast-forwards onto
  upstream only when that's a clean fast-forward — any real divergence or conflict stops with the
  same manual recipe (including the `.claude/settings.json` `git checkout --theirs` step) rather
  than attempting a merge, which this deliberately never does. On success it prints the `VERSION`
  delta and the `CHANGELOG.md` sections that landed, then runs `lane doctor`.

## [0.4.0] — 2026-09-20

### Added

- **`lane doctor` flags repos with undeclared candidate secret/credential files.** `lane secrets
  scan|add|list` already let a repo declare filenames the guard's built-in pattern misses
  (`.npmrc`, `id_rsa`, `service-account.json`, ...), but nothing ever prompted you to actually run
  it — a repo added before the feature existed, or where the prompt was declined, sat with zero
  per-repo protection, silently. `lane doctor` now re-runs the same local, no-network scan every
  time and lists any repo with candidates nobody has declared, with the exact command to fix it —
  same advisory-only philosophy as the stale-lane and branch-protection-sync reports, and simpler
  than both since a local filesystem scan needs no staleness window at all.

## [0.3.0] — 2026-09-20

### Added

- **`lane sync [repo]`** checks a repo's real GitHub branch protection (`gh api
  repos/<owner>/<repo>/branches`) and records it in `registry/repos.yaml` as
  `protected_branches:` + `protection_synced: <date>`. `guard.py`'s protected-branch check now
  unions that list in too, alongside `main`/`master`/`develop` and a repo's own
  `default_branch`/`compare_branch` — never fewer branches protected, only ever more accurate.
  Manual and always available; never run automatically by any other command, so nothing that
  "starts work" blocks on a network call. Fails soft (a clear message, never a crash) for a repo
  that isn't on GitHub, or when `gh` is missing or unauthenticated. `lane doctor` now also lists,
  informationally only, any managed GitHub repo whose protection hasn't been checked in
  `protection: sync_days` (`registry/config.yml`, 7 by default; `0` turns it off).

## [0.2.1] — 2026-09-20

### Fixed

- **The guard's default-branch protection (push, force-push, delete/move) only ever recognised
  `main`/`master`/`develop`, hardcoded.** A repo whose integration branch is named something else —
  `release`, `staging`, anything — got none of that protection, including this repo's own `release`
  branch, added by the release-automation work without updating the guard. `registry/repos.yaml`
  already records each repo's `default_branch`/`compare_branch` (set by `lane add`, used elsewhere
  to resolve a lane's base) but `guard.py` never read it. It now unions that into the protected-branch
  check per repo — never fewer branches protected than before, just more accurate when a repo's own
  integration branch has a different name.

## [0.2.0] — 2026-09-19

### Added

- **`lane add` accepts a local checkout with no `origin` remote.** It used to die outright; it now
  registers the repo as local-only (`origin: (local-only)` in `registry/repos.yaml`) and says so,
  including how to add one later: `git -C repos/<name> remote add origin <url>`.
- **`lane secrets <repo> scan|add|list`.** Every repo can have its own credential filenames beyond
  the built-in `.env`/`.pem`/`credentials.json` set the guard already denies globally. `lane add`
  now scans a newly added repo by filename only (never contents) and either prompts to protect the
  candidates it finds (interactive) or reports them for review (agent-driven, so nothing is added
  without a human confirming). Protecting a file writes deny rules into `registry/rules.yaml`, the
  same mechanism described in [`docs/rules.md`](docs/rules.md#rules-of-your-own), so `lane doctor`
  verifies them the same way it verifies any other custom rule.
- **`lane done` now asks what to do with a finished lane's Claude sessions.** Removing a
  worktree left `~/.claude/projects/<slug>` behind forever, unreported. `lane init` now asks
  (`registry/config.yml`'s `lanes: delete_sessions_on_done:`, default keep) which way the prompt
  defaults, but the prompt itself is never skipped in an interactive run; `lane done <id>
  --delete-sessions`/`--keep-sessions` answer it up front, and a non-interactive run (no
  terminal — an agent driving `lane done`) never deletes, it only reports the count.

### Fixed

- **`lane sessions <repo>` was checking a folder that can never have sessions in it.** It looked
  under the slug for `repos/<repo>` — the mirror — but Claude Code is never launched there (the
  guard refuses `cd`-ing into it). It now unions every live lane worktree for the repo, every
  finished lane's worktree (reconstructed from the archived lane file even though the folder is
  gone), and notes separately how many conversations still sit at the repo's pre-Repolane
  checkout (`old_paths:`), not yet brought in with `lane import`.
- **`pref`-scoped memory was written but never read back into a session.** `lane-memory file <slug>
  pref` correctly appended to `knowledge/preferences.md`, but `memory_brief()` in
  `scripts/hooks/guard.py` never read that file, so the most durable scope — meant to apply to
  every lane, forever — was the one scope that silently never reached a session. It now has its
  own `## preferences` section, read the same way the cross-repo and per-repo sections are.

- **`lane env <repo-name>` silently checked nothing.** `lane-env-check` filtered worktrees by lane
  id only, so `lane env <repo-name>` matched no worktree and printed nothing — a result
  indistinguishable from "all good." It now matches against either the lane id or the repo name.

## [0.1.0] — 2026-09-18

First release. Everything below was built between 2026-09-17 and 2026-09-18; there are no earlier
versions, and this is the first tag. It is early, solo-authored software with no external users yet:
used daily by its author, stable for that use, and unproven anywhere else. The layout on disk and
the command names are settled, and the guard has a real test suite — expect rough edges outside the
paths that get walked every day.

### Added

- **Lanes.** `lane start <id> <repo>…` gives each named repo a worktree on one shared branch under
  `lanes/<id>/`, alongside a spec file in `registry/lanes/`. Repos live once in `repos/` as clean
  mirrors, so a second lane costs a checkout rather than a clone. `lane resume`, `lane park`,
  `lane with`, `lane merge` and `lane done` move work through its life.
- **A permission guard.** `scripts/hooks/guard.py` is a hook dispatcher that fences a Claude Code
  session into the lane it belongs to: it refuses reads of other lanes and of the mirrors, refuses
  `.env` and credential files outright, requires an explicit `ALLOW_DEFAULT_BRANCH_PUSH=1` marker to
  push to a default branch, and routes every memory write through a scope the owner chooses.
  Each refusal is documented in [`docs/rules.md`](docs/rules.md) together with the failure behind it.
- **`lane doctor`.** Compiles the guard, fires nine named probes at it and reports every verdict,
  then checks that every lane, worktree and the control-plane root is still wired to it.
- **`lane board`.** A local, no-build git client scoped to the work in flight.
- **Memory and knowledge.** `lane note` writes what a session learned into `memory/<repo>/` or
  `knowledge/`, under a scope the owner picks rather than one the model picks.
- **Documentation.** A README that explains the problem before the mechanism, plus
  [`docs/concepts.md`](docs/concepts.md), [`docs/rules.md`](docs/rules.md),
  [`docs/commands.md`](docs/commands.md), [`docs/board.md`](docs/board.md), and a README in every
  folder with something non-obvious in it.
- **`CHANGELOG.md` and `VERSION`**, so `lane --version` reports something other than `dev`. It reads
  `VERSION`, which works from a downloaded tarball with no git metadata, and adds the distance from
  the release tag when there is a git checkout to ask.
- **`docs/troubleshooting.md`**: what each failure looks like on disk and how to recover from it.

### Fixed

- **The guard test suite tested nothing on almost every machine.** It was written against a fixture
  only the author had — a lane named `docs` containing a repo named `docs` — and when that was
  missing it printed "Skipped" and exited 0. It was also the evidence behind a public claim of 179
  cases. It now builds its own throwaway control plane under `$HOME`, runs every case against a copy
  of the guard inside it, removes it on exit, and asserts the case count so a run that quietly stops
  testing fails instead of looking like a pass. It touches no real lane, repo or memory file.
- **`lane doctor` reported green on a disarmed control plane.** It checked that the guard compiled
  and refused one probe — not that anything still called it. It now verifies the wiring too, and
  names the lanes and worktrees that have lost it. One unfalsifiable line became nine probes,
  including a control that must come back *undecided*, because a guard that refuses everything
  passes all eight refusal probes and is still useless.
- **A lane could disarm its own guard with a shell redirect.** The control-plane rule was wired into
  `Edit`/`Write` but not into Bash write targets, so `echo '{}' > lanes/<id>/.claude/settings.local.json`
  removed a lane's hooks silently while the file tools refused the same thing. Absolute paths under
  the control plane are now tokenised, `mv` counts both ends, the judgement is shared between the two
  paths so they cannot drift apart again, and a session's own `.claude/settings*` is refused outright.
- **The board staged, committed and pushed secrets.** `is_secret()` gated listing and diffing but not
  `/api/stage`, so a `.env` could be committed through the UI — and because the diff is withheld,
  without anyone seeing what they were committing. Staging a secret is now refused by name, and
  `/api/commit` refuses a staged secret as a second line of defence. Unstaging stays allowed.
- **`lane with` could never succeed.** It exec'd `lane-start`, whose "already has a folder" check
  fires unconditionally, and a started lane always has a folder. Growing a lane now inverts that
  check rather than sharing it.
- **`lane install` put `bin/README.md` on your PATH.** It linked every entry in `bin/`, and the
  printed count was one too high. It now links only executables, and removes such a link left by an
  earlier install — but only when it points into a Repolane `bin/` at something that is not a
  command, so an unrelated file in the same directory is never touched.
- **Drift detection had three readers and no writer.** `registry/old-checkouts.json` was read by
  `status-all`, `session-start` and the guard, and nothing ever created it, so drift was permanently
  empty and the guard never refused the abandoned checkouts it claimed to. `lane add` now records
  the checkout it adopted.
- **The resume note swallowed the findings.** It was read as everything between `## Resume note` and
  `## Log`, but `## Findings` sits between them, so every finding was printed twice. All three
  sections now stop at the next heading of any kind.
- **`lane merge` could mark a repo you were committing to as read-only**, by leaving a stray
  `mode: read` in the repos block. The frontmatter is now rebuilt deterministically instead of being
  rewritten by two overlapping regexes.
- **`lane done` from inside the lane printed three `getcwd` errors** after "removed worktree", which
  reads like data loss. It steps out to the control-plane root first.
- **`lane brief` failed on a finished lane**, though the archive is the point of keeping it. It falls
  back to `registry/lanes/done/`, and an unknown id now lists the lanes that do exist.
- **`lane <cmd> --help` was read as a lane id** and answered `no lane '--help'`. The dispatcher
  answers it now, from the same line `lane help` prints.
- **Commands run before `lane init` crashed** with raw git and Python errors. They now say to run
  `lane init`.
- **`lane env <id>` was documented as taking a repo name.** It filters on lane id, so passing a repo
  name printed nothing at all and looked like a clean result.
- Guard leftovers from the `ws` → `lane` rename: the memory-gate exemption no longer recognised the
  tool's own scripts, and `SessionEnd` rewrote the lane file with BSD-only `sed -i ""`.
- A folder `README.md` was indexed as a cross-repo memory wherever memory files are listed.

### Changed

- **Renamed from Lane to Repolane.** Branding only: the command is still `lane`, as are the `lanes/`
  folder, `registry/lanes/` and every `lane-*` script — the same way Homebrew ships `brew`.
- Two documented claims were corrected rather than fixed, because the code was right and the docs
  were not. A `lane ref` is read-only to a session via the hook, not on disk — it is a symlink. And
  the board fetches its typefaces from Google Fonts, so "no network calls beyond its own server" was
  false; [`docs/board.md`](docs/board.md) now says so, and how to remove them.

[Unreleased]: https://github.com/aj-oss-tools/repolane/compare/v0.11.0...HEAD
[0.11.0]: https://github.com/aj-oss-tools/repolane/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/aj-oss-tools/repolane/compare/v0.9.2...v0.10.0
[0.9.2]: https://github.com/aj-oss-tools/repolane/compare/v0.9.1...v0.9.2
[0.9.1]: https://github.com/aj-oss-tools/repolane/compare/v0.9.0...v0.9.1
[0.9.0]: https://github.com/aj-oss-tools/repolane/compare/v0.8.1...v0.9.0
[0.8.1]: https://github.com/aj-oss-tools/repolane/compare/v0.8.0...v0.8.1
[0.8.0]: https://github.com/aj-oss-tools/repolane/compare/v0.7.2...v0.8.0
[0.7.2]: https://github.com/aj-oss-tools/repolane/compare/v0.7.1...v0.7.2
[0.7.1]: https://github.com/aj-oss-tools/repolane/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/aj-oss-tools/repolane/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/aj-oss-tools/repolane/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/aj-oss-tools/repolane/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/aj-oss-tools/repolane/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/aj-oss-tools/repolane/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/aj-oss-tools/repolane/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/aj-oss-tools/repolane/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/aj-oss-tools/repolane/releases/tag/v0.1.0
