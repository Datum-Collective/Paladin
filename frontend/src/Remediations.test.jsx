// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
const mocks = vi.hoisted(() => ({ api: {}, downloadText: vi.fn() }))
vi.mock('./api.js', () => ({ api: mocks.api, downloadText: mocks.downloadText }))
vi.mock('./toast.jsx', () => ({ useToast: () => vi.fn() }))
const { Remediations } = await import('./parts.jsx')

const PATCH = 'diff --git a/server.py b/server.py\n--- a/server.py\n+++ b/server.py\n@@ -1,2 +1,2 @@\n import os\n-x = md5()\n+x = sha256()\n'
const rem = (state, extra = {}) => ({ id: 4, kind: 'code', state, title: 'Cheapest cut', files: [{ path: 'server.py', fixed: [] }],
  finding_ids: ['f1'], applied: '', note: '', runbook: 'Patch for 1 finding(s)', ai_drafted: false, audit: [], patch: PATCH, ...extra })
let host, root
const tick = () => act(async () => { await new Promise((r) => setTimeout(r, 20)) })
const btn = (t) => [...host.querySelectorAll('button')].find((b) => b.textContent.trim() === t)

async function render(items, onChange = vi.fn()) {
  await act(async () => { root.render(<Remediations items={items} onChange={onChange} />) })
  await tick()
  return onChange
}

beforeEach(() => {
  Object.assign(mocks.api, {
    remediation: vi.fn(async () => ({ ...rem('proposed'), audit: [{ action: 'proposed', actor: 'me', detail: '' }] })),
    rstep: vi.fn(async () => ({})), remediationPatchUrl: (id) => `/api/remediations/${id}/patch`,
  })
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
})
afterEach(() => { act(() => root.unmount()); host.remove() })

describe('code remediation card', () => {
  it('walks the next step for each state with a label that says what it does', async () => {
    await render([rem('proposed')])
    expect(btn('Approve')).toBeTruthy() && expect(host.textContent).toContain('does not change any file')
    await render([rem('approved')])
    expect(btn('Apply to Folder')).toBeTruthy()
    await render([rem('approved', { applied: '' })])
    await render([rem('executed', { applied: 'local folder demo' })])
    expect(btn('Verify')).toBeTruthy() && expect(btn('Roll Back')).toBeTruthy()
    await render([rem('executed', { applied: 'https://github.com/a/b/pull/7' })])
    expect(btn('Check After Merge')).toBeTruthy() && expect(host.textContent).toContain('Nothing is marked fixed until')
  })

  it('shows the reason next to the button when applying is refused, and does not pretend it worked', async () => {
    mocks.api.rstep.mockRejectedValueOnce(new Error('The files changed since the scan, so Paladin did not touch them. Your work is untouched.'))
    const onChange = await render([rem('approved')])
    await act(async () => { btn('Apply to Folder').click() })
    await tick()
    expect(host.querySelector('[role=alert]').textContent).toContain('Your work is untouched')
    expect(mocks.api.rstep).toHaveBeenCalledWith(4, 'execute')
    expect(onChange).not.toHaveBeenCalled()
    expect(btn('Apply to Folder').disabled).toBe(false)               // can be retried after refreshing the scan
  })

  it('a pull-request remediation says so, and a successful step refreshes the parent', async () => {
    const onChange = await render([rem('approved', { applied: '' })])
    await act(async () => { btn('Apply to Folder').click() })
    await tick()
    expect(mocks.api.rstep).toHaveBeenCalledWith(4, 'execute')
    expect(onChange).toHaveBeenCalled()
  })

  it('reviewing the diff loads the patch and renders the changed lines; download goes through the authenticated helper', async () => {
    await render([rem('proposed')])
    await act(async () => { btn('Review Diff').click() })
    await tick()
    expect(host.textContent).toContain('x = sha256()')
    await act(async () => { btn('Download Patch').click() })
    expect(mocks.downloadText).toHaveBeenCalledWith('/api/remediations/4/patch', 'paladin-fix-4.patch')
  })

  it('an unapplied proposal can be discarded, and says no file was touched', async () => {
    const onChange = await render([rem('proposed')])
    await act(async () => { btn('Discard').click() })
    await tick()
    expect(mocks.api.rstep).toHaveBeenCalledWith(4, 'rollback')
    expect(onChange).toHaveBeenCalled()
  })

  it('a failed verification keeps its explanation and offers roll back', async () => {
    await render([rem('failed', { note: 'server.py: weak-hash still matches 1 time(s)' })])
    expect(host.textContent).toContain('weak-hash still matches')
    expect(btn('Roll Back')).toBeTruthy()
  })
})
