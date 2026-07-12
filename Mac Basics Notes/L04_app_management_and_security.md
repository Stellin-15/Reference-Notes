# L04: App Management & Security Basics

## Installing apps

- Apps come as `.app` bundles, usually inside a `.dmg` (disk image) you download — open the `.dmg`, then drag the app icon into the **Applications** folder to "install" it.
- Mac App Store — built in, works like the Microsoft Store, for App-Store-distributed apps.
- Homebrew (see L03) — fastest way to install most everyday apps without visiting websites:
  ```bash
  brew install --cask slack spotify visual-studio-code
  ```

## Uninstalling apps

- No universal uninstaller — for most apps, just drag the app from **Applications** to the **Trash**.
- Some apps leave residual settings/cache files behind. If that bothers you, **AppCleaner** (free) removes those too — install via `brew install --cask appcleaner`.

## Gatekeeper (security prompts)

- Downloading an app outside the App Store may show: *"can't be opened because it is from an unidentified developer."*
- Fix: right-click (or Ctrl+click) the app → **Open** → confirm. Only needed the first time; after that it opens normally.

## Admin actions

- Installs, system setting changes, and some app permissions require your **password or Touch ID** — this is the Mac equivalent of Windows' UAC prompt.

## Moving from Windows

- No built-in migration tool from a Windows PC — for a fresh Mac, manually copy files over (external drive, cloud storage, or AirDrop if you have another Apple device) or use iCloud sync for photos/docs.
- If setting up a *new* Mac from an *old* Mac, **Migration Assistant** (built in) handles that automatically — just not from Windows.

## Notifications & menu bar

- Menu bar (top of screen) — always shows the active app's name and its menus (File, Edit, etc.), separate from the app's window, since one menu bar is shared across the whole system.
- Notification Center — swipe in from the right edge of the trackpad, or click the date/time in the top-right corner.
