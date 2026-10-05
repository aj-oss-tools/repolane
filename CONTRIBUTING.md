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

## Run the guard's test suite

```sh
bash scripts/hooks/test-guard.sh
```

It builds its own throwaway control plane in a temp directory under `$HOME` and runs every case
against a copy of `guard.py` placed inside it. It never reads or writes your real lanes, mirrors
or memory, so it is safe to run anywhere — on a fresh clone or on a machine with years of work
in it. It prints `184/184 cases passed` and `ALL PASS`, and exits non-zero on any mismatch.

The suite also fails if it asserts *fewer* cases than it expects: `EXPECTED_CASES` at the top of
the file is checked against the number actually run, because a safety suite that exits 0 without
having asserted anything is worse than no suite at all. If you add cases, bump that number in the
same commit.

`lane doctor` runs nine named probes against the guard; `lane doctor -v` runs this whole suite.

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
4. Run `bash scripts/hooks/test-guard.sh`, and `lane doctor` if you have the clone set up.
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
