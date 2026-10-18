# `scripts/hooks/` — the guard

This is the part of Repolane that makes the rules real. Everything else is convenience; this is the
thing that refuses.

| | |
|---|---|
| `guard.py` | the whole dispatcher — one file, no dependencies |
| `guard-check` | is it healthy? compiles it, fires eleven named probes, checks every lane is wired, and lists lanes nobody has touched in `stale_days` with the command that clears each (`lane doctor`; `-v` also runs the suite) |
| `test-guard.sh` | 1,700+ cases covering every rule, against a throwaway control plane it builds itself (there is no hard-coded count to keep in step: every section must run at least one case and the totals must add up) |

## How it is wired

`.claude/settings.json` at the control plane root points seven hook events at `guard.py`, and
`write_guard` in `../lib.sh` writes the same wiring into every lane and worktree. The `PreToolUse`
matcher (`Bash|Edit|Write|MultiEdit|NotebookEdit|Read|EnterWorktree|Glob|Grep`) is written in those two
places and the suite fails if they ever differ; `lane doctor` also flags a lane whose matcher predates
`Glob|Grep` (run `lane resume` to rewrite it). The script reads
the hook JSON on stdin, branches on `hook_event_name`, prints a JSON decision on stdout, and exits.

```
PreToolUse        allow / deny / add context, before the tool runs
PostToolUse       records every file edited, into lanes/<id>/.touched
UserPromptSubmit  injects the lane's state, and the memory index on first use
PreCompact        re-states the rules and the lane spec, so compaction cannot drop them;
                  clears the per-session cache so the memory and rules briefs inject again
SessionEnd        appends a state line to the lane file; tidies transcripts
WorktreeCreate    interprets EnterWorktree name="<id>" as "resume this lane"
WorktreeRemove    always refuses — worktrees are removed by lane-done
```

`AD` is derived from the script's own real path, so the guard always knows which control plane it
belongs to regardless of where the session was launched.

## What it actually checks

The important idea: **the guard reads the tool call, not the intention.** For Bash it reads the command
with a small shell reader (`shell_stmts`, one linear pass): quotes (including `$'…'` and `$"…"`) are
removed, `;` `&` `|` and newlines end a statement, `$( )`, backticks and `( )` become statements of their
own, redirect targets are kept apart from arguments, and `bash -c '…'`, `eval …`, `env -S '…'` and `su -c '…'`
are followed. A heredoc body, a here-string and what `echo`/`printf` pipe in are **data** for the command
that receives them (`cat`, `git commit -F -`, `gh pr create --body-file -`) and **code** for a shell or
an interpreter (`bash <<< '…'`, `echo '…' | sh`, `python3 - <<EOF`), which is then read as code.
Every rule then works on words, not on a regular expression over the raw line, so `git push origin
'main';`, `{ cd /; }` and `ls $(cat .env)` are judged as what they are -- and a 96 KB command costs the
same as a short one (the regexes this replaced were quadratic).

- **Paths are judged as written, and again where their symlinks lead.** A path under the home
  directory but outside the plane is refused, and so is `$HOME` itself (`~`, `$HOME`, `${HOME}` are
  expanded). A symlink inside a lane that leads out is refused, except a lane's own attached
  reference (`lanes/<id>/refs/…`). The program being run is not followed through its links, so a
  `.venv/bin/python` that points into a version manager still works.
- **Write targets are distinguished from reads.** `rm`, `touch`, `tee`, `sed -i` and friends treat
  every path as a target; `cp`, `mv`, `ln` treat only their *last* argument as one; `git -C <dir>`
  with a writing subcommand targets that directory; `>` and `>>` targets are collected too. This is
  why reading a mirror is fine and writing to one is not.
- **Secrets are denied by default.** `SECRET_SAFE_CMDS` is a short allow-list of commands that only
  touch metadata (`ls`, `stat`, `wc`, `find`, `lane-env-keys`…), matched as the exact command word, and
  only without the options that turn them into readers (`file -f`, `wc --files0-from`, `find -exec`).
  Anything else naming a secret path is refused -- including the `cat .env` hiding inside `$( )`. A
  `.env.example` that is a symlink to `.env` is the secret, not the template. An earlier version
  listed the *readers* instead, and `dd`, `gpg -d` and `git show HEAD:.env` walked straight through.
  The names it knows are in `SECRET_FILE` (`.env*`, `*.pem *.key *.p12 *.pfx *.p8 *.jks *.keystore *.kdbx`,
  `id_rsa id_ed25519 id_ecdsa id_dsa`, `.netrc .npmrc .pgpass .git-credentials .htpasswd`,
  `*credentials*.json`, `service-account*.json`, `secrets.{json,yaml,toml}`); the same pattern is
  written in `scripts/gitstate.sh` and `scripts/board/server.py` and `tests/` fails if the three differ.
  What counts as a *name* is read after the shell would have read it: variables set earlier in the same
  command (`f=.en; cat ${f}v`), brace expansion (`.{env,x}`), `$'\x2eenv'`, and what `$(echo .env)` prints.
  Text that merely **mentions** a name reads nothing and passes: what `echo`/`printf` print, a commit
  message (`-m`, `-am`), a `gh --body`/`--title`, a grep pattern, an `--exclude=`/`-g '!…'`/`find -name`
  pattern, a heredoc body (see above). The one copy of a secret that is allowed is the onboarding step
  `cp .env.example .env`: only a source that is a template by name *and* by where it leads, copied to
  a place inside this lane. `git rm --cached`, `git check-ignore` and `git ls-files` take names and
  open nothing, so they pass. A list of names piped into a reader (`ls .env | xargs cat`,
  `find . -name '*.pem' | xargs cat`, `xargs cat <<< .env`) is judged as if typed after `cat`.
- **A whole folder is a read of everything in it.** `grep -r`, `rg --hidden`, `tar c`, `zip -r`, `cp -r`,
  `rsync`, `scp -r`, `diff -r` and `find … -exec <reader>` are refused over a folder that holds a secret
  unless they exclude it explicitly (`--exclude='.env*'`, `-x`, `! -name`, `rg -g '!…'`) or can only
  reach files that cannot be one (`--include='*.py'`, `-t py`); a copy that lands inside the lane is
  fine. `.git`, `node_modules` and virtualenvs are not searched for secrets (a package's own test keys
  are not yours), and a folder with more than 100,000 files is refused as too big to vouch for. `rg` and
  `ag` skip hidden files by default, so `.env` does not trip them unless `--hidden`/`-uu` is given; a
  non-hidden `server.pem` does. `Grep` (the tool) is judged the same way: a folder that holds a secret
  may be searched only with a glob that leaves it out (`"!.env*"`), a glob that cannot match it
  (`"*.py"`) or a `type`. `Glob` lists names only, like `ls`, and is left alone.
- **Program text is searched, not parsed.** `python3 -c`, `node -e`, `ruby -e`, `perl -e`, and anything
  fed to an interpreter on its stdin: a secret's name, the common ways of assembling one (`'.'+'env'`,
  `chr(46)`, `fromCharCode`, base64) next to a file read, a glob that names one, a path outside the
  plane, and -- if the program writes at all -- a path into the plane are refused. It cannot see a name
  computed from arbitrary data; that is a limit of the approach, not something it pretends to cover.
- **`cd` is a door, and the cwd is simulated.** In Claude Code a `cd` moves the session, so every
  directory a command would enter (`cd`, `pushd`, `builtin cd`, `\cd`, `{ cd x; }`, `eval cd x`, a bare
  `cd`) is resolved from where the previous statement left the shell (`walk_cwds`) and judged by the same
  rules as `EnterWorktree`: `cd ..; cd ..; cd ..` leaves a lane on the second step, and `cd app && cat
  ../../../../x` is judged from `app`. Every later path, redirect, `$PWD` and `$(pwd)` is resolved from
  that simulated directory. A cd inside `( )`, `$( )` or `bash -c` moves nothing outside its own process
  and is not counted as leaving, but the paths after it are still judged from there. What cannot be
  followed is widened or refused, never ignored: a cd to a missing directory, after `||`, in an
  `if`/`while` body or a pipeline keeps both the old and the new directory; a cd to a computed target
  (`cd $x`) leaves the cwd unknown (and is refused inside a lane, and makes a later relative path with
  `..` refused elsewhere); a cd inside a loop or a function, which may repeat, is refused inside a lane;
  `CDPATH` is read (a plain `cd name` may mean `$CDPATH/name`).
- **The plane protects itself.** From inside a lane the plane's code, docs, `bin/`, `.github/`,
  `registry/` (except the lane's own spec), `.cache/` (except the memory inbox), the files at its root
  and every `.claude/settings*` are not writable -- by a file tool, a redirect, or a link that leads
  there. `git -C <plane> checkout|reset|clean|apply` is a write to it. Control-plane commands (`lane
  upgrade`, `init`, `install`, `add`, `use`, `rules pull`, `secrets add|ignore`) are for the dispatcher
  session; `lane-done|park|resume|with` act only on the lane you are in; `lane-ref add` refuses `/`,
  the home directory, system and credential directories and secret files.
- **Pushes are read, not pattern-matched.** `git push` is judged by its refspecs: `+main`, `'main'`,
  `HEAD:refs/heads/main`, `:main`, `--delete main`, `--all`, `--mirror` and a bare `git push` while a
  protected branch is checked out are all refused, whether the line is `bash -c`, `eval`, a heredoc,
  `xargs`, an `env -S` string or reached through a `git -c`. A `git <word>` that git does not ship may be
  a user alias for `push`, so one that names a protected branch (`git x origin main`) is refused (`git lg`
  and `git co feature` are not), and so is anything that defines one or changes where hooks and settings
  come from: `-c alias.*`, `core.hooksPath`, `include.path`, `GIT_CONFIG_*`, `GIT_EXEC_PATH`,
  `GIT_TEMPLATE_DIR`, `git config` setting any of those or any setting that holds a program
  (`core.editor`, `core.pager`, `core.sshCommand`, `credential.helper` …: written into the config it
  would run unseen on every later git call), and writes to `.git/config` or `.git/hooks`. A program given
  for one call, with `-c core.pager=…` or `GIT_EDITOR=…`/`GIT_SSH_COMMAND=…` in the environment, is read
  as the shell code it is, so `GIT_EDITOR=true git rebase --continue` works and `GIT_EDITOR='git push
  origin main' git commit` does not. The `ALLOW_DEFAULT_BRANCH_PUSH=1` marker works per statement and never overrides a
  force-push, but it is **advisory**: Claude can type it as easily as the human can, so it records that
  the human agreed, it does not prove it. A hard version needs something the model cannot produce --
  for example the human exporting `ALLOW_DEFAULT_BRANCH_PUSH=1` in the environment Claude Code is
  launched from, which the hook process inherits and the command text does not show -- and is not
  implemented. `gh` writes (`api` with a body or a non-GET method, `pr merge|close`, `secret|variable
  set|delete`, `alias set`, `extension install|exec`, `ssh-key|gpg-key add`, `release|issue|label|run|cache
  delete`, `workflow disable`, `repo edit --visibility|--default-branch|--name`, `auth token`) are
  refused; `gh repo edit --delete-branch-on-merge` is not.
- **Our own commands are exempt — narrowly.** A command made only of `lane-*` scripts (no redirect
  except to `/dev/null`, nothing in a `$( )`) is trusted, because they validate their own arguments. `lane-run` and `lane-gh` are explicitly *not* exempt:
  they carry someone else's command, and it is judged as if typed directly. Only a script this plane
  really has counts: a bare name that exists in its `scripts/` or `bin/`, or a path that leads
  there from where the command runs -- `/tmp/lane-evil` and a repo's own `scripts/lane-evil` are just
  other commands. From inside a lane, `lane-ref <other lane> add|rm` is refused like the other
  lifecycle commands.
- **Writes are found by verb.** Besides `rm touch tee dd truncate chmod sed -i`, `cp mv ln install rsync scp`
  (last argument), the guard treats `perl -i`/`-pi`, `ruby -i`, `awk -i inplace`, `patch`, `ed`, `ex`,
  `vi`/`vim`, `sponge`, `tar`, `unzip`, `zip`, `curl -o`, `wget -O` and an interpreter whose program writes
  as writing every path they name. A word with a `$` it cannot read is judged by the part before it
  (`/plane/scripts/$f` is a path into the plane), `$PWD`, `$(pwd)`, `$(git rev-parse --show-toplevel)`,
  `${HOME:-x}` and `~user` (any account's home counts as outside) are read.

## What it does not see (stated, not hidden)

A heuristic over a reader is not a shell. Where a command's meaning depends on something the reader
cannot see, it refuses (fails closed) and says why; where refusing would block ordinary work it does
not see, and that is listed here:

- **Fails closed:** input to a shell or interpreter that comes from anything but a literal heredoc /
  here-string / `echo` / `printf` / a file it can read (`curl … | sh`, `cat x | bash`); code that only
  exists after another command ran (`bash -c "$(…)"`, `eval $x` -- unless the substitution is a literal
  `echo`/`printf`/heredoc); `bash -c` / `eval` / `env -S` nested more than 4 deep, a group nested more
  than 100 deep, more than 8 programs inside one command, a brace expansion past 256 words, a glob
  component longer than any file name that is mostly wildcards; an unterminated `$'…'`; a cd to a
  computed target or in a loop or a function; `xargs git push …` fed from a stdin it cannot read.
- **Not seen:** the contents of a script that is run by name (`bash build.sh`, `source x`, `./run`), so
  a script can do what the line cannot; a variable it cannot resolve (`cat $f` where `$f` is set
  elsewhere); the output of a command other than echo/printf/cat (`cat $(ls -a | grep env)`); interpreter
  code that builds a name by arbitrary computation; what `git diff --cached`, `git log -p` or `git stash
  show -p` print from history (they name no secret); whether an `rg` run is stopped by a `.gitignore`.

It also adds context rather than only subtracting it: the first time a session touches a repo,
`rules_brief()` injects that repo's own `CLAUDE.md` and the list of its `.claude/rules/*`; the
first prompt in a lane carries `memory_brief()`. A small per-session cache under `.cache/sessions/`
stops it repeating itself.

## When the input is not what was expected

The two failure modes are chosen on purpose (the same text is at the top of `guard.py`):

- **`PreToolUse` fails closed.** A payload the guard cannot make sense of -- a `command` that is not a
  string, a `cwd` that is not a path, a body that is not JSON but plainly a `PreToolUse` call -- is
  answered with a deny that says why, and so is any unexpected exception while judging a tool call.
  A hook that crashes exits non-zero *without a decision* and Claude Code then runs the tool, so an
  input that crashes the guard would be the easiest bypass there is. The price of a guard bug is one
  refused command with the reason printed, not a silently unguarded session.
- **Every other event fails open.** `UserPromptSubmit`, `PreCompact`, `SessionEnd`, `PostToolUse` and
  `Worktree*` only add context or tidy up; refusing them would break the session over bookkeeping.
  Unreadable input there is ignored (exit 0), and a crash exits 1 so Claude Code shows a hook error.
- A body that is valid JSON but not an object (`null`, a list) has no event name, so there is nothing
  to decide: exit 0.

What fail-closed cannot cover is the guard not running at all: a syntax error disables every rule,
which is exactly what `guard-check` exists to catch, and why `status-all` runs it before printing
anything and warns you not to trust the state below if it fails.

## Changing a rule

Run the suite:

```sh
bash scripts/hooks/test-guard.sh
```

It builds its own throwaway control plane under a temp directory — a lane with repos, a mirror,
an attached reference, a second lane to test reach-in against, an existing memory file — copies
`guard.py` into it (a copy, not a symlink: the guard finds the control plane from its own real
path) and runs every case there. The guard runs with `HOME` pointed at a fake home inside that
directory, so the result is the same wherever the real `$HOME` or `$TMPDIR` is (`/Users`, `/home`,
`/tmp`, macOS `/var/folders`). It asserts the same cases on a fresh clone as on a machine full of
work, and it never reads or writes your real lanes, mirrors or memory (`LANE_TEST_KEEP=1` keeps the
fixture so you can poke at it). If the fixture
cannot be built the run fails; it never skips. There is no hard-coded case count (nobody notices when
one is edited to match a suite that lost half its cases): instead every section must run at least one
case, every case must also see the guard exit with status 0, and the totals must add up. The
`K` section makes the guard hit a real internal error and asserts it answers with a deny, not a crash.

A case is one line:

```bash
bash_case deny "rm $AD/lanes/$OTHER/app.ts"
file_case allow Read "$AD/lanes/docs/refs/client-docs/README.md"
expect deny "EnterWorktree with a path" "{...raw hook json...}"
```

`pass` means the guard returned no decision and normal permissions apply — which is different from
`allow`, which short-circuits them.

Add a case for whatever you change, in both directions: the thing that should now be refused, and
the near-miss that should still be allowed. Most of the regressions this file has caught were rules
that became *too* broad and started refusing ordinary work.
