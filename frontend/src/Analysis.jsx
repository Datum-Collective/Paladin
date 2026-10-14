import Graph from './Graph.jsx'
import Resizer from './Resizer.jsx'
import { useStored } from './useStored.js'
import { Empty, Events, Fixes, Ingest, PathDetail, Remediations, Severity } from './parts.jsx'

export default function Analysis({ state, selected, setSelected, tab, setTab, go, desktop }) {
  const { graph, paths, fixes, events, rems, empty, canPlay, play, refresh, propose } = state
  const [left, setLeft] = useStored('w-left', 300)
  const [right, setRight] = useStored('w-right', 400)
  const [inspect, setInspect] = useStored('inspector', 'path')
  const sel = paths.find((p) => p.id === selected)
  const pending = rems.filter((r) => !['verified', 'rolled_back'].includes(r.state)).length

  return (
    <main className="analysis" style={{ gridTemplateColumns: `${left}px 1fr ${right}px` }}>
      <section className="pane left" aria-label="Paths, events and data">
        <div className="seg small" role="tablist">
          {[['paths', 'Paths'], ['events', 'Events'], ['ingest', 'Add data']].map(([t, l]) => (
            <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? 'on' : ''} onClick={() => setTab(t)}>
              {l}{t === 'paths' && paths.length > 0 && <span className="count"> {paths.length}</span>}
            </button>
          ))}
        </div>
        {tab === 'paths' && (paths.length === 0 ? <p className="muted">No paths yet.</p> : (
          <ul className="rows selectable" role="listbox" aria-label="Attack paths">
            {paths.map((p) => (
              <li key={p.id} role="option" aria-selected={p.id === selected} tabIndex={0}
                  className={p.id === selected ? 'on' : ''} onClick={() => setSelected(p.id)}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelected(p.id) } }}>
                <div className="row-top"><Severity level={p.severity} /><span className="muted">{p.risk.toFixed(3)}</span></div>
                <div className="path-line">{p.nodes.join(' → ')}</div>
              </li>
            ))}
          </ul>
        ))}
        {tab === 'events' && <Events data={events} />}
        {tab === 'ingest' && <Ingest onDone={refresh} desktop={desktop} />}
      </section>
      <Resizer side="left" value={left} min={240} max={480} onChange={setLeft} label="Resize paths column" />

      <section className="canvas" aria-label="Attack graph">
        {empty ? <Empty canPlay={canPlay} onPlay={play} go={go} /> : <Graph graph={graph} highlight={sel} />}
      </section>

      <Resizer side="right" value={right} min={320} max={560} onChange={setRight} label="Resize inspector" />
      <aside className="pane right" aria-label="Inspector">
        <div className="seg small" role="tablist">
          {[['path', 'Path'], ['fixes', 'Fixes'], ['rem', 'Remediation']].map(([t, l]) => (
            <button key={t} role="tab" aria-selected={inspect === t} className={inspect === t ? 'on' : ''}
                    onClick={() => setInspect(t)}>
              {l}{t === 'rem' && pending > 0 && <span className="count"> {pending}</span>}
            </button>
          ))}
        </div>
        {inspect === 'path' && (empty ? <p className="muted">Nothing selected.</p> : <PathDetail path={sel} />)}
        {inspect === 'fixes' && (empty ? <p className="muted">Nothing to fix yet.</p> : <Fixes fixes={fixes} onPropose={propose} />)}
        {inspect === 'rem' && <Remediations items={rems} onChange={refresh} />}
      </aside>
    </main>
  )
}
