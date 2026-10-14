import { useMemo, useState } from 'react'
import Icon from './Icons.jsx'
import { parseDiff, withInline } from './diffParse.js'

function Code({ line }) {
  if (!line.mark || line.mark[0] >= line.mark[1]) return <>{line.text || ' '}</>
  const [a, b] = line.mark
  return (
    <>
      {line.text.slice(0, a)}
      <mark>{line.text.slice(a, b)}</mark>
      {line.text.slice(b)}
    </>
  )
}

function FileDiff({ file, fixes, defaultOpen }) {
  const [open, setOpen] = useState(defaultOpen)
  const hunks = useMemo(() => file.hunks.map((h) => ({ ...h, lines: withInline(h.lines) })), [file])
  return (
    <section className="diff-file">
      <button className="diff-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <Icon name={open ? 'down' : 'chevron'} size={14} />
        <Icon name="file" size={14} />
        <span className="diff-path">{file.path}</span>
        {file.isNew && <span className="tag">new</span>}
        <span className="diff-stat"><span className="add">+{file.add}</span> <span className="del">−{file.del}</span></span>
      </button>
      {open && fixes.length > 0 && (
        <ul className="diff-notes">
          {fixes.map((f) => (
            <li key={f.id}>
              <span className="tag">{f.method === 'haiku' ? 'AI-drafted' : 'rule'}</span>
              <b>{f.rule}</b> <span className="muted">{f.cwe} · {f.technique}</span>
              <div className="muted">{f.explanation}</div>
            </li>
          ))}
        </ul>
      )}
      {open && hunks.map((h, hi) => (
        <div key={hi} className="hunk">
          <div className="hunk-head">{h.header || `change ${hi + 1}`}</div>
          <table className="diff"><tbody>
            {h.lines.map((l, i) => (
              <tr key={i} className={l.t === '+' ? 'row-add' : l.t === '-' ? 'row-del' : ''}>
                <td className="ln">{l.o ?? ''}</td>
                <td className="ln">{l.n ?? ''}</td>
                <td className="sign">{l.t === ' ' ? '' : l.t}</td>
                <td className="code"><Code line={l} /></td>
              </tr>
            ))}
          </tbody></table>
        </div>
      ))}
    </section>
  )
}

export default function DiffView({ diff, fixes }) {
  const files = useMemo(() => parseDiff(diff), [diff])
  if (!files.length) return <p className="muted">No code changes.</p>
  const add = files.reduce((s, f) => s + f.add, 0)
  const del = files.reduce((s, f) => s + f.del, 0)
  const byFile = (p) => fixes.filter((f) => f.file === p)
  return (
    <div>
      <p className="muted">{files.length} file{files.length > 1 ? 's' : ''} changed, <span className="add">+{add}</span>{' '}
        <span className="del">−{del}</span></p>
      {files.map((f, i) => <FileDiff key={f.path} file={f} fixes={byFile(f.path)} defaultOpen={i < 4} />)}
    </div>
  )
}
