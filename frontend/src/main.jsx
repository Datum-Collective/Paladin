import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'
import './styles.css'
import { applyTheme } from './prefs.jsx'

// the last chosen theme, before the server's preferences arrive, so there is no flash of the wrong one
try { applyTheme(localStorage.getItem('paladin:theme')) } catch { /* no storage */ }

// The desktop app exposes its platform through the preload bridge. Set it before the first paint, so the Windows
// theme (styles.css, html[data-platform="win32"]) never flashes the default look.
if (typeof window !== 'undefined' && window.paladin && typeof window.paladin.platform === 'string') {
  document.documentElement.dataset.platform = window.paladin.platform
}

createRoot(document.getElementById('root')).render(<App />)
