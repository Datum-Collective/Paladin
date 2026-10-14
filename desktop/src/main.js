'use strict'
const path = require('node:path')
const {
  app, BrowserWindow, Menu, dialog, ipcMain, nativeTheme, safeStorage, session, shell,
} = require('electron')
const { Backend, resolveCommand } = require('./backend')
const { Settings } = require('./settings')
const { createUpdater } = require('./updater')

const REPO_ROOT = path.resolve(__dirname, '..', '..')
const isMac = process.platform === 'darwin'
let win = null
let backend = null
let settings = null
let updater = null
let restarting = false
const crashTimes = []

if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (!win) return
    if (win.isMinimized()) win.restore()
    win.focus()
  })
}

function log(...a) { console.log('[paladin]', ...a) }
const send = (channel, payload) => { if (win && !win.isDestroyed()) win.webContents.send(channel, payload) }

function sameOrigin(url) {
  try { return backend && new URL(url).origin === backend.origin } catch { return false }
}

function hardenSession() {
  const ses = session.defaultSession
  // The renderer never holds the desktop token; the main process adds it to requests for our own backend only.
  ses.webRequest.onBeforeSendHeaders({ urls: ['http://127.0.0.1/*'] }, (d, cb) => {
    if (sameOrigin(d.url)) d.requestHeaders['X-Desktop-Token'] = backend.token
    cb({ requestHeaders: d.requestHeaders })
  })
  ses.webRequest.onHeadersReceived((d, cb) => {
    const h = { ...d.responseHeaders }
    if (sameOrigin(d.url)) {
      h['Content-Security-Policy'] = [
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; " +
        "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
      ]
    }
    cb({ responseHeaders: h })
  })
  ses.setPermissionRequestHandler((_wc, _perm, cb) => cb(false))
}

function createWindow(origin) {
  win = new BrowserWindow({
    width: 1440, height: 920, minWidth: 980, minHeight: 640,
    show: false,
    title: 'Paladin',
    // vibrancy needs a transparent window; the content column paints its own opaque background
    backgroundColor: isMac ? '#00000000' : (nativeTheme.shouldUseDarkColors ? '#1c1c1e' : '#ffffff'),
    titleBarStyle: isMac ? 'hiddenInset' : 'hidden',
    trafficLightPosition: isMac ? { x: 18, y: 18 } : undefined,
    titleBarOverlay: isMac ? undefined : { color: '#00000000', symbolColor: '#8e8e93', height: 44 },
    vibrancy: isMac ? 'sidebar' : undefined,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true, nodeIntegration: false, sandbox: true, webSecurity: true,
    },
  })
  win.once('ready-to-show', () => win.show())
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https:\/\//.test(url)) shell.openExternal(url)
    return { action: 'deny' }
  })
  win.webContents.on('will-navigate', (e, url) => {
    if (sameOrigin(url)) return
    e.preventDefault()
    if (/^https:\/\//.test(url)) shell.openExternal(url)
  })
  win.on('closed', () => { win = null })
  if (process.env.PALADIN_SMOKE_TEST === '1') smokeTest(win)
  win.loadURL(origin)
}

// `PALADIN_SMOKE_TEST=1 npm start`: prove the window loads the UI and the backend session works, then exit.
function smokeTest(w) {
  w.webContents.once('did-finish-load', async () => {
    try {
      const r = await w.webContents.executeJavaScript(
        `fetch('/api/auth/local',{method:'POST'}).then(r=>r.json()).then(b=>fetch('/api/me').then(r=>r.json()).then(m=>({local:b,me:m,bridge:typeof window.paladin,title:document.title})))`)
      console.log('SMOKE', JSON.stringify(r))
      if (process.env.PALADIN_SCREENSHOT) {
        // optional: load a few real log lines, wait for the UI to settle, save a PNG of the window
        await w.webContents.executeJavaScript(`fetch('/api/ingest',{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({format:'linux_auth',lines:['May 14 13:05:11 WEB-BO-01 sshd[912]: Accepted password for www-data from 185.199.110.42 port 51544 ssh2']})})`)
        await new Promise((res) => setTimeout(res, 2500))
        const img = await w.webContents.capturePage()
        require('node:fs').writeFileSync(process.env.PALADIN_SCREENSHOT, img.toPNG())
      }
      app.exit(r.me && r.me.email ? 0 : 1)
    } catch (e) {
      console.log('SMOKE_FAIL', String(e))
      app.exit(1)
    }
  })
}

function failureWindow(message) {
  const html = `<meta charset=utf-8><body style="font:14px -apple-system,Segoe UI,sans-serif;padding:48px;
    color-scheme:light dark"><h2>Paladin could not start its analysis engine</h2>
    <pre style="white-space:pre-wrap">${String(message).replace(/[<&]/g, (c) => ({ '<': '&lt;', '&': '&amp;' }[c]))}</pre>`
  win = new BrowserWindow({ width: 760, height: 460, title: 'Paladin' })
  win.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`)
}

function registerIpc() {
  ipcMain.handle('app:info', () => ({
    version: app.getVersion(), platform: process.platform, arch: process.arch, packaged: app.isPackaged,
    dataDir: path.join(app.getPath('userData'), 'data'),
  }))
  ipcMain.handle('settings:get', () => settings.status())
  ipcMain.handle('settings:set', async (_e, patch) => {
    settings.set(patch)
    restarting = true // the key is read at spawn, so the engine restarts; the crash handler must not race it
    try {
      send('backend:status', { state: 'restarting' })
      await backend.restart()
      if (win && !win.isDestroyed()) await win.loadURL(backend.origin)
    } finally { restarting = false }
    return settings.status()
  })
  ipcMain.handle('update:check', () => updater.check())
  ipcMain.handle('update:install', () => updater.install())
  ipcMain.handle('app:open-data', () => shell.openPath(path.join(app.getPath('userData'), 'data')))
}

function buildMenu() {
  const t = [
    ...(isMac ? [{ role: 'appMenu' }] : []),
    { role: 'fileMenu' }, { role: 'editMenu' },
    { label: 'View', submenu: [{ role: 'reload' }, { role: 'togglefullscreen' }, { type: 'separator' },
                               { role: 'resetZoom' }, { role: 'zoomIn' }, { role: 'zoomOut' },
                               ...(app.isPackaged ? [] : [{ type: 'separator' }, { role: 'toggleDevTools' }])] },
    { role: 'windowMenu' },
  ]
  Menu.setApplicationMenu(Menu.buildFromTemplate(t))
}

async function boot() {
  const dataRoot = path.join(app.getPath('userData'), 'data')
  settings = new Settings(app.getPath('userData'), safeStorage)
  backend = new Backend({
    command: resolveCommand({ packaged: app.isPackaged, resourcesPath: process.resourcesPath, repoRoot: REPO_ROOT }),
    dataDir: dataRoot,
    version: app.getVersion(),
    getExtraEnv: () => settings.env(),
  })
  backend.on('crash', async ({ code, signal, tail }) => {
    log('backend crashed', code, signal, tail)
    if (restarting) return
    const now = Date.now()
    crashTimes.push(now)
    while (crashTimes.length && crashTimes[0] < now - 60000) crashTimes.shift()
    if (crashTimes.length > 3) {
      dialog.showErrorBox('Paladin engine keeps stopping', String(tail || 'The analysis engine exited repeatedly.'))
      app.quit()
      return
    }
    send('backend:status', { state: 'restarting' })
    try {
      await new Promise((r) => setTimeout(r, 500 * crashTimes.length))
      await backend.start()
      if (win) await win.loadURL(backend.origin)
    } catch (e) {
      dialog.showErrorBox('Paladin engine stopped', String(e.message || e))
      app.quit()
    }
  })
  registerIpc()
  buildMenu()
  hardenSession()
  updater = createUpdater({ app, send: (s) => send('update:status', s), log })
  try {
    await backend.start()
  } catch (e) {
    failureWindow(e.message || e)
    return
  }
  createWindow(backend.origin)
  if (app.isPackaged) setTimeout(() => updater.check(), 5000)
}

app.whenReady().then(boot)
app.on('window-all-closed', () => { if (!isMac) app.quit() })
app.on('activate', () => { if (!win && backend && backend.proc) createWindow(backend.origin) })
let quitting = false
app.on('before-quit', (e) => {
  if (quitting || !backend) return
  e.preventDefault()
  quitting = true
  backend.stop().finally(() => app.quit())
})
