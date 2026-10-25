# The board

`lane board` opens a local web page. It is a git client scoped to your work, and it replaces
reaching for a desktop git app.

It serves only to your own machine and reads the same files the commands do. Nothing is sent
anywhere.

## Three places

A rail on the left holds them: Active lanes, Parked, Memory, and every lane in flight.

**Home** is what opens: a card per lane with its Goal, one row per repo with its branch and state
(uncommitted, to push, to pull, behind its base, PR checks failing, clean), and the one thing to do
next. Parked lanes sit below with their resume note. On the right: what wants a decision, memory
drafts waiting for a scope, and recent Claude conversations with a `claude --resume` line to copy.

**A lane** is one piece of work. The repos it spans, the files you have changed (staged and
unstaged), the diff of the one you picked, and a commit box. History shows this repo's commits or
every repo's at once. *About this lane* (press `i`) opens a side panel with the Goal, resume note,
Findings, references, past conversations and the lane file.

**Memory** browses the scopes and what is in each, and files or discards drafts.

Press the jump control in the top bar, or Command-K, to move between pieces of work without going
back Home. Press `?` for every shortcut.

Every screen has its own address, so Back and Forward work, a reload keeps your place, and a link
can be shared or bookmarked: `/lanes/<lane>/<repo>` for a lane's changes (`?file=` opens a diff),
`/lanes/<lane>/<repo>/history` and `/lanes/<lane>/<repo>/commits/<sha>` for its history, `/memory`
for memory. Another registered workspace adds `/w/<name>` in front.

## Which workspace it shows

The board shows the workspace you start `lane board` in (or the one `LANE_WORKSPACE` names). To look at another
workspace, run `lane board` there. Every state-changing action (stage, commit, push, pull, discard, amend,
start/resume/park/done) is validated server-side against that workspace's registry on every request. The board binds
`127.0.0.1` only and requires the per-run `X-Token` header for every state-changing route.

## Notes

Ticket keys link wherever `tracker.url` in `.repolane/config.yml` points. Blank means keys show as
plain text.

Secret files are never shown: the server drops them by path before git is asked for any content.

The page is plain HTML, CSS and JavaScript with no build step. It uses the same palette and typefaces as
repolane.dev — the fonts ship with the board and are served by it — and makes no outbound requests. It
follows your system's light or dark setting; the theme button in the top bar switches between system,
light and dark.
