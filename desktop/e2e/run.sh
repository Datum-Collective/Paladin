#!/usr/bin/env bash
# Click-through test of the real app. Needs: frontend built (frontend/dist), backend venv, git.
set -euo pipefail
cd "$(dirname "$0")/.."
T="$(mktemp -d)"
REPO="$T/vuln-e2e"; mkdir -p "$REPO"
cat > "$REPO/app.py" <<'PY'
import sqlite3, subprocess
from flask import request
def find():
    uid = request.args.get("id")
    c = sqlite3.connect("x")
    return c.execute("SELECT * FROM users WHERE id = " + uid).fetchall()
def run():
    subprocess.call(request.args.get("c"), shell=True)
SECRET = "AKIAIOSFODNN7EXAMPLE"
PY
( cd "$REPO" && git init -q && git add . && GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t git commit -q -m init )
BAD="$T/broken-e2e"; mkdir -p "$BAD/.git"      # has a .git entry but is not a repository: the clone must fail
export E2E_REPO="$REPO" E2E_BADREPO="$BAD"
export E2E_LOG='May 14 13:05:11 WEB-BO-01 sshd[912]: Accepted password for www-data from 185.199.110.42 port 51544 ssh2'
export PALADIN_E2E="$PWD/e2e/run.js"
OUT="$(npx electron . --user-data-dir="$T/ud" 2>&1 | grep -E '^E2E_' || true)"
python3 - "$OUT" <<'PY'
import json, sys
line = sys.argv[1]
if not line.startswith("E2E_RESULT"):
    print(line or "no output (the app did not start)"); sys.exit(2)
data = json.loads(line[len("E2E_RESULT "):])
bad = 0
for r in data["results"]:
    print(("PASS " if r["ok"] else "FAIL ") + r["name"] + (f"  [{r['note']}]" if r["note"] else ""))
    bad += 0 if r["ok"] else 1
if data["jsErrors"]:
    print("\nJS errors seen:"); [print("  -", e) for e in data["jsErrors"]]
print(f"\n{len(data['results']) - bad}/{len(data['results'])} passed")
sys.exit(1 if bad else 0)
PY
