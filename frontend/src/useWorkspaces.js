import { useCallback, useEffect, useState } from 'react'
import { api, setWorkspace } from './api.js'
import { useToast } from './toast.jsx'

/** The user's workspaces and the actions that change which one is active. Server is the source of truth. */
export function useWorkspaces(user) {
  const toast = useToast()
  const [state, setState] = useState({ active: null, workspaces: [], loaded: false })
  const take = useCallback((r) => { setWorkspace(r.active); setState({ active: r.active, workspaces: r.workspaces, loaded: true }) }, [])

  const reload = useCallback(async () => {
    try { take(await api.workspaces()) } catch (e) { setState((s) => ({ ...s, loaded: true })); toast(e.message, 'bad') }
  }, [take, toast])
  useEffect(() => { if (user) reload() }, [user, reload])

  const guard = useCallback(async (fn) => {
    try { return await fn() } catch (e) { toast(e.message || 'That did not work.', 'bad'); return null }
  }, [toast])

  const open = useCallback((id) => guard(async () => { take(await api.openWorkspace(id)); return true }), [guard, take])
  const create = useCallback((name) => guard(async () => {
    const r = await api.createWorkspace(name)
    take(r)
    return r.workspace
  }), [guard, take])
  const rename = useCallback((id, name) => guard(async () => { await api.renameWorkspace(id, name); await reload(); return true }), [guard, reload])
  const remove = useCallback((id) => guard(async () => { take(await api.deleteWorkspace(id)); return true }), [guard, take])
  const importRepo = useCallback(async (query) => {      // errors propagate: the landing screen shows them inline
    const r = await api.importRepo(query)
    take(r)
    return r
  }, [take])

  const current = state.workspaces.find((w) => w.id === state.active) || null
  return { ...state, current, reload, open, create, rename, remove, importRepo }
}
