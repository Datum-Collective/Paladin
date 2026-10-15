// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
const store = { anthropicApiKey: false, openaiApiKey: false, githubToken: false, encryptionAvailable: true }
const prefsSet = vi.fn(async () => {})
const mocks = vi.hoisted(() => ({ api: {} }))

vi.mock('./api.js', () => ({ api: mocks.api }))
vi.mock('./prefs.jsx', () => ({ usePrefs: () => ({ prefs: { 'assistant.provider': '', 'assistant.model': '' }, set: prefsSet }) }))

const { default: Setup } = await import('./Setup.jsx')

const tick = () => act(async () => { await new Promise((r) => setTimeout(r, 30)) })
let host, root
const q = (sel) => host.querySelector(sel)
const btn = (text) => [...host.querySelectorAll('button')].find((b) => b.textContent.trim().startsWith(text))
const click = async (el) => { await act(async () => { el.click() }); await tick() }
async function typeKey(value) {
  const input = q('#setup-key')
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

beforeEach(async () => {
  localStorage.clear(); prefsSet.mockClear()
  Object.assign(store, { anthropicApiKey: false, openaiApiKey: false })
  window.paladin = {
    getSettings: vi.fn(async () => ({ ...store })),
    setSettings: vi.fn(async (patch) => { for (const [k, v] of Object.entries(patch)) store[k] = Boolean(v); return { ...store } }),
  }
  Object.assign(mocks.api, {
    providers: vi.fn(async () => ({ providers: [{ id: 'anthropic', configured: store.anthropicApiKey }, { id: 'openai', configured: store.openaiApiKey }] })),
    validate: vi.fn(async () => ({ ok: true, models: 2 })),
    models: vi.fn(async () => ({ models: [{ id: 'm-big', name: 'Big' }, { id: 'm-small', name: 'Small' }] })),
    testProvider: vi.fn(async (_p, model) => ({ ok: true, model })),
  })
  host = document.createElement('div'); document.body.append(host)
  root = createRoot(host)
  await act(async () => { root.render(<Setup config={{ desktop: true, providers: {} }} onClose={vi.fn()} onOpenAssistant={vi.fn()} />) })
  await tick()
})
afterEach(() => { act(() => root.unmount()); host.remove(); delete window.paladin })

async function toKeyStep() {
  await click(btn('Continue')); await click(btn('Continue'))   // welcome -> how -> provider
  await click(btn('Continue'))                                  // provider -> key
}

describe('setup flow', () => {
  it('walks to done only after a successful test, then persists provider, model and completion', async () => {
    await toKeyStep()
    expect(q('#setup-key').type).toBe('password')
    await typeKey('sk-ant-api03-' + 'x'.repeat(30))
    await click(btn('Save and check key'))
    expect(window.paladin.setSettings).toHaveBeenCalledWith({ anthropicApiKey: 'sk-ant-api03-' + 'x'.repeat(30) })
    expect(host.textContent).toContain('Pick a model')
    await click(btn('Test connection'))
    expect(mocks.api.testProvider).toHaveBeenCalledWith('anthropic', 'm-big')
    expect(host.textContent).toContain('all set')
    expect(prefsSet).toHaveBeenCalledWith('general.setup_done', true)
    expect(prefsSet).toHaveBeenCalledWith('assistant.model', 'm-big')
  })

  it('refuses a malformed key before any request and offers reveal', async () => {
    await toKeyStep()
    await typeKey('not-a-key')
    expect(host.textContent).toMatch(/start with sk-ant-/)
    expect(btn('Save and check key').disabled).toBe(true)
    await click(q('button[aria-label="Show key"]'))
    expect(q('#setup-key').type).toBe('text')
  })

  it('removes a key the provider rejects and shows its reason', async () => {
    mocks.api.validate.mockResolvedValueOnce({ ok: false, error: { kind: 'auth', message: 'invalid x-api-key', hint: 'Check the key.' } })
    await toKeyStep()
    await typeKey('sk-ant-api03-' + 'y'.repeat(30))
    await click(btn('Save and check key'))
    expect(host.textContent).toContain('invalid x-api-key')
    expect(window.paladin.setSettings).toHaveBeenLastCalledWith({ anthropicApiKey: null })
    expect(host.textContent).not.toContain('Pick a model')
  })

  it('does not mark setup done when the connection test fails, and routes to the right fix', async () => {
    mocks.api.testProvider.mockResolvedValueOnce({ ok: false, error: { kind: 'not_found', message: 'model: m-big', hint: 'Pick another model.' } })
    await toKeyStep()
    await typeKey('sk-ant-api03-' + 'z'.repeat(30))
    await click(btn('Save and check key'))
    await click(btn('Test connection'))
    expect(host.textContent).toContain('model: m-big')
    expect(btn('Choose another model')).toBeTruthy()
    expect(prefsSet).not.toHaveBeenCalledWith('general.setup_done', true)
  })

  it('keeps the existing key when a replacement fails to verify', async () => {
    store.anthropicApiKey = true
    await act(async () => { root.unmount() })
    root = createRoot(host)
    await act(async () => { root.render(<Setup config={{ desktop: true, providers: {} }} onClose={vi.fn()} onOpenAssistant={vi.fn()} />) })
    await tick()
    mocks.api.validate.mockResolvedValueOnce({ ok: false, error: { kind: 'network', message: 'offline', hint: '' } })
    await click(btn('Continue')); await click(btn('Continue')); await click(btn('Continue'))
    await typeKey('sk-ant-api03-' + 'q'.repeat(30))
    await click(btn('Save and check key'))
    expect(host.textContent).toContain('offline')
    expect(window.paladin.setSettings).not.toHaveBeenCalledWith({ anthropicApiKey: null })
  })

  it('closing early records "set up later"', async () => {
    const onClose = vi.fn()
    await act(async () => { root.render(<Setup config={{ desktop: true, providers: {} }} onClose={onClose} onOpenAssistant={vi.fn()} />) })
    await click(btn('Set up later'))
    expect(prefsSet).toHaveBeenCalledWith('general.setup_skipped', true)
    expect(onClose).toHaveBeenCalled()
  })
})

describe('setup flow on the web (no desktop app)', () => {
  async function webKeyStep() {
    await act(async () => { root.unmount() })
    delete window.paladin
    root = createRoot(host)
    await act(async () => { root.render(<Setup config={{ desktop: false, providers: {} }} onClose={vi.fn()} onOpenAssistant={vi.fn()} />) })
    await tick()
    await toKeyStep()
  }

  it('lets the user paste a key, sends it to the server and moves on once it checks out', async () => {
    mocks.api.setKey = vi.fn(async () => ({ ok: true, models: 3 }))
    await webKeyStep()
    expect(q('#setup-key')).toBeTruthy()
    expect(host.textContent).not.toContain('Ask them to add it')
    await typeKey('sk-ant-api03-' + 'w'.repeat(30))
    await click(btn('Save and check key'))
    expect(mocks.api.setKey).toHaveBeenCalledWith('anthropic', 'sk-ant-api03-' + 'w'.repeat(30))
    expect(host.textContent).toContain('Pick a model')
  })

  it('shows the provider\'s reason and stays on the key step when the key is rejected', async () => {
    mocks.api.setKey = vi.fn(async () => ({ ok: false, error: { kind: 'auth', message: 'invalid x-api-key', hint: 'Check the key.' } }))
    await webKeyStep()
    await typeKey('sk-ant-api03-' + 'v'.repeat(30))
    await click(btn('Save and check key'))
    expect(host.textContent).toContain('invalid x-api-key')
    expect(host.textContent).not.toContain('Pick a model')
  })
})

