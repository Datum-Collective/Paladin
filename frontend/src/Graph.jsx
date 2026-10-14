import { useEffect, useRef } from 'react'
import cytoscape from 'cytoscape'
import dagre from 'cytoscape-dagre'

cytoscape.use(dagre)

const KIND_COLOR = {
  external: '#8b5cf6', host: '#3b82f6', identity: '#0ea5a4', data: '#dc2626',
  secret: '#d97706', role: '#64748b', service: '#64748b',
}

const STYLE = [
  { selector: 'node', style: {
      label: 'data(label)', 'font-size': 11, 'text-wrap': 'wrap', 'text-max-width': 120,
      'text-valign': 'bottom', 'text-margin-y': 6, color: '#cbd5e1',
      'text-background-color': '#0f172a', 'text-background-opacity': 0.75, 'text-background-padding': 2,
      'background-color': 'data(color)', width: 24, height: 24, 'border-width': 0 } },
  { selector: 'edge', style: {
      width: 'mapData(p, 0, 1, 1, 4)', 'line-color': '#475569', 'target-arrow-color': '#475569',
      'target-arrow-shape': 'triangle', 'curve-style': 'bezier', 'arrow-scale': 0.9,
      label: 'data(technique)', 'font-size': 9, color: '#94a3b8', 'text-rotation': 'autorotate',
      'text-background-color': '#0f172a', 'text-background-opacity': 0.85, 'text-background-padding': 2,
      'text-margin-y': -6 } },
  { selector: 'edge[?observed]', style: { 'line-color': '#f59e0b', 'target-arrow-color': '#f59e0b', color: '#f59e0b' } },
  { selector: 'edge[?fixed]', style: { 'line-style': 'dashed', opacity: 0.35 } },
  { selector: '.dim', style: { opacity: 0.18 } },
  { selector: 'edge.hl', style: { 'line-color': '#ef4444', 'target-arrow-color': '#ef4444', color: '#fca5a5',
      width: 4, opacity: 1, 'z-index': 10 } },
  { selector: 'node.hl', style: { 'border-width': 3, 'border-color': '#ef4444', opacity: 1, color: '#fecaca' } },
]

export default function Graph({ graph, highlight, onEdge }) {
  const ref = useRef(null)
  const cy = useRef(null)

  useEffect(() => {
    cy.current = cytoscape({ container: ref.current, style: STYLE, minZoom: 0.2, maxZoom: 2.5, wheelSensitivity: 0.3 })
    cy.current.on('tap', 'edge', (e) => onEdge && onEdge(e.target.id()))
    return () => cy.current.destroy()
  }, [])

  useEffect(() => {
    if (!graph || !cy.current) return
    const els = [
      ...graph.nodes.map((n) => ({ data: { id: n.id, label: n.label, color: KIND_COLOR[n.kind] || '#64748b' } })),
      ...graph.edges.map((e) => ({ data: { id: e.id, source: e.src, target: e.dst, technique: e.technique,
          p: e.p, observed: e.observed, fixed: e.fixed } })),
    ]
    cy.current.elements().remove()
    cy.current.add(els)
    cy.current.layout({ name: 'dagre', rankDir: 'LR', nodeSep: 60, rankSep: 170, edgeSep: 30,
      ranker: 'longest-path', fit: true, padding: 40 }).run()
  }, [graph])

  useEffect(() => {
    if (!cy.current) return
    const c = cy.current
    c.elements().removeClass('hl dim')
    if (highlight) {
      c.elements().addClass('dim')
      highlight.edges.forEach((id) => c.getElementById(id).removeClass('dim').addClass('hl'))
      highlight.nodes.forEach((id) => c.getElementById(id).removeClass('dim').addClass('hl'))
    }
  }, [highlight, graph])

  return <div ref={ref} className="graph" />
}
