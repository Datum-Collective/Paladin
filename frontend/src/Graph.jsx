import { useEffect, useRef } from 'react'
import cytoscape from 'cytoscape'
import dagre from 'cytoscape-dagre'
import { KIND_LABEL } from './kinds.js'

cytoscape.use(dagre)

// node kind is encoded by shape as well as colour, so the graph reads without colour vision
const SHAPE = { external: 'diamond', identity: 'ellipse', host: 'round-rectangle', role: 'hexagon', secret: 'octagon',
  data: 'star', service: 'round-tag', component: 'round-rectangle', weakness: 'round-triangle' }


const css = (name, fallback) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback

function theme() {
  const text = css('--text', '#1d1d1f'), muted = css('--text-2', '#5c5c63'), bg = css('--bg-2', '#f5f5f7')
  const line = css('--text-2', '#8e8e93'), bad = css('--bad', '#c4261d'), warn = css('--warn', '#9a5b00')
  const kind = { external: muted, host: css('--info', '#0058b0'), identity: css('--ok', '#1f7a3a'),
    data: bad, secret: warn, role: muted, service: muted, component: css('--info', '#0058b0'), weakness: warn }
  const ink = css('--text', '#1d1d1f'), accent = css('--accent', '#0a62c9')
  return { kind, style: [
    { selector: 'node', style: {
        label: 'data(label)', 'font-size': 11, 'text-wrap': 'wrap', 'text-max-width': 130, 'text-valign': 'bottom',
        'text-margin-y': 6, color: text, 'text-background-color': bg, 'text-background-opacity': 0.9,
        'text-background-padding': 2, 'background-color': 'data(color)', width: 24, height: 24, 'border-width': 0 } },
    { selector: 'node[shape]', style: { shape: 'data(shape)' } },
    { selector: 'edge', style: {
        width: 'mapData(p, 0, 1, 1, 4)', 'line-color': line, 'target-arrow-color': line, 'line-opacity': 0.55,
        'target-arrow-shape': 'triangle', 'curve-style': 'bezier', 'arrow-scale': 0.9, label: 'data(technique)',
        'font-size': 9, color: muted, 'text-rotation': 'autorotate', 'text-background-color': bg,
        'text-background-opacity': 0.9, 'text-background-padding': 2, 'text-margin-y': -6 } },
    { selector: 'edge[?observed]', style: { 'line-color': warn, 'target-arrow-color': warn, 'line-opacity': 1, color: warn } },
    { selector: 'edge[basis = "assumed"]', style: { 'line-style': 'dashed' } },
    { selector: 'edge[?fixed]', style: { 'line-style': 'dotted', opacity: 0.35 } },
    { selector: ':selected', style: { 'overlay-color': accent, 'overlay-opacity': 0.18, 'overlay-padding': 6 } },
    { selector: 'node:selected', style: { 'border-width': 2, 'border-color': ink } },
    { selector: 'edge:selected', style: { width: 4, 'line-color': ink, 'target-arrow-color': ink, 'line-opacity': 1 } },
    { selector: '.dim', style: { opacity: 0.18 } },
    { selector: 'edge.hl', style: { 'line-color': bad, 'target-arrow-color': bad, color: bad, width: 4, 'line-opacity': 1,
        opacity: 1, 'z-index': 10 } },
    { selector: 'node.hl', style: { 'border-width': 3, 'border-color': bad, opacity: 1 } },
  ] }
}

export default function Graph({ graph, highlight, selected, onNode, onEdge, onClear, showLabels = true }) {
  const ref = useRef(null)
  const cy = useRef(null)
  const cb = useRef({})
  const orient = useRef('LR')
  cb.current = { onNode, onEdge, onClear }

  useEffect(() => {
    cy.current = cytoscape({ container: ref.current, style: theme().style, minZoom: 0.2, maxZoom: 2.5, wheelSensitivity: 0.3 })
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const onScheme = () => { cy.current.style(theme().style); draw() }
    mq.addEventListener('change', onScheme)
    const mo = new MutationObserver(onScheme)        // the Theme setting changes data-theme on <html>
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    cy.current.on('tap', 'edge', (e) => cb.current.onEdge && cb.current.onEdge(e.target.id()))
    cy.current.on('tap', 'node', (e) => cb.current.onNode && cb.current.onNode(e.target.id()))
    cy.current.on('tap', (e) => { if (e.target === cy.current && cb.current.onClear) cb.current.onClear() })
    // refit whenever the pane is resized (window, splitter drag, first layout) so the graph never stays tiny
    const ro = new ResizeObserver(() => {
      if (!cy.current) return
      cy.current.resize()
      const el = ref.current
      const want = el && el.clientHeight > el.clientWidth * 1.15 ? 'TB' : 'LR'
      if (want !== orient.current) draw()            // the pane changed shape: lay it out the other way
      else cy.current.fit(undefined, 40)
    })
    ro.observe(ref.current)
    return () => { ro.disconnect(); mo.disconnect(); mq.removeEventListener('change', onScheme); cy.current.destroy() }
  }, [])

  const graphRef = useRef(null)
  graphRef.current = graph
  const showLabelsRef = useRef(showLabels)
  showLabelsRef.current = showLabels

  const shown = useRef('')

  function draw() {
    const g = graphRef.current
    if (!g || !cy.current) return
    const c = cy.current
    const kind = theme().kind
    // Cytoscape throws on an edge whose endpoint is missing, and a throw here unmounted the whole app (blank
    // window). The API drops such edges too; this keeps the canvas alive if one ever arrives anyway.
    const ids = new Set()
    const nodes = (g.nodes || []).filter((n) => n && n.id != null && !ids.has(n.id) && ids.add(n.id))
    const seen = new Set()
    const edges = (g.edges || []).filter((e) => e && ids.has(e.src) && ids.has(e.dst) && !seen.has(e.id) && seen.add(e.id))
    const els = [
      ...nodes.map((n) => ({ data: { id: n.id, label: showLabelsRef.current ? n.label : '', color: kind[n.kind] || kind.service,
                                     shape: SHAPE[n.kind] || 'round-rectangle' } })),
      ...edges.map((e) => ({ data: { id: e.id, source: e.src, target: e.dst, technique: e.technique,
          p: e.p, observed: e.observed, fixed: e.fixed, basis: e.basis || '' } })),
    ]
    // a tall, narrow pane reads better top to bottom; a wide one left to right (the attack direction either way)
    const el = ref.current
    const tall = el && el.clientHeight > el.clientWidth * 1.15
    const want = tall ? 'TB' : 'LR'
    const sig = want + '#' + [...ids].sort().join('|') + '#' + edges.map((e) => `${e.id}>${e.src}>${e.dst}`).sort().join('|')
    const same = sig === shown.current && c.elements().length === els.length
    if (same) {   // same structure (status, label or theme change): update in place so pan and zoom stay put
      c.batch(() => els.forEach((x) => { const n = c.getElementById(x.data.id); if (n.nonempty()) n.data(x.data) }))
      return
    }
    c.elements().remove()
    c.add(els)
    orient.current = want
    c.layout({ name: 'dagre', rankDir: want, nodeSep: tall ? 110 : 56, rankSep: tall ? 70 : 84, edgeSep: 30,
      ranker: 'longest-path', fit: true, padding: 40 }).run()
    shown.current = sig
  }

  useEffect(() => { draw() }, [graph, showLabels])

  useEffect(() => {
    const c = cy.current
    if (!c) return
    c.elements().unselect()
    if (selected) c.getElementById(selected.id).select()
  }, [selected, graph])

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

  const zoom = (f) => { const c = cy.current; if (c) c.zoom({ level: c.zoom() * f, renderedPosition: { x: c.width() / 2, y: c.height() / 2 } }) }
  const fit = () => { const c = cy.current; if (c) c.fit(highlight ? c.elements('.hl') : undefined, 40) }
  const kinds = [...new Set((graph ? graph.nodes : []).map((n) => n.kind))]
  const assumed = (graph ? graph.edges : []).some((e) => e.basis === 'assumed')
  return (
    <div className="graph-wrap">
      <div ref={ref} className="graph" />
      <div className="graph-tools" role="toolbar" aria-label="Graph view">
        <button className="tool" onClick={() => zoom(1.25)} aria-label="Zoom in" title="Zoom in">+</button>
        <button className="tool" onClick={() => zoom(0.8)} aria-label="Zoom out" title="Zoom out">−</button>
        <button className="tool" onClick={fit} aria-label={highlight ? 'Fit the selected path' : 'Fit the whole graph'}
                title={highlight ? 'Fit the selected path' : 'Fit to view'}>Fit</button>
      </div>
      {kinds.length > 0 && (
        <ul className="graph-legend" aria-label="Legend">
          {kinds.map((k) => <li key={k}><i className={`lg lg-${k}`} aria-hidden="true" />{KIND_LABEL[k] || k}</li>)}
          {assumed && <li><i className="lg-dash" aria-hidden="true" />Assumed step (not verified)</li>}
        </ul>
      )}
    </div>
  )
}
