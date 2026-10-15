import { describe, expect, it } from 'vitest'
import { categoryDistribution, componentRisk, findingCategory, mitreMappings, remediationOutcome } from './Insights.jsx'

describe('Insights analytics aggregation', () => {
  it('uses the scanner rule taxonomy for categories and leaves unknown rules visible as Other', () => {
    expect(findingCategory({ rule: 'sql-concat' })).toBe('Input validation')
    expect(findingCategory({ rule: 'ai-authentication' })).toBe('Authentication')
    expect(findingCategory({ rule: 'unknown-rule' })).toBe('Other')
    const rows = categoryDistribution([{ rule: 'sql-concat', file: 'api.py', title: 'SQL built from strings' }, { rule: 'sql-concat', file: 'api.py', title: 'SQL built from strings' }, { rule: 'hardcoded-secret', file: 'env.py', title: 'Hard-coded credential' }])
    expect(rows[0]).toMatchObject({ category: 'Input validation', count: 2 })
  })

  it('attributes ranked-path risk to actual component nodes', () => {
    const graph = { nodes: [{ id: 'code:api.py', kind: 'component', label: 'api.py' }, { id: 'asset', kind: 'data', label: 'Database' }] }
    const rows = componentRisk(graph, [{ nodes: ['code:api.py', 'asset'], risk: 0.8 }, { nodes: ['code:api.py'], risk: 0.3 }])
    expect(rows).toEqual([expect.objectContaining({ id: 'code:api.py', risk: 1.1, paths: 2 })])
  })

  it('keeps mapped findings distinct from confirmed observations and only sums recorded verified changes', () => {
    expect(mitreMappings([{ technique: 'T1190', status: 'confirmed', file: 'api.py' }, { technique: 'T1190', status: 'potential', file: 'web.py' }])[0]).toMatchObject({ count: 2, confirmed: 1 })
    expect(remediationOutcome([{ state: 'verified', risk_before: 2, risk_after: 0.5 }, { state: 'executed', risk_before: 1, risk_after: 0.2 }])).toMatchObject({ verified: 1, directRiskChange: 1.5 })
  })
})
