#!/usr/bin/env python3
"""Regression tests for the lane-board server (stdlib only).

Starts the real server.py against a throwaway control plane under a temp dir, with a throwaway
HOME, so neither ~/.lane nor any real repo is ever touched. Run: python3 scripts/board/test_board.py
"""
import http.client, json, os, shutil, socket, subprocess, sys, tempfile, time, unittest, urllib.parse

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
SECRET_VALUE = "TOPSECRETVALUE-9f3a"
ROOT = PLANE = HOME = LANE_REPO = PORT = TOKEN = PROC = None


def git(*a, check=True):
    # a concurrent `git status` in the server can briefly hold .git/index.lock: retry that, nothing else
    for attempt in range(40):
        r = subprocess.run(["git", "-C", LANE_REPO, *a], capture_output=True, text=True)
        if r.returncode and "index.lock" in r.stderr and attempt < 39: time.sleep(0.1); continue
        break
    if check and r.returncode: raise RuntimeError(f"git {a}: {r.stderr}")
    return r.stdout


def write(rel, text=SECRET_VALUE + "\n"):
    p = os.path.join(LANE_REPO, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f: f.write(text)


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def req(method, path, body=None, host=None, origin=None, token=True):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=30)
    h = {"Host": f"127.0.0.1:{PORT}" if host is None else host}
    if origin is not None: h["Origin"] = origin
    if token: h["X-Token"] = TOKEN
    data = None
    if body is not None: data = json.dumps(body); h["Content-Type"] = "application/json"
    c.request(method, path, data, h)
    r = c.getresponse(); raw = r.read().decode(); c.close()
    try: return r.status, json.loads(raw)
    except ValueError: return r.status, raw


REPO_API = "/api/lanes/L1/repos/web"   # the resource; the verb is the last path segment
def post(verb, body, **kw): return req("POST", f"{REPO_API}/{verb}", body, **kw)
def get(sub="", **q):
    kw = {k: q.pop(k) for k in ("host", "origin") if k in q}
    return req("GET", REPO_API + (f"/{sub}" if sub else "") + ("?" + urllib.parse.urlencode(q) if q else ""), **kw)
Q = lambda s: urllib.parse.quote(s, safe="")   # one path segment, percent-encoded


def setUpModule():
    global ROOT, PLANE, HOME, LANE_REPO, PORT, TOKEN, PROC
    for k in ("LANE_PRODUCT", "LANE_WORKSPACE"): os.environ.pop(k, None)   # the scratch plane is both roots, by its own location
    ROOT = os.path.realpath(tempfile.mkdtemp(prefix="board-test-"))
    PLANE, HOME = f"{ROOT}/plane", f"{ROOT}/home"
    os.makedirs(HOME)
    shutil.copytree(f"{SRC}/scripts", f"{PLANE}/scripts", symlinks=True, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(f"{SRC}/bin", f"{PLANE}/bin", symlinks=True)
    if os.environ.get("BOARD_TEST_SERVER"):   # run the suite against another server.py (e.g. an older one)
        shutil.copy(os.environ["BOARD_TEST_SERVER"], f"{PLANE}/scripts/board/server.py")
    for d in ("registry/lanes", "repos/web", "memory", "knowledge", ".cache/memory-inbox"):
        os.makedirs(f"{PLANE}/{d}")
    open(f"{PLANE}/registry/repos.yaml", "w").write("repos:\n  web:\n    short: web\n    default_branch: main\n")
    open(f"{PLANE}/registry/config.yml", "w").write("owner:\n  name: tester\n")
    open(f"{PLANE}/registry/lanes/L1.md", "w").write(
        "---\nstatus: active\nticket: T-1\nupdated: 2026-01-01\nrepos:\n  - repo: web\n    branch: l1\n    base: main\n---\n\n## Goal\ntest\n")
    LANE_REPO = f"{PLANE}/lanes/L1/web"
    os.makedirs(LANE_REPO)
    env = {**os.environ, "HOME": HOME, "GIT_CONFIG_GLOBAL": f"{HOME}/.gitconfig", "GIT_CONFIG_SYSTEM": "/dev/null"}
    os.environ.update(env)
    git("init", "-q", "-b", "l1")
    git("config", "user.email", "t@example.com"); git("config", "user.name", "t")
    write("README.txt", "hi\n"); write("sub/ok.txt", "ok\n")
    git("add", "-A"); git("commit", "-q", "-m", "init")
    PORT = free_port()
    PROC = subprocess.Popen([sys.executable, f"{PLANE}/scripts/board/server.py"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, env={**env, "WS_BOARD_NO_OPEN": "1", "WS_BOARD_PORT": str(PORT),
                                 "WS_BOARD_REFRESH": "3600"})   # no background git while a test runs
    for _ in range(100):
        try:
            st, html = req("GET", "/", token=False)
            if st == 200: break
        except OSError: pass
        time.sleep(0.1)
    else: raise RuntimeError("board did not start")
    TOKEN = html.split("__T='")[1].split("'")[0]


def tearDownModule():
    if PROC: PROC.terminate(); PROC.wait()
    if ROOT and ROOT.startswith(os.path.realpath(tempfile.gettempdir())): shutil.rmtree(ROOT, ignore_errors=True)


class Base(unittest.TestCase):
    def setUp(self):
        # back to the initial commit, whatever the previous test committed
        git("reset", "-q", "--hard", git("rev-list", "--max-parents=0", "HEAD").split()[0]); git("clean", "-fdxq")

    def staged(self): return [x for x in git("diff", "--cached", "--name-only", "-z").split("\0") if x]


NEW_SECRETS = ["id_rsa", "id_ed25519", "id_ecdsa", "id_dsa", ".netrc", ".npmrc", ".pgpass", ".git-credentials", ".htpasswd",
               "a.p8", "a.jks", "a.keystore", "a.kdbx", "a.pfx", "a.p12", "service-account.json", "service-account-prod.json",
               "credentials.json", "d/ID_RSA", "d/.NETRC", "SERVICE-ACCOUNT-DEV.JSON", "Release.KEYSTORE"]


class TestStage(Base):
    def test_new_credential_names_refused(self):
        for n in NEW_SECRETS: write(n)
        for n in NEW_SECRETS:
            st, _ = post("stage", {"files": [n]})
            self.assertEqual(st, 400, n)
        self.assertEqual(self.staged(), [])

    def test_pub_key_is_not_secret(self):
        write("id_rsa.pub", "pub\n")
        st, _ = post("stage", {"files": ["id_rsa.pub"]})
        self.assertEqual(st, 200); self.assertEqual(self.staged(), ["id_rsa.pub"])

    def test_dot_does_not_stage_env(self):
        write(".env"); write("new.txt", "x\n")
        for spec in (".", "./", "*", ".e*", ":/", ":(top)", ":(glob)**", "sub/..", "", "sub/../.env"):
            st, _ = post("stage", {"files": [spec]})
            self.assertEqual(st, 400, spec)
            self.assertEqual(self.staged(), [], spec)

    def test_directory_with_secret_refused(self):
        write("d/.env"); write("d/a.txt", "x\n")
        for spec in ("d", "d/"):
            st, _ = post("stage", {"files": [spec]})
            self.assertEqual(st, 400, spec)
            self.assertEqual(self.staged(), [])

    def test_secret_name_variants_refused(self):
        names = [".ENV", ".Env.local", "KEY.PEM", "Secrets.JSON", "x/credentials-prod.json", 'we"ird.pem', "é.key", ".env", "a b.p12"]
        for n in names: write(n)
        for n in names:
            st, _ = post("stage", {"files": [n]})
            self.assertEqual(st, 400, n)
        self.assertEqual(self.staged(), [])

    def test_mixed_request_stages_nothing(self):
        write(".env"); write("good.txt", "x\n")
        st, _ = post("stage", {"files": ["good.txt", ".env"]})
        self.assertEqual(st, 400); self.assertEqual(self.staged(), [])

    def test_option_like_and_unknown_names(self):
        write("a.txt", "x\n"); write(".env")
        for spec in ("-A", "--all", "-u", "nope.txt", "../outside", "/etc/passwd"):
            st, _ = post("stage", {"files": [spec]})
            self.assertEqual(st, 400, spec)
        self.assertEqual(self.staged(), [])

    def test_glob_chars_are_literal(self):
        write(".env"); write("s*.txt", "x\n"); write("sa.txt", "y\n")
        st, _ = post("stage", {"files": ["s*.txt"]})
        self.assertEqual(st, 200); self.assertEqual(self.staged(), ["s*.txt"])

    def test_normal_file_and_dir_still_stage_and_unstage(self):
        write("one.txt", "x\n"); write("d/two.txt", "y\n"); write("d/three.txt", "z\n")
        self.assertEqual(post("stage", {"files": ["one.txt"]})[0], 200)
        self.assertEqual(self.staged(), ["one.txt"])
        self.assertEqual(post("stage", {"files": ["d"]})[0], 200)
        self.assertEqual(sorted(self.staged()), ["d/three.txt", "d/two.txt", "one.txt"])
        self.assertEqual(post("unstage", {"files": ["one.txt", "d"]})[0], 200)
        self.assertEqual(self.staged(), [])

    def test_modified_tracked_file_stages(self):
        write("README.txt", "changed\n")
        self.assertEqual(post("stage", {"files": ["README.txt"]})[0], 200)
        self.assertEqual(self.staged(), ["README.txt"])


class TestAmendAndCommit(Base):
    def test_commit_and_amend_refuse_new_credential_names(self):
        head = git("rev-parse", "HEAD")
        for n in NEW_SECRETS:
            write(n); git("add", "-f", "--", n)
            self.assertEqual(post("commit", {"message": "x"})[0], 400, n)
            self.assertEqual(post("amend", {"message": "x"})[0], 400, n)
            self.assertEqual(git("rev-parse", "HEAD"), head, n)
            git("reset", "-q"); git("clean", "-fdxq")

    def test_amend_refuses_staged_secret(self):
        head = git("rev-parse", "HEAD")
        for n in (".env", ".ENV", "d/server.pem"):
            write(n); git("add", "-f", "--", n)
            st, r = post("amend", {"message": "x"})
            self.assertEqual(st, 400, n); self.assertEqual(git("rev-parse", "HEAD"), head, n)
            git("reset", "-q"); git("clean", "-fdxq")

    def test_amend_refuses_staged_quoted_secret(self):
        head = git("rev-parse", "HEAD"); write("é.key"); git("add", "-f", "--", "é.key")
        self.assertEqual(post("amend", {"message": "x"})[0], 400)
        self.assertEqual(git("rev-parse", "HEAD"), head)

    def test_commit_refuses_staged_quoted_secret(self):
        head = git("rev-parse", "HEAD"); write('we"ird.pem'); git("add", "-f", "--", 'we"ird.pem')
        self.assertEqual(post("commit", {"message": "x"})[0], 400)
        self.assertEqual(git("rev-parse", "HEAD"), head)

    def test_amend_and_commit_still_work(self):
        write("n.txt", "x\n"); git("add", "n.txt")
        self.assertEqual(post("commit", {"message": "add n"})[0], 200)
        write("m.txt", "x\n"); git("add", "m.txt")
        self.assertEqual(post("amend", {"message": "add n and m"})[0], 200)
        self.assertEqual(git("log", "-1", "--format=%s").strip(), "add n and m")
        self.assertIn("m.txt", git("show", "--name-only", "--format=", "HEAD"))


class TestReadLeaks(Base):
    def commit_all(self, names):
        for n in names: write(n, "plain\n" if n == "ok.txt" else SECRET_VALUE + "\n")
        git("add", "-f", "--", *names); git("commit", "-q", "-m", "c"); return git("rev-parse", "HEAD").strip()

    def test_show_glob_pathspec_does_not_leak(self):
        sha = self.commit_all(["s*.json", "secrets.json"])
        st, r = get("commits/" + sha)
        self.assertEqual(st, 200)
        self.assertEqual(r["hidden"], 1)
        self.assertNotIn("secrets.json", r["diff"])

    def test_show_quoted_secret_names_do_not_leak(self):
        sha = self.commit_all(['we"ird.pem', "é.key", "ok.txt"])
        st, r = get("commits/" + sha)
        self.assertEqual(st, 200); self.assertEqual(r["hidden"], 2)
        self.assertNotIn(SECRET_VALUE, r["diff"]); self.assertIn("ok.txt", r["diff"])

    def test_show_case_variant_hidden(self):
        sha = self.commit_all([".ENV", "Secrets.YAML", "ok.txt"])
        st, r = get("commits/" + sha)
        self.assertEqual(r["hidden"], 2); self.assertNotIn(SECRET_VALUE, r["diff"])

    def test_show_new_credential_names_hidden(self):
        sha = self.commit_all(NEW_SECRETS + ["ok.txt"])
        st, r = get("commits/" + sha)
        self.assertEqual(st, 200); self.assertEqual(r["hidden"], len(NEW_SECRETS))
        self.assertNotIn(SECRET_VALUE, r["diff"]); self.assertIn("ok.txt", r["diff"])

    def test_show_pub_key_not_hidden(self):
        sha = self.commit_all(["id_rsa.pub", "ok.txt"])
        st, r = get("commits/" + sha)
        self.assertEqual(r["hidden"], 0); self.assertIn("id_rsa.pub", r["diff"])

    def test_diff_new_credential_names_flagged(self):
        for n in NEW_SECRETS: write(n)
        for n in NEW_SECRETS:
            st, r = get("diff", file=n)
            self.assertTrue(r.get("secret"), n); self.assertNotIn(SECRET_VALUE, json.dumps(r), n)

    def test_show_normal_commit_unchanged(self):
        sha = self.commit_all(["ok.txt"])
        st, r = get("commits/" + sha)
        self.assertEqual(r["hidden"], 0); self.assertIn("+plain", r["diff"])

    def test_diff_glob_and_dir_do_not_leak(self):
        write("secrets.json"); write("s*.json", "harmless\n")
        git("add", "-f", "--", "secrets.json"); git("commit", "-q", "-m", "c")
        write("secrets.json", SECRET_VALUE + "2\n"); write("s*.json", "harmless2\n")
        for staged in ("0", "1"):
            if staged == "1": git("add", "--", "s*.json")
            st, r = get("diff", file="s*.json", staged=staged)
            self.assertNotIn(SECRET_VALUE, json.dumps(r), staged)
        st, r = get("diff", file="s*.json", staged="1")
        self.assertIn("harmless2", r["diff"])

    def test_diff_directory_and_traversal_refused(self):
        write("d/.env"); write("d/a.txt", "x\n")
        outside = os.path.join(ROOT, "outside.txt")
        open(outside, "w").write(SECRET_VALUE)
        for f in ("d", "d/", ".", "../../../../outside.txt", "d/../d/.env"):
            for staged in ("0", "1"):
                st, r = get("diff", file=f, staged=staged)
                self.assertNotIn(SECRET_VALUE, json.dumps(r), (f, staged))

    def test_diff_secret_flagged_and_normal_works(self):
        write(".ENV"); write("n.txt", "plain\n")
        st, r = get("diff", file=".ENV"); self.assertTrue(r.get("secret"))
        st, r = get("diff", file="n.txt"); self.assertIn("+plain", r["diff"])
        git("add", "n.txt")
        st, r = get("diff", file="n.txt", staged="1"); self.assertIn("+plain", r["diff"])

    def test_discard_literal(self):
        write("s*.txt", "x\n"); write("sa.txt", "y\n")
        st, _ = post("discard", {"files": ["s*.txt"]})
        self.assertEqual(st, 200)
        self.assertFalse(os.path.exists(f"{LANE_REPO}/s*.txt")); self.assertTrue(os.path.exists(f"{LANE_REPO}/sa.txt"))
        st, _ = post("discard", {"files": ["s*"]})
        self.assertEqual(st, 400); self.assertTrue(os.path.exists(f"{LANE_REPO}/sa.txt"))


def raw_post(headers, body=b"", path=REPO_API + "/stage"):
    """A POST with hand-written headers over a bare socket; returns (status, hung)."""
    s = socket.create_connection(("127.0.0.1", PORT), timeout=6)
    h = f"POST {path} HTTP/1.1\r\nHost: 127.0.0.1:{PORT}\r\nX-Token: {TOKEN}\r\n" + "".join(f"{k}: {v}\r\n" for k, v in headers.items()) + "\r\n"
    s.sendall(h.encode() + body)
    try:
        data = s.recv(4096)
    except socket.timeout:
        return None, True
    finally:
        s.close()
    return int(data.split()[1]) if data else None, False


class TestRenameOfSecret(Base):
    def track_env(self):
        write(".env"); git("add", "-f", "--", ".env"); git("commit", "-q", "-m", "env")

    def test_staged_rename_of_env_is_secret(self):
        self.track_env(); git("mv", ".env", "notes.txt")
        st, r = get("diff", file="notes.txt", staged="1")
        self.assertNotIn(SECRET_VALUE, json.dumps(r)); self.assertTrue(r.get("secret"))
        st, r = post("stage", {"files": ["notes.txt"]}); self.assertEqual(st, 400)
        head = git("rev-parse", "HEAD")
        st, r = post("commit", {"message": "rename"}); self.assertEqual(st, 400)
        self.assertEqual(git("rev-parse", "HEAD"), head)
        st, r = post("amend", {"message": "rename"}); self.assertEqual(st, 400)
        self.assertEqual(git("rev-parse", "HEAD"), head)

    def test_show_of_rename_commit_withholds(self):
        self.track_env(); git("mv", ".env", "notes.txt"); git("commit", "-q", "-m", "mv")
        st, r = get("commits/" + git("rev-parse", "HEAD").strip())
        self.assertNotIn(SECRET_VALUE, json.dumps(r)); self.assertGreaterEqual(r["hidden"], 1)

    def test_files_list_marks_rename_secret(self):
        self.track_env(); git("mv", ".env", "notes.txt")
        post("pull", {})   # refreshes the cache
        st, r = get()
        self.assertTrue([f for f in r["files"] if f["file"] == "notes.txt"][0]["secret"])

    def test_rename_into_secret_name_still_refused(self):
        write("plain.txt", "x\n"); git("add", "plain.txt"); git("commit", "-q", "-m", "p"); git("mv", "plain.txt", ".env")
        self.assertEqual(post("commit", {"message": "x"})[0], 400)

    def test_ordinary_rename_still_commits(self):
        write("old.txt", "some longer text\n" * 5); git("add", "old.txt"); git("commit", "-q", "-m", "o"); git("mv", "old.txt", "new.txt")
        self.assertEqual(post("commit", {"message": "rename"})[0], 200)


class TestNewlineNames(Base):
    def test_embedded_newline_secret_names(self):
        names = ["\u00e9\n.env", "a\nserver.pem", "x\n.env.local"]
        for n in names: write(n)
        for n in names:
            self.assertEqual(post("stage", {"files": [n]})[0], 400, repr(n))
            st, r = get("diff", file=n); self.assertTrue(r.get("secret"), repr(n))
        self.assertEqual(self.staged(), [])


class TestDirDiffNoLeak(Base):
    def test_directory_and_dot_with_modified_tracked_env(self):
        write("d/.env"); write("d/a.txt", "x\n"); git("add", "-f", "--", "d/.env", "d/a.txt"); git("commit", "-q", "-m", "c")
        write("d/.env", SECRET_VALUE + "-NEW\n"); write("d/a.txt", "y\n")
        for staged in ("0", "1"):
            if staged == "1": git("add", "-f", "--", "d/.env", "d/a.txt")
            for f in ("d", "d/", ".", "./"):
                st, r = get("diff", file=f, staged=staged)
                self.assertNotIn(SECRET_VALUE, json.dumps(r), (f, staged))


class TestBodyAndIds(Base):
    def test_bad_content_length(self):
        for cl in ("-1", "abc", "99999999999999999999", "1.5", " "):
            st, hung = raw_post({"Content-Length": cl, "Content-Type": "application/json"})
            self.assertFalse(hung, cl); self.assertIn(st, (400, 413), cl)
        st, hung = raw_post({"Content-Length": str(50 * 1024 * 1024)})
        self.assertFalse(hung); self.assertEqual(st, 413)

    def test_normal_post_still_works(self):
        self.assertEqual(post("stage", {"files": ["nope.txt"]})[0], 400)

    def test_brief_and_other_lane_ids_traversal(self):
        open(f"{PLANE}/registry/notes.md", "w").write("x\n")
        for bad in ("../../../notes", "..", ".", "a/b", "L1/../L1", "%2e%2e", "-x", "a\\b", "a\x00b"):
            for route in ("brief", "spec", "log", "repos/web", "repos/web/diff?file=README.txt"):
                st, r = req("GET", f"/api/lanes/{Q(bad)}/{route}")
                self.assertEqual(st, 400, (route, bad))
            self.assertEqual(req("POST", f"/api/lanes/{Q(bad)}/done", {})[0], 400, bad)
        self.assertEqual(req("GET", "/api/lanes/L1/brief")[0], 200)


class TestResourcePaths(unittest.TestCase):
    """The path names the resource. Every segment is percent-decoded once and judged like the old query values."""
    def test_traversal_in_segments_refused(self):
        open(f"{PLANE}/registry/notes.md", "w").write("x\n")
        for path in ("/api/lanes/L1/repos/..%2F..%2Frepos%2Fweb", "/api/lanes/L1/repos/%2E%2E", "/api/lanes/L1/repos/web%00",
                     "/api/lanes/L1/repos/web/commits/..%2F..%2Fx", "/api/lanes/L1/repos/web/commits/HEAD",
                     "/api/lanes/..%2Frepos/repos/web", "/api/lanes/L1%5C..%5Cx/spec", "/api/lanes/L1/repos//diff",
                     "/api/memory/cross/..%2F..%2Fcanary.md", "/api/memory/..%2F..%2Fregistry/notes.md", "/api/memory/repo:..%2F../x.md",
                     "/api/w/..%2F../board", "/api/w/nope/board", "/api/lanes/L1/repos/web%2F..%2Fweb"):
            st, r = req("GET", path)
            self.assertEqual(st, 400, path); self.assertNotIn("x\n", json.dumps(r), path)
        for path in ("/api/lanes/L1/repos/..%2Fweb/stage", "/api/lanes/..%2FL1/park", "/api/lanes/L1/refs/..%2F..%2Fetc/detach",
                     "/api/lanes/L1/refs/-rf/detach", "/api/memory/drafts/..%2Fx.md/discard", "/api/w/..%2F../lanes/L1/done"):
            self.assertEqual(req("POST", path, {"files": ["README.txt"]})[0], 400, path)

    def test_unknown_resources_are_404(self):
        for path in ("/api/repo?lane=L1&repo=web", "/api/diff?lane=L1&repo=web&file=x", "/api/show", "/api/lanelog?lane=L1",
                     "/api/lanes/L1/repos/web/nope", "/api/lanes/L1"):
            self.assertEqual(req("GET", path)[0], 404, path)
        for path in ("/api/stage", "/api/lane", "/api/lanes/L1/nope", "/api/lanes/L1/repos/web/reset", "/api/memory/cross/a.md/shred"):
            self.assertEqual(req("POST", path, {})[0], 404, path)
        self.assertEqual(req("POST", "/api/memory/cross/a.md/discard", {})[0], 400)   # discard is for drafts only

    def test_the_new_paths_answer(self):
        self.assertEqual(get()[0], 200)
        self.assertEqual(req("GET", "/api/lanes/L1/spec")[0], 200)
        self.assertEqual(req("GET", "/api/lanes/L1/log?all=1")[0], 200)
        self.assertEqual(req("GET", "/api/memory")[0], 200)
        self.assertEqual(req("GET", "/api/lanes/L1/repos/web", token=False)[0], 403)

    def test_deep_links_serve_the_page(self):
        for path in ("/", "/memory", "/memory/cross", "/memory/repo:web", "/lanes/L1", "/lanes/L1/web", "/lanes/L1/web?file=a.txt&staged=1",
                     "/lanes/L1/web/history?repos=all", "/lanes/L1/web/commits/abc1234", "/w/other/lanes/L1/web", "/w/other",
                     "/?theme=dark"):
            st, body = req("GET", path, token=False)
            self.assertEqual(st, 200, path); self.assertIn(f"__T='{TOKEN}'", body, path)
            self.assertIn('href="/board.css"', body, path); self.assertIn('src="/board.js"', body, path)
        for path in ("/nope", "/lanes", "/lanes/L1/web/bogus", "/lanes/L1/web/commits/zzz", "/lanes/..%2Fx", "/memory/../x",
                     "/memory/everything", "/w", "/lanes/L1/web/history/extra", "/index.html", "/lanes/L1%00/web"):
            st, body = req("GET", path, token=False)
            self.assertEqual(st, 404, path); self.assertNotIn(TOKEN, json.dumps(body), path)


class TestAheadAfterPlainPush(Base):
    def test_ahead_counts_against_origin_branches(self):
        bare = f"{ROOT}/origin.git"
        subprocess.run(["git", "init", "-q", "--bare", bare], check=True)
        git("remote", "add", "origin", bare)
        try:
            write("p.txt", "x\n"); git("add", "p.txt"); git("commit", "-q", "-m", "p")
            post("pull", {}); self.assertEqual(get()[1]["state"]["ahead"], 2)   # the init commit too: nothing is on origin yet
            git("push", "-q", "origin", "l1")
            post("pull", {}); self.assertEqual(get()[1]["state"]["ahead"], 0)
        finally:
            git("remote", "remove", "origin")


class TestUntrackedSecretNotDirty(Base):
    """Item 33: `lane park` leaves untracked secret files out on purpose; the board must not call them dirty work."""
    def srv(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("board_server_under_test", f"{PLANE}/scripts/board/server.py")
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

    def web(self, srv):
        board = srv.compute_board_for(PLANE)
        return next(r for w in board["lanes"] if w["id"] == "L1" for r in w["repos"] if r["repo"] == "web")

    def test_untracked_secrets_are_not_dirty(self):
        srv = self.srv()
        write(".env.local", "K=1\n"); write("id_rsa", "k\n"); write("keys/server.pem", "k\n")
        self.assertEqual(srv.repo_state(LANE_REPO)["dirty"], 0)
        r = self.web(srv)
        self.assertEqual((r["dirty"], r["staged"], r["unstaged"]), (0, 0, 0))

    def test_real_work_still_counts_next_to_secrets(self):
        srv = self.srv()
        write(".env.local", "K=1\n"); write("new.txt", "x\n")
        self.assertEqual(srv.repo_state(LANE_REPO)["dirty"], 1)
        r = self.web(srv)
        self.assertEqual((r["dirty"], r["unstaged"]), (1, 1))

    def test_tracked_modified_env_is_still_dirty(self):
        srv = self.srv()
        write(".env.tracked", "A=1\n"); git("add", "-f", ".env.tracked"); git("commit", "-q", "-m", "t")
        write(".env.tracked", "A=2\n")
        self.assertEqual(srv.repo_state(LANE_REPO)["dirty"], 1)
        self.assertEqual(self.web(srv)["unstaged"], 1)


class TestHostOrigin(unittest.TestCase):
    def test_legit_hosts_work(self):
        for h in (f"127.0.0.1:{PORT}", f"localhost:{PORT}", f"LOCALHOST:{PORT}"):
            st, body = req("GET", "/", host=h, token=False)
            self.assertEqual(st, 200, h); self.assertIn("__T='", body)
            self.assertEqual(req("GET", "/api/board", host=h)[0], 200, h)

    def test_legit_origin_works(self):
        for o in (f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"):
            self.assertEqual(req("GET", "/", origin=o, token=False)[0], 200, o)
            self.assertEqual(req("GET", "/api/board", origin=o)[0], 200, o)
            self.assertEqual(req("POST", "/api/lanes/x/nuke", {}, origin=o)[0], 404, o)

    def test_evil_host_refused_everywhere(self):
        for h in ("evil.example.com", f"evil.example.com:{PORT}", f"127.0.0.1.evil.com:{PORT}", f"localhost.evil.com:{PORT}",
                  f"evil.com#@127.0.0.1:{PORT}", "127.0.0.1:1", ""):
            for path in ("/", "/board.js", "/board.css", "/api/board", "/api/planes", "/nope"):
                st, body = req("GET", path, host=h)
                self.assertEqual(st, 403, (h, path))
                self.assertNotIn(TOKEN, json.dumps(body), (h, path))
            self.assertEqual(req("GET", "/", host=h, token=False)[0], 403, h)
            self.assertEqual(req("POST", REPO_API + "/stage", {"files": ["x"]}, host=h)[0], 403, h)

    def test_rebinding_style_origin_refused(self):
        for o in ("http://evil.example.com", f"http://evil.example.com:{PORT}", f"http://127.0.0.1.evil.com:{PORT}", "null",
                  f"https://127.0.0.1:{PORT}", f"http://127.0.0.1:{PORT + 1}", "http://localhost", "file://"):
            self.assertEqual(req("GET", "/", origin=o, token=False)[0], 403, o)
            self.assertEqual(req("GET", "/api/board", origin=o)[0], 403, o)
            self.assertEqual(req("POST", REPO_API + "/stage", {"files": ["x"]}, origin=o)[0], 403, o)

    def test_token_still_required(self):
        self.assertEqual(req("GET", "/api/board", token=False)[0], 403)


class TestMemory(unittest.TestCase):
    def setUp(self):
        self.canaries = [f"{PLANE}/canary.md", f"{ROOT}/canary.md", f"{PLANE}/memory/canary.md"]
        for c in self.canaries: open(c, "w").write("canary\n")

    def tearDown(self):
        for c in self.canaries[:2]:
            if os.path.exists(c): os.remove(c)

    def alive(self):
        for c in self.canaries: self.assertTrue(os.path.exists(c), c)

    def mem(self, body):
        """The old {action, file, to, lane} cases, sent the new way: /api/memory/<scope>/<file>/<verb>."""
        act, f = body["action"], body.get("file", "")
        scope, verb = {"drop": ("drafts", "discard"), "file": ("drafts", "file"), "rm": ("cross", "delete"), "move": ("cross", "move")}[act]
        return req("POST", f"/api/memory/{scope}/{Q(f)}/{verb}", {k: v for k, v in body.items() if k in ("to", "lane")})

    def test_traversal_slugs_rejected(self):
        bad = ["../x.md", "../../canary.md", "a/b.md", "a/../../canary.md", "..md", "/etc/passwd.md", "-rf.md", "a b.md", "x\n.md", "..", ".md", "a*.md", ""]
        for f in bad:
            for body in ({"action": "drop", "file": f}, {"action": "rm", "file": f}, {"action": "file", "file": f, "to": "cross"},
                         {"action": "file", "file": f, "to": "pref"}, {"action": "move", "file": f, "to": "cross"}):
                st, r = self.mem(body)
                self.assertEqual(st, 400, body); self.alive()

    def test_traversal_scopes_rejected(self):
        open(f"{PLANE}/.cache/memory-inbox/ok.md", "w").write("---\nname: ok\ndescription: d\n---\nb\n")
        for to in ("repo:../..", "repo:a/b", "../..", "repo:", "repo:-x", "repo:..", "repo:.", "lane"):
            for act, extra in (("move", {"file": "ok.md"}), ("file", {"file": "ok.md"})):
                st, r = self.mem({"action": act, "to": to, **extra, **({"lane": "../.."} if to == "lane" else {})})
                self.assertEqual(st, 400, (act, to)); self.alive()
            self.assertTrue(os.path.exists(f"{PLANE}/.cache/memory-inbox/ok.md"), to)
        self.assertEqual(self.mem({"action": "file", "file": "ok.md", "to": "lane", "lane": "../.."})[0], 400)
        self.assertEqual(self.mem({"action": "file", "file": "ok.md", "to": "lane", "lane": "a/b"})[0], 400)

    def test_traversal_never_reaches_lane_memory(self):
        marker = f"{ROOT}/invoked"
        orig = f"{PLANE}/scripts/lane-memory"   # the file itself: bin/lane-memory is a link to it, the server runs either
        os.rename(orig, orig + ".real")
        open(orig, "w").write(f'#!/bin/sh\necho "$@" >> {marker}\n'); os.chmod(orig, 0o755)
        try:
            self.mem({"action": "drop", "file": "../../canary.md"})
            self.mem({"action": "rm", "file": "../canary.md"})
            self.assertFalse(os.path.exists(marker))
            self.assertEqual(self.mem({"action": "drop", "file": "fine-1.0_x.md"})[0], 200)
            self.assertTrue(os.path.exists(marker))
        finally:
            os.remove(orig); os.rename(orig + ".real", orig)

    def test_normal_slugs_still_work(self):
        inbox = f"{PLANE}/.cache/memory-inbox"
        def draft(n): open(f"{inbox}/{n}.md", "w").write(f"---\nname: {n}\ndescription: d\n---\nbody\n")
        draft("note-1"); draft("note.two_x"); draft("gone")
        st, r = self.mem({"action": "file", "file": "note-1.md", "to": "cross"}); self.assertEqual(st, 200, r)
        self.assertTrue(os.path.exists(f"{PLANE}/memory/note-1.md"))
        st, r = self.mem({"action": "move", "file": "note-1.md", "to": "repo:web"}); self.assertEqual(st, 200, r)
        self.assertTrue(os.path.exists(f"{PLANE}/memory/web/note-1.md"))
        st, r = self.mem({"action": "file", "file": "note.two_x.md", "to": "repo:web"}); self.assertEqual(st, 200, r)
        st, r = self.mem({"action": "drop", "file": "gone.md"}); self.assertEqual(st, 200, r)
        self.assertFalse(os.path.exists(f"{inbox}/gone.md"))
        st, r = self.mem({"action": "rm", "file": "note-1.md"}); self.assertEqual(st, 200, r)
        self.assertFalse(os.path.exists(f"{PLANE}/memory/web/note-1.md"))
        for c in self.canaries: self.assertTrue(os.path.exists(c), c)


class TestTrackerUrl(unittest.TestCase):
    """A blank tracker.url must mean "no link", not whatever key follows it in the file."""
    def url(self, cfg):
        import importlib.util
        spec = importlib.util.spec_from_file_location("board_server_under_test", f"{SRC}/scripts/board/server.py")
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        d = tempfile.mkdtemp(prefix="tracker-test-")
        try:
            os.makedirs(f"{d}/registry")
            if cfg is not None: open(f"{d}/registry/config.yml", "w").write(cfg)
            return mod.tracker_url(d)
        finally: shutil.rmtree(d, ignore_errors=True)

    def test_blank_url_is_empty(self):
        self.assertEqual(self.url("owner:\n  name: t\ntracker:\n  url:\nlanes:\n  x: 1\n"), "")
        self.assertEqual(self.url("tracker:\n  url:   \nlanes:\n  url: https://wrong/{key}\n"), "")
        self.assertEqual(self.url('tracker:\n  url: ""\nlanes:\n  x: 1\n'), "")
        self.assertEqual(self.url("tracker:\n  url: # none yet\nlanes:\n"), "")

    def test_no_tracker_or_no_file_is_empty(self):
        self.assertEqual(self.url("owner:\n  name: t\n"), "")
        self.assertEqual(self.url(None), "")

    def test_configured_url_still_works(self):
        self.assertEqual(self.url("tracker:\n  url: https://x.atlassian.net/browse/{key}\nlanes:\n  a: b\n"),
                         "https://x.atlassian.net/browse/{key}")
        self.assertEqual(self.url('tracker:\n  url: "https://l.app/i/{key}"\n'), "https://l.app/i/{key}")


class TestDesignTokens(unittest.TestCase):
    """board.css is the single source of design tokens: colours, font families, font sizes and radii live in its
    two :root blocks (light, and :root[data-theme="dark"]) and nowhere else; the page carries no inline styles."""
    HERE = os.path.dirname(os.path.realpath(__file__))
    SPRITE = '<svg width="0" height="0" style="position:absolute"'   # the icon sprite must not take up space

    def css_outside_tokens(self):
        import re
        css = re.sub(r"/\*.*?\*/", "", open(f"{self.HERE}/board.css").read(), flags=re.S)
        # @font-face is where a family name is defined: allowed, but only for files the server ships from fonts/
        faces = re.findall(r"@font-face\s*\{[^}]*\}", css)
        for f in faces:
            self.assertTrue(re.search(r'src:url\("/fonts/[\w.-]+\.woff2"\)', f), f)
            name = re.search(r'/fonts/([\w.-]+\.woff2)', f).group(1)
            self.assertTrue(os.path.exists(f"{self.HERE}/fonts/{name}"), name)
        css = re.sub(r"@font-face\s*\{[^}]*\}", "", css)
        for head in (":root{", ':root[data-theme="dark"]{'):
            self.assertEqual(css.count(head), 1, f"exactly one {head} block")
            i = css.index(head); depth = 0
            for j in range(i, len(css)):
                depth += {"{": 1, "}": -1}.get(css[j], 0)
                if css[j] == "}" and depth == 0: break
            css = css[:i] + css[j + 1:]
        self.assertNotIn(":root", css, "a :root rule outside the two token blocks")
        self.assertNotIn("prefers-color-scheme", css, "dark is defined once, on :root[data-theme=dark]")
        # declarations only: the innermost {...} bodies (selectors like #fbar must not read as colours)
        return [d.strip() for body in re.findall(r"\{([^{}]*)\}", css) for d in body.split(";") if ":" in d]

    def test_css_has_no_literals_outside_tokens(self):
        import re
        bad = []
        for d in self.css_outside_tokens():
            prop, val = (x.strip() for x in d.split(":", 1))
            if re.search(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?)\(", val): bad.append(f"colour literal: {d}")
            if prop == "font-family" and not re.fullmatch(r"var\(--[\w-]+\)", val): bad.append(f"font family: {d}")
            if prop == "font" and (re.search(r"['\"]", val) or not re.search(r"var\(--(?:sans|mono|serif)\)\s*(?:!important)?$", val)):
                bad.append(f"font family: {d}")
            if prop in ("font", "font-size") and re.search(r"\d(?:\.\d+)?px", val): bad.append(f"px font size: {d}")
            if prop.startswith("border") and "radius" in prop and re.search(r"\d(?:\.\d+)?(?:px|%)", val):
                bad.append(f"radius literal: {d}")
        self.assertEqual(bad, [], "\n" + "\n".join(bad))

    def test_no_inline_styles(self):
        import re
        for name in ("index.html", "board.js"):
            src = open(f"{self.HERE}/{name}").read().replace(self.SPRITE, "")
            self.assertEqual(re.findall(r".{0,40}\bstyle\s*=.{0,40}", src), [], name)


if __name__ == "__main__":
    unittest.main(verbosity=1)
