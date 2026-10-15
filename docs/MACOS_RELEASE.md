# Building the macOS app and installer

```
cd desktop
SUPABASE_URL=... SUPABASE_ANON_KEY=... npm run dist:mac        # app, zip and DMG in desktop/dist
npm run dist:mac -- --dir                                      # unpacked .app only (faster)
npm run icons                                                  # regenerate icns/png/DMG art from build/*.svg
```

`dist:mac` builds the UI, freezes the engine with PyInstaller (own `backend/.venv`; needs `uv`), packages with
electron-builder and writes `Paladin-<version>-<arch>.dmg` plus the `.zip` that auto-update needs. It never publishes.

## Artwork

| File | Purpose |
|---|---|
| `desktop/build/icon.svg` | Master app icon (1024 grid, Apple icon template). Edit this, then `npm run icons`. |
| `desktop/build/icon.icns`, `icon.png` | Generated: Dock, Finder, Launchpad, window icon. |
| `desktop/build/dmg-background.svg` / `.tiff` | Installer window art (660x400, retina TIFF generated). |
| `frontend/public/{favicon,mark,glyph}.svg` | Web favicon, in-app brand mark, single-colour glyph. |

## What needs credentials

Nothing is needed for a local build; it is sealed ad hoc and opens after right-click, Open (or `xattr -cr Paladin.app`).
For a distributable build, set these and run the same command. `dist:mac` prints which are missing:

| Step | Needs |
|---|---|
| Signing | A "Developer ID Application" certificate: `CSC_LINK` (+ `CSC_KEY_PASSWORD`) or one in the login keychain |
| Notarization | `APPLE_ID`, `APPLE_APP_SPECIFIC_PASSWORD`, `APPLE_TEAM_ID` |
| Publishing updates | `GH_TOKEN` and `electron-builder --publish always` (not done by `dist:mac`) |

Apple Silicon only by default (PyInstaller does not cross-compile); build x64 on an Intel Mac.
