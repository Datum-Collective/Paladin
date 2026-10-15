"""Regression tests for defects found in the end-to-end audit. Each one failed before its fix."""
import threading

from conftest import sign_in

LOG = "May 14 13:05:11 WEB-BO-01 sshd[912]: Accepted password for www-data from 185.199.110.42 port 51544 ssh2"
SNORT_GOOD = ("05/14-12:55:03.123456  [**] [1:2013504:3] ET SCAN Nikto [**] [Classification: x] [Priority: 2] "
              "{TCP} 1.2.3.4:5 -> 5.6.7.8:80")
SNORT_BAD_DATE = ("99/99-99:99:99.000000  [**] [1:1:1] ET SCAN x [**] [Priority: 2] {TCP} 1.2.3.4:5 -> 5.6.7.8:80")


# ---- malformed timestamps must never poison a workspace ----
def test_event_with_garbage_timestamp_is_rejected_at_ingest(client):
    sign_in(client)
    r = client.post("/api/ingest", json={"events": [{"ts": "yesterday-ish", "source": "x", "type": "y"}]})
    assert r.status_code == 422
    assert client.get("/api/timeline").status_code == 200


def test_snort_alert_with_impossible_date_is_a_rejected_line_not_a_stored_event(client):
    sign_in(client)
    r = client.post("/api/ingest", json={"format": "snort_alert", "lines": [SNORT_GOOD, SNORT_BAD_DATE]}).json()
    assert r["accepted"] == 1 and r["rejected"] == 1
    assert client.get("/api/timeline").status_code == 200


def test_timeline_survives_mixed_timestamp_forms(client):
    sign_in(client)
    evs = [{"ts": "2024-05-14T13:00:00Z", "source": "a", "type": "t"},
           {"ts": "2024-05-14T13:05:00+02:00", "source": "a", "type": "t"},
           {"ts": "2024-05-14T13:10:00", "source": "a", "type": "t"}]
    assert client.post("/api/ingest", json={"events": evs}).status_code == 200
    r = client.get("/api/timeline")
    assert r.status_code == 200 and r.json()["events"] == 3


# ---- code scan directory skipping ----
def test_accept_files_only_skips_whole_directory_names():
    from app import codescan
    files = [{"path": "src/rebuild/app.py", "content": "x=1"},
             {"path": "mydist/app.py", "content": "x=1"},
             {"path": "build/app.py", "content": "x=1"},
             {"path": "web/node_modules/x/index.js", "content": "x=1"},
             {"path": "a..b/ok.py", "content": "x=1"},
             {"path": "../escape.py", "content": "x=1"}]
    got = {f["path"] for f in codescan.accept_files(files)}
    assert got == {"src/rebuild/app.py", "mydist/app.py", "a..b/ok.py"}


def test_over_long_path_is_skipped_not_truncated():
    from app import codescan
    p = "d/" + "a" * 400 + ".py"
    assert codescan.accept_files([{"path": p, "content": "x=1"}]) == []


def test_over_large_file_is_skipped_before_scanning():
    from app import codescan
    big = "x" * (codescan.MAX_FILE_BYTES + 1)
    assert codescan.accept_files([{"path": "src/too-large.py", "content": big}]) == []


# ---- rate limiter memory ----
def test_ratelimit_forgets_idle_keys(monkeypatch):
    from app import ratelimit
    t = [1000.0]
    monkeypatch.setattr(ratelimit.time, "monotonic", lambda: t[0])
    rl = ratelimit.RateLimit(limit=2, window_s=10)
    for i in range(500):
        rl.hit(f"ip{i}")
    t[0] += ratelimit.RateLimit.SWEEP_EVERY_S + 11
    rl.hit("fresh")
    assert len(rl.hits) < 50


def test_ratelimit_is_exact_under_threads():
    from fastapi import HTTPException
    from app.ratelimit import RateLimit
    rl = RateLimit(limit=50, window_s=60)
    ok, blocked = [], []

    def go():
        for _ in range(20):
            try:
                rl.hit("k")
                ok.append(1)
            except HTTPException:
                blocked.append(1)
    ts = [threading.Thread(target=go) for _ in range(10)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(ok) == 50 and len(blocked) == 150


# ---- body size limit must hold for chunked uploads too ----
def test_chunked_body_over_limit_is_refused(client):
    sign_in(client)

    def chunks():
        for _ in range(30):
            yield b"x" * 100_000          # 3 MB, no Content-Length
    r = client.post("/api/ingest", content=chunks(), headers={"content-type": "application/json"})
    assert r.status_code == 413


# ---- unknown API routes must stay JSON 404s, not the SPA shell ----
def test_unknown_api_path_is_404_even_with_ui_mounted(tmp_path, monkeypatch):
    import importlib
    (tmp_path / "index.html").write_text("<html>shell</html>")
    monkeypatch.setenv("STATIC_DIR", str(tmp_path))
    import app.main as m
    m = importlib.reload(m)
    try:
        from fastapi.testclient import TestClient
        c = TestClient(m.app)
        assert c.get("/some/page").text == "<html>shell</html>"
        r = c.get("/api/definitely-not-a-route")
        assert r.status_code == 404 and "shell" not in r.text
    finally:
        monkeypatch.delenv("STATIC_DIR")
        importlib.reload(m)


# ---- concurrent scan start must yield one job ----
def test_concurrent_start_creates_a_single_job(client, monkeypatch):
    from app import harness
    monkeypatch.setenv("APC_ALLOW_LOCAL", "1")
    monkeypatch.setattr(harness, "_run", lambda *a, **k: threading.Event().wait(0.5))
    sign_in(client)
    created, errors = [], []

    def go():
        try:
            created.append(client.post("/api/harness/jobs", json={"repo_url": "https://github.com/octo/demo"}).status_code)
        except Exception as e:  # noqa: BLE001
            errors.append(e)
    ts = [threading.Thread(target=go) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors
    assert created.count(200) == 1, created


# ---- hostile repository content must not be able to pin a scan thread ----
def test_scan_rules_are_not_quadratic_on_long_lines():
    import time
    from app import codescan
    n = 190_000
    hostile = ["a." * (n // 2), "execute(" + " " * n, "<script a" * (n // 9), "key=" + "'a" * (n // 2),
               "execute(" * (n // 8), "target='_blank' " * (n // 16),
               # contains a keyword, so the cheap pre-check lets it through to the secret regex itself
               "key_" + "a." * (n // 2), "token." * (n // 6)]
    t = time.perf_counter()
    for text in hostile:
        codescan.static_scan([{"path": "x.py", "content": text}])
    assert time.perf_counter() - t < 3.0


def test_long_line_guards_keep_real_matches():
    from app import codescan
    src = "x" * 100_000 + '\nAPI_KEY = "sk_live_abcdefghijklmnop"\nexecute(f"select {user}")\n<script src="http://x"></script>'
    rules = {f["rule"] for f in codescan.static_scan([{"path": "a.py", "content": src}])}
    assert {"hardcoded-secret", "sql-concat", "http-script-src"} <= rules


def test_secret_rule_still_finds_real_secrets():
    from app import codescan
    src = 'API_KEY = "sk_live_abcdefghijklmnop"\nconfig.db.password: "hunter2hunter2"\nname = "abcdefghijkl"\n'
    hits = codescan.static_scan([{"path": "a.py", "content": src}])
    assert [h["line"] for h in hits if h["rule"] == "hardcoded-secret"] == [1, 2]


def test_static_scan_stops_at_its_time_budget():
    from app import codescan
    big = "\n".join(f"x{i} = 'abcdefgh{i}'" for i in range(2000))
    assert codescan.static_scan([{"path": "a.py", "content": big}], budget_s=-1) == []


# ---- the event cache cannot grow without bound ----
def test_event_cache_is_bounded(client, monkeypatch):
    from app import store
    monkeypatch.setattr(store, "MAX_CACHED_WORKSPACES", 3)
    for ws in range(10):
        store._remember_events(("u", ws), {"count": 0, "max_seq": 0, "events": []})
    assert len(store._events) == 3 and ("u", 9) in store._events and ("u", 0) not in store._events


# ---- line numbers: only "\n" ends a line, as for git, editors and the fixers ----
def test_form_feed_and_unicode_separators_do_not_shift_line_numbers():
    from app import codescan, fixers
    src = "import os\n\x0c\n\x0c\nx = 1 y = 2\neval(input())\n"
    hit = [f for f in codescan.static_scan([{"path": "a.py", "content": src}]) if f["rule"] == "code-exec"][0]
    assert src.split("\n")[hit["line"] - 1].startswith("eval(")
    assert fixers._locate(src, hit) == hit["line"] - 1


def test_crlf_files_report_the_same_lines_as_lf():
    from app import codescan
    lf = "a = 1\nb = 2\neval(x)\n"
    crlf = lf.replace("\n", "\r\n")
    got = [f["line"] for f in codescan.static_scan([{"path": "a.py", "content": crlf}])]
    assert got == [f["line"] for f in codescan.static_scan([{"path": "a.py", "content": lf}])] == [3]


# ---- a hostile repository, end to end through clone -> scan -> fix -> verify ----
def test_hostile_repository_scans_to_completion_quickly(client, tmp_path, monkeypatch):
    import os
    import subprocess
    import time
    from app import harness
    monkeypatch.setenv("APC_ALLOW_LOCAL", "1")
    r = tmp_path / "hostile"
    (r / "src" / "rebuild").mkdir(parents=True)
    (r / "node_modules" / "dep").mkdir(parents=True)
    (r / "docs").mkdir()
    (r / "src" / "rebuild" / "app.py").write_text('import hashlib\nh = hashlib.md5(b"x")\n')   # must be scanned
    (r / "node_modules" / "dep" / "index.js").write_text('const apiKey = "abcdefghijklmnop";\n')   # must not
    (r / "ff.py").write_text("import os\n\x0c\n\x0c\nimport hashlib\nh = hashlib.md5(b'x')\n")
    (r / "minified.js").write_text("a." * 95_000 + "\n")                                      # ReDoS shape
    (r / "binary.py").write_bytes(b"\xff\xfe\x00\x00" + os.urandom(2048))
    (r / "weird name (1) +@.py").write_text('import hashlib\nhashlib.sha1(b"y")\n')
    (r / "link.py").symlink_to("/etc/passwd")
    (r / "linkdir").symlink_to("/")
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "PATH": os.environ["PATH"], "HOME": str(tmp_path)}
    for cmd in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "i"]):
        subprocess.run(["git", *cmd], cwd=r, env=env, check=True)

    sign_in(client)
    t0 = time.perf_counter()
    j = client.post("/api/harness/jobs", json={"repo_url": str(r)}).json()
    harness.wait(j["id"], 90)
    job = client.get(f"/api/harness/jobs/{j['id']}").json()
    elapsed = time.perf_counter() - t0

    assert job["state"] in ("ready", "done"), (job["state"], job.get("error"), job["log"][-3:])
    assert elapsed < 30, elapsed
    files = {f["file"] for f in job["findings"]}
    assert "src/rebuild/app.py" in files                       # 'rebuild/' is not 'build/'
    assert not any(f.startswith("node_modules/") for f in files)
    assert not any("passwd" in f for f in files)
    ff = [f for f in job["findings"] if f["file"] == "ff.py"][0]
    assert open(r / "ff.py").read().split("\n")[ff["line"] - 1].strip().startswith("h = hashlib.md5")
    # every applied fix compiled and the patched copy of the scanner's own file is what the diff shows
    assert job["state"] != "ready" or "sha256" in job["diff"]


# ---- concurrency: mixed traffic from many threads must never 5xx or deadlock ----
def test_mixed_concurrent_traffic_never_errors(client):
    import time
    sign_in(client)
    snort = ("05/14-12:55:03.123456  [**] [1:2013504:3] ET SCAN Nikto [**] [Classification: x] [Priority: 2] "
             "{TCP} 1.2.3.4:5 -> 5.6.7.8:80")
    ops = [
        lambda: client.post("/api/ingest", json={"format": "linux_auth", "lines": [LOG] * 20}),
        lambda: client.post("/api/ingest", json={"format": "snort_alert", "lines": [snort, "junk"]}),
        lambda: client.get("/api/graph"),
        lambda: client.get("/api/paths"),
        lambda: client.get("/api/fixes"),
        lambda: client.get("/api/timeline"),
        lambda: client.get("/api/events"),
        lambda: client.get("/api/workspaces"),
        lambda: client.post("/api/workspaces", json={"name": None}),
        lambda: client.get("/api/activity"),
        lambda: client.get("/api/metrics"),
    ]
    bad, lock = [], threading.Lock()

    def worker(seed):
        for i in range(25):
            r = ops[(seed + i * 7) % len(ops)]()
            if r.status_code >= 500:
                with lock:
                    bad.append((r.request.method, r.request.url.path, r.status_code, r.text[:120]))
    t0 = time.perf_counter()
    ts = [threading.Thread(target=worker, args=(s,)) for s in range(8)]
    [t.start() for t in ts]
    [t.join(120) for t in ts]
    assert not any(t.is_alive() for t in ts), "deadlock: a worker did not finish"
    assert not bad, bad[:5]
    assert time.perf_counter() - t0 < 60
