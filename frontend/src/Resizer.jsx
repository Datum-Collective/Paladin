import { useRef } from 'react'
import { clamp } from './lib.js'

/** Vertical drag handle. `side` is the pane it resizes: 'left' grows with pointer x, 'right' shrinks with it. */
export default function Resizer({ side, value, min, max, onChange, label }) {
  const start = useRef(null)
  const down = (e) => {
    e.preventDefault()
    start.current = { x: e.clientX, v: value }
    const move = (ev) => {
      const dx = ev.clientX - start.current.x
      onChange(clamp(start.current.v + (side === 'left' ? dx : -dx), min, max))
    }
    const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up) }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }
  const key = (e) => {
    const step = e.shiftKey ? 40 : 12
    if (e.key === 'ArrowLeft') onChange(clamp(value + (side === 'left' ? -step : step), min, max))
    if (e.key === 'ArrowRight') onChange(clamp(value + (side === 'left' ? step : -step), min, max))
  }
  return (
    <div className="resizer" role="separator" aria-orientation="vertical" aria-label={label} aria-valuenow={value}
         aria-valuemin={min} aria-valuemax={max} tabIndex={0}
         style={side === 'left' ? { left: value - 4 } : { right: value - 4 }} onPointerDown={down} onKeyDown={key} />
  )
}
