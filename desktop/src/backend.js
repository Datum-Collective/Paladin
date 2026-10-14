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
             seedDir: path.join(resourcesPath, 'data') }
  }
  const py = process.platform === 'win32'
    ? path.join(repoRoot, 'backend', '.venv', 'Scripts', 'python.exe')
    : path.join(repoRoot, 'backend', '.venv', 'bin', 'python')
  return { cmd: py, args: [path.join(repoRoot, 'backend', 'desktop_server.py')], cwd: path.join(repoRoot, 'backend'),
           staticDir: path.join(repoRoot, 'frontend', 'dist'), seedDir: path.join(repoRoot, 'data') }
}

function buildEnv({ base, port, token, dataDir, staticDir, seedDir, version, extra }) {
  const { ANTHROPIC_API_KEY, GITHUB_TOKEN, ...clean } = base // keys come only from the Settings store
  return {
    ...clean,
    ...extra,
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
    })
    if (!fs.existsSync(command.cmd)) throw new Error(`backend not found at ${command.cmd}`)
    const proc = spawn(command.cmd, command.args, { cwd: command.cwd, env, stdio: ['ignore', 'pipe', 'pipe'],
                                                    windowsHide: true })
    this.proc = proc
    let tail = ''
    const keep = (b) => { tail = (tail + b.toString()).slice(-4000) }
    proc.stdout.on('data', keep)
    proc.stderr.on('data', keep)
    proc.on('exit', (code, signal) => {
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

module.exports = { Backend, freePort, ping, waitHealthy, resolveCommand, buildEnv, EXE }
