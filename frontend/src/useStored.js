import { useEffect, useState } from 'react'

/** localStorage-backed state; falls back silently when storage is unavailable. */
export function useStored(key, initial) {
  const [v, setV] = useState(() => {
    try {
      const raw = localStorage.getItem(`paladin:${key}`)
      return raw === null ? initial : JSON.parse(raw)
    } catch { return initial }
  })
  useEffect(() => {
    try { localStorage.setItem(`paladin:${key}`, JSON.stringify(v)) } catch { /* storage blocked */ }
  }, [key, v])
  return [v, setV]
}
