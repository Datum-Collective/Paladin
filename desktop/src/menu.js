'use strict'
// Native menu bar in the order the HIG specifies: App, File, Edit, View, app-specific (Go, Workspace), Window, Help.
// Every command here is delivered to the renderer as { id } so the toolbar, command palette and menu share one
// implementation; the renderer owns what each id does.
function buildTemplate({ isMac, isPackaged, send, appName = 'Paladin' }) {
  const cmd = (id) => () => send({ id })
  const settings = { label: 'Settings…', accelerator: 'CommandOrControl+,', click: cmd('settings') }
  const about = { role: 'about', label: `About ${appName}` }
  const t = []
  if (isMac) {
    t.push({
      label: appName,
      submenu: [about, { type: 'separator' }, settings, { type: 'separator' }, { role: 'services' },
                { type: 'separator' }, { role: 'hide' }, { role: 'hideOthers' }, { role: 'unhide' },
                { type: 'separator' }, { role: 'quit' }],
    })
  }
  t.push({
    label: 'File',
    submenu: [
      { label: 'New Workspace', accelerator: 'CommandOrControl+N', click: cmd('new-workspace') },
      { label: 'Open Repository…', accelerator: 'CommandOrControl+Shift+O', click: cmd('open-repo') },
      { label: 'Open Folder…', accelerator: 'CommandOrControl+O', click: cmd('open-folder') },
      { label: 'Add Log Data…', accelerator: 'CommandOrControl+Shift+L', click: cmd('ingest') },
      { type: 'separator' },
      ...(isMac ? [{ role: 'close' }] : [settings, { type: 'separator' }, { role: 'quit' }]),
    ],
  })
  t.push({
    label: 'Edit',
    submenu: [{ role: 'undo' }, { role: 'redo' }, { type: 'separator' }, { role: 'cut' }, { role: 'copy' },
              { role: 'paste' }, { role: 'selectAll' }, { type: 'separator' },
              { label: 'Find…', accelerator: 'CommandOrControl+F', click: cmd('palette') }],
  })
  t.push({
    label: 'View',
    submenu: [
      { label: 'Show or Hide Sidebar', accelerator: isMac ? 'Control+Command+S' : 'Control+B', click: cmd('toggle-sidebar') },
      { label: 'Show or Hide Inspector', accelerator: isMac ? 'Alt+Command+I' : 'Control+Alt+I', click: cmd('toggle-inspector') },
      { type: 'separator' },
      { role: 'resetZoom' }, { role: 'zoomIn' }, { role: 'zoomOut' },
      { type: 'separator' },
      { role: 'togglefullscreen' },
      ...(isPackaged ? [] : [{ type: 'separator' }, { role: 'reload' }, { role: 'toggleDevTools' }]),
    ],
  })
  t.push({
    label: 'Go',
    submenu: [
      { label: 'Start Screen', accelerator: 'CommandOrControl+Shift+H', click: cmd('home') },
      { label: 'Analysis', accelerator: 'CommandOrControl+1', click: cmd('analysis') },
      { label: 'Repository', accelerator: 'CommandOrControl+2', click: cmd('repo') },
      { label: 'Insights', accelerator: 'CommandOrControl+3', click: cmd('insights') },
      { label: 'Assistant', accelerator: 'CommandOrControl+4', click: cmd('assistant') },
      { label: 'Activity', accelerator: 'CommandOrControl+5', click: cmd('activity') },
      { label: 'Workspaces', accelerator: 'CommandOrControl+6', click: cmd('workspaces') },
      { label: 'Integrations', accelerator: 'CommandOrControl+7', click: cmd('integrations') },
      { type: 'separator' },
      { label: 'Command Palette…', accelerator: 'CommandOrControl+K', click: cmd('palette') },
    ],
  })
  t.push({
    label: 'Workspace',
    submenu: [
      { label: 'Play Sample Scenario', click: cmd('play') },
      { label: 'Propose Cheapest Cut', click: cmd('fix-cheapest') },
      { label: 'Propose Best Single Fix', click: cmd('fix-single') },
      { type: 'separator' },
      { label: 'Refresh', accelerator: 'CommandOrControl+R', click: cmd('refresh') },
      { label: 'Reset Workspace…', click: cmd('reset') },
    ],
  })
  t.push({ role: 'windowMenu' })
  t.push({
    role: 'help',
    submenu: [{ label: 'Check for Updates…', click: cmd('check-updates') }],
  })
  return t
}

module.exports = { buildTemplate }
