'use strict'
// Thin wrapper over electron-updater so the renderer sees one status shape.
// Updates only run in a packaged build; macOS requires the app to be signed (Electron docs, autoUpdater).
function createUpdater({ app, send, log = () => {} }) {
  let state = { phase: app.isPackaged ? 'idle' : 'disabled', version: null, percent: 0, error: null }
  const set = (patch) => { state = { ...state, ...patch }; send(state) }
  let autoUpdater = null

  if (app.isPackaged) {
    try {
      ;({ autoUpdater } = require('electron-updater'))
      autoUpdater.autoDownload = true
      autoUpdater.autoInstallOnAppQuit = true
      autoUpdater.logger = { info: log, warn: log, error: log, debug: () => {} }
      autoUpdater.on('checking-for-update', () => set({ phase: 'checking', error: null }))
      autoUpdater.on('update-available', (i) => set({ phase: 'downloading', version: i.version, percent: 0 }))
      autoUpdater.on('update-not-available', () => set({ phase: 'current' }))
      autoUpdater.on('download-progress', (p) => set({ phase: 'downloading', percent: Math.round(p.percent) }))
      autoUpdater.on('update-downloaded', (i) => set({ phase: 'ready', version: i.version, percent: 100 }))
      autoUpdater.on('error', (e) => set({ phase: 'error', error: String(e && e.message ? e.message : e) }))
    } catch (e) {
      state = { ...state, phase: 'disabled', error: String(e.message || e) }
    }
  }

  return {
    state: () => state,
    check: async () => {
      if (!autoUpdater) return state
      try { await autoUpdater.checkForUpdates() } catch (e) { set({ phase: 'error', error: String(e.message || e) }) }
      return state
    },
    install: () => { if (autoUpdater && state.phase === 'ready') autoUpdater.quitAndInstall() },
  }
}

module.exports = { createUpdater }
