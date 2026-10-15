# Paladin attack intelligence and research validation

**Scope and revision.** This report audits the code at `b3fd8e5` on 2026-10-15. It is a source, deterministic-test,
and local-synthetic-benchmark review. It does not attest to detection on a production network, exploitability of a
specific customer finding, or zero-day discovery.

## Executive result

Paladin has three distinct evidence classes:

1. **Observed activity:** parsed web, Linux-auth, and IDS events can confirm a small, configured set of inventory
   edges. The event identifier is retained as evidence.
2. **Static candidates:** twelve deterministic source-code rules report potential weaknesses. A match is not proof that
   the weakness is reachable or exploitable.
3. **Inferred graph steps:** inventory priors, route reachability, import relationships, and impact edges make a path
   explorable. These are explicitly marked `assumed` or `reference`; they are not observations.

The engine ranks paths across those supplied edges. It does **not** prove exploit preconditions, infer new exploit
semantics, or detect zero-days. It can reveal an unenumerated *combination* of configured or scanned edges, subject to
the graph's finite rules and assumptions.

## Verified attack and weakness coverage

### Log evidence

| Category | Detection and required input | Evidence / mapping | Type and validated tests | Limits |
|---|---|---|---|---|
| External web reconnaissance | Combined Apache/Nginx access line with a scanner user agent or a sensitive probe path (`/.env`, `/.git`, `../`, etc.). | `web_scan`, source IP, target host, raw line; parser labels **T1595.002**. Inventory may confirm `scan-web`, whose configured technique is **T1190**. | Observed event; positive end-to-end evidence in `backend/tests/test_api.py::test_ingest_raises_risk_and_fix_lowers_it`; malformed input is rejected in the same test. | Signature heuristic; no request-body inspection, exploit success validation, CVE identification, or general WAF evasion handling. The parser's ATT&CK label and the inventory edge's T1190 meaning differ and must not be presented as a precise ATT&CK conclusion. |
| SSH valid-account login | Linux syslog/RFC5424 `Accepted ... for user from IP`. | `auth_success`, actor, host, IP; **T1078**. Only actor `www-data` matches the provided `ssh-wwwdata` inventory edge. | Observed event; positive ingestion in `test_api.py::test_ingest_raises_risk_and_fix_lowers_it` and sample replay in `test_play_sample_scenario_produces_ranked_path`. | A successful login is not proof of compromise; no authentication provenance, privilege level, session duration, or command telemetry is required. |
| SSH password spray / invalid account | Linux auth `Failed ...` or `Invalid user ...`. | `auth_failure`; **T1110**. | Observed parsed event only; parser code is `backend/app/parsers/linux_auth.py`. No inventory edge consumes it. | No thresholding, source aggregation, or graph correlation rule. It is not currently a ranked attack path. |
| IDS reconnaissance or exploit alert | Snort/Suricata fast-format alert containing `scan`, `exploit`, or `web`. | `ids_alert`, source/destination, raw line; `scan` => **T1046**, `exploit`/`web` => **T1190**. In the supplied inventory, destination-only matching can confirm `scan-web` or `rdp-file`. | Observed event; accepted/malformed-date rejection in `backend/tests/test_audit_regressions.py::test_snort_alert_with_impossible_date_is_a_rejected_line_not_a_stored_event`. | No signature-ID semantics, port condition, actor identity, alert confidence, deduplication, or packet evidence. A destination-only inventory match is correlation evidence, not proof of RDP or exploitation. |

The three supported input formats are registered in `backend/app/parsers/registry.py`; all parser rows are bounded in
the `Event` model. The synthetic sample documents web scan -> `www-data` SSH -> admin RDP as a story, but it is not a
real intrusion dataset ([ground truth](/Users/bhuvi/Desktop/DATUM/data/samples/GROUND_TRUTH.md)).

### Deterministic static code rules

`backend/app/codescan.py:18-44` defines the implemented rules. They are static pattern matches and each produces a
file, line, masked snippet/context, CWE, application-selected ATT&CK technique, and a potential graph weakness.

| Rule | CWE / assigned ATT&CK | Required evidence and graph effect | Positive / negative evidence | Main limitation |
|---|---|---|---|---|
| Hard-coded credential | CWE-798 / T1552.001 | Assignment whose credential-like name contains a quoted 8+ character value; reaches a secret data node. | Positive in `test_codescan.py::test_static_scan_finds_and_redacts`; secret redaction verified there and in `test_audit_regressions.py::test_secret_rule_still_finds_real_secrets`. | Entropy, validity, repository history, and exposure are not checked. |
| Dynamic code execution | CWE-95 / T1059 | `eval(` or `exec(`; host-impact node. | Rule is enumerated and the long-line guard test protects its scan path. | No taint flow or language-aware parse; benign controlled uses can match. |
| Shell command execution | CWE-78 / T1059 | `shell=True`, `os.system`, or Node `child_process.exec`; host impact. | Positive fixture contains `subprocess.run(..., shell=True)` in `test_codescan.py`. | Does not prove attacker-controlled argument, shell reachability, or command execution. |
| SQL built from strings | CWE-89 / T1190 | SQL call with f-string/concatenation/format; database impact. | Positive in `test_static_scan_finds_and_redacts`; cross-file route -> SQL path and invalid-review rejection in `test_crawler.py::test_analyze_end_to_end_builds_cross_file_attack_paths` and `test_validate_keeps_only_claims_that_quote_real_lines_and_downgrades_unproven_flows`. | No dataflow/sanitizer analysis; T1190 is an application mapping, not a claim that external exploitation happened. |
| Unsafe deserialization | CWE-502 / T1190 | `pickle.loads`, unsafe `yaml.load`, or `marshal.loads`; host impact. | Rule implementation is covered by the common bounded scanner path. | No attacker-control or loader configuration proof. |
| TLS verification disabled | CWE-295 / T1557 | `verify=False` or `rejectUnauthorized:false`; intercepted-traffic impact. | Rule implementation; no dedicated positive/negative test. | Does not establish a live MITM opportunity. |
| Weak hash | CWE-327 / T1110 | MD5/SHA-1 constructor; credential impact. | Positive fixture and remediation verification in `test_verification.py::test_job_runs_independent_final_verification`. | Does not determine whether the hash is used for password storage or a non-security checksum. |
| XSS sink | CWE-79 / T1189 | `innerHTML`, `dangerouslySetInnerHTML`, or `document.write`; session impact. | Two independent findings/paths verified by `test_graph_model.py::test_each_finding_is_its_own_node_and_path`. | Sink-only match: no source, escaping, CSP, or browser exploitability analysis. |
| Permissive CORS | CWE-942 / T1190 | Wildcard CORS patterns; session impact. | Positive fixture in `test_graph_model.py::test_entry_exposure_is_not_a_fix_and_fixes_target_findings`. | Does not model credentials, origin reflection, or endpoint sensitivity. |
| Missing `noopener` | CWE-1022 / T1189 | `target=_blank` without a `rel` attribute; session impact. | Rule implementation; no dedicated positive/negative test. | Regex can miss valid multi-line markup and cannot establish opener abuse. |
| HTTP script source | CWE-829 / T1189 | `<script src="http://...">`; session impact. | Guard-preservation positive in `test_audit_regressions.py::test_long_line_guards_keep_real_matches`. | No SRI, redirect, HTTPS-upgrade, or runtime-load analysis. |
| Debug mode | CWE-489 / T1190 | `debug=True`; host impact. | Rule implementation; no dedicated positive/negative test. | No framework/config/environment context. |

The file filter rejects traversal paths, secrets, dependencies, generated output, files over 200 KB, and total input
over 3 MB (`codescan.py:74-116`); `test_accept_files_filters` is the negative test. The scanner is deliberately
bounded by time and 60 findings (`codescan.py:119-149`); hostile long-line, over-large-file, and time-budget
negative tests are in `test_audit_regressions.py`.

### AI review and dependency advisory enrichment

The optional repository crawler can identify route declarations and imports, query OSV for pinned dependencies, and
ask a provider to review bounded/redacted excerpts. A review claim is retained only when its file, exact line, quoted
text, and CWE format validate against the source (`codescan.py:283-346`; crawler validation tests in
`test_crawler.py`). Published advisory IDs are evidence of a dependency advisory, not evidence that vulnerable code
is reachable. Provider findings remain potentially fallible even after line validation.

Potential categories named in the reviewer prompt—path traversal, SSRF, authorization, configuration, and sensitive
data exposure—are **not deterministic rules**. They can appear only as an optional, source-quoted AI-review claim;
they are not guaranteed coverage and have no per-category deterministic positive/negative suite.

## Graph model, reasoning, and research comparison

### Actual model and workflow

`Node` kinds are identity, host, secret, role, service, data, external, component, and weakness
(`backend/app/models.py:6-42`). Edges carry probability, remediation cost, technique, observation flag, evidence IDs,
and basis (`finding`, `reference`, or `assumed`). `engine.snapshot` combines inventory only when event evidence exists
with a separately constructed code model, correlates events, builds a directed graph, ranks paths, and attaches the
supporting events (`backend/app/engine.py:12-63`). The two models are intentionally not joined merely because they
share a workspace; `test_graph_model.py::test_both_sources_are_separate_components` verifies that separation.

Correlation is exact field matching against each configured edge, then raises its prior toward 0.99 and attaches no
more than 20 event IDs (`backend/app/correlate.py:17-33`). It does not learn probabilities from data or require all
multi-step prerequisites.

The graph adds a synthetic source to every `external` node and a synthetic sink to `data` nodes with criticality >= 8.
It ranks up to 50 simple paths: NetworkX k-shortest paths use `-log(p)` for likelihood, up to `min(4k, 200)` candidates
and a two-second budget, then the candidates are re-ranked by `product(p) * impact / 10`
(`backend/app/analyze.py:9-100`). Aggregate risk is noisy-or, not a calibrated Bayesian posterior. Costed minimum cut
and greedy single-edge fixes consider only paths at risk >= 0.03 (`analyze.py:104-190`).

| Research baseline | Similarity | Material difference / limitation |
|---|---|---|
| Sheyner et al., *Automated Generation and Analysis of Attack Graphs* (IEEE S&P, 2002, DOI [10.1109/SECPRI.2002.1004377](https://doi.org/10.1109/SECPRI.2002.1004377)) | Automatic graph construction from modelled steps; path analysis and prevention/cut reasoning resemble the decision-support goal. | Paladin is not symbolic model checking, does not represent global system states or exhaustive transitions, and cannot claim completeness/soundness for all possible attacks. |
| Ou, Govindavajhala & Appel, *MulVAL* (USENIX Security, 2005, [official paper](https://www.usenix.org/event/sec05/tech/full_papers/ou/ou.pdf)) | Multi-stage composition and data from scans/configuration are shared ambitions. | No Datalog, CVE/OVAL logic, host/OS privilege semantics, AND prerequisites, or formal hypothetical-vulnerability analysis. |
| Ingols et al., *Validating and Restoring Defense in Depth Using Attack Graphs* (MILCOM, 2006, DOI [10.1109/MILCOM.2006.302434](https://doi.org/10.1109/MILCOM.2006.302434)) / NetSPA | Configured network steps and minimum-cost intervention are analogous. | No firewall rule import, reachability computation, vulnerability-scanner import, or enterprise network model; supplied inventory is small and synthetic. |
| Poolsappasit, Dewri & Ray, *Dynamic Security Risk Management Using Bayesian Attack Graphs* (IEEE TDSC, 2012, DOI [10.1109/TDSC.2011.34](https://doi.org/10.1109/TDSC.2011.34)) | Edge probabilities and a noisy-or aggregate offer a simple likelihood-weighted prioritisation. | No Bayesian network/conditional probability tables, posterior inference, independence validation, or probability calibration. Risk values are prioritisation scores. |
| MITRE, *Toward a Knowledge Graph of Cybersecurity Countermeasures* (2021, [official PDF](https://d3fend.mitre.org/resources/D3FEND.pdf)) | Paladin records MITRE ATT&CK identifiers and mitigation identifiers next to steps. | It does not import or reason over D3FEND ontology relations, artifacts, or defensive technique mappings. The local mitigation strings are not D3FEND inference. |
| Konsta et al., *Survey: Automatic Generation of Attack Trees and Attack Graphs* (Computers & Security 137, 2024, DOI [10.1016/j.cose.2023.103602](https://doi.org/10.1016/j.cose.2023.103602)) | Paladin fits the survey's analysis-/vulnerability-driven family: source rules and configured evidence generate a directed model. | The survey's concerns—input fidelity, formal rigor, scalability, and reproducibility—remain open here; the local benchmark is a limited reproducible baseline, not a general scalability claim. |

## Known attacks, correlation, and impossible paths

- **Documented weaknesses:** deterministic rules detect only their textual patterns; OSV output reports published IDs
  when a dependency is pinned and the service is reachable.
- **Correlation:** yes, the engine joins multiple matching events with inventory edges and ranks chains. The sample
  replay test produces at least one ranked path.
- **Previously unenumerated paths:** only combinations of nodes/edges already supplied by inventory or scan results.
  Import edges allow a route file to reach a separately detected weak file; `test_crawler.py::test_analyze_end_to_end_builds_cross_file_attack_paths` exercises this.
- **Prerequisites / impossible paths:** no formal AND/OR prerequisite engine, reachability proof, identity privilege
  model, or temporal-causal constraint exists. The engine rejects graph edges whose endpoints are absent and returns
  no path for disconnected graphs (`test_analyze.py::test_disconnected_and_no_path`), but this is graph consistency,
  not attack feasibility. Hence it cannot claim to reject all impossible paths.
- **Unseen scenarios:** new valid combinations of the finite rules can be ranked. New vulnerability classes, novel
  exploit mechanisms, and zero-days cannot be claimed without independently validated detections.

## Remediation validation

For model edges, execution removes selected graph edges, records before/after risk and path counts, and verification
requires both closed edges and no later matching event (`backend/app/remediation.py:167-207`).

Measured test evidence: `test_remediation.py::test_full_lifecycle_verified` proves a configured web-scan fix lowers
model risk and verifies only with no later match; `test_verify_fails_when_still_observed` proves a repeated scan
fails verification; `test_rollback_restores_risk` proves rollback restores the model result. `test_analyze.py::test_min_cut_is_cost_weighted`
shows the cut chooses `e2+e4` at cost 3 over entry edge `e1` at cost 5. These validate graph-model disruption, not a
change to a production host.

For code remediation, verification rereads the patched files and checks parseability and the targeted rules, but
explicitly says tests were not run (`remediation.py:219-235`). `test_verification.py::test_job_runs_independent_final_verification`
independently recompiles a patched Python fixture and confirms findings decrease. That is stronger than a visual
claim, but still not a production deployment validation.

## Reproducible scalability measurements

Command: `/private/tmp/datum-main-venv312/bin/python scripts/benchmark.py`. It runs the real parsers,
correlator, and graph algorithms against deterministic synthetic data (seed 7), excluding Supabase/HTTP/network.
Peak is Python `tracemalloc`, not process RSS. Measurements were produced locally on Darwin arm64, 6 CPUs, Python
3.12.14 at 2026-10-15 19:27:45; full data is in [BENCHMARKS.md](/Users/bhuvi/Desktop/DATUM/docs/BENCHMARKS.md).

| Synthetic events | End-to-end ms | Correlate + graph + top paths ms | Peak KiB | Confirmed edges / paths |
|---:|---:|---:|---:|---:|
| 1,000 | 196.3 | 64.42 | 2,800.6 | 2 / 8 |
| 10,000 | 1,690.9 | 533.29 | 27,133.3 | 2 / 8 |
| 50,000 | 8,948.0 | 2,515.1 | 135,635.6 | 2 / 8 |

| Synthetic layered graph | Nodes / edges | Build ms | Top-10 ms | Min-cut ms | Peak KiB | Paths returned |
|---|---:|---:|---:|---:|---:|---:|
| sparse layered | 106 / 309 | 1.6 | 145.5 | 7.7 | 873.2 | 10 |
| medium layered | 501 / 1,494 | 8.7 | 958.0 | 6.3 | 4,116.6 | 10 |
| denser layered | 1,986 / 5,949 | 41.0 | 2,075.8 | 14.4 | 16,084.1 | 8 |

At the largest graph, the two-second top-path budget was reached, so only eight paths were returned. This is an
intentional completeness trade-off, not a proof that only eight paths exist. `MAX_NODES=2000` also rejects larger
models before construction.

## Limitations and defensible judge-facing claims

Safe claims: Paladin parses three specified log formats; creates evidence-linked correlations for configured
inventory edges; identifies twelve static pattern classes; builds distinct source/weakness/asset graph nodes; ranks
bounded candidate paths; and demonstrates graph-level remediation disruption with regression tests.

Do not claim: CVE detection from logs, exploit confirmation from a static match, calibrated exploit probability,
complete attack enumeration, formal prerequisite enforcement, production remediation, D3FEND reasoning, or zero-day
detection. Future research should add machine-readable topology/firewall and CVE/OVAL facts, explicit AND/OR
prerequisites and temporal constraints, probability calibration against labelled incidents, D3FEND ontology mappings,
independent benchmark corpora, and process-RSS/large-graph performance testing.
