'use strict'
const test = require('node:test')
const assert = require('node:assert/strict')
const { buildTemplate } = require('../src/menu')

const labels = (t) => t.map((m) => m.label || m.role)
const flat = (t) => t.flatMap((m) => [m, ...(m.submenu || [])])

test('top-level order follows the HIG on macOS', () => {
  const t = buildTemplate({ isMac: true, isPackaged: true, send: () => {} })
  assert.deepEqual(labels(t), ['Paladin', 'File', 'Edit', 'View', 'Go', 'Workspace', 'windowMenu', 'help'])
})

test('Settings is in the app menu on macOS with Command-Comma and About comes first', () => {
  const t = buildTemplate({ isMac: true, isPackaged: true, send: () => {} })
  const app = t[0].submenu
  assert.equal(app[0].role, 'about')
  const s = app.find((i) => i.label === 'Settings…')
  assert.equal(s.accelerator, 'CommandOrControl+,')
  assert.ok(app.some((i) => i.role === 'quit'))
})

test('on Windows Settings lives in File and there is no app menu', () => {
  const t = buildTemplate({ isMac: false, isPackaged: true, send: () => {} })
  assert.equal(labels(t)[0], 'File')
  assert.ok(t[0].submenu.some((i) => i.label === 'Settings…'))
})

test('no accelerator is assigned twice', () => {
  for (const isMac of [true, false]) {
    const acc = flat(buildTemplate({ isMac, isPackaged: true, send: () => {} })).map((i) => i.accelerator).filter(Boolean)
    assert.deepEqual(acc.filter((a, i) => acc.indexOf(a) !== i), [], `duplicates for isMac=${isMac}`)
  }
})

test('menu clicks deliver a command id to the renderer', () => {
  const sent = []
  const t = buildTemplate({ isMac: true, isPackaged: true, send: (m) => sent.push(m) })
  flat(t).find((i) => i.label === 'Analysis').click()
  flat(t).find((i) => i.label === 'Show or Hide Sidebar').click()
  assert.deepEqual(sent, [{ id: 'analysis' }, { id: 'toggle-sidebar' }])
})

test('dev tools only appear in unpackaged builds', () => {
  const has = (p) => flat(buildTemplate({ isMac: true, isPackaged: p, send: () => {} })).some((i) => i.role === 'toggleDevTools')
  assert.equal(has(true), false)
  assert.equal(has(false), true)
})
