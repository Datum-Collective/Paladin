import { useEffect, useRef } from 'react'
import cytoscape from 'cytoscape'
import dagre from 'cytoscape-dagre'

cytoscape.use(dagre)

const css = (name, fallback) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback

function theme() {
  const text = css('--text', '#1d1d1f'), muted = css('--text-2', '#5c5c63'), bg = css('--bg-2', '#f5f5f7')
  const line = css('--text-2', '#8e8e93'), bad = css('--bad', '#c4261d'), warn = css('--warn', '#9a5b00')
  const kind = { external: muted, host: css('--info', '#0058b0'), identity: css('--ok', '#1f7a3a'),
    data: bad, secret: warn, role: muted, service: muted }
  return { kind, style: [
    { selector: 'node', style: {
        label: 'data(label)', 'font-size': 11, 'text-wrap': 'wrap', 'text-max-width': 130, 'text-valign': 'bottom',
        'text-margin-y': 6, color: text, 'text-background-color': bg, 'text-background-opacity': 0.9,
        'text-background-padding': 2, 'background-color': 'data(color)', width: 22, height: 22, 'border-width': 0 } },
    { selector: 'edge', style: {
        width: 'mapData(p, 0, 1, 1, 4)', 'line-color': line, 'target-arrow-color': line, 'line-opacity': 0.55,
        'target-arrow-shape': 'triangle', 'curve-style': 'bezier', 'arrow-scale': 0.9, label: 'data(technique)',
        'font-size': 9, color: muted, 'text-rotation': 'autorotate', 'text-background-color': bg,
        'text-background-opacity': 0.9, 'text-background-padding': 2, 'text-margin-y': -6 } },
    { selector: 'edge[?observed]', style: { 'line-color': warn, 'target-arrow-color': warn, 'line-opacity': 1, color: warn } },
    { selector: 'edge[?fixed]', style: { 'line-style': 'dashed', opacity: 0.35 } },
    { selector: '.dim', style: { opacity: 0.18 } },
    { selector: 'edge.hl', style: { 'line-color': bad, 'target-arrow-color': bad, color: bad, width: 4, 'line-opacity': 1,
        opacity: 1, 'z-index': 10 } },
    { selector: 'node.hl', style: { 'border-width': 3, 'border-color': bad, opacity: 1 } },
  ] }
}

export default function Graph({ graph, highlight, onEdge }) {
  const ref = useRef(null)
  const cy = useRef(null)

  useEffect(() => {
    cy.current = cytoscape({ container: ref.current, style: theme().style, minZoom: 0.2, maxZoom: 2.5, wheelSensitivity: 0.3 })
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const onScheme = () => { cy.current.style(theme().style); draw() }
    mq.addEventListener('change', onScheme)
    cy.current.on('tap', 'edge', (e) => onEdge && onEdge(e.target.id()))
    // refit whenever the pane is resized (window, splitter drag, first layout) so the graph never stays tiny
    const ro = new ResizeObserver(() => { if (cy.current) { cy.current.resize(); cy.current.fit(undefined, 40) } })
    ro.observe(ref.current)
    return () => { ro.disconnect(); mq.removeEventListener('change', onScheme); cy.current.destroy() }
  }, [])

  const graphRef = useRef(null)
  graphRef.current = graph

  function draw() {
    const g = graphRef.current
    if (!g || !cy.current) return
    const kind = theme().kind
    const els = [
      ...g.nodes.map((n) => ({ data: { id: n.id, label: n.label, color: kind[n.kind] || kind.service } })),
      ...g.edges.map((e) => ({ data: { id: e.id, source: e.src, target: e.dst, technique: e.technique,
          p: e.p, observed: e.observed, fixed: e.fixed } })),
    ]
    cy.current.elements().remove()
    cy.current.add(els)
    cy.current.layout({ name: 'dagre', rankDir: 'LR', nodeSep: 70, rankSep: 105, edgeSep: 30,
      ranker: 'longest-path', fit: true, padding: 40 }).run()
  }

  useEffect(() => { draw() }, [graph])

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
