# Attack Path Compiler: build plan (team of 5)

One sentence: raw logs from different sources go in; a ranked, explained attack graph and the cheapest fix come out, live.

## 1. Architecture (keep it this simple)

```
EvidenceForge logs (+ optional log-generator / honeypot)     data/inventory.yaml (who can reach what)
            │  POST /api/ingest                                        │ loaded at start
            ▼                                                          ▼
   parsers → normalized Event ──► correlate ──► graph (networkx) ──► analyze ──► API ──► React + Cytoscape
                                   (events raise edge probability     (top-k paths,      (SSE live push)
                                    and attach evidence)               min-cut, fixes)
```

Key idea: `inventory.yaml` says which attack edges are POSSIBLE (identity -> role, host -> secret, role -> data).
Logs say which edges are LIVE. A live edge gets higher probability and shows its evidence events.

## 2. Stack and repo layout

- Backend: Python 3.12, FastAPI, networkx, SQLite (stdlib `sqlite3`), pytest.
- Frontend: React + Vite + Cytoscape.js (dagre layout).
- Deploy: backend on Render, frontend on Vercel. Fallback: `docker compose up` (Dockerfile owned by Person E).

```
backend/app/{main.py, models.py, parsers/, correlate.py, analyze.py, narrate.py, store.py}
backend/tests/
frontend/src/
data/{inventory.yaml, attack_subset.json, samples/}
scenarios/        # our EvidenceForge scenario YAML (hand-written by us)
docs/{PLAN.md, contracts.md}
README.md  .env.example
```

## 3. Contracts (freeze in hour 1; everyone codes against these)

**Event** (output of every parser)
```json
{"id":"e17","ts":"2026-10-14T09:12:03Z","source":"linux_auth","type":"auth_success",
 "actor":"alice","host":"web-01","src_ip":"203.0.113.9","dst":"web-01",
 "outcome":"success","attack":"T1078","raw":"<original line>"}
```
**Graph node:** `{id, kind: identity|host|secret|role|service|data|external, label, criticality}`
**Graph edge:** `{id, src, dst, technique:"T1078", p:0.3, cost:2, observed:false, evidence:["e17"], mitigation:"M1032"}`
**Path:** `{id, nodes:[...], edges:[...], p, impact, risk, tactics:[...], narrative}`
**Fix:** `{edges:[edge ids], total_cost, paths_broken, risk_removed_pct, mitigations:[...]}`

## 4. API (at least 5 real endpoints, all exercised by the UI)

| Endpoint | Purpose |
|---|---|
| `POST /api/ingest` | Raw log lines or Event JSON, `format` hint; validates and stores |
| `POST /api/simulate/{start,step,reset}` | Replays `data/samples` through the same ingest path |
| `GET /api/graph` | Current nodes and edges |
| `GET /api/paths?k=10` | Ranked attack paths |
| `GET /api/paths/{id}` | Path detail with narrative and evidence |
| `GET /api/fixes` | Min-cut fix, best single fix, ATT&CK mitigations |
| `POST /api/fixes/apply` | Removes cut edges, recomputes |
| `GET /api/stream` | SSE: pushes graph/path updates |
| `GET /health` | Liveness |

## 5. The algorithm (Person A owns; about 150 lines)

1. Build DiGraph from inventory plus correlated events. Edge weight `w = -log(p)`.
2. Add `SUPER_SOURCE` -> every `external` node, `SUPER_SINK` <- every crown-jewel `data` node.
3. Top-k paths: `nx.shortest_simple_paths(G, SUPER_SOURCE, SUPER_SINK, weight="w")`.
4. Risk = path probability (product of p) × impact (target criticality).
5. Min-cut: split each node, capacity = remediation cost, `nx.minimum_cut`. Edges without capacity are uncuttable.
6. Best single fix: greedy, pick the edge that removes the most total risk.
7. Mitigation label: look up the technique in `attack_subset.json` (trimmed from `data/attack/enterprise-attack.json`).

## 6. Roles

| | Owner | Builds | Done when |
|---|---|---|---|
| **A** | Engine | `correlate.py`, `analyze.py`, graph build, tests | `GET /paths` and `/fixes` return correct results on the sample |
| **B** | Data and ingest | EvidenceForge setup, scenario YAML, parsers, `/ingest`, simulator, SQLite | Raw sample logs become Events; replay works |
| **C** | Frontend core | Cytoscape graph, path list, highlight, Play, Apply fix, SSE | Whole demo works against live API |
| **D** | Knowledge and explain | `attack_subset.json` trimmer, `inventory.yaml`, `narrate.py`, kill-chain bar, evidence panel | Each path has narrative, technique labels and mitigation |
| **E** | Platform and docs | Repo and branches, CI, deploy, `.env.example`, README, objectives docs, tests runner, bug-bounty hardening | Public URL up by H4; README satisfies section 4.1 of the rulebook |

Rules: each person pushes small, real commits to `main` (rebase, never force-push). Whole team must hit at least one meaningful commit every 120 minutes.

## 7. Timeline (H0 = now)

| Hours | Goal | Notes |
|---|---|---|
| H0-1 | Contracts and scaffolds | Freeze section 3. C builds against fixture JSON, A against fake events. E deploys hello-world to a public URL. B installs EvidenceForge. |
| H1-4 | Parallel build | B: first sample logs plus parsers. A: analyzer on fixture graph. D: inventory, ATT&CK subset. C: graph view. |
| H4 | **Integration 1** | Real parsed events -> real graph in the UI, locally |
| H4-8 | Close the loop | Simulate/Play, SSE live updates, Apply fix recomputes. Deployed. |
| H8 | **Checkpoint-1 ready** | End-to-end on the public URL. (Official deadline 15 Oct 1 PM.) |
| H8-12 | Depth | Narratives, evidence, mitigations, input validation, tests, objectives doc |
| H12-16 | Rehearse and sleep in shifts | Demo-ready for Judging Round 1 (15 Oct 8:30 AM) |
| After JR1 | Extras, in order | 1. GitHub sink (SARIF, Issue, PR check) 2. second log source 3. honeypot adapter |
| Before 16 Oct 12:00 AM | Hardening and freeze | `bugbounty` branch = deployable, setup docs complete |

## 8. Cut line

- **Must ship:** ingest (real parsers), graph, top-k paths, min-cut fix, Apply fix, live UI, narratives, public URL, README, objectives doc.
- **Strong extras:** ATT&CK mitigations on fixes, comparison to `GROUND_TRUTH.json`, GitHub Security tab / Issue / PR check.
- **Only if idle:** log-generator for cloud/auth noise, T-Pot/Cowrie adapter.
- **Dropped:** real laptop scanning CLI, GitHub-clone UI, auth/multi-tenant.

## 9. Demo (3 min)

1. Four "low" alerts side by side. 2. Press Play: raw logs stream in, parsed live, the four snap into one red path to the crown jewel.
3. Click path: kill-chain bar, narrative, evidence per hop. 4. Fixes panel: cheapest cut with ATT&CK mitigation; Apply fix; risk falls.
5. Show we recovered the `GROUND_TRUTH.json` path. 6. (If built) GitHub Security tab, Issue, failing PR check.

## 10. Rulebook checklist (E owns)

- README: team, summary, stack, run commands, env vars, tests, limitations, AI tools used (Claude Code), third-party (EvidenceForge MIT, log-generator PolyForm-NC, MITRE ATT&CK), synthetic-data label.
- `.env.example`, no secrets in git, no force-push.
- Objectives document before each judging round.
- Branches `main`, `bugbounty`, `fixing` exist. Evaluators need no private help.
- Hardening: size limits, schema validation, escape output, rate limit.

## 11. User flows (Figma rules: one goal per flow, start/end defined, decisions explicit, same symbols)

Notation: `( )` start/end, `[ ]` screen or step, `< >` decision.

**Flow 1: Sign in** (user: judge/evaluator or analyst; goal: reach the dashboard)
```
(Open public URL) -> [Login screen] -> <Have account?>
   yes -> [Enter email + password] -> <Valid?> yes -> (Dashboard)
                                              no  -> [Show error, 5 tries/min] -> [Login screen]
   no  -> <Quick start?> demo -> [Click "Use demo account"] -> (Dashboard)
                         new  -> [Register: email + password] -> (Dashboard)
```

**Flow 2: Compile and fix an attack path** (user: security analyst; goal: find and break the worst path)
```
(Dashboard, empty graph) -> [Press Play or Upload logs] -> [Events stream in, graph builds live]
  -> [Ranked path list] -> [Click top path] -> [Read story, kill-chain, evidence]
  -> <Accept suggested fix?> yes -> [Apply fix] -> [Paths re-rank, risk drops] -> (Risk LOW)
                             no  -> [Pick another fix or path] -> [Read story, kill-chain, evidence]
```

**Flow 3: Connect a log source** (user: admin; goal: send own events)
```
(Dashboard) -> [Settings > Sources] -> [Create API key] -> [Copy curl/CLI snippet]
  -> [Send events] -> <Accepted?> yes -> (Events appear on the graph)
                                   no  -> [Validation error shown] -> [Fix payload]
```

Auth design (kept minimal): `POST /api/auth/register`, `/login`, `/logout`, `GET /api/me`.
Passwords hashed (argon2/bcrypt), httpOnly session cookie, login rate-limited. Seeded demo account
documented in README (rulebook 4.1). Ingest uses per-source API keys (`X-API-Key`), not user cookies.
Owner: B (backend auth), C (login screen). Budget: 1.5 h. Cut: per-user workspaces (shared resettable demo workspace is fine).
