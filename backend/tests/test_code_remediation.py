"""Remediation changes real files: plan -> approve -> apply -> verify -> graph updates, or rollback; conflicts refuse."""
import subprocess

import pytest

from app import codefix
from conftest import sign_in
from fakes import ALICE
from test_harness import repo, _wait  # noqa: F401  (the repo fixture: a git repo with three real findings)


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          env={"PATH": __import__("os").environ["PATH"], "HOME": str(cwd), "GIT_AUTHOR_NAME": "t",
                                "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


@pytest.fixture()
def scanned(client, world, repo, monkeypatch):
    monkeypatch.setenv("APC_ALLOW_LOCAL", "1")
    sign_in(client, ALICE)
    job = _wait(client, client.post("/api/harness/jobs", json={"repo_url": str(repo)}).json()["id"])
    assert job["state"] == "ready"
    return client, repo


def propose(client, edges=None, title="Fix"):
    edges = edges or client.get("/api/fixes").json()["cheapest_cut"]["edges"]
    return client.post("/api/remediations", json={"edges": edges, "title": title})


def test_propose_builds_a_reviewable_patch_for_the_selected_findings(scanned):
    client, repo = scanned
    r = propose(client)
    assert r.status_code == 200, r.text
    rem = r.json()
    assert rem["kind"] == "code" and rem["state"] == "proposed" and rem["finding_ids"]
    assert rem["patch"].startswith("diff --git a/server.py b/server.py") and "sha256" in rem["patch"]
    assert {f["path"] for f in rem["files"]} == {"server.py"} and rem["files"][0]["added"] > 0
    assert "Tests are not run" in rem["runbook"]
    assert client.get(f"/api/remediations/{rem['id']}/patch").text == rem["patch"]
    # proposing changes nothing on disk
    assert "sha256" not in (repo / "server.py").read_text()


def test_only_the_selected_finding_is_patched(scanned):
    client, repo = scanned
    one = client.get("/api/fixes").json()["best_single"]["edges"]
    rem = propose(client, one).json()
    assert len(rem["finding_ids"]) == 1
    assert rem["patch"].count("@@") == 2          # one hunk, not the whole file's fixes


def test_approve_execute_verify_changes_the_folder_and_removes_the_paths(scanned):
    client, repo = scanned
    before = len(client.get("/api/paths").json()["paths"])
    rid = propose(client).json()["id"]
    assert client.post(f"/api/remediations/{rid}/execute").status_code == 409     # not approved yet
    assert client.post(f"/api/remediations/{rid}/approve").json()["state"] == "approved"
    r = client.post(f"/api/remediations/{rid}/execute")
    assert r.status_code == 200 and r.json()["state"] == "executed" and "local folder" in r.json()["applied"]
    text = (repo / "server.py").read_text()
    assert "sha256" in text and "debug=False" in text and "sk-live-abcdef1234567890" not in text
    compile(text, "server.py", "exec")
    assert git(repo, "status", "--short").stdout.strip() == "M server.py"          # reviewable with plain git
    v = client.post(f"/api/remediations/{rid}/verify").json()
    assert v["state"] == "verified"
    assert v["risk_after"] < v["risk_before"] and v["paths_after"] < v["paths_before"]   # Insights' before/after table
    after = client.get("/api/paths").json()["paths"]
    assert len(after) < before
    rep = client.get("/api/codescan").json()
    assert sum(1 for f in rep["findings"] if f.get("fixed")) == len(v["finding_ids"])


def test_a_file_edited_since_the_scan_is_never_overwritten(scanned):
    client, repo = scanned
    rid = propose(client).json()["id"]
    client.post(f"/api/remediations/{rid}/approve")
    mine = (repo / "server.py").read_text().replace("hashlib.md5(", "hashlib.md5( ")   # the user edited a flagged line
    (repo / "server.py").write_text(mine)
    r = client.post(f"/api/remediations/{rid}/execute")
    assert r.status_code == 409 and "Your work is untouched" in r.json()["detail"]
    assert (repo / "server.py").read_text() == mine
    assert client.get(f"/api/remediations/{rid}").json()["state"] == "approved"      # not "executed"


def test_unrelated_local_edits_survive_apply_and_rollback(scanned):
    client, repo = scanned
    rid = propose(client).json()["id"]
    client.post(f"/api/remediations/{rid}/approve")
    p = repo / "server.py"
    p.write_text(p.read_text() + "\n# note from the user\n")
    assert client.post(f"/api/remediations/{rid}/execute").status_code == 200
    assert "# note from the user" in p.read_text() and "sha256" in p.read_text()
    assert client.post(f"/api/remediations/{rid}/verify").json()["state"] == "verified"
    r = client.post(f"/api/remediations/{rid}/rollback")
    assert r.status_code == 200 and r.json()["state"] == "rolled_back"
    text = p.read_text()
    assert "# note from the user" in text and "hashlib.md5(" in text and "sha256" not in text
    assert len(client.get("/api/paths").json()["paths"]) >= 1                       # findings are back in the graph


def test_rollback_refuses_when_the_fixed_lines_were_edited_afterwards(scanned):
    client, repo = scanned
    rid = propose(client).json()["id"]
    client.post(f"/api/remediations/{rid}/approve")
    client.post(f"/api/remediations/{rid}/execute")
    p = repo / "server.py"
    edited = p.read_text().replace("sha256", "sha512")
    p.write_text(edited)
    r = client.post(f"/api/remediations/{rid}/rollback")
    assert r.status_code == 409 and "edited after the fix" in r.json()["detail"]
    assert p.read_text() == edited


def test_verify_fails_when_a_fixed_rule_matches_again(scanned):
    client, repo = scanned
    rid = propose(client).json()["id"]
    client.post(f"/api/remediations/{rid}/approve")
    client.post(f"/api/remediations/{rid}/execute")
    p = repo / "server.py"
    p.write_text(p.read_text() + "\nimport hashlib\nx = hashlib.md5(b'a')\n")
    v = client.post(f"/api/remediations/{rid}/verify").json()
    assert v["state"] == "failed" and "weak-hash" in v["note"]
    assert not any(f.get("fixed") for f in client.get("/api/codescan").json()["findings"])


def test_exposure_edges_and_mixed_selections_are_refused_with_a_reason(scanned):
    client, _ = scanned
    r = propose(client, ["code:in:server.py"])
    assert r.status_code == 422 and "exposure" in r.json()["detail"]
    mixed = propose(client, ["code:f1", "no-such-edge"])
    assert mixed.status_code == 422


def test_remote_repositories_open_a_pull_request_with_only_the_selected_files(scanned, monkeypatch):
    client, repo = scanned
    from app import github_access
    seen = {}

    async def fake_pr(u, repo_full, title, body, commit_message, files):
        seen.update(repo=repo_full, files=files)
        return "https://github.com/alice-gh/demo/pull/7"

    monkeypatch.setattr(github_access, "open_fix_pr", fake_pr)
    rid = propose(client).json()["id"]
    from app import supa  # point the stored job at a GitHub name; the working copy is still the scanned one
    import app.remediation as remmod
    monkeypatch.setattr(remmod, "_job_repo", lambda ws, cur: "alice-gh/demo")
    client.post(f"/api/remediations/{rid}/approve")
    r = client.post(f"/api/remediations/{rid}/execute")
    assert r.status_code == 200, r.text
    assert r.json()["applied"] == "https://github.com/alice-gh/demo/pull/7"
    assert list(seen["files"]) == ["server.py"] and "sha256" in seen["files"]["server.py"]
    assert "sha256" not in (repo / "server.py").read_text()                          # the local folder is untouched
    v = client.post(f"/api/remediations/{rid}/verify").json()
    assert v["state"] == "verified" and "not merged" in v["detail"] if "detail" in v else v["state"] == "verified"
