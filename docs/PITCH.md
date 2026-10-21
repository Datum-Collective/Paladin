# How we sell Paladin

The source of truth for the pitch: what to say on stage and in the Q&A, in plain words. Build slides and talking
points from this file, and use the **leading words** in bold exactly as written so the story stays consistent. The
technical details live in `HOW_IT_WORKS.md` and `docs/PRESENTATION.md`; the honest limits live in
`docs/research/ATTACK_INTELLIGENCE_VALIDATION.md`. Every claim below can be shown in the app or the code.

## The one-liner

> Paladin finds the route an attacker would take into your systems, tells you the one cheapest thing that blocks it,
> fixes it for you, and proves the fix worked.

Say it in four beats: **find the path → find the cheapest fix → fix it → prove it.**

## The problem, in one breath

Security tools shout thousands of small alerts. Each one looks harmless on its own, so teams ignore them, and nobody
sees that four "low" alerts together form one open road to the company's most valuable data. Even when someone does
see it, they get a list of problems, not an answer to "what do I fix first?"

## The house analogy (use this first)

Think of a burglar breaking into a house:

1. The side gate is unlocked.
2. There is a spare key under the doormat.
3. The key opens the back door.
4. The safe is in the back room.

Every one of those is a "low" problem. Together they are a **path** to the safe. A normal tool hands you four
separate warnings. Paladin shows you the whole route, and says: *take the key from under the mat*. That one cheap
move breaks the route, even though the gate is still unlocked.

Map it onto the product: the house is the company's systems, the safe is the **crown jewel** (customer data,
passwords), each step is a weakness, and taking the key is the **cheapest fix**.

## How it works, in five steps

1. **Feed it signals.** Logs (logins, website traffic, intrusion alarms) and code (a GitHub repository or a folder on
   your machine). No cleanup needed; Paladin reads the raw lines.
2. **Connect the dots.** Paladin knows which steps an attacker *could* take. When a real log line shows a step
   actually happening, that step is **confirmed**, gets more likely, and the log line is kept as **evidence**. No
   evidence means no alarm: guesses alone never raise the risk.
3. **Find the dangerous paths.** It draws everything as a map (a **graph**): boxes are computers, accounts and data;
   arrows are attack steps. It then finds every route from the internet to a crown jewel and gives each one a
   **risk score**: how likely every step is, multiplied together, times how valuable the target is. Highest score on
   top.
4. **Find the cheapest fix.** Every step has a cost to fix. Paladin finds the cheapest set of steps to block so that
   *no* dangerous route survives (the maths name is a **minimum cut**). Example from the demo: blocking one step that
   costs 4 beats blocking two steps that cost 5 + 8.
5. **Fix it and prove it.** A human approves the fix. For code, Paladin writes the change and opens a pull request.
   Afterwards it keeps watching: if the attacker's activity shows up again on that step, the fix is marked
   **failed**, with the log lines that prove it. If not, it is **verified**. You watch the risk number drop.

## Every answer comes with a reason

Nothing is a black box. For every path Paladin shows:

- each step, in order, with the log line or line of code behind it;
- the standard name of the technique from **MITRE ATT&CK** (the industry's shared dictionary of attacker moves),
  explained in plain words beside the code;
- a short story in plain English: "someone scanned the web server, logged in as the web user, then…".

## The fixing agent (the "wow" part)

For a code repository, Paladin can hand a weakness to an AI agent (Claude) that edits the code to fix it. The key
point to sell: **the AI does the typing, Paladin does the judging.** A fix is only called **verified** when Paladin
itself checks that:

- a fresh scan no longer finds the problem, and finds nothing new;
- the project's own tests still pass (run in a sealed box, Docker, so the code can't touch your machine);
- every security reference the AI quoted really exists in MITRE's official data.

If any check fails, Paladin says exactly which one (for example "fixed but untested" or "tests failed"). The AI's own
summary is shown separately, labelled as a claim. Nothing goes to GitHub until a human clicks to open the pull
request.

## AI is optional

The scoring, the paths and the cheapest fix are plain maths. They work with no AI and no internet AI account, and
they give the same answer every time. AI is an upgrade (explanations, the assistant chat, harder code fixes), never
the decision maker. This matters to security buyers: no one has to trust a model's guess about their risk.

## Why Paladin and not what they already have

| What they have today | What Paladin does |
|---|---|
| A flood of separate alerts | Joins them into the few routes that matter |
| A list of everything that's wrong | The **cheapest fix** that blocks the most risk |
| "Here's the problem, good luck" | Writes the fix and opens the pull request |
| "Done" when someone clicks done | **Proves** it: watches for the attacker afterwards |
| Scores nobody can explain | Every score shows its steps and evidence |
| AI that decides | Maths decides, AI only helps, and its work is checked |

## Who it's for

- **Small security and dev teams** with no dedicated analyst: they need "what do I fix first", not more alerts.
- **Developers** who want security problems in their own code found and fixed as a pull request they can review.
- **Security leads** who must show their boss that risk actually went down: Paladin records the risk before and
  after every fix.

## Where it runs

- **Desktop app** for Mac (Apple Silicon) and Windows: install and sign in with GitHub. No passwords.
- **Web app**, same features, from a browser.
- **Your data stays yours:** each user can only ever see their own data (enforced by the database itself, not just
  the app). Login tokens never sit in the browser where a script could steal them.

## Demo script (about 3 minutes)

1. **The noise.** Show a handful of separate low alerts. "On their own, nobody would care."
2. **Press Play.** The map builds live as the logs stream in. One path turns red.
3. **Open the path.** Walk each hop: evidence, MITRE name, the plain-English story.
4. **The cheapest fix.** Show the one highlighted step. "Block this, and every route to the data breaks."
5. **Approve → execute.** The risk score drops on screen. Verification runs.
6. **The code.** Open a repository, let the fixing agent fix a finding, show Paladin's verdict and the pull request.

Close with the one-liner.

## Numbers we can stand behind

Measured with `scripts/benchmark.py` on a laptop (Apple Silicon), synthetic data. Full table: `docs/BENCHMARKS.md`.

| What | Result |
|---|---|
| 1,000 log events, read and fully analysed | about 0.2 seconds |
| 10,000 events | about 1.7 seconds |
| 50,000 events | about 9 seconds end to end (2.5 s of it is the path analysis) |
| A map of ~2,000 systems and ~6,000 steps | top 10 paths in about 2 s, cheapest fix in 0.01 s |
| Log formats read today | Linux login logs, web server logs, Snort/Suricata alarms, plus our own JSON |
| Built-in code checks | 12 (leaked passwords, SQL injection, shell commands, weak encryption, unsafe settings, …) |

## Honest answers for the Q&A

Say these before a judge has to ask. Honesty is part of the pitch: we prove things, so we don't overclaim.

- **"Is this real attack data?"** No. The demo uses synthetic logs generated with EvidenceForge (an open-source tool
  from Cisco Talos). The engine reads real log formats; we have not run it on a live company network.
- **"Does it find new hacks / zero-days?"** No. It finds known weaknesses and shows how they *combine* into a route
  you didn't know you had. That combination is the new insight.
- **"Is a code finding a confirmed attack?"** No. A code check finds a *possible* weakness; a log event is what
  confirms activity. Paladin labels which is which.
- **"Where do the probabilities come from?"** Starting values are set by hand per step; real evidence raises them.
  They rank routes against each other; they are not a calibrated forecast.
- **"Is the fix automatic?"** Never without a human. A person approves every fix and opens every pull request.
- **"Did AI build this?"** AI coding tools (Claude Code) helped write it; the team reviewed and owns every part. This
  is disclosed in the README.

## Words to use, and what they mean

| Word | Plain meaning |
|---|---|
| **Path** | A chain of steps an attacker could take from the internet to something valuable |
| **Crown jewel** | The thing worth stealing: customer data, passwords, secrets |
| **Confirmed** | A real log line shows this step actually happened |
| **Evidence** | The exact log line or line of code behind a claim |
| **Risk score** | How likely the whole path is × how valuable the target is |
| **Cheapest fix** (minimum cut) | The lowest-cost set of steps to block so no dangerous path survives |
| **Verified** | Paladin checked the fix worked; the AI's word is not enough |
| **MITRE ATT&CK** | The industry's shared dictionary of attacker techniques |
