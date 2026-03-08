# Infinite Archer

A single-player archery roguelike. Fight waves of enemies, level up, choose abilities, and unlock classes.

---

## Download

- **macOS (standalone app):** [itch.io](https://YOUR_ITCH_USER.itch.io/infinite-archer) — download and run **Infinite Archer.app**. (First time: right-click → Open if macOS blocks it. See [ITCHIO.md](ITCHIO.md).)
- **Source (all platforms):** [GitHub Releases](https://github.com/Breakpoint0CC/InfiniteArcher/releases/latest) — **InfiniteArcher.zip** with `game.py` and requirements.

After downloading:

1. Unzip **InfiniteArcher.zip**.
2. Open a terminal in the unzipped folder.
3. Install dependencies: `pip install -r requirements.txt`
4. Run the game: `python game.py`

---

## Quick start (run from source)

**You need:** Python 3 (3.11, 3.12, or 3.13) and pygame.

**Run the game:**

```bash
python game.py
```

If pygame is missing, the game will try to set up a virtual environment and install it for you. When that finishes, run `python game.py` again.

**Manual install (if the above doesn’t work):**

```bash
python3 -m venv venv
source venv/bin/activate   # On Windows: venv\Scripts\activate
pip install -r requirements.txt
python game.py
```

---

## How to play

- **WASD** — Move
- **Mouse** — Aim
- **Left click** — Shoot (bow) or attack (sword; Knight only)
- **1** — Bow (default)
- **2** — Sword (Knight only) or Flamethrower (Flame Archer mastery)
- **Escape** — Pause

**Class abilities (when unlocked):**

- **No Class:** **R** — Dash (15 s cooldown)
- **Vampire:** **V** — Fly
- **Assassin:** **V** — Invisibility; **B** — Hit List
- **Mad Scientist:** **V** — Overcharge
- **Flame Archer:** **F** — Flame Bomb; **1** / **2** — Bow / Flamethrower
- **Robber:** **1–4** — Switch guns (AK-47, Minigun, Shotgun, Sniper)
- **Hacker:** Terminal at bottom of screen — click **Freeze All**, **Flame All**, **Fly Me**, **Invisible Me**, or **Teleport Me** (then click where to teleport)

**Hacker class** is unlocked by opening the in-game admin panel (enter **6543** at the title screen, then type the code shown in the panel).

**Daily Challenge** — From the main menu, choose **Daily Challenge** to start a run with that day’s modifiers (e.g. Glass Cannon, Onslaught). Reach **wave 5** to earn **+75 gems** once per day (saved to your current slot).

---

## Troubleshooting

- **“No module named pygame”** — Install dependencies:  
  `pip install -r requirements.txt`  
  (Use the same Python that runs the game; if you use a venv, activate it first.)

- **Python 3.14** — Pygame doesn’t support 3.14 yet. Install Python 3.13 (or 3.12/3.11) and use that to create your venv and run the game.

- **Game won’t start** — Make sure you’re using Python 3.11, 3.12, or 3.13:  
  `python --version` or `python3 --version`

---

## Creating the download zip (for the Download link)

To build the zip that users get when they click **Download** (contains `game.py` and all requirements):

```bash
python create_release_zip.py
```

This creates **dist/InfiniteArcher.zip**. Upload that file to a [GitHub Release](https://github.com/YOUR_USERNAME/InfiniteArcher/releases) (or wherever you host it) so the download link delivers the source package.

## Building the macOS app (itch.io)

To build the standalone macOS app and upload to itch.io:

```bash
pip install -r requirements.txt
python scripts/build_macos.py
```

Then push with butler (see [ITCHIO.md](ITCHIO.md) for full steps):

```bash
butler push itch/InfiniteArcher-mac YOUR_ITCH_USER/infinite-archer:mac
```
