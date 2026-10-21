# Paladin: pitch deck and winning plan

Slide-by-slide script, demo, prep plan and Q&A. Plain-language explanations live in `docs/PITCH.md`; this file is
the stage version. Facts come from the repo (`HOW_IT_WORKS.md`, `docs/BENCHMARKS.md`,
`docs/research/ATTACK_INTELLIGENCE_VALIDATION.md`). If a number here and the app disagree, the app wins: fix this file.

## What we follow from the Anthropic deck

Source: [Upmetrics breakdown](https://upmetrics.co/pitch-deck-examples/anthropic) of a real Anthropic overview deck
(about February 2023). Its arc is **who they are → why they're credible → momentum → a specific ask**, in a minimal
style that reads without narration. It has 10 slides; we compress the same arc into **4**, because the live demo
carries the rest. We add what that deck skips and judges need: a problem and honest limits.

| Anthropic's arc | Our slide |
|---|---|
| Cover + introduction + mission (who we are, one repeatable line) | 1. Paladin |
| (missing in theirs) the problem | 2. The problem |
| Cutting edge: show the real work, not claims | 3. How it works, with evidence |
| Outside validation + momentum with concrete numbers | 4. Proof and the ask |
| Specific ask at the end | 4. Proof and the ask |

Not copied: their papers and press coverage. We have neither, so no invented press, users or partners.

## The winning story in one line

> Everyone shows you what's wrong. Paladin shows you the one cheap thing to fix, fixes it, and proves it worked.

Repeat it at the start, after the demo, and at the close. Four beats: **find the path → cheapest fix → fix it →
prove it.**

## Win conditions

The four Round 2 objectives (`docs/OBJECTIVES.md`) are the likely scoring rubric. Each gets one clear on-stage moment:

| Objective | On-stage proof | Slide / demo step |
|---|---|---|
| 1. Multi-source correlation | Linux auth + web + Snort events become one chain | Slide 3, demo step 2 |
| 2. Risk analysis and optimal remediation | Ranked paths, minimum cut, before/after risk | Slide 3, demo steps 4-5 |
| 3. Interactive dashboard | Live graph, timeline, risk-over-time | Demo (whole), slide 4 |
| 4. Explainable analysis + remediation lifecycle | Evidence per hop, ATT&CK ids, PR delivery | Slide 3, demo step 6 |

If the real rubric differs, re-order the slides to match it, but keep the story.

## The deck (4 slides + live demo)

Design rules: minimal, readable without narration, one idea per slide, clean dark background so numbers stand out,
red for "dangerous", green for "safe". Use screenshots from the real app. Total slide time about 2 minutes; the demo
is the rest.

### 1. Paladin (who we are)
**On slide:** Paladin, tagline "Find the route. Cut it cheaply. Prove it's closed.", team name and photo, presenter.
Below it the mission in three words: **explainable, minimal, provable.**
**Say:** Your name, the one-liner, then the three words. Explainable: every score shows its evidence. Minimal: the
cheapest fix, not a list. Provable: we check the fix worked.

### 2. The problem
**On slide:** A wall of identical alerts with four circled. Headline: "Four 'low' alerts. One open road to your data."
**Say:** The house story: unlocked gate, key under the mat, back door, safe. Each is minor; together they are a
route. Tools list the four; nobody says which one to fix first.

### 3. How Paladin works (show the real work)
**On slide:** One flow: logs + code → map → ranked paths → cheapest fix → verified. Under it, three small panels:
(a) risk: `0.675 × 0.35 × 0.6 × 0.8 × 9/10 = 0.102 → HIGH`; (b) cheapest fix: cut one step for **4**, not two for
**13**; (c) the three checks behind "verified": re-scan clean, tests pass, MITRE ids real.
**Say:** A step turns *confirmed* only when a real log line matches it, and that line is kept as evidence. Rank is
likelihood times value of the target. Then the trust line: the AI never sets your risk and never decides "verified";
Paladin's own checks do. A human approves every fix.

### 4. Proof and the ask
**On slide:** Benchmarks from `docs/BENCHMARKS.md` (1k events ≈ 0.2 s, 10k ≈ 1.7 s, 50k ≈ 9 s end to end), 12 scan
rules, 3 log formats, Mac + Windows + web. Built on MITRE ATT&CK / CWE / CAPEC and EvidenceForge (Cisco Talos). Then
the ask: QR code to install, "give us your hardest question".
**Say:** Measured, reproducible with `python scripts/benchmark.py`; our data is synthetic and we say so. Then go
straight into the demo.

## Demo script (3 minutes, rehearse to the second)

| Time | Action | Say |
|---|---|---|
| 0:00 | Open Paladin with an empty workspace | "Nothing here. No data, so zero risk." |
| 0:15 | Press **Play** | "Logs stream in. Watch the map build." |
| 0:45 | One path turns red | "Four separate low alerts just became one critical route." |
| 1:00 | Open the path | Walk each hop: evidence, ATT&CK name, plain-English story |
| 1:40 | Show the highlighted cheapest cut | "Block this one step and every route to the data breaks." |
| 2:00 | Propose → Approve → Execute | "A human approves." Risk number drops on screen |
| 2:20 | Verify | "It now watches for the attacker. Nothing matching, so verified." |
| 2:30 | Repository: paste a repo, run the fixing agent | Show the verdict and the pull request |
| 2:55 | Back to slide 4 | The one-liner |

**Demo rules**
- Record a backup video of the full run. If the live app stalls, play the video without apologising.
- Run the demo once on stage Wi-Fi equivalent (phone hotspot) before the day.
- Sign in before going on stage. Pre-load the workspace and the repo to scan.
- The fixing-agent step needs an Anthropic key and (for `verified`) Docker. If Docker is off, the verdict stops at
  `fixed_untested`; either have Docker running or narrate that honestly.

## Prep plan

| When | Task | Owner |
|---|---|---|
| T-5 days | Freeze features. Only bug fixes from here. | Everyone |
| T-5 | Fix the claims in `docs/PRESENTATION.md` ("under 1 second on 50k events" → measured ~9 s end to end; "full ATT&CK enterprise" → the subset we ship) | Docs |
| T-4 | Build the 4 slides from this file; screenshots from the real app | Design |
| T-3 | Record the backup demo video; test the Mac and Windows installers on clean machines | Eng |
| T-3 | Fill in the README's `Reviewed by: <team members>` placeholder | Docs |
| T-2 | Full dry run with a timer, two people play judges and ask the Q&A below | Everyone |
| T-1 | Second dry run; fix only what broke. Charge laptops, bring adapters, USB copy of the deck and video | Everyone |
| Day | Sign in, warm the workspace, open the backup video in another tab | Presenter |

**Roles:** one presenter, one person on the keyboard if the demo needs a second pair of hands, one person dedicated to
Q&A, one owner of the backup video and the files.

## Question bank (every question a judge can ask)

Answers are from the code and docs at the time of writing; file paths are given so anyone can check. Two rules for
the whole section: (1) answer in one or two sentences, then stop; (2) when the honest answer is "not yet", say
"not yet" and what we would do. Items marked **DECIDE** are not in the repo: agree the answer as a team before the
day and write it here.

### A. The basics

**What is Paladin?** A tool that reads security logs and source code, draws the routes an attacker could take to
valuable data, ranks them, finds the cheapest set of fixes that blocks all of them, helps fix them, and checks the fix
worked.

**What problem does it solve?** Security tools produce many small alerts that look harmless alone. Teams can't see
that several of them chain into one route to critical data, and don't know what to fix first.

**Who is it for?** Small security and dev teams with no dedicated analyst, developers who want findings in their own
code fixed as a pull request, and security leads who must show risk went down.

**What does it take in?** Three log formats (Linux auth, web access, Snort/Suricata alerts), a generic JSON event
format, and source code from a GitHub repository or (desktop only) a local folder. Parsers are in
`backend/app/parsers/`.

**What does it produce?** A live graph, ranked attack paths with evidence per hop and ATT&CK ids, a plain-English
story, the cheapest fix, a remediation record with before/after risk, and (for code) a verified patch or pull request.

**Is it a SIEM / scanner / pentest tool?** None of them. A SIEM collects and alerts; a scanner lists weaknesses; a
pentest report is a one-off. Paladin joins signals from both into paths, picks the cheapest fix and tracks it to
proof. It is not a replacement for log collection.

**What platforms does it run on?** macOS (Apple Silicon only), Windows, and a web app (Docker, behind Caddy). See
`INSTALLATION.md`.

### B. How it finds things

**How does it find vulnerabilities?** Twelve built-in rules scan source files (`backend/app/codescan.py`): hard-coded
secrets, dynamic code execution, shell execution, SQL built from strings, unsafe deserialization, TLS verification
off, weak hashes, XSS sinks, permissive CORS, missing `noopener`, HTTP script sources, debug mode. It also checks
dependencies against osv.dev (the fixing agent handles `vulnerable-dependency`). Each match gets a file, line, CWE and
an ATT&CK technique.

**Which languages does it scan?** Common source extensions (`CODE_EXT` in `codescan.py`: Python, JavaScript/TypeScript,
Java, Go, Ruby, PHP, C#, shell and more). Rules are text patterns, so quality varies by language; Python and
JavaScript are the best covered. Files over 200 KB and a 3 MB total are skipped, secrets files (`.env`, keys) and
lockfiles are excluded.

**Is a rule match proof it's exploitable?** No. It is a *possible* weakness. There is no data-flow analysis, so a
match can be a false positive. An optional AI triage step reads the code around each match and says whether it looks
exploitable; the rule match exists either way.

**How do logs become attack steps?** Each log line becomes an `Event`. `data/inventory.yaml` lists the steps an
attacker *could* take (12 edges in the bundled synthetic company), each with a prior probability, a cost to fix and a
match rule. When an event matches a rule, that edge is **confirmed**, its probability rises
(`p + (1 - p) × 0.5`) and the event id is attached as evidence (`backend/app/correlate.py`).

**What if there are no events?** Zero paths, zero risk. Starting probabilities alone are not evidence.

**What attacks does it detect from logs?** Web reconnaissance (scanner user agents and probes for `/.env`, `/.git`,
`../`), successful SSH logins by an account the inventory flags, and Snort/Suricata scan or exploit alerts. Failed
logins are parsed but no rule uses them yet. Details and limits: `docs/research/ATTACK_INTELLIGENCE_VALIDATION.md`.

**Does it detect zero-days or new attack techniques?** No. It finds known weaknesses and shows how they combine into a
route you hadn't listed. A new exploit technique would need independent reproduction; the graph can't prove one.

**Can it handle an attack that isn't in the inventory?** The inventory is the model of what is possible. An event
that matches no edge is stored but has no effect. Building the inventory automatically from a real environment is
future work; today it is hand-written for the synthetic company and derived from code for repository scans.

**How are code findings and logs combined?** Both become nodes and edges on the same graph, so a hard-coded secret in
code and a scan against the web server rank together (`HOW_IT_WORKS.md` section 3). Code findings are marked as
assumed or reference, not observed.

### C. How the maths works

**How is risk computed?** `risk = product of each step's probability × target criticality / 10`. Severity: CRITICAL
≥ 0.30, HIGH ≥ 0.10, MEDIUM ≥ 0.03, else LOW (`backend/app/analyze.py`).

**How are paths found?** Each step gets weight `-log(p)`, so the most likely route is the shortest. It takes the top
candidates by k-shortest simple paths (2 s time budget), then re-ranks by risk, because a slightly less likely route
to a more valuable target can matter more.

**What is a minimum cut, simply?** The cheapest set of steps to block so that no route from the internet to a valuable
target survives. Example: cutting one step costing 4 beats cutting two costing 5 + 8.

**Why cost and not the number of steps?** Fewest steps can be the more expensive fix, so Paladin minimises total
cost and shows the count-based result as a baseline.

**What is the "best single fix"?** The one step whose removal takes away the most risk, for when only one action is
possible today.

**Where do the probabilities and costs come from?** Hand-set priors in `data/inventory.yaml`; real evidence raises
the probabilities. They are for ranking routes against each other, not a calibrated forecast of attack likelihood.
Calibration (for example Bayesian attack graphs with sourced data) is future work.

**What about steps that need two things at once (a credential AND network access)?** The graph uses independent
edges, so it can't express AND/OR prerequisites yet. That is a known limit and a planned improvement.

**Is the result the same every run?** Yes. Scoring, paths and the cut are deterministic and need no AI.

**What are the research foundations?** Attack graphs (Sheyner et al. 2002), MulVAL (2005), Bayesian attack graphs
(Poolsappasit 2012), MITRE ATT&CK/CWE/CAPEC, NVD, EPSS. These are inspiration and vocabulary; Paladin does not claim
to implement them in full (`docs/research/DATUM_Paladin_Attack_Intelligence_Research.md`).

### D. Fixing and verification

**How does it fix code?** Two ways. Deterministic rewrites for simple rules (weak hash, TLS off, `yaml.load`, debug
mode, hard-coded secret, plain-HTTP script, `target=_blank`, permissive CORS; `backend/app/fixers.py`), and the fixing
agent for harder ones.

**What is the fixing agent?** A Claude tool-use loop (`backend/app/fixagent.py`, default `claude-opus-5-5`, up to 40
turns and 16 edits, 8 findings at a time). Its tools: list, read and search files, exact-match edit, MITRE lookup,
re-scan a file, run tests, finish. It works in a scan's working copy.

**What is the agent not allowed to do?** Edit tests, CI files or `.git`; leave the working copy; follow symlinks. The
system prompt treats everything in the repo as untrusted data.

**How is "verified" decided, and by whom?** By Paladin, in `judge()` (`fixagent.py:488`), never by the model. All of:
the changed files re-scan clean with nothing new; the repository's tests pass; every MITRE id the agent cited exists.
Otherwise it names the gap: `no_changes`, `regressed`, `failed_tests`, `not_fixed`, `ungrounded`, `fixed_untested`,
`partial`.

**How is Claude grounded?** MITRE's own entry for each finding's CWE, its linked CAPEC patterns and their ATT&CK
techniques go into the prompt (`data/mitre.json`, built offline by `scripts/build_mitre_pack.py` from MITRE's
downloads). The `mitre_lookup` tool only answers from that pack and says "do not cite it" otherwise. The agent must
list the ids it relied on; invented ids give `ungrounded`.

**Can it cite a real but irrelevant MITRE id and still pass?** Today yes: unrelated citations are recorded in the
result but don't change the verdict. Real ids are enforced, relevance is not. Tightening it is a small change in
`judge()`.

**Does it run the repo's tests? Safely?** Yes, in a Docker sandbox (`backend/app/services/sandbox/`): ephemeral
non-root container, read-only root, no added capabilities, `no-new-privileges`, CPU/memory/PID limits, bounded
`/tmp`, removed afterwards. It detects `npm test` or pytest only. Without Docker, the verdict stops at
`fixed_untested`; on your own machine tests run only with `APC_ALLOW_LOCAL_TESTS=1`. (`docs/SANDBOX.md` still says no
workflow calls the sandbox; the fixing agent does, so that sentence is stale.)

**What if the repo has no tests?** The result is `fixed_untested` with the reason. Paladin never rounds up.

**How does the log-side fix get verified?** After execution, Paladin watches new events. If any event ingested after
the fix still matches a closed step, the state becomes `failed` and lists the event ids; otherwise `verified`
(`backend/app/remediation.py:189`).

**Does "executed" change my real systems?** No. For log-side fixes it closes the step in the model and records risk
before and after. The real delivery path is the pull request for code; infrastructure changes are for a human to
make.

**What goes into the pull request?** The fixes with their CWE and ATT&CK ids, a flag on AI-drafted patches, and a
statement of what was and wasn't tested. Nothing is pushed until a human clicks.

**Is there a human in the loop?** Always: a person approves each fix and opens each pull request.

**What if the AI fix is wrong?** The re-scan, the tests and the citation check are the gates; a human reviews the
pull request; and results that fail a gate are labelled, not hidden. We don't claim AI patches are always correct.

### E. Trust, privacy and security

**Does the AI see my code?** Only if you add a key. When the fixing agent, assistant or triage runs, the relevant file
contents go to Anthropic or OpenAI. Credentials found in prompts are masked first (`REDACT` in `codescan.py`). With no
key, nothing leaves the machine except GitHub and Supabase traffic.

**Where is my data stored?** Supabase Postgres (events, findings, remediations), per user, enforced by row-level
security. Scan clones live under the app data directory and are deleted after 24 hours on the server.

**How do you stop one user reading another's data?** The backend calls Supabase *as the signed-in user*, so row-level
security is the main access control. Caps and size checks are enforced in the database too. Tests:
`backend/tests/test_isolation.py`.

**How does sign-in work?** GitHub only, through Supabase Auth with PKCE. Tokens are httpOnly cookies, so page
scripts never see them. Sign-in asks GitHub for identity only; repo access is a separate opt-in GitHub App install.
There are no passwords.

**Where are API keys kept?** Never returned by any endpoint. On desktop they are encrypted with the OS keychain
(`safeStorage`, `desktop/src/settings.js`) and sent to the local backend over loopback with a per-launch token.

**Can a malicious repo attack Paladin?** Cloning uses hooks off, symlinks off and a strict `github.com` URL check;
the repo's code is never executed outside the sandbox; scanner patterns avoid catastrophic backtracking on hostile
text; file size and time are capped; the agent treats repo text as untrusted. This is defence in depth, not a
guarantee.

**What about prompt injection in the repo?** The system prompts tell the model repo content is data, the agent has
no network or shell tools, it can only edit non-test files inside the working copy, and the verdict never reads its
text. Injection could still make it write a bad edit; the gates and the human review are the backstop.

**Is the desktop app signed?** Not yet. macOS shows a first-launch warning and unsigned builds can't auto-update.
`INSTALLATION.md` has the Open Anyway steps.

**Is there rate limiting?** Yes, an in-memory sliding-window limiter (`backend/app/ratelimit.py`), which assumes one
backend instance.

### F. Product and scale

**How fast is it?** Measured on a laptop with synthetic data (`docs/BENCHMARKS.md`): 1k events ≈ 0.2 s end to end,
10k ≈ 1.7 s, 50k ≈ 9 s (about 2.5 s of that is analysis). A graph of ~2,000 nodes and ~6,000 edges: top-10 paths
≈ 2 s, minimum cut ≈ 0.01 s. Excludes network and database latency.

**Is the graph live?** Yes in the sense of updating without reload: the browser holds a server-sent-events stream; the
backend checks every 0.5 s and the page refetches when the event count, fixes or scan state change
(`backend/app/main.py:346`, `frontend/src/useWorkspace.js`). It is not tapping a real network on its own: events
arrive by upload, API key or the Play scenario.

**How do I get my own logs in?** Integrations → create a named ingest key (shown once, revocable), then
`POST /api/ingest` with `X-API-Key` in one of the supported formats.

**Does it scale to production volumes?** Not yet. Analysis recomputes from scratch per request and events are cached
in memory per user, which assumes one process. Fine for a team; a streaming design would be needed for large SOC
volumes.

**What happens when there are thousands of findings?** The scanner caps at 60 findings per scan and the agent takes
8 targets at a time. Bounded on purpose.

**Why Supabase / Electron / FastAPI / React?** Supabase gives auth plus row-level security; FastAPI and Python suit the
graph maths (networkx); Electron lets the same UI run offline as a Mac and Windows app; React with Cytoscape.js draws
the graph. All boring, well-understood choices.

**Why a desktop app?** Local folders, the OS keychain for keys, and a workflow that doesn't need a hosted service.

**What AI models does it use?** Anthropic (default `claude-opus-5-5` for the agent; Haiku for optional triage and
patch drafting) or OpenAI for the assistant. Providers sit behind one interface in `backend/app/providers/`. Core
analysis runs without any.

**What does it cost to run?** **DECIDE.** No pricing in the repo. Costs are AI tokens (optional, user-supplied key),
Supabase, and hosting.

### G. Honesty, limits and "gotcha" questions

**Is the demo data real?** No. Synthetic logs generated with EvidenceForge (MIT, Cisco Talos) from
`scenarios/stalk-branch.yaml`. The engine parses real log formats; it has not been run on a live company network.
Provenance: `data/samples/README.md`.

**What are the known limitations?** Hand-set priors; code reachability is a heuristic; text-pattern scanning with no
data flow; independent edges only; recompute per request; unsigned installers; provider wire formats exercised against
mocked transports, never a live key; cancelling a running clone isn't supported; "verified" for rule-based fixes means
the pattern is gone and the file parses. The README's *Known limitations* list is the source.

**What did you not build?** Real log collection, calibrated probabilities, AND/OR prerequisites, code signing,
multi-instance scale, automatic inventory discovery.

**Did AI write this? Is it yours?** AI coding tools (Claude Code) helped with backend, frontend and scenario drafting
and are disclosed in the README; the team reviewed and owns every module. **DECIDE** who can explain which module.

**What is the test coverage?** 30 test files and about 370 test functions under `backend/tests/`, run offline with
fake Supabase and GitHub. We have not measured line coverage; don't quote a percentage. Run `pytest` live if asked.

**How do I know your numbers aren't made up?** `python scripts/benchmark.py` regenerates `docs/BENCHMARKS.md`. Nothing
in the UI is hard-coded; numbers are computed from ingested events.

**What if the AI is wrong?** The risk and the cheapest cut never depend on it. For code fixes its work must pass
Paladin's checks and a human reads the pull request.

**What was the hardest problem?** **DECIDE** (suggested honest answer: making "verified" mean something: separating
what the model claims from what Paladin proves).

**What would you do with another month?** Real connectors (cloud audit logs, EDR), AND/OR prerequisites, calibrated
probabilities, tighter MITRE relevance checks, code-signed installers, multi-instance scale.

### H. Competition and business

**Who are your competitors?** **DECIDE** and be specific. Categories to compare against honestly: SIEMs (alerting),
vulnerability scanners and SAST (listing), attack-path/exposure management products (graph-only), and AI code-fix
tools (patching without a proof step). Our edge is the loop: path → cheapest fix → fix → proof, with the AI outside
the decision path. Don't claim to beat products we haven't tested.

**What's the business model / pricing / go-to-market?** **DECIDE.** Nothing in the repo. Suggested: open-core desktop
app free for individuals, paid team plan for hosted workspaces and connectors.

**Is it open source? What licence?** **DECIDE.** There is no `LICENSE` file in the repo; add one or say it's private.
The repository is currently private (`INSTALLATION.md`). Third-party licences are listed in the README.

**Who is on the team and who did what?** **DECIDE.**

**What's next after the hackathon?** The "another month" list above, then pilot with a real team's logs.

### I. Live-demo recovery questions

**"Show me it works on my repo."** Paste any public GitHub URL; the scan runs on a shallow clone. The fixing agent
needs an Anthropic key and (for `verified`) Docker. Have a fallback repo already scanned.

**"Break it."** Feed a malformed log line: it is rejected as a bad line, not stored. Feed events that match no edge:
no effect. Try a non-GitHub URL: refused by the strict URL check.

**"What happens offline?"** Parsing, correlation, paths and the cut work with no network. Sign-in, GitHub and AI need
connectivity.

**"Can I see the evidence for that score?"** Open the path: each hop shows the event id or code line, the technique
name explained in words, and the story.

## Risks and fixes

| Risk | Fix |
|---|---|
| Live demo fails | Backup video; second device already signed in |
| Judge asks about overclaims | Every claim above is measured or labelled; use the Q&A answers |
| `PRESENTATION.md` still says "under 1 second" | Fix before anyone reads it |
| Unsigned desktop installer blocks on first launch | Install on a judge-facing machine beforehand; Mac needs Privacy & Security → Open Anyway (`INSTALLATION.md`) |
| Fixing agent needs key and Docker | Test on the demo machine the day before; know the fallback verdict |
| Over time limit | Cut slide 4's numbers first; never cut the demo |
| Placeholder text left in README (`<team members>`) | Fill it in |

## Final checklist (morning of)

- [ ] Deck exported to PDF and on a USB stick
- [ ] Backup demo video on the laptop and the USB stick
- [ ] Signed in on desktop app; workspace and repo pre-loaded
- [ ] Docker running; Anthropic key set
- [ ] Phone hotspot tested
- [ ] Timer set: 4 slides about 2 min, demo 3 min
- [ ] Everyone knows who answers which Q&A topic
