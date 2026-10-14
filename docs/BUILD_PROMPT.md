# Build prompt: Attack Path Compiler

Paste everything below the line into your coding assistant (one session per owner: A, B, C, D, E, each told
which role they are). Source of truth: `docs/MASTER_PLAN.md`.

---

You are helping a 5-person team build the **Attack Path Compiler** for Manipal Hackathon 2026 (Round 2, technical).
Read `docs/MASTER_PLAN.md` first and follow it. If this prompt and the plan disagree, ask before deviating.

## Goal
Convert heterogeneous security logs into a continuously updated, explainable attack-path graph. Correlate
identities, permissions, hosts, secrets, services and events; rank paths by likelihood x impact; find the
smallest (cheapest) defensive intervention that breaks the most dangerous paths. Demo it on SIMULATED logs.

## Hard rules (rulebook; do not violate)
- All project code is written now, from scratch. Do not paste pre-existing complete solutions.
- Logs come from EvidenceForge (deterministic, no LLM) generated from a scenario YAML the team writes by hand.
  Never invent or LLM-generate log lines. Never hardcode results: the UI must show output computed from
  ingested events.
- Cite third-party code/data/licences in README (EvidenceForge MIT, MITRE ATT&CK, libraries). Disclose AI tools.
- No secrets in git. Provide `.env.example`. No force-push, no squashing.
- Synthetic data only, clearly labelled. No real credential or personal data.
- Evaluators must be able to test alone: seeded demo account, no paid external APIs in the core path,
  GitHub integration optional.
- At least 5 real API endpoints that the UI actually uses.

## Stack
Python 3.12, FastAPI, networkx, SQLite (stdlib sqlite3), pytest. React + Vite + Cytoscape.js (dagre layout).
One Docker image (existing `Dockerfile`): FastAPI serves `/api/*` and the built UI from `STATIC_DIR`.
Deployed on a VPS with Caddy via `docker-compose.yml` / `deploy.sh`.

## Repo layout
```
backend/app/{main.py,models.py,auth.py,parsers/,correlate.py,analyze.py,narrate.py,store.py}
backend/tests/   backend/requirements.txt
frontend/src/    frontend/package.json  frontend/package-lock.json
data/{inventory.yaml,attack_subset.json,samples/}   # data/attack/enterprise-attack.json is local only
scenarios/       docs/
```
Backend contract: module `app.main:app`, `GET /health`, honour `PORT`, `STATIC_DIR`, `SEED_DIR`, `DATA_DIR`.
Mount static files LAST (after `/api/*`) with an index.html fallback.

## Data contracts (freeze first in docs/contracts.md, with example JSON)
- Event: `{id, ts, source, type, actor, host, src_ip, dst, outcome, attack, raw}`
- Node: `{id, kind: identity|host|secret|role|service|data|external, label, criticality}` (criticality 1-10)
- Edge: `{id, src, dst, technique, p, cost, observed, evidence:[event ids], mitigation}`
- Path: `{id, nodes, edges, p, impact, risk, tactics, narrative}`
- Fix: `{edges, total_cost, paths_broken, risk_removed_pct, mitigations}`
All ids in the scenario YAML and `inventory.yaml` come from ONE shared name list (users, hosts, roles,
secrets, crown jewels).

## Modules to build

### Ingest and data (role B)
1. Install EvidenceForge (Python 3.12+, uv). Write `scenarios/*.yaml` by hand: small company, 3 entry points,
   2 crown jewels, one attack that crosses sources. Generate once with a fixed seed; commit output to
   `data/samples/` with the command and seed in the README.
2. INSPECT the real generated files before writing parsers. Do not assume formats.
3. Parsers (`line -> Event`, <40 lines each): Linux auth syslog, Suricata alerts, web access. Reject malformed.
4. `POST /api/ingest` (lines or Event JSON + `format`), `POST /api/simulate/{start,step,reset}` replaying
   `data/samples/` through the SAME ingest function, SQLite store (append-only events).
5. Auth: register/login/logout/me, argon2 or bcrypt, httpOnly session cookie, login rate limit, seeded demo
   account from env, per-source API keys (`X-API-Key`) for ingest.

### Engine (role A)
1. Load `inventory.yaml` into a DiGraph (possible edges with prior p, cost, technique).
2. Correlate: an event confirming an edge sets `observed=true`, raises p, appends evidence ids.
3. Weight `w = -log(p)`. Add SUPER_SOURCE -> all `external`, all crown-jewel `data` -> SUPER_SINK.
4. Top-k via `nx.shortest_simple_paths(..., weight="w")`; cap k and graph size; handle "no path".
5. risk = product(edge p) x criticality (normalise once, documented). Do not use per-hop averages.
6. Min cut: node-split, capacity = remediation cost, `nx.minimum_cut`; edges without capacity are uncuttable.
   Do not use `minimum_node_cut`. Greedy best single fix = edge removing most total risk.
7. Recompute per batch (debounce ~500 ms) and publish via SSE.
8. Unit tests on a hand-made graph: known top path, known min cut, p=1 and p~0 edges, disconnected graph.

### Knowledge and explanation (role D)
1. `data/inventory.yaml` using the shared name list.
2. Script that trims `data/attack/enterprise-attack.json` to `data/attack_subset.json` (<1 MB): technique id,
   name, tactic(s), mitigations via `mitigates` relationships.
3. `narrate.py`: template narrative per path ("alice was reached via MFA fatigue (T1621), then ..."), each hop
   with technique id and evidence event ids; kill-chain ordered by tactic.
4. Compare found path with EvidenceForge `GROUND_TRUTH` output (verify actual file name/format first).

### Frontend (role C)
Login (with "Use demo account"), dashboard: alert list, Cytoscape graph (live), ranked path list, path detail
(story, kill-chain bar, evidence), fixes panel (cheapest cut, best single fix, ATT&CK mitigation), Play,
Upload logs, Apply fix, Settings > Sources (create API key, copy curl). SSE for live updates. Build against
fixture JSON first. Escape ALL event text (no raw HTML).

### Platform (role E)
Branches `main`, `bugbounty`, `fixing`; VPS + HTTPS first (plan section 4.2); keep deploy working from
the first hour; README per rulebook 4.1; objectives docs; input limits, schema validation, rate limits;
CI running pytest.

## API
`/api/auth/*`, `POST /api/ingest`, `POST /api/simulate/*`, `GET /api/graph`, `GET /api/paths?k=`,
`GET /api/paths/{id}`, `GET /api/fixes`, `POST /api/fixes/apply`, `GET /api/stream` (SSE),
`POST /api/keys`, `GET /health`.

## Security / bug bounty
Body and upload size limits; cap events/nodes; strict schema validation; no stack traces to clients; auth on
non-public endpoints; users cannot read/reset others' data; escape output; secrets only in server env.

## Order of work
1. contracts + fixtures + deploy hello-world. 2. sample logs + parsers. 3. engine on toy graph. 4. UI on
fixtures. 5. integrate real events -> graph -> UI. 6. Play/SSE/Apply fix/auth. 7. narratives, mitigations,
tests, README. 8. optional: GitHub Security tab / Issue / PR check, second log source.

## Working style
Small, real commits at least every 2 hours. Tests for every engine function. Explain each module in 3-5 lines
in the PR/commit so the owner can defend it to judges. If a requirement is ambiguous or a log format is
unknown, stop and ask rather than guessing.

## Definition of done (MVP)
Press Play on the public URL: raw sample logs are parsed live, four weak signals join into one ranked critical
path with technique ids and evidence, the cheapest fix is shown with its ATT&CK mitigation, Apply fix
re-ranks and risk drops; an evaluator can sign in with the demo account and POST their own events.
