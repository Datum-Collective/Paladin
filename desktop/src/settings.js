'use strict'
// Encrypted key store. Secrets are only ever written through the OS keychain-backed safeStorage;
// if that is unavailable we refuse to save rather than fall back to plaintext.
const fs = require('node:fs')
const path = require('node:path')

const FIELDS = { anthropicApiKey: 'ANTHROPIC_API_KEY', openaiApiKey: 'OPENAI_API_KEY', githubToken: 'GITHUB_TOKEN' }
// settings field -> provider id the backend's key store uses
const PROVIDER = { anthropicApiKey: 'anthropic', openaiApiKey: 'openai', githubToken: 'github' }
const MAX_LEN = 512

class Settings {
  constructor(dir, crypto) {
    this.file = path.join(dir, 'settings.json')
    this.crypto = crypto // { isEncryptionAvailable(), encryptString(s)->Buffer, decryptString(Buffer)->s }
  }

  _read() {
    try {
      const raw = JSON.parse(fs.readFileSync(this.file, 'utf8'))
      return raw && typeof raw === 'object' ? raw : {}
    } catch {
      return {}
    }
  }

  /** Booleans only: the renderer must never receive a stored secret. */
  status() {
    const d = this._read()
    return {
      encryptionAvailable: this.crypto.isEncryptionAvailable(),
      anthropicApiKey: Boolean(d.anthropicApiKey),
      openaiApiKey: Boolean(d.openaiApiKey),
      githubToken: Boolean(d.githubToken),
    }
  }

  /** Set a field to a string, or clear it with null / empty string. */
  set(patch) {
    if (!patch || typeof patch !== 'object') throw new Error('invalid settings')
    const d = this._read()
    for (const [k, v] of Object.entries(patch)) {
      if (!Object.hasOwn(FIELDS, k)) throw new Error(`unknown setting: ${k}`)   // not `in`: it matches toString, constructor
      if (v === null || v === '') { delete d[k]; continue }
      if (typeof v !== 'string' || v.length > MAX_LEN || /\s/.test(v)) throw new Error(`invalid value for ${k}`)
      if (!this.crypto.isEncryptionAvailable()) throw new Error('secure storage is unavailable on this system')
      d[k] = this.crypto.encryptString(v).toString('base64')
    }
    fs.mkdirSync(path.dirname(this.file), { recursive: true })
    const tmp = `${this.file}.tmp`
    fs.writeFileSync(tmp, JSON.stringify(d), { mode: 0o600 })
    fs.renameSync(tmp, this.file)
  }

  /** Decrypted keys keyed by provider id, null for unset so the backend clears removed keys. Main process only;
   *  pushed to the backend over loopback with the desktop token, never through env or argv. */
  providerKeys() {
    const env = this.env()
    const out = {}
    for (const [field, envName] of Object.entries(FIELDS)) out[PROVIDER[field]] = env[envName] || null
    return out
  }

  /** Decrypted values as environment-variable names. Main process only. */
  env() {
    const d = this._read()
    const out = {}
    for (const [k, envName] of Object.entries(FIELDS)) {
      if (!d[k]) continue
      try { out[envName] = this.crypto.decryptString(Buffer.from(d[k], 'base64')) } catch { /* unreadable: skip */ }
    }
    return out
  }
}

module.exports = { Settings, FIELDS, PROVIDER }
