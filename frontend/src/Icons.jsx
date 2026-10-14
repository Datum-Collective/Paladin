// Monochrome outlined icons (1.5px stroke, currentColor). Used sparingly, always with a text label nearby.
const P = {
  graph: 'M5 6a2 2 0 100-4 2 2 0 000 4zM19 12a2 2 0 100-4 2 2 0 000 4zM5 22a2 2 0 100-4 2 2 0 000 4zM6.8 5.2l10.4 5.6M6.8 18.8l10.4-5.6',
  repo: 'M6 3v12M6 15a3 3 0 103 3M18 9a3 3 0 100-6 3 3 0 000 6zM18 9c0 4-6 4-9 9',
  chart: 'M4 20V10M10 20V4M16 20v-8M22 20H2',
  play: 'M7 4.5v15l12-7.5z',
  check: 'M5 12.5l4.5 4.5L19 7.5',
  chevron: 'M9 6l6 6-6 6',
  down: 'M6 9l6 6 6-6',
  copy: 'M9 9h10v11H9zM5 15V4h10',
  file: 'M7 3h7l5 5v13H7zM14 3v5h5',
  x: 'M6 6l12 12M18 6L6 18',
  logout: 'M10 4H5v16h5M15 8l4 4-4 4M19 12H9',
  upload: 'M12 16V4M7 9l5-5 5 5M5 20h14',
  list: 'M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01',
  settings: 'M12 15a3 3 0 100-6 3 3 0 000 6zM19.4 15a1.7 1.7 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.8-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 01-4 0v-.1a1.7 1.7 0 00-1.1-1.5 1.7 1.7 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.8 1.7 1.7 0 00-1.5-1H3a2 2 0 010-4h.1a1.7 1.7 0 001.5-1.1 1.7 1.7 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.8.3H9a1.7 1.7 0 001-1.5V3a2 2 0 014 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.8V9a1.7 1.7 0 001.5 1H21a2 2 0 010 4h-.1a1.7 1.7 0 00-1.5 1z',
  search: 'M11 18a7 7 0 100-14 7 7 0 000 14zM21 21l-4.3-4.3',
  refresh: 'M20 11a8 8 0 10-2.3 5.7M20 4v7h-7',
  shield: 'M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z',
  command: 'M9 6a3 3 0 10-3 3h12a3 3 0 10-3-3v12a3 3 0 103-3H6a3 3 0 103 3z',
  trash: 'M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3',
}

export default function Icon({ name, size = 16, className = '' }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className={`icon ${className}`}>
      <path d={P[name]} />
    </svg>
  )
}
