'use strict'
const { contextBridge, ipcRenderer } = require('electron')

const on = (channel) => (cb) => {
  const h = (_e, payload) => cb(payload)
  ipcRenderer.on(channel, h)
  return () => ipcRenderer.removeListener(channel, h)
}

contextBridge.exposeInMainWorld('paladin', {
  platform: process.platform,
  info: () => ipcRenderer.invoke('app:info'),
  signIn: () => ipcRenderer.invoke('auth:sign-in'),
  getSettings: () => ipcRenderer.invoke('settings:get'),
  setSettings: (patch) => ipcRenderer.invoke('settings:set', patch),
  setTheme: (t) => ipcRenderer.invoke('app:set-theme', t),
  checkForUpdates: () => ipcRenderer.invoke('update:check'),
  installUpdate: () => ipcRenderer.invoke('update:install'),
  chooseFolder: () => ipcRenderer.invoke('dialog:choose-folder'),
  openDataFolder: () => ipcRenderer.invoke('app:open-data'),
  onUpdate: on('update:status'),
  onBackend: on('backend:status'),
  onCommand: on('menu:command'),
})
