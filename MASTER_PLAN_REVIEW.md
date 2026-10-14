# Attack Path Compiler: Master Plan Review

Diff and critical evaluation of MASTER_PLAN.md against PROJECT_DOCUMENTATION.md
Prepared: 14 Oct 2026

---

## 1. What Changed

### 1.1 Stack: TypeScript → Python + React

The old doc committed to a single TypeScript/Next.js codebase (frontend and API in one deployable). The new plan uses Python 3.12 + FastAPI + networkx on the backend with React + Vite on the frontend, deployed as two separate services (Render + Vercel). This is the biggest architectural change and has real consequences covered in section 2.

### 1.2 Graph algorithm: custom TS module → networkx

Old: bespoke bounded DFS in `/lib/paths`. New: `nx.shortest_simple_paths` with a super-source/super-sink wrapper. The new approach is more theoretically grounded (Yen-style shortest simple paths) but has different performance failure modes under load.

### 1.3 Min-cut: greedy set cover → node-split min-cut

Old: greedy weighted set cover capped at k=5 picks. New: `nx.minimum_cut` on a node-split graph with edge capacities as remediation costs, with greedy as a secondary single-fix picker. This is strictly better; the old greedy approach can miss the true minimum cut. The new doc also correctly calls out not using `minimum_node_cut` (which counts nodes, ignores cost).

### 1.4 Scoring formula: unchanged and still broken

Both documents use `risk = product(edge_p) * target_criticality`. The path-length collapse bug from the earlier evaluation is not fixed in either document. The MASTER_PLAN makes it slightly worse: it uses `w = -log(p)` as the Dijkstra weight for internal ranking while displaying the raw product as the risk score. Paths are now ranked one way internally and scored another way in the UI.

### 1.5 Data source: synthetic JSON → EvidenceForge

Old: hand-rolled synthetic JSON committed to the repo. New: EvidenceForge generates logs from scenario YAMLs; parsers normalise them into the event schema. More realistic but adds ETL complexity.

### 1.6 Ingest surface: three parser formats specified

The new plan names Linux auth, Suricata EVE JSON, and web access as the first three parsers, each estimated at under 40 lines. Reasonable for auth and web access; Suricata's EVE JSON has many alert subtypes and will likely run longer.

### 1.7 ATT&CK integration: P2 nice-to-have → core deliverable

Old doc listed MITRE tags as a "nice to have." The new plan ships a trimmed `attack_subset.json` from the full 53 MB enterprise-attack dataset and uses technique IDs for mitigation labels on every fix recommendation. The kill-chain bar and ground-truth comparison are now explicit demo steps. This is a genuine and meaningful upgrade.

### 1.8 Auth: optional → required

Old: "optional demo account." New: argon2/bcrypt passwords, httpOnly session cookies, rate-limited login, per-source API keys, seeded demo account in README. Correct decision for Bug Bounty readiness.

### 1.9 GitHub integration: new optional target

Not present in the old doc. The new plan adds SARIF upload, auto-filed issues, and PR check runs as an optional post-JR1 deliverable. It correctly notes the GitHub App requirement (PATs cannot create Check Runs) and lists three specific unknowns to test early. Good scope discipline — but the "test early" scheduling is not in the timeline (see section 2.6).

### 1.10 Team structure: loose roles → five named owners with done-criteria

Old: four generic roles. New: owners A through E, each with explicit module ownership and a measurable done condition. Owner E holds platform and docs, including README, which is a Bug Bounty disqualifier if missing.

### 1.11 Timeline: day-by-day → hour-resolution with hard integration milestones

Significantly more detailed. H0–1 freezes contracts and installs EvidenceForge; H4 requires real parsed logs in the UI; H8 requires end-to-end on a public URL. More realistic for a 48-hour event.

---

## 2. Critical Issues

### 2.1 Two-service deploy doubles the failure surface

Splitting backend (Render) and frontend (Vercel) means: CORS configuration, two deployment pipelines, two sleep/wake cycles to manage, and two URLs to submit. Free Render instances sleep after 15 minutes of inactivity. If the backend sleeps while the Vercel frontend is live, the demo stops working mid-presentation with no warning.

The old single-service Next.js deploy avoided this entirely. The MASTER_PLAN lists Docker Compose as a fallback but not as the primary; it should be the primary.

**Recommended fix:** Serve the React build as static files from FastAPI on a single Render Docker deploy. One URL, one sleep cycle, one deployment to manage. Use Docker Compose as the LAN fallback it already is.

---

### 2.2 Scoring is broken and internally inconsistent

The Dijkstra weight is `w = -log(p)`, which is correct (additive in log space, does not collapse with path length). The displayed risk score is `product(edge_p) * criticality`, which collapses on long paths and gives different ordering than the internal ranking.

A judge who asks "how is this risk score computed" will get two answers depending on which part of the code they look at. This is a demo liability.

**Recommended fix:** Use the log-space score throughout, including display.

```python
import math

def path_risk(edges, target_criticality):
    log_mean = sum(math.log(e.p) for e in edges) / len(edges)
    return math.exp(log_mean) * (target_criticality / 10)
```

This is normalised per hop, consistent between ranking and display, and does not collapse. Replace the product formula in both `analyze.py` and the UI wherever the score is rendered.

---

### 2.3 `nx.shortest_simple_paths` is unbounded by default

`nx.shortest_simple_paths` returns a lazy generator of all simple paths in increasing weight order. It has no built-in count or time limit. With a super-source connected to every external node, one injected event that adds a new external node can make the generator expensive before k results are returned.

The plan says "recompute from scratch on each batch, debounced ~500ms," which is fine at demo scale on the prepared scenarios. It is not fine if a judge uploads their own events at Checkpoint 2.

**Recommended fix:**

```python
import itertools
from concurrent.futures import ThreadPoolExecutor, TimeoutError

def top_k_paths(G, source, sink, k=10, timeout_s=2.0):
    gen = nx.shortest_simple_paths(G, source, sink, weight="w")
    with ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(lambda: list(itertools.islice(gen, k)))
        try:
            return future.result(timeout=timeout_s)
        except TimeoutError:
            return []   # return partial results accumulated so far
```

---

### 2.4 EvidenceForge open item is on the critical path and still open

Section 5 explicitly flags "Generate a sample and confirm the exact line formats before B writes parsers" as Open Item 2. The parsers are B's primary Day 1 deliverable. If B starts writing them against assumed format and EvidenceForge outputs something different, that is a Day 2 rewrite on the most critical path in the build.

**Required action:** Close this in H0–1 (first hour), not later. Owner B runs `eforge generate` on the minimal fixture scenario, inspects `ecar.json` and `security.xml`, and confirms field names match the parser assumptions before writing a single line of parser code. This is not optional.

---

### 2.5 Demo step 5 depends on ground-truth matching that can silently break

Demo script step 5 is "show our path matches `GROUND_TRUTH.json`." EvidenceForge emits `GROUND_TRUTH.md` (not JSON), and matching it requires the recovered path node IDs to correspond to EvidenceForge's internal entity labels from the scenario YAML. If the name list (users, hosts, roles, secrets) agreed between B and D does not exactly match what EvidenceForge uses internally, the comparison will fail or show a false mismatch.

This is a classic rehearsal trap: it works in dev when the scenario was generated locally, and fails during the live demo if the scenario was regenerated with a slightly different name or the deployment loaded a different seed.

**Required actions:**

1. Pin the scenario YAML and the ground truth file together in the repo after the first successful generation. Do not regenerate after Day 1.
2. Write a test that asserts the top recovered path contains the exact node IDs present in `GROUND_TRUTH.md`. Run this test in CI so a regeneration breaks the build before it breaks the demo.
3. If EvidenceForge emits `GROUND_TRUTH.md` and not JSON, write a one-time parser to convert it to JSON and commit the result. Do not parse it live.

---

### 2.6 GitHub integration unknowns are listed but not scheduled

Three unknowns are correctly identified in section 11:

1. Whether secret-scanning alerts work on public repos via the API.
2. Whether `result.graphs` renders in GitHub's Security tab (assume it does not).
3. Whether check runs can be created with `GITHUB_TOKEN` or require a full GitHub App install.

These are flagged but there is no time slot to test them. The plan says "after JR1," which is 11am on Day 2. Checkpoint 2 is 9:30pm the same day. If any of the three fail, the screenshots backup needs to exist before JR1 to be usable as a backup during JR1.

**Recommended fix:** Test all three on Day 1 night during the "minimal UI" window (23:00–01:00). Assign to Owner E. If they work, the GitHub integration goes into the JR2 demo. If they fail, screenshots are ready before JR1 and the demo script does not depend on a live GitHub connection.

---

## 3. What the Master Plan Gets Right

These do not need changing:

- **Node-split min-cut with cost-weighted capacities** — correct algorithm, correctly avoids `minimum_node_cut`.
- **Greedy best-single-fix as a secondary output** — gives a simple actionable answer alongside the full cut.
- **ATT&CK subset trimmed from enterprise-attack.json** — right approach; shipping 53MB in the repo is fine for a hackathon, trimming it keeps the app lean.
- **Per-source API keys separate from user sessions** — correct security model; session cookies for humans, API keys for ingest.
- **Named-owner model with explicit done-criteria** — the clearest accountability structure either document has.
- **H4 and H8 hard integration milestones** — forces real integration before Day 2 rather than discovering integration bugs during the judging rounds.
- **Bug bounty hardening checklist** — covers the standard web attack surface; the addition of `npm audit` / dependency scanning is correct.
- **Docker Compose as a LAN fallback** — right call; having it ready means a sleeping Render instance is not a demo-stopper.
- **GROUND_TRUTH.md comparison as a demo step** — differentiating move that shows the system is not just alarming but actually reasoning about attack sequences.

---

## 4. Priority Summary

| Issue | Severity | Owner | When |
|---|---|---|---|
| Fix scoring formula (log-space, consistent display) | Critical | A | H0–2 |
| Confirm EvidenceForge output format before writing parsers | Critical | B | H0–1 |
| Collapse to single-service deploy (FastAPI serves React build) | High | E | H0–1 |
| Add timeout + islice to `shortest_simple_paths` | High | A | H1–4 |
| Pin scenario YAML + ground truth; add CI assertion | High | B, D | H1–4 |
| Test GitHub integration unknowns; build screenshot backup | Medium | E | Day 1 night |

---

*All data described in this document is synthetic. Scenario and log references are for evaluation only.*
