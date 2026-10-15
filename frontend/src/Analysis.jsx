import { useEffect, useRef, useState } from 'react'
import Graph from './Graph.jsx'
import GraphBoundary from './GraphBoundary.jsx'
import Resizer from './Resizer.jsx'
import { useStored } from './useStored.js'
import { usePrefs } from './prefs.jsx'
import { Tabs } from './ui.jsx'
import { api } from './api.js'
import { pathLabels, scanBanner, scanTarget } from './lib.js'
import { ElementDetail, Empty, Events, Fixes, Ingest, PathDetail, Remediations, Severity } from './parts.jsx'

/** One line above the panes while a scan runs (or after it failed): what it is doing and how much has arrived. */
function ScanBanner({ scan, paths, onRescan }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const b = scanBanner(scan, paths)
  if (!b) return null
  const again = async () => {
    setBusy(true); setErr('')
    try { await api.hStart(scanTarget(scan.repo_url)); await onRescan() } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  return (
    <div className={`scan-banner ${b.tone}`} role="status" aria-live="polite">
      {b.busy && <span className="spinner tiny" aria-hidden="true" />}
      <span>{b.text}{err ? ` ${err}` : ''}</span>
      {b.action === 'rescan' && <button className="small-btn" disabled={busy} onClick={again}>{busy ? 'Starting…' : 'Scan Again'}</button>}
    </div>
  )
}

export default function Analysis({ state, selected, setSelected, tab, setTab, go, desktop, inspectorOpen = true }) {
  const { graph, paths, fixes, events, rems, empty, canPlay, play, refresh, propose, scan } = state
  const [left, setLeft] = useStored('w-left', 280)
  const [right, setRight] = useStored('w-right', 360)
  const [inspect, setInspect] = useStored('inspector', 'path')
  const { prefs } = usePrefs()
  const root = useRef(null)
  const [width, setWidth] = useState(1200)
  useEffect(() => {
    const ro = new ResizeObserver(([e]) => setWidth(e.contentRect.width))
    if (root.current) ro.observe(root.current)
    return () => ro.disconnect()
  }, [])
  // never let the side panes take more than ~60% of the window, so the graph stays usable at the minimum size
  const leftW = Math.round(Math.min(left, width * 0.3))
  const rightW = inspectorOpen ? Math.round(Math.min(right, width * 0.34)) : 0
  const sel = paths.find((p) => p.id === selected)
  const [el, setEl] = useState(null)               // a clicked node or edge in the graph
  const pending = rems.filter((r) => !['verified', 'rolled_back'].includes(r.state)).length

  return (
    <main className="analysis" ref={root} style={{ gridTemplateColumns: `${leftW}px 1fr ${rightW}px` }}>
      <ScanBanner scan={scan} paths={paths.length} onRescan={refresh} />
      <section className="pane left" aria-label="Paths, events and data">
        <Tabs label="Paths, events and data" value={tab} onChange={setTab}
              tabs={[{ id: 'paths', label: 'Paths', count: paths.length }, { id: 'events', label: 'Events' }, { id: 'ingest', label: 'Import' }]} />
        {tab === 'paths' && (paths.length === 0 ? <p className="muted">No paths yet.</p> : (
          <ul className="rows selectable" role="listbox" aria-label="Attack paths">
            {paths.map((p) => (
              <li key={p.id} role="option" aria-selected={p.id === selected} tabIndex={0}
                  className={p.id === selected ? 'on' : ''} onClick={() => setSelected(p.id)}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelected(p.id) } }}>
                <div className="row-top"><Severity level={p.severity} /><span className="muted">{p.risk.toFixed(3)}</span></div>
                <div className="path-line">{pathLabels(p.nodes, graph && graph.nodes).join(' → ')}</div>
              </li>
            ))}
          </ul>
        ))}
        {tab === 'events' && <Events data={events} />}
        {tab === 'ingest' && <Ingest onDone={refresh} desktop={desktop} />}
      </section>
      <Resizer side="left" value={leftW} min={200} max={480} onChange={setLeft} label="Resize paths column" />

      <section className="canvas" aria-label="Attack graph">
        {empty ? <Empty canPlay={canPlay} onPlay={play} go={go} /> : <GraphBoundary resetKey={graph}><Graph graph={graph} highlight={sel} selected={el} showLabels={prefs['appearance.graph_labels']}
                                    onNode={(id) => { setEl({ type: 'node', id }); setInspect('path') }}
                                    onEdge={(id) => { setEl({ type: 'edge', id }); setInspect('path') }} onClear={() => setEl(null)} /></GraphBoundary>}
      </section>

      {inspectorOpen && <Resizer side="right" value={rightW} min={260} max={560} onChange={setRight} label="Resize inspector" />}
      <aside className="pane right" aria-label="Inspector" hidden={!inspectorOpen}>
        <Tabs label="Inspector" value={inspect} onChange={setInspect}
              tabs={[{ id: 'path', label: 'Path' }, { id: 'fixes', label: 'Fixes' }, { id: 'rem', label: 'Remediation', count: pending }]} />
        {inspect === 'path' && el && <ElementDetail el={el} graph={graph} onClear={() => setEl(null)} />}
        {inspect === 'path' && (empty ? <p className="muted">Nothing selected.</p> : <PathDetail path={sel} />)}
        {inspect === 'fixes' && (empty ? <p className="muted">Nothing to fix yet.</p> : <Fixes fixes={fixes} onPropose={propose} />)}
        {inspect === 'rem' && <Remediations items={rems} onChange={refresh} desktop={desktop} />}
      </aside>
    </main>
  )
}
