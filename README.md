# Infinite Archer

A single-player archery roguelike. Fight waves of enemies, level up, choose abilities, and unlock classes.

---

## Quick start

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
- **Left click** — Shoot (bow) or attack (sword)
- **1** — Bow (default)
- **2** — Sword
- **Escape** — Pause

**Class abilities (when unlocked):**

- **No Class:** **R** — Dash (15 s cooldown)
- **Vampire:** **V** — Fly
- **Assassin:** **V** — Invisibility; **B** — Hit List
- **Mad Scientist:** **V** — Overcharge
- **Flame Archer:** **F** — Flame Bomb; **1** / **3** — Bow / Flamethrower
- **Robber:** **1–4** — Switch guns
- **Hacker:** Terminal at bottom of screen — click **Freeze All**, **Flame All**, **Fly Me**, **Invisible Me**, or **Teleport Me** (then click where to teleport)

**Hacker class** is unlocked by opening the in-game admin panel (enter **6543** at the title screen, then type the code shown in the panel).

---

## Troubleshooting

- **“No module named pygame”** — Install dependencies:  
  `pip install -r requirements.txt`  
  (Use the same Python that runs the game; if you use a venv, activate it first.)

- **Python 3.14** — Pygame doesn’t support 3.14 yet. Install Python 3.13 (or 3.12/3.11) and use that to create your venv and run the game.

- **Game won’t start** — Make sure you’re using Python 3.11, 3.12, or 3.13:  
  `python --version` or `python3 --version`
