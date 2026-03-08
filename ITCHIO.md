# Publishing Infinite Archer to itch.io (macOS)

## 1. Build the macOS app

From the repo root (with Python 3.11–3.13 and dependencies installed):

```bash
pip install -r requirements.txt
python scripts/build_macos.py
```

This produces **itch/InfiniteArcher-mac/** containing `Infinite Archer.app` (or the app folder), ready to upload.

## 2. Install and authenticate butler

- Download butler: https://itch.io/docs/butler/installing.html  
  (macOS: download the macOS build and put `butler` in your PATH.)
- Log in (one-time):

```bash
butler login
```

Follow the browser prompt to link your itch.io account.

## 3. Create the itch.io project

1. On itch.io, go to **Create new project**.
2. Set the project name (e.g. **Infinite Archer**), set visibility, and save.
3. Note the project URL: `YOUR_ITCH_USER/infinite-archer` (or whatever you chose).

## 4. Push the macOS build

From the repo root:

```bash
butler push itch/InfiniteArcher-mac YOUR_ITCH_USER/infinite-archer:mac
```

Replace `YOUR_ITCH_USER` with your itch.io username and `infinite-archer` with your project slug if different. The channel name `mac` tells itch this is the macOS download; players will pick it when they choose “mac” on the project page.

## 5. First-time run on a player’s Mac (Gatekeeper)

macOS may block the app because it’s not notarized. Tell players:

- **Right-click (or Control-click) “Infinite Archer”** (or the app) → **Open** → confirm **Open** in the dialog.  
  After that, they can open it normally from the Dock or Applications.

Alternatively they can allow it in **System Settings → Privacy & Security** (e.g. “Infinite Archer was blocked” → **Open anyway**).

## 6. Updating

After changing the game or rebuilding:

```bash
python scripts/build_macos.py
butler push itch/InfiniteArcher-mac YOUR_ITCH_USER/infinite-archer:mac
```

Butler uploads only changed files, so updates are usually quick.
