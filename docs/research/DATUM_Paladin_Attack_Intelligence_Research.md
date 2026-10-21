# DATUM / Paladin — Attack Intelligence, Graph Reasoning and Research Foundation

**Research brief | 15 October 2026**  
**Status:** Research architecture and evaluation guidance. Actual DATUM capabilities require source-code and test verification.  
**Purpose:** Hackathon technical defense, engineering audit, and research-backed product positioning.

## Executive summary

Paladin's strongest defensible research proposition is **evidence-grounded correlation of individual security weaknesses into plausible multi-step attack paths, followed by explainable remediation analysis**. It should not claim to discover zero-days or novel exploitation techniques solely because a graph traversal produces a new route.

A robust demonstration should connect: **input → observed evidence → validated finding → prerequisite-aware graph → possible attack path → remediation cut → measured effect**.

## 1. Threat and attack taxonomy

| Area | Representative threats | Evidence / prerequisites | Potential Paladin analysis |
|---|---|---|---|
| Credentials | Leaked API keys, token exposure, stolen credentials | Repository secret, credential scope | Identify exposure; correlate access rights if known |
| Injection | SQL and command injection, unsafe input handling | Data flow or convincing code evidence | Static weakness finding, not proof of exploitation |
| Access control | Broken object authorization, excessive privileges | Identity and authorization rules | Model privilege-transition prerequisites |
| Supply chain | Vulnerable dependencies, malicious build configuration | Manifest, lockfile, advisories, workflow | Dependency/configuration risk correlation |
| Cloud/container | Exposed services, unsafe container settings | Config and environment facts | Model reachable assets and permissions |
| Lateral movement | Compromise in one system leading to another | Verified connectivity and credentials | Candidate multi-step paths |
| Exfiltration | Unauthorized route to sensitive data | Data store, read permission, network path | Potential path to high-value target |
| Denial of service | Unbounded parser resource use, computational exhaustion | Reproducible local fixture | Resource-safety finding and regression test |
| Persistence/evasion | Suspicious service changes or task execution | Runtime logs and telemetry | EvidenceForge analysis only if supported by parsers |
| AI-specific | Prompt injection, untrusted tool instructions | Untrusted repo text, model/tool boundary | Assess trust-boundary protections |

**Claiming discipline:** A code finding is not necessarily an observed attack. An ATT&CK mapping is not confirmation that a technique occurred. Capability support must be supported by code, data and tests.

## 2. Existing attacks, novel combinations, and genuinely unknown techniques

### Known patterns
Recognize documented weaknesses, known CVEs, suspicious patterns, and ATT&CK-aligned behaviors using explicit rules, version data, validated evidence, or supported telemetry.

### Novel *combinations* of known weaknesses
A path may be new to the assessed environment even when every weakness is familiar. Example (hypothetical): exposed service token → access to a privileged service → excessive database permissions → sensitive data reachable. Each arrow requires evidence of permissions, connectivity, and conditions; the graph must not assume them.

### Genuinely novel techniques
A novel exploit primitive or zero-day is a separate, substantially stronger claim. Graph discovery does not prove such novelty; independent reproduction and external validation are needed.

## 3. Graph representation and reasoning

A useful graph should distinguish:

- **Assets:** repositories, services, identities, data stores, devices.
- **Weaknesses:** vulnerable dependencies, insecure permissions, code flaws.
- **Evidence:** source location, log event, configuration excerpt, provenance.
- **Prerequisites:** conditions necessary for exploitation (e.g., network access **and** valid credential).
- **Transitions:** potential changes in attacker capabilities.
- **Objectives:** sensitive target or modeled security impact.
- **Countermeasures:** changes capable of disrupting the path.

### Recommended conceptual pipeline

```text
Repository / logs / configuration / supported inputs
                   |
                   v
     Parse, normalize, preserve provenance
                   |
                   v
       Validate and classify findings
                   |
                   v
    Build prerequisite-aware security graph
                   |
                   v
    Search and validate possible attack paths
                   |
                   v
   Analyze remediation cuts and tradeoffs
                   |
                   v
 Explain paths, evidence, uncertainty and limits
```

**Logical edges matter:** If exploitation requires both access and a credential, simple independent directed edges can incorrectly treat those as alternatives. AND/OR logical prerequisites or hypergraph-like representations may be required. Do not assume the current product implements these until inspected.

| Technique | Appropriate use | Caveat |
|---|---|---|
| Reachability | Determine if a modeled target can be reached | Dependent on valid edges and prerequisites |
| Shortest path | Find minimal *assigned-cost* routes | Shortest does not mean most likely |
| Centrality | Flag influential nodes or relationships | Not automatically a risk score |
| Minimum cut | Find interventions interrupting specified paths | Must confirm feasible remediation actions |
| Logic-based attack graph | Express conjunctions and inference rules | Depends on correct environmental facts |
| Bayesian attack graph | Estimate conditional compromise likelihood | Requires defensible probabilities and calibration |

## 4. Research foundation

These are established papers/resources to consult and cite. Their findings support research directions, **not proof that Paladin has implemented them**.

1. **Sheyner, Haines, Jha, Lippmann & Wing (2002)**. *Automated Generation and Analysis of Attack Graphs*. IEEE Symposium on Security and Privacy. Foundational automated attack-graph/model-checking approach. https://www.ll.mit.edu/r-d/publications/automated-generation-and-analysis-attack-graphs
2. **Ou, Govindavajhala & Appel (2005)**. *MulVAL: A Logic-based Network Security Analyzer*. USENIX Security Symposium. Demonstrates logical security preconditions and attack graph analysis. https://www.usenix.org/conference/14th-usenix-security-symposium/mulval-logic-based-network-security-analyzer
3. **Lippmann et al. (2006)**. *Validating and Restoring Defense in Depth Using Attack Graphs*. IEEE MILCOM. NetSPA attack analysis and defensive prioritization. https://www.ll.mit.edu/r-d/publications/validating-and-restoring-defense-depth-using-attack-graphs
4. **Poolsappasit, Dewri & Ray (2012)**. *Dynamic Security Risk Management Using Bayesian Attack Graphs*. IEEE Transactions on Dependable and Secure Computing. Probability-informed risk and defense selection, conditional on sound models. https://ieeexplore.ieee.org/document/5936075/
5. **Konsta, Lluch Lafuente, Spiga & Dragoni (2024)**. *Survey: Automatic Generation of Attack Trees and Attack Graphs*. *Computers & Security*. Survey of automation and open problems. https://www.sciencedirect.com/science/article/pii/S0167404823005126
6. **Kaloroumakis & Smith (2021)**. *Toward a Knowledge Graph of Cybersecurity Countermeasures*. MITRE D3FEND. Structures offensive/defensive technique relationships. https://d3fend.mitre.org/resources/D3FEND.pdf

### Supporting standards and datasets

- **MITRE ATT&CK:** documented adversary tactics and techniques; a mapping is not proof of observed exploitation. https://attack.mitre.org/
- **MITRE CAPEC:** attack-pattern taxonomy. https://capec.mitre.org/
- **MITRE CWE:** weakness taxonomy. https://cwe.mitre.org/
- **NIST NVD:** published vulnerability records. https://nvd.nist.gov/
- **FIRST EPSS:** predictive exploitation-probability signal for published CVEs; do not confuse with uncalibrated proprietary scores. https://www.first.org/epss/

Publication links should be validated against original proceedings before final submission; use correct attribution and license notices for third-party material.

## 5. Evaluation experiments and evidence

| Experiment | Method | Evidence required |
|---|---|---|
| Known attack/weakness fixtures | Labeled positive and negative examples | Detection correctness, false positives and missed cases |
| Multi-step correlation | Construct environment with independently supported weaknesses | Actual edges, prerequisites, retrieved paths |
| False-path rejection | Remove prerequisite such as credential or network access | Invalid route disappears |
| Remediation effectiveness | Apply modeled defensive change | Previously reachable objective no longer reachable, with limitations |
| Graph scalability | Vary nodes and graph density in safe synthetic datasets | Construction time, query time, peak RAM, CPU |
| Scan scalability | 100, 1,000, 5,000, 10,000 file controlled fixtures | Throughput, memory, failure rate |
| Unseen scenario test | Hold out scenarios from rule/design development | Generalization accuracy and documented limits |

Collect multiple runs, state hardware/runtime versions, and distinguish mock from live integrations. Report P50/P95/P99 only with sufficient observations. Never invent numbers or claim 100% coverage.

## 6. Threats to validity and product limitations

- Static source inspection cannot confirm runtime exploitation without additional evidence.
- Missing environmental facts can lead to false graph edges and paths.
- Vulnerability severity alone does not establish exploitability or probability.
- A graph derived from the same detection rules as its evaluation dataset may overstate novelty.
- External CVE/ATT&CK data can be outdated or incomplete.
- AI explanations must cite source findings rather than invent paths, permissions, or security events.
- Scalable operation requires bounded parsing, path enumeration, and concurrency; benchmark results must be measured.

## 7. Recommended judging narrative

**Problem:** Independent findings do not explain whether and how an attacker could combine weaknesses to reach a critical asset.

**Method:** Parse authorized evidence, normalize findings, form prerequisite-aware relationships, analyze possible attack paths, and identify high-leverage mitigations.

**Demonstration:** Show a real input, traceable evidence, a path with documented assumptions, and a remediation whose modeled effect can be re-evaluated.

**Technical proof:** Provide reproducible positive/negative fixtures, path-correctness checks, a measured benchmark, and limitations.

**Novelty framing:** Environment-specific discovery of *previously unenumerated combinations* rather than unverified zero-day discovery.

## 8. Codex implementation audit prompt (research only)

```text
Inspect the current DATUM / Paladin repository, but do not change UI,
core functionality, detection behavior, or architecture.

1. Inventory attack/weakness classes actually supported by code and tests.
2. Identify repository/log/config input types and evidence provenance.
3. Separate observed attacks, potential vulnerabilities, inferred paths,
   and unimplemented capabilities.
4. Inspect graph node/edge semantics, prerequisites, traversal, cut analysis,
   ranking, and remediation impact.
5. Verify path correctness with positive and negative fixtures; flag paths
   that omit necessary conditions.
6. Measure graph building/query latency, memory and scaling under controlled
   local synthetic graph sizes and densities.
7. Compare verified implementation with Sheyner 2002, MulVAL 2005,
   NetSPA 2006, Bayesian Attack Graphs 2012, MITRE D3FEND 2021,
   and attack graph survey 2024.
8. Cite precise repository file locations, test names and legitimate papers.
9. Produce a factual supported-versus-planned capability matrix and an
   evidence-backed research report. Never invent benchmarks or novelty.
10. Respect Manipal Hackathon branch freeze and repository rules.
```

## 9. Immediate next actions

1. Have Codex map source code and tests against the taxonomy.
2. Pick one evidence-supported multi-step scenario and one negative-control scenario.
3. Measure path validation and remediation interruption.
4. Record reproducible performance results.
5. Prepare a concise 3-minute technical demonstration and research bibliography.

---

**Research integrity note:** This document deliberately separates literature-established methods and illustrative architecture from *verified product functionality*. No access to the latest DATUM source tree or live repository was used to substantiate capability claims in this document.
