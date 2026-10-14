# Objectives (Round 2): Attack Path Compiler

All data is synthetic. Status is as of the last commit; "measured" numbers come from `scripts/benchmark.py`.

## 1. Real-time multi-source attack path correlation
Ingest heterogeneous events (Linux auth logs, web access logs, IDS alerts in Snort/Suricata fast format),
correlate them with an inventory of possible attack steps into one graph, and find the most probable paths to
critical assets. Events that match a step mark it confirmed, raise its probability and attach evidence.
**Evidence:** `/api/ingest`, `/api/graph`, `/api/paths`; Insights > alert compression.

## 2. Risk-based prioritisation and remediation
Rank paths by `product(edge p) x criticality / 10`. Compute the cheapest fix with a cost-weighted minimum cut and
the best single fix, label each with its ATT&CK mitigation, and show risk before and after execution. Deliver an
approved fix as a verified remediation (and, for source repos, a pull request).
**Evidence:** `/api/fixes`, `/api/remediations`, `risk_before`/`risk_after`, Insights > before/after.

## 3. Performance benchmarking and quantitative evaluation
Measure ingest latency, throughput, graph build, path search and end-to-end time on a seeded synthetic load, and
path/min-cut time on graphs up to ~2,000 nodes. The baseline is alert load, not an invented analyst time: raw
events versus confirmed steps versus ranked paths.
**Evidence:** `docs/BENCHMARKS.md`, `/api/metrics`, `/api/benchmarks`.

## 4. Interactive security operations dashboard
Live attack graph, ranked paths, per-path story, attack timeline, risk-over-time chart, fixes panel,
remediation workflow, log upload, API-key sources, repo and code scanning.
**Evidence:** UI (Dashboard and Insights views).

## 5. Explainable cyber threat analysis
Every path has a narrative, per-hop ATT&CK technique ids, evidence event ids, a kill-chain bar and the
mitigation rationale. Ranking and cuts are deterministic and unit-tested. AI (Claude Haiku) is optional: it
triages code findings and drafts runbooks and patches, and every patch is verified by code before it counts.
**Evidence:** `/api/paths/{id}`, `backend/tests`, `docs/MASTER_PLAN.md` decisions D2, D6, D7.

## Judging criteria map

| Judges evaluate | Objective |
|---|---|
| Solves the problem statement | 1 |
| Mathematical approach | 2, 5 |
| Before vs after | 2 |
| Empirical results, latency, throughput | 3 |
| UI / UX | 4 |
| Explainability | 5 |
| Practical viability | 1, 2, 4 |
