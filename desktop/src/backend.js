'use strict'
// Owns the bundled FastAPI process: where it lives, how it is started, when it is healthy, restart on crash.
const { spawn } = require('node:child_process')
const crypto = require('node:crypto')
const fs = require('node:fs')
const http = require('node:http')
const net = require('node:net')
const path = require('node:path')
const { EventEmitter } = require('node:events')

const EXE = process.platform === 'win32' ? 'paladin-server.exe' : 'paladin-server'

function freePort(preferred = 0) {
  return new Promise((resolve, reject) => {
    const s = net.createServer()
    s.once('error', (e) => (preferred ? resolve(freePort(0)) : reject(e)))
    s.listen(preferred, '127.0.0.1', () => {
      const { port } = s.address()
      s.close(() => resolve(port))
    })
  })
}

function ping(port, timeoutMs = 800) {
  return new Promise((resolve) => {
    const req = http.get({ host: '127.0.0.1', port, path: '/health', timeout: timeoutMs }, (res) => {
      res.resume()
      resolve(res.statusCode === 200)
    })
    req.on('timeout', () => { req.destroy(); resolve(false) })
    req.on('error', () => resolve(false))
  })
}

async function waitHealthy(port, { timeoutMs = 30000, intervalMs = 150, alive = () => true } = {}) {
  const end = Date.now() + timeoutMs
  while (Date.now() < end) {
    if (!alive()) throw new Error('backend exited before becoming healthy')
    if (await ping(port)) return
    await new Promise((r) => setTimeout(r, intervalMs))
  }
  throw new Error('backend did not become healthy in time')
}

/** Packaged: the frozen binary under resources. Dev: the repo virtualenv running uvicorn via desktop_server.py. */
function resolveCommand({ packaged, resourcesPath, repoRoot }) {
  if (packaged) {
    const dir = path.join(resourcesPath, 'backend')
    return { cmd: path.join(dir, EXE), args: [], cwd: dir, staticDir: path.join(resourcesPath, 'ui'),
             seedDir: path.join(resourcesPath, 'data'), supabaseConfig: path.join(resourcesPath, 'supabase.json') }
  }
  const py = process.platform === 'win32'
    ? path.join(repoRoot, 'backend', '.venv', 'Scripts', 'python.exe')
    : path.join(repoRoot, 'backend', '.venv', 'bin', 'python')
  return { cmd: py, args: [path.join(repoRoot, 'backend', 'desktop_server.py')], cwd: path.join(repoRoot, 'backend'),
           staticDir: path.join(repoRoot, 'frontend', 'dist'), seedDir: path.join(repoRoot, 'data'),
           // dev: optional; without it the engine reads SUPABASE_URL / SUPABASE_ANON_KEY from backend/.env
           supabaseConfig: path.join(repoRoot, 'desktop', 'build', 'supabase.json') }
}

// Server-only secrets that must never reach the engine on a user's machine, even if set in the parent environment
const SERVER_SECRETS = ['SUPABASE_SERVICE_KEY', 'SUPABASE_JWT_SECRET', 'GITHUB_APP_CLIENT_SECRET', 'GITHUB_APP_PRIVATE_KEY',
  'GITHUB_APP_PRIVATE_KEY_PATH', 'GITHUB_APP_ID', 'GITHUB_APP_CLIENT_ID', 'GITHUB_APP_SLUG', 'APP_URL']

/** Public Supabase settings (project URL + anon key) for sign-in and data. A secret key is refused outright. */
function readSupabaseConfig(file) {
  let cfg
  try { cfg = JSON.parse(fs.readFileSync(file, 'utf8')) } catch { return null }
  const url = String(cfg.url || ''), anonKey = String(cfg.anonKey || '')
  if (!/^https:\/\/[a-z0-9-]+\.supabase\.co$/.test(url) || !anonKey) return null
  if (anonKey.startsWith('sb_secret_') || /service_role/.test(Buffer.from(anonKey.split('.')[1] || '', 'base64').toString())) {
    throw new Error('supabase.json holds a secret key; only the publishable (anon) key may ship with the app')
  }
  return { url, anonKey }
}

function buildEnv({ base, port, token, dataDir, staticDir, seedDir, version, extra, supabase }) {
  const { ANTHROPIC_API_KEY, GITHUB_TOKEN, ...rest } = base // keys come only from the Settings store
  const clean = Object.fromEntries(Object.entries(rest).filter(([k]) => !SERVER_SECRETS.includes(k)))
  return {
    ...clean,
    ...extra,
    ...(supabase ? { SUPABASE_URL: supabase.url, SUPABASE_ANON_KEY: supabase.anonKey } : {}),
    HOST: '127.0.0.1',
    PORT: String(port),
    DATA_DIR: dataDir,
    STATIC_DIR: staticDir,
    SEED_DIR: seedDir,
    DESKTOP_MODE: '1',
    APC_DESKTOP_TOKEN: token,
    COOKIE_SECURE: '0',
    APP_VERSION: version,
    // the local account is the only account; keep the shared demo login out of the desktop build
    DEMO_USER: '',
    DEMO_PASSWORD: '',
    PYTHONUNBUFFERED: '1',
    APC_PARENT_PID: String(process.pid),   // the engine exits by itself if this app disappears
  }
}

const LOG_MAX = 1024 * 1024

function openLog(file) {
  try {
    if (fs.statSync(file).size > LOG_MAX) {
      try { fs.rmSync(`${file}.1`, { force: true }) } catch { /* best effort */ }
      fs.renameSync(file, `${file}.1`)
    }
  } catch { /* first run */ }
  let written = 0
  let stream = null
  try { stream = fs.createWriteStream(file, { flags: 'a' }) } catch { /* logging is best effort */ }
  if (stream) {
    stream.on('error', () => { stream = null })
    stream.write(`\n--- engine start ${new Date().toISOString()} ---\n`)
  }
  return {
    write(b) {
      if (!stream || written >= LOG_MAX) return
      const chunk = Buffer.isBuffer(b) ? b : Buffer.from(String(b))
      const limited = chunk.subarray(0, LOG_MAX - written)
      written += limited.length
      stream.write(limited)
    },
    end() { if (stream) stream.end() },
  }
}

class Backend extends EventEmitter {
  constructor(opts) {
    super()
    this.opts = opts // { command, dataDir, version, getExtraEnv() }
    this.token = crypto.randomBytes(32).toString('base64url')
    this.port = null
    this.proc = null
    this.stopping = false
    this.ready = false
    this.crashes = []
  }

  get origin() { return `http://127.0.0.1:${this.port}` }

  async start() {
    this.stopping = false
    const { command, dataDir, version } = this.opts
    fs.mkdirSync(dataDir, { recursive: true })
    const portFile = path.join(dataDir, 'port')
    let want = 0
    try { want = Number(fs.readFileSync(portFile, 'utf8')) || 0 } catch { /* first launch */ }
    this.port = await freePort(want >= 1024 && want < 65536 ? want : 0)
    try { fs.writeFileSync(portFile, String(this.port)) } catch { /* non-fatal */ }
    const env = buildEnv({
      base: process.env, port: this.port, token: this.token, dataDir,
      staticDir: command.staticDir, seedDir: command.seedDir,
      version, extra: this.opts.getExtraEnv ? this.opts.getExtraEnv() : {},
      supabase: command.supabaseConfig ? readSupabaseConfig(command.supabaseConfig) : null,
    })
    if (!fs.existsSync(command.cmd)) throw new Error(`backend not found at ${command.cmd}`)
    const proc = spawn(command.cmd, command.args, { cwd: command.cwd, env, stdio: ['ignore', 'pipe', 'pipe'],
                                                    windowsHide: true })
    this.proc = proc
    let tail = ''
    // The engine's own log (warnings and errors, e.g. why a sign-in failed) goes to <data>/engine.log so it can be
    // read after the fact. One previous file is kept; each is capped at about 1 MB.
    const log = openLog(path.join(dataDir, 'engine.log'))
    const keep = (b) => { tail = (tail + b.toString()).slice(-4000); log.write(b) }
    proc.stdout.on('data', keep)
    proc.stderr.on('data', keep)
    proc.on('exit', (code, signal) => {
      log.end()
      if (this.proc === proc) this.proc = null
      if (this.stopping || !this.ready) return // a failed start is reported by start() itself
      this.ready = false
      this.emit('crash', { code, signal, tail })
    })
    try {
      await waitHealthy(this.port, { alive: () => this.proc === proc })
    } catch (e) {
      const err = new Error(`${e.message}\n${tail}`.trim())
      await this.stop()
      throw err
    }
    this.ready = true
    this.emit('ready', this.origin)
  }

  async stop() {
    this.stopping = true
    this.ready = false
    const p = this.proc
    if (!p) return
    this.proc = null
    await new Promise((resolve) => {
      const t = setTimeout(() => { try { p.kill('SIGKILL') } catch { /* gone */ } resolve() }, 3000)
      p.once('exit', () => { clearTimeout(t); resolve() })
      try { p.kill() } catch { clearTimeout(t); resolve() }
    })
  }

  async restart() {
    await this.stop()
    await this.start()
  }
}

module.exports = { openLog, readSupabaseConfig, SERVER_SECRETS, Backend, freePort, ping, waitHealthy, resolveCommand, buildEnv, EXE }
