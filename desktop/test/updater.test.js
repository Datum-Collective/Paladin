'use strict'
const test = require('node:test')
const assert = require('node:assert/strict')
const { EventEmitter } = require('node:events')
const { createUpdater } = require('../src/updater')

function harness({ packaged = true, checkImpl, ...opts } = {}) {
  const au = new EventEmitter()
  au.checks = 0
  au.installs = 0
  au.checkForUpdates = async () => { au.checks += 1; if (checkImpl) return checkImpl(au) }
  au.quitAndInstall = () => { au.installs += 1 }
  const sent = []
  const fake = { queue: [], intervals: [] }
  const timers = {
    setTimeout: (fn, ms) => { fake.queue.push({ fn, ms }); return fake.queue.length },
    clearTimeout: () => {},
    setInterval: (fn, ms) => { fake.intervals.push({ fn, ms }); return {} },
    clearInterval: () => {},
  }
  const u = createUpdater({ app: { isPackaged: packaged }, send: (s) => sent.push(s), load: () => ({ autoUpdater: au }), timers,
    releaseUrl: 'https://example.test/releases/latest', ...opts })
  return { u, au, sent, fake }
}

test('does nothing outside a packaged build', async () => {
  const { u, au } = harness({ packaged: false })
  u.start()
  await u.check()
  assert.equal(au.checks, 0)
  assert.equal(u.state().phase, 'disabled')
})

test('start checks once soon after launch and then on an interval', () => {
  const { u, fake } = harness({ firstCheckMs: 111, intervalMs: 222 })
  u.start()
  u.start()                                    // idempotent
  assert.deepEqual(fake.queue.map((q) => q.ms), [111])
  assert.deepEqual(fake.intervals.map((q) => q.ms), [222])
})

test('a finished download restarts into the new version after the delay', () => {
  const { u, au, fake, sent } = harness({ installDelayMs: 4000 })
  au.emit('update-available', { version: '2.0.0' })
  au.emit('download-progress', { percent: 50.4 })
  au.emit('update-downloaded', { version: '2.0.0' })
  assert.equal(u.state().phase, 'installing')
  assert.equal(u.state().version, '2.0.0')
  assert.equal(au.installs, 0)
  const t = fake.queue.find((q) => q.ms === 4000)
  t.fn()
  assert.equal(au.installs, 1)
  assert.ok(sent.some((s) => s.phase === 'downloading' && s.percent === 50))
})

test('autoInstall can be switched off: the update waits for the person', () => {
  const { u, au, fake } = harness({ autoInstall: false })
  au.emit('update-downloaded', { version: '2.0.0' })
  assert.equal(u.state().phase, 'ready')
  assert.equal(fake.queue.length, 0)
  u.install()
  assert.equal(au.installs, 1)
})

test('a failed update carries the download page so the person is never stuck', () => {
  const { u, au } = harness()
  au.emit('error', new Error('code signature did not pass validation'))
  assert.equal(u.state().phase, 'error')
  assert.match(u.state().error, /code signature/)
  assert.equal(u.state().releaseUrl, 'https://example.test/releases/latest')
})

test('a failed restart is reported, not swallowed', () => {
  const { u, au, fake } = harness()
  au.quitAndInstall = () => { throw new Error('cannot swap bundle') }
  au.emit('update-downloaded', { version: '2.0.0' })
  fake.queue[0].fn()
  assert.equal(u.state().phase, 'error')
  assert.match(u.state().error, /cannot swap/)
})

test('checks do not overlap or interrupt a download', async () => {
  const { u, au } = harness()
  au.emit('update-available', { version: '2.0.0' })
  await u.check()
  assert.equal(au.checks, 0)
})
