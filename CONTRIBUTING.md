# Contributing to Repolane

Issues, discussions and pull requests are welcome, and used. If something is broken, unclear or
missing, filing it is the useful thing to do — you do not need to have a fix in hand, or to be
sure it is a real bug.

- [**Issues**](https://github.com/aj-oss-tools/repolane/issues) — bugs and feature requests.
  There are templates; they mostly ask for the command you ran and what it did.
- [**Discussions**](https://github.com/aj-oss-tools/repolane/discussions) — questions, "is this a
  bug or am I holding it wrong", and general feedback.
- **Pull requests** — the rest of this page.

This page is the long version of the README's "Status and contributing" paragraph: what the
project expects of a change, and why.

## What this repo is

A folder of bash scripts and two stdlib Python programs (`scripts/hooks/guard.py` and
`scripts/board/server.py`). There is no package manifest — no `package.json`, no
`pyproject.toml`, no `requirements.txt` — and that is deliberate, not an oversight. A control
plane you clone and run should not need a build step or an install of anything beyond `git`,
`bash` and `python3`, which are already on the machine. **A change that adds a dependency needs
an argument for itself before it needs code.**

So: bash and stdlib Python only. Nothing compiled, nothing fetched at runtime.

## Run the tests

Three suites, all stdlib-only, and each builds its own throwaway control plane under a temporary
`HOME` with local bare repos as remotes, so none of them reads or writes your real lanes, mirrors,
memory or `~/.claude`, and none needs the network. Safe on a fresh clone or on a machine with years
of work in it.

```sh
bash scripts/hooks/test-guard.sh          # the guard: well over 1,800 cases, ending in ALL PASS
bash tests/run-all.sh                     # the lane commands: every tests/t_*.sh in its own sandbox
python3 -W ignore scripts/board/test_board.py   # the board server's regression tests
```

Each exits non-zero on any failure. There is no hard-coded case count to bump: the guard suite
fails if the number it passed differs from the number it ran, so a case that silently never
asserted cannot hide, and adding a case needs no bookkeeping. For a change to a `lane` command, add
a case to the matching `tests/t_*.sh` (they share `tests/lib.sh`); for the board, to
`scripts/board/test_board.py`.

`tests/t_upgrade_path.sh` is the upgrade check: it installs the newest `v*` release tag, runs that
release's own `lane init` and `lane upgrade`, and upgrades onto your branch. A change that makes the
shipped upgrader refuse or conflict fails it, for example editing a tracked file that `lane init`
leaves modified in every install (`registry/config.yml`). Run it with `bash tests/t_upgrade_path.sh`
in a checkout that has the tags.

CI runs these on every push and pull request: [`.github/workflows/tests.yml`](.github/workflows/tests.yml)
runs `tests/run-all.sh`, the guard suite and the board smoke test (`scripts/board/smoke.sh`) on Linux
and on macOS's bash 3.2, and [`.github/workflows/test.yml`](.github/workflows/test.yml) runs the guard
suite alone on pull requests into `main` and `release`.

`lane doctor` runs eleven named probes against the guard; `lane doctor -v` runs the whole guard suite
and exits non-zero if it fails.

## If you touch `scripts/hooks/guard.py`

Add a case for whatever you changed. **A rule with no test is a rule that will quietly stop
working** — it is the failure mode this project cares most about, because nothing visibly breaks
when a refusal silently starts allowing.

Read [`docs/rules.md`](docs/rules.md) first. Every refusal in the guard has a story behind it,
and that page tells each one. A change that removes or loosens a rule should say which story it
thinks no longer applies.

If what you want is a refusal specific to *your* project rather than to every project, you
probably do not need to touch `guard.py` at all: `registry/rules.yaml` takes rules in YAML and
the loader can only ever add a `deny`. See
["Rules of your own"](docs/rules.md#rules-of-your-own) for the format, the fields, and why a
rules file can tighten the guard and never loosen it.

## Docs are part of the change

The docs in this repo describe behaviour precisely, and they have been kept honest — if the code
says one thing and a page says another, the page is a bug. Keep it that way. A pull request that
changes behaviour and leaves the docs describing the old behaviour is not finished.

| | |
|---|---|
| [`docs/concepts.md`](docs/concepts.md) | the model: lanes, repos, the registry |
| [`docs/rules.md`](docs/rules.md) | every refusal, and the failure behind it |
| [`docs/commands.md`](docs/commands.md) | the full command reference |
| [`docs/board.md`](docs/board.md) | the web board |
| [`docs/troubleshooting.md`](docs/troubleshooting.md) | the ways it breaks, and how to recover |
| [`docs/releasing.md`](docs/releasing.md) | how a merged PR actually becomes a release |
| [`docs/extending.md`](docs/extending.md) | `scripts/local/` custom commands, and `lane rules pull` for shared rules |

Each folder also has its own README explaining what lives there — `scripts/`, `scripts/hooks/`,
`scripts/board/`, `registry/`, `memory/`, `knowledge/`, `.claude/`. If you add a file, the
folder's README should still be true afterwards. User-visible changes belong in
[`CHANGELOG.md`](CHANGELOG.md) too.

## Proposing a change

1. Open an issue first if it is a design change or a new rule. For a bug or an obvious fix, go
   straight to a pull request.
2. Fork, and branch from `release` — **not `main`.** `main` only ever moves by a "Release
   vX.Y.Z" PR merging in from `release`, opened automatically once something lands there; your PR
   into `release` is the whole contribution, you never need to touch `main` or think about version
   numbers. Full picture: [`docs/releasing.md`](docs/releasing.md).
3. Make the change. Match the surrounding style: `set -u`, explicit error paths, comments that
   explain *why* rather than restating the line below them.
4. Run the suites above (at least the one for what you touched), and `lane doctor` if you have the clone set up.
5. Open the pull request against `release`. Say what changed and why, and whether the suite still
   passes. If the change is user-visible, add an entry under `## [Unreleased]` in
   [`CHANGELOG.md`](CHANGELOG.md) — merging into `release` is what makes that section non-empty,
   which is what triggers the automatic version bump (see
   [`.github/workflows/release-plan.yml`](.github/workflows/release-plan.yml): the bump type comes
   from which headings — `### Added`, `### Fixed`, `### Removed` — are actually used, not from a
   commit-message convention).

Keep pull requests to one thing. A guard rule and a board tweak are two pull requests.

## Reporting a security problem

If you find a way to get the guard to allow something it should refuse — a path that escapes the
lane, a chained command that slips past, a way to read a secret file — please report it privately
through [GitHub's vulnerability reporting](https://github.com/aj-oss-tools/repolane/security/advisories/new)
rather than a public issue. See [SECURITY.md](SECURITY.md) for what's in scope.

## Conduct

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).
