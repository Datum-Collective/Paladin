# Attack Path Compiler: Master Plan (v2, updated 14 Oct 2026)

Manipal Hackathon 2026, Round 2 (Technical). Team of 5. Coding began 14 Oct 10:00 AM.
This file is the single source of truth. It supersedes v1 and records what was built, what changed from the
earlier docs, and what is still open. All data is synthetic.

---

## 1. The problem and our answer

**Problem.** Security tools raise isolated alerts. Combinations of weak signals reveal how an attacker could
move through an organization. Build a system that turns heterogeneous security events into continuously
updated attack paths, correlates identities, permissions, applications, endpoints, secrets, services and
events, ranks paths by likelihood and impact, and finds the smallest defensive intervention that breaks the
most dangerous paths. Demonstrate with simulated events and an explainable model.

**Our answer.** Raw logs go in; a live graph comes out with ranked attack paths, a plain-English story and
ATT&CK labels per path, and the cheapest fix. A human approves the fix, a connector delivers it (local branch
plus GitHub PR), and later events verify it. A repo harness extends the same graph from source code.

| Brief says | We do | State |
|---|---|---|
| Heterogeneous events | Parsers for Linux auth, web access, Snort/IDS alerts into one Event schema | built |
| Correlate identities, permissions, apps, endpoints, secrets, services | `inventory.yaml` (possible steps) + events (live) + code findings in one graph | built |
| Continuously updated | Append-only store, recompute per request, SSE push | built |
| Construct attack paths | Super-source/super-sink + k shortest simple paths | built |
| Rank by likelihood and impact | risk = product(edge p) x target criticality / 10 | built |
| Smallest intervention | Cost-weighted min cut + greedy best single fix, ATT&CK mitigations | built |
| Simulated events | EvidenceForge logs from our hand-written scenario | **scenario written, logs not generated yet** |
| Explainable | Per-hop evidence, technique ids, kill-chain bar, narrative | built (ground-truth compare open) |
| Act on the result | Remediation lifecycle, audit log, verify loop, repo harness -> PR | built |

---

## 2. What we use from each document

| Document | What we took | What we did NOT take |
|---|---|---|
| `docs/BUILD_PROMPT.md` | Hard rules, stack, repo layout, data contracts, module list, API list, definition of done | Per-owner split: one session built backend + UI end to end |
| `docs/MASTER_PLAN.md` v1 | Rulebook constraints, VPS + Caddy deployment, simulated-data plan, timeline, demo script, cut line | Open items now resolved or re-listed in section 12 |
| `docs/PLAN.md` | Contracts-first approach, 5+ endpoints, user flows, rulebook checklist for owner E | TypeScript-era algorithm notes (superseded) |
| `docs/research/attack-path-compiler.md` | BloodHound-style graph model, ATT&CK labelling, min-cut formulation, SARIF/Checks/Issues API notes, 3-minute demo | OCSF export, Sigma rules, local laptop scanning (cut) |
| `MASTER_PLAN_REVIEW.md` | Single-service deploy; confirm formats before parsers; pin scenario + ground truth; schedule GitHub unknowns; min-cut/ATT&CK/auth validation | Per-hop geometric-mean score (see decision D2) |
| EvidenceForge README + example scenario | Scenario schema, output formats (syslog, web_access, snort_alert), GROUND_TRUTH answer keys | Its LLM skills (rulebook: no LLM-made logs) |

---

## 3. Rulebook constraints that shape the build

| Rule | Consequence |
|---|---|
| No pre-event code, designs, schemas, prompts | Everything project-specific written after 14 Oct 10:00 AM |
| Disclose AI tools; team must explain and debug all code | README lists Claude Code and the Claude API features; every owner reads what they merge |
| Cite third-party code, data, licences | EvidenceForge (MIT), MITRE ATT&CK, FastAPI, networkx, bcrypt, React, Vite, Cytoscape |
| One meaningful commit per 120 min, no force-push or squash | Small real commits to `main` |
| No secrets in git, `.env.example` required | All keys in server env; `.env.local` ignored |
| Synthetic, anonymized or labelled data only | Sample logs labelled synthetic. The repo harness is for repos the user is permitted to scan |
| Public URL, LAN, or Docker; up until the end | One Docker image on a VPS behind Caddy |
| Evaluators test alone, no paid APIs in the core path | Demo account; AI and GitHub are optional flags with deterministic fallbacks |
| Checkpoint 1: 15 Oct 1:00 PM; Checkpoint 2: 15 Oct 9:30 PM | Section 11 |
| Bug bounty 16 Oct 12:00-2:00 AM on frozen `bugbounty` branch | Section 10 hardening |

Schedule: JR1 15 Oct 8:30-11:00 AM, JR2 15 Oct 6:30-8:30 PM, JR3 and bounty review 16 Oct 8:30-10:00 AM,
finals 16 Oct 10:30 AM-1:00 PM.

---

## 4. Architecture (as built)

```
 EvidenceForge logs ─┐                                   ┌─ GitHub repo URL ──► harness
 API key / upload ───┤ POST /api/ingest                  │   clone -> scan -> fix -> verify
 Play (replay) ──────┘        │                          │   -> local branch -> approved PR
                              ▼                          ▼
        parsers ─► Event ─► SQLite ──► correlate ◄── code findings (codescan)
                              inventory.yaml ──────────►│
                                                        ▼
                         graph (networkx) ─► analyze: top-k paths, risk, min cut, best single fix
                                                        ▼
                         remediation lifecycle (proposed > approved > executed > verified)
                                                        ▼
                         FastAPI ──SSE──► React + Cytoscape UI
```

**Core idea.** The inventory says which steps are *possible*. Logs say which are *happening*. The code scan
adds weaknesses found in source. The engine composes them into paths and finds the cheapest cut.

### Stack

- Backend: Python 3.12, FastAPI, networkx, SQLite (stdlib), bcrypt, httpx, pytest.
- Frontend: React, Vite, Cytoscape.js (dagre layout).
- Deploy: one Docker image (multi-stage; includes `git` for the harness); FastAPI serves `/api/*` and the UI.
  VPS + Caddy via `docker-compose.yml` / `deploy.sh`. Local: Colima + docker on macOS.

### Repo layout (actual)

```
backend/app/
  main.py            API, ingest, simulate, graph/paths/fixes, SSE, static mount (last)
  models.py          Event / Node / Edge (pydantic)
  parsers/           linux_auth, web_access, snort_alert, registry
  inventory.py       loads data/inventory.yaml
  correlate.py       events confirm edges, saturating p update, evidence ids
  analyze.py         graph build, top-k, risk, min cut, best single fix, count-cut baseline
  engine.py          snapshot: inventory + code model + events + applied fixes
  narrate.py         per-hop story, kill-chain order, ATT&CK names
  remediation.py     lifecycle, audit, verify-by-later-events, rollback
  remediation_api.py /api/remediations/*
  codescan.py        static rules + Haiku triage -> graph nodes/edges
  fixers.py          deterministic fixes, Haiku search/replace patch, code-verified
  harness.py         URL -> safe clone -> scan -> fix -> branch -> PR
  harness_api.py     /api/harness/*
  ai.py              optional Claude calls (flagged, fails closed)
  auth.py, store.py  sessions, API keys, SQLite
backend/tests/       31 tests (engine, API, remediation, codescan, harness)
frontend/src/        App.jsx, Graph.jsx, api.js
data/                inventory.yaml, attack_subset.json, samples/ (empty), attack/ (local only)
scenarios/           stalk-branch.yaml (hand-written)
scripts/             build_attack_subset.py
docs/                MASTER_PLAN.md, contracts.md, PLAN.md, BUILD_PROMPT.md, research/
```

---

## 5. Data contracts (frozen in `docs/contracts.md`)

- Event `{id, ts, source, type, actor, host, src_ip, dst, outcome, attack, raw}`
- Node `{id, kind, label, criticality 1-10}`; Edge `{id, src, dst, technique, p, cost|null, observed, evidence[], mitigation, match}`
- Path `{id, nodes, edges, p, impact, risk, severity, tactics, narrative, hops}`; Fix `{edges, total_cost, paths_broken, risk_removed_pct, mitigations}`
- Remediation `{id, edges, state, title, runbook, ai_drafted, connector, note}` + audit rows.

Probability update: a distinct matching event sets `observed` and `p' = min(0.99, p + (1-p) * 0.5)`.
Severity: CRITICAL >= 0.30, HIGH >= 0.10, MEDIUM >= 0.03, else LOW.

---

## 6. Algorithm (analyze.py)

1. Build a DiGraph from inventory + code model + correlated events; `w = -log(p)`.
2. SUPER_SOURCE -> every `external` node; every `data` node with criticality >= 8 -> SUPER_SINK.
3. `nx.shortest_simple_paths(..., weight="w")`, k capped at 50, graph capped at 2000 nodes.
4. `risk = product(edge p) x criticality / 10`; paths are sorted by this value and it is the value displayed.
5. Min cut over paths with risk >= 0.03 (edges with `cost: null` are uncuttable); greedy best single fix;
   a count-minimising cut is computed as a baseline so the UI can show cost beats edge count.
6. Total risk = sum over top-k paths, capped at 1.0.

### Decisions that differ from, or settle, earlier docs

| # | Decision | Why |
|---|---|---|
| D1 | One shared workspace per user (`ws` = user id), demo user seeded | Isolation without a full tenant model; resets can't touch others |
| D2 | Keep the product score (not per-hop geometric mean) | Ranking and display use the same number; length penalty is intended. Review's inconsistency concern is met because we sort by the displayed risk |
| D3 | Min cut on edge capacities (cost) rather than node-split | Costs live on edges; equivalent and simpler. `minimum_node_cut` is not used |
| D4 | ATT&CK bundle untracked; trimmed `attack_subset.json` ships | 53 MB stays out of the repo and image |
| D5 | Single-service Docker deploy on a VPS (not Render + Vercel) | One URL, no CORS, no sleeping free tier |
| D6 | AI is optional and never in the decision path | Rulebook: no paid API in the core path; defensibility |
| D7 | PRs are opened only after an explicit human approval click | Outward-facing action; audit trail |

---

## 7. Ingest and simulated data

Three ways in, one code path (`ingest_events`): Play replays `data/samples/` via `manifest.json`; Upload sends
lines with a format; API sends with `X-API-Key`. IPs are normalised to inventory host names.

EvidenceForge is the only log source (deterministic, no LLM). `scenarios/stalk-branch.yaml` is hand-written:
two users, five systems, one IDS sensor, three-step storyline (web scan, ssh as `www-data`, RDP to the file
server) plus one red herring. **Not generated yet.** On generation:

1. `eforge validate` then `eforge generate` with a fixed seed into `scenarios/output`.
2. Inspect real files; fix parser regexes and `match` specs in `inventory.yaml` (RDP may need Windows or
   Cisco ASA evidence and a fourth parser).
3. Commit `data/samples/` + `manifest.json` + the command and seed in the README.
4. Convert `GROUND_TRUTH` (README says `.json` and `.md` exist; review said `.md` only: verify) once and
   commit; add a CI test that the top recovered path contains the ground-truth node ids.

---

## 8. Remediation and AI

State machine: `proposed -> approved -> executed -> verified | failed -> rolled_back`, every step audited.
`verify` passes only if the edges are closed and no event ingested after execution still matches them.

| Feature | Deterministic path (always works) | Optional AI (`ANTHROPIC_API_KEY`) |
|---|---|---|
| Runbook | Template per ATT&CK mitigation | Haiku rewrites from structured facts only |
| Code-finding triage | Static rule hit, confidence 0.5 | Haiku: exploitable?, confidence, reason (validated JSON) |
| Patch | Rule rewrites (hash, TLS, yaml, debug, secret->env) | Haiku `{old,new}` edit, accepted only if code verifies it |

Execute today closes the edge **in our model**; the repo harness is the real connector (branch + PR).

## 9. Repo harness

`https://github.com/<owner>/<repo>` only -> shallow clone (hooks off, symlinks off, no submodules, time and size
caps, repo code never executed) -> static scan + triage -> findings join the graph -> fixes (max 25) verified
by code -> commit on `apc/fix-N` -> human clicks Approve -> push (fork if no write access) -> PR whose body
lists CWE/ATT&CK ids, says if AI was used, and states that tests were not run. No token: patch download only.

---

## 10. Auth and security

Today: bcrypt, httpOnly SameSite=Lax session cookies, login rate limit, per-source API keys (hashed),
per-workspace isolation, demo sign-in endpoint with server-side credentials.
Planned (friend): Supabase auth, roles (`can_approve` hook exists), CSRF/Origin check, hashed session tokens,
persistent rate limit, audit of logins.

Bounty checklist: body/line/file caps, strict schema validation, no stack traces, security headers, auth on
all private endpoints, escaped UI output (React), secrets only in env, `npm audit`/`pip` dependency check,
test with a second browser profile and malformed payloads. **Open:** a timeout around path generation (only
caps exist today).

---

## 11. Team roles, timeline, demo, cut line

| Owner | Slice | Status |
|---|---|---|
| A Engine | analyze/correlate/tests | done; add generation timeout |
| B Data/ingest | scenario, EvidenceForge, parsers, replay | **scenario done; generation + parser verification open** |
| C Frontend | UI | done; polish + fixtures |
| D Knowledge | inventory, ATT&CK subset, narrative, ground truth | inventory + subset + narrative done; ground truth open |
| E Platform | VPS, HTTPS, CI, README, objectives doc | CI + Dockerfile done; **VPS/domain, objectives doc open** |
| Friend | Supabase auth, roles, hardening | in progress |

| When | Goal |
|---|---|
| 15 Oct 1:00 PM | Checkpoint 1: deployed, one end-to-end flow (needs sample logs + public URL) |
| 15 Oct 8:30 AM / 6:30 PM | JR1 / JR2 |
| 15 Oct 9:30 PM | Checkpoint 2: 5+ APIs (done), real inputs: evaluator can POST events |
| 16 Oct 12:00 AM | `bugbounty` branch frozen and deployable with setup docs |
| 2:00-3:30 AM | Fixing phase on `fixing`, then merge to `main` |

Demo (3 min): four low alerts side by side -> Play -> one critical path with evidence -> cheapest fix with
mitigation -> Propose, approve, execute, verify, risk drops -> paste a repo URL, show the PR diff -> ground
truth match. Rehearse twice; keep a recorded backup.

Cut line. Must: parsers, graph, paths, min cut, remediation, live UI, auth + demo, public URL, README,
objectives doc. Strong extras: ATT&CK mitigations, ground truth, repo harness PR. Only if idle: OCSF export,
honeypot adapter. Dropped: laptop scanning CLI, multi-tenant admin.

---

## 12. Open items (priority order)

1. Run EvidenceForge (blocked on permission to execute the cloned tool), commit `data/samples/`.
2. Correct parsers and `match` specs against real output; add fourth parser if RDP needs it.
3. Ground-truth conversion and CI assertion.
4. VPS, domain, HTTPS, `./deploy.sh main`; second teammate with SSH access.
5. Generation timeout on `shortest_simple_paths`; widen candidate pool before re-sorting by risk.
6. Supabase auth + roles; CSRF; hashed sessions.
7. Test the live Haiku and real GitHub PR paths with a throwaway repo and fine-grained token.
8. GitHub unknowns (secret-scanning API, check runs with `GITHUB_TOKEN`, SARIF `codeFlows`) and screenshots.
9. README completion (section list in v1 is still the checklist) and the objectives document.

## 13. README checklist (rulebook 4.1)

Project and team; solution summary; architecture and stack; environments; dependencies; install/run;
deployment/access; env vars (`SECRET_KEY`, `DEMO_USER`, `DEMO_PASSWORD`, `COOKIE_SECURE`, `ANTHROPIC_API_KEY`,
`AI_MODEL`, `GITHUB_TOKEN`, `PORT`, `STATIC_DIR`, `SEED_DIR`, `DATA_DIR`); DB setup; tests; limitations; AI
disclosure (Claude Code, Claude API features); third-party and licences; synthetic-data statement;
Dockerfile commands; test account.
