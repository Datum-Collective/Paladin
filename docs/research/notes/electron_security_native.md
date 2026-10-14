# Electron security and native-feel checklist for a key-holding desktop app (Electron 44.x)

Note: the security page links the v44.7.2 tag, so the docs fetched correspond to 44.x. Docs fetched 2026-10-14 from electronjs.org/docs/latest.

## 1. Official security checklist (all 20 items) and relevance to a local http://127.0.0.1 origin

### Takeaway
Electron's checklist has 20 items. For an app loading its UI from a local backend over http://127.0.0.1, the key adjustments are: item 1 (HTTPS) is a conscious exception for loopback, item 18 (avoid file://) is satisfied by loading over http or a custom protocol, and items 13/14/17 (navigation, window open, sender validation) must pin to the exact loopback origin including port.

### Cited Findings
Source for all items: [Electron Security tutorial](https://www.electronjs.org/docs/latest/tutorial/security)
- 1 Only load secure content: use HTTPS/WSS rather than HTTP/WS. A plain http://127.0.0.1 origin deviates from this; the page does not carve out a loopback exception (UNVERIFIED whether any exception is stated). — [Security](https://www.electronjs.org/docs/latest/tutorial/security)
- 2 No Node.js integration for remote content; expose needed APIs via preload and contextBridge. — [Security](https://www.electronjs.org/docs/latest/tutorial/security)
- 3 Enable context isolation (default since Electron 12; do not set `contextIsolation: false`). — [Security](https://www.electronjs.org/docs/latest/tutorial/security)
- 4 Enable process sandboxing (default since Electron 20; don't set `sandbox: false`; `nodeIntegration: true` also disables sandboxing). — [Security](https://www.electronjs.org/docs/latest/tutorial/security)
- 5 Handle session permission requests: Electron auto-approves by default; set a handler approving only specific permissions from verified origins. — [Security](https://www.electronjs.org/docs/latest/tutorial/security)
- 6 Do not disable `webSecurity` (turns off same-origin policy). — [Security](https://www.electronjs.org/docs/latest/tutorial/security)
- 7 Define a CSP (e.g. `script-src 'self'`) via response header from `session.webRequest.onHeadersReceived` or a `<meta http-equiv>` tag; headers do not apply to file:// so meta is needed there. — [Security](https://www.electronjs.org/docs/latest/tutorial/security)
- 8 Do not enable `allowRunningInsecureContent`. 9 Do not enable experimental features. 10 Do not use `enableBlinkFeatures`. — [Security](https://www.electronjs.org/docs/latest/tutorial/security)
- 11 No `allowpopups` on webviews; 12 verify webview options in `will-attach-webview` (not relevant if webview tag unused; prefer not to use it). — [Security](https://www.electronjs.org/docs/latest/tutorial/security)
- 13 Limit navigation: handle `will-navigate` and compare parsed `new URL(url).origin` against an expected value, not string prefix checks; hook via `app.on('web-contents-created')`. — [Security](https://www.electronjs.org/docs/latest/tutorial/security)
- 14 Limit new windows: `contents.setWindowOpenHandler(() => ({ action: 'deny' }))` by default. — [Security](https://www.electronjs.org/docs/latest/tutorial/security)
- 15 Do not pass untrusted content to `shell.openExternal`; pass only fixed trusted URLs. — [Security](https://www.electronjs.org/docs/latest/tutorial/security)
- 16 Use a current Electron version; migrate one major at a time via Breaking Changes. — [Security](https://www.electronjs.org/docs/latest/tutorial/security)
- 17 Validate the IPC sender: check sender frame origin against an allowlist in every handler. — [Security](https://www.electronjs.org/docs/latest/tutorial/security)
- 18 Avoid file://; serve via custom protocol with `protocol.handle`. — [Security](https://www.electronjs.org/docs/latest/tutorial/security)
- 19 Check fuses via `@electron/fuses`; disable unneeded ones (e.g. `runAsNode`, `nodeCliInspect`). — [Security](https://www.electronjs.org/docs/latest/tutorial/security)
- 20 Do not expose Electron APIs to untrusted content: no raw `ipcRenderer`, no raw callbacks. — [Security](https://www.electronjs.org/docs/latest/tutorial/security)
- The docs' permission-handler example calls `callback(true)` without returning, which can fall through to a second callback; add `return`. (Observed by the fetch summary; verify against live page.) — [Security](https://www.electronjs.org/docs/latest/tutorial/security)
- Permission handling needs both `setPermissionRequestHandler(webContents, permission, callback, details)` and `setPermissionCheckHandler(webContents, permission, requestingOrigin, details)`, because web APIs usually run a check first. For subframes `webContents` is top-level, so use `requestingOrigin`/`requestingUrl`/`isMainFrame`; `webContents` can be null in checks (service worker, notifications). `setDevicePermissionHandler` covers hid/serial/usb. — [Session API](https://www.electronjs.org/docs/latest/api/session)
- Fuses (9): `runAsNode` (default on), `cookieEncryption` (off), `nodeOptions` (on), `nodeCliInspect` (on), `embeddedAsarIntegrityValidation` (off; macOS and Windows), `onlyLoadAppFromAsar` (off), `loadBrowserProcessSpecificV8Snapshot` (off), `grantFileProtocolExtraPrivileges` (on), `wasmTrapHandlers` (on). — [Fuses](https://www.electronjs.org/docs/latest/tutorial/fuses)

### Inferences
- Implementer checklist for a loopback UI: pin `will-navigate`, `setWindowOpenHandler`, permission handlers and IPC sender checks to `http://127.0.0.1:<port>` exact origin (compare `new URL().origin`); consider a random port or loading UI from bundled files via `protocol.handle` so a different local process on that port is not trusted.
- Another local process could listen on the loopback port before the backend does; the origin check alone does not authenticate the backend. Use a per-launch random token (UNVERIFIED as an Electron recommendation; general practice).
- With a fixed CSP, `connect-src` should allow only the backend origin; the renderer should never connect to Anthropic/OpenAI/GitHub directly.
- Disable fuses `runAsNode`, `nodeOptions`, `nodeCliInspect`, `grantFileProtocolExtraPrivileges`; enable `embeddedAsarIntegrityValidation` and `onlyLoadAppFromAsar` to protect code that handles keys; enable `cookieEncryption` if cookies are used (it is one-way).

### Gaps
- Whether the checklist explicitly exempts loopback HTTP from item 1: not confirmed in fetched summary.
- Exact current text of the 44.x CSP section for `connect-src` guidance not retrieved.

## 2. safeStorage

### Takeaway
`safeStorage` (main process only) encrypts strings with OS-held keys; it protects against other users and offline disk access, not against other apps running as the same user. Prefer the async API; on Linux check for `basic_text` backend.

### Cited Findings
- Main-process-only API that encrypts/decrypts strings using OS cryptography. — [safeStorage](https://www.electronjs.org/docs/latest/api/safe-storage)
- macOS: keys stored in Keychain; other apps/users can't load them without user override; apps should be code signed, otherwise Keychain may re-prompt on every update. — [safeStorage](https://www.electronjs.org/docs/latest/api/safe-storage); [Code signing](https://www.electronjs.org/docs/latest/tutorial/code-signing)
- Windows: DPAPI keys; blocks other users but not other apps in the same user session. — [safeStorage](https://www.electronjs.org/docs/latest/api/safe-storage)
- Linux: backends `kwallet`, `kwallet5`, `kwallet6`, `gnome-libsecret`; if none is available, encrypted with a hardcoded plaintext password (effectively unprotected), detectable via `getSelectedStorageBackend() === 'basic_text'`. — [safeStorage](https://www.electronjs.org/docs/latest/api/safe-storage)
- Sync methods: `isEncryptionAvailable()`, `encryptString()` -> Buffer (throws on failure), `decryptString()`. On macOS and Linux sync calls can block the thread to collect user input. — [safeStorage](https://www.electronjs.org/docs/latest/api/safe-storage)
- Async methods (recommended): `isAsyncEncryptionAvailable()`, `encryptStringAsync()`, `decryptStringAsync()` -> `{shouldReEncrypt, result}`; if `shouldReEncrypt` is true, call decrypt again for the new value (per the page's wording). Docs say the sync API "may be deprecated in a future version". — [safeStorage](https://www.electronjs.org/docs/latest/api/safe-storage)
- Linux async providers: `org.freedesktop.portal.Secret`, Secret Service API, or fallback. — [safeStorage](https://www.electronjs.org/docs/latest/api/safe-storage)
- `getSelectedStorageBackend()` is Linux only; returns `unknown` before `ready`; override via `--password-store`. `setUsePlainTextEncryption()` is Linux only, no-op elsewhere. — [safeStorage](https://www.electronjs.org/docs/latest/api/safe-storage)
- Availability: on Linux and Windows, `isEncryptionAvailable()` is true only after `ready`; macOS true if Keychain available. — [safeStorage](https://www.electronjs.org/docs/latest/api/safe-storage)
- `safeStorage` and the `cookieEncryption` fuse share Keychain access. — [Code signing](https://www.electronjs.org/docs/latest/tutorial/code-signing)

### Inferences
- Store only the encrypted blob (e.g. in userData); never return decrypted keys to the renderer. Await `app.whenReady()` and `isAsyncEncryptionAvailable()` before use; on Linux refuse or warn on `basic_text`.
- Same-user malware on Windows can call DPAPI as the user; Electron states this itself. Treat safeStorage as at-rest protection only.
- macOS keychain prompt behavior from an unsigned dev build will differ from signed releases; test with a signed build.

### Gaps
- Electron docs have no explicit "how to store secrets" statement beyond the above; none found.
- The exact semantic of `isTemporarilyUnavailable` is named but not documented in the fetched page.

## 3. IPC security

### Takeaway
Expose one narrow function per channel via contextBridge, use `invoke`/`handle`, and validate `event.senderFrame` origin in every handler.

### Cited Findings
- Use `ipcRenderer.invoke` + `ipcMain.handle` for two-way; avoid `sendSync`. — [IPC tutorial](https://www.electronjs.org/docs/latest/tutorial/ipc)
- Do not expose `ipcRenderer.send`/`invoke` wholesale; wrap listeners so `event.sender` (which leaks `ipcRenderer`) isn't passed to the page. — [IPC tutorial](https://www.electronjs.org/docs/latest/tutorial/ipc); [Context isolation](https://www.electronjs.org/docs/latest/tutorial/context-isolation)
- "Just enabling contextIsolation and using contextBridge does not automatically mean that everything you do is safe"; expose "one method per IPC message". — [Context isolation](https://www.electronjs.org/docs/latest/tutorial/context-isolation)
- Errors thrown in `handle` reach the renderer with only the original `message`; IPC uses Structured Clone (no WebContents, DOM objects). — [IPC tutorial](https://www.electronjs.org/docs/latest/tutorial/ipc)
- `senderFrame` is `WebFrameMain | null`; can be null if the frame navigated away or was destroyed, so null-check. — [IpcMainInvokeEvent](https://www.electronjs.org/docs/latest/api/structures/ipc-main-invoke-event)
- `frame.origin` is serialized per RFC 6454, can differ from `frame.url`; `"null"` for schemeless origins. Usually only the main frame can use IPC unless `nodeIntegrationInSubFrames`. — [WebFrameMain](https://www.electronjs.org/docs/latest/api/web-frame-main)
- Security checklist item 17 requires validating the sender in every handler. — [Security](https://www.electronjs.org/docs/latest/tutorial/security)

### Inferences
- Handler template: `if (!e.senderFrame || e.senderFrame.origin !== ALLOWED_ORIGIN) throw`; then schema-validate args (zod or equivalent; no Electron-specific source for the validation library); never accept a path, URL, provider name or header from the renderer without allowlisting.
- Never expose a "get key" channel; expose `setKey(provider, value)` write-only and `hasKey(provider)` boolean.

### Gaps
- Official docs fetched do not give a full sender-validation code sample beyond the checklist (the live security page may; not captured).

## 4. Keeping keys out of the renderer; env vs stdin/IPC to backend

### Takeaway
Renderer should send only prompts/operations over a narrow bridge; main (or backend) attaches the key. Electron docs do not prescribe env vs stdin for a Python child; the tradeoff below is inference.

### Cited Findings
- `utilityProcess.fork` `env` defaults to `process.env`; stdio supports `pipe`/`ignore`/`inherit` (default `inherit`); stdin other than `ignore` throws; `postMessage`/`process.parentPort` for messaging. Note: this is for Node utility processes, not a Python child (use `child_process.spawn`). — [utilityProcess](https://www.electronjs.org/docs/latest/api/utility-process)
- With `pipe`, the parent can read child's stdout/stderr (so don't log keys). — [utilityProcess](https://www.electronjs.org/docs/latest/api/utility-process)
- Linux: a process's environment is readable at /proc/PID/environ by the owner and root (forum-level source, not vendor). — [Search result, forum/NetBSD advisory](https://ftp.riken.jp/NetBSD/misc/security/advisories/NetBSD-SA2023-004.txt.asc) (weak source; marked UNVERIFIED for macOS `ps eww` behavior)
- Fuses `runAsNode` and `nodeOptions` can be disabled to limit environment-variable-based abuse (`ELECTRON_RUN_AS_NODE`, `NODE_OPTIONS`). — [Fuses](https://www.electronjs.org/docs/latest/tutorial/fuses)

### Inferences
- Option A, env at spawn: simple, visible to same-user processes via process inspection and inherited by grandchildren; set only the needed vars with an explicit `env` object, never inherit full env.
- Option B, stdin or an inherited pipe after spawn (key sent once, kept in backend memory): not in environ or argv; slightly more code; preferred. Option C, main proxies calls to providers: backend never holds keys, but loses Python-side SDK use.
- Never pass keys in argv (visible in process listings). Backend should bind 127.0.0.1 only and require a per-launch bearer token.
- Same-user malware can still ptrace/read memory on most desktop OSes; none of these options defeat it.

### Gaps
- No primary vendor source found for macOS `ps -E`/environment visibility; UNVERIFIED.
- No Electron doc recommending a pattern for a Python sidecar.

## 5. Streaming AI responses to the renderer

### Takeaway
Electron docs offer no streaming-specific guidance; options are SSE/fetch streaming from the loopback backend (CSP `connect-src` to the backend origin) or main-to-renderer `webContents.send` chunks. Details below are inference.

### Cited Findings
- Main-to-renderer: `webContents.send` + `ipcRenderer.on` in preload; there is no `invoke` equivalent in that direction, replies need a separate renderer-to-main message. — [IPC tutorial](https://www.electronjs.org/docs/latest/tutorial/ipc)
- MessagePort can be passed to set up direct channels (renderer-to-renderer; MessagePortMain exists for main/utility). — [IPC tutorial](https://www.electronjs.org/docs/latest/tutorial/ipc); [utilityProcess](https://www.electronjs.org/docs/latest/api/utility-process)

### Inferences
- SSE/fetch from backend: native cancellation via `AbortController`, browser-managed backpressure; requires the renderer origin to reach the backend (same origin if UI is served by the backend; otherwise CORS and CSP). Keys never involved because the backend holds them.
- IPC streaming: use a request id, `webContents.send('chunk', id, text)`, and a `cancel(id)` channel that aborts the upstream request; no built-in backpressure so batch chunks (e.g. per animation frame).
- Pick SSE if the backend is already the UI origin; choose IPC only if main proxies provider calls.

### Gaps
- No primary-source guidance on backpressure in Electron IPC.

## 6. Auto-update and code signing relevance to key storage

### Takeaway
Signing is required for consistent macOS Keychain behavior with `safeStorage` and for Squirrel.Mac auto-update.

### Cited Findings
- macOS requires code signing plus notarization; without them Gatekeeper warns. — [Code signing](https://www.electronjs.org/docs/latest/tutorial/code-signing)
- Features needing a signed app: `safeStorage` (re-prompts after updates otherwise), `app.setLoginItemSettings()`, `cookieEncryption` fuse, `autoUpdater` (Squirrel.Mac requires signed app). — [Code signing](https://www.electronjs.org/docs/latest/tutorial/code-signing)
- Windows: EV code signing certificate required since June 2023 for SmartScreen reputation per the page; hardware (FIPS 140 L2) storage; cloud signing options (DigiCert KeyLocker, Azure Artifact Signing). — [Code signing](https://www.electronjs.org/docs/latest/tutorial/code-signing)

### Inferences
- Keep the same signing identity (Team ID) across releases so the Keychain item remains accessible without re-prompts. Specific ACL/access-group semantics were not in Electron docs (UNVERIFIED; see Apple Keychain docs).
- `embeddedAsarIntegrityValidation` complements signing for tamper detection.

### Gaps
- Apple keychain ACL tie to code signature requirement not verified from Apple sources in this pass.

## 7. Native-feel features (HIG-related)

### Takeaway
All needed APIs exist; most are platform-specific so gate by `process.platform`. SF Symbols are available on macOS via `nativeImage.createFromNamedImage`/`createMenuSymbol`; Windows has no equivalent.

### Cited Findings
- `titleBarStyle`: `hidden` (macOS traffic lights stay upper-left; Windows/Linux need `titleBarOverlay`), `hiddenInset` (macOS; shifts traffic lights inset), `customButtonsOnHover` (macOS). — [Custom title bar](https://www.electronjs.org/docs/latest/tutorial/custom-title-bar)
- `trafficLightPosition: {x, y}` (macOS), `win.setWindowButtonVisibility`, `win.setWindowButtonPosition(pos|null)`. — [Custom title bar](https://www.electronjs.org/docs/latest/tutorial/custom-title-bar); [BrowserWindow](https://www.electronjs.org/docs/latest/api/browser-window)
- `titleBarOverlay` (Windows/Linux): `height`, `color`, `symbolColor` (Windows only); DOM can't use the overlay area; `win.setTitleBarOverlay()` updates it. — [Custom title bar](https://www.electronjs.org/docs/latest/tutorial/custom-title-bar); [BrowserWindow](https://www.electronjs.org/docs/latest/api/browser-window)
- `win.setVibrancy(type)` (macOS) types include `titlebar`, `sidebar`, `hud`, `window` (list truncated in fetch); null removes. — [BrowserWindow](https://www.electronjs.org/docs/latest/api/browser-window)
- `win.setBackgroundMaterial` (Windows): `auto`, `none`, `mica`, `acrylic`, `tabbed`; Windows 11 22H2+ only. — [BrowserWindow](https://www.electronjs.org/docs/latest/api/browser-window)
- `nativeTheme.themeSource` (`system`/`light`/`dark`), `shouldUseDarkColors`, `updated` event, `inForcedColorsMode` (Windows), `prefersReducedTransparency`. — [nativeTheme](https://www.electronjs.org/docs/latest/api/native-theme)
- `systemPreferences.getAccentColor()` macOS (10.14+), `accent-color-changed` event on Windows/Linux; `accessibilityDisplayShouldReduceTransparency` deprecated in favor of `nativeTheme.prefersReducedTransparency`. — [systemPreferences](https://www.electronjs.org/docs/latest/api/system-preferences)
- `app.setAboutPanelOptions`: `applicationName`, `applicationVersion`, `copyright`, `version` (macOS), `credits` (macOS, Windows), `authors`/`website` (Linux), `iconPath` (Linux, Windows). — [app](https://www.electronjs.org/docs/latest/api/app)
- Menu roles include `appMenu`, `fileMenu`, `editMenu`, `viewMenu`, `windowMenu`, `services`, `hide`, `hideOthers`, `about`, `quit`, `startSpeaking`, `toggleSmartQuotes`, etc.; when `role` is set `click` is ignored. `acceleratorWorksWhenHidden` macOS only; `registerAccelerator` Linux/Windows. macOS 14+ `header`/`palette` types and `badge`. — [MenuItem](https://www.electronjs.org/docs/latest/api/menu-item)
- Touch ID: `systemPreferences.canPromptTouchID()` and `promptTouchID(reason)` macOS only; docs state it "will not protect your user data" by itself; native apps must set keychain access control flags. — [systemPreferences](https://www.electronjs.org/docs/latest/api/system-preferences)
- `nativeImage.createFromNamedImage(name)` and `createMenuSymbol(name)` accept SF Symbol names (macOS only); template images end in `Template` (`@2x` variants). Windows: use ICO/PNG; no named-image equivalent. — [nativeImage](https://www.electronjs.org/docs/latest/api/native-image)

### Inferences
- `promptTouchID` is a UI gate, not cryptographic: a "reveal key" flow should still keep the secret only in main and gate display with `promptTouchID` (a compromised main process bypasses it). On Windows there is no Electron equivalent (Windows Hello not in the fetched docs; UNVERIFIED).
- Use Menu roles for standard items to get localized, native behavior and macOS accelerators automatically.
- For Windows: Mica via `backgroundMaterial: 'mica'` plus `titleBarOverlay`; fall back to solid color on Windows 10.

### Gaps
- Full `vibrancy` value list, `visualEffectState`, and constructor-level `backgroundMaterial` option text were in the truncated part of the BrowserWindow page.
- Native context-menu guidance (`Menu.popup`, `context-menu` event) not confirmed beyond MenuItem page; UNVERIFIED.
- Windows Hello equivalent for secret reveal: no Electron API found.
