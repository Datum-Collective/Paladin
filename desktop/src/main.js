'use strict'
const path = require('node:path')
const {
  app, BrowserWindow, Menu, dialog, ipcMain, nativeTheme, safeStorage, session, shell,
} = require('electron')
const { Backend, resolveCommand } = require('./backend')
const { Settings } = require('./settings')
const { createUpdater } = require('./updater')
const { buildTemplate } = require('./menu')
const http = require('node:http')

const REPO_ROOT = path.resolve(__dirname, '..', '..')
const isMac = process.platform === 'darwin'
let win = null
let backend = null
let settings = null
let updater = null
const crashTimes = []

const gotLock = app.requestSingleInstanceLock()
if (!gotLock) {
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

/** Decrypted keys go to the backend over loopback with the per-launch token: never env, argv or the renderer. */
function pushKeys() {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify(settings.providerKeys())
    const req = http.request({ host: '127.0.0.1', port: backend.port, path: '/api/providers/keys', method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body),
                 'X-Desktop-Token': backend.token } }, (res) => {
      res.resume()
      res.on('end', () => (res.statusCode === 200 ? resolve() : reject(new Error(`key push failed: ${res.statusCode}`))))
    })
    req.on('error', reject)
    req.end(body)
  })
}

/** Begin a GitHub sign-in and open it in the system browser (RFC 8252: never in an embedded window). */
function startSignIn() {
  return new Promise((resolve, reject) => {
    const req = http.request({ host: '127.0.0.1', port: backend.port, path: '/api/auth/desktop/start', method: 'POST',
      headers: { 'X-Desktop-Token': backend.token, 'Content-Length': 0 } }, (res) => {
      let body = ''
      res.on('data', (c) => { body += c })
      res.on('end', async () => {
        try {
          if (res.statusCode !== 200) throw new Error(`sign-in could not start (${res.statusCode})`)
          const url = new URL(JSON.parse(body).url)
          // only ever open our own engine's login page; it redirects to Supabase and GitHub
          if (url.origin !== backend.origin || url.pathname !== '/api/auth/login') throw new Error('unexpected sign-in URL')
          await shell.openExternal(url.toString())
          resolve(true)
        } catch (e) { reject(e) }
      })
    })
    req.on('error', reject)
    req.end()
  })
}

function trusted(e) {
  const f = e.senderFrame
  return Boolean(f && backend && sameOrigin(f.url))
}

function hardenSession() {
  const ses = session.defaultSession
  // The renderer never holds the desktop token. The main process attaches it to exactly one request from our own
  // page: collecting a finished GitHub sign-in. Starting a sign-in and pushing keys are done by the main process
  // itself (startSignIn, pushKeys), so the renderer cannot start, finish or read either on its own.
  ses.webRequest.onBeforeSendHeaders({ urls: ['http://127.0.0.1/*'] }, (d, cb) => {
    if (sameOrigin(d.url) && d.method === 'POST' && new URL(d.url).pathname === '/api/auth/desktop/claim') {
      d.requestHeaders['X-Desktop-Token'] = backend.token
    }
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
  // deny everything except writing to the clipboard (Copy patch, Copy diagnostics) for our own page
  const allowed = new Set(['clipboard-sanitized-write'])
  ses.setPermissionRequestHandler((wc, perm, cb) => cb(allowed.has(perm) && sameOrigin(wc.getURL())))
  ses.setPermissionCheckHandler((wc, perm, origin) => allowed.has(perm) && sameOrigin(origin || (wc && wc.getURL())))
}

function createWindow(origin) {
  win = new BrowserWindow({
    width: Number((process.env.PALADIN_SIZE || '').split('x')[0]) || 1440,
    height: Number((process.env.PALADIN_SIZE || '').split('x')[1]) || 920, minWidth: 980, minHeight: 640,
    show: false,
    title: 'Paladin',
    // vibrancy needs a transparent window; the content column paints its own opaque background
    backgroundColor: isMac ? '#00000000' : (nativeTheme.shouldUseDarkColors ? '#1c1c1e' : '#ffffff'),
    titleBarStyle: isMac ? 'hiddenInset' : 'hidden',
    trafficLightPosition: isMac ? { x: 13, y: 12 } : undefined, // centres the controls in the 40pt titlebar row
    titleBarOverlay: isMac ? undefined : { color: '#00000000', symbolColor: '#8e8e93', height: 36 },
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
  if (process.env.PALADIN_E2E) e2e(win, process.env.PALADIN_E2E)
  win.loadURL(origin)
}

// `PALADIN_E2E=desktop/e2e/run.js npm start`: run a script inside the real window and print its results as JSON.
// The script is plain renderer JavaScript that clicks real buttons; nothing is mocked.
function e2e(w, file) {
  w.webContents.once('did-finish-load', async () => {
    try {
      const src = require('node:fs').readFileSync(file, 'utf8')
      const env = JSON.stringify({ REPO: process.env.E2E_REPO || '', BADREPO: process.env.E2E_BADREPO || '', LOG: process.env.E2E_LOG || '' })
      await new Promise((r) => setTimeout(r, 1500))
      const out = await w.webContents.executeJavaScript(`(async () => { const ENV = ${env}; ${src} })()`)
      console.log(`E2E_RESULT ${JSON.stringify(out)}`)
      app.exit(0)
    } catch (e) {
      console.log(`E2E_ERROR ${String(e)}`)
      app.exit(1)
    }
  })
}

// `PALADIN_SMOKE_TEST=1 npm start`: prove the window loads the UI and the backend session works, then exit.
function smokeTest(w) {
  w.webContents.once('did-finish-load', async () => {
    try {
      const r = await w.webContents.executeJavaScript(
        `fetch('/api/config').then(r=>r.json()).then(c=>fetch('/api/me').then(r=>({config:c,me:r.status,bridge:typeof window.paladin,title:document.title})))`)
      console.log('SMOKE', JSON.stringify(r))
      if (process.env.PALADIN_SCREENSHOT) {
        // optional: load a few real log lines, wait for the UI to settle, save a PNG of the window
        if (process.env.PALADIN_NO_INGEST !== '1') await w.webContents.executeJavaScript(`fetch('/api/ingest',{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({format:'linux_auth',lines:['May 14 13:05:11 WEB-BO-01 sshd[912]: Accepted password for www-data from 185.199.110.42 port 51544 ssh2']})})`)
        await new Promise((res) => setTimeout(res, 2000))
        if (process.env.PALADIN_SEED === '1') {   // a few realistic workspaces so list screens can be reviewed
          await w.webContents.executeJavaScript(`(async () => { const post = (u, b) => fetch(u, { method: 'POST',
            headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
            await post('/api/workspaces', { name: 'payments-service', repo_url: 'https://github.com/acme/payments-service' });
            await post('/api/workspaces', { name: 'incident-review' });
            await post('/api/workspaces', { name: 'web-frontend', repo_url: 'https://github.com/acme/web-frontend' }); })()`)
          await new Promise((res) => setTimeout(res, 800))
          await w.webContents.executeJavaScript('location.reload()')
          await new Promise((res) => setTimeout(res, 2200))
        }
        // drive the same path as the menu bar: main -> renderer command channel
        for (const id of (process.env.PALADIN_SCREENSHOT_VIEW || '').split(/\s\|\s|,(?=[a-z-]+(?::|$))/).filter(Boolean)) {
          if (id.startsWith('pane:')) {   // click a Settings category by its label
            await w.webContents.executeJavaScript(`[...document.querySelectorAll('.settings-nav button')]
              .find((b) => b.textContent.includes(${JSON.stringify(id.slice(5))}))?.click()`)
          } else if (id.startsWith('flash:')) {   // click a tab and capture mid-animation
            await w.webContents.executeJavaScript(`[...document.querySelectorAll('[role=tab]')]
              .find((b) => b.textContent.includes(${JSON.stringify(id.slice(6))}))?.click()`)
            // freeze the flash at its peak so the capture is deterministic
            await w.webContents.executeJavaScript(`(() => { const st = document.createElement('style');
              st.textContent = '.seg button.on::after{animation-delay:-.2s!important;animation-play-state:paused!important}' +
                '.seg button.on{animation-delay:-.25s!important;animation-play-state:paused!important}';
              document.head.appendChild(st) })()`)
            await new Promise((res) => setTimeout(res, 120))
            continue
          } else if (id.startsWith('focus:')) {   // focus an element so its selected state renders
            await w.webContents.executeJavaScript(`(() => { const e = document.querySelector(${JSON.stringify(id.slice(6))}); if (!e) return; e.focus(); e.dispatchEvent(new FocusEvent('focusin', { bubbles: true })) })()`)
          } else if (id.startsWith('eval:')) {   // run a snippet in the page (capture helper)
            await w.webContents.executeJavaScript(id.slice(5))
          } else if (id.startsWith('css:')) {   // inject a style (used to freeze an animation for a screenshot)
            await w.webContents.executeJavaScript(`(() => { const st = document.createElement('style'); st.textContent = ${JSON.stringify(id.slice(4))}; document.head.appendChild(st) })()`)
          } else if (id.startsWith('press:')) {   // press a key in the focused element
            await w.webContents.executeJavaScript(`document.activeElement.dispatchEvent(new KeyboardEvent('keydown',
              { key: ${JSON.stringify(id.slice(6))}, bubbles: true }))`)
          } else if (id.startsWith('type:')) {   // type into the start-screen bar to show autocomplete
            await w.webContents.executeJavaScript(`(() => { const i = document.querySelector('.bar input'); i.focus();
              Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(i, ${JSON.stringify(id.slice(5))});
              i.dispatchEvent(new Event('input', { bubbles: true })) })()`)
          } else {
            w.webContents.send('menu:command', { id })
          }
          await new Promise((res) => setTimeout(res, 900))
        }
        const img = await w.webContents.capturePage()
        require('node:fs').writeFileSync(process.env.PALADIN_SCREENSHOT, img.toPNG())
      }
      // signed out on a fresh profile: the engine answers, reports desktop mode and protects /api/me
      app.exit(r.config && r.config.desktop && (r.me === 200 || r.me === 401) ? 0 : 1)
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
  // every handler checks that the call came from our own page; arguments are validated in Settings.set
  const handle = (channel, fn) => ipcMain.handle(channel, (e, ...args) => {
    if (!trusted(e)) throw new Error('untrusted sender')
    return fn(...args)
  })
  handle('app:info', () => ({
    version: app.getVersion(), platform: process.platform, arch: process.arch, packaged: app.isPackaged,
    dataDir: path.join(app.getPath('userData'), 'data'),
  }))
  handle('auth:sign-in', () => startSignIn())
  handle('settings:get', () => settings.status())
  handle('settings:set', async (patch) => {
    settings.set(patch)   // persisted first: the keychain is the source of truth
    try {
      await pushKeys()    // takes effect immediately; no engine restart needed
    } catch {
      try { await new Promise((r) => setTimeout(r, 500)); await pushKeys() } catch {
        throw new Error('Saved, but the analysis engine could not be updated. Restart Paladin to apply it.')
      }
    }
    return settings.status()
  })
  handle('dialog:choose-folder', async () => {
    const r = await dialog.showOpenDialog(win, { title: 'Open a Git repository', properties: ['openDirectory'] })
    return r.canceled || !r.filePaths[0] ? null : r.filePaths[0]
  })
  handle('update:check', () => updater.check())
  handle('update:install', () => updater.install())
  handle('app:open-data', () => shell.openPath(path.join(app.getPath('userData'), 'data')))
}

function buildMenu() {
  Menu.setApplicationMenu(Menu.buildFromTemplate(buildTemplate({
    isMac, isPackaged: app.isPackaged, send: (m) => send('menu:command', m),
  })))
  app.setAboutPanelOptions({ applicationName: 'Paladin', applicationVersion: app.getVersion(), copyright: 'Paladin' })
}

async function boot() {
  const dataRoot = path.join(app.getPath('userData'), 'data')
  settings = new Settings(app.getPath('userData'), safeStorage)
  backend = new Backend({
    command: resolveCommand({ packaged: app.isPackaged, resourcesPath: process.resourcesPath, repoRoot: REPO_ROOT }),
    dataDir: dataRoot,
    version: app.getVersion(),
  })
  backend.on('crash', async ({ code, signal, tail }) => {
    log('backend crashed', code, signal, tail)
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
      pushKeys().catch((e) => log('could not push keys after restart', e.message))
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
  pushKeys().catch((e) => log('could not push keys at startup', e.message)) // the app works without provider keys
  createWindow(backend.origin)
  if (app.isPackaged) setTimeout(() => updater.check(), 5000)
}

// a second launch only quits; booting here too would start a second engine on the same data directory
if (gotLock) app.whenReady().then(boot)
app.on('window-all-closed', () => { if (!isMac) app.quit() })
app.on('activate', () => { if (!win && backend && backend.proc) createWindow(backend.origin) })
let quitting = false
app.on('before-quit', (e) => {
  if (quitting || !backend) return
  e.preventDefault()
  quitting = true
  backend.stop().finally(() => app.quit())
})
