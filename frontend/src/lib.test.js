import { describe, expect, it } from 'vitest'
import { scanTarget, scanBanner, normalizeTheme, fromStored, pathLabels, scanStages, groupCommands, keyProblem, setupAdvice, ago, classifyInput, clamp, filterWorkspaces, folderName, fuzzy, looksLikeRepo, pushRecent, rankCommands, sortWorkspaces, toHistory, workspaceStatus, errorText, githubUrl, pathKey } from './lib.js'

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
    expect(workspaceStatus(w('github', { state: 'cancelled' }))).toMatchObject({ tone: 'mute', label: 'Cancelled', busy: false })
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

describe('githubUrl', () => {
  it('only passes https github.com links', () => {
    expect(githubUrl('https://github.com/a/b/pull/1')).toBe('https://github.com/a/b/pull/1')
    for (const bad of ['javascript:alert(1)', 'http://github.com/a/b', 'https://github.com.evil.io/a', 'data:text/html,x', null, undefined, 5]) {
      expect(githubUrl(bad)).toBeUndefined()
    }
  })
})

describe('errorText', () => {
  it('reads strings and FastAPI validation lists, else falls back', () => {
    expect(errorText('nope')).toBe('nope')
    expect(errorText([{ msg: 'ts must be an ISO-8601 timestamp' }, { msg: 'bad' }])).toBe('ts must be an ISO-8601 timestamp; bad')
    expect(errorText([])).toBe('request failed')
    expect(errorText({ a: 1 }, 'x')).toBe('x')
  })
})

describe('keyProblem', () => {
  it('accepts well-formed keys for each provider', () => {
    expect(keyProblem('anthropic', 'sk-ant-api03-' + 'a'.repeat(30))).toBe('')
    expect(keyProblem('openai', 'sk-proj-' + 'b'.repeat(30))).toBe('')
  })
  it('names what is wrong', () => {
    expect(keyProblem('anthropic', '')).toBe('')                      // empty is "not entered yet", not an error
    expect(keyProblem('anthropic', 'sk-' + 'a'.repeat(40))).toMatch(/sk-ant-/)
    expect(keyProblem('openai', 'nope-' + 'a'.repeat(40))).toMatch(/sk-/)
    expect(keyProblem('openai', 'sk-abc')).toMatch(/short/i)
    expect(keyProblem('openai', 'sk-abc def' + 'x'.repeat(30))).toMatch(/space/i)
  })
})

describe('setupAdvice', () => {
  it('sends credential problems back to the key step', () => {
    expect(setupAdvice({ kind: 'auth' }).goto).toBe('key')
    expect(setupAdvice({ kind: 'permission' }).goto).toBe('model')
  })
  it('sends model problems to the model step and transient ones to a retry', () => {
    expect(setupAdvice({ kind: 'not_found' }).goto).toBe('model')
    expect(setupAdvice({ kind: 'rate_limit' })).toMatchObject({ goto: null, retry: true })
    expect(setupAdvice({ kind: 'network' })).toMatchObject({ goto: null, retry: true })
    expect(setupAdvice({ kind: 'quota' })).toMatchObject({ goto: null, retry: false })
  })
  it('falls back to a retry for unknown kinds', () => {
    expect(setupAdvice({ kind: 'weird' }).retry).toBe(true)
    expect(setupAdvice(null).retry).toBe(true)
  })
})

describe('groupCommands', () => {
  it('gathers each group into one contiguous run, keeping first-seen group order and item order', () => {
    const out = groupCommands([
      { id: 'a', group: 'Go to' }, { id: 'b', group: 'Workspaces' }, { id: 'c', group: 'Go to' },
      { id: 'd', group: 'Actions' }, { id: 'e', group: 'Workspaces' },
    ])
    expect(out.map((c) => c.id)).toEqual(['a', 'c', 'b', 'e', 'd'])
  })
  it('is a no-op for an already grouped list', () => {
    const list = [{ id: 'a', group: 'X' }, { id: 'b', group: 'Y' }]
    expect(groupCommands(list)).toEqual(list)
  })
})

describe('pathLabels', () => {
  it('shows node labels instead of internal ids, falling back to the id', () => {
    const nodes = [{ id: 'code:internet', label: 'Internet (any client)' }, { id: 'code:a.py', label: 'a.py' }]
    expect(pathLabels(['code:internet', 'code:a.py', 'x'], nodes)).toEqual(['Internet (any client)', 'a.py', 'x'])
    expect(pathLabels(['x'], null)).toEqual(['x'])
  })
})

describe('scanStages', () => {
  it('marks finished, current and pending stages for each job state', () => {
    const s = (state) => scanStages(state).map((x) => x.status)
    expect(s('queued')).toEqual(['current', 'pending', 'pending', 'pending'])
    expect(s('cloning')).toEqual(['current', 'pending', 'pending', 'pending'])
    expect(s('scanning')).toEqual(['done', 'current', 'pending', 'pending'])
    expect(s('fixing')).toEqual(['done', 'done', 'current', 'pending'])
    expect(s('ready')).toEqual(['done', 'done', 'done', 'done'])
    expect(s('done')).toEqual(['done', 'done', 'done', 'done'])
  })
  it('marks the stage that was running when a scan failed', () => {
    expect(scanStages('failed', 'scanning').map((x) => x.status)).toEqual(['done', 'failed', 'pending', 'pending'])
  })
})

describe('fromStored', () => {
  it('keeps the text of failed, stopped and cut-off replies and labels them', () => {
    expect(fromStored({ id: 1, role: 'assistant', content: 'partial', status: 'interrupted', meta: {} }).interrupted).toBe(true)
    expect(fromStored({ id: 2, role: 'assistant', content: '', status: 'error', meta: { error: { kind: 'auth', message: 'bad key' } } }).error.kind).toBe('auth')
    const ok = fromStored({ id: 3, role: 'assistant', content: 'hi', status: 'complete', meta: { stop_reason: 'end_turn', usage: { input: 1, output: 2 } } })
    expect(ok).toMatchObject({ content: 'hi', stop: 'end_turn', usage: { output: 2 }, stopped: false, interrupted: false })
    expect(ok.error).toBeUndefined()
  })
})

describe('normalizeTheme', () => {
  it('keeps the three known choices and falls back to following the system', () => {
    expect(['system', 'light', 'dark'].map(normalizeTheme)).toEqual(['system', 'light', 'dark'])
    for (const bad of ['', 'solarized', null, undefined, 3]) expect(normalizeTheme(bad)).toBe('system')
  })
})

describe('scanBanner', () => {
  const job = (state, extra = {}) => ({ state, repo_url: 'acme/shop', error: '', updated: Date.now() / 1000, ...extra })
  it('says what is happening and how much has arrived while a scan runs', () => {
    expect(scanBanner(job('cloning'), 0)).toMatchObject({ busy: true, text: expect.stringContaining('Fetching acme/shop') })
    const b = scanBanner(job('scanning'), 3)
    expect(b.busy).toBe(true)
    expect(b.text).toContain('3 attack paths so far')
    expect(scanBanner(job('scanning'), 1).text).toContain('1 attack path so far')
  })
  it('keeps what was found when a scan fails or is cancelled, and says why', () => {
    const f = scanBanner(job('failed', { error: 'clone timed out' }), 2)
    expect(f).toMatchObject({ busy: false, tone: 'bad' })
    expect(f.text).toContain('clone timed out')
    expect(f.text).toContain('2 attack paths found before it stopped')
    expect(scanBanner(job('cancelled'), 0).text).toBe('The scan of acme/shop was cancelled.')
    expect(f.action).toBe('rescan')
  })
  it('stays quiet when nothing is running, and for old failures', () => {
    expect(scanBanner(null)).toBeNull()
    expect(scanBanner(job('ready'), 4)).toBeNull()
    expect(scanBanner(job('done'), 0)).toBeNull()
    expect(scanBanner(job('failed', { updated: Date.now() / 1000 - 7200 }), 0)).toBeNull()
  })
  it('shortens a local folder path to the last two segments', () => {
    expect(scanBanner(job('scanning', { repo_url: '/Users/me/code/shop' }), 0).text).toContain('code/shop')
  })
})

describe('a scan cut off by closing the app', () => {
  const interrupted = (paths, ageS = 86400 * 3) => scanBanner({ state: 'failed', repo_url: 'acme/shop', updated: Date.now() / 1000 - ageS,
    error: 'Interrupted: the app closed before this scan finished. Retry to run it again.' }, paths)
  it('is always mentioned, however long ago, keeps the saved paths and offers to scan again', () => {
    const b = interrupted(3)
    expect(b).toMatchObject({ busy: false, tone: 'warn', action: 'rescan' })
    expect(b.text).toContain('interrupted when Paladin closed')
    expect(b.text).toContain('3 attack paths found before it stopped')
    expect(interrupted(0).text).toContain('Nothing had been found yet')
  })
})

describe('scanTarget', () => {
  it('turns a stored owner/name back into a GitHub address and leaves paths alone', () => {
    expect(scanTarget('acme/shop')).toBe('https://github.com/acme/shop')
    expect(scanTarget('/Users/me/code/shop')).toBe('/Users/me/code/shop')
    expect(scanTarget('C:\\code\\shop')).toBe('C:\\code\\shop')
  })
})

describe('pathKey', () => {
  it('stays the same when a path moves in the ranking', () => {
    const hops = [{ edge: 'e1' }, { edge: 'e7' }]
    expect(pathKey({ id: 'p1', hops })).toBe(pathKey({ id: 'p4', hops }))
  })
  it('differs between paths over different edges', () => {
    expect(pathKey({ id: 'p1', hops: [{ edge: 'e1' }] })).not.toBe(pathKey({ id: 'p1', hops: [{ edge: 'e2' }] }))
  })
  it('falls back to the id when there are no hops', () => {
    expect(pathKey({ id: 'p3', hops: [] })).toBe('p3')
    expect(pathKey(undefined)).toBe(null)
  })
})
