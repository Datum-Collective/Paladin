import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react'
import Icon from './Icons.jsx'

const Ctx = createContext({ push: () => {} })
export const useToast = () => useContext(Ctx).push
const GLYPH = { ok: 'check', bad: 'alert', warn: 'alert', info: 'info' }

export function ToastProvider({ children }) {
  const [items, setItems] = useState([])
  const n = useRef(0)
  const dismiss = useCallback((id) => setItems((xs) => xs.filter((x) => x.id !== id)), [])
  const push = useCallback((msg, tone = 'info') => {
    const id = ++n.current
    setItems((xs) => [...xs.slice(-3), { id, msg: String(msg), tone }])
    setTimeout(() => dismiss(id), tone === 'bad' ? 7000 : 3500)
  }, [dismiss])
  const value = useMemo(() => ({ push }), [push])
  return (
    <Ctx.Provider value={value}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={`toast ${t.tone}`}>
            <span className="toast-ic" aria-hidden="true"><Icon name={GLYPH[t.tone] || 'info'} size={13} /></span>
            <span className="toast-msg">{t.msg}</span>
            <button className="toast-x" aria-label="Dismiss" onClick={() => dismiss(t.id)}><Icon name="x" size={12} /></button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  )
}
