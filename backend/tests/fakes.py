"""In-memory fakes behind httpx.MockTransport: Supabase (Auth + PostgREST with row-level security) and GitHub.

The fake PostgREST enforces the same rules as supabase/migrations/*.sql: a user token sees and changes only rows
with its own user_id, writes into a workspace need that workspace to be the user's, the anon role sees nothing,
generated ids cannot be chosen, users cannot read an API key's hash, and only the service key reaches the GitHub
App tables. So an authorization bug in the app shows up as wrong data here, as it would against the real thing.
The real policies are checked separately by supabase/tests/rls_test.sql.
"""
import base64
import copy
import hashlib
import itertools
import json
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, unquote

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PRIVATE_PEM = _key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                 serialization.NoEncryption()).decode()
PUBLIC_PEM = _key.public_key().public_bytes(serialization.Encoding.PEM,
                                            serialization.PublicFormat.SubjectPublicKeyInfo).decode()
JWT_SECRET = "test-jwt-secret-test-jwt-secret-0123456789"
CLIENT_SECRET = "test-client-secret-5f1d2c"
APP_ID = "424242"
CLIENT_ID = "Iv1.testclientid"
SUPABASE_HOST = "fake.supabase.co"
ANON_KEY = "anon-key"
SERVICE_KEY = "service-key"

# supabase uid: (github id, github login)
USERS = {
    "dddddddd-0000-0000-0000-00000000000d": (100, "demo-gh"),
    "aaaaaaaa-0000-0000-0000-000000000001": (101, "alice-gh"),
    "bbbbbbbb-0000-0000-0000-000000000002": (102, "bob-gh"),
    "cccccccc-0000-0000-0000-000000000003": (103, "carol-gh"),
    "eeeeeeee-0000-0000-0000-00000000000e": (104, "other-gh"),
}
DEMO, ALICE, BOB, CAROL, OTHER = USERS


def now_iso(delta_s: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_s)).isoformat()


def access_token(uid: str, exp_in: int = 3600, iat_offset: int = 0) -> str:
    gid, login = USERS[uid]
    return jwt.encode({
        "sub": uid, "aud": "authenticated", "role": "authenticated", "email": f"{login}@users.example",
        "exp": int(time.time()) + exp_in, "iat": int(time.time()) + iat_offset,
        # user_metadata is user-editable in Supabase; the app must not trust provider_id from here
        "user_metadata": {"user_name": login, "provider_id": str(gid), "full_name": login.title(),
                          "avatar_url": f"https://avatars.example/{gid}"},
    }, JWT_SECRET, algorithm="HS256")


class PgError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


# table -> rules. ws: workspace-scoped; rls: own | select_own | none | audit; hidden: columns users cannot read
SCHEMA = {
    "profiles": {"pk": ("id",), "rls": "own_id"},
    "workspaces": {"pk": ("id",), "identity": "id", "rls": "own", "unique": [("user_id", "name_ci")],
                   "defaults": {"repo_url": None}},
    "active_ws": {"pk": ("user_id",), "rls": "own", "ws_col": "ws"},
    "prefs": {"pk": ("user_id", "key"), "rls": "own"},
    "events": {"pk": ("seq",), "identity": "seq", "rls": "own", "ws_col": "ws"},
    "fixes": {"pk": ("ws", "edge"), "rls": "own", "ws_col": "ws"},
    "sim": {"pk": ("ws",), "rls": "own", "ws_col": "ws"},
    "remediations": {"pk": ("id",), "identity": "id", "rls": "own", "ws_col": "ws",
                     "defaults": {"ai_drafted": False, "mark": 0, "note": "", "risk_before": None, "risk_after": None,
                                  "paths_before": None, "paths_after": None}},
    "audit": {"pk": ("id",), "identity": "id", "rls": "own", "ws_col": "ws", "defaults": {"detail": ""}},
    "jobs": {"pk": ("id",), "identity": "id", "rls": "own", "ws_col": "ws",
             "defaults": {"log": [], "findings": [], "fixes": [], "report": {}, "branch": "", "pr_url": "",
                          "diff": "", "ai_used": False, "error": ""}},
    "code_models": {"pk": ("ws",), "rls": "own", "ws_col": "ws", "defaults": {"ai_used": False, "files": 0}},
    "api_keys": {"pk": ("id",), "uuid": "id", "rls": "own", "ws_col": "ws", "ws_optional": True,
                 "unique": [("key_hash",)], "hidden": ("key_hash",), "user_update_cols": ("revoked_at",),
                 "defaults": {"revoked_at": None, "source": None, "label": "source", "ws": None}},
    "github_installations": {"pk": ("user_id", "installation_id"), "unique": [("installation_id",)],
                             "rls": "select_own"},
    "github_install_states": {"pk": ("state_hash",), "rls": "none"},
    "github_audit_log": {"pk": ("id",), "identity": "id", "rls": "audit", "defaults": {"via": "app"}},
}
WS_TABLES = [t for t, s in SCHEMA.items() if s.get("ws_col")]


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _dt(v):
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


def _split_list(inner: str) -> list[str]:
    out, cur, q, esc = [], "", False, False
    for ch in inner:
        if esc:
            cur, esc = cur + ch, False
        elif ch == "\\":
            esc = True
        elif ch == '"':
            q = not q
        elif ch == "," and not q:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return out


def _cmp(rowv, op: str, raw: str) -> bool:
    if op == "is":
        return (rowv is None) if raw == "null" else (rowv is (raw == "true"))
    if op == "in":
        vals = _split_list(raw[1:-1]) if raw.startswith("(") else [raw]
        return any(_cmp(rowv, "eq", v) for v in vals)
    if rowv is None:
        return op == "neq"
    if isinstance(rowv, bool):
        a, b = rowv, raw == "true"
    elif isinstance(rowv, (int, float)):
        a, b = rowv, _num(raw)
        if b is None:
            return False
    elif _dt(rowv) and _dt(raw) and op in ("gt", "lt", "gte", "lte"):
        a, b = _dt(rowv), _dt(raw)
    else:
        a, b = str(rowv), raw
    return {"eq": a == b, "neq": a != b, "gt": a > b, "lt": a < b, "gte": a >= b, "lte": a <= b}[op]


class FakeSupabase:
    def __init__(self):
        self.tables: dict[str, list[dict]] = {t: [] for t in SCHEMA}
        self.seq = itertools.count(1)
        self.refreshed: list[str] = []
        self.logouts: list[str] = []
        self.requests: list[tuple[str, str, str]] = []   # (role, method, path)
        self.fail_refresh = False
        self.access_ttl = 3600

    # ---- helpers for tests ----
    def add(self, table: str, row: dict) -> int | str:
        """Insert as the service role (bypasses RLS), filling defaults and generated ids. Returns the id."""
        return self._insert(table, [dict(row)], role=("service", None), mode="plain")[0].get(
            SCHEMA[table].get("identity") or SCHEMA[table].get("uuid") or SCHEMA[table]["pk"][0])

    def rows(self, table: str, **match) -> list[dict]:
        return [r for r in self.tables[table] if all(r.get(k) == v for k, v in match.items())]

    # ---- transport entry ----
    def handle(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path.startswith("/rest/v1/"):
            role = self._role(req)
            self.requests.append((role[0], req.method, path))
            try:
                return self._rest(req, path.removeprefix("/rest/v1/"), role)
            except PgError as e:
                return httpx.Response(e.status, json={"code": e.code, "message": e.message})
        return self._auth(req, path)

    def _role(self, req) -> tuple[str, str | None]:
        bearer = req.headers.get("authorization", "").removeprefix("Bearer ")
        if req.headers.get("apikey") == SERVICE_KEY and bearer == SERVICE_KEY:
            return ("service", None)
        if req.headers.get("apikey") != ANON_KEY:
            raise AssertionError("PostgREST call without the anon or service key")
        try:
            claims = jwt.decode(bearer, JWT_SECRET, algorithms=["HS256"], audience="authenticated")
            return ("user", claims["sub"])
        except jwt.InvalidTokenError:
            return ("anon", None)

    # ---- Supabase Auth ----
    def _auth(self, req, path):
        q = dict(req.url.params)
        if path == "/auth/v1/token" and q.get("grant_type") == "pkce":
            assert req.headers.get("apikey") == ANON_KEY
            body = json.loads(req.content)
            uid = body["auth_code"]          # tests use the uid as the code
            if uid not in USERS or not body.get("code_verifier"):
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json=self._session(uid))
        if path == "/auth/v1/token" and q.get("grant_type") == "refresh_token":
            tok = json.loads(req.content)["refresh_token"]
            self.refreshed.append(tok)
            uid = tok.removeprefix("refresh-").split("#")[0]
            if self.fail_refresh or uid not in USERS:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json=self._session(uid))
        if path == "/auth/v1/logout":
            self.logouts.append(q.get("scope", "global"))
            return httpx.Response(204)
        if m := re.fullmatch(r"/auth/v1/admin/users/([0-9a-f-]+)", path):
            assert req.headers["apikey"] == SERVICE_KEY
            gid, login = USERS[m[1]]
            return httpx.Response(200, json={"id": m[1], "user_metadata": {"provider_id": "999999"},
                                             "identities": [{"provider": "github", "id": str(gid),
                                                             "identity_data": {"user_name": login}}]})
        return httpx.Response(404)

    def _session(self, uid: str) -> dict:
        return {"access_token": access_token(uid, self.access_ttl), "expires_in": self.access_ttl,
                "refresh_token": f"refresh-{uid}#{next(self.seq)}"}

    # ---- PostgREST ----
    def _rest(self, req, table, role):
        params = parse_qs(req.url.query.decode() if isinstance(req.url.query, bytes) else req.url.query,
                          keep_blank_values=True)
        params = {k: v[-1] for k, v in params.items()}
        prefer = req.headers.get("prefer", "")
        if table.startswith("rpc/"):
            return self._rpc(table.removeprefix("rpc/"), json.loads(req.content or b"{}"), role)
        if table not in SCHEMA:
            raise PgError(404, "42P01", f"relation {table} does not exist")
        cols = params.pop("select", "*")
        order = params.pop("order", None)
        limit = params.pop("limit", None)
        offset = params.pop("offset", None)
        on_conflict = params.pop("on_conflict", None)
        filters = params
        rep = "return=representation" in prefer
        if req.method in ("GET", "HEAD"):
            rows = self._visible(table, role, filters)
            total = len(rows)
            rows = self._order(rows, order)
            if offset:
                rows = rows[int(offset):]
            if limit is not None:
                rows = rows[:int(limit)]
            out = [self._project(table, r, cols, role) for r in rows]
            headers = {"content-range": f"0-{max(0, len(out) - 1)}/{total if 'count=exact' in prefer else '*'}"}
            return httpx.Response(200, json=out if req.method == "GET" else None, headers=headers)
        if req.method == "POST":
            body = json.loads(req.content)
            rows = body if isinstance(body, list) else [body]
            mode = ("merge" if "merge-duplicates" in prefer else "ignore" if "ignore-duplicates" in prefer
                    else "plain")
            out = self._insert(table, rows, role, mode, on_conflict)
            return httpx.Response(201, json=[self._project(table, r, cols, role) for r in out] if rep else None)
        if req.method == "PATCH":
            if not filters:
                raise PgError(400, "21000", "UPDATE requires a WHERE clause")
            values = json.loads(req.content)
            out = self._update(table, role, filters, values)
            return httpx.Response(200 if rep else 204, json=[self._project(table, r, cols, role) for r in out]
                                  if rep else None)
        if req.method == "DELETE":
            if not filters:
                raise PgError(400, "21000", "DELETE requires a WHERE clause")
            out = self._delete(table, role, filters)
            return httpx.Response(200 if rep else 204, json=[self._project(table, r, cols, role) for r in out]
                                  if rep else None)
        return httpx.Response(405)

    def _can_read(self, table, role, row) -> bool:
        kind, uid = role
        if kind == "service":
            return True
        if kind != "user":
            return False
        rls = SCHEMA[table]["rls"]
        if rls in ("own", "select_own", "audit"):
            return row.get("user_id") == uid
        if rls == "own_id":
            return row.get("id") == uid
        return False

    def _visible(self, table, role, filters) -> list[dict]:
        out = []
        for r in self.tables[table]:
            if not self._can_read(table, role, r):
                continue
            ok = True
            for col, expr in filters.items():
                op, _, raw = expr.partition(".")
                if op == "not":
                    op2, _, raw2 = raw.partition(".")
                    ok = not _cmp(r.get(col), op2, unquote(raw2))
                else:
                    ok = _cmp(r.get(col), op, unquote(raw))
                if not ok:
                    break
            if ok:
                out.append(r)
        return out

    @staticmethod
    def _order(rows, order):
        if not order:
            return list(rows)
        out = list(rows)
        for part in reversed(order.split(",")):
            col, _, direction = part.partition(".")
            desc = direction.startswith("desc")
            present = [r for r in out if r.get(col) is not None]
            missing = [r for r in out if r.get(col) is None]
            present.sort(key=lambda r: r[col], reverse=desc)
            out = present + missing
        return out

    def _project(self, table, row, cols, role) -> dict:
        hidden = SCHEMA[table].get("hidden", ()) if role[0] != "service" else ()
        if cols in ("*", "", None):
            if hidden:
                raise PgError(401, "42501", f"permission denied for table {table}")
            return copy.deepcopy(row)
        wanted = [c.strip() for c in cols.split(",") if c.strip()]
        if any(c in hidden for c in wanted):
            raise PgError(401, "42501", f"permission denied for column in {table}")
        return {c: copy.deepcopy(row.get(c)) for c in wanted}

    def _owns_ws(self, uid, ws) -> bool:
        return any(w["id"] == ws and w["user_id"] == uid for w in self.tables["workspaces"])

    def _check_write(self, table, role, row):
        kind, uid = role
        if kind == "service":
            return
        if kind != "user":
            raise PgError(401, "42501", "permission denied")
        rls = SCHEMA[table]["rls"]
        if rls in ("none", "select_own", "own_id"):
            raise PgError(403, "42501", "new row violates row-level security policy")
        if rls == "audit" and not (row.get("via") == "token" and row.get("installation_id") is None):
            raise PgError(403, "42501", "new row violates row-level security policy")
        if row.get("user_id") != uid:
            raise PgError(403, "42501", "new row violates row-level security policy")
        wc = SCHEMA[table].get("ws_col")
        if wc and not (row.get(wc) is None and SCHEMA[table].get("ws_optional")) and not self._owns_ws(uid, row.get(wc)):
            raise PgError(403, "42501", "new row violates row-level security policy")

    def _unique_keys(self, table, row):
        s = SCHEMA[table]
        keys = [("pk", tuple(row.get(c) for c in s["pk"]))]
        for cols in s.get("unique", []):
            keys.append((cols, tuple(str(row.get("name", "")).lower() if c == "name_ci" else row.get(c) for c in cols)))
        return keys

    def _conflict(self, table, row, exclude=None, with_key=False):
        mine = dict(self._unique_keys(table, row))
        for r in self.tables[table]:
            if r is exclude:
                continue
            for k, v in self._unique_keys(table, r):
                if mine.get(k) == v and None not in v:
                    return (r, k) if with_key else r
        return (None, None) if with_key else None

    @staticmethod
    def _arbiter(table, on_conflict):
        """The unique key ON CONFLICT targets; a clash on any OTHER unique key is still an error, as in Postgres."""
        cols = tuple(c.strip() for c in on_conflict.split(",")) if on_conflict else SCHEMA[table]["pk"]
        return "pk" if cols == SCHEMA[table]["pk"] else cols

    def _insert(self, table, rows, role, mode="plain", on_conflict=None) -> list[dict]:
        s = SCHEMA[table]
        out, staged = [], []
        for raw in rows:
            row = {**copy.deepcopy(s.get("defaults", {})), **raw}
            if role[0] == "user":
                row.setdefault("user_id", role[1])
                if s.get("identity") and s["identity"] in raw:
                    raise PgError(400, "428C9", f"cannot insert a non-DEFAULT value into column {s['identity']}")
            if s.get("identity") and row.get(s["identity"]) is None:
                row[s["identity"]] = next(self.seq)
            if s.get("uuid") and not row.get(s["uuid"]):
                row[s["uuid"]] = str(uuid.uuid4())
            if table in ("api_keys", "github_installations", "github_audit_log"):
                row.setdefault("created_at", now_iso())
            self._check_write(table, role, row)
            self._caps(table, row, extra=staged)
            existing, key = self._conflict(table, row, with_key=True)
            if existing is not None:
                targeted = key == self._arbiter(table, on_conflict)
                if mode == "ignore" and targeted:
                    continue
                if mode == "merge" and targeted and self._can_read(table, role, existing):
                    merged = {**existing, **row}
                    self._check_write(table, role, merged)
                    existing.update(merged)
                    out.append(existing)
                    continue
                raise PgError(409, "23505", "duplicate key value violates unique constraint")
            staged.append(row)
            out.append(row)
            self.tables[table].append(row)
        return out

    def _caps(self, table, row, extra):
        if table == "workspaces":
            n = sum(1 for r in self.tables[table] if r["user_id"] == row["user_id"])
            if n >= 50:
                raise PgError(400, "23514", "workspace limit reached")
        if table == "events":
            n = sum(1 for r in self.tables[table] if r["ws"] == row["ws"])
            if n >= 50000:
                raise PgError(400, "23514", "event limit reached for this workspace")

    def _update(self, table, role, filters, values) -> list[dict]:
        s = SCHEMA[table]
        if role[0] == "user":
            allowed = s.get("user_update_cols")
            if allowed and any(k not in allowed for k in values):
                raise PgError(401, "42501", f"permission denied for table {table}")
            if s.get("identity") in values or "user_id" in values and values["user_id"] != role[1]:
                raise PgError(403, "42501", "new row violates row-level security policy")
        hit = self._visible(table, role, filters)
        if role[0] == "user" and s["rls"] in ("none", "select_own", "audit"):
            return []   # no update policy: rows are invisible to UPDATE
        for r in hit:
            new = {**r, **copy.deepcopy(values)}
            self._check_write(table, role, new)
            if self._conflict(table, new, exclude=r) is not None:
                raise PgError(409, "23505", "duplicate key value violates unique constraint")
        for r in hit:
            r.update(copy.deepcopy(values))
        return hit

    def _delete(self, table, role, filters) -> list[dict]:
        if role[0] == "user" and SCHEMA[table]["rls"] in ("none", "select_own", "audit"):
            return []
        hit = self._visible(table, role, filters)
        ids = {id(r) for r in hit}
        self.tables[table] = [r for r in self.tables[table] if id(r) not in ids]
        if table == "workspaces":   # ON DELETE CASCADE
            gone = {r["id"] for r in hit}
            for t in WS_TABLES:
                col = SCHEMA[t]["ws_col"]
                self.tables[t] = [r for r in self.tables[t] if r.get(col) not in gone]
        return hit

    # ---- RPC ----
    def _rpc(self, fn, args, role):
        if fn == "ingest_with_key":
            key, events = args.get("p_key"), args.get("p_events")
            if not isinstance(key, str) or not key.startswith("apc_") or not isinstance(events, list) or len(events) > 2000:
                raise PgError(400, "22023", "invalid request")
            h = hashlib.sha256(key.encode()).hexdigest()
            k = next((r for r in self.tables["api_keys"] if r["key_hash"] == h and r["revoked_at"] is None), None)
            if not k:
                raise PgError(403, "28000", "invalid api key")
            target = k.get("ws")
            if target is None or not self._owns_ws(k["user_id"], target):
                mine = sorted((w for w in self.tables["workspaces"] if w["user_id"] == k["user_id"]),
                              key=lambda w: (w["created"], w["id"]))
                target = mine[0]["id"] if mine else None
            if target is None:
                raise PgError(400, "22023", "no workspace for this key")
            room = max(0, 50000 - sum(1 for e in self.tables["events"] if e["ws"] == target))
            for e in events[:room]:
                self.tables["events"].append({"seq": next(self.seq), "ws": target, "user_id": k["user_id"], "data": e})
            return httpx.Response(200, json={"accepted": min(room, len(events)), "ws": target})
        if fn == "workspace_event_counts":
            vis = [e for e in self.tables["events"] if self._can_read("events", role, e) and e["ws"] in args["p_ws"]]
            counts: dict[int, int] = {}
            for e in vis:
                counts[e["ws"]] = counts.get(e["ws"], 0) + 1
            return httpx.Response(200, json=[{"ws": w, "n": n} for w, n in counts.items()])
        if fn == "workspace_latest_jobs":
            latest: dict[int, dict] = {}
            for j in self.tables["jobs"]:
                if self._can_read("jobs", role, j) and j["ws"] in args["p_ws"]:
                    if j["ws"] not in latest or j["id"] > latest[j["ws"]]["id"]:
                        latest[j["ws"]] = j
            return httpx.Response(200, json=[{k: j[k] for k in ("ws", "id", "state", "error", "updated")}
                                             for j in latest.values()])
        raise PgError(404, "PGRST202", f"function {fn} not found")


class FakeGitHub:
    """GitHub that enforces token scoping like the real one: an installation token only sees its installation's
    repos, a repo-scoped token only that repo, and a read-only token cannot write."""

    def __init__(self):
        self.codes: dict[str, str] = {}             # oauth code -> user token
        self.user_tokens: dict[str, int] = {}       # user token -> github user id
        self.revoked: list[str] = []
        self.installations = {
            # Bob is a collaborator on alice's repo, so GitHub lists this installation for Bob too
            1001: {"account": {"login": "alice-gh", "id": 101, "type": "User"}, "app_id": int(APP_ID),
                   "repos": [5001], "members": [102]},
            1002: {"account": {"login": "bob-gh", "id": 102, "type": "User"}, "app_id": int(APP_ID), "repos": [5002]},
            # Org installation alice can see via membership: must NOT be linkable
            1003: {"account": {"login": "acme", "id": 900, "type": "Organization"}, "app_id": int(APP_ID),
                   "repos": [5003], "members": [101]},
            # Installation on the blocked official account, visible to carol
            1004: {"account": {"login": "official-hackathon-org", "id": 103, "type": "User"},
                   "app_id": int(APP_ID), "repos": [5004]},
        }
        self.repos = {
            5001: {"full_name": "alice-gh/demo", "default_branch": "main", "private": True},
            5002: {"full_name": "bob-gh/secret", "default_branch": "main", "private": True},
            5003: {"full_name": "acme/internal", "default_branch": "main", "private": True},
            5004: {"full_name": "official-hackathon-org/app", "default_branch": "main", "private": False},
        }
        for rid, repo in self.repos.items():
            repo["branches"] = {repo["default_branch"]: f"root{rid}"}
            repo["files"] = {"README.md": f"secret contents of {repo['full_name']}".encode()}
            repo["pulls"] = []
            repo["commit_parents"] = {f"root{rid}": []}
        self.inst_tokens: dict[str, tuple[int, int | None, dict]] = {}
        self.pats: dict[str, int] = {}              # desktop personal tokens -> github user id
        self.seq = 0
        self.calls: list[tuple[str, str]] = []

    def code_for(self, github_id: int) -> str:
        self.seq += 1
        token, code = f"ghu_user{github_id}_{self.seq}", f"code-{github_id}-{self.seq}"
        self.codes[code] = token
        self.user_tokens[token] = github_id
        return code

    def repo_by_name(self, full_name: str) -> tuple[int, dict]:
        return next((rid, r) for rid, r in self.repos.items() if r["full_name"].lower() == full_name.lower())

    def touched_repo(self, full_name: str) -> bool:
        return any(f"/repos/{full_name}".lower() in path.lower() for _, path in self.calls)

    def handle(self, req: httpx.Request) -> httpx.Response:
        host, path = req.url.host, req.url.path
        if host == "github.com" and path == "/login/oauth/access_token":
            form = parse_qs(req.content.decode())
            assert form["client_secret"] == [CLIENT_SECRET]
            token = self.codes.pop(form["code"][0], None)
            return httpx.Response(200, json={"access_token": token, "token_type": "bearer"} if token
                                  else {"error": "bad_verification_code"})
        self.calls.append((req.method, path))
        return self.api(req, path)

    def api(self, req, path):
        bearer = req.headers.get("authorization", "").removeprefix("Bearer ")

        if m := re.fullmatch(r"/app/installations/(\d+)/access_tokens", path):
            claims = jwt.decode(bearer, PUBLIC_PEM, algorithms=["RS256"])
            assert claims["iss"] == CLIENT_ID
            inst = self.installations.get(int(m[1]))
            if not inst:
                return httpx.Response(404, json={"message": "Not Found"})
            body = json.loads(req.content or b"{}") or {}
            ids = body.get("repository_ids")
            if ids and not set(ids) <= set(inst["repos"]):
                return httpx.Response(422, json={"message": "repository not in installation"})
            self.seq += 1
            token = f"ghs_inst{m[1]}_{self.seq}"
            self.inst_tokens[token] = (int(m[1]), ids[0] if ids else None, body.get("permissions") or {})
            return httpx.Response(201, json={"token": token, "expires_at": now_iso(3600).replace("+00:00", "Z")})

        if path == "/user":
            gid = self.user_tokens.get(bearer) or self.pats.get(bearer)
            if gid is None:
                return httpx.Response(401, json={"message": "Bad credentials"})
            login = next(l for g, l in USERS.values() if g == gid)
            return httpx.Response(200, json={"id": gid, "login": login}, headers={"x-oauth-scopes": "repo"})

        if path == "/user/installations":
            gid = self.user_tokens.get(bearer)
            if gid is None:
                return httpx.Response(401, json={"message": "Bad credentials"})
            visible = [{"id": iid, "app_id": i["app_id"], "account": i["account"]}
                       for iid, i in self.installations.items()
                       if i["account"]["id"] == gid or gid in i.get("members", [])]
            return httpx.Response(200, json={"total_count": len(visible), "installations": visible})

        if re.fullmatch(r"/applications/([^/]+)/token", path):
            self.revoked.append(json.loads(req.content)["access_token"])
            return httpx.Response(204)

        if bearer in self.pats:   # desktop: the user's own token sees repos owned by that GitHub account
            gid = self.pats[bearer]
            login = next(l for g, l in USERS.values() if g == gid)
            allowed = [rid for rid, r in self.repos.items() if r["full_name"].split("/")[0] == login]
            readonly = False
        else:
            scope = self.inst_tokens.get(bearer)
            if scope is None:
                return httpx.Response(401, json={"message": "Bad credentials"})
            inst_id, only_repo, perms = scope
            allowed = [rid for rid in self.installations[inst_id]["repos"] if only_repo in (None, rid)]
            readonly = perms.get("contents") == "read"

        if path == "/installation/repositories":
            repos = [{"id": rid, "full_name": self.repos[rid]["full_name"],
                      "name": self.repos[rid]["full_name"].split("/")[1],
                      "owner": {"login": self.repos[rid]["full_name"].split("/")[0]},
                      "private": self.repos[rid]["private"],
                      "default_branch": self.repos[rid]["default_branch"]} for rid in allowed]
            return httpx.Response(200, json={"total_count": len(repos), "repositories": repos})

        m = re.fullmatch(r"/repos/([^/]+)/([^/]+)(/.*)?", path)
        if not m:
            return httpx.Response(404, json={"message": "Not Found"})
        try:
            rid, repo = self.repo_by_name(f"{m[1]}/{m[2]}")
        except StopIteration:
            return httpx.Response(404, json={"message": "Not Found"})
        if rid not in allowed:
            return httpx.Response(404, json={"message": "Not Found"})  # GitHub hides inaccessible repos
        if readonly and req.method != "GET":
            return httpx.Response(403, json={"message": "Resource not accessible by integration"})
        if not m[3]:
            return httpx.Response(200, json={"id": rid, "full_name": repo["full_name"], "private": repo["private"],
                                             "default_branch": repo["default_branch"],
                                             "permissions": {"push": True}})
        return self.repo_api(req, repo, m[3])

    def repo_api(self, req, repo, sub):
        body = json.loads(req.content) if req.content else {}
        if m := re.fullmatch(r"/git/ref/heads/(.+)", sub):
            sha = repo["branches"].get(unquote(m[1]))
            return (httpx.Response(200, json={"object": {"sha": sha}}) if sha
                    else httpx.Response(404, json={"message": "Not Found"}))
        if sub == "/git/refs" and req.method == "POST":
            name = body["ref"].removeprefix("refs/heads/")
            if name in repo["branches"]:
                return httpx.Response(422, json={"message": "Reference already exists"})
            repo["branches"][name] = body["sha"]
            return httpx.Response(201, json={"ref": body["ref"]})
        if m := re.fullmatch(r"/git/refs/heads/(.+)", sub):
            assert req.method == "PATCH" and body["force"] is False
            name = unquote(m[1])
            if repo["branches"].get(name) not in repo["commit_parents"].get(body["sha"], []):
                return httpx.Response(422, json={"message": "Update is not a fast forward"})
            repo["branches"][name] = body["sha"]
            return httpx.Response(200, json={"object": {"sha": body["sha"]}})
        if m := re.fullmatch(r"/git/commits/([\w-]+)", sub):
            return httpx.Response(200, json={"tree": {"sha": f"tree-{m[1]}"}})
        if sub == "/git/trees" and req.method == "POST":
            self.seq += 1
            repo.setdefault("written", []).extend(e["path"] for e in body["tree"])
            repo.setdefault("written_content", {}).update({e["path"]: e["content"] for e in body["tree"]})
            return httpx.Response(201, json={"sha": f"tree{self.seq}"})
        if m := re.fullmatch(r"/git/trees/(.+)", sub):
            if unquote(m[1]) not in repo["branches"]:
                return httpx.Response(404, json={"message": "Not Found"})
            return httpx.Response(200, json={"truncated": False, "tree": [
                {"path": p, "type": "blob", "size": len(c)} for p, c in repo["files"].items()]})
        if sub == "/git/commits" and req.method == "POST":
            self.seq += 1
            sha = f"c{self.seq}"
            repo["commit_parents"][sha] = body["parents"]
            if race := repo.pop("push_during_commit", None):
                # Someone else pushes to the branch between our read and our ref update
                repo["branches"]["fixes"] = race
                repo["commit_parents"][race] = []
            return httpx.Response(201, json={"sha": sha})
        if m := re.fullmatch(r"/contents/(.+)", sub):
            p = unquote(m[1])
            if p not in repo["files"]:
                return httpx.Response(404, json={"message": "Not Found"})
            c = repo["files"][p]
            return httpx.Response(200, json={"type": "file", "path": p, "sha": "blob1", "size": len(c),
                                             "encoding": "base64", "content": base64.b64encode(c).decode()})
        if sub == "/pulls" and req.method == "GET":
            q = dict(req.url.params)
            owner = repo["full_name"].split("/")[0]
            hits = [p for p in repo["pulls"] if f"{owner}:{p['head']}" == q["head"]
                    and p["base"] == q["base"] and p["state"] == q["state"]]
            return httpx.Response(200, json=hits)
        if sub == "/pulls" and req.method == "POST":
            pr = {"number": len(repo["pulls"]) + 1, "head": body["head"], "base": body["base"], "state": "open",
                  "title": body["title"]}
            repo["pulls"].append(pr)
            return httpx.Response(201, json=pr)
        return httpx.Response(404, json={"message": "Not Found"})


class World:
    """Everything outside the app: Supabase and GitHub, on one transport."""

    def __init__(self):
        self.db = FakeSupabase()
        self.gh = FakeGitHub()

    def handler(self, req: httpx.Request) -> httpx.Response:
        if req.url.host == SUPABASE_HOST:
            return self.db.handle(req)
        if req.url.host in ("github.com", "api.github.com"):
            return self.gh.handle(req)
        return httpx.Response(599)
