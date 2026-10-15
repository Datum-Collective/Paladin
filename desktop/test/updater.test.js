'use strict'
const test = require('node:test')
const assert = require('node:assert')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { createUpdater, hasUpdateFeed } = require('../src/updater')

test('a packaged build without an update feed never checks (private releases)', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'paladin-upd-'))
  const sent = []
  const u = createUpdater({ app: { isPackaged: true }, send: (s) => sent.push(s), resourcesPath: dir })
  assert.equal(hasUpdateFeed(dir), false)
  assert.equal(u.state().phase, 'disabled')
  assert.equal((await u.check()).phase, 'disabled')
  assert.deepEqual(sent, [], 'no error status is pushed to the window')
})

test('development runs never check for updates', () => {
  const u = createUpdater({ app: { isPackaged: false }, send: () => {} })
  assert.equal(u.state().phase, 'disabled')
})

test('an update feed is detected from app-update.yml', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'paladin-upd-'))
  fs.writeFileSync(path.join(dir, 'app-update.yml'), 'provider: github\n')
  assert.equal(hasUpdateFeed(dir), true)
})
