"""Remediation changes real files: plan -> approve -> apply -> verify -> graph updates, or rollback; conflicts refuse."""
import os
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


def _remote(monkeypatch, upstream, merged=False):
    """GitHub stubbed at the module's seams: what the default branch holds, the PR it opens, whether it is merged."""
    from app import github_access
    import app.remediation as remmod
    sent = {}

    async def read(u, repo_full, paths):
        return {p: upstream.get(p) for p in paths}

    async def open_pr(u, repo_full, title, body, commit_message, files):
        sent.update(repo=repo_full, files=files)
        return "https://github.com/alice-gh/demo/pull/7"

    async def pull_merged(u, repo_full, number):
        sent["checked_pr"] = number
        return merged

    monkeypatch.setattr(github_access, "read_repo_files", read)
    monkeypatch.setattr(github_access, "open_fix_pr", open_pr)
    monkeypatch.setattr(github_access, "pull_merged", pull_merged)
    monkeypatch.setattr(remmod, "_job_repo", lambda ws, cur: "alice-gh/demo")
    return sent


def test_remote_pull_request_is_built_on_the_current_default_branch_and_verifies_only_once_merged(scanned, monkeypatch):
    client, repo = scanned
    upstream = {"server.py": (repo / "server.py").read_text() + "\n# added upstream after the scan\n"}
    sent = _remote(monkeypatch, upstream)
    rid = propose(client).json()["id"]
    client.post(f"/api/remediations/{rid}/approve")
    r = client.post(f"/api/remediations/{rid}/execute")
    assert r.status_code == 200, r.text
    assert r.json()["applied"] == "https://github.com/alice-gh/demo/pull/7"
    body = sent["files"]["server.py"]
    assert "sha256" in body and "# added upstream after the scan" in body            # upstream work is kept, not reverted
    assert "sha256" not in (repo / "server.py").read_text()                          # the local folder is untouched
    # not merged: nothing is verified and nothing leaves the graph
    v = client.post(f"/api/remediations/{rid}/verify")
    assert v.status_code == 409 and "not merged" in v.json()["detail"]
    assert client.get(f"/api/remediations/{rid}").json()["state"] == "executed"
    assert len(client.get("/api/paths").json()["paths"]) >= 1
    assert sent["checked_pr"] == 7


def test_remote_verify_checks_the_merged_files_not_the_scanned_copy(scanned, monkeypatch):
    client, repo = scanned
    fixed = (repo / "server.py").read_text().replace("hashlib.md5(", "hashlib.sha256(")
    sent = _remote(monkeypatch, {"server.py": (repo / "server.py").read_text()}, merged=True)
    rid = propose(client).json()["id"]
    client.post(f"/api/remediations/{rid}/approve")
    client.post(f"/api/remediations/{rid}/execute")
    # merged, but the default branch still holds the vulnerable code (e.g. the PR was edited): must fail
    v = client.post(f"/api/remediations/{rid}/verify").json()
    assert v["state"] == "failed" and "still matches" in v["note"]
    assert not any(f.get("fixed") for f in client.get("/api/codescan").json()["findings"])


def test_remote_refuses_when_upstream_changed_the_flagged_lines(scanned, monkeypatch):
    client, repo = scanned
    edited = (repo / "server.py").read_text().replace("hashlib.md5(", "hashlib.md5( ")
    sent = _remote(monkeypatch, {"server.py": edited})
    rid = propose(client).json()["id"]
    client.post(f"/api/remediations/{rid}/approve")
    r = client.post(f"/api/remediations/{rid}/execute")
    assert r.status_code == 409 and "changed since the scan" in r.json()["detail"] and "files" not in sent
    assert client.get(f"/api/remediations/{rid}").json()["state"] == "approved"


def test_a_double_click_applies_once(scanned):
    import concurrent.futures as cf
    client, repo = scanned
    rid = propose(client).json()["id"]
    client.post(f"/api/remediations/{rid}/approve")
    with cf.ThreadPoolExecutor(2) as ex:
        codes = sorted(ex.map(lambda _: client.post(f"/api/remediations/{rid}/execute").status_code, range(2)))
    assert codes == [200, 409]
    assert (repo / "server.py").read_text().count("hashlib.sha256(") == 1


def test_an_unapplied_proposal_can_be_discarded_without_touching_files(scanned):
    client, repo = scanned
    before = (repo / "server.py").read_text()
    rid = propose(client).json()["id"]
    r = client.post(f"/api/remediations/{rid}/rollback")
    assert r.status_code == 200 and r.json()["state"] == "rolled_back"
    assert (repo / "server.py").read_text() == before
    assert not any(f.get("fixed") for f in client.get("/api/codescan").json()["findings"])


def test_rollback_keeps_findings_another_applied_fix_still_covers(scanned):
    client, repo = scanned
    first = propose(client, client.get("/api/fixes").json()["best_single"]["edges"]).json()
    client.post(f"/api/remediations/{first['id']}/approve")
    client.post(f"/api/remediations/{first['id']}/execute")
    client.post(f"/api/remediations/{first['id']}/verify")
    # a second proposal for the same finding from the (now stale) fixes list is refused or has nothing left to patch
    again = propose(client, ["code:" + first["finding_ids"][0]])
    assert again.status_code in (200, 422)
    fixed_before = {f["id"] for f in client.get("/api/codescan").json()["findings"] if f.get("fixed")}
    assert fixed_before == set(first["finding_ids"])


def test_findings_from_a_replaced_scan_are_not_flipped_by_an_old_remediation(scanned):
    client, repo = scanned
    rid = propose(client).json()["id"]
    client.post(f"/api/remediations/{rid}/approve")
    client.post(f"/api/remediations/{rid}/execute")
    # the user adds a new weakness and rescans: finding ids restart at f1 and mean something else now
    (repo / "extra.py").write_text('import hashlib\nh = hashlib.md5(b"y")\n')
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "more")
    rescan = _wait(client, client.post("/api/harness/jobs", json={"repo_url": str(repo)}).json()["id"])
    assert rescan["findings"], "the rescan must have findings for this test to mean anything"
    # verifying the OLD remediation must not mark any of the NEW scan's findings fixed
    client.post(f"/api/remediations/{rid}/verify")
    assert not any(f.get("fixed") for f in client.get("/api/codescan").json()["findings"])


def test_paths_that_leave_the_repository_are_refused():
    for bad in ["../x.py", "/etc/passwd", "a/../../b", "C:\\x", "a\\b", ""]:
        with pytest.raises(codefix.FixError):
            codefix.safe_rel(bad)
    assert codefix.safe_rel("docs/My File.py") == "docs/My File.py"


def test_a_folder_symlink_cannot_redirect_a_write_or_read(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.py").write_text("x = 1\n")
    root = tmp_path / "repo"
    root.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(codefix.FixError):
        codefix.safe_join(root, "link/secret.py")


def test_repository_gitconfig_is_never_read(scanned, tmp_path):
    client, repo = scanned
    marker = tmp_path / "ran"
    (repo / ".gitconfig").write_text(f"[core]\n\tfsmonitor = touch {marker}\n")
    env = codefix._env()
    assert env["HOME"] != str(repo) and env["GIT_CONFIG_GLOBAL"] == os.devnull
    codefix.uncommitted(repo, ["server.py"])
    assert not marker.exists()


def test_paths_with_spaces_make_a_valid_patch(tmp_path):
    p = codefix._diff("docs/My File.py", "a = 1\n", "a = 2\n")
    assert p.startswith("diff --git a/docs/My File.py b/docs/My File.py")
    repo = tmp_path / "r"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "My File.py").write_text("a = 1\n")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    codefix.apply_local(repo, p)
    assert (repo / "docs" / "My File.py").read_text() == "a = 2\n"


def _bare_repo(tmp_path, name, data: bytes):
    repo = tmp_path / "r"
    repo.mkdir()
    (repo / name).write_bytes(data)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    return repo


def test_a_crlf_working_copy_is_patched_in_crlf_and_rolls_back_byte_for_byte(tmp_path):
    # fixes are computed from the scanned copy (LF); a Windows checkout with core.autocrlf holds CRLF
    before = b"import os\r\nx = 1\r\ny = 2\r\n"
    repo = _bare_repo(tmp_path, "m.py", before)
    p = codefix._diff("m.py", "import os\nx = 1\ny = 2\n", "import os\nx = 1\nz = 3\nw = 4\ny = 2\n")
    codefix.apply_local(repo, p)
    assert (repo / "m.py").read_bytes() == b"import os\r\nx = 1\r\nz = 3\r\nw = 4\r\ny = 2\r\n"
    codefix.apply_local(repo, p, reverse=True)
    assert (repo / "m.py").read_bytes() == before


def test_an_lf_working_copy_stays_lf(tmp_path):
    repo = _bare_repo(tmp_path, "m.py", b"a = 1\nb = 2\n")
    codefix.apply_local(repo, codefix._diff("m.py", "a = 1\nb = 2\n", "a = 1\nb = 3\n"))
    assert (repo / "m.py").read_bytes() == b"a = 1\nb = 3\n"


def test_crlf_conversion_keeps_the_no_newline_at_end_marker_right(tmp_path):
    repo = _bare_repo(tmp_path, "m.py", b"a = 1\r\nb = 2")
    p = codefix._diff("m.py", "a = 1\nb = 2", "a = 1\nb = 3")
    assert r"\ No newline at end of file" in p
    codefix.apply_local(repo, p)
    assert (repo / "m.py").read_bytes() == b"a = 1\r\nb = 3"


def test_a_crlf_file_edited_since_the_scan_is_still_refused(tmp_path):
    repo = _bare_repo(tmp_path, "m.py", b"a = 1\r\nb = 99\r\n")
    with pytest.raises(codefix.FixError, match="changed since the scan"):
        codefix.apply_local(repo, codefix._diff("m.py", "a = 1\nb = 2\n", "a = 1\nb = 3\n"))
    assert (repo / "m.py").read_bytes() == b"a = 1\r\nb = 99\r\n"


def test_a_patch_section_outside_the_folder_is_not_inspected(tmp_path):
    # the line-ending probe goes through safe_join, so a hostile path in a stored patch reads nothing outside
    (tmp_path / "secret.py").write_bytes(b"a = 1\r\n")
    repo = _bare_repo(tmp_path, "m.py", b"a = 1\n")
    hostile = "diff --git a/../secret.py b/../secret.py\n--- a/../secret.py\n+++ b/../secret.py\n@@ -1 +1 @@\n-a = 1\n+a = 2\n"
    assert codefix._for_folder(repo, hostile) == hostile
    with pytest.raises(codefix.FixError):
        codefix.apply_local(repo, hostile)
    assert (tmp_path / "secret.py").read_bytes() == b"a = 1\r\n"
