import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api.js'
import { useToast } from './toast.jsx'

// Mirrors the server's defaults so the UI renders before the first response; the server stays authoritative.
export const PREF_DEFAULTS = {
  'general.startup': 'home', 'general.after_import': 'repository', 'general.onboarding_dismissed': false,
  'general.setup_done': false, 'general.setup_skipped': false,
  'workspaces.sort': 'recent', 'appearance.density': 'comfortable',
  'appearance.graph_labels': true, 'diff.wrap': true, 'diff.font_size': 12, 'assistant.provider': '',
  'assistant.model': '', 'assistant.effort': '', 'assistant.context': true,
}
const Ctx = createContext({ prefs: PREF_DEFAULTS, set: () => {}, ready: false })
export const usePrefs = () => useContext(Ctx)

/** Reflect preferences on <html> so plain CSS can react to them. */
function apply(p) {
  const r = document.documentElement
  r.dataset.density = p['appearance.density']
  r.dataset.diffWrap = p['diff.wrap'] ? 'on' : 'off'
  r.style.setProperty('--diff-size', `${p['diff.font_size']}px`)
}

export function PrefsProvider({ children }) {
  const toast = useToast()
  const [prefs, setPrefs] = useState(PREF_DEFAULTS)
  const [ready, setReady] = useState(false)
  const latest = useRef(PREF_DEFAULTS)
  latest.current = prefs

  useEffect(() => {
    api.prefs().then((p) => { setPrefs({ ...PREF_DEFAULTS, ...p }); setReady(true) }).catch(() => setReady(true))
  }, [])
  useEffect(() => { apply(prefs) }, [prefs])

  const set = useCallback(async (key, value) => {
    const previous = latest.current[key]
    setPrefs((p) => ({ ...p, [key]: value }))                            // optimistic
    try {
      const saved = await api.setPrefs({ [key]: value })
      setPrefs((p) => ({ ...p, [key]: saved[key] }))                     // adopt the server's value for this key only
    } catch (e) {
      setPrefs((p) => ({ ...p, [key]: previous }))                       // roll back this key, not concurrent edits
      toast(e.message || 'Could not save that setting.', 'bad')
    }
  }, [toast])

  const value = useMemo(() => ({ prefs, set, ready }), [prefs, set, ready])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}
