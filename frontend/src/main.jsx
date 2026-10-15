import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'
import './styles.css'
import { applyTheme } from './prefs.jsx'

// the last chosen theme, before the server's preferences arrive, so there is no flash of the wrong one
try { applyTheme(localStorage.getItem('paladin:theme')) } catch { /* no storage */ }

createRoot(document.getElementById('root')).render(<App />)
