'use strict'
// Freeze the FastAPI app into a single self-contained binary with PyInstaller (no Python needed on the user's machine).
// PyInstaller does not cross-compile: run this on the OS you are packaging for.
const { spawnSync } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')

const root = path.resolve(__dirname, '..', '..')
const backend = path.join(root, 'backend')
const out = path.join(__dirname, '..', 'build', 'backend')
const win = process.platform === 'win32'
const py = path.join(backend, '.venv', win ? 'Scripts' : 'bin', win ? 'python.exe' : 'python')

function run(cmd, args, opts = {}) {
  const r = spawnSync(cmd, args, { stdio: 'inherit', cwd: backend, ...opts })
  if (r.status !== 0) { console.error(`failed: ${cmd} ${args.join(' ')}`); process.exit(r.status || 1) }
}

if (!fs.existsSync(py)) {
  console.error(`Missing ${py}. Create it: cd backend && uv venv .venv && uv pip install -r requirements.txt`)
  process.exit(1)
}
run('uv', ['pip', 'install', '--python', py, 'pyinstaller==6.11.1'])
fs.rmSync(out, { recursive: true, force: true })
run(py, ['-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--name', 'paladin-server',
         '--distpath', out, '--workpath', path.join(out, '..', 'pyi-work'), '--specpath', path.join(out, '..', 'pyi-work'),
         '--collect-submodules', 'app', '--collect-submodules', 'uvicorn', '--hidden-import', 'bcrypt',
         path.join(backend, 'desktop_server.py')])
// electron-builder copies build/backend/paladin-server/* into resources/backend (see electron-builder.yml)
console.log('backend built at', path.join(out, 'paladin-server'))
