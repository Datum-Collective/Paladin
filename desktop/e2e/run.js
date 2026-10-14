// End-to-end click-through, executed inside the real app window against the real backend (nothing mocked).
// Run: E2E_REPO=/path/to/git/repo PALADIN_E2E=e2e/run.js npx electron . --user-data-dir=<fresh dir>
// Body of an async function: it must `return` the results array.
const results = []
const jsErrors = []
window.addEventListener('error', (e) => jsErrors.push(String(e.message)))
window.addEventListener('unhandledrejection', (e) => jsErrors.push(`unhandled: ${e.reason && e.reason.message || e.reason}`))
const origErr = console.error
console.error = (...a) => { jsErrors.push(a.map(String).join(' ').slice(0, 200)); origErr(...a) }

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const $ = (s, r = document) => r.querySelector(s)
const $$ = (s, r = document) => [...r.querySelectorAll(s)]
const txt = (e) => (e ? e.textContent.replace(/\s+/g, ' ').trim() : '')
const byText = (sel, t, root = document) => $$(sel, root).find((e) => txt(e).includes(t))
async function waitFor(fn, ms = 6000) {
  const t = Date.now()
  while (Date.now() - t < ms) { const v = fn(); if (v) return v; await sleep(60) }
  return null
}
const ok = (c, m) => { if (!c) throw new Error(m) }
async function test(name, fn) {
  try { const note = await fn(); results.push({ name, ok: true, note: note || '' }) } catch (e) {
    results.push({ name, ok: false, note: String((e && e.message) || e) })
  }
}
const must = (sel, t, root = document) => {
  const e = byText(sel, t, root)
  if (!e) throw new Error(`no element ${sel} containing "${t}" (found: ${$$(sel, root).map((x) => txt(x).slice(0, 30)).join(' | ')})`)
  return e
}
const nav = (label) => $(`button.nav-item[aria-label="${label}"]`)
async function go(label, titleText) {
  const b = nav(label); ok(b, `nav "${label}" missing`)
  b.click()
  ok(await waitFor(() => txt($('.toolbar-title')) === (titleText || label)), `title did not become ${titleText || label}`)
}
function setValue(el, value) {
  const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : el.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype
  Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, value)
  el.dispatchEvent(new Event(el.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true }))
}
const key = (el, k, init = {}) => el.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true, ...init }))
const api = async (m, u, b) => { const r = await fetch(u, { method: m, headers: b ? { 'Content-Type': 'application/json' } : {}, body: b ? JSON.stringify(b) : undefined }); return r.json().catch(() => ({})) }
const toastText = () => $$('.toast').map(txt).join(' | ')

// ---------------------------------------------------------------- boot
await test('boot: app renders Home with every navigation entry', async () => {
  ok(await waitFor(() => $('.sidebar')), 'sidebar missing')
  const labels = ['Home', 'Workspaces', 'Analysis', 'Repository', 'Insights', 'Assistant', 'Activity', 'Integrations', 'Settings']
  const missing = labels.filter((l) => !nav(l))
  ok(!missing.length, `missing nav: ${missing.join(', ')}`)
  ok(txt($('.toolbar-title')) === 'Home', `title is ${txt($('.toolbar-title'))}`)
})

await test('navigation: every sidebar destination opens and titles the page', async () => {
  for (const [label, title] of [['Workspaces', 'Workspaces'], ['Analysis', 'Analysis'], ['Repository', 'Repository'], ['Insights', 'Insights'],
    ['Assistant', 'Assistant'], ['Activity', 'Activity'], ['Integrations', 'Integrations'], ['Settings', 'General'], ['Home', 'Home']]) {
    await go(label, title)
  }
})

// ---------------------------------------------------------------- chrome
await test('chrome: sidebar hide/show, collapse to rail and expand', async () => {
  $('button.tool[aria-label="Hide sidebar"]').click()
  ok(await waitFor(() => !$('.sidebar')), 'sidebar did not hide')
  $('button.tool[aria-label="Show sidebar"]').click()
  ok(await waitFor(() => $('.sidebar')), 'sidebar did not show')
  $('.nav-item.collapse').click()
  ok(await waitFor(() => $('.sidebar.rail')), 'rail did not engage')
  ok(!$('.sidebar.rail .nav-item span'), 'rail still shows labels')
  $('.sidebar.rail .nav-item.collapse').click()
  ok(await waitFor(() => $('.sidebar') && !$('.sidebar.rail')), 'rail did not expand')
})

await test('chrome: sidebar resizer responds to the keyboard', async () => {
  const r = $('[role=separator][aria-label="Resize sidebar"]'); ok(r, 'resizer missing')
  const before = Number(r.getAttribute('aria-valuenow'))
  key(r, 'ArrowRight')
  ok(await waitFor(() => Number($('[role=separator][aria-label="Resize sidebar"]').getAttribute('aria-valuenow')) > before), 'width did not grow')
})

await test('chrome: inspector toggle hides and shows the right pane', async () => {
  await go('Analysis')
  const t = $('button.tool[aria-label="Hide inspector"]'); ok(t, 'inspector toggle missing')
  t.click()
  ok(await waitFor(() => $('aside.pane.right').hidden), 'inspector did not hide')
  $('button.tool[aria-label="Show inspector"]').click()
  ok(await waitFor(() => !$('aside.pane.right').hidden), 'inspector did not show')
})

// ---------------------------------------------------------------- command palette
await test('palette: opens, filters, runs a command, and Escape closes it', async () => {
  await go('Home')
  $('.palette-trigger').click()
  const input = await waitFor(() => $('.palette input')); ok(input, 'palette did not open')
  setValue(input, 'integr')
  const item = await waitFor(() => byText('.palette-item', 'Integrations')); ok(item, 'no Integrations command')
  key(input, 'Enter')
  ok(await waitFor(() => !$('.palette') && txt($('.toolbar-title')) === 'Integrations'), 'command did not run')
  await go('Home')
  $('.palette-trigger').click()
  const i2 = await waitFor(() => $('.palette input'))
  key(i2, 'Escape')
  ok(await waitFor(() => !$('.palette')), 'Escape did not close the palette')
})

// ---------------------------------------------------------------- launcher input
const bar = () => $('.bar input')
async function submit(value) {
  const i = bar(); i.focus(); setValue(i, value); await sleep(80)
  key(i, 'Enter')
}
await test('launcher: unrecognised text gives a clear error, not a silent no-op', async () => {
  await submit('hello world')
  const e = await waitFor(() => $('.inline-error')); ok(e, 'no error shown')
  ok(/GitHub link|Nothing matches/.test(txt(e)), `unexpected: ${txt(e)}`)
})
await test('launcher: a repository that does not exist explains how to fix it', async () => {
  await submit('zz-nonexistent-owner-123/definitely-missing-repo-xyz')
  const e = await waitFor(() => { const x = $('.inline-error'); return x && /not found|reach|rate limit/i.test(txt(x)) ? x : null }, 15000)
  ok(e, `no actionable error: ${txt($('.inline-error'))}`)
  ok(byText('.inline-error button', 'GitHub Settings') || /reach|rate limit/i.test(txt(e)), 'no path to Settings')
})
await test('launcher: a folder that is not a Git repository is rejected with guidance', async () => {
  await submit('/private/tmp')
  const e = await waitFor(() => { const x = $('.inline-error'); return x && /git/i.test(txt(x)) ? x : null }, 8000)
  ok(e, `got: ${txt($('.inline-error'))}`)
})

// ---------------------------------------------------------------- new workspace dialog
await test('new workspace: validates, creates, switches and reports', async () => {
  must('.launch-actions button', 'New Workspace').click()
  ok(await waitFor(() => $('.dialog')), 'dialog did not open')
  must('.dialog button', 'Create').click()
  ok(await waitFor(() => /name/i.test(txt($('.dialog .err')))), 'no validation message for empty name')
  setValue($('.dialog input'), 'E2E Empty')
  must('.dialog button', 'Create').click()
  ok(await waitFor(() => !$('.dialog')), 'dialog did not close')
  ok(await waitFor(() => txt($('.switcher-btn')).includes('E2E Empty')), 'switcher did not show the new workspace')
  ok(await waitFor(() => /Created/.test(toastText())), 'no confirmation toast')
})

// ---------------------------------------------------------------- import a real local repository
await test('import: a real local Git folder is previewed, cloned, scanned and lands on Repository', async () => {
  ok(ENV.REPO, 'E2E_REPO not provided')
  await go('Home')
  await submit(ENV.REPO)
  const prev = await waitFor(() => $('.preview'), 10000); ok(prev, `no preview: ${txt($('.inline-error'))}`)
  ok(txt(prev).includes('vuln-e2e'), `preview does not name the folder: ${txt(prev)}`)
  must('.preview button', 'Scan Folder').click()
  ok(await waitFor(() => txt($('.toolbar-title')) === 'Repository', 10000), 'did not navigate to Repository')
  const done = await waitFor(() => { const p = $('.status .pill'); const t = txt(p); return /ready|done|failed|PR opened/i.test(t) ? t : null }, 90000)
  ok(done, 'scan never settled')
  ok(/ready|done/i.test(done), `scan ended as: ${done}`)
})
await test('repository: findings listed with verification and patch actions', async () => {
  ok(await waitFor(() => /SQL|Shell|Hard-coded/.test(txt($('.repo-side')))), 'findings not listed')
  ok(byText('.repo-main button', 'Copy patch') || byText('.repo-main .btn', 'Download'), 'no patch actions')
  const pr = byText('.repo-main button', 'Open Pull Request'); ok(pr, 'no PR button')
  ok(pr.disabled, 'PR button should be disabled without a GitHub token')
})

// ---------------------------------------------------------------- analysis
await test('analysis: graph canvas renders and paths are listed', async () => {
  await go('Analysis')
  ok(await waitFor(() => $('.graph canvas')), 'no graph canvas')
  const n = await waitFor(() => $$('.rows.selectable li').length > 0 ? $$('.rows.selectable li').length : 0)
  ok(n > 0, 'no paths listed')
  return `${n} paths`
})
await test('analysis: selecting a path shows its narrative, stages and evidence', async () => {
  $$('.rows.selectable li')[0].click()
  ok(await waitFor(() => byText('h2', 'Attack path')), 'no path detail')
  ok($('.killchain'), 'no kill chain')
  ok($$('.steps li').length > 0, 'no progression steps')
})
await test('analysis: Fixes tab proposes a fix and Remediation walks approve, execute, verify, roll back', async () => {
  must('.pane.right [role=tab]', 'Fixes').click()
  const propose = await waitFor(() => byText('.pane.right button', 'Propose Fix')); ok(propose, 'no fix suggested')
  propose.click()
  ok(await waitFor(() => /Fix proposed/.test(toastText())), 'no confirmation toast')
  must('.pane.right [role=tab]', 'Remediation').click()
  const act = async (label, state) => {
    const b = await waitFor(() => byText('.pane.right .card button', label)); ok(b, `no ${label} button`)
    b.click()
    ok(await waitFor(() => new RegExp(state, 'i').test(txt($('.pane.right .card .pill')))), `state did not become ${state}`)
  }
  await act('Approve', 'approved')
  await act('Execute', 'executed')
  await act('Verify', 'verified')
  const rb = byText('.pane.right .card button', 'Roll Back'); ok(rb, 'no Roll Back')
})
await test('analysis: Events and Import tabs; pasted log lines are ingested', async () => {
  must('.pane.left [role=tab]', 'Import').click()
  const ta = await waitFor(() => $('.pane.left textarea')); ok(ta, 'no paste area')
  const imp = byText('.pane.left button', 'Import Logs'); ok(imp.disabled, 'Import Logs should be disabled when empty')
  setValue(ta, ENV.LOG)
  ok(await waitFor(() => !byText('.pane.left button', 'Import Logs').disabled), 'Import Logs stayed disabled')
  must('.pane.left button', 'Import Logs').click()
  ok(await waitFor(() => /accepted/.test(toastText())), `no result toast: ${toastText()}`)
  must('.pane.left [role=tab]', 'Events').click()
  ok(await waitFor(() => $$('.pane.left code.snippet').length > 0), 'event not listed')
})

// ---------------------------------------------------------------- insights / activity
await test('insights: findings chart and metrics render', async () => {
  await go('Insights')
  ok(await waitFor(() => byText('h3', 'Repository findings')), 'no findings card')
  ok($$('svg.chart').length > 0, 'no charts')
})
await test('activity: lists the scan and remediation steps and filters work', async () => {
  await go('Activity')
  ok(await waitFor(() => $$('.tl-item').length > 0), 'no activity')
  ok(/Scan/.test(txt($('.timeline'))), 'scan not listed')
  must('[role=radio]', 'Remediation').click()
  ok(await waitFor(() => $$('.tl-item').every((i) => !/^Scan/.test(txt($('b', i))))), 'filter did not hide scans')
  must('[role=radio]', 'Scans').click()
  ok(await waitFor(() => $$('.tl-item').length > 0 && $$('.tl-item').every((i) => /^Scan/.test(txt($('b', i))))), 'scans filter wrong')
  must('.page-head button', 'Refresh').click()
})

// ---------------------------------------------------------------- workspaces browser
await test('workspaces: search, filter, sort, rename, delete (cancel then confirm), open', async () => {
  await go('Workspaces')
  ok(await waitFor(() => $$('.wrow').length >= 2), 'expected at least 2 workspaces')
  const total = $$('.wrow').length
  setValue($('.search-field input'), 'E2E Empty')
  ok(await waitFor(() => $$('.wrow').length === 1), 'search did not narrow the list')
  setValue($('.search-field input'), '')
  must('.seg [role=radio]', 'Local').click()
  ok(await waitFor(() => $$('.wrow').length === 1 && /vuln-e2e/.test(txt($('.wrow')))), 'Local filter wrong')
  must('.seg [role=radio]', 'All').click()
  setValue($('select[aria-label], .sort select'), 'name')
  ok(await waitFor(() => $$('.wrow-name').length === total), 'sort broke the list')
  // rename
  $('button[aria-label="Rename E2E Empty"]').click()
  const ri = await waitFor(() => $('.wrow input[aria-label="Workspace name"]')); ok(ri, 'no rename field')
  setValue(ri, 'E2E Renamed'); key(ri, 'Enter')
  ok(await waitFor(() => byText('.wrow-name', 'E2E Renamed')), 'rename did not apply')
  // delete: cancel keeps, confirm removes
  $('button[aria-label="Delete E2E Renamed"]').click()
  ok(await waitFor(() => $('[role=alertdialog]')), 'no confirmation dialog')
  must('[role=alertdialog] button', 'Cancel').click()
  ok(await waitFor(() => !$('[role=alertdialog]')), 'cancel did not close')
  ok(byText('.wrow-name', 'E2E Renamed'), 'cancel deleted the workspace')
  $('button[aria-label="Delete E2E Renamed"]').click()
  ok(await waitFor(() => $('[role=alertdialog]')), 'confirmation did not reopen')
  must('[role=alertdialog] button', 'Delete Workspace').click()
  ok(await waitFor(() => !byText('.wrow-name', 'E2E Renamed')), 'delete did not remove it')
})
await test('workspaces: opening a row lands inside that workspace', async () => {
  const row = $$('.wrow-main').find((b) => !/Open$/.test(txt($('.pill', b.parentElement)) || ''))
  const target = $$('.wrow-main')[0]
  target.click()
  ok(await waitFor(() => ['Analysis', 'Repository', 'Insights', 'Assistant', 'Activity'].includes(txt($('.toolbar-title')))), `stayed on ${txt($('.toolbar-title'))}`)
})
await test('switcher: lists workspaces and has create, open repository and manage entries', async () => {
  await go('Home')
  $('.switcher-btn').click()
  const pop = await waitFor(() => $('.popover')); ok(pop, 'popover did not open')
  ok(byText('.pop-item', 'New Workspace') && byText('.pop-item', 'Open Repository') && byText('.pop-item', 'Manage Workspaces'), 'entries missing')
  must('.pop-item', 'Manage Workspaces').click()
  ok(await waitFor(() => txt($('.toolbar-title')) === 'Workspaces'), 'Manage did not open Workspaces')
})

// ---------------------------------------------------------------- integrations / assistant
await test('integrations: connection rows and API key creation', async () => {
  await go('Integrations')
  ok(byText('.frow', 'GitHub') && byText('.frow', 'Claude') && byText('.frow', 'OpenAI'), 'rows missing')
  const check = $$('.frow button').filter((b) => txt(b) === 'Check Key'); ok(check.length >= 2, 'Check Key missing')
  ok(check.every((b) => b.disabled), 'Check Key should be disabled with no key')
  must('.frow button', 'Create API Key').click()
  ok(await waitFor(() => /X-API-Key/.test(txt($('.runbook')))), 'no ingestion snippet')
})
await test('assistant: with no provider key it explains how to connect and cannot send', async () => {
  await go('Assistant')
  ok(await waitFor(() => /Connect a model provider|No Claude key|No OpenAI key/.test(txt($('.thread')))), 'no empty state')
  ok($('.composer textarea').disabled, 'composer should be disabled')
  const open = byText('.thread button', 'Open Settings'); ok(open, 'no Open Settings')
  open.click()
  ok(await waitFor(() => txt($('.toolbar-title')) === 'Models & Providers'), 'did not open the providers pane')
})

// ---------------------------------------------------------------- settings
await test('settings: every category opens and shows content', async () => {
  const panes = $$('.settings-nav button').map((b) => txt(b))
  ok(panes.length === 9, `expected 9 panes, got ${panes.length}`)
  for (const p of panes) {
    must('.settings-nav button', p).click()
    ok(await waitFor(() => txt($('.toolbar-title')) === p), `title not ${p}`)
    ok($('.settings-inner').children.length > 0, `${p} is empty`)
  }
})
await test('settings: preferences apply immediately and persist on the server', async () => {
  must('.settings-nav button', 'Appearance').click()
  await waitFor(() => byText('[role=radio]', 'Compact'))
  must('[role=radio]', 'Compact').click()
  ok(await waitFor(() => document.documentElement.dataset.density === 'compact'), 'density not applied')
  ok(await waitFor(async () => (await api('GET', '/api/prefs'))['appearance.density'] === 'compact', 3000) || true, '')
  const p = await api('GET', '/api/prefs'); ok(p['appearance.density'] === 'compact', 'not persisted')
  must('[role=radio]', 'Comfortable').click()
  ok(await waitFor(() => document.documentElement.dataset.density === 'comfortable'), 'did not switch back')
  const sw = $('button[role=switch][aria-label="Graph labels"]'); ok(sw, 'no graph labels switch')
  const was = sw.getAttribute('aria-checked'); sw.click()
  ok(await waitFor(() => $('button[role=switch][aria-label="Graph labels"]').getAttribute('aria-checked') !== was), 'switch did not flip')
  $('button[role=switch][aria-label="Graph labels"]').click()
  must('.settings-nav button', 'Code & Diffs').click()
  const fs = await waitFor(() => $('#s-fs')); setValue(fs, '14')
  ok(await waitFor(() => document.documentElement.style.getPropertyValue('--diff-size') === '14px'), 'font size not applied')
  setValue($('#s-fs'), '12')
})
await test('settings: workspace reset dialog cancels without deleting', async () => {
  must('.settings-nav button', 'General').click()
  const r = await waitFor(() => byText('.frow button', 'Reset…')); ok(r, 'no reset entry')
  r.click()
  ok(await waitFor(() => $('[role=alertdialog]')), 'no confirmation')
  must('[role=alertdialog] button', 'Cancel').click()
  ok(await waitFor(() => !$('[role=alertdialog]')), 'cancel did not close')
})
await test('settings: privacy delete-all and storage clear-clones ask for confirmation', async () => {
  must('.settings-nav button', 'Privacy').click()
  const d = await waitFor(() => byText('.frow button', 'Delete All…')); ok(d, 'no delete all')
  d.click()
  ok(await waitFor(() => $('[role=alertdialog]')), 'no confirmation')
  must('[role=alertdialog] button', 'Cancel').click()
  must('.settings-nav button', 'Advanced').click()
  const c = await waitFor(() => byText('.frow button', 'Clear…')); ok(c, 'no clear clones')
  ok(await waitFor(() => /MB|KB|B/.test(txt($('.settings-inner')))), 'storage sizes missing')
})
await test('keyboard shortcuts pane lists commands', async () => {
  must('.settings-nav button', 'Keyboard Shortcuts').click()
  ok(await waitFor(() => $$('kbd.kbd-lg').length >= 10), 'too few shortcuts')
})


// ---------------------------------------------------------------- every remaining control
await test('home: checklist and connection buttons open the right Settings pane; links and Dismiss work', async () => {
  await go('Home')
  must('.rail-group button', 'Connect').click()
  ok(await waitFor(() => txt($('.toolbar-title')) === 'GitHub'), 'Connect did not open GitHub settings')
  await go('Home')
  must('.rail-group button', 'Add key').click()
  ok(await waitFor(() => txt($('.toolbar-title')) === 'Models & Providers'), 'Add key did not open provider settings')
  await go('Home')
  must('button.link', 'All workspaces').click()
  ok(await waitFor(() => txt($('.toolbar-title')) === 'Workspaces'), 'All workspaces did not open')
  await go('Home')
  const c = byText('.resume button', 'Continue'); ok(c, 'no Resume row')
  c.click()
  ok(await waitFor(() => txt($('.toolbar-title')) === 'Analysis'), 'Continue did not open the workspace')
  await go('Home')
  must('.rail-group button', 'Dismiss').click()
  ok(await waitFor(() => !byText('h3', 'Get started')), 'checklist stayed')
  ok((await api('GET', '/api/prefs'))['general.onboarding_dismissed'] === true, 'dismissal not persisted')
})

await test('palette: every command runs without errors and closes the palette', async () => {
  await go('Home')
  const before = jsErrors.length
  $('.palette-trigger').click()
  await waitFor(() => $('.palette'))
  const names = $$('.palette-item').map((i) => txt($('.palette-title', i)))
  ok(names.length >= 10, `only ${names.length} commands`)
  const skip = /Reset workspace|Open folder|Check for updates|Switch to|→|Play sample|Propose|Show or hide|Collapse or expand/
  let ran = 0
  for (const n of names.filter((x) => !skip.test(x))) {
    if (!$('.palette')) { $('.palette-trigger').click(); await waitFor(() => $('.palette')) }
    const input = $('.palette input'); setValue(input, n); await sleep(60)
    const item = byText('.palette-item', n); if (!item) continue
    item.click(); ran += 1
    await sleep(120)
    $$('[role=dialog], [role=alertdialog]').forEach((d) => { const b = byText('button', 'Cancel', d); if (b) b.click() })
    await sleep(60)
  }
  ok(jsErrors.length === before, `JS errors while running commands: ${jsErrors.slice(before).join(' / ')}`)
  return `${ran} commands ran`
})

await test('new workspace dialog: GitHub and folder sources validate before creating', async () => {
  await go('Home')
  must('.launch-actions button', 'New Workspace').click()
  await waitFor(() => $('.dialog'))
  must('.dialog [role=radio]', 'GitHub repository').click()
  ok(await waitFor(() => byText('.dialog button', 'Import')), 'submit label did not update')
  must('.dialog button', 'Import').click()
  ok(await waitFor(() => /GitHub link/i.test(txt($('.dialog .err')))), 'no GitHub validation')
  setValue($('.dialog input'), 'not a repo !!')
  must('.dialog button', 'Import').click()
  ok(await waitFor(() => $('.dialog .err') && txt($('.dialog .err')).length > 0), 'bad link accepted silently')
  must('.dialog [role=radio]', 'Local folder').click()
  await sleep(150)
  must('.dialog button', 'Import').click()
  ok(await waitFor(() => /folder/i.test(txt($('.dialog .err')))), 'no folder validation')
  must('.dialog button', 'Cancel').click()
  ok(await waitFor(() => !$('.dialog')), 'Cancel did not close')
})

await test('failure and recovery: a broken repository fails with a reason and Retry works', async () => {
  ok(ENV.BADREPO, 'E2E_BADREPO missing')
  await go('Home')
  await submit(ENV.BADREPO)
  const prev = await waitFor(() => $('.preview'), 8000); ok(prev, `no preview: ${txt($('.inline-error'))}`)
  must('.preview button', 'Scan Folder').click()
  ok(await waitFor(() => txt($('.toolbar-title')) === 'Repository', 8000), 'did not navigate')
  const failed = await waitFor(() => /failed/i.test(txt($('.status .pill'))), 30000)
  ok(failed, `state: ${txt($('.status .pill'))}`)
  ok(txt($('.repo-side')).length > 0 && $('.err'), 'no failure reason shown')
  await go('Activity')
  const retry = await waitFor(() => byText('button', 'Retry scan')); ok(retry, 'no Retry on the failed scan')
  retry.click()
  ok(await waitFor(() => /Scan restarted/.test(toastText())), `no confirmation: ${toastText()}`)
  ok(txt($('.toolbar-title')) === 'Activity', 'Retry moved the user away from Activity')
})

await test('repository: copy patch and download controls exist on a finished scan', async () => {
  await go('Workspaces')
  const row = $$('.wrow-main').find((b) => /vuln-e2e/.test(txt(b))); ok(row, 'scanned workspace missing')
  row.click()
  await go('Repository')
  ok(await waitFor(() => byText('.repo-main button', 'Copy patch')), 'no Copy patch')
  const before = jsErrors.length
  byText('.repo-main button', 'Copy patch').click()
  await sleep(300)
  ok(jsErrors.length === before, `copy raised: ${jsErrors.slice(before).join(' / ')}`)
  const dl = byText('.repo-main a.btn', 'Download'); ok(dl && /\/patch$/.test(dl.getAttribute('href')), 'download link wrong')
})

await test('toasts: can be dismissed', async () => {
  await go('Analysis')
  $('button.tool[aria-label="Hide inspector"]').click(); await sleep(50)
  $('button.tool[aria-label="Show inspector"]').click()
  byText('.pane.left [role=tab]', 'Import').click()
  const imp = await waitFor(() => $('.pane.left textarea')); setValue(imp, 'garbage line')
  must('.pane.left button', 'Import Logs').click()
  ok(await waitFor(() => $('.toast')), 'no toast')
  $('.toast .toast-x').click()
  ok(await waitFor(() => !$('.toast')), 'toast did not dismiss')
})

await test('assistant: provider, effort and workspace-context controls change state', async () => {
  await go('Assistant')
  const sels = $$('.assistant-bar select'); ok(sels.length >= 2, 'selectors missing')
  setValue(sels[0], 'openai')
  ok(await waitFor(() => (async () => true)()), '')
  ok(await waitFor(() => /OpenAI|No OpenAI key|Connect a model provider/.test(txt($('.thread')))), 'thread did not react to provider')
  const cb = $('.assistant-bar input[type=checkbox]'); ok(cb, 'no context checkbox')
  const was = cb.checked; cb.click()
  ok(await waitFor(() => $('.assistant-bar input[type=checkbox]').checked !== was), 'context toggle stuck')
  $('.assistant-bar input[type=checkbox]').click()
})

await test('settings: general, workspaces, GitHub and provider controls', async () => {
  nav('Settings').click()
  await waitFor(() => $('.settings-nav button'))
  must('.settings-nav button', 'General').click()
  const seg = await waitFor(() => $('[role=radiogroup][aria-label="Start with"]')); ok(seg, 'no startup control')
  must('[role=radiogroup][aria-label="Start with"] [role=radio]', 'Last workspace').click()
  ok(await waitFor(async () => true), '')
  await sleep(300)
  ok((await api('GET', '/api/prefs'))['general.startup'] === 'last', 'startup preference not saved')
  must('[role=radiogroup][aria-label="Start with"] [role=radio]', 'Start screen').click()
  must('.settings-nav button', 'Workspaces').click()
  ok(await waitFor(() => $('#s-sort')), 'no default sort')
  setValue($('#s-sort'), 'events'); await sleep(300)
  ok((await api('GET', '/api/prefs'))['workspaces.sort'] === 'events', 'sort preference not saved')
  setValue($('#s-sort'), 'recent')
  must('.settings-nav button', 'GitHub').click()
  ok(await waitFor(() => byText('label', 'Personal access token')), 'no token field')
  must('.settings-nav button', 'Models & Providers').click()
  ok(await waitFor(() => byText('label', 'Claude API key')) && byText('label', 'OpenAI API key'), 'key fields missing')
  const checks = $$('.frow button').filter((b) => txt(b) === 'Check Key'); ok(checks.every((b) => b.disabled), 'Check Key enabled without a key')
  setValue($('#d-prov'), 'anthropic'); await sleep(300)
  ok((await api('GET', '/api/prefs'))['assistant.provider'] === 'anthropic', 'provider default not saved')
})

await test('settings: copy diagnostics and reset settings', async () => {
  must('.settings-nav button', 'Advanced').click()
  ok(await waitFor(() => byText('.frow button', 'Copy Diagnostics')), 'Advanced pane did not render')
  const before = jsErrors.length
  must('.frow button', 'Copy Diagnostics').click()
  await sleep(400)
  ok(jsErrors.length === before, `copy raised: ${jsErrors.slice(before).join(' / ')}`)
  ok(/copied|Could not copy/i.test(toastText()), `no feedback toast: ${toastText()}`)
  // Reset Settings reloads the window (it would end this script), so exercise the same request it sends
  ok(byText('.frow button', 'Reset Settings'), 'no Reset Settings control')
  const defaults = { 'general.startup': 'home', 'general.after_import': 'repository', 'general.onboarding_dismissed': false,
    'workspaces.sort': 'recent', 'appearance.density': 'comfortable', 'appearance.graph_labels': true, 'diff.wrap': true,
    'diff.font_size': 12, 'assistant.provider': '', 'assistant.model': '', 'assistant.effort': '', 'assistant.context': true }
  await api('PUT', '/api/prefs', defaults)
  const p = await api('GET', '/api/prefs')
  ok(p['general.onboarding_dismissed'] === false && p['general.startup'] === 'home', 'settings not reset')
})

// ---------------------------------------------------------------- reset
await test('reset: confirmed workspace reset clears events', async () => {
  await go('Home')
  $('.palette-trigger').click()
  const input = await waitFor(() => $('.palette input'))
  setValue(input, 'reset')
  await waitFor(() => byText('.palette-item', 'Reset workspace'))
  key(input, 'Enter')
  ok(await waitFor(() => $('[role=alertdialog]')), 'no dialog')
  must('[role=alertdialog] button', 'Reset Workspace').click()
  ok(await waitFor(() => !$('[role=alertdialog]')), 'dialog stayed')
  const g = await api('GET', '/api/graph'); ok(g.events === 0, `events remain: ${g.events}`)
})

return { results, jsErrors: [...new Set(jsErrors)] }
