import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { AlertCircle, AlertTriangle, CheckCircle2, Info, X } from 'lucide-react'

const Ctx = createContext({ push: () => {} })
export const useToast = () => useContext(Ctx).push
const GLYPH = { ok: CheckCircle2, bad: AlertCircle, warn: AlertTriangle, info: Info }

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
        <AnimatePresence initial={false}>
          {items.map((t) => {
            const G = GLYPH[t.tone] || Info
            return (
              <motion.div key={t.id} layout className={`toast ${t.tone}`}
                          initial={{ opacity: 0, y: 16, scale: 0.96 }} animate={{ opacity: 1, y: 0, scale: 1 }}
                          exit={{ opacity: 0, x: 40 }} transition={{ duration: 0.18 }}>
                <span className="toast-ic" aria-hidden="true"><G size={14} /></span>
                <span className="toast-msg">{t.msg}</span>
                <button className="toast-x" aria-label="Dismiss" onClick={() => dismiss(t.id)}><X size={13} /></button>
              </motion.div>
            )
          })}
        </AnimatePresence>
      </div>
    </Ctx.Provider>
  )
}
