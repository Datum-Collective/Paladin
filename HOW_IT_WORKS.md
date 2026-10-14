# How the Attack Path Compiler works

One idea: **small alerts in, one attack path out, and the cheapest fix that stops it.**
All data is synthetic.

## 1. The big picture

```mermaid
flowchart LR
    L1[Linux auth logs] --> P
    L2[Web access logs] --> P
    L3[IDS alerts] --> P
    P[Parsers<br/>text line to Event] --> S[(SQLite<br/>append-only events)]
    INV[inventory.yaml<br/>possible attack steps] --> C
    S --> C[Correlate<br/>events confirm steps]
    C --> G[Graph<br/>nodes + weighted edges]
    G --> A[Analyze<br/>top paths, risk, min cut]
    A --> API[FastAPI]
    API -- SSE live updates --> UI[React + Cytoscape UI]
```

## 2. Two sources of truth

| Source | Says | Example |
|---|---|---|
| `inventory.yaml` | what **could** happen (possible steps, prior probability, fix cost) | WEB-BO-01 could leak nina.kapoor's credentials, p = 0.35 |
| Logs | what **is** happening | Nikto scan against WEB-BO-01 at 13:00 |

When a log event matches a possible step, that step becomes **observed**,
its probability goes up, and the event id is attached as evidence.

```mermaid
flowchart TD
    E["Event: Nikto scan on WEB-BO-01"] --> M{"matches an edge's<br/>match rule?"}
    M -- no --> X[stored, no effect]
    M -- yes --> U["edge observed = true<br/>p = p + (1 - p) x 0.5<br/>evidence += event id"]
```

## 3. The graph it builds

Circles are things (internet, hosts, identities, data). Arrows are attack steps.
Amber = confirmed by events. Grey = prior only.

```mermaid
flowchart LR
    internet((Internet)):::ext -- "T1190 scan, p 0.35 ✔" --> WEB[WEB-BO-01]
    internet -- "T1078 ssh login, p 0.2 ✔" --> WWW[www-data]
    WWW -- "T1059, p 0.8" --> WEB
    WEB -- "T1552 creds, p 0.35" --> NINA[nina.kapoor<br/>domain admin]
    MAIL((Phishing)):::ext -- "T1566, p 0.3" --> MWS[WS-MPATEL-01]
    MWS -- "T1558, p 0.15" --> NINA
    NINA -- "T1021.001 RDP, p 0.6" --> FILE[FILE-BO-01]
    NINA -- "T1021.001 RDP, p 0.4" --> DC[DC-BO-01]
    FILE -- "T1005, p 0.8" --> CLAIMS[(claims-data<br/>crit 9)]:::crown
    DC -- "T1003, p 0.5" --> SECRETS[(domain-secrets<br/>crit 10)]:::crown
    classDef ext fill:#8b5cf6,color:#fff
    classDef crown fill:#dc2626,color:#fff
```

## 4. Ranking paths: likelihood x impact

A **path** runs from an external entry point to a crown-jewel data node.

```
risk = (p1 x p2 x ... x pn) x criticality of the target / 10
```

Example top path from the demo:

```mermaid
flowchart LR
    a[internet] -- 0.5 --> b[WEB-BO-01] -- 0.35 --> c[nina.kapoor] -- 0.6 --> d[FILE-BO-01] -- 0.8 --> e[claims-data]
```

`0.5 x 0.35 x 0.6 x 0.8 x 9/10 = 0.076` (the first hop is raised from 0.35 because an event confirmed it).

Search uses `w = -log(p)` so the **most likely** path is the **shortest** path
(k shortest simple paths in networkx). Severity bands: CRITICAL >= 0.30, HIGH >= 0.10, MEDIUM >= 0.03, else LOW.

## 5. Finding the cheapest fix

Every arrow has a **remediation cost** (for example "enforce MFA" = 5).
We want the cheapest set of arrows to remove so **no dangerous path survives**. That is a minimum cut.

```mermaid
flowchart LR
    S([source]) --> internet --> WEB
    WEB -- "cost 4" --> NINA
    NINA -- "cost 5" --> FILE --> CLAIMS --> T([sink])
    NINA -- "cost 8" --> DC --> SECRETS --> T
```

- Cutting `WEB -> NINA` (cost 4) breaks everything downstream.
- Cheaper than cutting `NINA -> FILE` and `NINA -> DC` (5 + 8 = 13).
- A cut that only minimises the **number** of edges can pick a costlier fix. We use cost, not count.
- Edges with no cost (for example "this host is this identity") can never be cut.

Two answers are shown:

| Fix | Meaning |
|---|---|
| Cheapest cut | min total cost that breaks all dangerous paths (min cut) |
| Best single fix | the one edge that removes the most risk |

Each fix is labelled with its ATT&CK mitigation, for example `T1552 -> M1027 Password Policies`.

## 6. What happens when you press Play / Apply fix

```mermaid
sequenceDiagram
    participant U as You (UI)
    participant API as FastAPI
    participant DB as SQLite
    participant E as Engine
    U->>API: Play (simulate/step)
    API->>DB: ingest events (same path as upload)
    DB-->>API: stored
    API-->>U: SSE "events changed"
    U->>API: GET graph / paths / fixes
    API->>E: correlate + build graph + rank + cut
    E-->>API: paths, risk, fixes
    API-->>U: JSON
    U->>API: Apply fix (edge ids)
    API->>DB: remember removed edges
    API->>E: recompute without those edges
    E-->>U: risk drops, paths re-rank
```

Nothing is hardcoded: the UI shows whatever the engine computes from the events you ingested.

## 7. Where things live

| Piece | File |
|---|---|
| Event / Node / Edge shapes | `backend/app/models.py`, `docs/contracts.md` |
| Log parsers | `backend/app/parsers/` |
| Event confirms edge | `backend/app/correlate.py` |
| Paths, risk, min cut | `backend/app/analyze.py` |
| Story per path | `backend/app/narrate.py` |
| Possible attack steps | `data/inventory.yaml` |
| ATT&CK names + mitigations | `data/attack_subset.json` |
| API | `backend/app/main.py` |
| UI | `frontend/src/` |
