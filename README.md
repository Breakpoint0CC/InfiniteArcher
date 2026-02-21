You need these to run Infinite Archer

Any platform
Python3
Pygame latest version recomended
Websockets also latest version recomended

How to get these requirements

Python3:
Windows: To install Python 3 on Windows, download the latest executable installer from python org
MacOS: brew install python  in terminal

Pygame:
Windows: pip install pygame in terminal
MacOS: pip3 install pygame  in terminal

Websockets:

Windows: pip install websockets  in terminal
MacOS: pip install websockets  in terminal

---

Running the server (e.g. DigitalOcean Droplet)

1. On the droplet: install Python 3, then `pip install pygame websockets`. Copy your game files (at least game.py and requirements.txt if you use it).
2. Open port 8765:
   - DigitalOcean: Networking → Firewall → add inbound rule TCP 8765.
   - On the server: `sudo ufw allow 8765` then `sudo ufw reload` (if using ufw).
3. Start the server: `python game.py --server` (or `PORT=8766 python game.py --server` to use another port).
4. On each client machine: set the server URL before launching the game, e.g. `IA_SERVER=ws://YOUR_DROPLET_IP:8765 python game.py`, or enter the URL in the game’s online menu.
5. Optional: run in background with `nohup python game.py --server &` or use a process manager (systemd, screen, tmux).