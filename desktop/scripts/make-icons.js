// Renders the brand artwork to every format the packaged app needs. Run from desktop/:
//   npx electron scripts/make-icons.js
// Inputs : build/icon-source.png (1024 master, Apple icon grid with its own shadow), build/dmg-background.svg (660x400)
// Outputs: build/icon.icns, build/dmg-background.png, build/dmg-background@2x.png, build/dmg-background.tiff
const { app, BrowserWindow, nativeImage } = require('electron')
const fs = require('node:fs')
const path = require('node:path')
const { execFileSync } = require('node:child_process')

const BUILD = path.join(__dirname, '..', 'build')
const ICONSET = path.join(BUILD, 'icon.iconset')
const SIZES = [[16, 1], [16, 2], [32, 1], [32, 2], [128, 1], [128, 2], [256, 1], [256, 2], [512, 1], [512, 2]]

/** Pixel size of a PNG read from its IHDR chunk, so DPI metadata cannot change the answer. */
function pngSize(file) {
  const b = fs.readFileSync(file)
  if (b.length < 24 || b.toString('ascii', 1, 4) !== 'PNG') throw new Error(`${file} is not a PNG`)
  return { width: b.readUInt32BE(16), height: b.readUInt32BE(20) }
}

async function render(svgFile, w, h) {
  const svg = fs.readFileSync(svgFile)
  const win = new BrowserWindow({ show: false, width: w, height: h, useContentSize: true, transparent: true, frame: false,
    webPreferences: { offscreen: true } })
  const page = path.join(require('node:os').tmpdir(), `paladin-render-${process.pid}-${w}.html`)
  fs.writeFileSync(page, `<body style="margin:0;background:transparent"><img width="${w}" height="${h}" src="data:image/svg+xml;base64,${svg.toString('base64')}"></body>`)
  await win.loadFile(page)
  fs.rmSync(page, { force: true })
  await new Promise((r) => setTimeout(r, 250))
  const img = await win.webContents.capturePage({ x: 0, y: 0, width: w, height: h })
  win.destroy()
  const size = img.getSize()
  return size.width === w ? img : img.resize({ width: w, height: h, quality: 'best' })
}

// closing each render window must not quit the app before the next render
app.on('window-all-closed', () => {})

app.whenReady().then(async () => {
  try {
    const source = path.join(BUILD, 'icon-source.png')
    if (!fs.existsSync(source)) throw new Error(`missing ${source}`)
    fs.rmSync(ICONSET, { recursive: true, force: true })
    fs.mkdirSync(ICONSET, { recursive: true })
    const { width, height } = pngSize(source)       // from the file header: nativeImage reports scale-adjusted sizes
    if (width !== 1024 || height !== 1024) throw new Error(`icon-source.png must be exactly 1024x1024, got ${width}x${height}`)
    const master = nativeImage.createFromPath(source)
    if (master.isEmpty()) throw new Error('icon-source.png could not be decoded')
    for (const [base, scale] of SIZES) {
      const px = base * scale
      const img = master.resize({ width: px, height: px, quality: 'best' })   // every size is a downscale of the 1024 master
      fs.writeFileSync(path.join(ICONSET, `icon_${base}x${base}${scale === 2 ? '@2x' : ''}.png`), img.toPNG())
    }
    execFileSync('iconutil', ['-c', 'icns', ICONSET, '-o', path.join(BUILD, 'icon.icns')])
    fs.rmSync(ICONSET, { recursive: true, force: true })

    const bg = path.join(BUILD, 'dmg-background.svg')
    const two = await render(bg, 1320, 800)
    const one = two.resize({ width: 660, height: 400, quality: 'best' })
    fs.writeFileSync(path.join(BUILD, 'dmg-background.png'), one.toPNG())
    fs.writeFileSync(path.join(BUILD, 'dmg-background@2x.png'), two.toPNG())
    // a multi-resolution TIFF is what Finder expects for a crisp background on retina displays
    execFileSync('tiffutil', ['-cathidpicheck', path.join(BUILD, 'dmg-background.png'), path.join(BUILD, 'dmg-background@2x.png'),
      '-out', path.join(BUILD, 'dmg-background.tiff')])
    console.log('icons written to', BUILD)
    app.exit(0)
  } catch (e) {
    console.error(e)
    app.exit(1)
  }
})
