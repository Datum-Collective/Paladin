# Attack Path Compiler: Master Plan

Manipal Hackathon 2026, Round 2 (Technical). Team of 5. Coding began 14 Oct 10:00 AM.
This file is the single source of truth. It consolidates `docs/PLAN.md` and the research in
`docs/research/attack-path-compiler.md`.

---

## 1. The problem and our answer

**Problem.** Security tools raise isolated alerts. Combinations of weak signals reveal how an attacker could
move through an organization. Build a system that turns heterogeneous security events into continuously
updated attack paths, correlates identities, permissions, applications, endpoints, secrets, services and
events, ranks paths by likelihood and impact, and finds the smallest defensive intervention that breaks the
most dangerous paths. Demonstrate with simulated events, with an explainable model of propagation.

**Our answer, one sentence.** Raw logs from different sources go in; a live graph comes out with ranked
attack paths, a plain-English story and ATT&CK labels for each, and the cheapest fix that breaks them.

**Requirement coverage**

| Brief says | We do |
|---|---|
| Heterogeneous events | Parsers for Linux auth, Suricata, web access (and more if time) into one Event schema |
| Correlate identities, permissions, apps, endpoints, secrets, services | `inventory.yaml` (possible edges) + events (live edges) in one graph |
| Continuously updated | Append-only event store; recompute on each batch; push to UI over SSE |
| Construct attack paths | Super-source/super-sink + k shortest simple paths |
| Rank by likelihood and impact | risk = product(edge p) x target criticality |
| Smallest intervention | Cost-weighted minimum cut plus greedy best single fix, labelled with ATT&CK mitigations |
| Simulated events | EvidenceForge-generated logs from our hand-written scenario |
| Explainable | Per-hop evidence, technique IDs, kill-chain bar, narrative, comparison to ground truth |

---

## 2. Rulebook constraints that shape the build

| Rule | Consequence |
|---|---|
| No pre-event code, designs, schemas, prompts | Everything project-specific written after 14 Oct 10:00 AM |
| Disclose AI tools; team must explain and debug all code | README lists Claude Code and what it did. Everyone reads what they merge |
| Cite third-party code, data, licences | EvidenceForge (MIT), log-generator (PolyForm Noncommercial, optional), MITRE ATT&CK, libraries |
| One meaningful commit per 120 min, no force-push or squash | Small real commits to `main`, rebase, never force-push |
| No secrets in git, `.env.example` required | Config via env vars only |
| Data must be public, anonymized, or clearly labelled synthetic | Label all sample logs synthetic. No real laptop scanning |
| Delivery: public URL, LAN, or Docker; stays up until the end | One Docker image on our own VPS behind Caddy HTTPS (public URL); same image runs on LAN with `docker run` |
| README sections (4.1) | See section 15 |
| Objectives document before each judging round | Owner E; format will be announced by organizers |
| Checkpoint 1: 15 Oct 1:00 PM; deployed, one end-to-end flow | Target: done by tonight |
| Checkpoint 2: 15 Oct 9:30 PM; at least 5 major APIs, real inputs, not hardcoded | Section 8 endpoints; evaluators can upload their own events |
| Bug bounty 16 Oct 12:00-2:00 AM on frozen `bugbounty` branch; missing setup docs disqualify | Section 14 hardening; branches created early |
| Evaluators test without private help or payment | Demo account, no paid APIs in the core path, GitHub optional |

Schedule: JR1 15 Oct 8:30-11:00 AM, JR2 15 Oct 6:30-8:30 PM, JR3 and bug bounty review 16 Oct 8:30-10:00 AM,
finals 16 Oct 10:30 AM-1:00 PM.

---

## 3. Architecture

```
 EvidenceForge logs (synthetic)  ──┐
 optional: log-generator / honeypot │  POST /api/ingest (file, API key, or Play)
                                    ▼
                          parsers ─► Event (normalized) ─► SQLite
                                                              │
 data/inventory.yaml (possible edges) ───────────────────────►│
                                                              ▼
                                         correlate: events mark edges live, raise p, attach evidence
                                                              ▼
                                   graph (networkx) ─► analyze: top-k paths, risk, min-cut, fixes
                                                              ▼
                                      FastAPI ──SSE──► React + Cytoscape UI
                                          └─(optional)─► GitHub: Security tab, Issue, PR check
```

**Core idea.** The inventory says which attack steps are *possible* (account -> role, host -> secret, role ->
data). Logs say which are *happening*. A live edge gets higher probability and shows its evidence events.

---

## 4. Stack and repo layout

- Backend: Python 3.12, FastAPI, networkx, SQLite (stdlib), pytest.
- Frontend: React, Vite, Cytoscape.js (dagre layout).
- Deploy: one Docker image (multi-stage `Dockerfile`: builds the Vite app, FastAPI serves it as static files) on a VPS, with Caddy for HTTPS via `docker-compose.yml`. No separate frontend host. See section 4.1.

```
backend/app/{main.py, models.py, auth.py, parsers/, correlate.py, analyze.py, narrate.py, store.py}
backend/tests/
frontend/src/
data/{inventory.yaml, attack_subset.json, samples/, attack/enterprise-attack.json}
scenarios/                 # our EvidenceForge scenario YAML
docs/{MASTER_PLAN.md, PLAN.md, contracts.md, research/}
README.md  .env.example  Dockerfile  docker-compose.yml  Caddyfile  deploy.sh
```

`data/attack/enterprise-attack.json` is already downloaded (53 MB, 867 techniques, 268 mitigations, 1,477
mitigates links). The app ships only `attack_subset.json`, trimmed to the techniques we use.

### 4.1 Deployment (VPS, single app image)

```
VPS (Ubuntu LTS, 2 vCPU, 2-4 GB RAM)
 └─ docker compose
     ├─ caddy       :80/:443  automatic HTTPS, reverse proxy
     ├─ apc-main    image built from `main`        (port 8000, internal)
     └─ apc-bounty  image built once from `bugbounty` (profile "bounty", started before the freeze)
```

- **One app image.** `Dockerfile` builds `frontend/` with Node, then a Python 3.12 image runs
  `uvicorn app.main:app`. FastAPI serves `/api/*` and the built UI from `STATIC_DIR` (mount static files
  last, with an index.html fallback for client-side routes).
- **Compose** is for Caddy and the two environments only. `Caddyfile` routes `$APP_DOMAIN` to `apc-main`
  and `$BOUNTY_DOMAIN` to `apc-bounty`.
- **Deploy command:** `./deploy.sh main` (pull, rebuild, restart) or `./deploy.sh bounty` (clone the
  `bugbounty` branch to `.bounty-src`, build once; refuses to rebuild a running bounty stack unless
  `FORCE=1`).
- **Run anywhere:** `docker build -t apc . && docker run --rm -p 8000:8000 -v apc-data:/var/lib/apc apc`
  then open `http://localhost:8000`. This is the reproducible-container delivery the rulebook accepts.
- **Config (env, see `.env.example`):** `PORT`, `STATIC_DIR`, `SEED_DIR` (read-only inventory/samples),
  `DATA_DIR` (SQLite), `SECRET_KEY`, `DEMO_USER`/`DEMO_PASSWORD`, `APP_DOMAIN`, `BOUNTY_DOMAIN`,
  `ALLOWED_ORIGINS` (dev only). `.env` exists only on the server.
- **Persistence.** SQLite lives in a named volume (`apc_main_data`). Still re-seed inventory, demo account
  and sample replay on start so a wiped volume never breaks the demo.
- **HTTPS.** Needs a domain (or a free wildcard-DNS hostname) pointing at the VPS. Open ports 80/443 and
  22 only. Verify the hostname approach and certificate issuance in H0-1.
- **Server hygiene (owner E).** SSH keys only, no root or password login, firewall on, `fail2ban` or Caddy
  rate-limit for `/api/auth/*`, unattended security updates, nothing else running on the box (no
  honeypot here). Containers use `restart: unless-stopped`. Keep the VPS paid through the end of the event.
- **Excluded from image:** `data/attack/enterprise-attack.json` (53 MB; only `attack_subset.json` ships),
  `docs/`, `.env`, `.bounty-src` (see `.dockerignore`).
- **Backend contract for the Dockerfile:** `backend/requirements.txt`, module `app.main:app`, `GET /health`,
  honours `PORT`, `STATIC_DIR`, `DATA_DIR`. Frontend: `frontend/package-lock.json`, `npm run build` -> `dist/`.
- **Fallbacks:** `docker run` on a laptop over LAN; Render or Cloudflare Containers can run the same image.

### 4.2 First-time VPS setup checklist (E, about 30-45 min)

1. Create the VPS; add every teammate's SSH key; disable password and root login.
2. Firewall: allow 22 (your IPs if possible), 80, 443 only.
3. `curl -fsSL https://get.docker.com | sh`; add the deploy user to the `docker` group.
4. Point DNS (`APP_DOMAIN`, `BOUNTY_DOMAIN`) at the VPS IP.
5. `git clone` the repo, `cp .env.example .env`, fill in real values, `./deploy.sh main`.
6. Check `https://$APP_DOMAIN/health`, then record the URL and demo account in the README.

---

## 5. Simulated data

We use EvidenceForge as the simulator. It is deterministic (same scenario + seed = same logs) and its engine
makes no LLM calls, which satisfies "do not let AI make the logs".

1. B hand-writes `scenarios/*.yaml`: small company, 3 entry points, 2 crown jewels, 4 weak signals, one
   attack storyline that crosses sources.
2. B runs `eforge generate` once with a fixed seed; the output goes to `data/samples/` and is committed with
   the command and seed in the README.
3. EvidenceForge also emits `GROUND_TRUTH.json`; D uses it to show our recovered path matches the real one.
4. Do not use EvidenceForge's LLM agent skills for authoring.

Gaps: the README lists Windows, Linux syslog, EDR, network, Suricata, Cisco ASA, web, proxy and email
evidence. We did not see cloud IAM events, which the inventory covers. log-generator (cloud, authentication,
ATT&CK-tagged chains) and a Cowrie/T-Pot adapter are optional extras. Honeypot IPs must be anonymized and
labelled real honeypot data.

**Open item:** generate a sample and confirm the exact line formats before B writes parsers.

---

## 6. Data contracts (freeze in hour 1)

**Event**
```json
{"id":"e17","ts":"2026-10-14T09:12:03Z","source":"linux_auth","type":"auth_success",
 "actor":"alice","host":"web-01","src_ip":"203.0.113.9","dst":"web-01",
 "outcome":"success","attack":"T1078","raw":"<original line>"}
```
**Node** `{id, kind: identity|host|secret|role|service|data|external, label, criticality}`
**Edge** `{id, src, dst, technique, p, cost, observed, evidence:[eventIds], mitigation}`
**Path** `{id, nodes, edges, p, impact, risk, tactics, narrative}`
**Fix** `{edges, total_cost, paths_broken, risk_removed_pct, mitigations}`

Shared name list (users, hosts, roles, secrets) is agreed once by B and D and used in both the scenario and
`inventory.yaml`. Fixture JSON for each shape lives in `docs/contracts.md`.

---

## 7. Ingest

Three ways in, one code path:

| Way | User | Behaviour |
|---|---|---|
| Play button | Demo, judges | Server replays `data/samples/` through the same ingest function |
| Upload file | Judges | UI upload with a format selector |
| API | Real use, Checkpoint 2 | `POST /api/ingest` with `X-API-Key` |

Per line: parser -> Event -> validate (schema, size) -> store -> correlate -> recompute -> SSE push.
Parsers are small `line -> Event` functions. First three: Linux auth, Suricata alerts, web access.

```bash
curl -X POST https://<app>/api/ingest -H "X-API-Key: <key>" -H "Content-Type: application/json" \
  -d '{"format":"linux_auth","lines":["Oct 14 09:12:03 web-01 sshd[912]: Accepted password for alice from 203.0.113.9 port 51544 ssh2"]}'
```

---

## 8. API (minimum five; we ship more)

| Endpoint | Purpose |
|---|---|
| `POST /api/auth/register`, `/login`, `/logout`, `GET /api/me` | Accounts and session |
| `POST /api/ingest` | Raw lines or Event JSON with a format hint |
| `POST /api/simulate/{start,step,reset}` | Replay sample logs |
| `GET /api/graph` | Nodes and edges |
| `GET /api/paths?k=10`, `GET /api/paths/{id}` | Ranked paths; detail with narrative and evidence |
| `GET /api/fixes`, `POST /api/fixes/apply` | Cheapest cut, best single fix; apply and recompute |
| `GET /api/stream` | SSE updates |
| `POST /api/keys` | Create ingest API key |
| `GET /health` | Liveness |

---

## 9. Algorithm (owner A, about 150 lines)

1. Build a `DiGraph` from inventory plus correlated events. Edge weight `w = -log(p)`.
2. Add `SUPER_SOURCE` -> every `external` node and every crown-jewel `data` node -> `SUPER_SINK`.
3. Top-k paths with `nx.shortest_simple_paths(G, SUPER_SOURCE, SUPER_SINK, weight="w")`.
4. risk = product of edge p x target criticality.
5. Minimum cut: node-split, capacity = remediation cost, `nx.minimum_cut`. Edges without capacity are
   uncuttable. Do not use `minimum_node_cut` (counts nodes, ignores cost).
6. Best single fix: greedy, pick the edge that removes the most total risk.
7. Mitigation label: technique id -> `attack_subset.json` -> mitigation (e.g. M1032 MFA).
8. Recompute from scratch on each batch (debounced about 500 ms). Fine at demo size.

Edge p starts from the inventory prior, rises when an event confirms the edge. Optionally calibrate from
honeypot statistics or Dependabot EPSS values.

---

## 10. Auth and user flows

Notation: `( )` start/end, `[ ]` step, `< >` decision. One goal per flow.

**Flow 1: Sign in**
```
(Open URL) -> [Login] -> <Have account?>
  yes -> [Email+password] -> <Valid?> yes -> (Dashboard) | no -> [Error, rate-limited] -> [Login]
  no  -> <Quick start?> demo -> [Use demo account] -> (Dashboard) | new -> [Register] -> (Dashboard)
```
**Flow 2: Find and fix a path**
```
(Dashboard) -> [Play or Upload] -> [Graph builds live] -> [Ranked paths] -> [Open top path]
 -> [Story, kill-chain, evidence] -> <Accept fix?> yes -> [Apply fix] -> (Risk LOW)
                                                    no  -> [Pick another] -> [Story, kill-chain, evidence]
```
**Flow 3: Connect a source**
```
(Dashboard) -> [Settings > Sources] -> [Create API key] -> [Copy curl] -> [Send events]
 -> <Accepted?> yes -> (Events on graph) | no -> [Validation error] -> [Fix payload]
```
**Flow 4 (optional): Connect GitHub**
```
(Dashboard) -> [Settings > Integrations] -> [Connect GitHub] -> [GitHub install approval]
 -> <Connected?> yes -> (Repo nodes appear) | no -> [Error] -> [Retry]
```

Auth: passwords hashed (argon2/bcrypt), httpOnly session cookie, login rate-limited, seeded demo account in
README. Ingest uses per-source API keys, separate from user sessions. Per-user workspaces are cut; one shared
resettable demo workspace.

---

## 11. GitHub integration (optional, after JR1)

Build a GitHub App (not a PAT; only Apps can create Check Runs). Use a public demo repo.

- **Read:** collaborators, deploy keys, Actions secret names (never values), Dependabot and secret-scanning
  alerts. Org audit log is Enterprise-only, so it is simulated.
- **Write:** SARIF upload with `codeFlows` (Security tab), Issue for the cut edges, Check Run that fails a PR
  creating a new critical path.
- **Test early:** whether the secret-scanning alerts endpoint works on public repos; whether `result.graphs`
  renders (assume not, use `codeFlows`); creating check runs with `GITHUB_TOKEN`.

Never required for the core demo. Screenshots as backup.

---

## 12. Team roles

| | Owner | Tasks | Done when |
|---|---|---|---|
| **A** | Engine | Graph classes; load inventory; correlation; top-k, risk; min-cut; best single fix; unit tests | `/paths` and `/fixes` correct on the sample |
| **B** | Data and ingest | Scenario YAML; run EvidenceForge; 3 parsers; `/ingest`; replay; SQLite; auth; API keys | Raw sample logs become Events end to end |
| **C** | Frontend | Login; dashboard; Cytoscape graph and highlighting; Play/Upload; Apply fix; SSE; Settings > Sources | Demo works fully through the UI |
| **D** | Knowledge and explanation | `inventory.yaml`; ATT&CK subset trimmer; narratives; kill-chain bar; evidence panel; ground-truth comparison | Every path has IDs, story, mitigation |
| **E** | Platform and docs | Repo, branches, CI; deploy early; README; objectives docs; validation, rate limits, escaping; demo script | Stranger can run and test from README |

Dependencies: B and D share the name list (hour 1). A and C share fixtures until real data lands.

---

## 13. Timeline (H0 = now)

| Hours | Goal |
|---|---|
| H0-1 | Freeze contracts and name list; repo + branches; VPS up with hello-world behind HTTPS (section 4.2); EvidenceForge installed |
| H1-4 | Parallel build against fixtures. First parsers, analyzer on fixture graph, graph view |
| H4 | **Integration 1:** real parsed logs -> real graph in UI |
| H4-8 | Play, SSE, Apply fix, auth, deployed |
| H8 | **End-to-end on the public URL** (Checkpoint 1 ready, official 15 Oct 1 PM) |
| H8-12 | Narratives, evidence, mitigations, validation, tests, objectives doc, README |
| H12-16 | Rehearse; sleep in shifts; ready for JR1 15 Oct 8:30 AM |
| After JR1 | GitHub sink and source, second log source; Checkpoint 2 (9:30 PM) needs 5+ APIs and real inputs |
| Before 16 Oct 12:00 AM | Hardening; `bugbounty` branch deployable with complete setup docs |
| 2:00-3:30 AM | Fixing phase on `fixing`; then merge to `main` |

Commit rhythm: whole team pushes at least one meaningful commit every 2 hours.

---

## 14. Hardening for the bug bounty

- Body and upload size limits; cap events and nodes per workspace.
- Strict schema validation on every ingest path; reject unknown formats.
- Escape all event text in the UI (no raw HTML); no stack traces to clients.
- Auth on all non-public endpoints; users cannot read or reset others' data; rate-limit login and ingest.
- Firewall/host config: only expected ports; secrets only in server env.
- Test with a second browser profile for access control and with malformed payloads.
- Also use the attack window to find bugs in assigned teams (max 10 bugs, 4 per team; no DoS).

---

## 15. README checklist (rulebook 4.1)

Project and team details; solution summary; architecture and stack; supported environments; dependencies;
install and run commands; deployment/access details; env vars; database setup; test instructions; known
limitations; AI tools disclosed (Claude Code and purpose); third-party resources (EvidenceForge MIT, MITRE
ATT&CK, libraries, licences); synthetic data statement; Dockerfile and container commands; test account.

---

## 16. Demo script (3 minutes)

1. **0:00-0:30** Four "low" alerts side by side that nobody would escalate.
2. **0:30-1:15** Press Play. Raw logs stream in, get parsed live, and snap into one red path to the crown
   jewel, rated CRITICAL.
3. **1:15-1:45** Click the path: kill-chain bar, narrative, evidence per hop with ATT&CK IDs.
4. **1:45-2:15** Fixes panel: cheapest cut with its mitigation; note a node-count cut would have picked a
   costlier fix. Apply fix; paths re-rank; risk falls to LOW.
5. **2:15-2:35** Show our path matches `GROUND_TRUTH.json`.
6. **2:35-3:00** If built: GitHub Security tab alert, auto-filed Issue, failing PR check. Close: "Small alerts
   in, attack path out, and the one fix that stops it."

Rehearse twice; keep a recorded backup video.

---

## 17. Cut line

- **Must ship:** real parsers, graph, top-k paths, min-cut fix, Apply fix, live UI, narratives, auth + demo
  account, public URL, README, objectives docs.
- **Strong extras:** ATT&CK mitigations on fixes, ground-truth comparison, GitHub integration.
- **Only if idle:** log-generator cloud/auth noise, honeypot adapter, OCSF Detection Finding export.
- **Dropped:** laptop-scanning CLI, GitHub-clone UI, multi-tenant workspaces.

---

## 18. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Parsers eat B's time | Only 3 formats; each parser < 40 lines |
| Generators do not share names | Hand-written inventory is the join point; log-generator optional |
| Nothing deployed until late | E deploys in hour 1; merge to `main` often |
| Min-cut slow or wrong | Demo graph is small; unit tests on toy graphs; greedy fallback |
| VPS misconfigured, down, or attacked during bug bounty | Hardening checklist (4.1, 14); restart policies; `docker run` LAN fallback; second teammate has SSH access |
| GitHub features break live | Pre-made repo; screenshots and video backup |
| Bug bounty finds trivial bugs | Section 14 checklist, tested before freeze |
| Team cannot explain AI-written code | Pair review; each owner walks through their module before JR1 |

---

## 19. Open items

1. Official repo URL and the objectives-document format (organizers).
2. Generate an EvidenceForge sample and confirm log formats before parsers.
3. Pick a VPS provider and domain in H0-1; confirm HTTPS issuance. Render or Cloudflare Containers can run the same image if the VPS fails (Cloudflare Containers needs the $5 Workers Paid plan; GA status not verified).
4. Test the three GitHub unknowns listed in section 11 early.
