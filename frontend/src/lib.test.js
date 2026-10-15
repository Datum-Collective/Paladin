import { describe, expect, it } from 'vitest'
import { ago, classifyInput, clamp, filterWorkspaces, folderName, fuzzy, looksLikeRepo, pushRecent, rankCommands, sortWorkspaces, toHistory, workspaceStatus } from './lib.js'

describe('fuzzy', () => {
  it('matches subsequences and rejects non-matches', () => {
    expect(fuzzy('rpo', 'Repository')).toBeGreaterThan(0)
    expect(fuzzy('xyz', 'Repository')).toBe(-1)
  })
  it('prefers prefix and word-start matches', () => {
    expect(fuzzy('rep', 'Repository')).toBeGreaterThan(fuzzy('rep', 'Prepare reply'))
  })
  it('treats an empty query as a match', () => {
    expect(fuzzy('  ', 'anything')).toBe(0)
  })
})

describe('rankCommands', () => {
  const cmds = [
    { id: 'a', title: 'Go to Analysis' }, { id: 'r', title: 'Go to Repository', keywords: 'github scan' },
    { id: 'p', title: 'Play sample scenario' },
  ]
  it('keeps order for an empty query', () => {
    expect(rankCommands(cmds, '').map((c) => c.id)).toEqual(['a', 'r', 'p'])
  })
  it('searches titles and keywords', () => {
    expect(rankCommands(cmds, 'github').map((c) => c.id)).toEqual(['r'])
    expect(rankCommands(cmds, 'play').map((c) => c.id)).toEqual(['p'])
  })
  it('returns nothing when nothing matches', () => {
    expect(rankCommands(cmds, 'zzzz')).toEqual([])
  })
})

describe('clamp / ago', () => {
  it('clamps', () => { expect(clamp(5, 1, 3)).toBe(3); expect(clamp(-1, 0, 3)).toBe(0) })
  it('formats relative times', () => {
    const now = Date.parse('2026-10-14T12:00:00Z')
    expect(ago('2026-10-14T11:59:50Z', now)).toBe('just now')
    expect(ago('2026-10-14T11:30:00Z', now)).toBe('30m ago')
    expect(ago('2026-10-14T06:00:00Z', now)).toBe('6h ago')
    expect(ago('nonsense', now)).toBe('')
  })
})

describe('pushRecent', () => {
  it('puts the newest first, de-duplicates and caps', () => {
    expect(pushRecent(['a', 'b', 'c'], 'c')).toEqual(['c', 'a', 'b'])
    expect(pushRecent(['a', 'b', 'c', 'd', 'e'], 'f')).toEqual(['f', 'a', 'b', 'c', 'd'])
  })
})

describe('toHistory', () => {
  it('drops errored and empty assistant turns and merges consecutive user turns', () => {
    const h = toHistory([
      { role: 'user', content: 'a' }, { role: 'assistant', content: '', error: { kind: 'auth' } },
      { role: 'user', content: 'b' }, { role: 'assistant', content: '' }, { role: 'user', content: 'c' },
    ])
    expect(h).toEqual([{ role: 'user', content: 'a\n\nb\n\nc' }])
  })
  it('keeps a normal alternating conversation untouched', () => {
    const m = [{ role: 'user', content: 'q' }, { role: 'assistant', content: 'a' }, { role: 'user', content: 'q2' }]
    expect(toHistory(m)).toEqual(m)
  })
})

describe('looksLikeRepo', () => {
  it('recognises links and owner/name, rejects prose', () => {
    for (const ok of ['https://github.com/a/b', 'github.com/a/b', 'git@github.com:a/b.git', 'a/b', ' acme/api ']) expect(looksLikeRepo(ok)).toBe(true)
    for (const no of ['', 'hello', 'a b/c', 'https://gitlab.com/a/b', 'one', 'src/main.py', 'docs/readme.md', 'github.com/torvalds', 'a_b/c']) expect(looksLikeRepo(no)).toBe(false)
  })
})

describe('classifyInput', () => {
  it('separates paths, repos, searches and empty', () => {
    expect(classifyInput('')).toBe('empty')
    expect(classifyInput('   ')).toBe('empty')
    expect(classifyInput('/Users/me/code/api')).toBe('path')
    expect(classifyInput('~/code/api')).toBe('path')
    expect(classifyInput('C:\\code\\api')).toBe('path')
    expect(classifyInput('https://github.com/acme/api')).toBe('github')
    expect(classifyInput('acme/api')).toBe('github')
    expect(classifyInput('payments')).toBe('search')
    expect(classifyInput('src/main.py')).toBe('search')
  })
})

describe('workspaceStatus', () => {
  const w = (kind, status, events = 0) => ({ kind, status, events })
  it('never reports a failed or running import as ready', () => {
    expect(workspaceStatus(w('github', { state: 'failed', error: 'clone failed' }))).toMatchObject({ tone: 'bad', label: 'Scan failed', detail: 'clone failed' })
    expect(workspaceStatus(w('github', { state: 'cloning' }))).toMatchObject({ tone: 'info', busy: true })
    expect(workspaceStatus(w('github', { state: 'scanning' }))).toMatchObject({ busy: true })
  })
  it('reports finished, unscanned and empty workspaces', () => {
    expect(workspaceStatus(w('github', { state: 'done' }))).toMatchObject({ tone: 'ok', label: 'Scanned' })
    expect(workspaceStatus(w('github', { state: 'ready' }))).toMatchObject({ label: 'Fixes ready' })
    expect(workspaceStatus(w('local', null))).toMatchObject({ tone: 'warn', label: 'Not scanned' })
    expect(workspaceStatus(w('empty', null, 0))).toMatchObject({ label: 'Empty' })
    expect(workspaceStatus(w('empty', null, 5))).toMatchObject({ label: 'Log data' })
  })
})

describe('filter and sort workspaces', () => {
  const list = [
    { id: 1, name: 'Zeta', kind: 'github', repo_url: 'https://github.com/acme/zeta', events: 2, opened: 10 },
    { id: 2, name: 'alpha', kind: 'empty', repo_url: null, events: 9, opened: 30 },
    { id: 3, name: 'Mid', kind: 'local', repo_url: '/code/mid', events: 0, opened: 20 },
  ]
  it('filters by text and kind', () => {
    expect(filterWorkspaces(list, { q: 'acme' }).map((w) => w.id)).toEqual([1])
    expect(filterWorkspaces(list, { kind: 'local' }).map((w) => w.id)).toEqual([3])
    expect(filterWorkspaces(list, { q: 'MID', kind: 'local' }).map((w) => w.id)).toEqual([3])
    expect(filterWorkspaces(list, {}).length).toBe(3)
  })
  it('sorts by recency, name (case-insensitive) and events without mutating', () => {
    expect(sortWorkspaces(list, 'recent').map((w) => w.id)).toEqual([2, 3, 1])
    expect(sortWorkspaces(list, 'name').map((w) => w.id)).toEqual([2, 3, 1])
    expect(sortWorkspaces(list, 'events').map((w) => w.id)).toEqual([2, 1, 3])
    expect(list.map((w) => w.id)).toEqual([1, 2, 3])
  })
  it('names a folder from its path', () => {
    expect(folderName('/Users/me/code/api/')).toBe('api')
    expect(folderName('C:\\code\\api')).toBe('api')
  })
})
