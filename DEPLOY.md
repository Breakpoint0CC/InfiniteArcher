# Infinite Archer — Online mode & droplet setup

Use this to run the **game server** on a fresh DigitalOcean (or other) droplet and connect from your game client. These steps are safe and won’t overwrite system packages destructively.

---

## 1. First time on the droplet (safe setup)

SSH in (use your droplet IP and key):

```bash
ssh root@YOUR_DROPLET_IP
```

Optional but recommended: create a non-root user so you don’t run the game as root:

```bash
adduser archer
usermod -aG sudo archer
# Copy your SSH key so you can log in as archer
rsync -av ~/.ssh/ /home/archer/.ssh/
chown -R archer:archer /home/archer/.ssh
chmod 700 /home/archer/.ssh
chmod 600 /home/archer/.ssh/authorized_keys
```

Then log in as that user (from your laptop, or `su - archer`):

```bash
ssh archer@YOUR_DROPLET_IP
```

Update the system (safe; won’t “ruin” the droplet):

```bash
sudo apt update && sudo apt upgrade -y
```

Install Python and pip if needed (Ubuntu/Debian):

```bash
sudo apt install -y python3 python3-pip python3-venv
```

Open the server port so clients can connect (optional but recommended):

```bash
sudo ufw allow 8765/tcp
sudo ufw allow 22/tcp   # keep SSH
sudo ufw enable
```

---

## 2. Put the game on the droplet

From your **local machine** (where the repo is), copy the project to the droplet:

```bash
cd /path/to/InfiniteArcher
scp -r game.py requirements.txt DEPLOY.md archer@YOUR_DROPLET_IP:~/
# If you use a data dir or extra files, copy those too.
```

Or clone from Git on the droplet:

```bash
# On droplet
git clone https://github.com/YOUR_USER/InfiniteArcher.git
cd InfiniteArcher
```

---

## 3. Run the game server on the droplet

On the **droplet**:

```bash
cd ~/InfiniteArcher   # or wherever you put the files
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python game.py --server
```

You should see something like:

```text
Infinite Archer server: ws://127.0.0.1:8765 (this machine)
```

The server listens on **port 8765** on all interfaces (`0.0.0.0`), so clients can use the droplet’s **public IP** and port 8765.

To run in the background (so it keeps running after you disconnect):

```bash
nohup python game.py --server > server.log 2>&1 &
# Or use screen/tmux:
screen -S archer
python game.py --server
# Detach: Ctrl+A, D
```

---

## 4. Connect from your game client

On your **local machine** (where you run the game normally):

1. Run the game: `python game.py`
2. In the main menu, choose **Online**.
3. In the lobby, either **Host** or **Join** a game.
4. When joining, use the **droplet’s public IP** as the server address (and port **8765** if the client asks).

The server has no built-in auth; it’s for trusted play. For production you’d add a firewall (e.g. UFW above), keep the OS updated, and consider HTTPS/WSS if you add a web front end later.

---

## 5. Quick reference

| What              | Command / value        |
|-------------------|------------------------|
| Server port       | `8765`                 |
| Run server        | `python game.py --server` |
| Run in background | `nohup python game.py --server > server.log 2>&1 &` |
| Logs              | `tail -f server.log`   |
| Stop server       | `pkill -f "game.py --server"` (or kill the process) |

---

## Don’t do (so you don’t “ruin” the droplet)

- Don’t run random scripts as root without reading them.
- Don’t disable the firewall and leave every port open.
- Don’t forget to open port **8765** in the cloud firewall (DigitalOcean “Networking” → Firewall) if you use one.
