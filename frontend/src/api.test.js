import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from './api.js'

afterEach(() => { vi.unstubAllGlobals() })

const stubFetch = (status, body) => {
  const f = vi.fn(async () => ({ ok: status < 400, status, json: async () => body }))
  vi.stubGlobal('fetch', f)
  return f
}

describe('api', () => {
  it('sends a pasted web key to the server and can remove it', async () => {
    const f = stubFetch(200, { ok: true })
    await api.setKey('anthropic', 'sk-ant-x')
    expect(f).toHaveBeenLastCalledWith('/api/providers/anthropic/key', expect.objectContaining({ method: 'PUT', body: JSON.stringify({ key: 'sk-ant-x' }) }))
    await api.removeKey('openai')
    expect(f).toHaveBeenLastCalledWith('/api/providers/openai/key', expect.objectContaining({ method: 'DELETE' }))
  })

  it('turns a FastAPI validation list into readable text', async () => {
    stubFetch(422, { detail: [{ msg: 'String should have at most 512 characters' }] })
    await expect(api.setKey('anthropic', 'x')).rejects.toThrow('String should have at most 512 characters')
  })
})
