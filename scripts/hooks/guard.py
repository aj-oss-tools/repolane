#!/usr/bin/env python3
"""lane hook dispatcher. Configured in the control plane/.claude/settings.json; runs for every session
launched at the control plane root, including after EnterWorktree moved the session into lanes/<id>/<repo>.
Reads the hook JSON on stdin, decides by hook_event_name.

What happens when the input is not what we expect is decided here, on purpose:
  PreToolUse fails CLOSED. A payload the guard cannot make sense of (a command that is not a string, a cwd that is
  not a path, a body that is not JSON but plainly a PreToolUse call) is answered with a deny that says so, and so is
  any unexpected exception while judging a tool call. A hook that crashes exits non-zero WITHOUT a decision, and
  Claude Code then runs the tool: an input that crashes the guard would be the easiest bypass there is. The price of
  a guard bug is one refused command, with the reason printed, never a silently unguarded one.
  Every other event (UserPromptSubmit, PreCompact, SessionEnd, PostToolUse, Worktree*) fails OPEN: those only add
  context or tidy up, and refusing them would break the session over bookkeeping. Unreadable input there is
  ignored (exit 0); a crash exits 1 so Claude Code shows a hook error instead of hiding it.
A body that is valid JSON but not an object (null, a list) carries no event name, so there is nothing to decide: exit 0.

The Bash rules are a heuristic over a shell reader, not a shell, and the limits are decided here too. Where a command's
meaning depends on something the reader cannot see, it FAILS CLOSED instead of guessing:
  - the cwd is simulated statement by statement (`cd a && cd b`, `cd x; cat ../y`), a cd to a computed target leaves it
    unknown, and a cd inside a loop or a function (which repeats) is refused inside a lane;
  - text fed to a shell or an interpreter (heredoc, here-string, a pipe from echo/printf, `-c`, `env -S`, `eval`) is code and
    is read as code; text fed to anything else is data and is not. Input the guard cannot see (`curl … | sh`,
    `bash "$cmd"`, `eval "$(…)"`) is refused;
  - nesting deeper than the reader follows, an expansion that grows past its cap and a string it cannot parse are refused;
  - an unknown `git <word>` that names a protected branch is treated as a possible alias for `push`.
What it does NOT see, and says so rather than pretending: the contents of a script run by name (`bash build.sh`, `source x`),
a variable it cannot resolve (`cat $f`), the output of a command that is not echo/printf/cat, and interpreter code that builds
a file name out of arbitrary computation (only the common assembling idioms are refused). ALLOW_DEFAULT_BRANCH_PUSH=1 is a
marker the model can type itself, so it is advisory: it documents that the human agreed, it does not prove it."""
import fnmatch, glob, itertools, json, os, re, subprocess, sys, datetime

LIMIT = []       # why the Bash reader gave up on a command; any entry turns the call into a deny (fail closed)
_EVENT = ""      # set once the payload is read; the crash handler below needs it to pick fail-closed vs fail-open
def _crash(et, ev, tb):
    import traceback
    traceback.print_exception(et, ev, tb)
    if _EVENT == "PreToolUse":
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
              "permissionDecisionReason": f"The lane guard hit an internal error ({et.__name__}) while judging this tool call, "
                                          f"and refuses what it cannot judge. Retry; if it repeats, run `lane doctor` and report it."}}))
    sys.stdout.flush(); sys.stderr.flush()
    os._exit(0 if _EVENT == "PreToolUse" else 1)
sys.excepthook = _crash

# Two roots, as in scripts/lib.sh: PRODUCT holds Repolane's own files (this one, scripts/, templates), AD is the workspace
# with the user's data. A clone is both, so by default they are the one folder this file sits in, wherever the session
# was launched; LANE_PRODUCT / LANE_WORKSPACE point either somewhere else. scripts/roots.py decides them and every data
# path, for a workspace (data under .repolane/) and a clone alike, exactly as scripts/roots.sh does for the shell.
# Real paths, always: every rule below compares real paths. The product is never written to, not even a __pycache__.
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
try:
    import roots as _roots
except Exception as _e:
    # Without its resolver the guard cannot know what to protect. That must not become a silent pass: a PreToolUse
    # call is refused, like any other internal error (fail closed), every other event shows a hook error.
    _raw0 = sys.stdin.read() if not sys.stdin.isatty() else ""
    if re.search(r'"hook_event_name"\s*:\s*"PreToolUse"', _raw0):
        _EVENT = "PreToolUse"
    raise
sys.path.pop(0)
R = _roots.Roots(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))
PRODUCT, AD = R.product, R.ad
HOME = os.path.expanduser("~")


def _owner():
    """Who the messages should name. One line in registry/config.yml. Falls back to a neutral
    word so a fresh clone nobody has configured yet still reads sensibly."""
    try:
        with open(R.config) as fh:
            m = re.search(r"^owner:\s*$.*?^\s+name:\s*(.+?)\s*$", fh.read(), re.M | re.S)
            if m:
                return m.group(1).strip().strip("\"'") or "the user"
    except OSError:
        pass
    return "the user"

OWNER = _owner()
REPOS, LANES, LANES_DIR = R.repos, R.lanes, R.lanes_dir
REGISTRY, MEMORY, KNOWLEDGE, CACHE = R.registry, R.memory, R.knowledge, R.cache

def out(obj): print(json.dumps(obj).replace("__OWNER__", OWNER)); sys.exit(0)
def deny(event, reason):
    # the refusals are written in a clone's words; a workspace's are its own paths and commands (roots.Roots.words)
    reason = R.words(reason)
    out({"hookSpecificOutput": {"hookEventName": event, "permissionDecision": "deny", "permissionDecisionReason": reason}})
def allow(event): out({"hookSpecificOutput": {"hookEventName": event, "permissionDecision": "allow"}})
def context(event, text): out({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}})
def lane_of(path):
    """lane id if path is under lanes/<id>/…, else None. Only ids that really exist count, so a stray
    path like lanes/repos/… is not reported as a lane."""
    return _lane_id(os.path.realpath(path)) if path else None
def _lane_id(p):
    if not p.startswith(LANES + "/"): return None
    seg = p[len(LANES) + 1:].split("/")[0]
    if not seg: return None
    if os.path.isdir(f"{LANES}/{seg}") or os.path.exists(f"{LANES_DIR}/{seg}.md"): return seg
    return None
def git(cwd, *args):
    try: return subprocess.check_output(["git", "-C", cwd, *args], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception: return ""

def lane_repo_dirs(lane):
    d = f"{LANES}/{lane}"
    return sorted(x for x in os.listdir(d) if os.path.isdir(f"{d}/{x}") and os.path.exists(f"{d}/{x}/.git")) if os.path.isdir(d) else []
def dirty_count(path):
    """Changed entries, NOT counting untracked secret-named files: the definition `lane status` uses (scripts/gitstate.sh
    lane_dirty_count) and the board's dirty_count. `lane park` leaves those out on purpose, so they are not unfinished work."""
    out = ""
    try: out = subprocess.check_output(["git", "--literal-pathspecs", "-C", path, "status", "--porcelain=v1", "-z"], stderr=subprocess.DEVNULL).decode("utf-8", "surrogateescape")
    except Exception: pass
    items = out.split("\0"); n = 0; i = 0
    while i < len(items):
        e = items[i]; i += 1
        if not e: continue
        if e[0] in "RC" and i < len(items): i += 1
        if e[:2] != "??": n += 1; continue
        name = e[3:]
        if not name.endswith("/"):
            n += 0 if _secret_name(name) else 1
        else:
            files = git(path, "ls-files", "-o", "--exclude-standard", "--", name).splitlines()
            if any(not _secret_name(x) for x in files): n += 1
    return n
def repo_state(path):
    dirty = dirty_count(path)
    br = git(path, "branch", "--show-current")
    # "ahead" is commits on HEAD that no origin/* branch has: the definition `lane status`, `lane done`, the board and the
    # statusline use (scripts/gitstate.sh lane_unpushed). The configured upstream is origin/<base> for a lane branch and a
    # plain `git push origin <id>` never changes it, so counting against @{u} disagreed with all of them.
    if not git(path, "remote", "get-url", "origin"): return br, "local-only", "-", dirty
    ahead = git(path, "rev-list", "--count", "HEAD", "--not", "--remotes=origin") or "?"
    behind = (git(path, "rev-list", "--count", f"HEAD..origin/{br}") or "-") if br and git(path, "rev-parse", "-q", "--verify", f"refs/remotes/origin/{br}") else "-"
    return br, ahead, behind, dirty
def slug_of(path):
    u = git(path, "remote", "get-url", "origin")
    m = re.search(r"github\.com[:/]([^/]+/[^/.]+)", u or "")
    return m.group(1) if m else ""

def state_block(lane, cwd):
    here = os.path.realpath(cwd); lines = []
    for r in lane_repo_dirs(lane):
        p = f"{LANES}/{lane}/{r}"; b, a, be, d = repo_state(p)
        mark = "*" if here == os.path.realpath(p) or here.startswith(os.path.realpath(p) + "/") else " "
        sl = slug_of(p)
        lines.append(f"  {mark} {r:22} branch: {b:26} ahead: {a:>3}  behind: {be:>3}  uncommitted: {d}"
                     + (f"   [{sl}]" if sl else ""))
    return "\n".join(lines)

SESS_DIR = f"{CACHE}/sessions"
def sess_file(sid):
    """The per-session cache file. The id comes from the payload, so it cannot be allowed to carry a path."""
    return f"{SESS_DIR}/{re.sub(r'[^A-Za-z0-9_.-]', '_', str(sid or 'nosid'))[:120]}.json"
def sess_state(sid):
    os.makedirs(SESS_DIR, exist_ok=True); p = sess_file(sid)
    try: return json.load(open(p)), p
    except Exception: return {"mem": [], "rules": []}, p
def sess_save(st, p):
    try: json.dump(st, open(p, "w"))
    except Exception: pass
def read(path, limit=6000):
    try: s = open(path).read()
    except Exception: return ""
    return s if len(s) <= limit else s[:limit] + f"\n… [{len(s)-limit} more chars — open {os.path.relpath(path, AD)} if needed]"
def memory_brief(lane):
    """Cross-repo index + every lane repo's index. Indexes only; Claude opens files it needs."""
    parts = ["MEMORY for this session (indexes; open a linked file when it is relevant):",
             f"## preferences — {KNOWLEDGE}/preferences.md", read(f"{KNOWLEDGE}/preferences.md", 3000).strip() or "(empty)"]
    # knowledge/shared/ (lane rules pull's knowledge.d/, docs/extending.md) is written but was
    # never read by anything -- it landed on disk and stayed invisible unless someone wired a
    # pointer to it by hand. Team knowledge is the same "applies to every session, forever" shape
    # as knowledge/preferences.md, so it's read the same automatic way, one section per file
    # (not concatenated) so each file's own name stays visible.
    shared_dir = f"{KNOWLEDGE}/shared"
    if os.path.isdir(shared_dir):
        for f in sorted(os.listdir(shared_dir)):
            if f.endswith(".md"):
                parts += [f"## shared: {f} — {shared_dir}/{f}", read(f"{shared_dir}/{f}", 3000).strip() or "(empty)"]
    parts += [f"## cross-repo — {MEMORY}/MEMORY.md", read(f"{MEMORY}/MEMORY.md", 3000).strip()]
    for r in lane_repo_dirs(lane):
        parts += [f"## {r} — {MEMORY}/{r}/MEMORY.md", read(f"{MEMORY}/{r}/MEMORY.md", 3000).strip() or "(empty)"]
    refs = lane_refs(lane)
    if refs:
        parts.append("## references attached to this lane (read-only unless marked rw) — under lanes/%s/refs/:" % lane)
        head = open(f"{LANES_DIR}/{lane}.md").read().split("\n---\n", 1)[0]
        for m in re.finditer(r"^  - path: (.+)\n((?:    .*\n?)*)", head, re.M):
            d = dict(re.findall(r"    (\w+): (.*)", m.group(2)))
            parts.append(f"  - {d.get('name', os.path.basename(m.group(1)))}  [{d.get('mode','read')}]  {m.group(1)}" + (f"  — {d['note']}" if d.get("note") else ""))
    parts.append(SCOPES)
    parts.append("TO SAVE A MEMORY: never write the file yourself. `lane-memory draft <slug> \"<draft>\"` "
                 "(or `-` and a heredoc), ASK __OWNER__ which scope (recommend one), then `lane-memory file <slug> lane|repo <repo>|cross|pref`. "
                 "The index line is written for you. Findings of this lane are in its spec under ## Findings.")
    return "\n".join(parts)
def rules_brief(lane, repo):
    """The repo's own CLAUDE.md in full plus a list of its rules files, injected the first time a session touches it."""
    root = f"{LANES}/{lane}/{repo}"; out = [f"RULES for {repo} (first touch in this session — they apply to every edit under lanes/{lane}/{repo}/):"]
    for cm in (f"{root}/CLAUDE.md", f"{root}/.claude/CLAUDE.md"):
        if os.path.exists(cm): out += [f"## {os.path.relpath(cm, AD)}", read(cm, 8000).strip()]
    rd = f"{root}/.claude/rules"
    if os.path.isdir(rd):
        out.append(f"## {os.path.relpath(rd, AD)}/ — read the ones that match the files you touch:")
        for f in sorted(os.listdir(rd)):
            if not f.endswith(".md"): continue
            head = read(f"{rd}/{f}", 600)
            m = re.search(r"^description:\s*(.+)$", head, re.M) or re.search(r"^#\s*(.+)$", head, re.M)
            g = re.search(r"^(?:paths|globs):\s*(.+)$", head, re.M)
            out.append(f"  - {f}: {(m.group(1).strip() if m else '')}{('  [applies to: '+g.group(1).strip()+']') if g else ''}")
    if len(out) == 1: out.append("(no CLAUDE.md or rules in this repo)")
    return "\n".join(out)
def repo_of(path, lane):
    if not path or not lane: return None
    rp = os.path.realpath(path); base = os.path.realpath(f"{LANES}/{lane}") + "/"
    if rp.startswith(base):
        seg = rp[len(base):].split("/")[0]
        return seg if os.path.exists(f"{LANES}/{lane}/{seg}/.git") else None
    return None

DEFAULT_PROTECTED = ("main", "master", "develop")
def protected_branches(cwd, cur, cmd):
    """main/master/develop plus this repo's own default_branch/compare_branch from
    registry/repos.yaml (already collected by `lane add`, just never read here before) —
    so a repo whose integration branch is named something else (release, staging, ...)
    gets the same protection without a hardcoded guess. Also unions in `protected_branches:`,
    the list `lane sync` writes from the repo's real GitHub branch protection. Union only:
    never drops the baseline three, only ever adds to them — a repo that has been synced and
    genuinely has nothing else protected on GitHub still keeps main/master/develop and its own
    default_branch/compare_branch, because `protected_branches: []` means "nothing EXTRA", not
    "nothing at all"."""
    names = set(DEFAULT_PROTECTED)
    repo = repo_of(cwd, cur)
    if not repo:
        m = re.search(re.escape(REPOS) + r"/([\w.-]+)", (cwd or "") + " " + cmd)
        repo = m.group(1) if m else None
    if repo:
        try:
            t = read(f"{REGISTRY}/repos.yaml", 20000)
            m = re.search(r"(?:^|\n)  " + re.escape(repo) + r":\n((?:    .*\n)*)", t)
            if m:
                block = m.group(1)
                for field in ("default_branch", "compare_branch"):
                    fm = re.search(rf"^    {field}:\s*(\S+)", block, re.M)
                    if fm: names.add(fm.group(1))
                pm = re.search(r"^    protected_branches:\n((?:      - .*\n)*)", block, re.M)
                if pm:
                    for bm in re.finditer(r"^      - (\S+)", pm.group(1), re.M):
                        names.add(bm.group(1))
        except Exception:
            pass
    return names

# ------------------------------------------------------- project rules: registry/rules.yaml
# Every project has refusals that only make sense there — "the entrypoint applies the migrations",
# "that branch deploys itself on push". They do not belong in this file: it is public, and a
# project's tool names, service names and repo names are not. registry/rules.yaml is per-machine
# and gitignored, and what it can say is deliberately small: a rule adds a refusal on top of the
# built-ins. There is no syntax for granting anything — the only thing the code below can do with
# a rule is call deny(), so a rules file can tighten this guard and never loosen it.
RULES_FILE = f"{REGISTRY}/rules.yaml"
# Every registry/rules.*.yaml file is read and unioned the same way RULES_FILE is — in
# particular registry/rules.shared.yaml, which `lane rules pull` (docs/extending.md) writes with
# rules copied, SHA-pinned, from a shared git repo. There is deliberately no special-casing here:
# a shared-sourced rule goes through the exact same parsing/validation/deny-only enforcement as
# one you typed by hand, so a malformed or broken one is caught by `lane doctor` the same way.

def _unquote(s):
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'": return s[1:-1]
    return s

def _split_out(s, ch):
    """Split on `ch`, ignoring the ones inside quotes — a regex full of punctuation is the norm here."""
    out, buf, q = [], "", ""
    for c in s:
        if q:
            buf += c
            if c == q: q = ""
        elif c in "\"'": q = c; buf += c
        elif c == ch: out.append(buf); buf = ""
        else: buf += c
    out.append(buf)
    return out

def _kv(n, s):
    """`key: value` -> (key, value). value is None for `key:` alone, a dict for a one-line { … }."""
    parts = _split_out(s, ":")
    if len(parts) < 2: raise ValueError(f"line {n}: `{s}` is not `key: value`")
    k, v = parts[0].strip(), ":".join(parts[1:]).strip()
    if not k: raise ValueError(f"line {n}: `{s}` has no key")
    if not v: return k, None
    if v.startswith("{") and v.endswith("}"):
        d = {}
        for piece in _split_out(v[1:-1], ","):
            if not piece.strip(): continue
            pk, pv = _kv(n, piece)
            d[pk] = "" if pv is None else pv
        return k, d
    return k, _unquote(v)

def parse_rules(text):
    """A small YAML subset, on purpose: `rules:` holding a list of maps whose values are scalars,
    one-line flow maps, or a block map indented under the key. Anything else raises ValueError with
    the line number, because a rules file that is half-understood is worse than one that is refused."""
    lines = []
    for n, raw in enumerate(text.splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"): continue
        lines.append((n, len(raw) - len(raw.lstrip()), raw.strip()))
    if not lines: return []
    if lines[0][1] != 0 or lines[0][2] != "rules:":
        raise ValueError(f"line {lines[0][0]}: the file has to start with `rules:` — nothing else is read from it")
    out, cur, blk, blk_at = [], None, None, -1
    for n, ind, s in lines[1:]:
        if ind == 0:
            raise ValueError(f"line {n}: `{s}` — `rules:` is the only top-level key")
        if s.startswith("- "):
            cur, blk = {}, None; out.append(cur)
            k, v = _kv(n, s[2:].strip()); cur[k] = v
            continue
        if cur is None:
            raise ValueError(f"line {n}: `{s}` is not inside a rule — every rule starts with `- id: <name>`")
        if blk is not None and ind > blk_at:
            k, v = _kv(n, s); blk[k] = "" if v is None else v
            continue
        blk = None
        k, v = _kv(n, s)
        if v is None: blk, blk_at = {}, ind; cur[k] = blk
        else: cur[k] = v
    return out

def load_rules():
    """(rules, complaints). A rule that cannot be trusted is never enforced — and never silent:
    the complaint goes to stderr from the hook and is a failure in `lane doctor`. Reads every
    registry/rules.*.yaml file (registry/rules.yaml plus, e.g., registry/rules.shared.yaml) and
    unions them through the identical parse/validate path — no file is trusted any differently."""
    files = sorted(glob.glob(f"{REGISTRY}/rules.*.yaml"))
    if os.path.exists(RULES_FILE) and RULES_FILE not in files:
        files = [RULES_FILE] + files
    good, bad = [], []
    for path in files:
        label = os.path.relpath(path, AD)
        try: text = open(path).read()
        except OSError as e: bad.append(f"{label} cannot be read ({e.__class__.__name__})"); continue
        try: raw = parse_rules(text)
        except ValueError as e: bad.append(f"{label} is malformed — {e}"); continue
        if not isinstance(raw, list): bad.append(f"{label}: `rules:` has to be a list of rules"); continue
        for i, r in enumerate(raw, 1):
            rid = r.get("id") or f"the rule at position {i} in {label}"
            w = r.get("when")
            if not isinstance(w, dict) or not w.get("tool"):
                bad.append(f"{rid}: needs `when: {{ tool: <ToolName>, matches|path: … }}`"); continue
            if not w.get("matches") and not w.get("path"):
                bad.append(f"{rid}: `when` needs either `matches:` (a command pattern) or `path:` (a glob)"); continue
            if w.get("matches") and w.get("path"):
                bad.append(f"{rid}: `matches` and `path` in one rule — write two rules, so each refusal says one thing"); continue
            if not r.get("deny"):
                bad.append(f"{rid}: no `deny:` — a rule has to say, in a sentence, what to do instead"); continue
            if not r.get("ref"):
                bad.append(f"{rid}: no `ref:` — a refusal nobody can check is a refusal that gets routed around. "
                           f"Point it at what it is enforcing (memory/…, docs/…, a runbook)."); continue
            if w.get("matches"):
                try: re.compile(w["matches"])
                except re.error as e: bad.append(f"{rid}: `matches` is not a valid regular expression ({e})"); continue
            r["_file"] = label
            good.append(r)
    # A rule id has to be unique across every rules.*.yaml file (including a shared one `lane
    # rules pull` namespaces): doctor verifies a rule by feeding its `example:` through the guard
    # and checking the refusal names that id, so two rules sharing an id makes that check
    # meaningless — either could be the one that actually fired, or neither, with no way to tell.
    # First occurrence wins and stays enforced; every later duplicate is rejected, loudly.
    seen, unique = {}, []
    for r in good:
        rid = r.get("id")
        if rid and rid in seen:
            bad.append(f"{rid}: this id is used by more than one rule — ids must be unique; "
                       f"the first one loaded stays enforced, this one does not")
            continue
        seen[rid] = True
        unique.append(r)
    return unique, bad

def _path_cands(given, cwd):
    """The forms a `path:` glob may be written against: as typed, absolute, and every tail of the
    absolute path — so `schema/generated/**` matches wherever in a lane the repo is checked out."""
    if not given: return []
    a = abs_of(given, cwd)
    parts = a.strip("/").split("/")
    return [given, given.lstrip("./"), a] + ["/".join(parts[i:]) for i in range(len(parts))]

def rule_hits(rule, tool, ti, segs, cwd):
    w = rule["when"]
    if w["tool"] != tool: return False
    if w.get("matches"):
        # The same normalised segments the built-in command rules are matched against — never a
        # second splitter of our own, or `echo ok && alembic upgrade head` would slip a project
        # rule while the built-ins caught its equivalent.
        pat = re.compile(w["matches"])
        return any(pat.search(s) for s in segs)
    glob = w["path"].strip().rstrip("/")
    pats = [glob] if glob.endswith("*") else [glob, glob + "/**"]
    for key in ("file_path", "notebook_path", "path"):
        for c in _path_cands(ti.get(key) or "", cwd):
            if any(fnmatch.fnmatch(c, p) for p in pats): return True
    return False

def enforce_rules(event, tool, ti, segs, cwd):
    """Runs before the built-ins, because several of them answer `allow` and exit — a project rule
    placed after those would never be reached for the files they cover. It can only ever deny."""
    rules, bad = load_rules()
    if bad:
        print(R.words("lane guard: registry/rules.yaml — these project rules are NOT being enforced:\n  "
              + "\n  ".join(bad) + "\n  The built-in rules are unaffected. Fix them, then `lane doctor`."), file=sys.stderr)
    for r in rules:
        try: hit = rule_hits(r, tool, ti, segs, cwd)
        except Exception as e:
            print(f"lane guard: project rule '{r.get('id','?')}' could not be evaluated "
                  f"({e.__class__.__name__}) and was skipped.", file=sys.stderr); continue
        if hit:
            deny(event, f"{r['deny']}\n  This is a project rule of this control plane ('{r['id']}' in "
                        f"{r.get('_file') or 'registry/rules.yaml'}), not a built-in one. Why: {r['ref']}")

if "--rules" in sys.argv:
    # `lane doctor` asks the guard itself what it loaded, so the doctor and the hook can never
    # disagree about which rules are in force.
    _rs, _bad = load_rules()
    for _b in _bad: print("!! " + _b, file=sys.stderr)
    print(json.dumps(_rs))
    sys.exit(1 if _bad else 0)

MALFORMED_MSG = ("The lane guard could not read this tool call (a field has the wrong type, or the payload is not valid JSON), "
                 "and it refuses what it cannot judge. A normally typed command is not the cause: retry it, and if it keeps "
                 "happening report it -- Claude Code is sending something this guard does not expect.")
try: _raw = sys.stdin.read()
except Exception: sys.exit(0)
try: data = json.loads(_raw)
except Exception:
    if re.search(r'"hook_event_name"\s*:\s*"PreToolUse"', _raw):
        _EVENT = "PreToolUse"; deny("PreToolUse", MALFORMED_MSG)
    sys.exit(0)
if not isinstance(data, dict): sys.exit(0)
event = data.get("hook_event_name")
if not isinstance(event, str): event = ""
_EVENT = event
_cwd = data.get("cwd")
if event == "PreToolUse" and _cwd is not None and (not isinstance(_cwd, str) or "\x00" in _cwd):
    deny(event, MALFORMED_MSG)
cwd = _cwd if isinstance(_cwd, str) and _cwd and "\x00" not in _cwd else os.getcwd()
cur = lane_of(cwd)

# secrets: never read, never edit, never print. Structure is available via `lane-env-keys` and .env.example.
# re.I because most disks are case-insensitive: .ENV, .Env and .env are all the same file.
# This pattern is written in three places (here, scripts/gitstate.sh, scripts/board/server.py); tests/ fails if they differ.
SECRET_FILE = re.compile(r"(^|/)(\.env(\.[\w.-]+)?|id_(rsa|ed25519|ecdsa|dsa)|\.netrc|\.npmrc|\.pgpass|\.git-credentials|\.htpasswd|[^/]*\.(pem|key|p12|pfx|p8|jks|keystore|kdbx)|[^/]*credentials[^/]*\.json|service-account[^/]*\.json|secrets?\.(json|ya?ml|toml))$", re.I)
SAFE_ENV_SUFFIX = re.compile(r"\.(example|sample|template|dist)$", re.I)
def _secret_name(p):
    """The name rule alone, template exemption included. Only the last component decides, so a huge path is cut to its
    tail first: it keeps the regex linear."""
    p = p[-1024:]
    return not SAFE_ENV_SUFFIX.search(p) and bool(SECRET_FILE.search(p))
def is_secret(path, base=None):
    """A secret file, or a path that leads to one. The `.env.example` exemption is applied to each form separately: an
    `.env.example` that is a symlink to `.env` is the secret, not the template."""
    if not path: return False
    p = path.rstrip("/")
    if _secret_name(p): return True
    try: real = os.path.realpath(abs_of(p, base or cwd))
    except (OSError, ValueError): return False
    return real != p and _secret_name(real)

# ----------------------------------------------------------------- brace expansion and variables
_BRACE_CAP = 256
def _brace_split(s):
    """(prefix, [alternatives], suffix) for the first brace group in `s` that bash would expand, else None.
    `${…}` is a parameter expansion, not a brace expansion."""
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if ch == "\\": i += 2; continue
        if ch == "{" and (i == 0 or s[i - 1] != "$"):
            depth, j, commas = 0, i, []
            while j < n:
                if s[j] == "\\": j += 2; continue
                if s[j] == "{": depth += 1
                elif s[j] == "}":
                    depth -= 1
                    if depth == 0: break
                elif s[j] == "," and depth == 1: commas.append(j)
                j += 1
            if j < n and s[j] == "}":
                if commas:
                    parts, prev = [], i + 1
                    for c in commas: parts.append(s[prev:c]); prev = c + 1
                    parts.append(s[prev:j])
                    return s[:i], parts, s[j + 1:]
                body = s[i + 1:j]
                m = re.fullmatch(r"(-?\d+)\.\.(-?\d+)", body)
                if m:
                    a, b = int(m.group(1)), int(m.group(2))
                    if abs(b - a) > _BRACE_CAP: LIMIT.append("a brace range that expands past the reader's cap"); return s[:i], [str(a)], s[j + 1:]
                    return s[:i], [str(k) for k in (range(a, b + 1) if a <= b else range(a, b - 1, -1))], s[j + 1:]
                m = re.fullmatch(r"([A-Za-z])\.\.([A-Za-z])", body)
                if m:
                    a, b = ord(m.group(1)), ord(m.group(2))
                    return s[:i], [chr(k) for k in (range(a, b + 1) if a <= b else range(a, b - 1, -1))], s[j + 1:]
            i += 1; continue
        i += 1
    return None

def expand_braces(s):
    """What bash's brace expansion turns one word into (`.{env,x}` -> `.env` `.x`). Past the cap the expansion is refused:
    nobody writes 256 variants of a name for a good reason, and a cap that silently stopped would be a way around the rule."""
    if "{" not in s: return [s]
    sp = _brace_split(s)
    if sp is None: return [s]
    pre, parts, post = sp
    out = []
    for p in parts:
        for e in expand_braces(pre + p + post):
            out.append(e)
            if len(out) > _BRACE_CAP:
                LIMIT.append("a brace expansion that grows past the reader's cap")
                return out[:_BRACE_CAP]
    return out

VARS = {}
def subst_vars(s):
    """`b=main; git push origin $b`: a variable assigned earlier in the same command is read back, so it cannot hide a branch
    name or a file name. Values may refer to other variables (`a=.en; b=${a}v`), so it repeats until nothing changes."""
    if "$" not in s or not VARS: return s
    for _ in range(4):
        t = _VAR_REF.sub(lambda m: VARS.get(m.group(2) or m.group(3), m.group(0)), s)
        if t == s: break
        s = t
    return s
_VAR_REF = re.compile(r"\$(\{(\w+)\}|(\w+))")

def glob_names_secret(g):
    """Does a glob aim at secret files? `*.pem`, `**/.env*`, `.e*`, `{*.js,.env}`, `secrets*`, `*credentials*` all do. A
    pattern that does not start with a dot cannot match `.env` in a shell, but a ripgrep glob can, so a literal part that says
    "secret" counts. `*.json` and `*.js` do not: they name no secret. A leading `!` excludes, so it names nothing."""
    for form in expand_braces(g[:4096]):
        for piece in form.split():
            if not piece or piece.startswith("!"): continue
            base = piece.rsplit("/", 1)[-1]
            if _secret_name(base.replace("*", "")) or _secret_name(base.replace("*", ".x")): return True
            for comp in piece.split("/"):
                if comp.startswith(".") and any(fnmatch.fnmatchcase(n, comp) for n in (".env", ".env.local")): return True
            if _GLOB_HINT.search(base) and any(fnmatch.fnmatchcase(smp.lower(), base.lower()) for smp in _SECRET_SAMPLES): return True
    return False
_GLOB_HINT = re.compile(r"env|secret|credential|id_|netrc|npmrc|pgpass|htpasswd|service-account|\.(pem|key|p12|pfx|p8|jks|keystore|kdbx)", re.I)
_SECRET_SAMPLES = (".env", ".env.local", ".env.production", "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa", ".netrc", ".npmrc", ".pgpass",
                   ".git-credentials", ".htpasswd", "server.pem", "server.key", "a.p12", "a.pfx", "a.p8", "a.jks", "a.keystore", "a.kdbx",
                   "credentials.json", "aws-credentials.json", "service-account.json", "service-account-prod.json",
                   "secrets.json", "secret.json", "secrets.yaml", "secrets.yml", "secrets.toml")
def secret_globs(word):
    """Secret-looking glob components in one shell word: `cat .e*` and `cat *.pem` read the file the wildcard hides. Runs of
    `*` are collapsed (a hundred of them match what one does). A component longer than any file name can only match one if
    it is mostly wildcards, and that is refused rather than judged: a length cut that waved it through would be the way around."""
    if not any(ch in word for ch in "*?["): return []
    out = []
    for c in word.split("/"):
        if not any(ch in c for ch in "*?["): continue
        c = re.sub(r"\*{2,}", "*", c)
        if len(c) > 255:
            if sum(1 for ch in c if ch not in "*?[]") > 255: continue
            LIMIT.append("a glob component longer than any file name that is mostly wildcards")
            continue
        if glob_names_secret(c): out.append(c)
    return out
# Commands allowed to name a secret file: they reveal nothing and cannot move it somewhere
# unguarded. Copying and linking are deliberately NOT here — `cp .env /tmp/x && cat /tmp/x`
# is the whole attack (the one exception, copying a template onto its working name, is cp_template_ok()). The lane-* scripts
# that set worktrees up are exempt elsewhere. The command word must be exactly one of these (not merely start with it:
# `ls-evil`, `stat.sh`).
SECRET_SAFE_CMDS = {"lane-env-keys", "lane-env-check", "ls", "stat", "test", "[", "wc", "file", "touch", "mkdir", "rm", "chmod", "chown",
                    "basename", "dirname", "readlink", "realpath", "find"}
def secret_safe_stmt(st):
    """A statement that names a secret is let through only if its command is on the list AND no option turns it into a
    reader: `file -f FILE` and `wc --files0-from=FILE` read file NAMES from the secret, `find -exec` runs anything."""
    w = st.words
    if not w: return False
    if w[0] not in SECRET_SAFE_CMDS: return git_names_only(st)
    a = w[1:]
    if w[0] == "file" and any(x.startswith("--files") or re.match(r"-[A-Za-z]*f", x) for x in a): return False
    if w[0] == "wc" and any(x.startswith("--files") for x in a): return False
    if w[0] == "find" and any(x.startswith(("-exec", "-ok")) for x in a): return False
    return True
def git_names_only(st):
    """`git rm --cached .env`, `git check-ignore .env`, `git ls-files .env`: they take a secret's name and never open it."""
    w = st.words
    if not w or w[0] != "git": return False
    calls = list(git_calls([st]))
    if len(calls) != 1: return False
    g = calls[0]
    if g.i != 0 or g.cfg or g.sub not in ("check-ignore", "ls-files", "rm"): return False
    if g.sub == "rm": return "--cached" in g.args
    return not any(a in ("-z", "--stdin") or a.startswith("--stdin") for a in g.args if g.sub == "check-ignore")

def cp_template_ok(st, cur_lane):
    """`cp .env.example .env`, the first step of every project's README. Allowed ONLY when the source is a template by name AND
    by where it leads (a `.env.example` that is a link to `.env` is the secret) and the copy lands inside this lane. A copy
    of a real secret, or a template copied out of the lane, is still refused."""
    w = st.words
    if not cur_lane or not w or os.path.basename(w[0]) != "cp" or st.redirs: return False
    args = w[1:]
    if any(not re.fullmatch(r"-[nipv]+", a) for a in args if a.startswith("-")): return False
    pos = [a for a in args if not a.startswith("-")]
    if len(pos) != 2: return False
    src, dst = pos
    if not SAFE_ENV_SUFFIX.search(src) or is_secret(src, bases_of(st)[0]) or "$" in dst or "`" in dst: return False
    lane_root = os.path.realpath(f"{LANES}/{cur_lane}")
    d = os.path.realpath(abs_of(dst, bases_of(st)[0]))
    return d == lane_root or d.startswith(lane_root + "/")

_RUN = re.compile(r"[\w./~-]+")
_SECRET_HINT = re.compile(r"\.env|credentials|\.(?:pem|p12|pfx|p8|jks|keystore|kdbx|key)|secrets?\.|id_(?:rsa|ed25519|ecdsa|dsa)|\.netrc|\.npmrc|\.pgpass|\.htpasswd|service-account", re.I)
_CRED = re.compile(r"credentials[\w.-]*\.json(?![\w-])", re.I)
_SVC = re.compile(r"service-account[\w.-]*\.json(?![\w-])", re.I)
_DOTCRED = re.compile(r"\.(?:netrc|npmrc|pgpass|git-credentials|htpasswd)", re.I)
_KEYFILE = re.compile(r"[\w.-]+\.(?:pem|p12|pfx|p8|jks|keystore|kdbx|key)|id_(?:rsa|ed25519|ecdsa|dsa)", re.I)
_SECRETS_NAME = re.compile(r"secrets?\.(?:json|ya?ml|toml)", re.I)
def secret_tokens(text, base):
    """Secret-looking path tokens inside one shell word (a word may be a whole `python -c "…"` program). Works on runs of
    path characters and their components, so its cost is linear however long the word is. A key/cert file only counts as
    a standalone token (`server.key`, not `e.key;` in some JavaScript); a `.env.example` counts only if it leads to a secret."""
    found = []; resolved = 0
    for m in _RUN.finditer(text):
        run = m.group(0)
        if len(run) > 4096: run = run[-4096:]
        if not _SECRET_HINT.search(run): continue
        prev = text[m.start() - 1] if m.start() else ""
        nxt = text[m.end()] if m.end() < len(text) else ""
        comps = run.split("/")
        for k, c in enumerate(comps):
            if not c or len(c) > 255: continue
            lc = c.lower()
            if lc == ".env" or lc.startswith(".env."): kind = "env"
            elif _DOTCRED.fullmatch(lc): kind = "dotcred"
            elif _CRED.search(c) or _SVC.search(c): kind = "cred"
            elif _SECRETS_NAME.fullmatch(c): kind = "secrets"
            elif k == len(comps) - 1 and prev in ("", " ", "\t", "\n", "'", '"', "=") and nxt in ("", " ", "\t", "\n", "'", '"') and _KEYFILE.fullmatch(c): kind = "key"
            else: continue
            tok = "/".join(comps[:k + 1])
            if SAFE_ENV_SUFFIX.search(c):
                resolved += 1
                if resolved > 64 or not is_secret(tok, base): continue
            found.append(tok)
    return found

SECRET_MSG = ("Secret file. Claude never reads .env/credential files here, even with permission — the read itself is the problem. "
              "For structure use `lane-env-keys <path>` (names only) or .env.example; for behaviour, run the app and read its output.")

WRITE_SECRET_MSG = ("Secret file. This is a write, not a read, and Claude does not create or edit .env/credential files here: their values are "
                    "__OWNER__'s. To start a local env file, copy the template (`cp .env.example .env` is allowed inside a lane) and ask "
                    "__OWNER__ to fill in the values; `lane-env-keys <path>` lists the variable names of an existing one.")
_INPLACE = re.compile(r"-[A-Za-z0-9]*i|--in-place")
def secret_write_only(st, toks):
    """True if every secret named by this statement is only being WRITTEN or created (a redirect target, `tee`, `cp x .env`,
    `sed -i`), never read: the denial then says so, instead of talking about reads."""
    if not toks: return False
    w = st.words; ci = cmd_index(w)
    if ci >= len(w): return False
    cmd = os.path.basename(w[ci]); data = data_of(st); b = bases_of(st)[0]
    named = lambda x: bool(secret_tokens(x, b) or secret_globs(x))
    if any(named(x) for x in st.inredirs): return False
    outs = [x for x in st.redirs if x not in st.inredirs]
    pos = [k for k in range(ci + 1, len(w)) if k not in data and not w[k].startswith("-")]
    for k, x in forms_of(st):
        if k in data or k <= ci or not named(x): continue
        if cmd in ("tee", "truncate", "shred"): continue
        if cmd in ("cp", "mv", "ln", "install", "rsync", "scp") and pos and k == pos[-1] and len(pos) > 1: continue
        if cmd == "dd" and x.startswith("of="): continue
        if cmd in ("sed", "perl", "ruby") and any(_INPLACE.fullmatch(y) for y in w[ci + 1:] if y.startswith("-")): continue   # the file edited in place
        return False
    return any(named(x) for x in outs) or any(named(x) for k, x in forms_of(st) if k not in data and k > ci)

def lane_refs(lane):
    """[(realpath, mode)] from the lane frontmatter refs: list."""
    f = f"{LANES_DIR}/{lane}.md"
    try: head = open(f).read().split("\n---\n", 1)[0]
    except Exception: return []
    out = []
    for m in re.finditer(r"^  - path: (.+)\n((?:    .*\n?)*)", head, re.M):
        mode = re.search(r"^    mode: (\w+)", m.group(2), re.M)
        out.append((os.path.realpath(os.path.expanduser(m.group(1))), mode.group(1) if mode else "read"))
    return out
def ref_name(lane, real):
    """The name a reference is registered under, so messages match what lane-ref expects."""
    f = f"{LANES_DIR}/{lane}.md"
    try: head = open(f).read().split("\n---\n", 1)[0]
    except Exception: return os.path.basename(real)
    for m in re.finditer(r"^  - path: (.+)\n((?:    .*\n?)*)", head, re.M):
        if os.path.realpath(os.path.expanduser(m.group(1))) == real:
            d = dict(re.findall(r"    (\w+): (.*)", m.group(2)))
            return d.get("name", os.path.basename(real))
    return os.path.basename(real)

def ref_mode(path, lane):
    if not path or not lane: return None
    rp = os.path.realpath(path)
    for r, mode in lane_refs(lane):
        if rp == r or rp.startswith(r + "/"): return mode
    return None

def old_paths():
    ps = set()
    try:
        for k in json.load(open(f"{REGISTRY}/old-checkouts.json")): ps.add(os.path.realpath(k))
    except Exception: pass
    ps.add(os.path.expanduser("~/.cursor/worktrees"))
    ps.add(os.path.dirname(AD) + "/clones")
    return sorted(ps, key=len, reverse=True)
OLD = old_paths()
def in_old(path):
    if not path: return None
    rp = os.path.realpath(path)
    for o in OLD:
        if rp == o or rp.startswith(o + "/"): return o
    return None
def cmd_mentions_old(cmd):
    for o in OLD:
        short = o.replace(os.path.expanduser("~"), "~")
        if o in cmd or short in cmd: return o
    return None
FROZEN_MSG = ("Frozen copy from before the migration. It is not part of the work any more. Use the worktree under "
              f"{AD}/lanes/ (state: lane-brief). Never read, compare or quote the old checkouts.")

REACH_MSG = ("lanes/{lane}/ belongs to a lane you have not entered. Reaching into it from here is how the "
             "dispatcher ends up editing code it has no scope for.\n"
             "  work on it:   EnterWorktree name=\"{lane}\"\n"
             "  look at it:   `lane-brief {lane}`, `lane-status`, or the board — they read it for you\n"
             "  the lane's own file (registry/lanes/{lane}.md) is editable from here.")

STAY_MSG = ("You are inside lane '{cur}'. The work stays here; do not create or enter another worktree from a worktree. "
            "Need a repo added to THIS work? `lane-with {cur} <repo>`. Is it genuinely separate work __OWNER__ asked for? Then: "
            "`lane-park {cur} \"<note>\"`, ExitWorktree keep, and start it from the root — after they confirm.")

# Memory, preferences and the control plane are never written directly: scope is __OWNER__'s call.
def _scopes():
    """The table every memory refusal and the memory brief show, with the paths where this plane keeps them."""
    rows = [("preference", f"{R.rel(KNOWLEDGE)}/preferences.md", "forever, all work", '"how should Claude work with me?"'),
            ("cross-repo", f"{R.rel(MEMORY)}/<slug>.md", "forever, any repo", '"true in every repo?"'),
            ("repo", f"{R.rel(MEMORY)}/<repo>/<slug>.md", "forever, that repo", '"still true after this ticket ships?"'),
            ("lane", f"{R.rel(LANES_DIR)}/<id>.md", "until it finishes", '"only matters while this work is live?"'),
            ("", "(its ## Findings section)", "", "  then archived with the lane")]
    w = max(len(r[1]) for r in rows) + 4
    return "MEMORY SCOPES — where a thing belongs is decided by how long it stays true:\n" + "\n".join(
        (f"  {a:<12} {b:<{w}}{c:<21}{d}").rstrip() for a, b, c, d in rows)
SCOPES = _scopes()
MEMORY_GATE = (
    "Memories are not written directly — the scope is __OWNER__'s decision.\n" + SCOPES + "\n"
    "Do this instead:\n"
    "  1. lane-memory draft <slug> \"<draft>\"   (or `-` and a heredoc; do not use Edit/Write, a worktree session cannot)\n"
    "  2. ASK __OWNER__ in one line: what it says, and which of the four scopes it is. Recommend one, using the\n"
    "     survival test: does it stay true after this ticket ships? after leaving this repo?\n"
    "  3. lane-memory file <slug> lane | repo <repo> | cross | pref     (files it and writes the index line)")
PLANE_GATE = ("This is the control plane ({what}). Changing it from inside a lane is how the system "
              "drifts. Propose the change to __OWNER__ and make it from a dispatcher session at the control plane root.")

# ------------------------------------------------------------ reading a shell command
# Every Bash rule below works on words, not on regular expressions over the raw line. A regex over
# the whole command was both bypassable (`main;`, `'main'`, `$(cat .env)`, `\cd`) and quadratic in
# the length of the command. This reader is one linear pass: quotes (including $'…' and $"…") are
# removed, `;` `&` `|` and newlines end a statement, `$( )`, backticks and `( )` are statements of
# their own, redirect targets are kept apart from the arguments, and a heredoc body is DATA for the
# command that receives it (cat, git commit -F -) unless that command is a shell or an interpreter, in
# which case it is code and is read as code; only the `$( )` an unquoted body contains are statements.
_SCOPES = itertools.count(1)
SCOPE_PARENT = {}                  # scope id -> the scope it was opened in; a cd in a scope never leaves it
FUNCS = []                         # a shell function was defined: a cd inside may run any number of times
def new_scope(parent):
    s = next(_SCOPES); SCOPE_PARENT[s] = parent
    return s

class Stmt:
    __slots__ = ("words", "redirs", "inredirs", "sub", "scope", "sep", "pipe_src", "pipe_to", "heredocs", "herestr", "procsubs",
                 "cwds", "cds", "forms", "rforms", "dataidx", "cdkind")
    def __init__(self, sub=False, scope=0):
        self.words, self.redirs, self.inredirs = [], [], []
        self.sub, self.scope, self.sep = sub, scope, ";"
        self.pipe_src = self.pipe_to = None
        self.heredocs, self.herestr, self.procsubs = [], [], []
        self.cwds, self.cds, self.forms, self.rforms, self.dataidx, self.cdkind = None, [], None, None, None, None

_PLAIN = re.compile(r"[\w./=:@%+,~{}\[\]*?!^-]+")      # characters that cannot start anything special
_DQ = re.compile(r'[^"\\$`]+')
_ASSIGN = re.compile(r"[A-Za-z_]\w*\+?=")
_WS = " \t\r\f\v"
_ANSI = {"a": "\a", "b": "\b", "e": "\x1b", "E": "\x1b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v", "\\": "\\", "'": "'", '"': '"', "?": "?"}
_HEX2, _OCT3 = re.compile(r"[0-9a-fA-F]{1,2}"), re.compile(r"[0-7]{1,3}")
_MAX_GROUP_DEPTH = 100

def shell_stmts(src, sub=False, depth=0, mode="sh", pscope=None, scope=None):
    """mode "dq" reads `src` as the inside of a double-quoted string (an unquoted heredoc body): only its command
    substitutions come back. `scope` makes the result share a scope with its caller (eval); otherwise a new scope
    that inherits the caller's cwd (bash -c, a subshell)."""
    out = []
    n = len(src)
    root = scope if scope is not None else new_scope(pscope)
    if depth > 6:
        LIMIT.append("commands nested more than 6 levels deep"); return out

    def ansi_c(i):
        """The value of an ANSI-C string whose body starts at i, and the index after its closing quote; None if unterminated."""
        res = []
        while i < n:
            ch = src[i]
            if ch == "'": return "".join(res), i + 1
            if ch == "\\" and i + 1 < n:
                e = src[i + 1]
                if e in _ANSI: res.append(_ANSI[e]); i += 2
                elif e == "x":
                    m = _HEX2.match(src, i + 2)
                    if m: res.append(chr(int(m.group(0), 16))); i = m.end()
                    else: res.append("\\x"); i += 2
                elif e in "01234567":
                    m = _OCT3.match(src, i + 1); res.append(chr(int(m.group(0), 8) & 0xFF)); i = m.end()
                elif e in "uU":
                    m = re.compile(r"[0-9a-fA-F]{1,%d}" % (4 if e == "u" else 8)).match(src, i + 2)
                    if m:
                        v = int(m.group(0), 16); res.append(chr(v) if v <= 0x10FFFF else "?"); i = m.end()
                    else: res.append("\\" + e); i += 2
                elif e == "c" and i + 2 < n: res.append(chr(ord(src[i + 2]) & 0x1F)); i += 3
                else: res.append("\\" + e); i += 2          # bash keeps the backslash of an escape it does not know
                continue
            res.append(ch); i += 1
        return None

    def group(i, closer, buf, scope, mark, gd):
        """A `$( )`, backtick or `( )` group starting at i: its statements join `out`; `buf` gets a marker for its value."""
        k0 = len(out)
        j = parse(i, closer, True, new_scope(scope), gd + 1)
        inner = out[k0:]
        if mark in ("$()", "``") and len(inner) == 1 and not inner[0].redirs:
            iw = inner[0].words
            if iw == ["pwd"]: mark = "$PWD"                                   # the simulated cwd, not an unknown
            elif iw == ["git", "rev-parse", "--show-toplevel"]: mark = "$GITTOP"
            else:
                lo = literal_out(inner[0])                                     # `cat $(echo .env)`: what echo/printf print is the word
                if lo is not None and "$()" not in lo and "``" not in lo: mark = lo.rstrip("\n")
        buf.append(mark)
        return j

    def dq_scan(i, buf, term, scope, gd):
        esc = '"\\$`' if term else '\\$`'            # a heredoc body is not delimited by quotes, and `\"` stays as it is
        while i < n:
            d = src[i]
            if term and d == term: return i + 1
            m = _DQ.match(src, i)
            if m: buf.append(m.group(0)); i = m.end(); continue
            if d == "\\" and i + 1 < n:
                e = src[i + 1]
                if e != "\n": buf.append(e if e in esc else d + e)
                i += 2; continue
            if d == "$" and src.startswith("$(", i): i = group(i + 2, ")", buf, scope, "$()", gd); continue
            if d == "`": i = group(i + 1, "`", buf, scope, "``", gd); continue
            buf.append(d); i += 1
        return i

    def parse(i, closer, sub, scope, gd=0):
        st = Stmt(sub, scope); buf = []; inword = False; wq = False; pend = None; heredocs = []
        seps = [";"]; prev = [None]
        if gd > _MAX_GROUP_DEPTH:
            LIMIT.append("groups nested more than %d levels deep" % _MAX_GROUP_DEPTH); return n
        def end_word():
            nonlocal buf, inword, wq, pend
            if not inword: return
            w = "".join(buf); q = wq; buf = []; inword = False; wq = False
            if pend is None: st.words.append(w)
            elif pend[0] == "heredoc": heredocs.append((w, pend[1], q, st)); pend = None
            elif pend[0] == "here": st.herestr.append(w); pend = None
            elif pend[0] == "dup":
                pend = None
                if not (w.isdigit() or w == "-"): st.redirs.append(w)
            elif pend[0] == "skip": pend = None
            elif pend[0] == "in": st.redirs.append(w); st.inredirs.append(w); pend = None
            else: st.redirs.append(w); pend = None
        def flush():
            nonlocal st, pend
            end_word(); pend = None
            if st.words or st.redirs or st.herestr or st.heredocs:
                st.sep = seps[0]; seps[0] = ";"
                if st.sep == "|" and prev[0] is not None: st.pipe_src = prev[0]; prev[0].pipe_to = st
                prev[0] = st; out.append(st)
                st = Stmt(sub, scope)
        while i < n:
            c = src[i]
            m = _PLAIN.match(src, i)
            if m: buf.append(m.group(0)); inword = True; i = m.end(); continue
            if c in _WS: end_word(); i += 1; continue
            if c == "\n":
                flush(); i += 1
                while heredocs:
                    delim, strip, quoted, owner = heredocs.pop(0)
                    lines = []
                    while i < n:
                        j = src.find("\n", i); line = src[i:j if j >= 0 else n]; i = j + 1 if j >= 0 else n
                        if strip: line = line.lstrip("\t")
                        if line == delim: break
                        lines.append(line)
                    body = "\n".join(lines)
                    owner.heredocs.append((body, quoted))
                    if not quoted: out.extend(shell_stmts(body, True, depth + 1, "dq", scope))
                continue
            if c == "\\":
                if i + 1 < n and src[i + 1] != "\n": buf.append(src[i + 1]); inword = True; wq = True
                i += 2; continue
            if c == "'":
                inword = True; wq = True; j = src.find("'", i + 1)
                if j < 0: buf.append(src[i + 1:]); i = n
                else: buf.append(src[i + 1:j]); i = j + 1
                continue
            if c == '"':
                inword = True; wq = True; i = dq_scan(i + 1, buf, '"', scope, gd); continue
            if c == "$":
                nx = src[i + 1:i + 2]
                if nx == "'":
                    r = ansi_c(i + 2)
                    if r is None:
                        LIMIT.append("an unterminated $'…' string"); i = n; continue
                    buf.append(r[0]); inword = True; wq = True; i = r[1]; continue
                if nx == '"': i += 1; continue                      # $"…" is a double-quoted string
                if nx == "(": i = group(i + 2, ")", buf, scope, "$()", gd); inword = True; continue
            if c == "`":
                if closer == "`": flush(); return i + 1
                i = group(i + 1, "`", buf, scope, "``", gd); inword = True; continue
            if c == "(":
                end_word(); flush(); k0 = len(out); i = group(i + 1, ")", [], scope, "()", gd)
                if len(out) == k0: FUNCS.append(1)                # `name() { … }`: an empty group right after a word
                continue
            if c == ")":
                flush()
                if closer == ")": return i + 1
                i += 1; continue
            if c in "<>" and src.startswith("(", i + 1):
                k0 = len(out); i = parse(i + 2, ")", True, new_scope(scope), gd + 1)
                st.procsubs.append(out[k0:]); buf.append("<()"); inword = True; continue
            if c in "<>":
                if inword and "".join(buf).isdigit(): buf = []; inword = False; wq = False       # the fd in `2>`
                else: end_word()
                if src.startswith("<<<", i): pend = ("here",); i += 3; continue
                if src.startswith("<<", i):
                    i += 2; strip = src.startswith("-", i)
                    if strip: i += 1
                    pend = ("heredoc", strip); continue
                i += 1
                if i < n and src[i] == "&": i += 1; pend = ("dup",)
                elif i < n and src[i] in ">|" and (c == ">" or src[i] == ">"): i += 1; pend = ("file",)
                else: pend = ("file",) if c == ">" else ("in",)
                continue
            if c == "&" and src.startswith("&>", i):
                end_word(); i += 2
                if src.startswith(">", i): i += 1
                pend = ("file",); continue
            if c in ";&|":
                flush(); i += 1; kind = c
                if i < n and src[i] in "&|" and c in "&|": kind = c + src[i]; i += 1
                seps[0] = "|" if kind in ("|", "|&") else kind
                continue
            if c == "#" and not inword:
                j = src.find("\n", i); i = n if j < 0 else j; continue
            buf.append(c); inword = True; i += 1
        flush()
        return n

    if mode == "dq":
        dq_scan(0, [], None, root, 0)
        return out
    parse(0, "", sub, root)
    return out

SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "ksh93", "mksh", "pdksh", "oksh", "posh", "ash", "yash", "rbash", "rzsh", "fish", "csh", "tcsh", "elvish", "nu", "xonsh"}
INTERPS = [  # (name pattern, option that carries the program text)
    (re.compile(r"python[\d.]*|pypy[\d.]*"), re.compile(r"-[A-Za-z]*c")),
    (re.compile(r"perl[\d.]*|ruby[\d.]*"), re.compile(r"-[A-Za-z0-9]*[eE]")),
    (re.compile(r"node(js)?|bun|deno"), re.compile(r"-e|-p|-pe|--eval|--print|eval")),
    (re.compile(r"php[\d.]*"), re.compile(r"-r")),
    (re.compile(r"lua[\d.]*|luajit|Rscript|osascript|groovy|tclsh|jshell|ts-node|tsx"), re.compile(r"-e")),
]
_INTERP_VAL_OPTS = {"-W", "-X", "-I", "-r", "--require", "--loader", "--import", "-C", "-M"}
PREFIX_WORDS = {"sudo", "doas", "command", "builtin", "exec", "time", "nohup", "nice", "ionice", "env", "!", "{", "then", "do", "else", "elif",
                "if", "while", "until"}
_PREFIX_VAL_OPTS = {"sudo": {"-u", "-g", "-h", "-p", "-C", "-D", "-R", "-T", "-U", "-r", "-t"}, "doas": {"-u", "-C"}, "nice": {"-n"}, "ionice": {"-n", "-c", "-p"},
                    "exec": {"-a"}, "time": {"-f", "-o"}, "command": set(), "builtin": set(), "nohup": set()}
WRAPPERS = {"timeout", "xargs", "busybox", "setsid", "stdbuf", "chroot", "taskset", "unshare", "flock", "watch", "strace", "ltrace", "parallel",
            "su", "runuser", "script", "nsenter", "chrt", "unbuffer", "entr", "caffeinate", "sandbox-exec", "firejail", "proot"}
def cmd_index(w):
    """Where the command itself is: past `VAR=x`, `env`, `sudo -u x`, `builtin`, `{`, `then` and the like."""
    i = 0
    while i < len(w):
        x = w[i]
        if x == "function" and i + 1 < len(w): i += 2; continue          # `function up { cd ..; }`: the body starts after the name
        if _ASSIGN.match(x) or x in PREFIX_WORDS:
            i += 1
            if x == "env":
                while i < len(w) and w[i].startswith("-"): i += 2 if w[i] in ("-u", "-C", "-S", "--chdir", "--unset", "--split-string") else 1
            elif x in _PREFIX_VAL_OPTS:
                vals = _PREFIX_VAL_OPTS[x]
                while i < len(w) and w[i].startswith("-") and len(w[i]) > 1: i += 2 if w[i] in vals else 1
            continue
        break
    return i

def env_chdir(w, ci):
    """The directory `env -C dir cmd` / `env --chdir=dir cmd` runs its command in, else None."""
    for k in range(min(ci, len(w))):
        if w[k] != "env": continue
        j = k + 1
        while j < ci and w[j].startswith("-"):
            if w[j] in ("-C", "--chdir") and j + 1 < len(w): return w[j + 1]
            if w[j].startswith("--chdir="): return w[j][8:]
            if w[j].startswith("-C") and len(w[j]) > 2 and not w[j].startswith("--"): return w[j][2:]
            j += 2 if w[j] in ("-u", "-S", "--unset", "--split-string") else 1
    return None

def cmd_positions(st):
    """Indexes in st.words where a program is run: the command itself, and what a wrapper (timeout, xargs, busybox,
    `find -exec`) hands the rest of its line to. Words that merely sit among a command's arguments are not."""
    w = st.words; ci = cmd_index(w)
    if ci >= len(w): return []
    pos = [ci]; b = os.path.basename(w[ci])
    if b in WRAPPERS: pos += range(ci + 1, len(w))
    elif b == "find":
        for k, x in enumerate(w):
            if x in ("-exec", "-execdir", "-ok", "-okdir"):
                j = k + 1
                while j < len(w) and w[j] not in (";", "+"): pos.append(j); j += 1
    return pos

# --- which words are data
GREPS = {"grep", "egrep", "fgrep", "zgrep", "rg", "ag", "ack", "pcregrep"}
_GREP_VAL = {"-e", "-f", "-m", "-A", "-B", "-C", "-d", "-D", "-g", "-t", "-T", "-j", "-M", "--regexp", "--file", "--max-count", "--context", "--after-context",
             "--before-context", "--directories", "--devices", "--include", "--exclude", "--exclude-dir", "--exclude-from", "--include-dir", "--glob", "--iglob", "--type", "--type-not",
             "--threads", "--max-columns", "--label", "--binary-files", "--color", "--colour", "--group-separator", "--max-depth", "--ignore-file", "--pre", "--path-separator"}
FILTER_OPTS = {c: {"--exclude", "--include", "--exclude-dir", "--include-dir", "-g", "--glob", "--iglob", "--ignore"} for c in GREPS}
FILTER_OPTS.update({"find": {"-name", "-iname", "-path", "-ipath", "-wholename", "-iwholename", "-regex", "-iregex"}, "tar": {"--exclude"}, "rsync": {"--exclude", "--include"},
                    "zip": {"-x", "-i", "--exclude"}, "diff": {"-x", "--exclude"}, "colordiff": {"-x", "--exclude"}})
_GH_DATA = {"--body", "-b", "--title", "-t", "--notes", "-n", "--message", "-m", "--subject", "--description", "--comment", "--reason", "--notes-start-tag", "--discussion-category"}
_GIT_MSG_SUBS = {"commit", "tag", "notes", "merge", "revert", "cherry-pick", "stash", "pull", "am", "rebase", "branch"}      # -m "text"
_GIT_SEARCH_SUBS = {"log", "grep", "shortlog", "for-each-ref", "rev-list", "diff", "show"}                                  # --grep=text, -S text
_GIT_MSG_FLAGS = {"-m", "--message", "--reason"}
_GIT_SEARCH_FLAGS = {"--grep", "--author", "--committer", "-S", "-G", "-e", "--format", "--pretty", "--since", "--until", "--after", "--before"}
def data_of(st):
    """Indexes of the words that are text, not paths: what echo/printf print, a commit message, a gh --body, a grep PATTERN.
    A file name inside one of them is a mention; it is not read. Redirects, `-F file`, `--body-file` and every path
    argument stay judged."""
    if st.dataidx is not None: return st.dataidx
    w = st.words; idx = set(); st.dataidx = idx
    ci = cmd_index(w)
    if ci >= len(w) and all(_ASSIGN.match(x) for x in w): idx.update(range(len(w))); return idx   # `f=.env`, `msg="fix .env"`: setting a variable reads nothing (its use is judged)
    if ci >= len(w): return idx
    cmd = os.path.basename(w[ci])
    if cmd in ("echo", "printf"): idx.update(range(ci + 1, len(w))); return idx
    if cmd in GREPS:
        have = False; k = ci + 1; dd = False
        while k < len(w):
            x = w[k]
            if dd or not x.startswith("-") or x == "-":
                if not have: idx.add(k); have = True
            elif x == "--": dd = True
            elif x in ("-e", "--regexp") and k + 1 < len(w): idx.add(k + 1); have = True; k += 1
            elif x.startswith("--regexp=") or (x.startswith("-e") and len(x) > 2 and not x.startswith("--")): idx.add(k); have = True
            elif x in ("-f", "--file"): have = True; k += 1
            elif x.startswith("--file=") or (x.startswith("-f") and len(x) > 2 and not x.startswith("--")): have = True
            elif x in _GREP_VAL: k += 1
            k += 1
    ghs = [k for k, x in enumerate(w) if k >= ci and os.path.basename(x) in ("gh", "lane-gh")]
    for n_, k in enumerate(ghs):
        for j in range(k + 1, ghs[n_ + 1] if n_ + 1 < len(ghs) else len(w)):
            y = w[j]
            if y in _GH_DATA and j + 1 < len(w): idx.add(j + 1)
            elif y.startswith("--") and "=" in y and y.split("=", 1)[0] in _GH_DATA: idx.add(j)
            elif re.fullmatch(r"-[bm].+", y): idx.add(j)
    # The value of a filter option is a pattern, not a file: `--exclude='.env*'`, `find ! -name .env`, `rg -g '!id_rsa'`. Naming the secret there
    # is how a tool is told to leave it alone (and tree_refusal reads these same values to see whether it does).
    ft = FILTER_OPTS.get(cmd)
    if ft:
        for j, y in enumerate(w):
            if j <= ci: continue
            if y in ft and j + 1 < len(w): idx.add(j + 1)
            elif y.startswith("--") and "=" in y and y.split("=", 1)[0] in ft: idx.add(j)
    for g in git_calls([st]):
        if g.sub in _GIT_MSG_SUBS: flags, short = _GIT_MSG_FLAGS, "m"
        elif g.sub in _GIT_SEARCH_SUBS: flags, short = _GIT_SEARCH_FLAGS, "SG"
        else: continue
        a = g.st.words; base = g.j + 1
        for off, y in enumerate(g.args):
            j = base + off
            if y in flags and j + 1 < len(a): idx.add(j + 1)
            elif y.startswith("--") and "=" in y and y.split("=", 1)[0] in flags: idx.add(j)
            elif re.fullmatch(r"-[%s].+" % short, y): idx.add(j)
            elif g.sub in _GIT_MSG_SUBS and re.fullmatch(r"-[A-Za-z]+m", y) and j + 1 < len(a): idx.add(j + 1)          # `git commit -am "msg"`
            if g.sub == "grep" and _PATHSPEC_EXCL.match(y): idx.add(j)                                                    # `-- ':!.env'` leaves a file out; it reads nothing
    return idx

_PATHSPEC_EXCL = re.compile(r":(?:!|\^|\((?:[a-z,]*,)?exclude(?:,[a-z]*)?\))")
def subst_words(st):
    """Put the variables the command set for itself into its own words (`s=push; git $s origin main`, `c=git; $c push origin main`), so every
    rule below reads `git push origin main`. A variable standing alone at the command position or where git's subcommand goes is also split
    at its spaces (`c='git push origin main'; $c`): that is where the shell would split it, and where a program is chosen."""
    if not VARS: return
    w = st.words
    if not any("$" in x for x in w) and not any("$" in x for x in st.redirs): return
    new = [subst_vars(x) if "$" in x else x for x in w]
    ci = cmd_index(w)
    spots = [ci]
    for i, x in enumerate(new):
        if os.path.basename(x) == "git":
            j = i + 1
            while j < len(new) and (new[j] in _GIT_VAL_OPTS or new[j].startswith("-")): j += 2 if new[j] in _GIT_VAL_OPTS else 1
            spots.append(j)
    for k in sorted(set(spots), reverse=True):
        if k < len(w) and _PURE_REF.fullmatch(w[k]) and new[k] != w[k] and re.search(r"\s", new[k].strip()):
            new[k:k + 1] = new[k].split()
    if new != w or any("$" in x for x in st.redirs):
        st.words[:] = new; st.redirs[:] = [subst_vars(x) for x in st.redirs]
        st.dataidx = st.forms = st.rforms = None
_PURE_REF = re.compile(r"\$(\{\w+\}|\w+)")

def forms_of(st):
    """[(word index, text)]: each word as the shell would hand it over after variable substitution (`f=.en; ${f}v`) and brace
    expansion (`.{env,x}`). Both are looked at, never the raw word alone, so a name cannot be assembled out of the guard's sight."""
    if st.forms is None:
        fl = []
        for k, x in enumerate(st.words):
            for v in expand_braces(subst_vars(x)): fl.append((k, v))
            if len(fl) > 300000:
                LIMIT.append("a command with more than 300000 words after expansion"); break
        st.forms = fl
    return st.forms
def redir_forms(st):
    if st.rforms is None:
        rl = []
        for x in st.redirs:
            for v in expand_braces(subst_vars(x)): rl.append(v)
        st.rforms = rl[:5000]
    return st.rforms

# --- what a statement hands to its stdin
def _printf_text(args):
    def esc(s):
        try: return s.encode("latin-1", "backslashreplace").decode("unicode_escape")
        except Exception: return s
    if not args: return ""
    fmt, rest = esc(args[0]), args[1:]
    pieces = re.split(r"(%[-+ #0-9.*]*[a-zA-Z%])", fmt)
    nconv = sum(1 for p in pieces if p.startswith("%") and p != "%%" and len(p) > 1)
    out = []; ai = 0
    while True:
        for p in pieces:
            if p == "%%": out.append("%")
            elif p.startswith("%") and len(p) > 1:
                a = rest[ai] if ai < len(rest) else ""; ai += 1
                out.append(esc(a) if p.endswith("b") else a)
            else: out.append(p)
        if ai >= len(rest) or nconv == 0: break
    return "".join(out)

def literal_out(st):
    """The text a statement certainly prints, or None. Only echo, printf and a bare cat of a literal heredoc / here-string
    qualify: anything else (curl, a file) prints something the guard cannot see."""
    if st is None or st.redirs: return None
    w = st.words; ci = cmd_index(w)
    if ci >= len(w): return None
    cmd = os.path.basename(w[ci]); args = w[ci + 1:]
    if cmd == "echo":
        nl = True; interp = False
        while args and re.fullmatch(r"-[neE]+", args[0]):
            nl = nl and "n" not in args[0]; interp = interp or "e" in args[0]; args = args[1:]
        t = " ".join(args)
        if interp:
            try: t = t.encode("latin-1", "backslashreplace").decode("unicode_escape")
            except Exception: pass
        return t + ("\n" if nl else "")
    if cmd == "printf": return _printf_text(args)
    if cmd == "cat" and not args:
        if st.heredocs: return st.heredocs[-1][0] + "\n"
        if st.herestr: return st.herestr[-1] + "\n"
    return None

def stdin_text(st):
    """What the statement reads on stdin: its text if it is written out in the command, "" if nothing is fed to it, None if
    it comes from somewhere the guard cannot see (a file it cannot read, curl, cat of a file)."""
    if st.heredocs: return st.heredocs[-1][0] + "\n"
    if st.herestr: return st.herestr[-1] + "\n"
    if st.pipe_src is not None: return literal_out(st.pipe_src)
    if st.inredirs:
        p = st.inredirs[-1]
        if p == "/dev/null": return ""
        try:
            with open(abs_of(p, cwd)) as fh: t = fh.read(262145)
            return t if len(t) <= 262144 else None
        except (OSError, ValueError): return None
    return ""

def dynamic(t):
    """Code text that only exists after the outer shell has run something (`bash -c "$(cat x)"`, `eval $cmd`)."""
    t = subst_vars(t).strip()
    return "$()" in t or "``" in t or t.startswith("$") or "$GITTOP" in t

def shell_invocation(w, k):
    """How the shell at w[k] gets its program: ("code", text) for -c, ("stdin", None), or ("script", path)."""
    has_c = has_s = False; j = k + 1
    while j < len(w):
        x = w[j]
        if x == "--": j += 1; break
        if x in ("-o", "+o", "-O", "+O", "--rcfile", "--init-file"): j += 2; continue
        if len(x) > 1 and x[0] in "-+":
            if x[0] == "-" and not x.startswith("--"):
                if "c" in x[1:]: has_c = True
                if "s" in x[1:]: has_s = True
                if x[-1] in "oO" and j + 1 < len(w): j += 2; continue
            j += 1; continue
        break
    if j >= len(w): return ("stdin", None)
    if has_c: return ("code", w[j])
    if has_s or w[j] == "-": return ("stdin", None)
    return ("script", w[j])

def interp_invocation(w, k, flag):
    """How an interpreter gets its program: ("code", text), ("stdin", None), ("module", name) or ("script", path)."""
    j = k + 1
    while j < len(w):
        x = w[j]
        if x == "--": j += 1; break
        if x == "-": return ("stdin", None)
        if x == "-m": return ("module", w[j + 1] if j + 1 < len(w) else "")
        if len(x) > 1 and x[0] == "-":
            if flag.fullmatch(x): return ("code", w[j + 1] if j + 1 < len(w) else "")
            j += 2 if x in _INTERP_VAL_OPTS else 1; continue
        if flag.pattern.endswith("eval") and x == "eval": return ("code", w[j + 1] if j + 1 < len(w) else "")
        return ("script", x)
    if j < len(w): return ("script", w[j])
    return ("stdin", None)

def interp_at(w, k):
    """The program-text option of the interpreter at w[k], or None if it is not one."""
    b = os.path.basename(w[k])
    for name, flag in INTERPS:
        if name.fullmatch(b): return flag
    return None

def plausible_cmd(w, k, ci):
    """Is w[k] being run, rather than just sitting among the arguments of something else (`xargs which bash`)? It is at the
    command position, right after an option or a number (`timeout 5 bash`, `xargs -I{} sh`), or right after a wrapper."""
    if k <= ci or k == 0: return True
    p = w[k - 1]
    return p.startswith("-") or bool(re.fullmatch(r"\d+[smhd]?", p)) or os.path.basename(p) in WRAPPERS or bool(_ASSIGN.match(p)) or p in (";", "+")

def expand_stmts(stmts, depth=0):
    """Add the statements hidden in `bash -c '…'`, `eval …`, `env -S '…'`, `su -c '…'`, and in the text fed to a shell on its stdin (a
    heredoc, a here-string, `echo … | bash`). They are inserted right after the statement that runs them, so the cwd they
    start from is the one in force at that point. Nested deeper than the cap is refused: stopping silently would be a bypass."""
    out = []
    for st in stmts:
        out.append(st)
        w = st.words; data = data_of(st); n_payloads = 0; ci = cmd_index(w)
        # A program git is told to run (GIT_EDITOR=…, `-c core.pager=…`) is read as the shell code it is: `GIT_EDITOR=true git rebase
        # --continue` stays fine, `GIT_EDITOR='git push origin main' git commit` does not.
        extra = [(m.group(2), False) for j, x in enumerate(w) if j not in data for m in [_GIT_CMD_ENV.match(x)] if m and m.group(2)]
        if any(os.path.basename(x) == "git" for x in w):
            for j, x in enumerate(w[:-1]):
                if x == "-c" and j not in data:
                    key, _, val = w[j + 1].partition("=")
                    if _CMD_CFG.match(key.strip().lower()) and val.lstrip("!"): extra.append((val.lstrip("!"), False))
        for k in [None] + [k for k in range(min(ci, len(w))) if w[k] == "env"] + cmd_positions(st):
            if k is None: b, texts = "", list(extra)
            else:
                if k in data or k >= len(w) or not plausible_cmd(w, k, ci): continue
                b = os.path.basename(w[k]); texts = []
            if b in SHELLS:
                kind, val = shell_invocation(w, k)
                if kind == "code": texts.append((val, False))
                elif kind == "stdin":
                    t = stdin_text(st)
                    if t is None: LIMIT.append("a shell is fed input the guard cannot read (a pipe from something other than echo/printf, a file it cannot open)")
                    elif t.strip(): texts.append((t, False))
                elif val == "<()":              # bash <(echo '…'): the script is the output of a process substitution
                    inner = st.procsubs[0] if st.procsubs else []
                    t = literal_out(inner[0]) if len(inner) == 1 else None
                    if t is None: LIMIT.append("a shell runs a script produced by a process substitution the guard cannot read")
                    elif t.strip(): texts.append((t, False))
            elif b == "eval" and k == ci: texts.append((" ".join(w[k + 1:]), True))
            elif b == "env":
                for j in range(k + 1, len(w)):
                    x = w[j]
                    if x in ("-S", "--split-string") and j + 1 < len(w): texts.append((w[j + 1], False)); break
                    if x.startswith("--split-string="): texts.append((x[15:], False)); break
                    if x.startswith("-S") and len(x) > 2: texts.append((x[2:], False)); break
                    if not x.startswith("-") and not _ASSIGN.match(x): break
            elif b in ("su", "runuser", "script", "flock"):
                for j in range(k + 1, len(w) - 1):
                    if re.fullmatch(r"-[A-Za-z]*c|--command|--session-command", w[j]): texts.append((w[j + 1], False)); break
            for text, same in texts:
                n_payloads += 1
                if n_payloads > 8: LIMIT.append("more than 8 shell programs inside one command"); break
                if dynamic(text):
                    LIMIT.append("code that only exists after another command has run (`bash -c \"$(…)\"`, `eval $x`, a variable holding a program)"); continue
                if depth >= 4:
                    LIMIT.append("bash -c / eval / env -S nested more than 4 levels deep"); continue
                inner = shell_stmts(subst_vars(text), st.sub if same else True, depth + 1, pscope=st.scope, scope=st.scope if same else None)
                out += expand_stmts(inner, depth + 1)
            if b == "eval": break
    return out

def first_arg(w, j):
    for x in w[j:]:
        if not x.startswith("-"): return x
    return ""

# ------------------------------------------------------------ where a statement runs: the simulated cwd
_MAX_STATES = 16
COND_WORDS = {"if", "elif", "then", "else", "do", "while", "until"}
LOOP_WORDS = {"for", "while", "until", "select"}
def _union(a, b):
    if a is None or b is None: return None
    out = list(a)
    for x in b:
        if x not in out: out.append(x)
    return out if len(out) <= _MAX_STATES else None

def cd_info(st):
    """(verb, raw target) when the statement is a cd/pushd/popd (`builtin cd`, `\\cd`, `{ cd x; }`, `FOO=1 cd x` all are), else None."""
    w = st.words; ci = cmd_index(w)
    if ci >= len(w) or w[ci] not in ("cd", "pushd", "popd"): return None
    args = [x for x in w[ci + 1:] if not (x.startswith("-") and len(x) > 1)]
    return w[ci], (args[0].strip() if args else "")

def resolve_cd(raw, base):
    """Where `cd raw` lands from `base`, as a real path; None when the target is computed at run time."""
    s = expand_vars(raw, base)
    if "$" in s or "`" in s: return None
    s = os.path.expanduser(s)
    if not os.path.isabs(s): s = os.path.join(base, s)
    return os.path.realpath(s)

def walk_cwds(stmts, cwd0):
    """Give every statement the directories it may run in (st.cwds, or None when it cannot be known) and record, on each cd,
    where it lands from each of them (st.cds). The simulation is what makes `cd ..; cd ..; cd ..` and `cd app; cat ../../x`
    mean what the shell makes them mean: each cd starts from the directory the one before it left, and a path is resolved
    from there. A cd that is skipped, repeated or chosen at run time cannot be followed, so it is widened to every directory
    it could leave (a cd to a missing directory, `||`, if/while bodies, a pipeline) or made unknown (a computed target, a cd
    in a loop or a function)."""
    states, hist, chain_in = {}, {}, {}
    ifd = loopd = 0
    funcs = bool(FUNCS) or any(st.words[:1] == ["function"] for st in stmts)
    def state_of(sc):
        if sc not in states:
            p = SCOPE_PARENT.get(sc)
            while p is not None and p not in states: p = SCOPE_PARENT.get(p)
            base = states[p] if p is not None else [cwd0]
            states[sc] = None if base is None else list(base)
            hist[sc] = set(base or [])
        return states[sc]
    cdpath = VARS.get("CDPATH", os.environ.get("CDPATH", ""))
    for st in stmts:
        sc = st.scope; w = st.words
        cur_s = state_of(sc)
        ins = _union(chain_in[sc], cur_s) if st.sep == "||" and sc in chain_in else cur_s
        if st.sep in (";", "&") or sc not in chain_in: chain_in[sc] = ins
        ci = cmd_index(w); first = w[0] if w else ""
        st.cwds = ins
        d = env_chdir(w, ci)
        if d is not None:
            r = None if ins is None else [resolve_cd(d, b) for b in ins]
            st.cwds = None if r is None or None in r else r
        info = cd_info(st)
        if info:
            verb, raw = info
            cond = ifd > 0 or first in COND_WORDS or st.sep in ("||", "&") or st.pipe_src is not None or st.pipe_to is not None
            looplike = loopd > 0 or first in LOOP_WORDS or funcs
            if verb == "popd" or raw == "-" or (verb == "pushd" and (not raw or re.fullmatch(r"[+-]\d+", raw))):
                out = _union(ins, sorted(hist[sc]))                # back to somewhere this scope has already been
            else:
                if not raw: raw = "~"                              # a bare cd goes home
                ts = []; unknown = ins is None
                if not unknown:
                    for b in ins:
                        cands = [raw]
                        if not raw.startswith(("/", "./", "../", "~")) and raw not in (".", ".."):      # CDPATH makes a plain name mean something else
                            if "$" in cdpath: unknown = True
                            else: cands += [os.path.join(e or ".", raw) for e in cdpath.split(":")] if cdpath else []
                        for n, rc in enumerate(cands):
                            t = resolve_cd(rc, b)
                            if t is None: unknown = True
                            elif t not in ts and (n == 0 or os.path.isdir(t)): ts.append(t)      # a CDPATH entry counts only where it exists; else cd falls back to ./
                if unknown: st.cds.append((raw, None)); out = None
                else:
                    st.cds.append((raw, [(b, t) for b in ins for t in ts]))
                    absolute = os.path.isabs(os.path.expanduser(expand_vars(raw, ins[0] if ins else cwd0)))
                    if looplike and not absolute: out = None; st.cdkind = "loop"
                    elif looplike or cond or not all(os.path.isdir(t) for t in ts): out = _union(ins, ts)
                    else: out = list(ts)
            states[sc] = out; hist[sc].update(out or [])
        if first in ("if", "case"): ifd += 1
        elif first in ("fi", "esac"): ifd = max(0, ifd - 1)
        if first in LOOP_WORDS: loopd += 1
        elif first == "done": loopd = max(0, loopd - 1)

def bases_of(st):
    """The directories a statement may run in. Never empty: where the guard cannot tell, it falls back to the session's own."""
    return st.cwds if st.cwds else [cwd]

class GitCall:
    __slots__ = ("st", "i", "j", "sub", "C", "cfg", "end", "xtra", "viaxargs")
    def __init__(self, st, i, j, C, cfg, end, viaxargs=False):
        self.st, self.i, self.j, self.sub, self.C, self.cfg, self.end = st, i, j, st.words[j], C, cfg, end
        self.viaxargs = viaxargs; self.xtra = []
    @property
    def args(self): return self.st.words[self.j + 1:self.end] + (self.xtra or [])
    @property
    def pre(self): return self.st.words[:self.i]
    @property
    def dirs(self):
        """Every directory this git may run in: `-C dir` from each cwd the statement may be in."""
        return [abs_of(self.C[-1], b) if self.C else b for b in bases_of(self.st)]
    @property
    def dir(self): return self.dirs[0]

_GIT_VAL_OPTS = ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix", "--config-env", "--exec-path")
def git_calls(stmts):
    """Every `git <subcommand>` in the command, however it is reached (lane-run, xargs, env, a path to git). A git word that is
    only text (an echo argument, a commit message) is not a call. Under xargs the stdin items are arguments too, and when they
    cannot be read (`find … | xargs git push origin`) the call says so: its arguments are unknown."""
    for st in stmts:
        w = st.words; data = data_of(st)
        idx = [i for i, x in enumerate(w) if os.path.basename(x) == "git" and i not in data]
        for k, i in enumerate(idx):
            end = idx[k + 1] if k + 1 < len(idx) else len(w)
            j = i + 1; C = []; cfg = []
            while j < end:
                x = w[j]
                if x in _GIT_VAL_OPTS:
                    if j + 1 < end:
                        if x == "-C": C.append(w[j + 1])
                        elif x == "-c": cfg.append(w[j + 1])
                        elif x == "--config-env": cfg.append(w[j + 1])
                    j += 2; continue
                if x.startswith("--config-env="): cfg.append(x.split("=", 1)[1])
                if x.startswith("-"): j += 1; continue
                break
            if j < end:
                g = GitCall(st, i, j, C, cfg, end, any(os.path.basename(w[m]) in ("xargs", "parallel") for m in range(i)))
                if g.viaxargs: g.xtra = xargs_items(g)
                yield g

def xargs_items(call):
    """The arguments xargs appends to a git call: a list of words, or None when stdin is not written out in the command."""
    t = stdin_text(call.st)
    return None if t is None else t.split()

# Every subcommand git itself ships. A word that is not one of them is a user's alias or an external `git-foo`; an alias can be
# `push`, so one that names a protected branch is judged as the push it may be.
KNOWN_GIT = set("""add am annotate apply archive bisect blame branch bundle cat-file check-attr check-ignore check-mailmap check-ref-format
checkout checkout-index cherry cherry-pick citool clean clone column commit commit-graph commit-tree config count-objects credential describe diff
diff-files diff-index diff-tree difftool fast-export fast-import fetch fetch-pack filter-branch fmt-merge-msg for-each-ref for-each-repo format-patch fsck gc
get-tar-commit-id grep gui hash-object help hook index-pack init instaweb interpret-trailers log ls-files ls-remote ls-tree mailinfo mailsplit maintenance merge
merge-base merge-file merge-index merge-tree mergetool mktag mktree multi-pack-index mv name-rev notes pack-objects pack-redundant pack-refs patch-id prune
prune-packed pull push range-diff read-tree rebase receive-pack reflog remote repack replace request-pull rerere reset restore rev-list rev-parse revert rm
send-email send-pack shortlog show show-branch show-index show-ref sparse-checkout stage stash status stripspace submodule subtree switch symbolic-ref tag
unpack-file unpack-objects update-index update-ref update-server-info upload-archive upload-pack var verify-commit verify-pack verify-tag version
whatchanged worktree write-tree lfs bugreport diagnose scalar http-fetch http-push svn p4 cvsimport quiltimport""".split())
# Git settings are of two kinds. STRUCTURAL ones define a new subcommand or move where hooks and config come from: they are refused outright
# (`-c alias.x=push`, `core.hooksPath`, `include.path`, GIT_CONFIG_*). COMMAND-valued ones hold a program git will run (an editor, a pager, an
# ssh command): given once with `-c` or an environment variable the program is read as shell code like any other (so `GIT_EDITOR=true git
# rebase --continue` works and `GIT_EDITOR='git push origin main'` does not); written into the config with `git config` it would run
# unseen on every later git call, so that is refused.
_STRUCT_CFG = re.compile(r"^(alias\.|core\.hookspath$|include\.|includeif\.|protocol\.ext|remote\.[^.]*\.(uploadpack|receivepack|vcs|proxy)$|uploadpack\.packobjectshook$)", re.I)
_CMD_CFG = re.compile(r"^(core\.(sshcommand|fsmonitor|pager|editor|askpass|gitproxy)$|credential\.([^.]*\.)?helper$|diff\.external$|diff\.[^.]*\.(command|textconv)$|"
                      r"merge\.[^.]*\.driver$|filter\.[^.]*\.(clean|smudge|process)$|gpg\.([^.]*\.)?program$|sequence\.editor$|pager\.|trailer\.[^.]*\.cmd$|submodule\.[^.]*\.update$)", re.I)
_GIT_ENV = re.compile(r"(GIT_(CONFIG\w*|EXEC_PATH|TEMPLATE_DIR))=")                       # structural: refused
_GIT_CMD_ENV = re.compile(r"(GIT_(?:EDITOR|SEQUENCE_EDITOR|PAGER|SSH|SSH_COMMAND|ASKPASS|EXTERNAL_DIFF|PROXY_COMMAND))=(.*)", re.S)       # a program: read as code
_GIT_CFG_READ = ("--get", "--get-all", "--get-regexp", "--get-urlmatch", "--list", "-l", "--name-only", "--show-origin", "--show-scope", "--help", "-h")
_GIT_CFG_VAL = ("--file", "-f", "--blob", "--type", "--default", "--comment")
def git_config_writes(g):
    """The key a `git config` call sets, or None when it only reads. Setting alias.*, core.hooksPath and the other keys that
    run commands is how a push to main gets renamed past the guard (`git config alias.p push && git p origin main`)."""
    if g.sub != "config": return None
    a = g.args
    if any(x in _GIT_CFG_READ for x in a): return None
    pos = []; k = 0
    while k < len(a):
        x = a[k]
        if x in _GIT_CFG_VAL: k += 2; continue
        if not x.startswith("-"): pos.append(x)
        k += 1
    edit = any(x in ("-e", "--edit") for x in a)
    unset = any(x in ("--unset", "--unset-all", "--replace-all", "--add", "--rename-section", "--remove-section") for x in a)
    if edit: return "(edit)"
    if len(pos) >= 2 or (unset and pos): return pos[0]
    return None
def git_refusal(g):
    """Why this git call is refused for what it configures, or None."""
    for c in g.cfg:
        key = c.split("=", 1)[0].strip()
        if _STRUCT_CFG.match(key):
            return (f"`-c {key}=…` defines a git subcommand or moves where hooks and settings come from, which is a way to rename a push "
                    "to a protected branch or to run anything: not part of the work.")
    k = git_config_writes(g)
    if k is not None and (k == "(edit)" or _STRUCT_CFG.match(k.strip()) or _CMD_CFG.match(k.strip())):
        return (f"Setting `{k}` is refused: aliases, hooksPath and the other git settings that run commands are how a "
                "push to a protected branch gets renamed past the guard (and a program written into the config runs unseen on every later git call). "
                "Use the real subcommand; give a one-off editor or pager with `-c` or an environment variable.")
    return None

def lane_cmds(stmts):
    """(name, words, j) for every lane-<name> script, `lane <name>` and the standalone helpers; the arguments start at words[j]."""
    for st in stmts:
        w = st.words; ci = cmd_index(w); data = data_of(st)
        for i, x in enumerate(w):
            if i in data: continue
            b = os.path.basename(x)
            if b.startswith("lane-") and len(b) > 5: yield b[5:], w, i + 1
            elif b == "lane" and i == ci and i + 1 < len(w): yield w[i + 1], w, i + 2
            elif b == "repo-secrets": yield "secrets", w, i + 1
            elif b == "init" and os.path.basename(os.path.dirname(x)) == "scripts": yield "init", w, i + 1

_branch_cache = {}
def current_branch(d):
    if d not in _branch_cache: _branch_cache[d] = git(d, "branch", "--show-current")
    return _branch_cache[d]

def push_hit(call, prot):
    """(protected?, forced?) for one `git push`. (A push whose arguments xargs appends from an unreadable stdin is refused by the caller.)"""
    args = call.args; force = mirror = tags = False; pos = []; i = 0
    while i < len(args):
        a = args[i]
        if a == "--": pos += args[i + 1:]; break
        if a.startswith("--"):
            name = a.split("=", 1)[0]
            if name in ("--force", "--force-with-lease", "--force-if-includes"): force = True
            elif name in ("--mirror", "--all", "--branches"): mirror = True
            elif name == "--tags": tags = True
            elif name in ("--push-option", "--receive-pack", "--exec", "--repo") and "=" not in a: i += 1
        elif a.startswith("-") and len(a) > 1:
            if re.match(r"-[A-Za-z]*f", a): force = True
            if a == "-o": i += 1
        else: pos.append(a)
        i += 1
    specs = pos[1:]; implicit = not specs and not tags and not mirror; hit = mirror
    for sp in specs:
        sp = subst_vars(sp)
        dst = sp[1:] if sp.startswith("+") else sp
        dst = dst.split(":", 1)[1] if ":" in dst else dst
        dst = dst[len("refs/heads/"):] if dst.startswith("refs/heads/") else dst
        if dst == "HEAD": implicit = True
        elif dst in prot or (any(ch in dst for ch in "*?[") and any(fnmatch.fnmatchcase(b, dst) for b in prot)): hit = True
    if implicit and not hit and any(current_branch(d) in prot for d in call.dirs): hit = True      # `git push` pushes the checked-out branch
    return hit, force

def alias_hit(call, prot):
    """An unknown `git <word> …` is a user alias or an external command, and an alias can be `push`. It is refused only when
    it names a protected branch, so `git lg` and `git co feature` keep working."""
    if call.sub in KNOWN_GIT or not re.fullmatch(r"[\w][\w.-]*", call.sub): return False
    for a in call.args:
        if a.startswith("-") and not a.startswith("--force"): continue
        for part in re.split(r"[:]", subst_vars(a).lstrip("+")):
            part = part[len("refs/heads/"):] if part.startswith("refs/heads/") else part
            if part in prot: return True
    return False

def branch_hit(call, prot):
    """Would this `git branch` delete, rename, overwrite or copy over a protected branch?"""
    flags = [a for a in call.args if a.startswith("-")]; pos = [subst_vars(a) for a in call.args if not a.startswith("-")]
    short = "".join(f[1:] for f in flags if not f.startswith("--"))
    delete = "--delete" in flags or any(ch in short for ch in "dD") or "--move" in flags or any(ch in short for ch in "mM")
    force = "--force" in flags or "f" in short
    copy = "--copy" in flags or any(ch in short for ch in "cC")
    if delete: return any(p in prot for p in pos)
    if copy and pos: return pos[-1] in prot
    if force and pos: return pos[0] in prot
    return False

def stash_refused(call):
    """The shared stash stack is unsafe: only a named `stash push|save` is let through."""
    sub = None; named = False; args = call.args; i = 0; dd = False
    while i < len(args):
        a = args[i]
        if a == "--": dd = True
        elif dd: pass
        elif a in ("-m", "--message"): named = True; i += 1
        elif a.startswith("--message=") or (a.startswith("-m") and len(a) > 2 and not a.startswith("--")): named = True
        elif a.startswith("-"): pass
        elif sub is None: sub = a
        elif sub == "save": named = True
        i += 1
    if sub in ("pop", "apply", "drop", "clear", "branch", "create", "store"): return True
    return sub in (None, "push", "save") and not named

def remote_change(call):
    if call.sub == "remote": return first_arg(call.st.words, call.j + 1) in ("add", "set-url", "remove", "rm", "rename", "prune")
    if call.sub == "config":
        if any(a in ("--get", "--get-all", "--get-regexp", "--get-urlmatch", "--list", "-l") for a in call.args): return False
        return any(re.search(r"(?:remote\.[\w.-]+\.(?:url|pushurl)|url\..+\.(?:push)?insteadof)", a, re.I) for a in call.args)
    return False

_GH_MSG_DESTROY = "Deleting, archiving, renaming or transferring a repository is never part of the work."
_GH_MSG_WRITE = ("A writing gh api call (DELETE/PUT/PATCH/POST, or any call with fields, which makes it a POST) bypasses every "
                 "check we have. Say what you need and let __OWNER__ decide; read-only `gh api` is fine.")
_GH_MSG_ADMIN = ("`gh {cmd} {sub}` changes the repository's or the account's settings, credentials, release history or other "
                 "people's work, and none of that is part of the work. Say what you need and let __OWNER__ do it.")
# (command, subcommands) pairs that are refused outright
_GH_ADMIN = {"alias": {"set", "import", "delete"}, "variable": {"set", "delete", "remove"}, "extension": {"install", "exec", "upgrade", "remove", "create"},
             "ssh-key": {"add", "delete"}, "gpg-key": {"add", "delete"}, "release": {"delete", "delete-asset"}, "issue": {"delete"},
             "label": {"delete"}, "run": {"delete"}, "cache": {"delete"}, "workflow": {"disable"}, "pr": {"close"}, "codespace": {"delete"}}
_GH_EDIT_FLAGS = ("--visibility", "--accept-visibility-change-consequences", "--default-branch", "--name", "--homepage", "--add-topic", "--remove-topic")
def gh_refusal(args):
    """The reason a gh invocation is refused, or None. `args` are the words after `gh`."""
    i = 0
    while i < len(args) and args[i].startswith("-"): i += 2 if args[i] in ("-R", "--repo", "--hostname") else 1
    rest = args[i:]
    if not rest: return None
    cmd = rest[0]; sub = first_arg(rest, 1)
    if cmd == "repo" and sub in ("delete", "archive", "rename", "transfer"): return _GH_MSG_DESTROY
    if cmd == "repo" and sub == "edit" and any(a.split("=", 1)[0] in _GH_EDIT_FLAGS for a in rest[2:]):
        return "Changing a repository's visibility, default branch or name is never part of the work. `gh repo edit --delete-branch-on-merge` and its description are fine."
    if cmd == "pr" and sub == "merge":
        return "Merging a pull request lands code on a protected branch. Ask __OWNER__ first; they merge it."
    if cmd in _GH_ADMIN and sub in _GH_ADMIN[cmd]: return _GH_MSG_ADMIN.format(cmd=cmd, sub=sub)
    if cmd == "secret" and sub in ("set", "delete", "remove"):
        return "Changing repository or organisation secrets is not part of the work. Say what you need and let __OWNER__ do it."
    if cmd == "auth" and (sub == "token" or (sub == "status" and any(a in ("--show-token", "-t") for a in rest))):
        return "Printing the GitHub token is a secret read. The token is never needed to do the work: use `lane-gh`."
    if cmd == "api":
        method = None; fields = []; has_input = False; endpoint = None; k = 1
        while k < len(rest):
            a = rest[k]
            if a in ("-X", "--method") and k + 1 < len(rest): method = rest[k + 1].upper(); k += 1
            elif a.startswith("--method="): method = a[9:].upper()
            elif a.startswith("-X") and len(a) > 2: method = a[2:].upper()
            elif a in ("-f", "-F", "--field", "--raw-field") and k + 1 < len(rest): fields.append(rest[k + 1]); k += 1
            elif a.startswith(("--field=", "--raw-field=")): fields.append(a.split("=", 1)[1])
            elif re.match(r"-[fF]\S", a): fields.append(a[2:])
            elif a == "--input" or a.startswith("--input="): has_input = True; k += a == "--input"
            elif a in ("-H", "--header", "-q", "--jq", "-t", "--template", "--cache", "--hostname", "-p", "--preview") and k + 1 < len(rest): k += 1
            elif not a.startswith("-") and endpoint is None: endpoint = a
            k += 1
        effective = method or ("POST" if fields or has_input else "GET")
        if effective == "GET": return None
        if endpoint == "graphql" and effective == "POST" and not has_input and fields \
           and not any("mutation" in f.lower() or "=@" in f for f in fields):
            return None                      # a graphql query is a POST that only reads
        return _GH_MSG_WRITE
    return None

# ----------------------------------------------------------------------- paths, cd, the plane
SCRATCH = re.compile(r"^(/private)?/tmp/")
OUTSIDE_MSG = ("Everything you work with lives under the control plane. {what} is outside it.\n"
               "  code of this work      lanes/<lane>/<repo>/\n"
               "  anything else you need attach it once: `lane-ref <lane> add <path> \"why\"`, then read it at\n"
               "                         lanes/<lane>/refs/<name>/… — the reference path, never the real one.\n"
               "  temporary files        the session scratchpad under /tmp")

def expand_vars(s, base=None):
    """The variables the guard can read for a path: $HOME, $AD, $WS_HOME, $USER, $PWD (the simulated cwd, and what `$(pwd)` stands
    for), `$(git rev-parse --show-toplevel)`, in `$X` and `${X}` form and with a default (`${HOME:-x}`: HOME is set, so the default is
    never used). Anything it cannot read is left as it is."""
    if "$" not in s: return s
    def val(name):
        if name in ("WS_HOME", "AD"): return AD
        if name == "HOME": return HOME
        if name == "PWD" and base: return base
        if name in ("USER", "LOGNAME"): return os.environ.get(name) or None
        return None
    def rep_brace(m):
        name, op, word = m.group(1), m.group(2), m.group(3)
        v = val(name)
        if v is None or (op is None and word): return m.group(0)
        if op in (":+", "+"): return word
        return v
    s = re.sub(r"\$\{(\w+)(:?[-=?+])?([^}]*)\}", rep_brace, s)
    s = re.sub(r"\$(WS_HOME|AD|HOME|PWD|USER|LOGNAME)(?!\w)", lambda m: val(m.group(1)) or m.group(0), s)
    if "$GITTOP" in s:
        d = base or cwd                     # `git rev-parse --show-toplevel` without running git: the nearest folder with a .git (file or folder)
        while d and d != "/" and not os.path.lexists(os.path.join(d, ".git")): d = os.path.dirname(d)
        if d and d != "/": s = s.replace("$GITTOP", d)
    return s

def abs_of(path, base):
    if not path: return ""
    p = os.path.expanduser(expand_vars(path, base))
    if not os.path.isabs(p): p = os.path.join(base, p)
    return os.path.normpath(p)

_OTHER_HOME = re.compile(r"^(/Users|/home)/[^/]+(/|$)|^(/var)?/root(/|$)")        # another account's home: `~root`, `~alice`, /Users/*, /home/*
def _outside(a):
    in_home = HOME not in ("", "/") and (a == HOME or a.startswith(HOME + "/"))
    if a == AD or a.startswith(AD + "/"): return None          # inside the control plane
    if a == PRODUCT or a.startswith(PRODUCT + "/"): return None  # the product's own files, wherever they are installed
    # /tmp is the scratchpad, unless the home directory itself lives under it
    if SCRATCH.match(a) and not in_home: return None
    if in_home: return a
    if _OTHER_HOME.match(a + "/"): return a                    # another account's home
    return None                                                 # system paths stay readable

def _ref_path_ok(a, real):
    """A symlink under lanes/<id>/refs/ that leads where the lane's own `refs:` list says it should."""
    m = re.match(re.escape(LANES) + r"/([^/]+)/refs/", a)
    return bool(m) and any(real == r or real.startswith(r + "/") for r, _mode in lane_refs(m.group(1)))

def outside_of(a, resolve=True, real=None):
    """`a` (absolute) judged as written, then judged again where its symlinks lead. Returns the offending path or None."""
    r = _outside(a)
    if r: return r
    if resolve:
        real = real or os.path.realpath(a)
        if real != a:
            r = _outside(real)
            if r and not _ref_path_ok(a, real): return r
    return None

def outside_ad(given, cwd):
    """The path a tool was pointed at. Returns None when it is fine, or a reason to refuse."""
    if not given: return None
    return outside_of(abs_of(given, cwd))

def ref_hint(a, cur):
    """If an outside path is a reference of this lane, point at the reference path instead."""
    if not cur: return ""
    for r, _mode in lane_refs(cur):
        if a == r or a.startswith(r + "/"):
            rel = a[len(r):].lstrip("/")
            return (f"\n  That path IS attached to this lane. Read it at "
                    f"lanes/{cur}/refs/{os.path.basename(r)}/{rel}")
    return ""

CRED_DIRS = (".ssh", ".aws", ".gnupg", ".kube", ".docker", ".azure", ".config", ".claude", ".cursor", ".netrc", ".npmrc", ".pypirc",
             ".git-credentials", ".gitconfig", ".password-store", "Library/Keychains")
SYSTEM_DIRS = ("/etc", "/proc", "/sys", "/dev", "/boot", "/root", "/System", "/private/etc", "/var/root")
def ref_add_refusal(raw, base):
    """Why `lane-ref add <raw>` is refused, or None. A reference is read by every session of the lane, so it may not be
    the home directory, an ancestor of it or of the plane, a system directory, a credential directory or a secret file."""
    rp = os.path.realpath(abs_of(raw, base))
    if rp == "/" or HOME == rp or HOME.startswith(rp + "/") or any(r.startswith(rp + "/") or rp == r for r in (AD, PRODUCT)):
        return "that folder holds the home directory or the control plane itself"
    if any(rp == d or rp.startswith(d + "/") for d in SYSTEM_DIRS):
        return "that is a system directory"
    if any(rp == f"{HOME}/{d}" or rp.startswith(f"{HOME}/{d}/") for d in CRED_DIRS):
        return "that is where credentials and tool configuration live"
    if is_secret(rp, base): return "that is a secret file"
    return None

PLANE_TOP = ("scripts", "src", "docs", ".claude", "bin", ".github", ".git")   # src/: the package launcher, product code like scripts/
WORKSPACE_TOP = (".claude", ".repolane", ".git")
def plane_target(rp):
    """What part of the control plane a path belongs to, or None."""
    if rp == AD: return "plane"
    # the product installed apart from the workspace is the plane's code all the same
    if PRODUCT != AD and (rp == PRODUCT or rp.startswith(PRODUCT + "/")): return "plane"
    if not rp.startswith(AD + "/"): return None
    # judged by the name it has in a clone, so a workspace's .repolane/memory/x is memory/x (scripts/roots.py)
    rel = R.logical(rp[len(AD) + 1:])
    top = rel.split("/")[0]
    if top == "memory": return "memory"
    if top == "knowledge": return "knowledge"
    if rel.startswith("registry/lanes/"): return "lane"
    if top == ".cache":
        # the inbox is where lane-memory drafts are written, and nx is a build cache; the rest is the guard's own state
        return None if rel.split("/")[1:2] in (["memory-inbox"], ["nx"]) else "plane"
    # a workspace holds no product code at its top: what is the plane's there is .claude/ and the rest of .repolane/
    tops = WORKSPACE_TOP if R.workspace else PLANE_TOP
    if top in tops or top == "registry" or "/" not in rel: return "plane"     # a file at the root is the plane's too
    return None

def session_config_msg(rp):
    if os.path.basename(rp).startswith("settings") and os.path.basename(os.path.dirname(rp)) == ".claude":
        return ("That file is the session's own permission and hook configuration. Editing it from "
                "inside a session is how the rules get switched off silently. Change it from a "
                "dispatcher session at the control plane root, or ask __OWNER__.")
    return None

def _write_verdict(rp, cur, cwd):
    # A session's own hook config is never writable from inside a session: overwriting it
    # is how a lane switches its own guard off.
    msg = session_config_msg(rp)
    if msg: return msg
    if cur and re.search(r"(?:^|/)\.git/(?:config$|hooks(?:/|$)|info/attributes$)", rp):
        return ("A repository's own .git/config and .git/hooks decide what git runs: aliases, hooksPath and hooks are how a push to a "
                "protected branch gets renamed past the guard. Not part of the work.")
    kind = plane_target(rp)
    if kind in ("memory", "knowledge"):
        return MEMORY_GATE
    if kind == "lane":
        wid = os.path.basename(rp)[:-3]
        if cur and wid != cur:
            return f"That is lane '{wid}'; this session is in '{cur}'. Only its own spec may be edited from here."
        return None
    if kind == "plane" and cur:
        return PLANE_GATE.format(what=os.path.relpath(rp, AD))
    return None

def link_itself(a, real):
    """Is `a` (as written) a symlink whose own directory is not inside a mirror? Removing it touches only the link."""
    if a.endswith("/") or not a: return False
    try:
        pa = abs_of(a, cwd)
        d = real(os.path.dirname(pa) or "/")
        if d == REPOS or d.startswith(REPOS + "/"): return False
        return os.path.islink(os.path.join(d, os.path.basename(pa)))
    except (OSError, ValueError): return False
def mirror_msg(a, p):
    """Why a write that lands in a mirror is refused. A lane's env file is usually a link into the mirror (lane start/resume
    put it there), and the plain text did not say so."""
    rel = os.path.relpath(p, AD)
    try: is_link = os.path.islink(abs_of(a, cwd)) or (abs_of(a, cwd) != p and os.path.realpath(abs_of(a, cwd)) == p)
    except (OSError, ValueError): is_link = False
    if is_link:
        name = os.path.basename(a.rstrip("/")) or a
        return (f"{a} is a symlink to {rel} in the read-only mirror (lane start/resume link a repo's env files into the lane so every lane shares "
                f"one copy), so writing it would change the mirror. For a local, writable env file: `rm {a}` (removes only the link), then "
                f"`cp .env.example {name}` (a copy of the template is allowed), and ask the owner for the real values; `lane-env-keys {name}` "
                f"lists the variable names. The shared one is the owner's to edit in the mirror.")
    return (f"{rel} is inside a read-only mirror. Mirrors stay on the default branch and clean; work happens in a lane. Reading them is fine.")
def write_target_verdict(rp, cur, cwd):
    """Why a write to `rp` is refused, or None. The file tools have judged the control
    plane since the beginning; this is the same judgement for a shell write target, so
    `echo x > guard.py` cannot do what `Write` is refused. Judged as written and again where
    a symlink leads (bin/* are links into scripts/, and a lane may hold a link of its own)."""
    if not rp:
        return None
    for p in dict.fromkeys((rp, os.path.realpath(rp))):
        v = _write_verdict(p, cur, cwd)
        if v: return v
    return None

ALL_VERBS = {"rm", "touch", "mkdir", "chmod", "chown", "dd", "truncate", "tee", "rmdir", "unlink", "shred", "sponge", "ed", "ex", "vi", "vim", "nvim", "nano",
             "patch", "tar", "unzip", "zip", "curl", "wget", "gzip", "gunzip", "bzip2", "xz"}
LAST_VERBS = {"cp", "ln", "install", "rsync", "scp"}
GIT_WRITE_SUBS = {"commit", "checkout", "switch", "reset", "push", "add", "rm", "mv", "stash", "rebase", "merge", "restore", "clean",
                  "apply", "am", "cherry-pick", "branch", "tag", "worktree"}
MIRROR_BLOCKED = {"checkout", "switch", "reset", "commit", "merge", "rebase", "stash", "cherry-pick", "am", "apply", "clean", "restore", "push"}
CONTROL_PLANE_CMDS = {"upgrade", "init", "install", "add", "use"}
CONTROL_PLANE_MSG = ("`{what}` changes the control plane itself (code, rules or the registry). Changing it from inside a lane "
                     "is how the system drifts. Propose it to __OWNER__ and run it from a dispatcher session at the control plane root.")
OTHER_LANE_MSG = ("`{what}` targets lane '{target}' but you are in '{cur}'. Lifecycle commands only act on this session's own lane; "
                  "the dispatcher at the control plane root handles the others.")

def plane_script(w0, base):
    """Is this command word a script of THIS plane (scripts/ or bin/)? A bare name counts only if the plane really has it; a path
    counts only if it leads there from `base`. `scripts/lane-evil` in a repo that has its own scripts/ is just another program."""
    if not w0: return False
    if "/" not in w0: return bool(re.fullmatch(r"lane-[\w-]+", w0)) and (os.path.isfile(f"{PRODUCT}/scripts/{w0}") or os.path.lexists(f"{PRODUCT}/bin/{w0}"))
    p = os.path.normpath(w0 if os.path.isabs(w0) else os.path.join(base, w0))
    return os.path.dirname(p) in (f"{PRODUCT}/scripts", f"{PRODUCT}/bin") and os.path.lexists(p)
def ours_word(w0, base):
    """One of OUR lane-* scripts, as opposed to lane-run / lane-gh (which carry someone else's command)."""
    return bool(re.fullmatch(r"(\S*/)?lane-[\w-]+", w0)) and not re.fullmatch(r"(\S*/)?lane-(run|gh)", w0) and plane_script(w0, base)

def stmt_cands(st, ci, base):
    """[(kind, absolute path)] for everything a statement's words and redirect targets may be naming, from directory `base`. A bare
    word only counts when it exists (so `app.py` is judged, `-r` and `HEAD~3` are not). A word with an unresolved `$` is judged by the
    part before it (`/plane/scripts/$f` is a path into the plane whatever `$f` is). What echo and printf print, a commit message and a
    grep pattern are text, not paths."""
    out = []; data = data_of(st)
    def add(text, kind):
        if len(text) > 4096 or "\x00" in text: return
        s = expand_vars(text, base)
        if not s: return
        if "$" in s or "`" in s:
            pre = re.split(r"[$`]", s, maxsplit=1)[0]
            if len(pre) > 1 and pre[0] in "/~": out.append((kind, abs_of(pre, base)))
            return
        if not (s[0] in "/~." or "/" in s) and not os.path.lexists(os.path.join(base, s)): return
        out.append((kind, abs_of(s, base)))
    for k, x in forms_of(st):
        if k in data: continue
        if x.startswith("-"):
            if "=" in x: add(x.split("=", 1)[1], "opt")
            continue
        kind = "cmd" if k == ci else ("env" if k < ci else "arg")
        add(x, kind)
        if "=" in x and not x.startswith("="): add(x.split("=", 1)[1], kind)
    for x in redir_forms(st): add(x, "redir")
    return out

_PATH_TOKEN = re.compile(r"(?<![\w.~/$-])(?:~[\w.-]*(?:/[\w./@%+,=:~-]*)?|/[\w./@%+,=:~-]*|(?:\.\.?/|[\w.-]+/)[\w./@%+,=:~-]*)")
def code_paths(code):
    """Path-looking tokens inside a program's text, `$HOME` and `~` already read."""
    return [m.group(0) for m in _PATH_TOKEN.finditer(code[:100000]) if len(m.group(0)) > 1]
# Idioms that build a string out of pieces, and calls that read a file: together they are how `.env` gets named without being written.
_ASSEMBLE = re.compile(r"chr\(|fromCharCode|\\x[0-9a-fA-F]{2}|\\u[0-9a-fA-F]{4}|b64decode|atob\(|base64|fromhex|unhexlify|['\"]\s*\+\s*['\"]|['\"]\s*\.\s*['\"]|getattr\(|__import__|\beval\(|\bexec\(|\bcompile\(|\bpack\(", re.I)
_READS = re.compile(r"open\s*\(|readFile|File\.(read|open|foreach)|IO\.(read|foreach)|fopen|\bcat\b|read_text|read_bytes|Path\(|createReadStream|\bglob\(|listdir|\bwalk\(|scandir|<\s*\$", re.I)
_WRITEY = re.compile(r"write|append|unlink|remove|rename|replace|rmtree|rmdir|shutil|copy|move|symlink|truncate|chmod|chown|mkdir|touch|system|popen|subprocess|exec|spawn|\bsed\b|\btee\b|"
                     r"open\s*\([^)]*,\s*(?:mode\s*=\s*)?['\"][rbt]*[wax+]|open\s*\([^)]*['\"]\s*\+?>|File\.open\([^)]*['\"][wa]|createWriteStream", re.I)
_LISTS = re.compile(r"glob|listdir|scandir|\bwalk\b|readdir|fnmatch|\bls\b|\bfind\b|Dir\.|opendir", re.I)
_QUOTED = re.compile(r"'([^'\n]{1,200})'|\"([^\"\n]{1,200})\"")
_SHELLY = re.compile(r"system|popen|subprocess|exec|spawn|\bsh\b|\bbash\b|`|%x|\bqx\b|shell", re.I)
_CODE_GLOB = re.compile(r"[^\s'\"();,<>|&]*[*?\[][^\s'\"();,<>|&]*")
def code_refusal(code, bases, writey=None):
    """Why program text (python -c, node -e, a heredoc fed to an interpreter …) is refused, or None. Program text is searched, not
    parsed, so it errs toward refusing; what it cannot see through (a name computed from arbitrary data) is documented in README."""
    base = bases[0]
    for b in bases[:3]:
        c = expand_vars(subst_vars(code), b)
        if secret_tokens(c, b) or secret_tokens(code, b) or secret_globs(c): return SECRET_MSG + " (the program names a secret file)"
    if _ASSEMBLE.search(code) and _READS.search(code):
        return SECRET_MSG + " (the program builds a file name out of pieces and reads files: name the file plainly, or this cannot be told from a read of a secret)"
    c = expand_vars(subst_vars(code), base)
    if _LISTS.search(code):                       # glob.glob('.e*'), os.listdir, find: a quoted pattern that names a secret
        for m in _QUOTED.finditer(c):
            lit = m.group(1) if m.group(1) is not None else m.group(2)
            if any(ch in lit for ch in "*?[") and glob_names_secret(lit): return SECRET_MSG + " (the program globs for a secret file)"
    if _SHELLY.search(code):                       # os.system('cat .en*'): a glob inside a command string a shell will expand
        for m in _CODE_GLOB.finditer(c[:100000]):
            if secret_globs(m.group(0)): return SECRET_MSG + " (the program globs for a secret file)"
    writes = bool(_WRITEY.search(code)) or bool(writey and writey.search(code))
    for tok in code_paths(c):
        a = abs_of(tok, base)
        o = outside_of(a)
        if o: return OUTSIDE_MSG.format(what=o) + ref_hint(o, cur)
        if writes:
            v = write_target_verdict(a, cur, cwd)
            if v: return v
    return None


# ------------------------------------------------ whole directories: a tool that reads or copies everything below a folder
# Naming no secret does not make a command safe if it reads a folder that holds one: `grep -r KEY .`, `tar czf x.tgz .`, `cp -r . /tmp/y`,
# `find . -exec cat {} +`. Such a command is refused unless it excludes the secret explicitly (--exclude, -x, ! -name, -g '!…') or
# restricts itself to files that cannot be one (--include='*.py', -t py).
SKIP_TREE = {".git", "node_modules", ".venv", "venv", "__pycache__", ".tox", ".mypy_cache"}     # a package's own test keys are not the project's
_WALK_CAP = 100000
_tree_cache = {}
def secrets_under(root, depth=None):
    """Relative paths of the secret files below directory `root` (symlinked directories are not entered; `.git`, node_modules and
    virtualenvs are skipped). Past _WALK_CAP entries the tree is too big to vouch for, and that refuses the command."""
    key = (root, depth)
    if key in _tree_cache: return _tree_cache[key]
    found = []; seen = 0
    for dp, dns, fns in os.walk(root):
        rel = os.path.relpath(dp, root); d = 0 if rel == "." else rel.count("/") + 1
        dns[:] = [x for x in dns if x not in SKIP_TREE]
        if depth is not None and d + 1 >= depth: dns[:] = []
        if depth is not None and d + 1 > depth: continue
        for f in fns:
            seen += 1
            if seen > _WALK_CAP:
                LIMIT.append("a folder with more than %d files below it, too big to check for secrets" % _WALK_CAP)
                _tree_cache[key] = found; return found
            p = os.path.join(dp, f)
            if _secret_name(f) or (os.path.islink(p) and is_secret(p, dp)): found.append(os.path.relpath(p, root))
    _tree_cache[key] = found
    return found

def _glob_hit(pat, rel):
    pat = pat.strip()
    if pat.startswith("./"): pat = pat[2:]
    if not pat: return False
    parts = rel.split("/")
    cands = [rel, parts[-1]] + ["/".join(parts[:i]) for i in range(1, len(parts))] + parts[:-1]
    return any(fnmatch.fnmatchcase(c, pat) for c in cands) or fnmatch.fnmatchcase(rel, pat.rstrip("/") + "/*")
def cannot_match_secret(incl, restricted):
    """A filter that only lets through files such a pattern names (`--include='*.py'`, `-t py`) cannot reach a secret, so there is no need to
    walk the folder to find out."""
    return restricted or (bool(incl) and not any(fnmatch.fnmatchcase(smp.lower(), g.lower()) for g in incl for smp in _SECRET_SAMPLES))
def uncovered(found, excl, incl, excl_dirs, restricted=False):
    """The secrets in `found` that the command's own filters do not keep it away from."""
    if restricted: return []
    out = []
    for rel in found:
        parts = rel.split("/")
        if any(_glob_hit(g, rel) for g in excl): continue
        if excl_dirs and any(fnmatch.fnmatchcase(p, g) for g in excl_dirs for p in parts[:-1]): continue
        if incl and not any(fnmatch.fnmatchcase(parts[-1], g) or fnmatch.fnmatchcase(rel, g) for g in incl): continue
        out.append(rel)
    return out

def _val(args, k):
    """(value, next index) of the option at args[k]: `--exclude=G` or `--exclude G`."""
    x = args[k]
    if x.startswith("--") and "=" in x: return x.split("=", 1)[1], k + 1
    return (args[k + 1] if k + 1 < len(args) else ""), k + 2
def _from_file(path):
    try:
        with open(abs_of(path, cwd)) as fh: return [l.strip() for l in fh.read(100000).splitlines() if l.strip()]
    except (OSError, ValueError): return []

def _parse_grep(b, args):
    rec = b in ("rg", "ag", "ack"); hidden = b not in ("rg", "ag"); pos = []; excl = []; incl = []; xd = []; have = False; restricted = False; u = 0; k = 0; dd = False
    while k < len(args):
        x = args[k]
        if dd or not x.startswith("-") or x == "-": pos.append(x); k += 1; continue
        if x == "--": dd = True; k += 1; continue
        name = x.split("=", 1)[0] if x.startswith("--") else x
        if name in ("-e", "--regexp", "-f", "--file"): have = True; k += 2 if "=" not in x or not x.startswith("--") else 1; continue
        if name in ("--recursive", "--dereference-recursive") or re.fullmatch(r"-[A-Za-z0-9]*[rR][A-Za-z0-9]*", x): rec = True
        if x in ("-d", "--directories") and k + 1 < len(args) and args[k + 1] == "recurse": rec = True
        if x == "--directories=recurse": rec = True
        if name == "--exclude" or (b == "ag" and name == "--ignore"): v, k = _val(args, k); excl.append(v); continue
        if name == "--include": v, k = _val(args, k); incl.append(v); continue
        if name == "--exclude-dir": v, k = _val(args, k); xd.append(v); continue
        if name == "--exclude-from": v, k = _val(args, k); excl += _from_file(v); continue
        if name in ("-g", "--glob", "--iglob"):
            v, k = _val(args, k)
            if v.startswith("!"): excl.append(v[1:])
            elif v: incl.append(v)
            continue
        if name in ("-t", "--type"): restricted = True; _, k = _val(args, k); continue
        if name in ("--hidden", "-."): hidden = True
        if name == "--unrestricted": u += 1
        if re.fullmatch(r"-u+", x): u += len(x) - 1
        if x in _GREP_VAL or name in _GREP_VAL: k += 1 if "=" in x and x.startswith("--") else 2; continue
        k += 1
    if u >= 2 or (b == "ag" and u >= 1): hidden = True
    roots = pos if have else pos[1:]
    return (roots or (["."] if rec else [])), excl, incl, xd, restricted, hidden, rec

def _tree_spec(b, w, k, st):
    """(roots, excl, incl, excl_dirs, restricted, hidden, dest_must_be_in_lane) for a command that reads or copies whole folders, else None."""
    a = [x for i, x in enumerate(w[k + 1:], k + 1) if i not in data_of(st)] if b in GREPS else w[k + 1:]
    if b in ("grep", "egrep", "fgrep", "zgrep", "rg", "ag", "ack", "pcregrep"):
        roots, excl, incl, xd, restricted, hidden, rec = _parse_grep(b, w[k + 1:])
        return (roots, excl, incl, xd, restricted, hidden, None) if rec else None
    if b in ("diff", "colordiff"):
        rec = any(x in ("--recursive", "-r", "-R") or re.fullmatch(r"-[A-Za-z]*[rR][A-Za-z]*", x) for x in a if not x.startswith("--") or x == "--recursive")
        if not rec: return None
        excl = []; pos = []; i = 0
        while i < len(a):
            x = a[i]
            if x in ("-x", "--exclude"): excl.append(a[i + 1] if i + 1 < len(a) else ""); i += 2; continue
            if x.startswith("--exclude="): excl.append(x[10:])
            elif not x.startswith("-"): pos.append(x)
            i += 1
        return pos, excl, [], [], False, True, None
    if b == "tar":
        mode = ""; pos = []; excl = []; chdir = None; i = 0
        for j, x in enumerate(a):
            if j == 0 and not x.startswith("-") and re.fullmatch(r"[A-Za-z]+", x): mode += x
            elif x.startswith("-") and not x.startswith("--") and re.fullmatch(r"-[A-Za-z]+", x): mode += x[1:]
            elif x in ("--create", "--append", "--update"): mode += "c"
        if not any(ch in mode for ch in "cru"): return None
        while i < len(a):
            x = a[i]
            if x in ("-C", "--directory"): chdir = a[i + 1] if i + 1 < len(a) else None; i += 2; continue
            if x.startswith("--directory="): chdir = x.split("=", 1)[1]
            elif x == "--exclude": excl.append(a[i + 1] if i + 1 < len(a) else ""); i += 2; continue
            elif x.startswith("--exclude="): excl.append(x[10:])
            elif x.startswith("--exclude-from="): excl += _from_file(x.split("=", 1)[1])
            elif x in ("-f", "--file", "-T", "--files-from", "--exclude-from", "-X"): i += 2; continue
            elif not x.startswith("-") and not (i == 0 and re.fullmatch(r"[A-Za-z]+", x) and mode): pos.append(x)
            i += 1
        roots = [os.path.join(chdir, r) if chdir and not os.path.isabs(r) else r for r in pos]
        return roots, excl, [], [], False, True, None
    if b == "zip":
        pos = []; excl = []; rec = False; i = 0
        while i < len(a):
            x = a[i]
            if x in ("-x", "--exclude"):
                i += 1
                while i < len(a) and not (a[i].startswith("-") and len(a[i]) > 1): excl.append(a[i]); i += 1
                continue
            if x in ("--recurse-paths",) or re.fullmatch(r"-[A-Za-z0-9]*[rR][A-Za-z0-9]*", x): rec = True
            elif not x.startswith("-"): pos.append(x)
            i += 1
        return (pos[1:], excl, [], [], False, True, None) if rec else None
    if b in ("cp", "rsync", "scp", "ditto"):
        rec = any(x in ("--recursive", "--archive") or (re.fullmatch(r"-[A-Za-z]+", x) and any(ch in x for ch in "rRa")) for x in a if x.startswith("-") and x != "-")
        if b == "ditto": rec = True
        if not rec: return None
        pos = []; excl = []; target = None; i = 0
        while i < len(a):
            x = a[i]
            if x in ("-t", "--target-directory"): target = a[i + 1] if i + 1 < len(a) else None; i += 2; continue
            if x.startswith("--target-directory="): target = x.split("=", 1)[1]
            elif x == "--exclude": excl.append(a[i + 1] if i + 1 < len(a) else ""); i += 2; continue
            elif x.startswith("--exclude="): excl.append(x[10:])
            elif x.startswith("--exclude-from="): excl += _from_file(x.split("=", 1)[1])
            elif (b == "rsync" and x in ("-e", "--rsh", "-f", "--filter", "--include")) or (b == "scp" and x in ("-P", "-i", "-l", "-F", "-o", "-S", "-J", "-c")): i += 2; continue
            elif not x.startswith("-"): pos.append(x)
            i += 1
        if target is not None: return pos, excl, [], [], False, True, target
        if len(pos) < 2: return None
        return pos[:-1], excl, [], [], False, True, pos[-1]
    if b == "find":
        roots = []; i = 0
        while i < len(a) and a[i] in ("-H", "-L", "-P"): i += 1
        while i < len(a) and not (a[i].startswith("-") and a[i] != "-") and a[i] not in ("!", "(", ")", ","): roots.append(a[i]); i += 1
        expr = a[i:]; incl = []; excl = []; neg = False; maxd = None; readers = False; j = 0
        has_or = any(x in ("-o", "-or") for x in expr)
        while j < len(expr):
            x = expr[j]
            if x in ("!", "-not"): neg = not neg; j += 1; continue
            if x in ("-name", "-iname", "-path", "-ipath", "-wholename", "-iwholename") and j + 1 < len(expr):
                (excl if neg else incl).append(expr[j + 1]); neg = False; j += 2; continue
            if x == "-maxdepth" and j + 1 < len(expr) and expr[j + 1].isdigit(): maxd = int(expr[j + 1]); j += 2; continue
            if x in ("-exec", "-execdir", "-ok", "-okdir"):
                c = os.path.basename(expr[j + 1]) if j + 1 < len(expr) else ""
                if c not in SECRET_SAFE_CMDS and c not in ("echo", "printf", "true", "false", "mv"): readers = True
                j += 1
                while j < len(expr) and expr[j] not in (";", "+"): j += 1
                j += 1; neg = False; continue
            neg = False; j += 1
        if has_or: incl, excl = [], []
        return (roots or ["."]), excl, incl, [], False, True, ("reader" if readers else "noreader", maxd)
    return None

TREE_HINT = {
    "*": "exclude it explicitly (grep/tar/rsync --exclude='.env*', zip -x '.env*', rg -g '!.env*', find ! -name '.env*') -- or name the files you need",
    "grep": "add --exclude='.env*' (and --exclude='*.pem' --exclude='id_*' for keys), or search a subfolder that holds none",
    "rg": "add -g '!.env*' (and -g '!*.pem' -g '!id_*'), or search a subfolder that holds none",
    "ag": "add --ignore '.env*' (and --ignore '*.pem' --ignore 'id_*'), or search a subfolder that holds none",
    "ack": "ack cannot leave a file out by name: search a subfolder that holds none, or use grep -r --exclude='.env*'",
    "tar": "add --exclude='.env*' (and --exclude='*.pem' --exclude='id_*'), or archive a subfolder that holds none",
    "rsync": "add --exclude='.env*' (and --exclude='*.pem' --exclude='id_*'), or copy a subfolder that holds none",
    "zip": "add -x '.env*' (and -x '*.pem' -x 'id_*'), or zip a subfolder that holds none",
    "cp": "cp cannot leave a file out: copy only the files you need, or use rsync -a --exclude='.env*' (rsync --exclude) instead",
    "find": "add ! -name '.env*' (and ! -name '*.pem' ! -name 'id_*') before -exec, or point find at a subfolder that holds none",
    "diff": "add -x '.env*' (and -x '*.pem' -x 'id_*'), or compare subfolders that hold none",
}
for _b in ("egrep", "fgrep", "zgrep", "pcregrep"): TREE_HINT[_b] = TREE_HINT["grep"]
for _b in ("colordiff",): TREE_HINT[_b] = TREE_HINT["diff"]
def tree_refusal(st, as_reader_of_find=False):
    """Message if the statement reads or copies a folder below which a secret sits, else None."""
    w = st.words; data = data_of(st)
    for k in cmd_positions(st):
        if k in data or k >= len(w): continue
        b = os.path.basename(w[k])
        if b not in GREPS and b not in ("diff", "colordiff", "tar", "zip", "cp", "rsync", "scp", "ditto", "find"): continue
        spec = _tree_spec(b, w, k, st)
        if spec is None: continue
        roots, excl, incl, xd, restricted, hidden, extra = spec
        maxd = None
        if b == "find":
            if extra[0] != "reader" and not as_reader_of_find: continue
            if any(glob_names_secret(g) for g in incl):
                return SECRET_MSG + " (find hands the files it matches by a secret's name to a command that reads them)"
            maxd = extra[1]; extra = None
        for base in bases_of(st):
            if isinstance(extra, str):                          # a copy: fine if it lands inside this lane
                dest = os.path.realpath(abs_of(extra, base))
                home = os.path.realpath(f"{LANES}/{cur}") if cur else AD
                if ":" not in extra.split("/")[0] and (dest == home or dest.startswith(home + "/")): continue
            if cannot_match_secret(incl, restricted): continue
            for r in roots:
                root = os.path.realpath(abs_of(r, base))
                if not os.path.isdir(root) or not (root == AD or root.startswith(AD + "/")): continue
                found = secrets_under(root, maxd)
                if b in ("rg", "ag") and not hidden: found = [f for f in found if not any(p.startswith(".") for p in f.split("/"))]
                bad = uncovered(found, excl, incl, xd, restricted)
                if bad:
                    return (SECRET_MSG + f" (`{b}` reads everything under {os.path.relpath(root, base) if root.startswith(base) else root}, which holds {', '.join(sorted(bad)[:3])}"
                            + ("" if len(bad) <= 3 else f" and {len(bad) - 3} more") + "; " + TREE_HINT.get(b, TREE_HINT["*"]) + ")")
    return None

_XARGS_VAL = ("-I", "-J", "-L", "-n", "-P", "-s", "-E", "-d", "-a", "-l", "-R", "-S", "--arg-file", "--max-args", "--max-procs", "--delimiter", "--replace", "-j")
_GITGREP_VAL = {"-e", "-f", "-m", "--max-count", "-A", "-B", "-C", "--after-context", "--before-context", "--context", "--max-depth", "--threads", "-O", "--open-files-in-pager"}
def _git_pathspec_hit(rel, pat):
    """git's own pathspec match (no FNM_PATHNAME: `*` also crosses `/`), relative to the directory git grep runs in; a pattern that
    names a folder covers what is below it."""
    pat = pat[2:] if pat.startswith("./") else pat
    pat = pat.rstrip("/")
    return bool(pat) and (fnmatch.fnmatchcase(rel, pat) or rel.startswith(pat + "/"))
def _git_ignored(base, path):
    try: return subprocess.run(["git", "-C", base, "check-ignore", "-q", "--", path], capture_output=True, timeout=10).returncode == 0
    except Exception: return False                                              # cannot tell: counts as exposed
def git_grep_refusal(st):
    """`git grep --no-index` searches the working tree whether or not git tracks or ignores a file (a gitignored `.env` is read), and
    `--untracked` adds every untracked file that is not ignored. Both are `grep -r` over the folder, judged the same way; whether
    an untracked secret is ignored is asked of git itself (`check-ignore`), and anything that cannot be asked counts as exposed."""
    for g in git_calls([st]):
        if g.sub != "grep" or g.viaxargs: continue
        args = g.args; mode = []; specs = []; have = False; dd = False; k = 0; npos = 0
        while k < len(args):
            x = args[k]
            if dd: specs.append(x)
            elif x == "--": dd = True
            elif x in ("--no-index", "--untracked"): mode.append(x)
            elif x in ("-e", "-f"): have = True; k += 1
            elif x.startswith("-") and x != "-":
                if x in _GITGREP_VAL: k += 1
                elif x.startswith(("-e", "-f")) and not x.startswith("--"): have = True
            else:
                npos += 1
                if have or npos > 1: specs.append(x)
            k += 1
        if not mode: continue
        excl = []; pos = []
        for x in specs:
            m = _PATHSPEC_EXCL.match(x)
            if m: excl.append(x[m.end():])
            else: pos.append(x)
        for base in g.dirs:
            rb = os.path.realpath(base)
            if not (rb == AD or rb.startswith(AD + "/")): continue
            dirs = []; globs = []; plain = False
            for x in pos:
                ax = os.path.realpath(abs_of(x, rb))
                if any(c in x for c in "*?["): globs.append(x)
                elif os.path.isdir(ax) and (ax == rb or ax.startswith(rb + "/")): dirs.append(os.path.relpath(ax, rb))
                else: plain = True
            if pos and plain and not dirs and not globs: continue          # only named files: those are judged as names
            bad = []
            for rel in secrets_under(rb):
                if pos and not any(d == "." or rel.startswith(d + "/") for d in dirs) and not any(_git_pathspec_hit(rel, x) for x in globs): continue
                if any(_git_pathspec_hit(rel, x) for x in excl): continue
                if "--no-index" not in mode and _git_ignored(rb, rel): continue
                bad.append(rel)
            if bad:
                return (SECRET_MSG + f" (`git grep {' '.join(mode)}` reads {', '.join(sorted(bad)[:3])}"
                        + ("" if len(bad) <= 3 else f" and {len(bad) - 3} more") + (" even though git ignores it" if "--no-index" in mode else ", which is untracked and not ignored")
                        + "; leave it out with a pathspec -- git grep … -- ':!*.env*' ':!*.pem' ':!*id_rsa*' -- or search a subfolder, or drop the flag (plain `git grep` reads tracked files only))")
    return None

def xargs_cmd(w):
    """(index of xargs, index of the command it runs or None) for the first xargs/parallel in the words."""
    for k, x in enumerate(w):
        if os.path.basename(x) in ("xargs", "parallel"):
            j = k + 1
            while j < len(w) and w[j].startswith("-") and len(w[j]) > 1: j += 2 if w[j] in _XARGS_VAL else 1
            return k, (j if j < len(w) else None)
    return None
_DANGEROUS_CONSUMERS = {"xargs", "parallel", "read", "mapfile", "readarray", "source", "."} | SHELLS
def consumer_dangerous(c):
    w = c.words; ci = cmd_index(w)
    return ci < len(w) and os.path.basename(w[ci]) in _DANGEROUS_CONSUMERS
SAFE_ARG_CMDS = SECRET_SAFE_CMDS | {"echo", "printf", "true"}

def names_secret(st, bases=None):
    """Secret-looking names or globs among the (non-text) words and redirects of a statement."""
    data = data_of(st); bs = bases or bases_of(st); toks = []
    for k, x in forms_of(st):
        if k in data: continue
        for b in bs[:3]: toks += secret_tokens(x, b)
        toks += secret_globs(x)
    for x in redir_forms(st): toks += secret_tokens(x, bs[0]) + secret_globs(x)
    return sorted(set(toks))

def xargs_refusal(st):
    """`… | xargs cat` hands the names on its stdin to a reader. The names may come from a heredoc, a here-string, echo/printf, or from a
    producer (`ls .env`, `find . -name '*.pem'`, `find . -type f`) -- all judged as if they had been typed after `cat`."""
    xc = xargs_cmd(st.words)
    if xc is None: return None
    k, j = xc
    cmd = os.path.basename(st.words[j]) if j is not None else "echo"
    if cmd in SAFE_ARG_CMDS: return None
    t = stdin_text(st)
    if t:
        toks = [s for part in t.split() for s in secret_tokens(part, bases_of(st)[0]) + secret_globs(part)]
        if toks: return SECRET_MSG + f" (xargs feeds a reader the name {toks[0]})"
    p = st.pipe_src
    if p is not None:
        n = names_secret(p)
        if n: return SECRET_MSG + f" (its input is a list naming {n[0]}, and xargs reads those files)"
        pw = p.words; pci = cmd_index(pw)
        pb = os.path.basename(pw[pci]) if pci < len(pw) else ""
        if pb == "find":
            r = tree_refusal(p, as_reader_of_find=True)
            if r: return r
        if pb == "ls":
            flags = "".join(x[1:] for x in pw[pci + 1:] if x.startswith("-") and not x.startswith("--")) + "".join("a" for x in pw if x in ("--all", "--almost-all"))
            roots = [x for x in pw[pci + 1:] if not x.startswith("-")] or ["."]
            for base in bases_of(p):
                for r in roots:
                    root = os.path.realpath(abs_of(r, base))
                    if os.path.isdir(root) and (root == AD or root.startswith(AD + "/")):
                        found = secrets_under(root, None if "R" in flags else 1)
                        if "a" not in flags and "A" not in flags: found = [f for f in found if not any(q.startswith(".") for q in f.split("/"))]
                        if found: return SECRET_MSG + f" (it lists {found[0]}, and xargs reads the list)"
    return None

_AWK_WRITES = re.compile(r">|\|\s*\"|system\s*\(|getline|close\s*\(")
_SED_WRITES = re.compile(r"(?:^|[\d$,;{}\s/])[wWe]\s*[/\w.~$]")
def interp_refusal(st):
    """Program text handed to an interpreter (-c / -e, or a heredoc, here-string or pipe on its stdin) is read as a program."""
    w = st.words; data = data_of(st); ci = cmd_index(w)
    for k in cmd_positions(st):
        if k in data or k >= len(w) or not plausible_cmd(w, k, ci): continue
        b = os.path.basename(w[k])
        if b in ("awk", "gawk", "mawk", "nawk", "sed", "gsed"):
            # the program is the first word that is not an option (or the value of -e / --expression); `-f file` reads it from a file
            rest = w[k + 1:]; prog = []; pos = None; q = 0
            while q < len(rest):
                x = rest[q]
                if x in ("-e", "--expression", "--source") and q + 1 < len(rest): prog.append(rest[q + 1]); q += 2; continue
                if x.startswith("--expression=") or x.startswith("--source="): prog.append(x.split("=", 1)[1])
                elif x in ("-f", "--file", "-i", "-v", "-F"): q += 2; continue
                elif not x.startswith("-") and pos is None and not prog: pos = x
                q += 1
            for text in prog + ([pos] if pos else []):
                r = code_refusal(text, bases_of(st), _AWK_WRITES if b.endswith("awk") else _SED_WRITES)
                if r: return r
            continue
        flag = interp_at(w, k)
        if flag is None: continue
        kind, val = interp_invocation(w, k, flag)
        if kind == "code": text = val
        elif kind == "stdin":
            text = stdin_text(st)
            if text is None: return "An interpreter is fed a program the guard cannot read (a pipe from something other than echo/printf, or a file it cannot open), and it refuses what it cannot judge."
        else: continue
        r = code_refusal(text, bases_of(st))
        if r: return r
    return None


# ---------------------------------------------------------------- PreToolUse
LIMIT_MSG = ("The guard cannot follow this command all the way ({why}), and it refuses what it cannot judge. "
             "Split it into plain steps (one command per call, no computed program text), or ask __OWNER__.")
def collect_vars(stmts):
    """Variables a command sets for itself: `b=main`, `B=main git push`, `export F=.env`."""
    for _st in stmts[:2000]:
        _w = _st.words; _ci = cmd_index(_w)
        _names = list(_w[:_ci]) + (list(_w[_ci + 1:]) if _ci < len(_w) and _w[_ci] in ("export", "declare", "typeset", "readonly", "local") else [])
        for _x in _names:
            if _ASSIGN.match(_x) and len(VARS) < 64: VARS[_x.split("=", 1)[0].rstrip("+")] = _x.split("=", 1)[1]

if event == "PreToolUse":
    tool = data.get("tool_name")
    ti = data.get("tool_input")
    # A field of the wrong type cannot be judged, and a guard that cannot judge a call refuses it (see the
    # docstring): a crash here would let the tool run with no decision at all.
    if not isinstance(tool, str) or not (ti is None or isinstance(ti, dict)):
        deny(event, MALFORMED_MSG)
    ti = ti or {}
    if any(ti.get(k) is not None and not isinstance(ti[k], str) for k in ("command", "file_path", "notebook_path", "path", "name", "pattern", "glob", "type")):
        deny(event, MALFORMED_MSG)
    ti = {k: (v if isinstance(v, (str, dict, list)) else str(v)) for k, v in ti.items()}
    cmdA = ti.get("command", "") if tool == "Bash" else ""
    # The segments project rules (registry/rules.yaml) are matched against.
    _segs = [s.strip() for s in re.split(r"[;&|]{1,2}|\n", cmdA) if s.strip()]
    stmts = []
    if tool == "Bash":
        stmts = shell_stmts(cmdA)
        collect_vars(stmts)                  # first, so that `bash -c "$c"` can be read; again afterwards for what the inner programs set
        for _st in stmts: subst_words(_st)
        stmts = expand_stmts(stmts)
        collect_vars(stmts)
        for _st in stmts: subst_words(_st)
        walk_cwds(stmts, cwd)
        for _st in stmts[:5000]:
            for _x in _st.words:
                if _GIT_ENV.match(_x) and _st.words.index(_x) not in data_of(_st):
                    deny(event, "`" + _x.split("=")[0] + "` makes git run a command or read other settings than the repository's: not part of the work.")
    # A command made only of our own lane-* scripts is the sanctioned way to do things: they validate their own
    # arguments and know the layout. The path rules below are about ad-hoc commands, not about them.
    # lane-run / lane-gh carry someone else's command, so they are deliberately NOT exempt: what they run
    # is judged exactly as if it had been typed directly. Only OUR lane-* scripts are trusted: a bare name that is one of this
    # plane's, or a path that leads to this plane's scripts/ or bin/ (see plane_script). `scripts/lane-evil` in a repo, or
    # /tmp/lane-evil, is just another command. A redirect (other than to /dev/null) is a write the script did not ask for,
    # so it ends the exemption.
    OURS = bool(stmts) and all(st.words and ours_word(st.words[0], bases_of(st)[0]) and all(r == "/dev/null" for r in st.redirs) for st in stmts)
    # Project rules first: they only ever add a refusal, and several built-ins below answer
    # `allow` and exit, which would put the files they cover out of a project rule's reach.
    enforce_rules(event, tool, ti, _segs, cwd)
    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        fp0 = ti.get("file_path") or ti.get("notebook_path") or ""
        rp0 = os.path.realpath(abs_of(fp0, cwd)) if fp0 else ""
        msg = session_config_msg(rp0) if rp0 else None
        if msg and (cur or rp0.startswith(LANES + "/")): deny(event, msg)
        kind = plane_target(rp0) if rp0 else None
        if kind in ("memory", "knowledge"):
            # Creating a memory always goes through lane-memory, so the scope is __OWNER__'s choice.
            # Editing one that already exists is allowed from the dispatcher session only: its scope
            # is already settled, and the owner is in the conversation. Worktree sessions are always refused.
            at_root = os.path.realpath(cwd) == os.path.realpath(AD)
            if cur or not at_root or not os.path.exists(rp0):
                deny(event, MEMORY_GATE if not os.path.exists(rp0) or cur else
                     "Editing an existing memory is allowed from a dispatcher session at the control plane root, not from here.")
        if kind == "lane":
            wid = os.path.basename(rp0)[:-3]
            if cur and wid != cur: deny(event, f"That is lane '{wid}'; this session is in '{cur}'. Only its own spec may be edited from here.")
        if kind == "plane" and cur: deny(event, PLANE_GATE.format(what=os.path.relpath(rp0, AD)))
    if tool == "Bash":
        # Lane lifecycle commands act on a lane by id; from inside a lane the only id that is yours is your own.
        for name, w, j in lane_cmds(stmts):
            if cur and name in ("done", "park", "resume", "with"):
                target = first_arg(w, j)
                if target and target != cur:
                    deny(event, OTHER_LANE_MSG.format(what=f"lane {name}", target=target, cur=cur))
            if cur and (name in CONTROL_PLANE_CMDS or (name == "rules" and first_arg(w, j) == "pull")
                        or (name == "secrets" and any(a in ("add", "ignore") for a in w[j:j + 4]))):
                deny(event, CONTROL_PLANE_MSG.format(what=f"lane {name}"))
            if name == "ref":
                ra = [a for a in w[j:] if not a.startswith("-")]
                if cur and len(ra) >= 2 and ra[0] != cur and ra[1] in ("add", "rm", "remove"):
                    deny(event, OTHER_LANE_MSG.format(what=f"lane ref {ra[1]}", target=ra[0], cur=cur))
                if len(ra) >= 3 and ra[1] == "add":
                    why = ref_add_refusal(ra[2], cwd)
                    if why: deny(event, f"Not attached: {why}. A reference is readable by every session of the lane. "
                                        f"Attach the specific folder you need, not a parent of it.")
        # Judge each statement on its own: our own lane-* scripts are the approved path, even inside a compound command.
        for st in stmts:
            w0 = st.words[0] if st.words else ""
            if plane_script(w0, bases_of(st)[0]): continue
            dts = data_of(st)
            memref = any(len(x) <= 4096 and re.search(r"(?:^|/)(?:memory|knowledge)/[\w./-]+", x) for k, x in enumerate(st.words) if k not in dts) \
                or any(len(x) <= 4096 and re.search(r"(?:^|/)(?:memory|knowledge)/[\w./-]+", x) for x in st.redirs)
            writes = any(os.path.basename(x) in ("rm", "mv", "cp", "tee", "touch") for k, x in enumerate(st.words) if k not in dts) \
                or (any(os.path.basename(x) == "sed" for x in st.words) and any(re.match(r"-[a-zA-Z]*i|--in-place", x) for x in st.words)) \
                or any(re.search(r"(memory|knowledge)/", x) for x in st.redirs)
            if memref and writes and (cur or os.path.realpath(cwd) != os.path.realpath(AD)): deny(event, MEMORY_GATE)
    if tool == "EnterWorktree":
        if cur:
            # Which lane is it aiming at? Aiming at its OWN is a re-pin attempt, not an escape.
            aim = lane_of(abs_of(ti.get("path") or "", cwd)) if ti.get("path") else (ti.get("name") or "").strip("/").split("/")[0]
            if aim == cur:
                deny(event, f"You are already in lane {cur}. Nothing is wrong and there is nothing to repair — "
                            f"every repo of {cur} is already reachable from where you stand.\n"
                            f"  a command in a repo:  lane-run <repo> <cmd…>      (mvn, yarn, tests, scripts)\n"
                            f"  GitHub:               lane-gh <repo> <args…>      (pr create, pr checks, workflow run)\n"
                            f"  git:                  git -C <repo> …\n"
                            f"  files:                <repo>/path/to/file       (edit and read them directly)\n"
                            f"If the shell sits inside one repo, that is cosmetic: it changes nothing about what you can "
                            f"reach. Do not try to move it, and do not exit — carry on with the work.")
            deny(event, STAY_MSG.format(cur=cur))
        nm = (ti.get("name") or "").strip("/")
        if ti.get("path"):
            deny(event, "There is one way into a lane: EnterWorktree name=\"<lane-id>\". A path is not "
                        "accepted — it can land outside the registry, in a mirror, or in a stale worktree. "
                        "`lane-status` lists the ids.")
        if not nm:
            deny(event, "EnterWorktree needs name=\"<lane-id>\". `lane-status` lists them.")
        if "/" in nm:
            lane_id = nm.split("/")[0]
            deny(event, f"Name the lane, not a repo: EnterWorktree name=\"{lane_id}\". A session works on every "
                        f"repo of the lane at once — once inside, `cd ../<repo>` switches which one you stand "
                        f"in, and `git -C ../<repo>` needs no move at all. Never exit and re-enter to change repo.")
    if tool == "Bash" and cur:
        for g in git_calls(stmts):
            if g.sub == "worktree" and "add" in g.args: deny(event, STAY_MSG.format(cur=cur))
        for st in stmts:
            ci = cmd_index(st.words); dts = data_of(st)
            for i, x in enumerate(st.words):
                if i in dts: continue
                b = os.path.basename(x)
                if b == "lane-start" or (b == "lane" and i == ci and st.words[i + 1:i + 2] == ["start"]): deny(event, STAY_MSG.format(cur=cur))
                if (b == "lane-merge" or (b == "lane" and i == ci and st.words[i + 1:i + 2] == ["merge"])) and "--run" in st.words:
                    deny(event, f"A merge moves and removes worktrees, including this one ({cur}). Run it from the "
                                f"control plane root. From here you can only preview it: lane-merge-plan <a> <b> [options].")
    def judge_path(tp):
        """One path handed to a file tool: outside the plane, another lane's, a reference, a frozen copy."""
        a = outside_ad(tp, cwd)
        if a: deny(event, OUTSIDE_MSG.format(what=a) + ref_hint(a, cur))
        if not cur:
            lane_t = lane_of(abs_of(tp, cwd))
            if lane_t: deny(event, REACH_MSG.format(lane=lane_t))
        # inside lane: a reference reached through lanes/<id>/refs/ is readable, never writable
        mode = ref_mode(tp, cur) if cur else None
        if mode:
            if tool in ("Read", "Glob", "Grep") or mode == "rw": allow(event)
            deny(event, f"This is a read-only reference of lane '{cur}'. Read it, do not change it. (lane-ref {cur} add <path> --rw to allow edits)")
        if in_old(tp): deny(event, FROZEN_MSG)
    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit", "Read", "Glob", "Grep"):
        for key in ("file_path", "notebook_path", "path"):
            tp = ti.get(key) or ""
            if not tp: continue
            # first, so that nothing below (a reference's `allow`, say) can answer before a secret is looked at
            if tool != "Glob" and is_secret(tp, cwd): deny(event, WRITE_SECRET_MSG if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit") else SECRET_MSG)
            judge_path(tp)
        if tool == "Glob" and ti.get("pattern"):
            # the part of a Glob pattern before its first wildcard is a path like any other, and `../..` climbs out
            base_dir = re.split(r"[*?\[{]", ti["pattern"], maxsplit=1)[0]
            if base_dir: judge_path(base_dir if base_dir.startswith(("/", "~")) else os.path.join(abs_of(ti.get("path") or "", cwd) or cwd, base_dir))
        if tool == "Grep":
            # A search over a folder returns the lines of every file in it, `.env` included (the tool does not skip hidden files), so
            # a folder that holds a secret may be searched only with a filter that leaves it out: a negative glob ("!.env*") or a
            # positive one that cannot match it ("*.py"), or a file type. Glob lists names only, like `ls`, and is left alone.
            if ti.get("glob") and glob_names_secret(ti["glob"]): deny(event, SECRET_MSG)
            gdir = abs_of(ti.get("path") or "", cwd) if ti.get("path") else cwd
            gl = ti.get("glob") or ""; excl, incl = [], []
            for form in expand_braces(gl):
                for piece in form.split():
                    (excl if piece.startswith("!") else incl).append(piece[1:] if piece.startswith("!") else piece)
            if os.path.isdir(gdir) and (gdir == AD or gdir.startswith(AD + "/")) and not cannot_match_secret(incl, bool(ti.get("type"))):
                bad = uncovered(secrets_under(os.path.realpath(gdir)), excl, incl, [], restricted=False)
                if bad:
                    deny(event, SECRET_MSG + f" (Grep over {gdir} would return lines from {', '.join(sorted(bad)[:3])}"
                         + ("" if len(bad) <= 3 else f" and {len(bad) - 3} more") + "; add glob \"!.env*\" (or a glob like \"*.py\", or type) so it is left out, or search a subfolder)")
    if tool == "Bash" and cur and not OURS:
        refs_ro = [(r, ref_name(cur, r)) for r, mode in lane_refs(cur) if mode != "rw"]
        if refs_ro:
            write_ish = any(os.path.basename(x) in ("rm", "mv", "tee", "touch", "mkdir", "chmod") for st in stmts for x in st.words) \
                or any(os.path.basename(x) == "sed" and any(re.match(r"-[a-zA-Z]*i|--in-place", y) for y in st.words) for st in stmts for x in st.words) \
                or any(g.sub in ("commit", "checkout", "switch", "reset", "push", "add", "rm", "mv", "stash", "rebase", "merge", "restore", "clean")
                       for g in git_calls(stmts))
            for r, nm in refs_ro:
                touched = (r in cmdA) or (r.replace(HOME, "~") in cmdA) or (f"refs/{nm}" in cmdA)
                if touched and (write_ish or any(nm in x for st in stmts for x in st.redirs)):
                    deny(event, f"'{nm}' is a read-only reference of lane '{cur}': read it, do not change it. "
                                f"(`lane-ref {cur} add <path> --rw` if it should be editable, `lane-ref {cur} rm {nm}` to detach it)")
    if tool == "Bash" and not OURS and cmd_mentions_old(cmdA) \
       and not (cur and any(r in cmdA for r, _ in lane_refs(cur))):
        deny(event, FROZEN_MSG)
    in_mirror = os.path.realpath(cwd).startswith(REPOS + "/")
    if tool == "Bash":
        # Every path a command names is judged the way a file tool would judge it: the words themselves, the redirect
        # targets, and where their symlinks lead. Mentioning another lane is refused outright; a mirror or the plane
        # is refused only when the path is what the command WRITES. HOME, not a literal /Users/..., because that is
        # macOS-only — this rule silently never fired on Linux until a real Linux CI run caught it.
        if not OURS:
            real_of = {}
            def real(a):
                if a not in real_of: real_of[a] = os.path.realpath(a)
                return real_of[a]
            for st in stmts:
                w = st.words; ci = cmd_index(w); dts = data_of(st)
                if st.cwds is None:
                    # a cd to a computed target left the directory unknown, so a relative path that climbs cannot be placed
                    for k, x in forms_of(st):
                        if k not in dts and not os.path.isabs(x) and ".." in x.split("/"):
                            deny(event, "An earlier cd chose its directory at run time, so where `" + x + "` leads cannot be judged. Use absolute paths, or cd to a literal directory.")
                verbs = {os.path.basename(x) for k, x in enumerate(w) if k not in dts}
                git_write = any(g.sub in GIT_WRITE_SUBS for g in git_calls([st]))
                sed_i = ("sed" in verbs and any(re.match(r"-[a-zA-Z]*i|--in-place", x) for x in w)) \
                    or (verbs & {"perl", "ruby"} and any(re.match(r"-[A-Za-z0-9]*i", x) for x in w)) \
                    or ("awk" in verbs or "gawk" in verbs) and any(x in ("-iinplace", "inplace") or x == "--include=inplace" for x in w)
                for base in bases_of(st):
                    cands = stmt_cands(st, ci, base)
                    if not cands and "patch" not in verbs: continue
                    args_only = [a for k, a in cands if k in ("arg", "opt")]
                    if verbs & ALL_VERBS or sed_i or "mv" in verbs: targets = [a for k, a in cands if k != "cmd"]
                    elif verbs & LAST_VERBS:
                        dirflag = any(x == "-t" or x.startswith("--target-directory") for x in w)
                        targets = args_only if dirflag else args_only[-1:]
                    elif git_write:
                        cs = [c for g in git_calls([st]) for c in g.C]
                        targets = [abs_of(c, base) for c in cs] if cs else [a for k, a in cands if k != "cmd"]
                    else: targets = []
                    targets += [a for k, a in cands if k == "redir"]
                    if "patch" in verbs and not args_only: targets.append(base)           # patch -p1 < x.diff edits what the diff names, from the cwd
                    for kind, a in cands:
                        r = a if kind == "cmd" else real(a)           # the program being run is not followed through its links (.venv/bin/python)
                        # another lane: any mention at all
                        lane_t = _lane_id(r)
                        if lane_t and lane_t != cur:
                            deny(event, REACH_MSG.format(lane=lane_t) if not cur else STAY_MSG.format(cur=cur))
                        o = outside_of(a, resolve=kind != "cmd", real=None if kind == "cmd" else r)
                        if o: deny(event, OUTSIDE_MSG.format(what=o) + ref_hint(o, cur))
                        if a == REPOS or a.startswith(REPOS + "/"): in_mirror = True
                    if base == REPOS or base.startswith(REPOS + "/"): in_mirror = True
                    # `rm <link>` removes the link, never what it points at: the one write that may name a link into a mirror.
                    rm_only = bool(verbs & {"rm", "unlink"}) and not (verbs & (ALL_VERBS - {"rm"})) and "mv" not in verbs and not sed_i \
                        and not git_write and not st.redirs and not (verbs & LAST_VERBS) and not any(x.endswith(("/", "/.", "/..")) for x in w)
                    for a in targets:
                        for p in dict.fromkeys((a, real(a))):
                            if p == REPOS or p.startswith(REPOS + "/"):
                                if rm_only and link_itself(a, real): continue
                                deny(event, mirror_msg(a, p))
                        reason = write_target_verdict(a, cur, cwd)
                        if reason: deny(event, reason)
        # gh reaches the same repositories over the network. Only the irreversible ones are refused here.
        for st in stmts:
            dts = data_of(st)
            idx = [i for i, x in enumerate(st.words) if os.path.basename(x) in ("gh", "lane-gh") and i not in dts]
            for k, i in enumerate(idx):
                end = idx[k + 1] if k + 1 < len(idx) else len(st.words)
                start = i + 2 if os.path.basename(st.words[i]) == "lane-gh" else i + 1       # lane-gh <repo> <gh args…>
                why = gh_refusal(st.words[start:end])
                if why: deny(event, why)
        # the remote and the default branches are not Claude's to change
        PROT = protected_branches(cwd, cur, cmdA)
        PROT_LIST = ", ".join(sorted(PROT))
        for g in git_calls(stmts):
            why = git_refusal(g)
            if why: deny(event, why)
            if remote_change(g) or any(re.match(r"remote\.[\w.-]+\.(url|pushurl)=|url\..+\.(push)?insteadof=", c, re.I) for c in g.cfg):
                deny(event, "Changing a git remote is never part of the work. If origin looks wrong, say so and stop.")
            if g.sub in ("symbolic-ref", "update-ref") and any(a[len("refs/heads/"):] in PROT for a in g.args if a.startswith("refs/heads/")) \
               or g.sub == "branch" and branch_hit(g, PROT):
                deny(event, f"Moving or deleting a protected branch ({PROT_LIST}) is not something to do unasked.")
            if alias_hit(g, PROT):
                deny(event, f"`git {g.sub}` is not a git subcommand this guard knows -- a user alias, which can be `push` -- and it names a protected "
                            f"branch ({PROT_LIST}). Use the real subcommand.")
            if g.sub in ("push", "send-pack", "http-push"):
                hit, force = push_hit(g, PROT)
                if g.viaxargs and g.xtra is None:
                    deny(event, "xargs would hand `git push` arguments the guard cannot read, which may name a protected branch. Write the push out.")
                if hit and force:
                    deny(event, f"Force-pushing a protected/integration branch ({PROT_LIST}) is blocked. Ask __OWNER__ explicitly if this is really intended.")
                if hit and "ALLOW_DEFAULT_BRANCH_PUSH=1" not in g.pre:
                    deny(event, f"That pushes to a protected branch ({PROT_LIST}). Ask __OWNER__ first. If they agree, run it "
                                "with the marker they can see: ALLOW_DEFAULT_BRANCH_PUSH=1 git push …")
            if g.sub == "stash" and stash_refused(g):
                deny(event, "Bare git stash/pop is unsafe here: the stash stack is shared across worktrees. Make a wip commit instead "
                            "(scripts/lane-park does this). A named `git stash push -m <name>` is the one form allowed.")
            if g.sub in MIRROR_BLOCKED and (in_mirror or any(os.path.realpath(d).startswith(REPOS + "/") for d in g.dirs)):
                deny(event, "The mirrors under repos/ stay on the default branch and clean. Only fetch/pull --ff-only/log/status/worktree are allowed there. Use scripts/lane-* for work.")
        for st in stmts:
            dts = data_of(st)
            if "rm" in {os.path.basename(x) for k, x in enumerate(st.words) if k not in dts} and any(re.fullmatch(r"-[a-zA-Z]*[rR][a-zA-Z]*|--recursive", x) for x in st.words) \
               and any(len(x) <= 4096 and (re.search(re.escape(REPOS) + r"(/|$)", x) or re.search(re.escape(LANES) + r"(/|$)", x)) for x in st.words):
                deny(event, "Deleting mirrors or worktrees by hand is blocked. Use scripts/lane-done (worktrees) or ask __OWNER__ (mirrors).")
        STAY_PUT = ("A cd moves the session itself, and once you are out of lane '{cur}' the way back is "
                    "EnterWorktree, not cd — so a single cd for convenience strands the session.\n"
                    "  lane-* scripts run from anywhere: `lane-status`, `lane-brief {cur}`, `lane-memory …` — no cd needed\n"
                    "  another repo of this lane: `git -C ../<repo> …`, or absolute paths for file tools\n"
                    "  a temporary file: write it by absolute path under /tmp")
        for st in stmts:
            if st.sub: continue                  # `( cd x )`, `$(cd x)` and `bash -c 'cd x'` move nothing outside their own process
            for raw, tl in st.cds:
                if tl is None:
                    if cur or "/lanes/" in raw or "/repos/" in raw:
                        deny(event, STAY_PUT.format(cur=cur) if cur else
                             "Do not cd into a worktree or a mirror. A cd moves the session without resuming the "
                             "lane or applying its scope. Use EnterWorktree name=\"<lane-id>\".")
                    continue
                if cur and st.cdkind == "loop":
                    deny(event, "A cd inside a loop or a function can run any number of times, so where it ends cannot be followed, and a session "
                                "that leaves its lane is stranded. Use absolute paths, `git -C`, or `lane-run <repo> <cmd>`.")
                for base, tgt in tl:
                    if cur:
                        mine = os.path.realpath(f"{LANES}/{cur}")
                        if not (tgt == mine or tgt.startswith(mine + "/")):
                            deny(event, STAY_PUT.format(cur=cur))          # leaving the lane entirely
                        # Inside the lane: the session lives at its root. Entering a repo is what made one of
                        # them look like the main one, and nothing needs it any more — lane-run does the moving.
                        tgt_repo = repo_of(tgt, cur)
                        here_repo = repo_of(base, cur)
                        if tgt_repo and tgt_repo != here_repo:
                            deny(event, f"Stay in the lane — do not cd into {tgt_repo}. Anything that must run inside a "
                                        f"repo runs there without moving the session:\n"
                                        f"  a command:  lane-run {tgt_repo} <cmd…>        (mvn, yarn, tests, scripts)\n"
                                        f"  GitHub:     lane-gh {tgt_repo} <args…>        (pr create, pr checks, workflow run)\n"
                                        f"  git:        git -C {tgt_repo} …\n"
                                        f"  files:      {tgt_repo}/path/to/file         (edit and read them directly)")
                        continue
                    if tgt == REPOS or tgt.startswith(REPOS + "/"):
                        deny(event, f"{os.path.relpath(tgt, AD)} is a read-only mirror; do not cd into it. Work happens in a "
                                    f"lane: EnterWorktree name=\"<id>\". Read it in place with `git -C` or absolute paths.")
                    lane_t = lane_of(tgt)
                    if lane_t:
                        deny(event, f"Do not cd into a lane — that skips the resume and the scope that come with it. "
                                    f"Use EnterWorktree name=\"{lane_t}\" instead.")
        # secrets: deny by default. Listing the readers meant `dd`, `gpg -d`, `git show HEAD:.env` and
        # anything else unlisted got straight through. A statement that names a secret passes only if its command is
        # one of the few that touch metadata (see secret_safe_stmt). $( ), backticks and ( ) are statements of
        # their own, so `ls $(cat .env)` is judged as the `cat .env` it contains. Text that merely MENTIONS a name (what echo
        # prints, a commit message, a heredoc body) is not a read.
        for st in stmts:
            toks = names_secret(st)
            if toks:
                if not (secret_safe_stmt(st) or cp_template_ok(st, cur)):
                    deny(event, (WRITE_SECRET_MSG if secret_write_only(st, toks) else SECRET_MSG) + f" (command references {', '.join(toks[:6])})")
                c = st.pipe_to
                while c is not None:
                    if consumer_dangerous(c):
                        deny(event, SECRET_MSG + f" (the name {toks[0]} is piped into a command that reads or runs it)")
                    c = c.pipe_to
            why = xargs_refusal(st) or interp_refusal(st) or tree_refusal(st) or git_grep_refusal(st)
            if why: deny(event, why)
        if LIMIT: deny(event, LIMIT_MSG.format(why=LIMIT[0]))

    if LIMIT: deny(event, LIMIT_MSG.format(why=LIMIT[0]))
    if tool == "Bash" and cur:
        m = re.search(re.escape(f"{LANES}/{cur}/") + r"([\w.-]+)", cmdA) or re.search(r"(?:^|\s)(?:cd|-C)\s+(?:\S*/)?lanes/" + re.escape(cur) + r"/([\w.-]+)", cmdA)
        repo = m.group(1) if m and os.path.exists(f"{LANES}/{cur}/{m.group(1)}/.git") else None
        if repo:
            # last, so that a first touch of a repo can never answer before every refusal above has had its say
            st, sp = sess_state(data.get("session_id", ""))
            if repo not in st["rules"]:
                st["rules"].append(repo); sess_save(st, sp)
                out({"hookSpecificOutput": {"hookEventName": event, "additionalContext": rules_brief(cur, repo)}})
    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit", "Read"):
        fp = ti.get("file_path") or ti.get("notebook_path") or ""
        rp = os.path.realpath(fp) if fp else ""
        if rp.startswith(REPOS + "/") and (tool != "Read" or cur):
            deny(event, f"{REPOS}/ is the read-only mirror. Work in the lane worktree under lanes/ (scripts/lane-start or lane-resume).")
        target = lane_of(rp)
        if cur and target and target != cur:
            deny(event, f"'{target}' is a different lane. This session is in '{cur}'. Ask __OWNER__ to add that repo with scripts/lane-with {cur} <repo>, or switch lanes.")
        if cur and target == cur:
            repo = repo_of(rp, cur); extra = None
            here = repo_of(cwd, cur)  # the repo the session stands in loads its own CLAUDE.md natively
            if repo and repo != here:
                st, sp = sess_state(data.get("session_id", ""))
                if repo not in st["rules"]:
                    st["rules"].append(repo); sess_save(st, sp); extra = rules_brief(cur, repo)
            o = {"hookSpecificOutput": {"hookEventName": event, "permissionDecision": "allow"}}
            if extra: o["hookSpecificOutput"]["additionalContext"] = extra
            out(o)
    if tool in ("Glob", "Grep") and cur:
        target = lane_of(abs_of(ti.get("path") or "", cwd)) if ti.get("path") else None
        if target and target != cur:
            deny(event, f"'{target}' is a different lane. This session is in '{cur}'. Ask __OWNER__ to add that repo with scripts/lane-with {cur} <repo>, or switch lanes.")
    sys.exit(0)

# ------------------------------------------------------------ PostToolUse: touched files
if event == "PostToolUse":
    tool = data.get("tool_name", "")
    # Bookkeeping only (which files a lane touched), so unlike PreToolUse a malformed body is simply ignored.
    ti = data.get("tool_input") or {}
    if not isinstance(ti, dict): ti = {}
    ti = {k: (v if isinstance(v, (str, dict, list)) else str(v)) for k, v in ti.items()}
    if not isinstance(ti.get("file_path"), (str, type(None))) or not isinstance(ti.get("notebook_path"), (str, type(None))): sys.exit(0)
    # A session that has just entered a lane gets the lane's rules (LANE.md) now: from here on Claude Code refuses its
    # Edit/Write outside the lane folder before any hook runs, so only told instructions can point it at lane-memory.
    # The lane is the one the session now sits in, or the one EnterWorktree named (`<id>` or `<id>/<repo>`).
    if tool == "EnterWorktree" and R.workspace:
        lid = cur or (ti.get("name") if isinstance(ti.get("name"), str) else "").split("/")[0]
        if lid and re.fullmatch(r"[A-Za-z0-9._-]+", lid) and lid not in (".", "..") and os.path.isfile(f"{LANES_DIR}/{lid}.md"):
            context(event, R.lane_context(lid))
        sys.exit(0)
    if cur and tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        fp = ti.get("file_path") or ti.get("notebook_path")
        if fp:
            try:
                with open(f"{LANES}/{cur}/.touched", "a") as f: f.write(os.path.realpath(fp) + "\n")
            except OSError: pass
    sys.exit(0)

# --------------------------------------------------------- UserPromptSubmit: one-line state
if event == "UserPromptSubmit":
    if cur:
        rel = os.path.relpath(os.path.realpath(cwd), AD)
        st, sp = sess_state(data.get("session_id", "")); pre = ""
        if cur not in st["mem"]:
            st["mem"].append(cur); sess_save(st, sp); pre = memory_brief(cur) + "\n\n"
        repos_here = lane_repo_dirs(cur)
        at_root = os.path.realpath(cwd) == os.path.realpath(f"{LANES}/{cur}")
        how = ""
        if len(repos_here) > 1:
            where = ("You are in the lane itself, which is the normal place to sit — no repo is home."
                     if at_root else
                     "The shell sits inside one repo — an older session lands that way. It says nothing about "
                     "which repo matters and it costs you nothing: every repo below is reachable from here by the "
                     "four routes above. Leave it alone. Do not cd, do not exit, do not re-enter — there is "
                     "nothing to repair, and the attempt just burns turns.")
            how = (f"\nAll {len(repos_here)} repos above are yours to work on right now — this is one piece of work, "
                   f"not one repo. {where}\n"
                   f"  edit any repo:    <repo>/… under lanes/{cur}/ (absolute paths work from anywhere in it)\n"
                   f"  git in a repo:    git -C <repo> …\n"
                   f"  run anything in a repo:  lane-run <repo> <cmd…>   ·   GitHub: lane-gh <repo> <args…>\n"
                   f"  do NOT cd into a repo — you never need to, and the hook refuses it\n"
                   f"  NEVER ExitWorktree/EnterWorktree to change repo — a cd does it and keeps the lane.")
        spec = f"{LANES_DIR}/{cur}.md" if R.workspace else f"registry/lanes/{cur}.md"
        context(event, pre + f"STATE of lane {cur} (every repo in it; * = where you are: {rel}). Report state only in this form:\n"
                       + state_block(cur, cwd) + R.words(how) +
                       R.words(f"\nSpec: {spec}. Never mention repos/ or the old checkouts."))
    if os.path.realpath(cwd) == os.path.realpath(AD):
        context(event, "[lane] at the dispatcher root, no lane entered. If this request is code work on a repo, first offer/enter a lane (EnterWorktree) and say so; do not edit code from here.")
    sys.exit(0)

# --------------------------------------------------------------- PreCompact: keep the spec
if event == "PreCompact":
    # The conversation is about to lose its context, so the once-per-session briefs (memory index, a repo's rules)
    # have to be injected again. This used to hang off SessionStart/compact, but SessionStart is wired to
    # scripts/session-start, never to this file, so the branch was dead.
    try: os.remove(sess_file(data.get("session_id")))
    except OSError: pass
    if cur and os.path.exists(f"{LANES_DIR}/{cur}.md"):
        spec = open(f"{LANES_DIR}/{cur}.md").read()
        context(event, R.words("Preserve through compaction — the session is in lane '%s' at %s.\n"
                        "Rules that still apply after this compaction:\n"
                        "  - the only way into a lane is EnterWorktree name=\"<id>\"; never cd into one\n"
                        "  - work only under lanes/%s/; repos/ are read-only mirrors; other lanes are out of bounds\n"
                        "  - nothing outside the control plane is readable; attach it with lane-ref and read it under refs/\n"
                        "  - never change a git remote, never move a default branch, ask before any commit or a push to main\n"
                        "  - memories go through lane-memory; __OWNER__ chooses the scope\n"
                        "  - old checkout paths in earlier turns are frozen copies; they all mean this worktree now\n"
                        "Its spec:\n%s") % (cur, cwd, cur, spec))
    sys.exit(0)

# --------------------------------------------------------------- SessionEnd: auto-log
if event == "SessionEnd":
    try: os.remove(sess_file(data.get("session_id")))
    except OSError: pass
    # Keep every transcript in exactly one project folder, under its repo. A conversation resumed from the
    # lane root may get its continuation written under the root's project folder; if the same id also
    # exists under a repos/<repo> folder, move the newer file into the repo folder and park the older one.
    sid = data.get("session_id", "")
    proj = os.path.expanduser("~/.claude/projects")
    root_slug = re.sub(r"[^A-Za-z0-9-]", "-", AD)          # how Claude Code names a project folder: everything but letters, digits and "-"
    root_f = f"{proj}/{root_slug}/{sid}.jsonl"
    if sid and os.path.exists(root_f):
        import glob as _g
        # a mirror's project folder: the slug of repos/<repo> (under .repolane/ in a workspace)
        others = _g.glob(f"{proj}/{re.sub(r'[^A-Za-z0-9-]', '-', REPOS)}-*/{sid}.jsonl")
        if len(others) == 1:
            repo_f = others[0]
            newer, older = (root_f, repo_f) if os.path.getmtime(root_f) >= os.path.getmtime(repo_f) else (repo_f, root_f)
            os.replace(older, older + ".superseded")
            if newer == root_f: os.replace(root_f, repo_f)
            with open(f"{CACHE}/transcript-moves.log", "a") as lg:
                lg.write(f"{datetime.datetime.now():%F %T} {sid}: kept newest under {os.path.dirname(repo_f)}; older -> .superseded\n")
    if cur and os.path.exists(f"{LANES_DIR}/{cur}.md"):
        touched = set()
        tf = f"{LANES}/{cur}/.touched"
        if os.path.exists(tf):
            touched = {os.path.relpath(l.strip(), f"{LANES}/{cur}") for l in open(tf) if l.strip()}; os.remove(tf)
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        parts = []; any_dirty = False
        for r in lane_repo_dirs(cur):
            b, a, be, d = repo_state(f"{LANES}/{cur}/{r}"); any_dirty |= d > 0
            parts.append(f"{r}@{b} ahead {a} behind {be} dirty {d}")
        line = f"- {now} session ended: " + "; ".join(parts)
        if touched: line += "; touched " + ", ".join(sorted(touched)[:12]) + (" …" if len(touched) > 12 else "")
        if any_dirty: line += " — UNPARKED: uncommitted work left in a worktree"
        # Every session end used to append a line, so read-only and denied runs filled the log with
        # copies of the same one. A line identical to the last one apart from its timestamp says nothing new.
        _lf = f"{LANES_DIR}/{cur}.md"
        try: _last = [l for l in open(_lf).read().splitlines() if l.strip()][-1]
        except Exception: _last = ""
        _strip = lambda l: re.sub(r"^- \d{4}-\d\d-\d\d \d\d:\d\d ", "", l)
        if not (_last.startswith("- ") and _strip(_last) == _strip(line)):
            with open(_lf, "a") as f: f.write(line + "\n")
        # Rewrite `updated:` in place. Done in python because `sed -i` needs an argument on BSD
        # and refuses one on GNU, and this runs on both.
        try:
            sp = f"{LANES_DIR}/{cur}.md"
            txt = re.sub(r"^updated: .*$", f"updated: {now[:10]}", open(sp).read(), count=1, flags=re.M)
            open(sp, "w").write(txt)
        except OSError:
            pass
    sys.exit(0)

# ------------------------------------------------- WorktreeCreate: EnterWorktree(name="<id>/<repo>")
if event == "WorktreeCreate":
    if cur:
        print(R.words(STAY_MSG.format(cur=cur)), file=sys.stderr); sys.exit(1)
    # EnterWorktree name= is interpreted by us, not by git:
    #   "<id>"          an existing lane -> resume it and land in whichever repo the work is in
    #   "<id>/<repo>"   that repo of that lane; creates the lane/worktree if needed
    name = data.get("name", "").strip("/")
    parts = [x for x in name.split("/") if x]
    known = sorted(os.listdir(REPOS))

    def repos_in(lane_id):
        f = f"{LANES_DIR}/{lane_id}.md"
        if not os.path.exists(f): return []
        head = open(f).read().split("\n---\n", 1)[0]
        return re.findall(r"^  - repo: (\S+)$", head, re.M)

    if len(parts) == 1:
        lane_id = parts[0]
        rs = repos_in(lane_id)
        if not rs:
            active = sorted(os.path.basename(f)[:-3] for f in __import__("glob").glob(f"{LANES_DIR}/*.md"))
            print(f"lane: no lane '{lane_id}'. To start new work name a repo too: <id>/<repo>.\n"
                  f"  repos: {', '.join(known)}\n  lanes: {', '.join(active)}", file=sys.stderr)
            sys.exit(1)
        # inherits LANE_PRODUCT / LANE_WORKSPACE when they were set, so it acts on the workspace this guard judged
        r = subprocess.run([f"{PRODUCT}/scripts/lane-resume", lane_id], capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stdout + r.stderr, file=sys.stderr); sys.exit(1)
        live = [x for x in rs if os.path.exists(f"{LANES}/{lane_id}/{x}/.git")]
        if not live:
            print(f"lane: lane '{lane_id}' has no worktree to enter", file=sys.stderr); sys.exit(1)
        # Sit in the lane itself, not in one of its repos. The anchor repo in that folder is what
        # makes it possible; without it git would resolve the folder to lane and Claude Code would refuse.
        if os.path.exists(f"{LANES}/{lane_id}/.git"):
            print(f"lane: in lane {lane_id}. Its repos — {', '.join(live)} — are all yours to work on; "
                  f"none is primary. Edit them at <repo>/…, run git with `git -C <repo>`, and `cd <repo>` only when a "
                  f"tool needs the working directory.", file=sys.stderr)
            print(f"{LANES}/{lane_id}"); sys.exit(0)
        # No repo of a lane is primary. A session has to start somewhere, so start where the work is:
        # uncommitted changes first, then the most recent commit. The choice changes with the work, by design.
        def recency(x):
            d = f"{LANES}/{lane_id}/{x}"
            dirty = len([l for l in git(d, "status", "--porcelain").splitlines() if l])
            when = git(d, "log", "-1", "--format=%ct") or "0"
            return (-min(dirty, 1), -int(when) if when.isdigit() else 0, x)
        here = sorted(live, key=recency)[0]
        if len(live) > 1:
            rest = [x for x in live if x != here]
            print(f"lane: a session's folder is always one repo — git needs it — so this one starts in {here}, "
                  f"where the most recent work is. That makes it no more important than {', '.join(rest)}.\n"
                  f"  to work in another repo of {lane_id}:   cd ../<repo>      (allowed, and it stays in the lane)\n"
                  f"  to start there next time:             EnterWorktree name=\"{lane_id}/<repo>\"\n"
                  f"  never exit and re-enter to switch repo — that is what a cd is for.", file=sys.stderr)
        print(f"{LANES}/{lane_id}/{here}"); sys.exit(0)

    lane_id = parts[0]
    print(f"lane: name the lane, not a repo — EnterWorktree name=\"{lane_id}\". A session works on every "
          f"repo of the lane at once; `cd ../<repo>` switches which one you stand in. A lane is created "
          f"with `lane-start {lane_id} <repo>[:<branch>][@<base>] …`.", file=sys.stderr); sys.exit(1)

if event == "WorktreeRemove":
    print(R.words("lane: worktrees are removed by scripts/lane-done after the branch is pushed. Nothing was removed."), file=sys.stderr); sys.exit(1)

sys.exit(0)
