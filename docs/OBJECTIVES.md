# Objectives (Round 2): Attack Path Compiler

All data is synthetic. Each objective lists where it can be seen. Numbers in the UI are computed from ingested
events; nothing is hardcoded.

## 1. Multi-Source Security Event Correlation
Ingest and correlate security events from multiple sources, including authentication logs, web access logs, and
IDS alerts. Transform isolated events into a unified view of related activities to identify potential attack
paths. The current implementation supports Snort-format IDS alerts, with additional formats supported only where
the corresponding parsers are implemented.
**Where:** Analysis (Import tab and Events tab), Integrations, `POST /api/ingest`, `backend/app/parsers/`,
`backend/app/correlate.py`.

## 2. Risk Analysis and Optimal Remediation
Construct an attack graph to identify and rank potential attack paths using path probability and target asset
criticality. Apply minimum-cut analysis to identify cost-effective remediation strategies that disrupt dangerous
paths. Compare risk levels and attack paths before and after remediation to demonstrate measurable risk
reduction.
**Where:** Analysis (Paths tab and path detail), Insights (Before and after), `backend/app/analyze.py`,
`GET /api/fixes`.

## 3. Interactive Threat Intelligence Dashboard
An interactive dashboard that visualises attack graphs, ranked attack paths, security events and remediation
recommendations, with a chronological attack timeline, risk-over-time charts and before-and-after remediation
comparisons.
**Where:** Home (recent and resumable work), Workspaces (project selection), Analysis (graph, Paths tab and Events
tab), and Insights (timeline, risk over time and before/after comparisons).

## 4. Explainable Cyber Threat Analysis and Remediation Lifecycle
Evidence-backed explanations for each path: contributing security events, affected assets, attack progression and
MITRE ATT&CK techniques. The workflow extends from detection to remediation approval and, through the repository
integration harness, delivery of the approved fix as a verified pull request. Risk calculations and path analysis
stay deterministic and explainable; AI is optional.
**Where:** Analysis (path detail and evidence), Repository (scan findings and proposed changes), Assistant
(optional provider-backed explanations), Activity (scan and remediation history), Integrations (GitHub and model
provider setup), `backend/app/remediation.py`, `backend/app/harness.py`.

## Honest scope notes
- Play sample scenario appears only when an EvidenceForge sample manifest is installed; otherwise a new workspace
  opens empty.
- Local-folder workspaces are available only in the desktop application. Browser deployments can open GitHub
  repositories instead.
- Assistant answers and AI-assisted repository review require a configured OpenAI or Anthropic API key. Core
  parsing, correlation, path ranking and remediation analysis remain deterministic and work without a provider.
- "Verified" for a pull request means the matched issue pattern is gone and the file still parses; tests are not
  run and a human reviews every PR.
