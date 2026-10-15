// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
const mocks = vi.hoisted(() => ({ api: {} }))
vi.mock('./api.js', () => ({ api: mocks.api }))
const { default: RepoView } = await import('./RepoView.jsx')

const job = (state, extra = {}) => ({ id: 1, state, repo_url: 'acme/shop', log: [], findings: [], fixes: [], error: '', ...extra })
let host, root, onDone
const wait = (ms) => act(async () => { await new Promise((r) => setTimeout(r, ms)) })
async function paste(v) {
  await type(v)
  await act(async () => { host.querySelector('input').dispatchEvent(new Event('paste', { bubbles: true })) })
  await wait(20)
}
async function type(v) {
  const input = host.querySelector('input')
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, v)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

beforeEach(async () => {
  onDone = vi.fn()
  Object.assign(mocks.api, {
    hConfig: vi.fn(async () => ({ github_enabled: false, ai_enabled: false })),
    hJobs: vi.fn(async () => ({ jobs: [] })),
    hStart: vi.fn(async () => job('cloning')),
    hJob: vi.fn(async () => job('scanning')),
    hCancel: vi.fn(async () => job('cancelled')),
  })
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
  await act(async () => { root.render(<RepoView onDone={onDone} onViewPaths={vi.fn()} />) })
})
afterEach(() => { act(() => root.unmount()); host.remove() })

describe('repository scan', () => {
  it('starts on its own when a repository link is pasted, with no Scan button', async () => {
    expect([...host.querySelectorAll('button')].some((b) => /^Scan$/.test(b.textContent))).toBe(false)
    await paste('https://github.com/acme/shop')
    expect(mocks.api.hStart).toHaveBeenCalledTimes(1)
    expect(mocks.api.hStart).toHaveBeenCalledWith('https://github.com/acme/shop')
    expect(host.textContent).toContain('Fetch repository')
  })

  it('does not scan a half-typed name when the user pauses', async () => {
    await type('https://github.com/facebook/rea')
    await wait(800)
    expect(mocks.api.hStart).not.toHaveBeenCalled()
  })

  it('never starts a second scan for the same submission or while one is running', async () => {
    await paste('https://github.com/acme/shop')
    await paste('https://github.com/acme/shop')
    await paste('https://github.com/acme/other')
    expect(mocks.api.hStart).toHaveBeenCalledTimes(1)
  })

  it('does not start for text that is not a repository', async () => {
    await paste('just some words')
    expect(mocks.api.hStart).not.toHaveBeenCalled()
  })

  it('keeps the scan the user started even if the history fetch answers later', async () => {
    let release
    mocks.api.hJobs.mockImplementation(() => new Promise((r) => { release = () => r({ jobs: [{ id: 9 }] }) }))
    mocks.api.hJob.mockImplementation(async (id) => (id === 9 ? job('ready', { id: 9, repo_url: 'old/repo' }) : job('scanning')))
    act(() => root.unmount())
    root = createRoot(host)
    await act(async () => { root.render(<RepoView onDone={onDone} onViewPaths={vi.fn()} />) })
    await paste('https://github.com/acme/shop')
    await act(async () => { release() })
    await wait(20)
    expect(host.textContent).toContain('acme/shop')
    expect(host.textContent).not.toContain('old/repo')
  })

  it('refreshes the graph when findings are stored and offers a retry after a failure', async () => {
    mocks.api.hJob.mockResolvedValueOnce(job('fixing')).mockResolvedValueOnce(job('failed', { error: 'clone timed out' }))
    await paste('https://github.com/acme/shop')
    await wait(1300)                                   // poll -> fixing: findings are stored, graph refetched
    expect(onDone).toHaveBeenCalled()
    await wait(1300)                                   // poll -> failed
    expect(host.textContent).toContain('clone timed out')
    expect(host.querySelector('.stage.failed').textContent).toContain('Build attack paths')
    const retry = [...host.querySelectorAll('button')].find((b) => b.textContent === 'Try again')
    await act(async () => { retry.click() })
    expect(mocks.api.hStart).toHaveBeenLastCalledWith('https://github.com/acme/shop')
  })

  it('shows where a failed job from history stopped', async () => {
    mocks.api.hJobs.mockResolvedValue({ jobs: [{ id: 5 }] })
    mocks.api.hJob.mockResolvedValue(job('failed', { id: 5, error: 'boom', report: { files_total: 3, scanned: 3, lines_scanned: 90, rules: [], candidates: 0, judged_not_exploitable: 0,
      ai: { enabled: false, review_findings: 0 }, skipped: {}, scanned_files: [], limits: '' } }))
    act(() => root.unmount())
    root = createRoot(host)
    await act(async () => { root.render(<RepoView onDone={onDone} onViewPaths={vi.fn()} />) })
    await wait(20)
    expect(host.querySelector('.stage.failed').textContent).toContain('Find weaknesses')
  })
})
