# Extending Repolane

Two ways to add to a workspace without forking it: your own `lane` subcommands, and (see
below) a shared, git-backed source of `.repolane/registry/rules.yaml`-style rules for a team.

## Your own `lane <name>` commands

Any executable file in `.repolane/scripts/local/` becomes a `lane <name>` command, where `<name>` is the
file's own name. Nothing else has to change, and nothing in the installed package.

```sh
mkdir -p .repolane/scripts/local
cat > .repolane/scripts/local/hello <<'EOF'
#!/usr/bin/env bash
# lane: say hello
echo "hello from .repolane/scripts/local/hello"
EOF
chmod +x .repolane/scripts/local/hello
lane hello
```

- `.repolane/scripts/local/` is part of your workspace, never of the package: an upgrade never touches it. It is
  exactly the kind of place a personal shortcut or a company-specific script belongs.
- The second line of the file, if it starts with `# lane: `, is the one-liner `lane help` shows
  next to it — the same convention `lane <cmd> --help` already reads its own usage block from.
- A local script is a full peer of a built-in command: it runs with `LANE_PRODUCT` (the installed package's files)
  and `LANE_WORKSPACE` (the workspace) set, can `source "$LANE_PRODUCT/scripts/lib.sh"` exactly the way the built-in
  `repo-secrets` and `lane-sync` do, and then gets the same `$AD`, `$DATA`, `$REGISTRY`, `die`, `repo_exists`, and
  everything else in that library.
- **Built-ins always win.** If `.repolane/scripts/local/` has a file with the same name as a real `lane`
  command, the built-in runs and the local file never does. `lane doctor` flags this — "shadowed
  by the built-in `<name>` command and will never run" — so it is never a silent surprise.
- **The command name is never a path.** `lane <name>` only ever looks up a bare filename directly
  inside `.repolane/scripts/local/` — a name containing `/` (path traversal, or reaching some other
  executable entirely) is rejected before the lookup happens, not resolved.
- **The `# lane: ` one-liner is untrusted display text**, not just local shorthand: it can arrive
  from a shared repo's `scripts.d/` via `lane rules pull` (below), landing on every teammate's
  machine with its comment intact. `lane help` strips control/escape characters from it and caps
  it at 72 characters before printing, so it can't clear the screen, recolor the terminal, or
  otherwise do anything beyond show a one-line description.

## Shared, git-backed rules: `lane rules pull`

`.repolane/registry/rules.yaml` (see [`docs/rules.md`](rules.md#rules-of-your-own)) is yours, per workspace — but a
team often wants the *same* set of project rules everywhere,
without pasting a file around by hand. `lane rules pull` fetches one from a git repo you point it
at, and keeps it in a second, separate file so it is never mixed with — and never overwrites —
whatever you have typed into `.repolane/registry/rules.yaml` yourself.

```sh
lane rules pull git@github.com:your-org/repolane-rules.git   # first pull
lane rules pull                                                # re-pull the same URL, pinned SHA-checked
lane rules pull --latest                                       # intentionally move the pin forward
lane rules status                                               # what is pinned, what is loaded
```

### What the shared repo looks like

At its root:

- `rules.yaml` — **required.** The same schema as `.repolane/registry/rules.yaml`
  ([field table](rules.md#rules-of-your-own)): `rules:`, a list of maps, `when`/`deny`/`ref`, and
  an `example:` for every rule so `lane doctor` can verify it is actually refused.
- `scripts.d/` — **optional.** Files here are copied (never symlinked) into your
  `.repolane/scripts/local/` — see above.
- `knowledge.d/` — **optional.** Plain markdown, copied (never symlinked) into
  `.repolane/knowledge/shared/` — never directly into `.repolane/knowledge/`, so a shared file can never silently
  overwrite or shadow one you typed by hand. Unlike `rules.yaml` and `scripts.d/`, these files
  aren't enforced by anything — they're read by a session, not validated or executed. Every
  `.md` file under `knowledge/shared/` is injected into every session's context automatically,
  the same way `.repolane/knowledge/preferences.md` already is (`guard.py`'s `memory_brief()`) — it's
  the same "applies to every session, forever" shape as your own preferences, so it needs no
  pointer added by hand to actually be read.

### The security properties, on purpose

- **Pinned, never tracking a branch tip.** The first `lane rules pull <url>` records the exact
  commit SHA it fetched, in `.repolane/config.yml`. Every later `lane rules pull` with no
  arguments re-fetches, diffs the new commit against the pinned one, and refuses to advance past
  it without confirmation. Only `lane rules pull --latest` intentionally moves the pin. A team's
  guard rules drifting silently, because someone's machine quietly tracked `main`, is exactly the
  failure this is built to prevent.
- **Copied, never symlinked or live-mounted.** The pulled repo lives in a cache
  (`.repolane/registry/.shared-cache/`, machine-local: keep it out of your workspace repo); nothing under
  `.repolane/registry/` or `.repolane/scripts/local/` ever points into it.
  A cache directory that goes away, or gets tampered with between pulls, cannot silently change
  what is enforced — only an explicit `lane rules pull` does that, and it re-verifies the pin
  each time.
- **A separate file, never merged into your own.** Shared rules land in
  `.repolane/registry/rules.shared.yaml`, not `.repolane/registry/rules.yaml`. The guard's
  `load_rules()` reads every `.repolane/registry/rules.*.yaml` file and unions them — through the *exact*
  same parsing, validation and `deny`-only enforcement path, no special case for a shared-sourced
  rule. A malformed or broken shared rule is caught by `lane doctor` exactly the way a broken
  local one already is.
- **Namespaced ids.** A rule pulled from a shared source has its `id` prefixed (`shared-<id>`,
  or `<repo-name>-<id>` when the shared repo names itself), so it cannot silently collide with —
  or shadow — a rule you wrote by hand.
- **Duplicate ids are rejected, not merged.** If a namespace prefix isn't enough — two rules
  genuinely end up with the identical id, in one file or across `rules.yaml` and
  `rules.shared.yaml` — the loader keeps the first one enforced and refuses the rest,
  reported by `lane doctor` exactly like any other broken rule. Two rules sharing an id would
  otherwise make `lane doctor`'s own per-rule verification meaningless (it couldn't tell which
  one actually fired), so this is checked structurally, not left to convention.
- **`knowledge.d/` never overwrites your own knowledge.** A shared `knowledge.d/preferences.md`
  cannot collide with your `.repolane/knowledge/preferences.md` — it lands in the separate
  `knowledge/shared/` namespace instead, the same "copied into a clearly-separate location, never
  merged into what you already have" principle as `rules.shared.yaml`.
- **No remote code.** This deliberately supports only a declarative `rules.yaml` (structurally
  validated, and the loader can only ever add a `deny` — see
  [`docs/rules.md`](rules.md#rules-of-your-own)) and a directory of plain scripts you can read
  before they land in `.repolane/scripts/local/`. It does **not** support pulling custom Python guard logic
  (an eventual `rules.d/*.py`, if this codebase ever grows one) from a remote source —
  running someone else's code inside your own `PreToolUse` hook is a different risk category
  than a rule file that can only refuse things, and this feature does not go there.

### `lane doctor`

Two advisories, both non-blocking:

- `.repolane/scripts/local/<name>` shadowed by a built-in — see above.
- The pinned shared-rules SHA is behind the shared repo's real `HEAD` (a cheap
  `git ls-remote`). This one line is printed more prominently than the other advisories — team
  guard-rule drift is a different severity of problem than one person's stale local cache — but
  it still never blocks, and never pulls anything itself.

## Sharing a workspace's files with a team

Your workspace can be a git repo of your own ([Installing Repolane](install.md#keep-your-workspace-in-your-own-git-repo)),
and nothing in it is ignored except what is machine-local. So `.repolane/registry/repos.yaml`,
`.repolane/registry/rules.yaml` and `.repolane/scripts/local/` are tracked like any other file you commit: a team that
wants everyone to start from the same repo list, rules and commands can keep one workspace repo and clone it on each
machine. What should stay per person — `.repolane/memory/`, `.repolane/knowledge/` — is up to you: leave it out of the
shared repo, or add it to `.gitignore`.

For rules alone, `lane rules pull` (above) is the lighter way: every machine pins the same commit of a separate rules
repo, and nobody's own files are touched.
