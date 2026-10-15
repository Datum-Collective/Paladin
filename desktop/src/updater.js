'use strict'
// Self-update from GitHub Releases through electron-updater, reduced to one status shape for the renderer.
//
// Behaviour: check shortly after launch and then every `intervalMs`; download in the background; as soon as a
// download finishes, restart into the new version after `installDelayMs` (long enough for the UI to say so).
// Updates only run in a packaged build. On macOS the app must be Developer ID signed for the swap to succeed:
// when it cannot be applied the state carries `releaseUrl` so the UI can send the person to the download page.
const DEFAULTS = {
  intervalMs: 30 * 60 * 1000,    // how often to look for a newer release while the app stays open
  firstCheckMs: 5000,            // first look, shortly after launch
  installDelayMs: 4000,          // pause between "downloaded" and restarting
  autoInstall: true,
}

function createUpdater({ app, send, log = () => {}, releaseUrl = '', load = () => require('electron-updater'),
  timers = { setTimeout, setInterval, clearTimeout, clearInterval }, ...opts }) {
  const cfg = { ...DEFAULTS, ...opts }
  let state = { phase: app.isPackaged ? 'idle' : 'disabled', version: null, percent: 0, error: null, releaseUrl: '' }
  const set = (patch) => { state = { ...state, ...patch }; send(state) }
  let autoUpdater = null
  let interval = null
  let installTimer = null
  let busy = false

  if (app.isPackaged) {
    try {
      ;({ autoUpdater } = load())
      autoUpdater.autoDownload = true
      autoUpdater.autoInstallOnAppQuit = true     // if the person quits first, the update still lands on the way out
      autoUpdater.logger = { info: log, warn: log, error: log, debug: () => {} }
      autoUpdater.on('checking-for-update', () => set({ phase: 'checking', error: null }))
      autoUpdater.on('update-available', (i) => set({ phase: 'downloading', version: i.version, percent: 0 }))
      autoUpdater.on('update-not-available', () => set({ phase: 'current' }))
      autoUpdater.on('download-progress', (p) => set({ phase: 'downloading', percent: Math.round(p.percent) }))
      autoUpdater.on('update-downloaded', (i) => {
        set({ phase: 'ready', version: i.version, percent: 100 })
        if (cfg.autoInstall) {
          set({ phase: 'installing' })
          clearTimeout(installTimer)
          installTimer = timers.setTimeout(() => {
            try { autoUpdater.quitAndInstall() } catch (e) { fail(e) }
          }, cfg.installDelayMs)
        }
      })
      autoUpdater.on('error', (e) => fail(e))
    } catch (e) {
      state = { ...state, phase: 'disabled', error: String(e.message || e) }
    }
  }

  function fail(e) {
    log('update error', String((e && e.message) || e))
    set({ phase: 'error', error: String((e && e.message) || e), releaseUrl })
  }

  const check = async () => {
    if (!autoUpdater || busy || state.phase === 'downloading' || state.phase === 'installing') return state
    busy = true
    try { await autoUpdater.checkForUpdates() } catch (e) { fail(e) } finally { busy = false }
    return state
  }

  return {
    state: () => state,
    check,
    /** Look once soon after launch, then keep looking while the app is open. Safe to call more than once. */
    start() {
      if (!autoUpdater || interval) return
      timers.setTimeout(check, cfg.firstCheckMs)
      interval = timers.setInterval(check, cfg.intervalMs)
      if (interval && interval.unref) interval.unref()
    },
    stop() { if (interval) timers.clearInterval(interval); interval = null; clearTimeout(installTimer) },
    install: () => { if (autoUpdater && (state.phase === 'ready' || state.phase === 'installing')) autoUpdater.quitAndInstall() },
  }
}

module.exports = { createUpdater, DEFAULTS }
