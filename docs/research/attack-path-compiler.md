# Attack Path Compiler: research notes

_Researched 2026-10-14 for a 24-hour hackathon. Every factual claim links to a primary source. Anything I could not confirm from a primary source is marked **UNVERIFIED**. Code snippets marked "tested" were run locally against networkx 3.6.1._

---

## TL;DR

1. **The problem is about a graph model and its algorithms, not about a scanner.** The judges will look for: heterogeneous events → correlated graph → ranked paths → minimal cut → explanation, all driven by **simulated** events. The current "local CLI + GitHub-style dashboard" idea covers ingestion and display well, but it says nothing about correlation, ranking, or the minimal intervention. Those parts are the product.
2. **Data model:** copy BloodHound's design: typed nodes, typed directed edges where "the direction ... always indicates the direction of attack or privilege" ([BloodHound edges](https://bloodhound.specterops.io/resources/edges/overview)), with an edge JSON of `{start, end, kind, properties}` ([OpenGraph edges](https://bloodhound.specterops.io/opengraph/developer/edges)). Add MulVAL's idea that **facts plus rules derive new edges** ([Ou et al. 2005](https://www.usenix.org/legacy/event/sec05/tech/full_papers/ou/ou_html/)), and label each edge with an ATT&CK technique ID.
3. **Algorithms (all available in networkx):**
   - Set the edge weight to `-log(p)`. The Dijkstra shortest path is then the most-likely path.
   - [`shortest_simple_paths`](https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.simple_paths.shortest_simple_paths.html) (Yen's algorithm) gives the top-k paths.
   - [`minimum_cut`](https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.flow.minimum_cut.html), run with a super-source and a super-sink, with **edge capacity = remediation cost**, gives the cheapest fix set. Edges with no capacity are treated as infinite, so they cannot be cut.
4. **GitHub:** build a **GitHub App** (fine-grained permissions, 1-hour tokens, central webhooks).
   - Use GitHub as an **event source**: secret scanning alerts, Dependabot alerts (which include **EPSS**), collaborators, deploy keys, Actions secrets, OIDC trust.
   - Use GitHub as an **output sink**: SARIF with `codeFlows` into the Security tab (free on **public** repos), Check Runs on PRs, and auto-filed Issues.
   - Only GitHub Apps can create Check Runs.
5. **Ingest format:** use a thin internal schema with OCSF-compatible field names (`class_uid`, `activity_id`, `actor`, `src_endpoint`, `resources`). Emit findings as **OCSF Detection Finding** with `finding_info.attacks` and `finding_info.attack_graph`; OCSF 1.9.0 already has a Graph object for this ([finding_info](https://schema.ocsf.io/1.9.0/objects/finding_info), [graph](https://schema.ocsf.io/1.9.0/objects/graph)).
6. **Visualization:** use **Cytoscape.js**. It has built-in `dijkstra`, `aStar`, `animate`, and `flashClass`, plus dagre/ELK layouts ([docs](https://js.cytoscape.org/)). Pick Sigma.js only if you need more than 5k nodes; React Flow is better suited to editors than to graph analysis.

---

## 1. Prior art to borrow from

### 1.1 BloodHound (SpecterOps)

**What it is:**
- A graph of identities and privileges.
- Nodes are typed (User, Group, Computer, and so on).
- Edges are typed relationships such as `MemberOf`. "The direction of the edge, indicated by the arrow, always indicates the direction of attack or privilege" ([edges overview](https://bloodhound.specterops.io/resources/edges/overview)).
- Azure/Entra edges carry an `AZ` prefix, and each edge doc has an "Edge Schema" section that says "whether the edge is traversable" ([same](https://bloodhound.specterops.io/resources/edges/overview)).

**OpenGraph:** BloodHound's generic ingest format.
- Nodes need an `id`, at least one `kind`, and optional `properties` ([OpenGraph nodes](https://bloodhound.specterops.io/opengraph/developer/nodes)).
- Edges are `{start:{match_by,value}, end:{match_by,value}, kind, properties}`. Property values must be primitives or arrays of primitives ([OpenGraph edges](https://bloodhound.specterops.io/opengraph/developer/edges)).
- BloodHound v9 added extension schemas that declare `node_kinds` and `relationship_kinds` with "traversability behavior" ([OpenGraph schema](https://bloodhound.specterops.io/opengraph/schema)).

**Copy these ideas:**

| BloodHound idea | Use in the Attack Path Compiler |
|---|---|
| Edge direction = direction of attack | Every edge `u → v` means "control of u gives (some) control of v" |
| Typed edges (`MemberOf`, `AdminTo`, …) | Closed enum of edge kinds (see 1.5) |
| Traversable vs non-traversable edges | `traversable: bool`. Context edges (e.g. `OwnedBy`) are shown in the UI but excluded from pathfinding |
| OpenGraph JSON `{start,end,kind,properties}` | Use the same shape. You can then also export to BloodHound CE as a stretch goal |
| Shortest-path-to-high-value queries | Super-source (entry points) → super-sink (crown jewels) |

### 1.2 MulVAL and logical attack graphs

MulVAL ([Ou, Govindavajhala, Appel, USENIX Security 2005](https://www.usenix.org/legacy/event/sec05/tech/full_papers/ou/ou_html/)) encodes configuration as Datalog facts. Examples:
- `vulExists(Host, VulID, Program)`
- `networkService(Host, Program, Protocol, Port, Priv)`
- `hacl(Src, Dst, Proto, Port)`
- `hasAccount(...)`

Interaction rules then derive attacker capabilities. For example:

```prolog
netAccess(P, H2, Protocol, Port) :- execCode(P, H1, Priv), hacl(H1, H2, Protocol, Port).
policyViolation(P, Access, Data) :- access(P, Access, Data), not allow(P, Access, Data).
```

- Tabling computes each fact once, so the paper calls simulation polynomial. It reports 3.85 s for 1,000 hosts ([same](https://www.usenix.org/legacy/event/sec05/tech/full_papers/ou/ou_html/)).
- The follow-up paper, "A Scalable Approach to Attack Graph Generation" ([Ou, Boyer, McQueen, CCS 2006](https://www.cs.ksu.edu/~xou/publications/ccs06.pdf)), introduces **logical attack graphs** whose size is polynomial in network size.
- [Saha, CCS 2008](https://dblp.dagstuhl.de/rec/conf/ccs/Saha08.html) adds **incremental recomputation** when inputs change.

**Copy this idea:** separate **observed facts** (events and inventory) from **derivation rules** that create attack edges. Example: `secret_found(laptop, aws_key)` + `key_belongs_to(aws_key, role:ci)` ⇒ edge `laptop -[UsesCredential]-> role:ci`. This is the "correlation" the problem statement asks for, and it is explainable for free: each edge records the facts and the rule that produced it.

**Minimal intervention in the literature:** Jha, Sheyner and Wing frame "which minimal set of security measures would guarantee the safety of the system" as polynomially equivalent to **minimum hitting set**, and they give a greedy algorithm with bounds. Source: Jha/Sheyner/Wing "Two Formal Analyses of Attack Graphs", referenced via [Sheyner & Wing tools paper](https://www.cs.columbia.edu/~wing/publications/SheynerWing04.pdf) and [Jha-Wing02](https://www.cs.columbia.edu/~wing/publications/Jha-Wing02.pdf). The exact wording is **UNVERIFIED**: I read the search abstract, not the full PDF. Original attack-graph paper: [Sheyner et al., IEEE S&P 2002](https://www.cs.cmu.edu/afs/cs.cmu.edu/project/calder/www/sp02.html).

**Probabilistic metrics:** [Wang et al., "An Attack Graph-Based Probabilistic Security Metric", DBSec 2008](https://dl.ifip.org/index.html/db/conf/dbsec/dbsec2008/WangILSJ08.pdf) defines path-likelihood metrics on attack graphs, including cyclic graphs, and notes that computing them exactly is expensive. The product-of-edge-probabilities simplification below is ours; it ignores AND-nodes and shared sub-paths. Say so to judges.

### 1.3 MITRE ATT&CK (label every edge)

- The current matrix is **ATT&CK v20** ([tactics page footer](https://attack.mitre.org/tactics/enterprise/)).
- **Note:** v20 tactics include **TA0005 Stealth** and **TA0112 Defense Impairment** where older docs say "Defense Evasion". Do not hard-code the old name.
- Enterprise tactics, in order ([source](https://attack.mitre.org/tactics/enterprise/)):
  - TA0043 Reconnaissance
  - TA0042 Resource Development
  - TA0001 Initial Access
  - TA0002 Execution
  - TA0003 Persistence
  - TA0004 Privilege Escalation
  - TA0005 Stealth
  - TA0112 Defense Impairment
  - TA0006 Credential Access
  - TA0007 Discovery
  - TA0008 Lateral Movement
  - TA0009 Collection
  - TA0011 Command and Control
  - TA0010 Exfiltration
  - TA0040 Impact

Techniques verified on the [Enterprise techniques list](https://attack.mitre.org/techniques/enterprise/) that map directly to edge kinds:

| Edge kind (ours) | ATT&CK |
|---|---|
| `PhishedBy` / initial login | T1566 Phishing (**UNVERIFIED**: not in my extract), T1078 Valid Accounts |
| `ExposedService` | T1190 Exploit Public-Facing Application, T1133 External Remote Services |
| `ContainsSecret` (file/repo → secret) | T1552.001 Credentials In Files, T1552.004 Private Keys |
| `UsesToken` (token → identity) | T1550.001 Application Access Token, T1528 Steal Application Access Token |
| `AuthenticatesAs` (cloud key → role) | T1078.004 Cloud Accounts |
| `CanAssume` / `CanGrant` | T1098.003 Additional Cloud Roles, T1098.001 Additional Cloud Credentials |
| `SSHTo` | T1021.004 SSH |
| `PushTo` (repo write → CI/supply chain) | T1195.002 Compromise Software Supply Chain |
| `MFAFatigue` signal | T1621 Multi-Factor Authentication Request Generation |
| `BruteForce` signal | T1110 Brute Force |
| `DockerSocket` / container escape | T1611 Escape to Host, T1609 Container Administration Command |
| `IMDSReachable` | T1552.005 Cloud Instance Metadata API |
| `CanRead` (role → data store) | T1530 Data from Cloud Storage |
| Vulnerable local service → root | T1068 Exploitation for Privilege Escalation |
| Third-party / vendor app access | T1199 Trusted Relationship |

### 1.4 Wiz / Orca "security graph" and "toxic combinations"

- **Wiz** describes attack path analysis as finding "toxic combinations where multiple low-risk issues chain together". The graph connects resources, identities, permissions, vulnerabilities, network exposure, and data sensitivity. Paths that reach crown jewels are prioritized ([Wiz Academy: Attack Path Analysis](https://www.wiz.io/academy/detection-and-response/attack-path-analysis); [Wiz blog: runtime signals in Security Graph](https://www.wiz.io/blog/runtime-signals-in-security-graph)).
  - Wiz's actual product docs (docs.wiz.io) require a customer login, so their exact graph schema is **UNVERIFIED**. The public pages are vendor marketing.
- **Orca** gives each attack path a 0–99 score built from severity, accessibility, lateral movement, access level, and business impact. It calls alerts that sit on many high-scoring paths "choke points" ([Orca blog: cloud attack path analysis](https://orca.security/resources/blog/cloud-attack-path-analysis/); [Orca blog: strategic remediation](https://orca.security/resources/blog/multi-cloud-attack-path-analysis-for-strategic-remediation/); [datasheet](https://orca.security/wp-content/uploads/2025/05/Orca-Attack-Path-Analysis-Digital.pdf)). These are also vendor blogs, since there is no public spec; treat the weights as **UNVERIFIED**.

**Copy these ideas:**
- The phrase "toxic combination", which is exactly the problem statement's "combinations of individually weak events".
- **Crown-jewel tagging** for impact.
- **Choke points**: rank nodes and edges by how many top paths they appear on. That is the greedy hitting-set heuristic from §3.3.

### 1.5 Recommended data model (concrete)

```ts
type NodeKind = "Identity" | "Group" | "Role" | "Secret" | "Endpoint" | "Service"
              | "Repo" | "Pipeline" | "DataStore" | "Internet";
interface Node {
  id: string;                 // stable, e.g. "aws:role/ci", "gh:repo/acme/web"
  kind: NodeKind;
  label: string;
  criticality: number;        // 0..10, crown jewels ≥ 8 (impact)
  entry?: boolean;            // attacker can start here (internet, phished user)
  props: Record<string, string | number | boolean | string[]>; // OpenGraph-style primitives
}
interface Edge {
  id: string; src: string; dst: string;
  kind: string;               // "ContainsSecret" | "AuthenticatesAs" | "CanAssume" | ...
  traversable: boolean;
  p: number;                  // 0<p≤1 likelihood attacker can traverse
  cost?: number;              // remediation cost; undefined = cannot be fixed (∞)
  remediation?: string;       // "Rotate AWS key AKIA… and remove from repo"
  attack: string[];           // ["T1552.001"]
  evidence: string[];         // event ids that created/raised this edge (explainability)
  rule: string;               // derivation rule id (MulVAL-style)
  firstSeen: string; lastSeen: string;
}
```

---

## 2. Normalizing heterogeneous events

### 2.1 OCSF

- **Version:** OCSF 1.9.0 ([class list](https://schema.ocsf.io/classes)).
- **Relevant classes:**

  | Class | class_uid |
  |---|---|
  | Process Activity | 1007 |
  | Vulnerability Finding | 2002 |
  | Detection Finding | 2004 |
  | Account Change | 3001 (deprecated in 1.9.0 in favour of User Management) |
  | Authentication | 3002 |
  | Entity Management | 3004 |
  | User Access Management | 3005 (deprecated) |
  | Group Management | 3006 |
  | User Management | 3007 |
  | Role Management | 3008 |
  | Network Activity | 4001 |
  | API Activity | 6003 |

- **Authentication (3002):**
  - Requires `activity_id`, `category_uid`, `class_uid`, `metadata`, `severity_id`, `time`, `type_uid`, and `user`.
  - Recommends `src_endpoint`, `dst_endpoint`/`service`, `is_mfa`, `status_id` (1 Success, 2 Failure), and `auth_protocol`.
  - `type_uid = class_uid * 100 + activity_id`, so a Logon is `300201` ([Authentication](https://schema.ocsf.io/1.9.0/classes/authentication)).
- **API Activity (6003):** requires `actor`, `api`, and `src_endpoint`. `activity_id` is 1 Create, 2 Read, 3 Update, or 4 Delete ([API Activity](https://schema.ocsf.io/1.9.0/classes/api_activity)).
- **Detection Finding (2004):** requires `finding_info`; `resources` and `evidences` are recommended ([Detection Finding](https://schema.ocsf.io/1.9.0/classes/detection_finding)). `finding_info` has:
  - `attacks[]` for ATT&CK tactic and technique ([finding_info](https://schema.ocsf.io/1.9.0/objects/finding_info))
  - `related_events[]`
  - **`attack_graph`**, a Graph object with `nodes`, `edges`, `is_directed`, and `query_language` ([graph](https://schema.ocsf.io/1.9.0/objects/graph))

**Verdict: use OCSF field names, not full OCSF.**
- Full OCSF is large, and its required fields would slow a 24h team down.
- Borrowing its vocabulary (`class_uid`, `activity_id`, `actor.user`, `src_endpoint.ip`, `resources[]`, `status_id`, `severity_id`) does three things:
  - It makes the "heterogeneous" claim credible.
  - It lets you say "we can ingest AWS Security Lake / any OCSF producer".
  - It lets you **output** each ranked path as an OCSF Detection Finding with `finding_info.attack_graph`, which is a very good talking point.

### 2.2 Sigma (briefly)

- **Sigma rules (spec v2.1.0):** YAML with `title`, `logsource` (`category`/`product`/`service`), `detection` + `condition`, `level` (`informational` … `critical`), and ATT&CK tags written as `attack.t1078` ([Sigma rules spec](https://github.com/SigmaHQ/sigma-specification/blob/main/specification/sigma-rules-specification.md)).
- **Correlation rules:**
  - Types: `event_count`, `value_count`, `temporal`, `temporal_ordered`, `value_sum`, `value_avg`, `value_percentile`.
  - Fields: `rules`, `group-by`, `timespan`, and `condition` ([correlation spec](https://raw.githubusercontent.com/SigmaHQ/sigma-specification/main/specification/sigma-correlation-rules-specification.md)).
- **How to use it:**
  - Sigma is a detection language, not a graph language.
  - Use its **shape** for your derivation rules (match conditions + ATT&CK tags + level).
  - Optionally use `temporal_ordered` as the inspiration for "signal A then signal B on the same identity within 1h raises edge probability".
  - Don't embed a Sigma engine.

### 2.3 Minimal event schema (recommended)

```jsonc
{
  "id": "evt_0042",
  "time": "2026-10-14T09:12:03Z",
  "source": "okta|cloudtrail|github|edr|local-scan|simulator",
  "class": "authentication|account_change|api_activity|detection_finding|inventory",
  "class_uid": 3002,                // optional OCSF mapping
  "activity": "logon|grant|create|read|exposed|secret_found|...",
  "status": "success|failure",
  "severity": 1,                    // 0-6 like OCSF severity_id
  "actor":   { "type": "user|role|service|token", "id": "user:alice@acme" },
  "target":  { "type": "role|repo|host|datastore|secret|service", "id": "aws:role/deploy" },
  "src_endpoint": { "ip": "203.0.113.7", "host": "laptop-alice", "geo": "RO" },
  "attrs":   { "is_mfa": false, "permission": "sts:AssumeRole", "port": 2375 },
  "attack":  ["T1078.004"]          // optional hint
}
```

**Pipeline:**
1. A source-specific adapter turns raw input into this schema.
2. A **rule engine** (about 15 hand-written rules) turns events into node and edge upserts plus probability bumps.
3. The graph is rebuilt and analysed.

There are two classes of input:
- **Inventory/facts:** who can assume what, where secrets live. These create edges.
- **Signals:** a failed MFA burst, impossible travel, a new admin grant. These **raise `p`** on existing edges, or flag nodes as "possibly compromised" (entry points).

This is how "individually weak events combine". No single signal reaches the threshold, but a path is a product of probabilities, so raising three edges from 0.2 to 0.7 multiplies the path likelihood about 40×.

---

## 3. Algorithms

### 3.1 Likelihood ranking

- **Transform:** If edge success probabilities are independent, then P(path) = ∏ pᵢ. Minimising Σ −log pᵢ is the same as maximising ∏ pᵢ, and −log p ≥ 0 for p ∈ (0,1], so Dijkstra applies.
  - The independence assumption is a simplification; see [Wang et al. 2008](https://dl.ifip.org/index.html/db/conf/dbsec/dbsec2008/WangILSJ08.pdf) for the rigorous treatment.
- **Top-k paths:** `nx.shortest_simple_paths(G, s, t, weight=...)` is based on Yen's algorithm.
  - It yields loopless paths lazily in increasing weight.
  - It forbids negative weights and does not support Multi(Di)Graphs.
  - Its complexity is **O(K·N³)** for the first K paths ([networkx docs](https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.simple_paths.shortest_simple_paths.html); [Yen 1971, Mgmt Sci 17(11)](https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.simple_paths.shortest_simple_paths.html)).
  - You need a `DiGraph`, not a `MultiDiGraph`: collapse parallel edges by keeping the max p.
- **Risk score:** `risk(path) = P(path) × criticality(target)`, optionally × (1 + exposure bonus for internet entry). Rank by risk, not by likelihood alone.
  - Orca reports a similar "probability and impact" framing ([datasheet](https://orca.security/wp-content/uploads/2025/05/Orca-Attack-Path-Analysis-Digital.pdf)).
  - Because Yen's algorithm orders by likelihood per target, compute top-k per crown jewel and merge-sort by risk.
- **Where p comes from (hackathon heuristics, our own):**
  - Base p per edge kind: `CanAssume` 0.9, `ContainsSecret` 0.8, `Phished` 0.2.
  - Multiply by signal boosts: verified secret ×1.2, no MFA ×1.3, recent anomalous login ×1.5; cap at 0.99.
  - For CVE edges, use the **EPSS** value that GitHub's Dependabot alerts API already returns (`security_advisory.epss.percentage`) ([Dependabot alerts API](https://docs.github.com/en/rest/dependabot/alerts)). That is a defensible, real-world likelihood.

### 3.2 Smallest defensive intervention = minimum cut

- **Edge cut (recommended):**
  - Add a super-source `SRC` → every entry node, and every crown jewel → a super-sink `SNK`.
  - Give each **fixable** edge `capacity = remediation cost`. Leave structural or unfixable edges **without** a capacity attribute; networkx treats those as **infinite capacity** ([`minimum_cut` docs](https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.flow.minimum_cut.html)).
  - The returned partition `(S, T)` gives the cut edges `{(u,v): u∈S, v∈T}`. That is the cheapest set of fixes that disconnects **all** entry points from **all** crown jewels (max-flow/min-cut).
  - The default `flow_func` is `preflow_push`, and the docs warn this default may change.
- **Node cut:**
  - [`minimum_node_cut`](https://networkx.org/documentation/stable/reference/algorithms/connectivity/generated/networkx.algorithms.connectivity.cuts.minimum_node_cut.html) returns a set of nodes of **minimum cardinality**, not minimum cost. It has no weight parameter.
  - For cost-weighted node cuts (e.g. "disable this identity" costs 8, "rotate this secret" costs 1), use the **node-splitting** trick: `n_in → n_out` with capacity = cost, and original edges `u_out → v_in` with infinite capacity.
- **Wrong target:** Cytoscape's `kargerStein` is a randomized **global** min cut on undirected graphs, not an s–t cut, so it is the wrong tool ([Cytoscape docs](https://js.cytoscape.org/#eles.kargerStein)).

**Tested snippet (edge cut + top-k):**

```python
import math, networkx as nx
from itertools import islice

G = nx.DiGraph()
def edge(u, v, kind, p, cost=None, tech=""):
    attrs = dict(kind=kind, p=p, w=-math.log(p), tech=tech)
    if cost is not None: attrs["capacity"] = cost      # absent => infinite (uncuttable)
    G.add_edge(u, v, **attrs)

edge("internet", "repo:web", "PublicRepo", 0.9)
edge("repo:web", "secret:aws_key", "ContainsSecret", 0.8, cost=1, tech="T1552.001")
edge("secret:aws_key", "role:ci", "AuthenticatesAs", 0.95, cost=1, tech="T1078.004")
edge("role:ci", "role:deploy", "CanAssume", 0.8, cost=2, tech="T1098.003")
edge("role:deploy", "db:customers", "CanRead", 0.95, cost=4, tech="T1530")
# ... more edges ...
entries, crown = ["internet"], {"db:customers": 10}
for s in entries: G.add_edge("SRC", s)
for t in crown:   G.add_edge(t, "SNK")

for path in islice(nx.shortest_simple_paths(G, "SRC", "SNK", weight="w"), 5):
    core = path[1:-1]
    p = math.prod(G[u][v]["p"] for u, v in zip(core, core[1:]))
    print(f"p={p:.3f} risk={p*crown[core[-1]]:.2f}", " -> ".join(core))

cut_value, (S, T) = nx.minimum_cut(G, "SRC", "SNK", capacity="capacity")
cut = [(u, v) for u in S for v in G[u] if v in T]
```

On an 11-edge demo graph (3 paths, 2 entry routes), this printed the three paths ranked by risk. The min cut was `[(secret:aws_key→role:ci), (repo:infra→role:deploy)]` at cost 3, and `has_path` was False afterwards.

**Tested snippet (weighted node cut by splitting):**

```python
def weighted_node_cut(G, s, t, node_cost):   # nodes missing from node_cost are uncuttable
    H = nx.DiGraph()
    for n in G:
        H.add_edge((n, "in"), (n, "out"), **({"capacity": node_cost[n]} if n in node_cost else {}))
    for u, v in G.edges:
        H.add_edge((u, "out"), (v, "in"))     # infinite
    val, (S, T) = nx.minimum_cut(H, (s, "out"), (t, "in"))
    return val, [n for n in G if (n, "in") in S and (n, "out") in T]
```

On a toy graph with costs `{a:1, b:1, c:5}`, this returned `(2, ['a','b'])`. `nx.minimum_node_cut` returned `{a, c}` instead, because it minimises count, not cost. This difference is a good one-liner for judges.

### 3.3 Alternative: greedy hitting set over the top-k paths

Min-cut cuts **all** paths. Sometimes you want "the one fix that removes the most risk among the dangerous paths". Picking a minimal set of measures is a hitting-set problem (§1.2 refs), and greedy is the classic approximation:

```python
def greedy_fix(paths, risk, cost, budget):          # paths: list[list[edge]]
    alive, chosen = set(range(len(paths))), []
    while alive and budget > 0:
        gain = {}
        for i in alive:
            for e in paths[i]:
                if e in cost: gain[e] = gain.get(e, 0) + risk[i]
        if not gain: break
        e = max(gain, key=lambda e: gain[e] / cost[e])   # risk removed per unit cost
        chosen.append(e); budget -= cost[e]
        alive = {i for i in alive if e not in paths[i]}
    return chosen
```

**Recommended UI:**
- Show "**Top fix**": the greedy pick #1, i.e. the choke point.
- Also show "**Complete fix**": the min cut.
- Recompute and animate the paths disappearing.

### 3.4 Feasibility and "continuously updated"

**Graph size:** a demo graph of 100–1,000 nodes and fewer than 5,000 edges is trivially small.
- Dijkstra and a max-flow run in milliseconds at this size. My 11-edge test ran instantly; I did not benchmark 1k nodes, so the exact timing is **UNVERIFIED**, but MulVAL handled thousands of hosts in seconds in 2005 ([Ou 2005](https://www.usenix.org/legacy/event/sec05/tech/full_papers/ou/ou_html/)).
- Yen's O(K·N³) is the only potentially slow step. Keep K ≤ 10 per crown jewel and prune with `maxDepth` ≈ 8.

**Incremental strategy that fits in 24h:**
1. **Event-sourced graph:** the append-only event log is the source of truth, and the graph is a fold over events. Replaying a scenario is then just replaying the log, which is great for demos.
2. **Debounced full recompute:** on each new event, apply the edge upsert in O(1), then recompute paths and the cut at most every 500 ms. At this size, full recompute *is* the incremental strategy. True incremental attack-graph maintenance exists ([Saha CCS 2008](https://dblp.dagstuhl.de/rec/conf/ccs/Saha08.html)), but don't build it.
3. **Dirty-target optimisation (optional):** only recompute top-k for crown jewels that are reachable from the changed edge (`nx.descendants(G, v)` ∩ crown).
4. Push diffs to the UI over **WebSocket/SSE**, e.g. `{newPaths, removedPaths, cut}`, and animate them.
5. **Time decay:** a signal's boost decays, e.g. `p_boost × exp(-Δt/τ)`, so paths cool down. This also makes the "continuously updated" claim visible.

### 3.5 JS / TypeScript-only option

| Need | graphology | Cytoscape.js |
|---|---|---|
| Weighted shortest path | `dijkstra.bidirectional`, `dijkstra.singleSource`, `astar.bidirectional`, with `getEdgeWeight` as an attribute or getter ([shortest-path](https://graphology.github.io/standard-library/shortest-path.html)) | `eles.dijkstra`, `eles.aStar`, `eles.bellmanFord`, `eles.floydWarshall` ([docs](https://js.cytoscape.org/)) |
| k-shortest / Yen | **Not provided** (no mention in [shortest-path](https://graphology.github.io/standard-library/shortest-path.html)) | **Not provided** |
| All simple paths | `allSimplePaths(graph, s, t, {maxDepth})` ([simple-path](https://graphology.github.io/standard-library/simple-path.html)) | via `dfs` (manual) |
| s–t max-flow / min-cut | **Not in the std-lib list** ([standard library](https://graphology.github.io/standard-library/)) | Only `kargerStein` (global, randomized) |
| Centrality | metrics package | `betweennessCentrality`, `pageRank`, `closeness` |

**Implications for a TypeScript-only build:**
- Implement **Yen** yourself, which is about 60 lines on top of Dijkstra.
- Implement **Edmonds–Karp** max-flow yourself, which is about 50 lines of BFS augmenting paths. That is fine at this graph size.
- Or use `allSimplePaths` with `maxDepth` and sort by product-p. This is exponential in the worst case, but OK for a curated demo graph.
- **Recommendation:** a Python (FastAPI + networkx) engine with a TS frontend is lower risk. The algorithms are already correct and documented.

---

## 4. GitHub integration

### 4.1 GitHub App vs OAuth App vs fine-grained PAT

| | GitHub App | OAuth App | Fine-grained PAT |
|---|---|---|---|
| Permissions | Fine-grained ([docs](https://docs.github.com/en/apps/creating-github-apps/about-creating-github-apps/deciding-when-to-build-a-github-app)) | Broad scopes | Fine-grained, per-repo |
| Token life | Installation token **expires after 1 hour** ([docs](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app)) | Doesn't expire until revoked | User-chosen expiry; default 30 days via URL template ([docs](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)) |
| Webhooks | Built-in, centralized across all installed repos | Per repo/org, manual | None |
| Act without a user | Yes | No | No (tied to a user) |
| **Create Check Runs** | **Yes (only Apps can)** ([Checks API](https://docs.github.com/en/rest/checks/runs)) | No | **No**: fine-grained PATs can't call the Checks API ([PAT limitations](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)) |

**Recommendation:** register a **GitHub App** (about 15 minutes in the UI).
- Use a webhook URL from smee.io or ngrok for local dev.
- Use a fine-grained PAT only for a quick first spike that reads alerts.
- Inside Actions, `GITHUB_TOKEN` "is a GitHub App installation access token" scoped to the workflow's repo ([GITHUB_TOKEN](https://docs.github.com/en/actions/concepts/security/github_token)). A workflow with `permissions: checks: write` can therefore create check runs without your own App.
  - Workflow permission keys include `checks`, `issues`, `security-events`, `id-token`, `pull-requests`, and `vulnerability-alerts` ([workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)).
  - The inference that a check run can be created with `GITHUB_TOKEN` follows from the two docs but is **not tested**.

**App permissions you need** ([permissions-required-for-github-apps](https://docs.github.com/en/rest/authentication/permissions-required-for-github-apps)):

| Purpose | Endpoint | App permission |
|---|---|---|
| Push SARIF to Security tab | `POST /repos/{o}/{r}/code-scanning/sarifs` | Code scanning alerts: **write** |
| PR gating | `POST /repos/{o}/{r}/check-runs` | Checks: **write** |
| Read leaked secrets | `GET /repos/{o}/{r}/secret-scanning/alerts` | Secret scanning alerts: read |
| Read vulnerable deps | `GET /repos/{o}/{r}/dependabot/alerts` | Dependabot alerts: read |
| Who has access | `GET /repos/{o}/{r}/collaborators` | Metadata: read |
| Deploy keys | `GET /repos/{o}/{r}/keys` | Administration: read |
| Actions secret names | `GET /repos/{o}/{r}/actions/secrets` | Secrets: read |
| Rulesets | `GET /repos/{o}/{r}/rulesets` | Metadata: read |
| File remediation issues | `POST /repos/{o}/{r}/issues` | Issues: **write** |

**Webhook events to subscribe** (all confirmed in [webhook events](https://docs.github.com/en/webhooks/webhook-events-and-payloads)):
- `secret_scanning_alert`
- `dependabot_alert`
- `code_scanning_alert`
- `member`
- `deploy_key`
- `repository_ruleset`
- `branch_protection_rule`
- `push`
- `pull_request`
- `check_suite`
- `check_run`
- `workflow_run`
- `organization`
- `team`
- `security_and_analysis`

These events are your real-time "continuously updated" feed.

### 4.2 Code scanning SARIF upload: attack paths in the Security tab

- **Endpoint:** `POST /repos/{owner}/{repo}/code-scanning/sarifs`. The body has `commit_sha`, `ref` (full ref; `refs/pull/N/head` shows results in the PR check, a branch ref shows them in the Security tab), and `sarif` (**gzip then base64**), plus optional `tool_name`, `checkout_uri`, and `validate`.
  - It returns 202 with an id that you poll at `GET .../sarifs/{id}`.
  - It returns **403 if GitHub Advanced Security is not enabled** or the repo is archived, and 413 if the payload is too large.
  - The rate limit is **1,000 requests/hour** per user or installation ([REST docs](https://docs.github.com/en/rest/code-scanning/code-scanning#upload-an-analysis-as-sarif-data)).
- **Availability:**
  - On **public repos**, code scanning and secret scanning are enabled/free ([About GHAS](https://docs.github.com/en/get-started/learning-about-github/about-github-advanced-security)).
  - **Private repos need a GitHub Code Security licence** ([About code scanning](https://docs.github.com/en/code-security/code-scanning/introduction-to-code-scanning/about-code-scanning)), which in turn requires a Team or Enterprise plan.
  - **For the demo, use a public repo.**
- **SARIF constraints** ([SARIF support](https://docs.github.com/en/code-security/code-scanning/integrating-with-code-scanning/sarif-support-for-code-scanning)):
  - SARIF **2.1.0** only.
  - At most 10 MB gzipped.
  - At most 20 runs per file and 25,000 results per run (only the top 5,000 are kept).
  - At most 10,000 thread-flow locations per result (top 1,000 kept).
  - At most 1,000 locations per result (100 kept).
  - At most 20 tags per rule (10 shown).
  - A result needs **at least one location** to display.
  - Include `partialFingerprints`; if you upload via the API without it, you may get duplicate alerts.
  - `properties.security-severity` ranges over 0.1–10. A score above 9.0 is **critical**, 7.0–8.9 is high, 4.0–6.9 is medium, and 0.1–3.9 is low.
  - "If code flows are provided, code scanning will expand code flows on GitHub for the relevant result."
- **SARIF `codeFlows` fit:**
  - A `codeFlow` "describes the progress of one or more programs through one or more thread flows". A threadFlow is "a temporally ordered sequence of code locations".
  - `threadFlowLocation.importance` ∈ {`essential`, `important`, `unimportant`}, and each location has a `message` and `kinds` ([SARIF 2.1.0 §3.36–3.38](https://docs.oasis-open.org/sarif/sarif/v2.1.0/os/sarif-v2.1.0-os.html)).
  - SARIF also has `result.graphs` (§3.27.19) for arbitrary directed graphs. GitHub does not document rendering it, so it is **UNVERIFIED** that it is displayed.

**Design trick:** GitHub needs **physical file locations**, but attack path hops are cloud/identity objects, so anchor each hop to the **file in the repo that creates the edge**. Examples:
- `.env:3` (the leaked key)
- `.github/workflows/deploy.yml:12` (`id-token: write` / role ARN)
- `infra/iam.tf:40` (`sts:AssumeRole` trust)
- `k8s/deploy.yaml:22` (privileged pod)

One attack path is one SARIF `result`:
- `ruleId` = the path pattern, e.g. `APC001-secret-to-prod-data`
- `security-severity` = risk scaled to 10
- `codeFlows[0].threadFlows[0].locations` = one hop each, with `message.text` = "Step 2 (T1078.004): AWS key authenticates as role/ci"
- the primary `location` = the **cut edge's** file, i.e. where to fix

```jsonc
{ "ruleId": "APC001", "level": "error",
  "message": { "text": "Internet → leaked AWS key → role/ci → role/deploy → customers DB (p=0.52). Fix: rotate key in .env." },
  "locations": [{ "physicalLocation": { "artifactLocation": { "uri": ".env" }, "region": { "startLine": 3 } } }],
  "partialFingerprints": { "primaryLocationLineHash": "apc001:secret:aws_key:db:customers" },
  "codeFlows": [{ "threadFlows": [{ "locations": [
    { "location": { "physicalLocation": { "artifactLocation": { "uri": ".env" }, "region": { "startLine": 3 } },
                    "message": { "text": "1. T1552.001 AWS key committed in .env" } }, "importance": "essential" },
    { "location": { "physicalLocation": { "artifactLocation": { "uri": "infra/iam.tf" }, "region": { "startLine": 40 } },
                    "message": { "text": "2. T1098.003 role/ci can assume role/deploy" } } }
  ]}]}]
}
```

The rule object gets `properties: { "security-severity": "9.4", "tags": ["security","attack-path","T1552.001"] }`.

### 4.3 Checks API: PR gating

- Only GitHub Apps can create check runs ([Checks API](https://docs.github.com/en/rest/checks/runs)).
- **Annotations:**
  - At most **50 per request**; append more with later updates.
  - Required fields: `path`, `start_line`, `end_line`, `annotation_level` (`notice` | `warning` | `failure`), and `message` (64 KB max).
  - `title` is optional (255 chars max).
- **Output:** `title`, `summary` (Markdown), `text`, and `images`.
- **Conclusion:** one of `success`, `failure`, `neutral`, `cancelled`, `skipped`, `timed_out`, `action_required`.

**Flow:**
1. A `pull_request` webhook arrives.
2. Build the graph at base and at head (parse IaC/workflow/env changes in the diff).
3. Compute `newCriticalPaths = paths(head) − paths(base)`.
4. Post a check run with `conclusion: failure`, a Markdown summary ("This PR adds edge `repo:infra → role:prod-admin` (OIDC trust on `pull_request`), creating 2 new critical paths"), and a `failure` annotation on the line that adds the edge.

**OIDC-specific gem:**
- A trust policy that matches `repo:ORG/REPO:pull_request` lets **any PR's workflow** assume the cloud role.
- The `sub` formats are documented: `repo:ORG/REPO:environment:NAME`, `…:pull_request`, `…:ref:refs/heads/BRANCH`.
- Repos created after **July 15, 2026** use an immutable format that includes owner and repo IDs ([OIDC reference](https://docs.github.com/en/actions/reference/security/oidc)).
- This is a perfect "toxic edge" that a PR can introduce.

### 4.4 Running in GitHub Actions

```yaml
name: attack-path-compiler
on: [push, pull_request]
jobs:
  apc:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      security-events: write   # required for SARIF upload
      actions: read            # only needed on private repos
      checks: write
      issues: write
    steps:
      - uses: actions/checkout@v6
      - run: pipx run apc scan --repo . --sarif apc.sarif
      - uses: github/codeql-action/upload-sarif@v4
        with:
          sarif_file: apc.sarif
          category: attack-path-compiler
```

- The `upload-sarif@v4`, `security-events: write`, `actions: read` (private repos only), and `category` details come from [Uploading a SARIF file](https://docs.github.com/en/code-security/code-scanning/integrating-with-code-scanning/uploading-a-sarif-file-to-github).
- `id-token: write` is only needed if your CLI itself must fetch a cloud token. "Without `id-token: write`, the OIDC JWT ID token cannot be requested" ([OIDC reference](https://docs.github.com/en/actions/reference/security/oidc)).
- `GITHUB_TOKEN` expires when the job finishes, or after 6 hours at most on hosted runners ([GITHUB_TOKEN](https://docs.github.com/en/actions/concepts/security/github_token)).

### 4.5 GitHub as an event SOURCE (graph mapping)

| API | Node/edge it produces | Availability notes |
|---|---|---|
| Secret scanning alerts `GET /repos/{o}/{r}/secret-scanning/alerts`, org variant `/orgs/{org}/...` ([docs](https://docs.github.com/en/rest/secret-scanning/secret-scanning)) | `Secret` node; `Repo -ContainsSecret-> Secret`; `Secret -AuthenticatesAs-> Identity` (by secret type) | **Free on public repos**; private repos need Secret Protection on Team/Enterprise Cloud ([about secret scanning](https://docs.github.com/en/code-security/secret-scanning/introduction/about-secret-scanning)). Needs repo admin; org endpoint needs org admin or security manager. The docs also say the repo endpoint 404s when "Repository is public or secret scanning is disabled". That contradicts the free-for-public claim, so the behaviour on public repos is **UNVERIFIED**; test it early. |
| Dependabot alerts ([docs](https://docs.github.com/en/rest/dependabot/alerts)) | `Service -HasVuln-> CVE` with `p` = **EPSS**, impact from CVSS | Returns `severity`, `cvss_v3/v4`, and `epss.percentage/percentile`. Docs say "public preview". |
| Collaborators ([docs](https://docs.github.com/en/rest/collaborators/collaborators)) | `Identity -CanPush/CanAdmin-> Repo` from `permissions{pull,triage,push,maintain,admin}` and `role_name`; `affiliation=outside` flags outside collaborators | Free |
| Deploy keys ([docs](https://docs.github.com/en/rest/deploy-keys/deploy-keys)) | `Secret(SSH key) -CanPush-> Repo` when `read_only: false`; uses `last_used` and `added_by` | Free |
| Actions secrets ([docs](https://docs.github.com/en/rest/actions/secrets)) | **Names only, never values.** `Repo -HasSecret-> Secret`. Org secrets have `visibility` all/private/selected, and `selected` lists repos. | Free |
| Rulesets / branch rules ([docs](https://docs.github.com/en/rest/repos/rules)) | Edge **modifier**: an unprotected default branch raises `p(PushTo → Pipeline)` | Free-plan availability for private repos is **UNVERIFIED** |
| Actions OIDC trust ([concepts](https://docs.github.com/en/actions/security-for-github-actions/security-hardening-your-deployments/about-security-hardening-with-openid-connect), [reference](https://docs.github.com/en/actions/reference/security/oidc)) | `Pipeline(workflow) -AssumesRole(OIDC)-> CloudRole`. Parse `aws-actions/configure-aws-credentials` `role-to-assume` from workflow YAML, plus the cloud trust policy `sub` condition. | Free. The trust itself lives in the cloud, so in the demo it comes from simulated IAM data. |
| Org audit log | `Authentication`/`AccountChange` signals | REST/GraphQL audit log API is for **GitHub Enterprise Cloud** orgs ([reviewing the audit log](https://docs.github.com/en/organizations/keeping-your-organization-secure/managing-security-settings-for-your-organization/reviewing-the-audit-log-for-your-organization)). Streaming details are **UNVERIFIED**. **Simulate it.** |
| Webhooks (§4.1 list) | Live updates | Free |

### 4.6 Issues API: auto-file remediation

- **Endpoint:** `POST /repos/{o}/{r}/issues` with `title` (required), `body`, `labels`, and `assignees`. Labels and assignees need push access, otherwise they are silently ignored ([Issues API](https://docs.github.com/en/rest/issues/issues#create-an-issue)).
- **Rate limit:** "Creating content too quickly ... may result in secondary rate limiting".
- **Use it for:** one issue per **cut edge**, not per path. The body should include the paths it breaks, the ATT&CK chain, and a fix checklist.
- **Deduplicate** by storing the issue number keyed on edge id.

---

## 5. Local scanning sources (if the CLI stays)

| Artifact | Edge(s) it reveals | Primary doc |
|---|---|---|
| `~/.aws/config` `[profile X] role_arn=… source_profile=Y` | `Identity(Y) -CanAssume-> Role(X)`. Chains are visible as source_profile → role. `mfa_serial` lowers p; `credential_source=Ec2InstanceMetadata` links to IMDS (T1552.005); `web_identity_token_file` links to OIDC. | [AWS CLI: using an IAM role](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-role.html) |
| `~/.aws/credentials`, `~/.aws/cli/cache` | `Endpoint -HasCredential-> Identity`. Cached temp creds live in `~/.aws/cli/cache`. | same |
| `~/.kube/config` (or `$KUBECONFIG`) | `Endpoint -HasCredential-> K8sUser -CanAccess-> Cluster`. Contexts = (cluster, namespace, user). | [kubeconfig docs](https://kubernetes.io/docs/concepts/configuration/organize-cluster-access-kubeconfig/) |
| gh CLI token | Token is in the **system credential store** by default and in plain text only as a fallback or with `--insecure-storage`. Use `gh auth status` to see where. The file path `~/.config/gh/hosts.yml` is **UNVERIFIED** from the manual page. | [gh auth login](https://cli.github.com/manual/gh_auth_login) |
| `~/.ssh/*` keys + `known_hosts` + `config` | `Endpoint -HasKey-> SSHKey -SSHTo-> Host` (T1021.004, T1552.004). Note `known_hosts` is often hashed. | ssh_config(5); I did not fetch it in this session, so **UNVERIFIED** |
| `.env` files, repo history | `ContainsSecret` | gitleaks / trufflehog (below) |
| Docker socket / listening ports | `Endpoint -ExposedService-> Service`; a writable docker socket is effectively root (T1611) | **UNVERIFIED** (no doc fetched) |

**Secret scanners:**
- **gitleaks (MIT):**
  - Commands: `git`, `dir`, `stdin`.
  - `--report-format json|csv|junit|sarif|template`.
  - Findings include `RuleID`, `File`, `StartLine`, `Secret`, `Match`, `Fingerprint`, `Entropy`.
  - `--redact` masks secrets.
  - The README says it is now feature-complete, with focus moving to "Betterleaks" ([repo](https://github.com/gitleaks/gitleaks)).
- **trufflehog (AGPL-3.0 since v3):**
  - `--json`, `--sarif`, `--github-actions`.
  - Results are `verified` / `unverified` / `unknown`. Verification **calls the provider's API with the found credential**, and `--no-verification` disables it.
  - JSON includes `DetectorName`, `Verified`, `SourceMetadata` ([repo](https://github.com/trufflesecurity/trufflehog)).
  - **AGPL note:** shelling out to the binary is fine for a hackathon; vendoring or linking it into a hosted service has licence implications.

**Ethics and privacy (important for judging):**
- **Never upload secret values.** Upload only `{type, location, fingerprint, verified?}`; gitleaks `--redact` helps.
- **Don't run trufflehog verification** on credentials you don't own. Use `--no-verification` by default.
- **Consent prompt** before scanning `~`, and an explicit allow-list of paths.
- **Dashboard access by "access keys":**
  - Treat these as bearer secrets: hashed at rest, scoped per project, revocable.
  - A shared-key dashboard that aggregates every developer's laptop secrets map is *itself* a crown jewel and an attack path. Expect judges to point this out.
- **The problem statement says "using simulated security events".** The demo must run on a **simulator**. Real ingestion is a bonus.

**Supporting both (same pipeline):**

```
[simulator scenario.yaml] ─┐
[apc scan (local)]         ├─► normalized events (§2.3) ─► rule engine ─► graph ─► paths/cut ─► UI / SARIF / Checks / Issues
[GitHub App webhooks/API] ─┘
```

The simulator is a scenario file: a timeline of events with delays, plus a `--speed` flag. This makes the demo deterministic and replayable.

---

## 6. Visualization

| | Cytoscape.js | React Flow | Sigma.js |
|---|---|---|---|
| Rendering | Canvas | DOM/SVG (React components) | **WebGL**, "Render large graphs in the browser. Fast." ([sigmajs.org](https://www.sigmajs.org/)) |
| Built-in algorithms | **Yes**: `dijkstra`, `aStar`, `bellmanFord`, `floydWarshall`, `pageRank`, `betweennessCentrality`, `kargerStein`, `tarjanStronglyConnected`… ([docs](https://js.cytoscape.org/)) | No | Via graphology std-lib |
| Animation / highlight | `eles.animate`, `cy.animate`, `eles.flashClass`, class-based styles ([docs](https://js.cytoscape.org/)) | `animated: boolean` on edges ([Edge type](https://reactflow.dev/api-reference/types/edge)); docs warn that CSS animations hurt perf ([performance](https://reactflow.dev/learn/advanced-use/performance)) | Node/edge reducers and v4 styles + `setNodeState` ([hover how-to](https://www.sigmajs.org/how-to/interactivity/hover-search/), [v3→v4](https://www.sigmajs.org/how-to/technical/migration-v3-v4/)) |
| Layout | Built-in: circle, concentric, grid, CoSE, breadthfirst. Extensions: fCoSE, Cola, **dagre**, **ELK**, Klay ([docs](https://js.cytoscape.org/)) | **None built in**; recommends dagre, d3-hierarchy, d3-force, elkjs ([layouting](https://reactflow.dev/learn/layouting/layouting)) | ForceAtlas2 via graphology |
| Best for | **Analysis graphs, 100–1000 nodes, path highlighting** | Node editors / flowcharts with rich custom node UI | 10k+ node exploration |

**Pick Cytoscape.js:**
- Use `dagre` or `elk` with a left-to-right `rankDir` so paths read Entry → Crown jewel. This mirrors the ATT&CK tactic order.
- Path highlighting is `path.addClass('hot')` plus `flashClass`.
- The cut can be shown by turning edges red-dashed, then animating them away.
- Exact node-count limits are not published; the docs only discuss degradation "on graphs with large numbers of elements" ([performance section](https://js.cytoscape.org/#performance)). Treat 1k nodes as comfortable but **UNVERIFIED** without a benchmark.

---

## 7. Explainability

1. **Every edge carries `evidence[]` (event ids) and `rule`.** The explanation is generated from data, not invented. Clicking an edge shows the raw events that created it.
2. **Template narrative (deterministic, always on).** One sentence per hop, keyed by edge kind:
   - `ContainsSecret`: "{src} contains a {secret.type} ({evidence: gitleaks rule X, line N}) — ATT&CK T1552.001 Credentials In Files."
   - `AuthenticatesAs`: "That key authenticates as {dst} — T1078.004 Cloud Accounts."

   Then add a summary line: "Likelihood {p:.0%} (weakest link: {min edge}), impact {criticality}/10 ({dst} holds customer PII). Breaking edge {cut} (cost {c}) removes {n} of {m} critical paths."
3. **LLM polish (optional).**
   - Send the **structured path JSON only**: hops, techniques, evidence summaries.
   - Ask for a 3-sentence incident-propagation story and a fix rationale.
   - Constrain it: "do not introduce entities not in the JSON". Validate that every entity id in the output exists in the graph, and fall back to the template if it doesn't.
   - Cache per path hash.
   - Never send secret values.
4. **Tactic swim-lanes:** order hops by ATT&CK tactic (Initial Access → Credential Access → Privilege Escalation → Lateral Movement → Collection/Exfiltration; [tactics](https://attack.mitre.org/tactics/enterprise/)). Render a little kill-chain bar above each path.
5. **Machine-readable output:** an OCSF Detection Finding (`finding_info.attacks`, `finding_info.related_events` = the evidence events, and `finding_info.attack_graph` = the path) ([finding_info](https://schema.ocsf.io/1.9.0/objects/finding_info)), plus SARIF `codeFlows` for GitHub.

---

## 8. Verdict

### 8.1 The idea against the problem statement

| Requirement | CLI + GitHub-style dashboard as pitched | Gap |
|---|---|---|
| Heterogeneous events | Only local machine/build artifacts | **Weak.** There are no auth logs, API activity, or privilege changes. Needs IdP/cloud/GitHub events, simulated. |
| Correlate identities, permissions, apps, endpoints, secrets, services | Not addressed. Issues are listed as separate items. | **Missing.** This is the core ask. A list of issues is exactly the "individual alerts" the brief criticises. |
| Construct attack paths | Not addressed | **Missing** |
| Rank by likelihood × impact | Not addressed | **Missing** |
| Smallest defensive intervention | Not addressed | **Missing.** This is the most differentiating requirement. |
| Continuously updated | A one-shot scan then upload | **Weak.** Needs an event stream and re-ranking. |
| Simulated events | Real local scanning | **Conflicts** with "using simulated security events", and raises privacy concerns |
| Explainable propagation model | GitHub-style issue list | **Weak.** Needs a path narrative and graph view. |
| GitHub integration | Planned | **Good**, if GitHub acts as both an event source and a sink (§4) |

**Risks:**
- **Judging:** the dashboard looks like "yet another secret scanner". Scanning is a solved problem: gitleaks and trufflehog already exist, and GitHub secret scanning is free on public repos.
- **Security:** a shared-access-key dashboard that collects many laptops' credential locations is a honeypot.
- **Time:** building a GitHub-clone UI eats the hours that should go into graph and algorithm work.

**Keep:** the CLI as *one adapter*, and GitHub integration as a strong differentiator. Reframe the product as **"attack-path engine + simulator; CLI and GitHub App are just event sources and output sinks"**.

### 8.2 Recommended architecture

```
 sources                         engine (Python, FastAPI)                     sinks
 ─────────                       ────────────────────────                    ──────
 scenario simulator (YAML) ─┐    adapters → normalized events (§2.3)        Web UI (React + Cytoscape.js)
 apc CLI (local scan)       ├──► append-only event log (SQLite)        ──►  live via SSE/WebSocket
 GitHub App (webhooks+REST) ┘    rule engine (~15 rules) → graph (networkx) GitHub: SARIF codeFlows, Check Run,
                                 analyzer: top-k Yen per crown jewel,        remediation Issues
                                 risk = p × impact, min-cut, greedy top fix  OCSF Detection Finding JSON export
                                 narrator: templates (+LLM optional)
```

### 8.3 24-hour build plan (ordered; the cut line is marked)

| # | Hours | Deliverable |
|---|---|---|
| 1 | 0–2 | Agree the schemas (§1.5 node/edge, §2.3 event). Write the **demo scenario YAML** first (about 25 events, 3 entry points, 2 crown jewels, 4 weak signals). |
| 2 | 2–5 | Rule engine: events → nodes/edges with `p`, `cost`, `attack[]`, `evidence[]`. Unit-test it on the scenario. |
| 3 | 5–8 | Analyzer: super-source/sink, `-log p`, Yen top-k, risk, `minimum_cut`, greedy top fix. JSON API at `/graph`, `/paths`, `/fix`. |
| 4 | 8–12 | UI: Cytoscape (dagre LR), path list ranked by risk, click a path to highlight it, and a narrative panel from templates. |
| 5 | 12–14 | **Live mode:** the simulator replays events over SSE; the graph and rankings update. A "Apply fix" button removes the cut edges, re-ranks, and animates. |
| — | — | **MVP CUT LINE: steps 1–5 alone satisfy every clause of the brief.** |
| 6 | 14–17 | GitHub sink: SARIF with `codeFlows` uploaded to a **public** demo repo, plus Issues for cut edges. |
| 7 | 17–19 | GitHub source: GitHub App reads collaborators, deploy keys, Actions secret names, Dependabot (EPSS), and secret-scanning alerts into events. |
| 8 | 19–20 | PR Check Run: "this PR adds edge X → new critical path" (OIDC `pull_request` trust example). |
| 9 | 20–21 | `apc scan` CLI adapter: aws config role chains, kubeconfig contexts, and gitleaks `--redact` JSON, with consent prompt. |
| 10 | 21–22 | LLM narrative polish + OCSF Detection Finding export. |
| 11 | 22–24 | Rehearse the demo, record a backup video, freeze. |

### 8.4 Three-minute demo script

**0:00–0:30, the problem.** The UI shows four alert cards, each "low/medium", that no SOC would escalate:
1. "Okta: 6 MFA push denials for alice, then 1 approval (T1621)"
2. "gitleaks: AWS key in `acme/web/.env` (T1552.001)"
3. "IAM: `role/ci` was granted `sts:AssumeRole` on `role/deploy` yesterday (T1098.003)"
4. "CloudTrail: `role/deploy` has read on `s3://customers-pii`"

**0:30–1:15, compile.** Press **Play** on the simulator. Events stream in, and nodes and edges appear live. The four cards snap together into one red path:

`Internet → alice (MFA fatigue) → alice's laptop → .env AWS key → role/ci → role/deploy → customers-pii`

The path is scored **p = 0.52 × impact 10 = CRITICAL #1**. Click it to show the kill-chain bar (Initial Access → Credential Access → Privilege Escalation → Collection) and the template narrative, with each hop linked to its evidence event.

**1:15–2:00, smallest fix.** The panel says: "Min-cut over all 7 dangerous paths: **revoke `role/ci → role/deploy` trust (cost 2)** + **rotate key (cost 1)**. Top single fix: the trust edge removes 81% of total risk." Point out that node-count min-cut would have picked "disable alice", which is expensive, so a cost-weighted cut is better. Click **Apply fix**: the edges fade, paths re-rank live, and the top risk drops from CRITICAL to LOW.

**2:00–2:40, GitHub.**
1. Open the demo repo's **Security tab**: the attack path appears as a code scanning alert with a step-by-step code flow (`.env:3` → `infra/iam.tf:40`).
2. Open the auto-filed remediation Issue.
3. Open a PR that adds `sub: repo:acme/infra:pull_request` to the deploy role trust. The **Check Run fails** with "This PR creates 2 new critical paths", annotated on the exact line.

**2:40–3:00, close.** "Heterogeneous events go in, an explainable attack graph comes out, ranked by likelihood × impact, and you get the cheapest cut that breaks it, continuously. It runs on simulated data today; the same pipeline takes OCSF, GitHub, and local scans."

---

## Appendix: UNVERIFIED items to check early

1. Whether `GET /repos/{o}/{r}/secret-scanning/alerts` works on **public** repos. Its doc lists a 404 for "Repository is public …", which conflicts with "free on public repos". Test it in hour 6.
2. Whether `result.graphs` in SARIF renders on GitHub. Assume it does not; use `codeFlows`.
3. Creating check runs with `GITHUB_TOKEN` + `checks: write` (inferred, not tested).
4. Free-plan availability of rulesets on private repos.
5. Cytoscape.js and Sigma.js node-count limits (no official numbers).
6. Wiz's internal graph schema (gated docs). The Orca score weights come only from blogs.
7. The exact location of the gh CLI's plain-text token file.
8. The exact wording of the Jha/Sheyner/Wing hitting-set result (taken from a search abstract, not the full paper).
