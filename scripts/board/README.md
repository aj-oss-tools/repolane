# `scripts/board/` — the web board

`lane board` opens a local web page: a git client scoped to the work you actually have in flight.
It is meant to replace reaching for a desktop git app, not to be a general one.

| | |
|---|---|
| `server.py` | stdlib HTTP server and the whole API |
| `index.html` | the page: markup and an inline SVG icon sprite |
| `board.js` | all the behaviour — three screens and a command bar |
| `board.css` | one token set, light and dark |
| `smoke.sh` | starts a server on a spare port, hits every endpoint, stops it |
| `test_board.py` | regression suite (stdlib unittest): the real server on a scratch plane in a temp dir with a throwaway HOME; `smoke.sh` runs it |

**No build step and no dependencies.** Python standard library on one side, plain
HTML/CSS/JavaScript on the other. Editing `board.js` and reloading the page is the whole dev loop.
The only outbound request the page makes is to Google Fonts for its typefaces; everything else is
served by `server.py`.

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
- **Memory names are plain slugs.** `/api/memory` rejects anything outside `[A-Za-z0-9._-]+`
  (no leading `-`, not only dots) with 400 before `lane-memory` runs.
- **Mirrors are never touched.** Every path is resolved and checked to be inside `lanes/`, so
  `?lane=../repos` is refused rather than served.
- **Secret files never leave the server.** The `SECRET` pattern (`.env*`, `*.pem`, `*.key`,
  `credentials*.json`, `secrets.*`) is matched on the path (case-insensitively, so `.ENV` counts) *before* git is asked for content. A diff
  of a secret file comes back flagged and empty — it is dropped, not redacted, so there is no
  version of the response that ever held the values. `smoke.sh` asserts this.

## The API

```
GET  /                      the page, with the token injected
GET  /api/board             every lane with per-repo state
GET  /api/repo              ?lane=&repo=            files, log, branch, PR, sessions
GET  /api/diff              ?lane=&repo=&file=&staged=0|1
GET  /api/show              ?lane=&repo=&sha=       one commit
GET  /api/spec              ?lane=                  the lane markdown
GET  /api/brief             ?lane=                  lane-brief output
GET  /api/lanelog           ?lane=                  commits across every repo of a lane
POST /api/stage             {lane,repo,files,stage}
POST /api/discard           {lane,repo,files}       throws away uncommitted changes
POST /api/commit            {lane,repo,message}
POST /api/amend             {lane,repo,message}     refused once pushed
POST /api/push | /api/pull  {lane,repo}
POST /api/pr                {lane,repo}             create a pull request
POST /api/ref               attach or detach a reference
POST /api/memory, /api/memfile                      browse and re-scope memories
POST /api/lane              {action:start|resume|park|done, id, repos?, note?}
```

Lifecycle actions shell out to the same `lane-*` scripts you would run in a terminal, so the board
cannot do anything the commands cannot — `park` still insists on a real resume note, `done` still
refuses while a repo is dirty or unpushed.

## The page

Three screens, one command bar. `⌘K` (or the jump control) moves between lanes without going home.

**Home** — what is in progress, what each lane touches, what needs attention. The "next action" per
repo is computed server-side (pull, stage, commit, push, open a PR, finish).

**Work** — one lane: its repos, the files you changed, the diff of the one you picked, and a commit
box. Side panels cover History, Notes, Refs, Spec and past Sessions. History has a scope toggle:
this repo's branch, or every repo of the lane at once.

**Memory** — the four scopes and what is in each, with duplicate detection and the live findings of
each lane.

State that should survive a reload (theme, last lane, last repo, current view) is kept in
`localStorage` under `lane-*` keys, every access wrapped in try/catch so a private window or blocked
site data degrades to defaults instead of throwing.
