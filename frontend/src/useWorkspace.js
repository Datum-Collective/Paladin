import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import { useToast } from './toast.jsx'

/** All server state for the active workspace plus the actions that change it. */
export function useWorkspace(user, onExpired) {
  const toast = useToast()
  const [data, setData] = useState({ graph: null, paths: [], fixes: null, events: null, rems: [] })
  const [loaded, setLoaded] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [canPlay, setCanPlay] = useState(false)
  const timer = useRef(null)
  const alive = useRef(true)
  const seq = useRef(0)
  const run = useRef(0)

  const refresh = useCallback(async () => {
    const mine = ++seq.current // only the newest response may write, so out-of-order replies cannot show stale data
    try {
      const [graph, p, fixes, r, events] = await Promise.all([api.graph(), api.paths(), api.fixes(), api.remediations(), api.events()])
      if (alive.current && mine === seq.current) setData({ graph, paths: p.paths, fixes, events, rems: r.remediations })
    } catch (e) {
      if (e.status === 401 && onExpired) onExpired()
      else toast(`Could not refresh: ${e.message}`, 'bad')
    } finally {
      if (alive.current) setLoaded(true)
    }
  }, [toast, onExpired])

  useEffect(() => {
    alive.current = true
    if (!user) return undefined
    refresh()
    api.simStatus().then((s) => setCanPlay(s.total > 0)).catch(() => {})
    const es = new EventSource('/api/stream')
    es.onmessage = () => refresh()
    return () => { alive.current = false; es.close(); clearTimeout(timer.current) }
  }, [user, refresh])

  const play = useCallback(async () => {
    const mine = ++run.current // a reset or a newer play invalidates this loop
    setPlaying(true)
    try {
      await api.simStart()
      const tick = async () => {
        if (mine !== run.current) return
        try {
          const r = await api.simStep(15)
          if (mine !== run.current) return
          if (r.done || !alive.current) { setPlaying(false); return }
          timer.current = setTimeout(tick, 700)
        } catch (e) { setPlaying(false); toast(e.message, 'bad') }
      }
      tick()
    } catch (e) { setPlaying(false); toast(e.message, 'bad') }
  }, [toast])

  const reset = useCallback(async () => {
    run.current += 1
    clearTimeout(timer.current)
    setPlaying(false)
    try { await api.simReset(); await refresh(); toast('Workspace reset', 'ok') } catch (e) { toast(e.message, 'bad') }
  }, [refresh, toast])

  const propose = useCallback(async (edges, title) => {
    try { await api.propose(edges, title); await refresh(); toast('Fix proposed. Review it under Remediation.', 'ok') }
    catch (e) { toast(e.message, 'bad') }
  }, [refresh, toast])

  const { graph, paths } = data
  const empty = !graph || (graph.events === 0 && paths.length === 0)
  return { ...data, loaded, empty, playing, canPlay, play, reset, refresh, propose }
}
