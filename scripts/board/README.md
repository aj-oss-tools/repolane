# `scripts/board/` — the web board

`lane board` opens a local web page: a git client scoped to the work you actually have in flight.
It is meant to replace reaching for a desktop git app, not to be a general one.

| | |
|---|---|
| `server.py` | stdlib HTTP server and the whole API |
| `index.html` | the page: markup and an inline SVG icon sprite |
| `board.js` | all the behaviour — three screens, a rail and a top bar |
| `board.css` | one token set, light and dark |
| `smoke.sh` | starts a server on a spare port, hits every endpoint, stops it |
| `test_board.py` | regression suite (stdlib unittest): the real server on a scratch plane in a temp dir with a throwaway HOME; `smoke.sh` runs it |

**No build step and no dependencies.** Python standard library on one side, plain
HTML/CSS/JavaScript on the other. Editing `board.js` and reloading the page is the whole dev loop.
The page makes no outbound requests: everything, its fonts included, is served by `server.py`.

| | |
|---|---|
| `fonts/` | Inter, JetBrains Mono and Instrument Serif — the same files repolane.dev serves (SIL OFL, `fonts/OFL.txt`) |

`board.css` is the single source of design tokens: colours, type, spacing, radii and control sizes live in its two
`:root` blocks (light, and `:root[data-theme="dark"]`), mirroring repolane.dev's palette. `--scale` (0.9) sets the
overall density; text never drops below `--fs-min` (11px). `test_board.py` fails on a colour, font family, px font size
or radius anywhere else in the file, and on any inline `style=` in the page or `board.js`.

## Running it

```sh
lane board                      # opens a browser at http://127.0.0.1:7777/
WS_BOARD_PORT=7801 lane board   # a different port
bash scripts/board/smoke.sh     # the smoke test
```

If the port is taken the server tries the next one. `WS_BOARD_NO_OPEN=1` starts it without opening a
browser.

## Security model

The board can commit, push and discard changes, so it is deliberately boring about access:

- **Bound to `127.0.0.1`.** Never `0.0.0.0`; nothing outside the machine can reach it.
- **A fresh token per run.** `secrets.token_urlsafe(24)`, substituted into the page as `__TOKEN__`
  (it is not printed; only the URL is). Every `/api/*` call must send it as `X-Token`, or the server
  answers 403. The token dies with the process. One token covers every registered plane.
- **Only `127.0.0.1` / `localhost` on the server's own port.** Every request, `GET /` and the static
  files included, is refused with 403 unless its `Host` (and its `Origin`, when sent) is exactly that.
  This is what stops a DNS-rebinding page from loading `/` and reading the token.
- **Paths are never pathspecs.** Staging and diffing accept only exact changed files (or a directory
  holding changed files); `.`, globs, `..` and option-like names are refused, and every git call
  runs with `--literal-pathspecs`. Amend and commit both refuse while a secret file is staged.
- **Memory names are plain slugs.** `/api/memory/…` rejects anything outside `[A-Za-z0-9._-]+`
  (no leading `-`, not only dots) with 400 before `lane-memory` runs.
- **Mirrors are never touched.** Every path is resolved and checked to be inside `lanes/`, so
  `/api/lanes/..%2Frepos/…` is refused rather than served.
- **Secret files never leave the server.** The `SECRET` pattern (`.env*`, `*.pem`, `*.key`,
  `credentials*.json`, `secrets.*`) is matched on the path (case-insensitively, so `.ENV` counts) *before* git is asked for content. A diff
  of a secret file comes back flagged and empty — it is dropped, not redacted, so there is no
  version of the response that ever held the values. `smoke.sh` asserts this.

## The URLs

The path names the place; query parameters only change how it is shown.

```
/                                         Home
/memory  /memory/<scope>?file=<file>      Memory (scope: cross, pref, drafts, repo:<repo>)
/lanes/<lane>                             a lane, on its last or busiest repo
/lanes/<lane>/<repo>?file=<path>&staged=1 Changes, with that file's diff open
/lanes/<lane>/<repo>/history              History  (?repos=all every repo of the lane, ?range=all earlier commits too)
/lanes/<lane>/<repo>/commits/<sha>        one commit
?theme=light|dark|system                  on any page
```

Another registered workspace puts `/w/<name>` in front of any of these; the default one has no prefix. Moving
somewhere adds a browser history entry, changing what is shown (the open file, staged, history scope) replaces it,
and a reload or a pasted link lands on the same screen. The server answers every one of these shapes with the page
and anything else with 404. An old `/#lane=X&repo=Y` link is rewritten to `/lanes/X/Y`.

## The API

Same rule: the resource is the path, the verb of a POST is its last segment.

```
GET  /api/board | /api/planes | /api/sessions
GET  /api/lanes/<lane>/spec | /api/lanes/<lane>/log[?all=1] | /api/lanes/<lane>/brief
GET  /api/lanes/<lane>/repos/<repo>                         files, log, branch, PR, sessions
GET  /api/lanes/<lane>/repos/<repo>/diff?file=&staged=0|1&all=1
GET  /api/lanes/<lane>/repos/<repo>/commits/<sha>[?all=1]
GET  /api/memory | /api/memory/<scope>/<file>
POST /api/lanes/<lane>/{start|resume|park|done}             {repos} for start, {note} for park
POST /api/lanes/<lane>/repos/<repo>/{stage|unstage|discard}  {files}
POST /api/lanes/<lane>/repos/<repo>/{commit|amend}           {message}   (amend refused once pushed)
POST /api/lanes/<lane>/repos/<repo>/{push|pull|pr}           pr answers a compare URL
POST /api/lanes/<lane>/refs/attach {path,note,rw} · /api/lanes/<lane>/refs/<name>/{detach|reveal}
POST /api/memory/drafts/<file>/{file|discard} {to,lane} · /api/memory/<scope>/<file>/{move|delete} {to}
```

Another workspace: `/api/w/<name>/…`. Each path segment is percent-decoded once and refused (400) if it is empty,
`.` or `..`, or holds `/`, `\` or a control character; lane and repo ids must be plain names, shas hex.

Lifecycle actions shell out to the same `lane-*` scripts you would run in a terminal, so the board
cannot do anything the commands cannot — `park` still insists on a real resume note, `done` still
refuses while a repo is dirty or unpushed.

## The page

Three screens, a top bar and a left rail (Active lanes, Parked, Memory, the lanes in flight). `⌘K` (or
the jump control) moves between lanes without going home.

**Home** — a card per active lane (Goal, one row per repo with branch and state chips, one next-action
button that opens the lane on the repo that needs it), parked lanes with their resume note, and a right
column: what wants a decision, memory drafts (File it / Discard), recent sessions, a tally. Inside a
lane the "next action" per repo is computed server-side (pull, stage, commit, push, open a PR, finish).

**Work** — one lane: its repos, the files you changed (staged / unstaged), the diff of the one you
picked, and a commit box. History has a scope toggle: this repo's branch, or every repo of the lane at
once. *About this lane* (`i`) is a side panel: Goal, resume note, Findings, references, sessions, the
lane file.

**Memory** — the scopes and what is in each; drafts are filed or discarded, filed memories moved or
deleted.

Where you are lives in the URL. Conveniences (theme, the collapsed Parked section, the last repo per lane) are kept in
`localStorage` under `lane-*` keys, every access wrapped in try/catch so a private window or blocked
site data degrades to defaults instead of throwing.
