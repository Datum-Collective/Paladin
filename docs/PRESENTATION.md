# DATUM — How It Works (Presentation Doc)

> *Raw security noise goes in. Ranked attack paths, a plain-English story, and the single cheapest fix come out. A human clicks Approve. Done.*

---

## 1. The Big Picture

Most security tools scream individual alerts at you. You end up drowning in noise with no idea which alerts actually connect into a real attack chain — and no idea what to fix first.

**DATUM solves all three problems at once.**

```mermaid
flowchart TD
    A[Scattered Security Signals] --> B[DATUM]
    B --> C[Live Attack Graph]
    B --> D[Ranked Attack Paths]
    B --> E[Cheapest Fix]
    B --> F[Proof It Worked]
```

---

## 2. What Goes In

DATUM eats logs from anywhere. You don't need to clean them up or reformat them. Drop them in raw.

```mermaid
flowchart LR
    L1[Linux Auth Logs\ne.g. failed SSH logins]
    L2[Web Access Logs\ne.g. Nikto scanner hits]
    L3[IDS Alerts\ne.g. Snort rules firing]
    L4[GitHub Repo URL\ne.g. github.com/org/repo]
    L5[API Key Ingest\ne.g. your own log shipper]

    L1 & L2 & L3 & L5 --> P[Parsers\nTurn raw lines into Events]
    L4 --> H[Repo Harness\nSafe clone + code scan]

    P --> DB[(Event Store\nSupabase Postgres)]
    H --> CF[Code Findings\ne.g. hardcoded secret,\nSQL injection, weak TLS]
```

---

## 3. The Engine — Two Sources of Truth

This is the key idea that makes DATUM different.

| Source | What it says | Example |
|---|---|---|
| `inventory.yaml` | What **could** happen — possible attack steps, pre-set probability | Web server *could* leak Nina's creds, p = 0.35 |
| Logs + Code Scan | What **is** happening right now | A Nikto scan hit the web server at 13:00 |

When a real event matches a possible step → that step gets **confirmed**, its probability **jumps**, and the event is attached as **evidence**.

> If there are no events at all — the system says zero risk. Prior probabilities alone are not evidence. No false alarms.

```mermaid
flowchart LR
    INV[inventory.yaml\nPossible attack steps\nwith probabilities]
    EVT[Ingested events\nReal signals]
    COD[Code findings\nStatic scan results]

    INV --> C[Correlate]
    EVT --> C
    COD --> C

    C --> G[Attack Graph\nNodes = assets\nEdges = confirmed steps\nwith evidence attached]
```

---

## 4. The Attack Graph

The graph models your whole organization as a network of assets and attack steps.

```mermaid
flowchart LR
    INET((Internet))
    WEB([Web Server\ncrit: 5])
    NINA([Nina's Account\ncrit: 7])
    FILE([File Server\ncrit: 9])
    DC([Domain Controller\ncrit: 10])

    INET -->|T1190 Exploit\np=0.675 CONFIRMED| WEB
    WEB -->|T1078 Valid Creds\np=0.35| NINA
    NINA -->|T1021 RDP\np=0.60| FILE
    NINA -->|T1078 Pass-the-hash\np=0.80| DC
```

- **Amber edges** = confirmed by real events
- **Grey edges** = possible only, no evidence yet
- **Criticality** = how bad it is if this asset is compromised (1–10)

---

## 5. Ranking Paths — Risk Score

Every path from the internet to a crown jewel gets a **risk score**.

```
risk = p₁ × p₂ × p₃ × ... × (criticality of target ÷ 10)
```

**Real example from the live demo:**

```
Internet → Web Server → Nina → Domain Controller

0.675 × 0.35 × 0.80 × (10 ÷ 10) = 0.189  →  HIGH
```

```mermaid
flowchart TD
    subgraph How paths are found
        direction LR
        S1[Weight each step\nw = -log-p\nso most likely = shortest] --> S2[Find k shortest\nsimple paths\n2 second time budget]
        S2 --> S3[Re-rank by risk\nnot just likelihood\nbecause critical assets matter more]
    end

    subgraph Severity thresholds
        direction LR
        CR[CRITICAL\n≥ 0.30]
        HI[HIGH\n≥ 0.10]
        ME[MEDIUM\n≥ 0.03]
        LO[LOW\nbelow 0.03]
    end
```

---

## 6. Finding the Cheapest Fix — Minimum Cut

Every attack step has a **remediation cost**. DATUM finds the minimum-cost set of steps to remove so that **no dangerous path survives**.

```mermaid
flowchart LR
    subgraph Option A — Cheapest Cut
        A1[Cut: Web → Nina\nCost: 4\nBreaks ALL downstream paths]
    end
    subgraph Option B — Brute Force
        B1[Cut: Nina → File AND\nNina → DC\nCost: 5 + 8 = 13]
    end

    A1 -->|WIN| WIN[4 < 13\nDATUM picks Option A]
    B1 --> WIN
```

On top of the min-cut, DATUM also shows:
- **Best single fix** — the one step that kills the most risk
- **ATT&CK mitigation** for every fix — e.g. `T1552 → M1027 Password Policies`

---

## 7. Remediation — From Fix to Proof

A recommended fix doesn't just disappear after you click it. It goes through a full lifecycle with an audit trail and verification.

```mermaid
stateDiagram-v2
    [*] --> Proposed : DATUM recommends a fix
    Proposed --> Approved : Human clicks Approve
    Approved --> Executed : Human clicks Execute
    Executed --> Verified : No matching events after execution
    Executed --> Failed : Attacker is still active
    Failed --> RolledBack : Human rolls back
    Verified --> [*]
    RolledBack --> [*]
```

**Verification is real.** The system re-ingests events after execution. If an event matching the same attack step appears — the fix is marked `failed` and shows you the event IDs. You can't fake it.

Before and after risk is recorded automatically. You see the number go down.

---

## 8. Code Scanner + Repo Harness

Paste a GitHub URL. Get a pull request with the fixes.

```mermaid
flowchart TD
    URL[GitHub Repo URL] --> CLN[Safe shallow clone\nNo hooks, no submodules\nCode never executed]
    CLN --> SCAN[Static code scan\nSQL injection, hardcoded secrets,\nweak TLS, debug mode, open redirects]
    SCAN --> TRIAGE[Optional AI triage\nClaude Haiku checks exploitability\nconfidence + reason]
    TRIAGE --> GRAPH[Findings join the attack graph\nas new nodes and edges]
    GRAPH --> FIX[Deterministic fixers\nOR Haiku search-replace patch]
    FIX --> VERIFY[Code verified on disk\nflagged line must actually change]
    VERIFY --> APPROVE{Human approves?}
    APPROVE -->|Yes| PR[GitHub Pull Request\nlists CWE + ATT&CK IDs\nflags AI-drafted patches\nstates tests were not run]
    APPROVE -->|No| WAIT[Diff available for download]
```

**Rules that fire deterministically (always work, no AI needed):**
weak hash · TLS off · `yaml.load` · debug mode · hardcoded secret · plain-HTTP script · `target=_blank` · permissive CORS

---

## 9. The Full System Architecture

```mermaid
flowchart TD
    subgraph Input
        LOGS[Linux auth / Web / IDS logs]
        REPO[GitHub repo URL]
        PLAY[Play scenario button]
    end

    subgraph Backend — FastAPI Python
        PARSE[Parsers]
        STORE[(Supabase Postgres\nper-user Row Level Security)]
        CORR[Correlate\nevents confirm inventory edges]
        INV[inventory.yaml\npossible steps + priors]
        ANALYZE[Analyze\ntop-k paths, risk, min cut]
        HARNESS[Repo harness\nclone → scan → fix → PR]
        REM[Remediation lifecycle\naudit log + verify loop]
        AI[AI providers\nClaude / OpenAI — optional]
    end

    subgraph Frontend — React + Cytoscape
        GRAPH_UI[Live attack graph]
        PATHS_UI[Ranked paths with evidence]
        FIX_UI[Fix recommendations]
        ASSISTANT[AI assistant chat]
        INSIGHTS[Insights — timeline, risk series]
        REPO_UI[Repo scan view + diff]
    end

    subgraph Delivery
        SSE[SSE push — live updates]
        DESKTOP[Electron desktop app\nmacOS and Windows]
        DOCKER[Docker image\nVPS behind Caddy HTTPS]
    end

    LOGS --> PARSE --> STORE
    PLAY --> STORE
    INV --> CORR
    STORE --> CORR --> ANALYZE
    REPO --> HARNESS --> CORR
    ANALYZE --> REM
    ANALYZE --> SSE --> GRAPH_UI & PATHS_UI & FIX_UI
    REM --> HARNESS
    AI -.->|optional| HARNESS
    AI -.->|optional| ASSISTANT
    Backend --> DESKTOP
    Backend --> DOCKER
```

---

## 10. Auth — GitHub Sign-In with Supabase

No passwords. No shared demo account. Every judge signs in with their own GitHub account.

```mermaid
sequenceDiagram
    participant User
    participant DATUM
    participant Supabase
    participant GitHub

    User->>DATUM: Click Sign In with GitHub
    DATUM->>GitHub: PKCE OAuth flow
    GitHub->>User: Which account?
    User->>GitHub: Pick account
    GitHub->>Supabase: Auth callback
    Supabase->>DATUM: Access token (httpOnly cookie)
    DATUM->>User: Signed in — your data, isolated by Row Level Security
```

- **Your data stays yours.** Row Level Security on every table. No user can ever read another user's events.
- **No secrets in the browser.** Tokens live in httpOnly cookies only.
- **Repo access is separate and opt-in.** Sign-in only asks for your public profile. You explicitly install the GitHub App to grant repo access.

---

## 11. Desktop App

Same app, no Docker, no Python install needed.

```mermaid
flowchart LR
    ELECTRON[Electron shell] --> RENDERER[React UI\nsandboxed renderer]
    ELECTRON --> ENGINE[FastAPI backend\nfrozen with PyInstaller\nspawned on a random port]
    ENGINE --> SUPABASE[(Supabase cloud\ndata stays in sync)]
    RENDERER <-->|localhost| ENGINE
```

Sign-in opens in the system browser. Switch between desktop and web — your workspaces and data follow you.

---

## 12. Why DATUM is the GOAT

```mermaid
quadrantChart
    x-axis Low Explainability --> High Explainability
    y-axis Alerts Only --> Full Fix Lifecycle
    DATUM: [0.92, 0.95]
    Typical SIEM: [0.20, 0.10]
    Vulnerability Scanner: [0.40, 0.20]
    Manual Pentest Report: [0.65, 0.30]
    Graph-only Tool: [0.70, 0.45]
```

| What everyone else does | What DATUM does |
|---|---|
| Fires isolated alerts | Chains alerts into full attack paths |
| Shows you what's wrong | Shows you the **cheapest single fix** that breaks the most paths |
| Tells you to fix it | Actually opens the **GitHub PR** with the fix |
| Marks it done when you click | Re-ingests events after execution — **proves** it worked |
| Black-box risk scores | Every score has hop-by-hop evidence, technique IDs, and a plain-English story |
| All-or-nothing AI | AI is **optional and never in the decision path** — full deterministic fallback always |
| Single tenant demo hack | Per-user Row Level Security — judges test independently with their own data |
| Web only | **Desktop app + web app + Docker** — runs anywhere |

### The numbers

| Metric | Value |
|---|---|
| Sources ingested | Linux auth + Web access + IDS/Snort + GitHub repos + API |
| ATT&CK techniques covered | Full MITRE ATT&CK enterprise subset |
| Remediation states | proposed → approved → executed → verified / failed / rolled back |
| API endpoints | 30+ |
| Code scan rules | SQL injection, secrets, weak crypto, TLS, debug, CORS, open redirect |
| Time to first path | Under 1 second on 50k events |
| Verification | Re-checks live events after execution — not just a checkbox |
| AI dependency | Zero — Claude/OpenAI are optional upgrades |

---

## 13. The Demo Flow (3 minutes)

```mermaid
journey
    title DATUM live demo
    section Start
      Show 4 isolated low alerts: 3: Judges
      Click Play — watch graph build live: 5: Judges
    section Insight
      One CRITICAL path lights up: 5: Judges
      Click path — see every hop with evidence and ATT&CK IDs: 5: Judges
      Read plain-English story of the attack: 5: Judges
    section Fix
      See cheapest cut highlighted: 5: Judges
      Click Propose → Approve → Execute: 5: Judges
      Watch risk score drop: 5: Judges
      Verify fires — no matching events: 5: Judges
    section Code
      Paste a GitHub repo URL: 4: Judges
      See code findings join the graph: 5: Judges
      Click Open PR — see the diff on GitHub: 5: Judges
```

---

> **DATUM** — *because seeing every threat at once is the only way to stop the right one first.*
