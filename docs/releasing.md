# How releases work

You don't need to read this to fix a bug or add something small — [`CONTRIBUTING.md`](../CONTRIBUTING.md)
covers what a normal pull request needs. This page is the full picture, for anyone who wants to
understand (or debug) the pipeline itself.

## The branch model

```
feature/your-fix ──┐
feature/other      ──┼──PR──►  release   (the staging branch — no PR review required to land
another contributor─┘                     here, but it's protected against force-push/delete)
                                   │
                     push to release with real content under
                     ## [Unreleased] in CHANGELOG.md triggers:
                                   │
                                   ▼
                     .github/workflows/release-plan.yml
                       - reads which ### headings are under Unreleased
                         (### Removed / BREAKING → major
                          ### Added               → minor
                          otherwise (Fixed/Changed/...) → patch)
                       - moves Unreleased's content into a new
                         "## [x.y.z] — <date>" section
                       - regenerates every changelog reference link
                       - bumps VERSION
                       - commits that to release
                       - opens/updates a "Release vX.Y.Z" PR: release → main
                                   │
                     merging that PR is the release action
                                   │
                                   ▼
                                 main   (protected: PR required, CI required —
                                          see that PR's own page for who can merge it)
                                   │
                     merging triggers .github/workflows/tag-release.yml
                     (tags the merge commit vX.Y.Z) and notify-site.yml
                     (rebuilds repolane.dev's changelog page)
```

## Who does what

- **Anyone** (fork or branch, doesn't matter) — fix something, branch from `release`, open a PR
  *into* `release`. That's the entire contribution flow; you never touch `main` directly, and you
  never need to think about version numbers.
- **`release`** is where work lands before it ships. It's not reviewed as strictly as `main` — no
  required approving review, no required status check gating the merge itself — but it's still
  protected against force-push and deletion, and every PR into it still runs the guard's test
  suite (`.github/workflows/test.yml`) so you get fast feedback either way.
- A plain contributor's PR into `release` never becomes a release by itself: it waits there until
  the auto-opened "Release vX.Y.Z" PR (into `main`) gets merged. Nothing about the automation
  decides *when* to ship — only *what version number* the next release should be, once it's
  merged. Who's able to merge it is whatever `main`'s PR page already shows you.
- **That one PR — `release` → `main` — always gets a plain merge commit, never squash or
  rebase.** Both of those rewrite the commits' SHAs when they land on `main`, which makes
  `release` instantly diverge from what it just shipped and forces a reconcile merge before the
  next push to `release` will even apply cleanly (this bit us twice before the rule existed). A
  real merge commit keeps `release`'s commits exactly as they are and just ties them into `main`,
  so `release` stays a clean ancestor and nothing needs reconciling afterward. Feature-branch PRs
  *into* `release` are unaffected by this — squash is still fine there, since those branches get
  discarded anyway.

## What you actually need to do in a PR

1. Branch from `release`.
2. Make the change. Run `bash scripts/hooks/test-guard.sh` (and `lane doctor` if you have a clone
   set up).
3. If the change is user-visible, add an entry under `## [Unreleased]` in
   [`CHANGELOG.md`](../CHANGELOG.md), under the right heading (`### Added` for a new capability,
   `### Fixed` for a bug fix, `### Changed`/`### Removed`/`### Security` as they apply) — **this
   heading is what decides the next version's major/minor/patch bump**, so get it right; see the
   diagram above. There's no separate "PR type" field or commit-message convention to learn — the
   changelog entry you'd write anyway is the only input the automation uses.
4. Open the PR against `release`, not `main`.

That's genuinely the whole contributor-facing surface. Everything past step 4 — the version
number, the PR into `main`, the tag, the site rebuild — happens without you, and without the
maintainer needing to do anything by hand either, once they decide to merge.

## Why the changelog entry isn't auto-generated

It would be possible to have CI draft a changelog entry from a PR's title/description
automatically. Deliberately not done, for two reasons: the heading you choose directly decides
the version bump, so an unreviewed, auto-generated entry could silently mis-tag a feature as a
patch (or vice versa); and the entries in this changelog are written with the actual root cause
in mind, not just a summary of the diff — something a PR description alone usually can't give you
as precisely. Writing the entry is the one place in this whole pipeline where a human judgment
call is genuinely load-bearing, so it stays manual on purpose.

## Every change reaches main through a PR, and release never falls behind main

Two small workflows keep the branches in step, each backed by a script with its own tests
(`tests/t_releasepr.sh`, `tests/t_releasesync.sh`):

- **`release-plan.yml` ends with `scripts/release-pr`.** Whenever `release` has non-merge commits that `main`
  lacks, it opens (or updates) the pull request `release` → `main`. If `VERSION` on `release` is ahead of `main`'s the title is
  **"Release vX.Y.Z"** and merging it tags the version. If it is not (docs, CI, tests: nothing was planned) the
  title is **"Sync release into main"** and merging it tags nothing, bumps nothing and does not rebuild the site's
  changelog. Either way the checks run on the PR before anything reaches `main`. Merge commits do not count, so there is
  never an empty PR.
- **`sync-release.yml` runs `scripts/release-sync` after every push to `main`.** Merging the release PR with a merge
  commit leaves that commit on `main` only; this brings it back into `release` (a fast-forward when `release` has not
  moved, a merge commit when it has) so `release` is never behind `main`. A conflict fails the job with the files named;
  nothing is forced or resolved automatically. Both workflows share one concurrency group, so they never push to
  `release` at the same time.

Both need the PR to be merged with a **plain merge commit** (never squash or rebase), as above: a squash gives the
change a new SHA on `main`, and `release` would then look ahead of `main` for good.

## If something in the pipeline itself breaks

The pipeline has needed a couple of fixes to itself along the way (a token permission the
default `GITHUB_TOKEN` doesn't have because the org blocks Actions from opening PRs — see
`RELEASE_PR_TOKEN` in `.github/workflows/release-plan.yml`'s comments; a missing git identity
before tagging in `tag-release.yml`). A fix to the pipeline's own workflow files is not user-visible in the `CHANGELOG.md` sense, so it has no
changelog entry and no version: `release-plan.yml` then opens a **"Sync release into main"** PR instead of a
release PR (see below), so it still reaches `main` through the checks.
