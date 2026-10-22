# Why it refuses things

Every refusal here exists because the alternative went wrong. If you hit one, this page says why.

Every rule below is enforced by Repolane's guard (`scripts/hooks/guard.py` in the installed package, which the
`lane hook` commands in your settings run) inspecting the tool call Claude Code is
about to make — the text of a Bash command, the path a file tool names — and answering allow or
deny. It is not an operating-system sandbox: it cannot stop anything Claude Code itself did not
route through a hook, and on hook input it does not recognize it fails open (lets the call through)
rather than blocking everything. "Never" and "cannot" below describe what the guard denies when it
recognizes the operation, not a guarantee enforced below the process level.

## Stay in the lane you are in

A session belongs to one piece of work. The guard denies reads of other lanes, the mirrors, or
anything outside this folder. Without this, a session asked to fix one bug quietly reads four repos,
fills its context with unrelated code, and starts making changes nobody asked for.

Need something outside? Attach it once with `lane ref` and read it at `lanes/<id>/refs/<name>`.
The hook refuses writes through a reference unless it was attached with `--rw`. It is a symlink
underneath, so this constrains the session, not you.

## Do not enter a repo

The session sits at `lanes/<id>/`, never inside `lanes/<id>/<repo>/`. Entering one makes that repo look
like the main one, and multi-repo work degrades into single-repo work. Nothing needs it:
`lane run <repo> <cmd>`, `lane gh <repo> <args>`, `git -C <repo>`, and editing `<repo>/file` all work
from where you are.

## The mirrors are read-only

`.repolane/repos/<name>` stays on its default branch and clean, because every worktree shares its object
store. Work in a worktree.

## The workspace is edited from the root

Your own commands, rules, the registry, memory and `.claude/settings.json` are changed from a session started at
the workspace root, not from inside a lane. A lane editing the rules that constrain it is how you lose the rules.

## Secret files are denied by default

The guard refuses the file tools and any Bash command naming a file it recognizes as a secret —
`.env*`, `*.pem`/`*.key`/`*.p12`/`*.pfx`, `*credentials*.json`, `secrets.json`/`.yaml`/`.toml` —
even when you grant permission: the read itself is the problem, because the values end up in a
transcript. Structure is available instead, via `.env.example` or `lane keys <path>`, which lists
key names and never values. This is a fixed, filename-based pattern, not every credential a project
might have — see ["Per-repo secret files"](#per-repo-secret-files) below for filenames the guard
doesn't recognize on its own and how to add them.

## Pushing to a default branch needs your word

`main`, `master` and `develop` are refused, plus a repo's own `default_branch`/`compare_branch`
(`.repolane/registry/repos.yaml`, set by `lane add`) — so a repo whose integration branch is named something
else, `release` or `staging`, gets the same protection without you writing a rule for it. Once a
repo has been checked with `lane sync`, its real GitHub branch protection is unioned in too. When
you do mean it, the command carries a marker you can see: `ALLOW_DEFAULT_BRANCH_PUSH=1 git push …`.
Remotes may never be added, changed or removed.

## Memory is never written directly

Claude drafts, then asks which of the four scopes it belongs in. Left alone, everything becomes a
permanent global preference, and within a month the system is full of things that were true once.

## New branches start from the default branch

Not from whatever happens to be checked out.

## Ask before committing

Commits are proposed, and shaped as coherent units: neither one commit per edit nor one enormous
commit at the end.

## Rules of your own

The rules above ship with Repolane, because they are true of every project. The ones that are
true only of *your* project — "never run a migration by hand, the entrypoint does it", "that
branch deploys itself" — go in `.repolane/registry/rules.yaml`, in your workspace. It never reaches the package or anyone else unless you
commit it to a repo you share.

A rule can only add a refusal. There is no syntax for granting anything, and the loader has no
path to anything but the same `deny` the built-in rules use — so a rules file can tighten this
guard and never loosen it. Project rules are checked first, before the built-ins, because a few
built-ins answer "allow" and stop.

```yaml
rules:
  - id: no-manual-migrations
    when: { tool: Bash, matches: '\balembic\s+(upgrade|downgrade)\b' }
    deny: "entrypoint.sh applies migrations on every start. Restart the service instead."
    ref: memory/api/migrations.md
    example: "alembic upgrade head"

  - id: no-editing-generated-schema
    when: { tool: Edit, path: 'schema/generated/**' }
    deny: "schema/generated/ is written by codegen. Edit the source schema and regenerate."
    ref: docs/codegen.md
    example: { path: "schema/generated/types.ts" }
```

| field | |
| --- | --- |
| `id` | how the refusal names itself, and what `lane doctor` reports |
| `when.tool` | the tool name exactly as Claude Code spells it: `Bash`, `Edit`, `Write`, `Read`, … |
| `when.matches` | a Python regular expression, for `Bash`. One rule has `matches` or `path`, never both |
| `when.path` | a glob, for the file tools. Matched against the path as written and against every tail of it, so `schema/generated/**` works wherever the repo is checked out in a lane |
| `deny` | what Claude is told. Say what to do instead, not just "no" |
| `ref` | **required.** The file that says why. A refusal nobody can check is a refusal that gets routed around, which is the whole reason the built-in messages all cite something |
| `example` | a case the rule must refuse. `lane doctor` feeds it through the guard on every run |

Values are single-line: the parser reads a deliberately small YAML subset — `rules:`, one map
per rule, scalars and one-line `{ … }` or an indented block under `when:`. Anything else is
reported as an error rather than half-understood.

The guard doesn't only read `rules.yaml` — it reads every `.repolane/registry/rules.*.yaml` file
and unions them all through this identical parse/validate/deny-only path, no special-casing for
any of them. `rules.shared.yaml` is the one you'll usually see alongside it: it's what
`lane rules pull` (a team-shared, SHA-pinned source of rules — see
[`docs/extending.md`](extending.md)) writes, with every rule id namespaced so it can't silently
collide with one you typed by hand. A broken rule in either file is caught by `lane doctor` the
same way, regardless of which file it came from.

`matches` is tested against the same normalised command segments the built-in rules are tested
against, not against the raw string, so `echo ok && alembic upgrade head` is judged exactly as
`alembic upgrade head` is. A rule cannot be slipped by chaining.

### Worked example: a branch that deploys itself

The built-in rule covers `main`, `master` and `develop`. If your CI deploys on a push to
something else, that is a rule of yours. Mirror the marker the built-in uses, so that when you do
mean it, the command says so in a form you can see:

```yaml
  - id: no-push-to-deploy-branch
    when:
      tool: Bash
      matches: '^(?!ALLOW_DEPLOY_PUSH=1\b).*\bgit\s+push\b.*\b(deploy|release)/'
    deny: "Pushing to a deploy/* or release/* branch ships it — CI deploys that branch on push. Ask first; if it is meant, run it with the marker: ALLOW_DEPLOY_PUSH=1 git push …"
    ref: docs/deploys.md
    example: "git push origin HEAD:deploy/staging"
```

`git push origin HEAD:deploy/staging` is refused; the same command behind
`ALLOW_DEPLOY_PUSH=1` is not.

### Per-repo secret files

`is_secret()` denies a fixed set of shapes — `.env*`, `*.pem`/`*.key`/`*.p12`/`*.pfx`,
`*credentials*.json`, `secrets.json`/`.yaml`/`.toml` — across every repo, for the file tools and for
Bash commands that name them. That set cannot grow to cover every project's own credential
filenames (`service-account.json`, `.npmrc`, `id_rsa`, `.aws/credentials`, `apikey.txt`, …) without
becoming unbounded, so those are declared per repo instead, using the exact mechanism above.

`lane add` scans a newly added repo for filename patterns that look like credentials beyond the
built-in set — by filename only, never by reading contents. Most candidates in a typical repo turn
out to be ordinary source (`password.py`, `token_store.py`, `credentials.py`) rather than actual
secrets, so review before acting. Run interactively, it prints what it found and asks whether to
**deny** them. Run without a terminal (an AI agent driving `lane add`), it only reports the
candidates for a human to review — nothing is ever denied without someone confirming, the same
principle behind every other guard behaviour in this repo.

`lane secrets <repo> add <path>` is **destructive, not bookkeeping**: it writes six deny rules into
`.repolane/registry/rules.yaml` (one each for `Read`, `Edit`, `Write`, `MultiEdit`, `NotebookEdit`, and
`Bash`), which makes that file unreadable (and unwritable) to every future Claude Code session in
this repo — so `lane doctor` checks them the same way it checks any other rule of your own. If a
candidate is a false positive — not actually a secret — use `lane secrets <repo> ignore <path>`
instead: it marks the path reviewed-and-not-a-secret in a separate
`.repolane/registry/secrets-ignored.yaml`, so `scan` (and `lane doctor`'s advisory) stops surfacing it, and
**no deny rule is written**. `lane secrets <repo> scan` runs the scan (excluding anything already
`ignore`d); `lane secrets <repo> list` shows what has been denied; `lane secrets <repo> ignored`
shows what has been dismissed.

### When the file is wrong

A rule with no `ref`, no `deny`, an unparseable `when`, or a `matches` that is not a valid regular
expression is not loaded — and never silently. The hook says so on stderr and carries on with the
built-in rules (the guard fails open by design, but it says so), and `lane doctor` fails, naming
each rule and the line. The same is true of a YAML error: you get the line number, not a
traceback and not a shrug.

`lane doctor` checks four things, and reports a fifth. It checks that the guard compiles, that it
still answers eleven named probes the way it should (ten refusals and one ordinary command it must leave alone), that every
rule in your `rules.yaml` still refuses its own `example` — and is refused *by that rule*,
not incidentally by a built-in — and that every lane and worktree is still wired to it. It prints each verdict, so the answer is something
you can check rather than something you have to believe; `lane doctor -v` also runs the full
guard suite. A session whose `settings.local.json` lost
its hooks is unguarded even when the guard itself is perfectly healthy, so both are checked.

It then reports one thing that is not a health check at all: **lanes nobody has touched in a
while**. Any lane whose `updated:` date is more than `stale_days` ago (`.repolane/config.yml`,
21 days by default; `0` turns it off) and that still has a worktree on disk is listed with its
age, its size on disk, why it is still here, and the one command that clears it:

| what it found | what it says | what to run |
|---|---|---|
| merged into its base, clean, fully pushed | `merged into its base and fully pushed` | `lane done <id>` |
| clean and pushed, but nothing was ever committed on the branch | `nothing was ever done on it` | `lane done <id> --delete-branches` |
| not merged, or dirty, or unpushed | what is unfinished, in as many words | `lane park <id> "<note>"` |

Nothing is parked, finished or deleted for you, and no prompt appears: `lane doctor` is called
from scripts and never blocks. It is also not a failure — a stale lane is untidy, not broken, so
this section never changes the exit code. (`lane audit` asks the same question of the mirrors'
branches and writes a file; this asks it of the lanes themselves, every time you run the doctor.)

It reports one more thing the same way: repos whose real GitHub branch protection hasn't been
checked. `lane sync [repo]` calls `gh api` for a repo's protected branches and writes them into
`.repolane/registry/repos.yaml` as `protected_branches:` + `protection_synced: <date>` — the guard unions
that in on top of `main`/`master`/`develop` and the repo's own `default_branch`/`compare_branch`,
never in place of them. Any managed repo on GitHub whose `protection_synced` is missing, or older
than `protection: sync_days` (`.repolane/config.yml`, 7 days by default; `0` turns it off), is
listed with `lane sync <repo>` to clear it. `lane sync` is never run for you — not by `lane
doctor`, not by `lane start`/`lane resume` — it is a manual, always-available command, so nothing
that "starts work" ever blocks on a network call to GitHub.

And a fourth: repos with a candidate secret/credential filename (`lane secrets <repo> scan`'s
patterns — `.npmrc`, `id_rsa`, `service-account.json` and the rest, see
["Rules of your own"](#rules-of-your-own) above) that nobody has reviewed yet — neither denied with
`lane secrets <repo> add` nor dismissed with `lane secrets <repo> ignore`. Unlike the other three,
this needs no staleness window at all — it is a plain local filesystem scan, cheap enough to
re-run on every `lane doctor`, so it is always current.
