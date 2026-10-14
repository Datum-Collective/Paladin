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
  chat: 'M4 5h16v11H9l-5 4zM8 10h8M8 13h5',
  stop: 'M7 7h10v10H7z',
  sidebar: 'M4 5h16v14H4zM9 5v14',
  inspector: 'M4 5h16v14H4zM15 5v14',
  github: 'M9 19c-4 1.5-4-2-6-2.5M15 21v-3.5c0-1 .1-1.4-.5-2 2.8-.3 5.5-1.4 5.5-6a4.6 4.6 0 00-1.3-3.2 4.2 4.2 0 00-.1-3.2s-1-.3-3.4 1.3a11.700 11.700 0 00-6.200 0C6.600 2.800 5.600 3.100 5.600 3.100a4.200 4.200 0 00-.1 3.200A4.600 4.600 0 004.200 9.500c0 4.600 2.700 5.700 5.500 6-.6.600-.6 1.200-.5 2V21',
  folder: 'M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z',
  plus: 'M12 5v14M5 12h14',
  lock: 'M6 11h12v9H6zM8 11V8a4 4 0 118 0v3',
  home: 'M4 11l8-7 8 7v9h-5v-6H9v6H4z',
  return: 'M20 6v6a3 3 0 01-3 3H5M9 11l-4 4 4 4',
  activity: 'M3 12h4l3-8 4 16 3-8h4',
  plug: 'M9 3v5M15 3v5M6 8h12v4a6 6 0 01-12 0zM12 18v3',
  search2: 'M11 18a7 7 0 100-14 7 7 0 000 14z',
  edit: 'M4 20h4L19 9l-4-4L4 16zM13.500 6.500l4 4',
  alert: 'M12 8v5M12 16.500h.01M12 3.500l9.500 16.500h-19z',
  info: 'M12 11v5M12 8h.01M12 21a9 9 0 100-18 9 9 0 000 18z',
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
