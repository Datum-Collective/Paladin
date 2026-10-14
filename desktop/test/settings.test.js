'use strict'
const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { Settings } = require('../src/settings')

const fakeCrypto = (available = true) => ({
  isEncryptionAvailable: () => available,
  encryptString: (s) => Buffer.from(`enc:${s}`),
  decryptString: (b) => b.toString().replace(/^enc:/, ''),
})
const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'paladin-settings-'))

test('status never exposes values and starts empty', () => {
  const s = new Settings(tmp(), fakeCrypto())
  assert.deepEqual(s.status(), { encryptionAvailable: true, anthropicApiKey: false, openaiApiKey: false, githubToken: false })
})

test('stored secrets are encrypted at rest and readable as env', () => {
  const dir = tmp()
  const s = new Settings(dir, fakeCrypto())
  s.set({ anthropicApiKey: 'sk-ant-123', githubToken: 'ghp_abc' })
  const onDisk = fs.readFileSync(path.join(dir, 'settings.json'), 'utf8')
  assert.ok(!onDisk.includes('sk-ant-123') && !onDisk.includes('ghp_abc'))
  assert.deepEqual(s.env(), { ANTHROPIC_API_KEY: 'sk-ant-123', GITHUB_TOKEN: 'ghp_abc' })
  assert.equal(s.status().anthropicApiKey, true)
})

test('null or empty clears a field', () => {
  const s = new Settings(tmp(), fakeCrypto())
  s.set({ githubToken: 'ghp_abc' })
  s.set({ githubToken: null })
  assert.deepEqual(s.env(), {})
})

test('refuses to store when secure storage is unavailable', () => {
  const s = new Settings(tmp(), fakeCrypto(false))
  assert.throws(() => s.set({ githubToken: 'ghp_abc' }), /secure storage/)
  assert.equal(fs.existsSync(s.file), false)
})

test('rejects unknown fields, whitespace and oversize values', () => {
  const s = new Settings(tmp(), fakeCrypto())
  assert.throws(() => s.set({ nope: 'x' }), /unknown/)
  assert.throws(() => s.set({ githubToken: 'a b' }), /invalid/)
  assert.throws(() => s.set({ githubToken: 'x'.repeat(513) }), /invalid/)
  assert.throws(() => s.set(null), /invalid/)
})

test('a corrupt settings file reads as empty', () => {
  const dir = tmp()
  fs.writeFileSync(path.join(dir, 'settings.json'), '{not json')
  assert.deepEqual(new Settings(dir, fakeCrypto()).env(), {})
})

test('providerKeys maps fields to provider ids and nulls unset keys', () => {
  const s = new Settings(tmp(), fakeCrypto())
  s.set({ openaiApiKey: 'sk-openai', githubToken: 'ghp_x' })
  assert.deepEqual(s.providerKeys(), { anthropic: null, openai: 'sk-openai', github: 'ghp_x' })
  s.set({ openaiApiKey: null })
  assert.deepEqual(s.providerKeys(), { anthropic: null, openai: null, github: 'ghp_x' })
})
