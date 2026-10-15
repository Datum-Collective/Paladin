// UILora-style primitives (sliding tabs, shimmer skeletons) built on the app's own theme tokens.
import { useId } from 'react'
import { motion, useReducedMotion } from 'framer-motion'

// Segmented tabs with a spring-animated active pill (UILora "Animated Pill Segmented").
export function Tabs({ tabs, value, onChange, label, className = '' }) {
  const group = useId()
  const reduce = useReducedMotion()
  return (
    <div className={`utabs ${className}`} role="tablist" aria-label={label}>
      {tabs.map(({ id, label: text, count }) => (
        <button key={id} role="tab" aria-selected={value === id} className={value === id ? 'utab on' : 'utab'} onClick={() => onChange(id)}>
          {value === id && (
            <motion.span layoutId={`utab-${group}`} className="utab-pill" aria-hidden="true"
                         transition={reduce ? { duration: 0 } : { type: 'spring', bounce: 0.2, duration: 0.4 }} />
          )}
          <span className="utab-text">{text}{count > 0 && <span className="count"> {count}</span>}</span>
        </button>
      ))}
    </div>
  )
}

// Shimmering placeholder blocks (UILora "Classic Skeleton"); the shimmer stops for reduced motion via CSS.
export function Skeleton({ lines = 3, className = '' }) {
  return (
    <div className={`skel ${className}`} role="status" aria-label="Loading">
      {Array.from({ length: lines }, (_, i) => <span key={i} className="skel-bone" style={{ width: `${100 - (i % 3) * 18}%` }} />)}
    </div>
  )
}
