# User flows

Notation (per Figma's user-flow guidance): one goal per flow, explicit start and end, decisions as diamonds, the
same symbol for the same thing. Rounded = start/end, rectangle = screen or step, diamond = decision, dashed =
recovery. Each flow lists the gaps it exposed in the previous design and what was changed.

## Capability inventory (what actually exists, so only these get a door)

| Capability | Backend | Where it lives now |
|---|---|---|
| Workspaces (create, open, rename, delete, search, sort) | `workspaces.py` | Home, Workspaces, sidebar switcher |
| GitHub link → resolve → clone → scan | `github.py`, `harness.py` | Home launcher |
| Local Git folder → scan (desktop only) | `harness.py` (local clone) | Home launcher, File menu |
| Attack-path analysis, fixes, remediation | `engine.py`, `remediation.py` | Analysis |
| Repository findings, patches, pull request | `harness.py` | Repository |
| Metrics, timeline, benchmarks | `metrics.py` | Insights |
| AI assistant (Claude, OpenAI) | `providers/` | Assistant |
| Scan history and remediation audit trail | `jobs`, `audit` tables | Activity |
| Connected services and log ingestion keys | `keys.py`, `/api/keys` | Integrations |
| Preferences, keys, storage, diagnostics | `prefs.py`, `keys.py` | Settings |

Not built, therefore not shown: a file browser, an integrated terminal, an agent runner.

## A. First launch

```mermaid
flowchart TD
  S([Launch app]) --> H[Home with Get started checklist]
  H --> D1{Connect GitHub?}
  D1 -- yes --> G[Settings: GitHub token] --> V{Token accepted?}
  V -- no --> GE[Show reason, fix token]:::rec --> G
  V -- yes --> H2[Home: checklist step done]
  D1 -- skip --> H2
  H2 --> D2{Choose a start}
  D2 -- Clone from GitHub --> B([Flow B])
  D2 -- Open local folder --> L[Pick folder] --> B
  D2 -- New workspace --> C([Flow C])
  D2 -- dismiss checklist --> R([Home, checklist hidden for good])
  classDef rec stroke-dasharray: 4 3
```

Gaps closed: the old screen never said what the product does or what was optional. Nothing is forced: every
checklist step is skippable, and it disappears once dismissed or complete.

## B. Import a repository

```mermaid
flowchart TD
  S([Type or paste in the launcher]) --> K{What is it?}
  K -- GitHub link or owner/name --> R[Check repository with GitHub]
  K -- absolute path --> P{Desktop and a Git folder?}
  P -- no --> PE[Explain why: web build or not a Git repo]:::rec
  P -- yes --> PV[Preview folder]
  K -- other text --> Q[Search workspaces and GitHub repos]
  R --> RS{Result}
  RS -- not found or private --> E1[Say so, link to GitHub settings]:::rec
  RS -- rate limited --> E2[Explain, offer retry later]:::rec
  RS -- offline --> E3[Offer retry]:::rec
  RS -- ok --> PRE[Preview: name, visibility, branch, description]
  PV --> PRE
  PRE --> X{Already a workspace?}
  X -- yes --> O[Open it, or rescan]
  X -- no --> CL[Clone and scan: real job]
  CL --> J{Job state}
  J -- failed --> JE[Show reason on Repository and Activity, Retry]:::rec
  J -- done --> W([Workspace ready: Repository or Analysis])
  classDef rec stroke-dasharray: 4 3
```

Gaps closed: the old flow created the workspace on Enter with no preview, and a failed clone left no way back.

## C. Create a workspace

```mermaid
flowchart TD
  S([New workspace]) --> N[Dialog: name, optional source]
  N --> V{Valid name?}
  V -- empty or duplicate --> VE[Inline message]:::rec --> N
  V -- ok --> SRC{Source given?}
  SRC -- none --> E[Create empty, open Analysis with import options]
  SRC -- repo --> B([Flow B])
  E --> W([Usable workspace])
  classDef rec stroke-dasharray: 4 3
```

## D. Returning user

```mermaid
flowchart TD
  S([Launch app]) --> P{Start with preference}
  P -- last workspace --> W([Resume where you left off])
  P -- start screen --> H[Home: Resume card and recents]
  H --> D{Know the project?}
  D -- in the list --> W
  D -- no --> F[Search or browse Workspaces: filter, sort]
  F --> W
```

## E. Change a setting

```mermaid
flowchart TD
  S([Open Settings]) --> C[Pick a category]
  C --> M[Change a control]
  M --> V{Valid?}
  V -- no --> VE[Reject, keep old value, say why]:::rec --> M
  V -- yes --> SAVE[Persist on the server or in the keychain]
  SAVE --> OK{Saved?}
  OK -- no --> RB[Roll back the control, show error]:::rec --> M
  OK -- yes --> DONE([Confirmation shown, effect is immediate])
  classDef rec stroke-dasharray: 4 3
```

## F. Recover from a failure

```mermaid
flowchart TD
  S([Operation fails]) --> W{Which one?}
  W -- clone or scan --> A[Repository and Activity show the real reason]
  W -- key rejected --> B[Settings shows provider message and fix]
  W -- app closed mid-scan --> C[On next launch the job is marked interrupted]
  A --> R{Choose}
  B --> R
  C --> R
  R -- Retry --> OK([Scan restarts in the same workspace, earlier results kept])
  R -- Fix configuration --> ST[Open the relevant Settings pane] --> OK
  R -- Choose another path --> H([Home])
```

Existing work is never discarded by a failure: a failed scan keeps its workspace, events and history.
