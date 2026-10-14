import { useEffect, useRef } from 'react'
import cytoscape from 'cytoscape'
import dagre from 'cytoscape-dagre'

cytoscape.use(dagre)

const KIND_COLOR = {
  external: '#8b5cf6', host: '#3b82f6', identity: '#0ea5a4', data: '#dc2626',
  secret: '#d97706', role: '#64748b', service: '#64748b',
}

export default function Graph({ graph, highlight, onEdge }) {
  const ref = useRef(null)
  const cy = useRef(null)

  useEffect(() => {
    cy.current = cytoscape({
      container: ref.current,
      style: [
        { selector: 'node', style: {
            label: 'data(label)', 'font-size': 10, 'text-wrap': 'wrap', 'text-max-width': 90,
            'text-valign': 'bottom', 'text-margin-y': 4, color: '#94a3b8',
            'background-color': 'data(color)', width: 26, height: 26 } },
        { selector: 'edge', style: {
            width: 'mapData(p, 0, 1, 1, 5)', 'line-color': '#475569', 'target-arrow-color': '#475569',
            'target-arrow-shape': 'triangle', 'curve-style': 'bezier', label: 'data(technique)',
            'font-size': 9, color: '#64748b' } },
        { selector: 'edge[?observed]', style: { 'line-color': '#f59e0b', 'target-arrow-color': '#f59e0b', color: '#f59e0b' } },
        { selector: 'edge[?fixed]', style: { 'line-style': 'dashed', opacity: 0.35 } },
        { selector: '.hl', style: { 'line-color': '#ef4444', 'target-arrow-color': '#ef4444', color: '#ef4444', opacity: 1 } },
        { selector: 'node.hl', style: { 'border-width': 3, 'border-color': '#ef4444' } },
      ],
    })
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
    cy.current.layout({ name: 'dagre', rankDir: 'LR', nodeSep: 30, rankSep: 80 }).run()
  }, [graph])

  useEffect(() => {
    if (!cy.current) return
    cy.current.elements().removeClass('hl')
    if (highlight) {
      highlight.edges.forEach((id) => cy.current.getElementById(id).addClass('hl'))
      highlight.nodes.forEach((id) => cy.current.getElementById(id).addClass('hl'))
    }
  }, [highlight, graph])

  return <div ref={ref} className="graph" />
}
