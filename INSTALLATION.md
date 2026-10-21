# Installing and using Paladin

Paladin is a desktop app that scans a code repository, shows how an attacker could chain its weaknesses into an
attack path, and helps you fix them (with a pull request if you want one). This guide covers installing it on a Mac
and using it end to end. A Windows installer (`Paladin-Setup-<version>.exe`) is published alongside the Mac build.

## What you need

- A Mac with **Apple Silicon** (M1 or later). The Mac build is arm64 only; it does not run on Intel Macs.
- A **GitHub account**. Sign-in is GitHub only; there is no username or password.
- Optional: an **Anthropic API key** for the AI assistant and the fixing agent (an OpenAI key also works for the
  assistant). Without one, scanning, attack paths and rule-based fixes still work.
- Optional: a **GitHub token** if you want Paladin to open pull requests or scan private repositories.
- Optional: **Docker Desktop**, so the fixing agent can run your repository's tests in a sandbox before calling a fix
  verified.

## 1. Download

Get `Paladin-<version>-arm64.dmg` from the latest release:
https://github.com/Manipal-Hackathon-2026/DATUM/releases/latest

(The repository is private: you need access to it to see the release.)

## 2. Install

1. Open the `.dmg`.
2. Drag **Paladin** onto the **Applications** folder in the window that appears.
3. Eject the disk image (drag it to the Trash, or right-click it in Finder and choose Eject).

## 3. First launch: allow it in Privacy & Security

This build is not signed with an Apple Developer ID or notarized by Apple, so the first time you open it macOS blocks
it with a message like **"Paladin" Not Opened** or **"Apple could not verify Paladin is free of malware"**. This is
expected. Allow it once:

1. Open **Applications** and double-click **Paladin**. When the warning appears, click **Done** (not Move to Trash).
2. Open **System Settings** → **Privacy & Security**.
3. Scroll down to the **Security** section. You will see *"Paladin" was blocked to protect your Mac.* Click
   **Open Anyway**.
4. Enter your Mac password (or use Touch ID) when asked.
5. In the dialog that follows, click **Open Anyway** again.

macOS remembers this; after the first time Paladin opens normally.

> The **Open Anyway** button only shows for about an hour after the blocked attempt. If you don't see it, try opening
> Paladin again from Applications, then go straight back to Privacy & Security.

**If it still won't open** (for example "Paladin is damaged and can't be opened"), the download was quarantined.
Clear the quarantine flag in Terminal and open it again:

```bash
xattr -cr /Applications/Paladin.app
```

### Keychain prompt

Paladin stores your API keys and tokens encrypted with the macOS Keychain. The first time it saves or reads one, macOS
may ask: *Paladin wants to use your confidential information stored in "Paladin Safe Storage" in your keychain.*
Enter your Mac login password and click **Always Allow**, otherwise you will be asked on every launch.

### Other permissions

Paladin does not need camera, microphone, screen recording, Full Disk Access or any other privacy permission. If you
open a local folder in a protected location (Desktop, Documents or Downloads), macOS asks once whether Paladin may
access that folder; click **Allow**.

## 4. Sign in

1. Click **Sign In with GitHub**. Your browser opens on GitHub's sign-in page (it never happens inside the app).
2. Pick your GitHub account and approve. Sign-in only asks GitHub for your identity and email, not your repositories.
3. Go back to Paladin; you are signed in.

Your workspaces and scan results are stored in your own account and nobody else can read them.

## 5. Add your keys (optional)

Open **Settings** (`⌘,`):

| Setting | What it unlocks | Where to get it |
|---|---|---|
| Anthropic API key | AI assistant, AI triage, and the **fixing agent** that writes and checks fixes | console.anthropic.com → API Keys |
| OpenAI API key | AI assistant with OpenAI models | platform.openai.com → API keys |
| GitHub token | Scanning private repositories and opening **pull requests** | GitHub → Settings → Developer settings → Personal access tokens |

For the GitHub token, create a **fine-grained** token for the repositories you want to work on with **Contents** and
**Pull requests** set to **Read and write**. Your account also needs write access to those repositories. Settings
tells you straight away whether a key was accepted and, if not, why.

Keys stay on your Mac in the Keychain; they are not uploaded to Paladin's servers.

## 6. Using Paladin

### Quick tour

1. **Start screen.** A *Get started* checklist walks you through connecting GitHub and starting your first scan.
   Every step is optional and the checklist disappears once you dismiss it.
2. **Bring in a repository**, any of these ways:
   - Paste a GitHub link or `owner/name` into the launcher. Paladin checks it with GitHub and shows a preview (name,
     visibility, branch) before anything is cloned.
   - **File → Open Folder…** (`⌘O`) to scan a Git repository already on your Mac.
   - **File → New Workspace** (`⌘N`) to start empty, then add a repository or log data later.
   - **Workspace → Play Sample Scenario** to try it with built-in sample data and no repository at all.
3. **Wait for the scan.** Paladin clones the code (it never runs it), scans it, and builds the attack graph. Progress
   and any failure reason show on **Repository** and **Activity**; a failed scan can be retried without losing
   anything.

### The main screens

| Screen | Shortcut | What it shows |
|---|---|---|
| Analysis | `⌘1` | Live attack graph, the ranked attack paths, each hop explained in plain English with its MITRE ATT&CK id and evidence, and the cheapest set of fixes that cuts every path |
| Repository | `⌘2` | Findings in the code, proposed patches, and the pull request button |
| Insights | `⌘3` | Metrics, timeline and benchmarks |
| Assistant | `⌘4` | Chat with Claude or OpenAI about the workspace, and the fixing agent |
| Activity | `⌘5` | Scan history and an audit trail of every fix decision |
| Workspaces | `⌘6` | All your workspaces: search, sort, rename, delete |
| Integrations | `⌘7` | Connected services and log-ingestion keys for shipping logs into a workspace |

`⌘K` opens the command palette, `⌘B` shows or hides the sidebar, `⌘R` refreshes.

### Fixing a weakness

1. On **Analysis**, use **Propose Cheapest Cut** or **Propose Best Single Fix** (also under the **Workspace** menu), or
   open a finding on **Repository**.
2. Each fix goes **proposed → approved → executed → verified**. Nothing changes until you approve it.
3. With an Anthropic key, the **fixing agent** (Assistant → Fix) edits the code in Paladin's own working copy of the
   repository, re-scans it and runs the tests. Paladin, not the AI, decides the verdict:
   - **verified**: the finding is gone, nothing new appeared, the tests pass and every cited MITRE id is real.
   - Otherwise it tells you exactly what is missing (for example `fixed_untested` if the tests could not run, or
     `failed_tests`).
   Running tests needs Docker Desktop to be running.
4. When you are happy, **open a pull request** from Repository (needs the GitHub token), or download the patch and
   apply it yourself. Nothing reaches GitHub until you click to open the pull request.

### Adding log data

**File → Add Log Data…** (`⌘⇧L`) imports security logs (for example Linux auth logs) into the current workspace.
Logged events confirm or raise the likelihood of edges in the attack graph. For continuous ingestion, create a
workspace key under **Integrations** and point your log shipper at it.

## Updating

Paladin checks for new releases shortly after launch and every 30 minutes. Because this build is not Developer ID
signed, macOS will not let it replace itself: when an update is available, **Settings → General** shows a **Download
Manually** button. Download the new `.dmg`, drag Paladin into Applications again and choose **Replace**. You may need
to repeat the Privacy & Security step once for the new version. Your sign-in, keys and workspaces are kept.

## Where your data lives

- Local working copies, logs and app data: `~/Library/Application Support/Paladin/data` (Settings can open this
  folder for you).
- Keys and tokens: the macOS Keychain, under "Paladin Safe Storage".
- Workspaces, findings and history: your Paladin account (Supabase), visible only to you.

## Uninstalling

1. Quit Paladin and drag it from Applications to the Trash.
2. To remove local data too, delete `~/Library/Application Support/Paladin`.
3. Optionally, delete the "Paladin Safe Storage" entry in **Keychain Access**.

## Troubleshooting

| Problem | Fix |
|---|---|
| "Paladin" Not Opened / cannot verify developer | Follow step 3 (Privacy & Security → Open Anyway). |
| "Paladin is damaged and can't be opened" | Run `xattr -cr /Applications/Paladin.app`, then open it again. |
| App doesn't launch on an Intel Mac | The Mac build is Apple Silicon only. |
| Keychain asks for a password every launch | Answer the prompt with **Always Allow**. |
| Sign-in page doesn't come back to the app | Finish sign-in in the browser, then switch back to Paladin; if it still shows signed out, click Sign In again. |
| "Pull requests need a GitHub token" | Add a fine-grained token with Contents and Pull requests set to Read and write (Settings). |
| Repository not found | It is private or misspelled; add a GitHub token that can access it. |
| Fix stays `fixed_untested` | Start Docker Desktop so the tests can run, then run the fix again. |
| Update downloads but won't install | Expected for this unsigned build; use **Download Manually** in Settings → General. |
