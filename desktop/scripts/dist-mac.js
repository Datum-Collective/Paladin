'use strict'
// Build the macOS app and drag-to-install DMG:  npm run dist:mac            (full build)
//                                              npm run dist:mac -- --dir  (unpacked .app only, fast)
//
// Credentials are optional for a local build. With none, the app and DMG are produced unsigned and this script says
// exactly what is missing. With them, the same command signs, notarizes and staples.
//   Signing      : CSC_LINK (+ CSC_KEY_PASSWORD), or a "Developer ID Application" identity in the login keychain
//   Notarization : APPLE_ID + APPLE_APP_SPECIFIC_PASSWORD + APPLE_TEAM_ID
//   Backend build: SUPABASE_URL + SUPABASE_ANON_KEY (the publishable key only)
const { spawnSync } = require('node:child_process')
const path = require('node:path')

const desktop = path.resolve(__dirname, '..')
const env = process.env
const has = (...names) => names.every((n) => env[n])
const extra = process.argv.slice(2)

if (process.platform !== 'darwin') {
  console.error('dist:mac must run on macOS (hdiutil builds the disk image, PyInstaller does not cross-compile).')
  process.exit(1)
}

const keychain = spawnSync('security', ['find-identity', '-v', '-p', 'codesigning'], { encoding: 'utf8' })
const haveIdentity = has('CSC_LINK') || /Developer ID Application/.test(keychain.stdout || '')
const notarize = haveIdentity && has('APPLE_ID', 'APPLE_APP_SPECIFIC_PASSWORD', 'APPLE_TEAM_ID')

const args = ['electron-builder', '--mac', '--publish', 'never', ...extra]   // publishing is a separate, deliberate step
// No identity: seal the bundle ad hoc. Unsealed, macOS refuses to run the repackaged Electron binary at all.
if (!haveIdentity) args.push('-c.mac.identity=-')
args.push(`-c.mac.notarize=${notarize}`)

console.log('Paladin macOS build')
console.log(`  signing      : ${haveIdentity ? 'Developer ID identity found' : 'ad hoc only (no Developer ID identity; set CSC_LINK or add one to the keychain)'}`)
console.log(`  notarization : ${notarize ? 'enabled' : 'SKIPPED, needs a signing identity plus APPLE_ID, APPLE_APP_SPECIFIC_PASSWORD, APPLE_TEAM_ID'}`)
if (!haveIdentity) console.log('  Unsigned builds open with a Gatekeeper warning: right-click the app, then Open.')

const steps = [
  ['npm', ['run', 'build:ui']],
  ['npm', ['run', 'build:backend']],
  ['npx', args],
]
for (const [cmd, a] of steps) {
  const r = spawnSync(cmd, a, { cwd: desktop, stdio: 'inherit', env })
  if (r.status !== 0) process.exit(r.status || 1)
}
