import { describe, expect, it } from 'vitest'
import { ago, clamp, fuzzy, pushRecent, rankCommands, toHistory } from './lib.js'

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
