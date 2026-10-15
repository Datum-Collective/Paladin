'use strict'
const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const http = require('node:http')
const os = require('node:os')
const path = require('node:path')
const { Backend, freePort, waitHealthy, resolveCommand, buildEnv, readSupabaseConfig, openLog } = require('../src/backend')

test('freePort returns a bindable loopback port', async () => {
  const p = await freePort()
  assert.ok(p > 1023 && p < 65536)
})

test('waitHealthy resolves once /health answers 200', async () => {
  const port = await freePort()
  const srv = http.createServer((q, r) => { r.statusCode = q.url === '/health' ? 200 : 404; r.end() })
  setTimeout(() => srv.listen(port, '127.0.0.1'), 250)
  await waitHealthy(port, { timeoutMs: 5000, intervalMs: 50 })
  srv.close()
})

test('waitHealthy fails fast when the process is no longer alive', async () => {
  const port = await freePort()
  await assert.rejects(waitHealthy(port, { timeoutMs: 5000, alive: () => false }), /exited/)
})

test('waitHealthy times out', async () => {
  const port = await freePort()
  await assert.rejects(waitHealthy(port, { timeoutMs: 300, intervalMs: 50 }), /in time/)
})

test('resolveCommand differs for packaged and dev', () => {
  const dev = resolveCommand({ packaged: false, resourcesPath: '/r', repoRoot: '/repo' })
  assert.match(dev.args[0], /desktop_server\.py$/)
  assert.equal(dev.staticDir, path.join('/repo', 'frontend', 'dist'))
  const pkg = resolveCommand({ packaged: true, resourcesPath: '/r', repoRoot: '/repo' })
  assert.deepEqual(pkg.args, [])
  assert.equal(pkg.staticDir, path.join('/r', 'ui'))
  assert.equal(pkg.seedDir, path.join('/r', 'data'))
})

test('buildEnv pins loopback, desktop mode and drops the demo login', () => {
  const env = buildEnv({ base: { DEMO_USER: 'x', PATH: '/bin', ANTHROPIC_API_KEY: 'leak', GITHUB_TOKEN: 'leak2' }, port: 1234, token: 'tok', dataDir: '/d',
                         staticDir: '/s', seedDir: '/e', version: '1.2.3',
                         extra: { GITHUB_TOKEN: 'g' } })
  assert.equal(env.HOST, '127.0.0.1')
  assert.equal(env.PORT, '1234')
  assert.equal(env.DESKTOP_MODE, '1')
  assert.equal(env.APC_DESKTOP_TOKEN, 'tok')
  assert.equal(env.DEMO_USER, '')
  assert.equal(env.APC_PARENT_PID, String(process.pid))
  assert.equal(env.GITHUB_TOKEN, 'g')
  assert.equal(env.PATH, '/bin')
  assert.equal(buildEnv({ base: { ANTHROPIC_API_KEY: 'leak' }, port: 1, token: 't', dataDir: '/d', staticDir: '/s',
                          seedDir: '/e', version: 'v', extra: {} }).ANTHROPIC_API_KEY, undefined)
})

test('buildEnv never passes server secrets to the engine, only the public Supabase settings', () => {
  const env = buildEnv({ base: { SUPABASE_SERVICE_KEY: 'svc', GITHUB_APP_PRIVATE_KEY: 'pem', GITHUB_APP_CLIENT_SECRET: 'cs',
                                 SUPABASE_JWT_SECRET: 'jwt', APP_URL: 'https://x', PATH: '/bin' },
                         port: 1, token: 't', dataDir: '/d', staticDir: '/s', seedDir: '/e', version: 'v', extra: {},
                         supabase: { url: 'https://abc.supabase.co', anonKey: 'sb_publishable_x' } })
  for (const k of ['SUPABASE_SERVICE_KEY', 'GITHUB_APP_PRIVATE_KEY', 'GITHUB_APP_CLIENT_SECRET', 'SUPABASE_JWT_SECRET', 'APP_URL']) {
    assert.equal(env[k], undefined, k)
  }
  assert.equal(env.SUPABASE_URL, 'https://abc.supabase.co')
  assert.equal(env.SUPABASE_ANON_KEY, 'sb_publishable_x')
})

test('readSupabaseConfig accepts a publishable key and refuses a secret one', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'paladin-sb-'))
  const f = path.join(dir, 'supabase.json')
  fs.writeFileSync(f, JSON.stringify({ url: 'https://abc.supabase.co', anonKey: 'sb_publishable_x' }))
  assert.deepEqual(readSupabaseConfig(f), { url: 'https://abc.supabase.co', anonKey: 'sb_publishable_x' })
  fs.writeFileSync(f, JSON.stringify({ url: 'https://abc.supabase.co', anonKey: 'sb_secret_x' }))
  assert.throws(() => readSupabaseConfig(f), /secret key/)
  const legacy = ['x', Buffer.from('{"role":"service_role"}').toString('base64'), 'y'].join('.')
  fs.writeFileSync(f, JSON.stringify({ url: 'https://abc.supabase.co', anonKey: legacy }))
  assert.throws(() => readSupabaseConfig(f), /secret key/)
  fs.writeFileSync(f, JSON.stringify({ url: 'http://evil.example', anonKey: 'k' }))
  assert.equal(readSupabaseConfig(f), null)
  assert.equal(readSupabaseConfig(path.join(dir, 'missing.json')), null)
})

test('Backend fails with a clear error when the binary is missing', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'paladin-be-'))
  const b = new Backend({ command: { cmd: path.join(dir, 'nope'), args: [], cwd: dir, staticDir: dir, seedDir: dir },
                          dataDir: dir, version: 't' })
  await assert.rejects(b.start(), /not found/)
})

test('Backend starts a real child, becomes healthy, and stops it', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'paladin-be-'))
  const script = path.join(dir, 'srv.js')
  fs.writeFileSync(script, `require('http').createServer((q,r)=>{r.statusCode=200;r.end('ok')})
    .listen(Number(process.env.PORT),'127.0.0.1')`)
  const b = new Backend({ command: { cmd: process.execPath, args: [script], cwd: dir, staticDir: dir, seedDir: dir },
                          dataDir: dir, version: 't' })
  await b.start()
  assert.match(b.origin, /^http:\/\/127\.0\.0\.1:\d+$/)
  const pid = b.proc.pid
  await b.stop()
  assert.throws(() => process.kill(pid, 0))
})

test('the engine output is kept in engine.log in the data folder', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'paladin-log-'))
  const script = path.join(dir, 'srv.js')
  fs.writeFileSync(script, `console.error('WARNING sign-in failed: example'); require('http').createServer((q,r)=>{r.end('ok')})
    .listen(Number(process.env.PORT),'127.0.0.1')`)
  const b = new Backend({ command: { cmd: process.execPath, args: [script], cwd: dir, staticDir: dir, seedDir: dir },
                          dataDir: dir, version: 't' })
  await b.start()
  await b.stop()
  await new Promise((r) => setTimeout(r, 100))
  assert.match(fs.readFileSync(path.join(dir, 'engine.log'), 'utf8'), /sign-in failed: example/)
})

test('engine.log is capped and rotated', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'paladin-log-'))
  const file = path.join(dir, 'engine.log')
  fs.writeFileSync(file, 'x'.repeat(1024 * 1024 + 10))
  const log = openLog(file)
  log.write(Buffer.from('fresh line\n'))
  log.end()
  assert.ok(fs.existsSync(`${file}.1`), 'the oversized log is kept as engine.log.1')
  assert.ok(fs.statSync(`${file}.1`).size > 1024 * 1024)
})

test('engine.log replaces the previous rotation and caps a single large write', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'paladin-log-'))
  const file = path.join(dir, 'engine.log')
  fs.writeFileSync(file, 'old current'.padEnd(1024 * 1024 + 1, 'x'))
  fs.writeFileSync(`${file}.1`, 'stale rotation')
  const log = openLog(file)
  log.write(Buffer.alloc(2 * 1024 * 1024, 120))
  log.end()
  await new Promise((r) => setTimeout(r, 50))
  assert.match(fs.readFileSync(`${file}.1`, 'utf8').slice(0, 11), /old current/)
  assert.ok(fs.statSync(file).size <= 1024 * 1024 + 100, 'one write cannot exceed the cap')
})

test('freePort reuses a preferred port when it is free and falls back when busy', async () => {
  const p = await freePort()
  assert.equal(await freePort(p), p)
  const srv = http.createServer().listen(p, '127.0.0.1')
  await new Promise((r) => srv.once('listening', r))
  const q = await freePort(p)
  assert.notEqual(q, p)
  srv.close()
})

test('a child that dies before becoming healthy fails start() without emitting crash', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'paladin-be-'))
  const script = path.join(dir, 'die.js')
  fs.writeFileSync(script, 'process.exit(3)')
  const b = new Backend({ command: { cmd: process.execPath, args: [script], cwd: dir, staticDir: dir, seedDir: dir },
                          dataDir: dir, version: 't' })
  let crashed = false
  b.on('crash', () => { crashed = true })
  await assert.rejects(b.start(), /exited/)
  assert.equal(crashed, false)
})

test('a crash after ready is reported once', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'paladin-be-'))
  const script = path.join(dir, 'srv.js')
  fs.writeFileSync(script, `require('http').createServer((q,r)=>{r.statusCode=200;r.end('ok')})
    .listen(Number(process.env.PORT),'127.0.0.1'); setTimeout(()=>process.exit(5), 1500)`)
  const b = new Backend({ command: { cmd: process.execPath, args: [script], cwd: dir, staticDir: dir, seedDir: dir },
                          dataDir: dir, version: 't' })
  const crash = new Promise((res) => b.once('crash', res))
  await b.start()
  assert.equal((await crash).code, 5)
})

test('buildEnv drops developer switches that would loosen the engine sandbox', () => {
  const env = buildEnv({ base: { APC_ALLOW_LOCAL_TESTS: '1', APC_ALLOW_LOCAL: '1', PATH: '/bin' }, port: 1, token: 't',
                         dataDir: '/d', staticDir: '/s', seedDir: '/e', version: 'v', extra: {} })
  assert.equal(env.APC_ALLOW_LOCAL_TESTS, undefined)
  assert.equal(env.APC_ALLOW_LOCAL, undefined)
  assert.equal(env.DESKTOP_MODE, '1')
})
