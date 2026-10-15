# Building the macOS app and installer

```
cd desktop
SUPABASE_URL=... SUPABASE_ANON_KEY=... npm run dist:mac        # app, zip and DMG in desktop/dist
npm run dist:mac -- --dir                                      # unpacked .app only (faster)
npm run icons                                                  # regenerate icns/png/DMG art from build/icon-source.png and build/dmg-background.svg
```

`dist:mac` builds the UI, freezes the engine with PyInstaller (own `backend/.venv`; needs `uv`), packages with
electron-builder and writes `Paladin-<version>-<arch>.dmg` plus the `.zip` that auto-update needs. It never publishes.

## Artwork

| File | Purpose |
|---|---|
| `desktop/build/icon-source.png` | Master app icon, 1024x1024 on Apple's icon grid (824 body, soft shadow). Replace it, then `npm run icons`. |
| `desktop/build/icon.icns` | Generated from the master: Dock, Finder, Launchpad. The master PNG is also the Windows/Linux window icon. |
| `desktop/build/dmg-background.svg` / `.tiff` | Installer window art (660x400, retina TIFF generated). |
| `frontend/public/{favicon,mark,glyph}.svg` | Web favicon, in-app brand mark, single-colour glyph. Static assets traced from the original artwork (a black tile with the white glyph, and the bare glyph used as a CSS mask); there is no generator in the repo, so edit them by hand or re-trace the artwork. |

## What needs credentials

Nothing is needed for a local build; it is sealed ad hoc and opens after right-click, Open (or `xattr -cr Paladin.app`).
For a distributable build, set these and run the same command. `dist:mac` prints which are missing:

| Step | Needs |
|---|---|
| Signing | A "Developer ID Application" certificate: `CSC_LINK` (+ `CSC_KEY_PASSWORD`) or one in the login keychain |
| Notarization | `APPLE_ID`, `APPLE_APP_SPECIFIC_PASSWORD`, `APPLE_TEAM_ID` |
| Publishing updates | `GH_TOKEN` and `electron-builder --publish always` (not done by `dist:mac`) |

Apple Silicon only by default (PyInstaller does not cross-compile); build x64 on an Intel Mac.

## Automatic updates

The app looks at GitHub Releases ~5 seconds after launch and every 30 minutes, downloads a newer release in the
background and restarts into it a few seconds after the download finishes (`desktop/src/updater.js`). If an update cannot
be applied, Settings, General shows the error with a **Download Manually** button.

For this to work in practice, all of the following must hold:

1. **The releases must be readable by the installed app.** The repository is currently private, so an installed app
   gets a 404 from the GitHub releases API and sees nothing. Either make the repository public, or publish release
   artifacts to a separate public repository and point `publish:` in `electron-builder.yml` at it. Do not ship a
   GitHub token inside the app.
2. **The app must be Developer ID signed.** macOS refuses to swap in an update for an ad-hoc signed app, so until
   signing credentials are set the update downloads but cannot install, and the manual download link is shown.
3. **Every release needs** the `.zip`, the `.dmg`, `latest-mac.yml` and the `.blockmap` files from `desktop/dist`,
   and `desktop/package.json` `version` must equal the release tag (without the `v`) and be higher than the one before.

The master icon is a raster. For a sharper icon, replace `desktop/build/icon-source.png` with a native 1024x1024 export of the same art (the script rejects any other size) and run `npm run icons`.
