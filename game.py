# =========================
# Infinite Archer — game.py
# FULL REPLACEMENT (PART 1/3)
# =========================
import os, sys, json, math, random, time, threading, asyncio
import wave
import io
import struct


def _ensure_dependencies():
    """Auto-install missing dependencies (pygame, websockets) then re-run."""
    try:
        import pygame  # noqa: F401
    except ImportError:
        import subprocess
        script_dir = os.path.dirname(os.path.abspath(__file__))
        req_file = os.path.join(script_dir, "requirements.txt")
        if os.path.exists(req_file):
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "-r", req_file])
        else:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "pygame", "websockets"])
        os.execv(sys.executable, [sys.executable] + sys.argv)


_ensure_dependencies()

# Headless safe mode for server (no window needed)
if "--server" in sys.argv:
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

try:
    import websockets
except Exception:
    websockets = None

import pygame
pygame.init()

# ---------- CONFIG ----------
DEFAULT_WIDTH, DEFAULT_HEIGHT = 1280, 800
SAVE_SLOTS = ["save1.json", "save2.json", "save3.json"]
current_save_slot = 1  # 1..3
SETTINGS_FILE = "settings.json"

# Online defaults
ONLINE_USERNAME = os.environ.get("IA_NAME", "Player")

# Online is temporarily disabled ("online closed")
ONLINE_ENABLED = True

online_mode = False
online_coop_enemies = True  # server-authoritative enemies
net = None

# Settings (volume, fullscreen); loaded on startup
def load_settings():
    out = {"volume": 0.7, "fullscreen": True}
    try:
        if os.path.isfile(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r") as f:
                data = json.load(f)
            out["volume"] = max(0, min(1, float(data.get("volume", 0.7))))
            out["fullscreen"] = bool(data.get("fullscreen", True))
    except Exception:
        pass
    return out

def save_settings():
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings, f)
    except Exception:
        pass

settings = load_settings()

def apply_display_mode():
    global screen, WIDTH, HEIGHT
    if settings.get("fullscreen", True):
        screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        WIDTH, HEIGHT = screen.get_size()
    else:
        WIDTH, HEIGHT = DEFAULT_WIDTH, DEFAULT_HEIGHT
        screen = pygame.display.set_mode((WIDTH, HEIGHT))

def get_save_path(slot=None):
    s = current_save_slot if slot is None else int(slot)
    s = max(1, min(3, s))
    return SAVE_SLOTS[s - 1]

def get_meta_path(slot=None):
    """Separate file per slot for gems + owned classes (persists across New Game)."""
    s = current_save_slot if slot is None else int(slot)
    s = max(1, min(3, s))
    base = os.path.splitext(SAVE_SLOTS[s - 1])[0]
    return base + "_meta.json"

# Display (from settings)
apply_display_mode()

pygame.display.set_caption("Infinite Archer")
clock = pygame.time.Clock()
FPS = 60

# ---------- SOUND ----------
_sounds = {}
_mixer_ok = False
if "--server" not in sys.argv:
    try:
        pygame.mixer.init(44100, -16, 2, 512)
        _mixer_ok = True
    except Exception:
        pass

def _make_tone(freq, duration_sec=0.08, volume=0.2):
    sample_rate = 44100
    n_frames = int(sample_rate * duration_sec)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        frames = []
        for i in range(n_frames):
            s = int(32767 * volume * math.sin(2 * math.pi * freq * i / sample_rate))
            frames.append(struct.pack("h", max(-32768, min(32767, s))))
        w.writeframes(b"".join(frames))
    return buf.getvalue()

def _make_arrow_sound():
    """Short bow/arrow release: quick high-to-mid pitch, 0.05s."""
    sample_rate = 44100
    n_frames = int(sample_rate * 0.05)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        frames = []
        for i in range(n_frames):
            t = i / sample_rate
            # Slight pitch drop (320 -> 200 Hz) over 0.05s for "thwip"
            freq = 320 - (120 * t / 0.05)
            s = int(32767 * 0.2 * math.sin(2 * math.pi * freq * t))
            frames.append(struct.pack("h", max(-32768, min(32767, s))))
        w.writeframes(b"".join(frames))
    return buf.getvalue()

def _init_sounds():
    if not _mixer_ok:
        return
    try:
        _sounds["shoot"] = pygame.mixer.Sound(buffer=io.BytesIO(_make_tone(380, 0.06, 0.15)))
        _sounds["arrow"] = pygame.mixer.Sound(buffer=io.BytesIO(_make_arrow_sound()))
        _sounds["hit"] = pygame.mixer.Sound(buffer=io.BytesIO(_make_tone(180, 0.05, 0.2)))
        _sounds["levelup"] = pygame.mixer.Sound(buffer=io.BytesIO(_make_tone(520, 0.12, 0.22)))
        _sounds["death"] = pygame.mixer.Sound(buffer=io.BytesIO(_make_tone(120, 0.35, 0.3)))
        _sounds["menu_click"] = pygame.mixer.Sound(buffer=io.BytesIO(_make_tone(280, 0.04, 0.18)))
    except Exception:
        pass

if _mixer_ok:
    _init_sounds()

def play_sound(name):
    if not _mixer_ok or name not in _sounds:
        return
    try:
        vol = settings.get("volume", 0.7)
        _sounds[name].set_volume(vol)
        _sounds[name].play()
    except Exception:
        pass

# ---------- COLORS & FONTS ----------
WHITE = (255,255,255)
BLACK = (0,0,0)
RED = (220,30,30)
GREEN = (50,200,50)
YELLOW = (240,240,50)
DARK_RED = (150,0,0)
ORANGE = (255,140,0)
PURPLE = (160,32,240)
CYAN = (0,200,255)
LIGHT_GRAY = (230,230,230)
DARK_GRAY = (40,40,40)
BLUE = (40,140,255)
BROWN = (139,69,19)
ACID_YELLOW = (200,230,50)

FONT_LG = pygame.font.SysFont(None, 84)
FONT_MD = pygame.font.SysFont(None, 44)
FONT_SM = pygame.font.SysFont(None, 28)
FONT_XS = pygame.font.SysFont(None, 16)  # orb amount (small box when enemy dies)

RARITY_COLORS = {
    "Common": (0,200,0),
    "Rare": (0,100,255),
    "Advanced": (80,170,255),  # between Rare and Epic
    "Epic": (160,32,240),
    "Legendary": (255,140,0),
    "Mythical": (220,20,20)
}

ABILITY_RARITY = {
    "Heal +20 HP": "Common",
    "Damage +5": "Common",
    "Lucky": "Common",
    "Steady": "Common",
    "Vitality": "Common",
    "Tough": "Common",
    "Flame": "Rare",
    "Poison": "Rare",
    "Lightning": "Rare",
    "Frost": "Rare",
    "Bounty": "Rare",
    "Scavenger": "Rare",
    "Haste": "Rare",
    "Knockback": "Epic",
    "Piercing": "Epic",
    "Critical": "Epic",
    "Splash": "Epic",
    "Overdraw": "Epic",
    "Double Shot": "Legendary",
    "Explosive": "Legendary",
    "Vampiric": "Legendary",
    "Heartseeker": "Legendary",
    "Berserk": "Legendary",
    "Shatter": "Legendary",
    "Corrosive": "Mythical",
    "Execution": "Mythical",
}

DEFAULTS = {
    "player_size": 40,
    "player_speed": 5,
    "max_hp": 100,
    "arrow_speed": 18,
    "arrow_damage": 10,
    "sword_damage": 40,
    "sword_range": 120,
    "sword_arc_half_deg": 45,
    "base_knockback": 6,
    "enemies_per_wave_start": 5,
    "boss_hp": 5000,
    "archer_shot_damage": 10
}

# ---------- HELPERS ----------
def generate_spawn_pattern(n):
    positions = []
    margin = 80
    for _ in range(n):
        x = random.randint(margin, WIDTH - margin)
        y = random.randint(margin, HEIGHT - margin)
        positions.append((x, y))
    return positions

def draw_text_centered(font, text, y, color=BLACK, y_is_center=False):
    surf = font.render(text, True, color)
    x = WIDTH//2 - surf.get_width()//2
    if y_is_center:
        y = y - surf.get_height()//2
    screen.blit(surf, (x, y))

# ---------- UI polish constants ----------
UI_PANEL_BG = (248, 250, 252)
UI_BUTTON_BG = (235, 238, 242)
UI_BUTTON_HOVER = (220, 224, 230)
UI_BORDER = (60, 64, 72)
UI_BORDER_LIGHT = (200, 204, 212)
UI_TEXT = (28, 32, 36)
UI_TEXT_MUTED = (80, 88, 96)
UI_OVERLAY_DARK = (0, 0, 0, 180)
UI_OVERLAY_PAUSE = (0, 0, 0, 160)

def draw_button(rect, label, font=FONT_MD, hover=False, border_color=BLACK, text_color=UI_TEXT):
    """Draw a consistent button; returns nothing. Caller handles click."""
    bg = UI_BUTTON_HOVER if hover else UI_BUTTON_BG
    pygame.draw.rect(screen, bg, rect)
    pygame.draw.rect(screen, border_color, rect, 3)
    txt = font.render(label, True, text_color)
    screen.blit(txt, (rect.x + (rect.w - txt.get_width()) // 2, rect.y + (rect.h - txt.get_height()) // 2))

def wrap_text_to_width(font, text, max_pixel_width):
    """Return list of lines that fit within max_pixel_width."""
    if not text:
        return []
    words = text.split()
    lines = []
    current = []
    for w in words:
        trial = " ".join(current + [w]) if current else w
        if font.render(trial, True, BLACK).get_width() <= max_pixel_width:
            current.append(w)
        else:
            if current:
                lines.append(" ".join(current))
            current = [w] if font.render(w, True, BLACK).get_width() <= max_pixel_width else []
            if current == []:
                lines.append(w)
                current = []
    if current:
        lines.append(" ".join(current))
    return lines

# ---------- ONLINE (CLIENT) ----------
# Fixes:
# - Less lag: send input at 20hz, not every frame
# - Ghost player fix: server only broadcasts players after first input (active=True)
# - Remote arrows: server broadcasts "shots"; clients render them

class NetClient:
    def __init__(self, url):
        self.url = url
        self.id = None
        self.connected = False
        self.last_error = ""
        self.last_status = "DISCONNECTED"

        self._loop = None
        self._ws = None
        self._lock = threading.Lock()

        self.players = {}
        self.enemies = {}
        self.shots = []
        self.chat = []
        self._lobby_status = None
        self._load_result = None   # {"slot", "data", "error"} from server
        self._meta_result = None  # {"slots"} or {"slot", "data", "error"}
        self._last_send_ms = 0

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._main())

    async def _main(self):
        if websockets is None:
            self.last_status = "NO_WEBSOCKETS"
            self.last_error = "websockets package not installed"
            return

        while True:
            try:
                self.last_status = "CONNECTING"
                self.last_error = ""
                async with websockets.connect(
                    self.url,
                    ping_interval=30,
                    ping_timeout=10,
                    max_size=2_000_000,
                    open_timeout=5,
                    close_timeout=2,
                ) as ws:
                    self._ws = ws
                    self.connected = True
                    self.last_status = "CONNECTED"

                    async for msg in ws:
                        try:
                            data = json.loads(msg)
                        except Exception:
                            continue
                        t = data.get("type")
                        if t == "welcome":
                            self.last_status = "CONNECTED"
                        elif t == "hello":
                            self.id = data.get("id")
                            self.last_status = "ONLINE"
                            try:
                                await ws.send(json.dumps({"type": "identify", "username": str(ONLINE_USERNAME)[:64]}))
                            except Exception:
                                pass
                        elif t == "load_result":
                            with self._lock:
                                self._load_result = {"slot": data.get("slot"), "data": data.get("data"), "error": data.get("error")}
                        elif t == "meta_result":
                            with self._lock:
                                self._meta_result = {"slots": data.get("slots"), "slot": data.get("slot"), "data": data.get("data"), "error": data.get("error")}
                        elif t == "lobby_created":
                            with self._lock:
                                self._lobby_status = "created"
                        elif t == "lobby_joined":
                            with self._lock:
                                self._lobby_status = "joined"
                        elif t == "lobby_error":
                            with self._lock:
                                self._lobby_status = ("error", str(data.get("msg", "Unknown error")))
                        elif t == "state":
                            with self._lock:
                                self.players = data.get("players", {})
                        elif t == "enemies":
                            with self._lock:
                                self.enemies = {str(e.get("id")): e for e in data.get("enemies", [])}
                        elif t == "shots":
                            # server sends a batch of recent shots
                            shots = data.get("shots", [])
                            with self._lock:
                                self.shots = shots[-80:]  # cap
                        elif t == "chat":
                            msgs = data.get("messages", [])
                            with self._lock:
                                self.chat = msgs[-60:]

            except Exception as e:
                self.connected = False
                self._ws = None
                self.last_status = "RECONNECTING" if self.id else "DISCONNECTED"
                self.last_error = str(e)

            await asyncio.sleep(0.3)

    def send_input_throttled(self, x, y, weapon):
        if not self.connected or self._ws is None or self._loop is None:
            return
        now = pygame.time.get_ticks()
        if now - self._last_send_ms < 50:  # 20hz
            return
        self._last_send_ms = now
        payload = {"type":"input","x":float(x),"y":float(y),"weapon":weapon,"name":str(ONLINE_USERNAME)}
        try:
            asyncio.run_coroutine_threadsafe(self._ws.send(json.dumps(payload)), self._loop)
        except Exception as e:
            self.last_error = str(e)

    def send_shoot(self, x, y, vx, vy):
        if not self.connected or self._ws is None or self._loop is None:
            return
        payload = {"type":"shoot","x":float(x),"y":float(y),"vx":float(vx),"vy":float(vy)}
        try:
            asyncio.run_coroutine_threadsafe(self._ws.send(json.dumps(payload)), self._loop)
        except Exception as e:
            self.last_error = str(e)

    def send_hit(self, enemy_id, dmg):
        if not self.connected or self._ws is None or self._loop is None:
            return
        payload = {"type":"hit","enemy_id":str(enemy_id),"dmg":float(dmg)}
        try:
            asyncio.run_coroutine_threadsafe(self._ws.send(json.dumps(payload)), self._loop)
        except Exception as e:
            self.last_error = str(e)

    def send_chat(self, msg: str):
        if not self.connected or self._ws is None or self._loop is None:
            return
        payload = {"type": "chat", "msg": str(msg)[:160], "name": str(ONLINE_USERNAME)[:16]}
        try:
            asyncio.run_coroutine_threadsafe(self._ws.send(json.dumps(payload)), self._loop)
        except Exception as e:
            self.last_error = str(e)

    def send_create_lobby(self, name: str, password: str):
        if not self.connected or self._ws is None or self._loop is None:
            return
        with self._lock:
            self._lobby_status = None
        try:
            asyncio.run_coroutine_threadsafe(
                self._ws.send(json.dumps({"type": "create_lobby", "name": str(name)[:32], "password": str(password)[:32]})),
                self._loop,
            )
        except Exception as e:
            self.last_error = str(e)

    def send_join_lobby(self, name: str, password: str):
        if not self.connected or self._ws is None or self._loop is None:
            return
        with self._lock:
            self._lobby_status = None
        try:
            asyncio.run_coroutine_threadsafe(
                self._ws.send(json.dumps({"type": "join_lobby", "name": str(name)[:32], "password": str(password)[:32]})),
                self._loop,
            )
        except Exception as e:
            self.last_error = str(e)

    def get_lobby_status(self):
        with self._lock:
            out = self._lobby_status
            self._lobby_status = None
        return out

    def send_save(self, slot: int, data: dict):
        if not self.connected or self._ws is None or self._loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(
                self._ws.send(json.dumps({"type": "save", "slot": max(1, min(3, slot)), "data": data})),
                self._loop,
            )
        except Exception as e:
            self.last_error = str(e)

    def send_load(self, slot: int):
        if not self.connected or self._ws is None or self._loop is None:
            return
        with self._lock:
            self._load_result = None
        try:
            asyncio.run_coroutine_threadsafe(
                self._ws.send(json.dumps({"type": "load", "slot": max(1, min(3, slot))})),
                self._loop,
            )
        except Exception as e:
            self.last_error = str(e)

    def send_meta_get(self, slot=None):
        if not self.connected or self._ws is None or self._loop is None:
            return
        with self._lock:
            self._meta_result = None
        try:
            payload = {"type": "meta_get"}
            if slot is not None:
                payload["slot"] = max(1, min(3, slot))
            asyncio.run_coroutine_threadsafe(self._ws.send(json.dumps(payload)), self._loop)
        except Exception as e:
            self.last_error = str(e)

    def send_meta_set(self, slot: int, data: dict):
        if not self.connected or self._ws is None or self._loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(
                self._ws.send(json.dumps({"type": "meta_set", "slot": max(1, min(3, slot)), "data": data})),
                self._loop,
            )
        except Exception as e:
            self.last_error = str(e)

    def send_delete_save(self, slot: int):
        if not self.connected or self._ws is None or self._loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(
                self._ws.send(json.dumps({"type": "delete_save", "slot": max(1, min(3, slot))})),
                self._loop,
            )
        except Exception as e:
            self.last_error = str(e)

    def get_load_result(self):
        with self._lock:
            out = self._load_result
            self._load_result = None
        return out

    def get_meta_result(self):
        with self._lock:
            out = self._meta_result
            self._meta_result = None
        return out

    def snapshot(self):
        with self._lock:
            return dict(self.players), dict(self.enemies), list(self.shots), list(self.chat)

# ---------- ONLINE (SERVER) ----------
import sqlite3

SERVER_DB_PATH = "infinite_archer.db"


def _db_init():
    conn = sqlite3.connect(SERVER_DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS saves (
            user_id TEXT NOT NULL, slot INTEGER NOT NULL, data TEXT NOT NULL, updated_at REAL NOT NULL,
            PRIMARY KEY (user_id, slot));
        CREATE TABLE IF NOT EXISTS meta (
            user_id TEXT NOT NULL, slot INTEGER NOT NULL, data TEXT NOT NULL, updated_at REAL NOT NULL,
            PRIMARY KEY (user_id, slot));
    """)
    conn.commit()
    conn.close()


def _db_save(user_id, slot, data, kind):
    conn = sqlite3.connect(SERVER_DB_PATH)
    now = time.time()
    tbl = "saves" if kind == "save" else "meta"
    conn.execute(
        f"INSERT INTO {tbl} (user_id, slot, data, updated_at) VALUES (?, ?, ?, ?)"
        " ON CONFLICT(user_id, slot) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
        (user_id, slot, json.dumps(data), now),
    )
    conn.commit()
    conn.close()


def _db_load(user_id, slot, kind):
    conn = sqlite3.connect(SERVER_DB_PATH)
    tbl = "saves" if kind == "save" else "meta"
    row = conn.execute(f"SELECT data FROM {tbl} WHERE user_id = ? AND slot = ?", (user_id, slot)).fetchone()
    conn.close()
    return json.loads(row[0]) if row else None


def _db_meta_all(user_id):
    conn = sqlite3.connect(SERVER_DB_PATH)
    rows = conn.execute("SELECT slot, data FROM meta WHERE user_id = ?", (user_id,)).fetchall()
    conn.close()
    return {slot: json.loads(data) for slot, data in rows}


def _db_delete_save(user_id, slot):
    conn = sqlite3.connect(SERVER_DB_PATH)
    conn.execute("DELETE FROM saves WHERE user_id = ? AND slot = ?", (user_id, slot))
    conn.execute("DELETE FROM meta WHERE user_id = ? AND slot = ?", (user_id, slot))
    conn.commit()
    conn.close()


async def run_server(host="0.0.0.0", port=8765, tick_hz=20):
    if websockets is None:
        print("websockets not installed. Run: python -m pip install websockets")
        return

    import uuid
    _db_init()
    lobbies = {}  # lobby_id -> { name, password, connections: set(ws), players, enemies, shots, chat, wave, enemies_per_wave, next_enemy_id }
    ws_lobby = {}  # ws -> lobby_id
    ws_pid = {}    # ws -> pid
    ws_user = {}   # ws -> user_id for cloud saves

    def spawn_wave_for_lobby(lob):
        lob["enemies"] = {}
        n = int(lob["enemies_per_wave"])
        for _ in range(n):
            eid = str(lob["next_enemy_id"]); lob["next_enemy_id"] += 1
            etype = random.choices(["normal","fast","tank","archer"], weights=[50,30,10,10])[0]
            side = random.choice(["top","bottom","left","right"])
            if side == "top": x, y = random.randint(80, 1200), -40
            elif side == "bottom": x, y = random.randint(80, 1200), 900
            elif side == "left": x, y = -40, random.randint(80, 700)
            else: x, y = 1400, random.randint(80, 700)
            if etype == "normal": hp, spd = 40, 2.0
            elif etype == "fast": hp, spd = 30, 3.0
            elif etype == "tank": hp, spd = 80, 1.2
            else: hp, spd = 36, 2.0
            lob["enemies"][eid] = {"id":eid,"x":float(x),"y":float(y),"w":30,"h":30,"hp":float(hp),"etype":etype,"spd":float(spd)}

    async def handler(ws):
        pid = None
        user_id = None
        lobby_id = None
        try:
            await ws.send(json.dumps({"type": "welcome"}))
        except Exception:
            pass
        try:
            async for msg in ws:
                try:
                    data = json.loads(msg)
                except Exception:
                    continue

                t = data.get("type")

                # Must create or join lobby before any game/save messages
                if t == "create_lobby":
                    name = (data.get("name") or "").strip()[:32]
                    password = (data.get("password") or "")[:32]
                    if not name:
                        await ws.send(json.dumps({"type": "lobby_error", "msg": "Lobby name required"}))
                        continue
                    if any(l.get("name") == name for l in lobbies.values()):
                        await ws.send(json.dumps({"type": "lobby_error", "msg": "Name already taken"}))
                        continue
                    lobby_id = uuid.uuid4().hex[:12]
                    pid = uuid.uuid4().hex[:8]
                    lobbies[lobby_id] = {
                        "name": name, "password": password, "connections": {ws},
                        "players": {pid: {"x":0.0,"y":0.0,"weapon":"bow","name":"Player","active":False,"last":time.time()}},
                        "enemies": {}, "shots": [], "chat": [],
                        "wave": 1, "enemies_per_wave": 5, "next_enemy_id": 1,
                    }
                    spawn_wave_for_lobby(lobbies[lobby_id])
                    ws_lobby[ws] = lobby_id
                    ws_pid[ws] = pid
                    ws_user[ws] = pid
                    await ws.send(json.dumps({"type": "lobby_created", "lobby_id": lobby_id, "name": name}))
                    await ws.send(json.dumps({"type": "hello", "id": pid}))
                    await ws.send(json.dumps({"type": "chat", "messages": []}))
                    await ws.send(json.dumps({"type": "state", "players": {pid: lobbies[lobby_id]["players"][pid]}}))
                    await ws.send(json.dumps({"type": "enemies", "enemies": list(lobbies[lobby_id]["enemies"].values())}))
                    await ws.send(json.dumps({"type": "shots", "shots": []}))
                    continue

                if t == "join_lobby":
                    name = (data.get("name") or "").strip()[:32]
                    password = (data.get("password") or "")[:32]
                    if not name:
                        await ws.send(json.dumps({"type": "lobby_error", "msg": "Lobby name required"}))
                        continue
                    found = None
                    for lid, lob in lobbies.items():
                        if lob["name"] == name:
                            found = (lid, lob)
                            break
                    if not found:
                        await ws.send(json.dumps({"type": "lobby_error", "msg": "Lobby not found"}))
                        continue
                    lid, lob = found
                    if lob["password"] != password:
                        await ws.send(json.dumps({"type": "lobby_error", "msg": "Wrong password"}))
                        continue
                    lobby_id = lid
                    pid = uuid.uuid4().hex[:8]
                    lob["connections"].add(ws)
                    lob["players"][pid] = {"x":0.0,"y":0.0,"weapon":"bow","name":"Player","active":False,"last":time.time()}
                    ws_lobby[ws] = lobby_id
                    ws_pid[ws] = pid
                    ws_user[ws] = pid
                    await ws.send(json.dumps({"type": "lobby_joined", "lobby_id": lobby_id, "name": lob["name"]}))
                    await ws.send(json.dumps({"type": "hello", "id": pid}))
                    await ws.send(json.dumps({"type": "chat", "messages": lob["chat"][-60:]}))
                    payload_players = {p: pl for p, pl in lob["players"].items() if pl.get("active", False)}
                    await ws.send(json.dumps({"type": "state", "players": payload_players}))
                    await ws.send(json.dumps({"type": "enemies", "enemies": list(lob["enemies"].values())}))
                    await ws.send(json.dumps({"type": "shots", "shots": lob["shots"][-80:]}))
                    continue

                # From here on we must be in a lobby
                if lobby_id is None or lobby_id not in lobbies:
                    continue
                lob = lobbies[lobby_id]
                players = lob["players"]
                enemies = lob["enemies"]
                shots = lob["shots"]
                chat = lob["chat"]

                if t == "identify":
                    uname = (data.get("username") or data.get("name") or "").strip()
                    if uname:
                        ws_user[ws] = uname[:64]

                elif t == "input":
                    p = players.get(pid)
                    if not p:
                        continue
                    p["last"] = time.time()
                    if "x" in data and "y" in data:
                        p["x"] = float(data["x"])
                        p["y"] = float(data["y"])
                        p["active"] = True
                    if "weapon" in data:
                        p["weapon"] = str(data["weapon"])
                    if "name" in data and str(data["name"]).strip():
                        p["name"] = str(data["name"])[:16]
                        if ws_user.get(ws) == pid:
                            ws_user[ws] = str(data["name"]).strip()[:64]

                elif t == "save":
                    uid = ws_user.get(ws, pid)
                    slot = max(1, min(3, int(data.get("slot", 1))))
                    payload = data.get("data")
                    if isinstance(payload, dict):
                        try:
                            _db_save(uid, slot, payload, "save")
                            await ws.send(json.dumps({"type": "save_ok", "slot": slot}))
                        except Exception as e:
                            await ws.send(json.dumps({"type": "save_ok", "slot": slot, "error": str(e)}))
                    else:
                        await ws.send(json.dumps({"type": "save_ok", "slot": slot, "error": "missing data"}))

                elif t == "load":
                    uid = ws_user.get(ws, pid)
                    slot = max(1, min(3, int(data.get("slot", 1))))
                    try:
                        out = _db_load(uid, slot, "save")
                        if out is not None:
                            await ws.send(json.dumps({"type": "load_result", "slot": slot, "data": out}))
                        else:
                            await ws.send(json.dumps({"type": "load_result", "slot": slot, "error": "no_save"}))
                    except Exception as e:
                        await ws.send(json.dumps({"type": "load_result", "slot": slot, "error": str(e)}))

                elif t == "meta_get":
                    uid = ws_user.get(ws, pid)
                    slot = data.get("slot")
                    try:
                        if slot is not None:
                            slot = max(1, min(3, int(slot)))
                            out = _db_load(uid, slot, "meta")
                            await ws.send(json.dumps({"type": "meta_result", "slot": slot, "data": out}))
                        else:
                            all_meta = _db_meta_all(uid)
                            by_slot = {}
                            for s in (1, 2, 3):
                                m = all_meta.get(s)
                                by_slot[s] = {"gems": m.get("gems", 0), "player_class": m.get("player_class", "No Class")} if m else {"gems": 0, "player_class": "No Class"}
                            await ws.send(json.dumps({"type": "meta_result", "slots": by_slot}))
                    except Exception as e:
                        await ws.send(json.dumps({"type": "meta_result", "error": str(e)}))

                elif t == "meta_set":
                    uid = ws_user.get(ws, pid)
                    slot = max(1, min(3, int(data.get("slot", 1))))
                    payload = data.get("data")
                    if isinstance(payload, dict):
                        try:
                            _db_save(uid, slot, payload, "meta")
                            await ws.send(json.dumps({"type": "meta_ok", "slot": slot}))
                        except Exception as e:
                            await ws.send(json.dumps({"type": "meta_ok", "slot": slot, "error": str(e)}))

                elif t == "delete_save":
                    uid = ws_user.get(ws, pid)
                    slot = max(1, min(3, int(data.get("slot", 1))))
                    try:
                        _db_delete_save(uid, slot)
                        await ws.send(json.dumps({"type": "delete_ok", "slot": slot}))
                    except Exception as e:
                        await ws.send(json.dumps({"type": "delete_ok", "slot": slot, "error": str(e)}))

                elif t == "shoot":
                    p = players.get(pid)
                    if not p or not p.get("active", False):
                        continue
                    sx = float(data.get("x", p["x"]))
                    sy = float(data.get("y", p["y"]))
                    vx = float(data.get("vx", 0))
                    vy = float(data.get("vy", 0))
                    shots.append({"pid": pid, "x": sx, "y": sy, "vx": vx, "vy": vy, "ts": time.time()})
                    if len(shots) > 120:
                        shots[:] = shots[-120:]

                elif t == "hit":
                    eid = str(data.get("enemy_id"))
                    dmg = float(data.get("dmg", 0))
                    if eid in enemies and dmg > 0:
                        enemies[eid]["hp"] -= dmg
                        if enemies[eid]["hp"] <= 0:
                            enemies.pop(eid, None)
                elif t == "chat":
                    name = str(data.get("name") or players.get(pid, {}).get("name") or "Player")[:16]
                    msg_txt = str(data.get("msg") or "").strip()[:160]
                    if msg_txt:
                        chat.append({"name": name, "msg": msg_txt, "ts": time.time()})
                        if len(chat) > 60:
                            del chat[:-60]
                        try:
                            websockets.broadcast(lob["connections"], json.dumps({"type": "chat", "messages": chat[-60:]}))
                        except Exception:
                            pass

        finally:
            if lobby_id and lobby_id in lobbies:
                lob = lobbies[lobby_id]
                lob["connections"].discard(ws)
                if pid and pid in lob["players"]:
                    lob["players"].pop(pid, None)
                if not lob["connections"]:
                    lobbies.pop(lobby_id, None)
            ws_lobby.pop(ws, None)
            ws_pid.pop(ws, None)
            ws_user.pop(ws, None)

    async def tick_loop():
        while True:
            now = time.time()
            for lobby_id, lob in list(lobbies.items()):
                players = lob["players"]
                enemies = lob["enemies"]
                shots = lob["shots"]
                chat = lob["chat"]
                for pid in list(players.keys()):
                    if now - float(players[pid].get("last", now)) > 15:
                        players.pop(pid, None)
                actives = [p for p in players.values() if p.get("active", False)]
                if actives:
                    for e in list(enemies.values()):
                        ex = e["x"] + e["w"]/2
                        ey = e["y"] + e["h"]/2
                        best = None
                        bestd = 1e18
                        for p in actives:
                            dx = float(p["x"]) - ex
                            dy = float(p["y"]) - ey
                            d = dx*dx + dy*dy
                            if d < bestd:
                                bestd = d
                                best = p
                        if best:
                            dx = float(best["x"]) - ex
                            dy = float(best["y"]) - ey
                            dist = math.hypot(dx, dy) or 1.0
                            spd = float(e.get("spd", 2.0))
                            e["x"] += (dx/dist)*spd
                            e["y"] += (dy/dist)*spd
                if not enemies:
                    lob["wave"] += 1
                    lob["enemies_per_wave"] = max(1, int(round(lob["enemies_per_wave"]*1.10)))
                    spawn_wave_for_lobby(lob)
                payload_players = {p: pl for p, pl in players.items() if pl.get("active", False)}
                lob["shots"] = [s for s in shots if now - s.get("ts", now) < 2.0]
                lob["chat"] = [c for c in chat if now - float(c.get("ts", now)) < 600]
                if lob["connections"]:
                    try:
                        websockets.broadcast(lob["connections"], json.dumps({"type": "state", "players": payload_players}))
                        websockets.broadcast(lob["connections"], json.dumps({"type": "enemies", "enemies": list(lob["enemies"].values())}))
                        websockets.broadcast(lob["connections"], json.dumps({"type": "shots", "shots": lob["shots"]}))
                    except Exception:
                        pass
            await asyncio.sleep(1.0 / float(tick_hz))

    async with websockets.serve(handler, host, port, ping_interval=30, ping_timeout=10, max_size=2_000_000):
        print(f"Infinite Archer server running on ws://{host}:{port}")
        await tick_loop()

# ========== END PART 1 ==========



# =========================
# FULL REPLACEMENT (PART 2/3)
# =========================

# ---------- GAME CLASSES ----------
class Enemy:
    def __init__(self, rect, etype="normal", is_mini=False, hp_override=None):
        self.rect = rect
        self.etype = etype
        self.is_mini = is_mini
        self.is_boss = False

        if etype=="normal": base_hp,base_speed,base_damage,color=20,2,10,RED
        elif etype=="fast": base_hp,base_speed,base_damage,color=15,3,8,YELLOW
        elif etype=="tank": base_hp,base_speed,base_damage,color=40,1,15,DARK_RED
        elif etype=="archer": base_hp,base_speed,base_damage,color=18,2,8,CYAN
        else: base_hp,base_speed,base_damage,color=20,2,10,RED

        if is_mini:
            self.color = YELLOW
            self.speed = base_speed*2
            self.hp = hp_override if hp_override is not None else base_hp
            self.damage = base_damage
        else:
            self.color = color
            self.hp = hp_override if hp_override is not None else base_hp*2
            self.speed = base_speed
            self.damage = base_damage

        self.max_hp = self.hp
        self.burn_ms_left = 0
        self.poison_ms_left = 0
        self.slow_until_ms = 0
        self.last_status_tick = 0
        self.shoot_timer = 0
        self.shoot_interval = 1800 + random.randint(-400,400)
        self.summon_timer = 0

    def move_towards(self, tx, ty):
        dx, dy = tx - self.rect.centerx, ty - self.rect.centery
        dist = math.hypot(dx, dy)
        if dist==0: return
        spd = self.speed*(0.5 if self.poison_ms_left>0 else 1.0)
        if getattr(self, "slow_until_ms", 0) and pygame.time.get_ticks() < self.slow_until_ms:
            spd *= 0.4
        self.rect.x += round(spd*dx/dist)
        self.rect.y += round(spd*dy/dist)

    def try_shoot(self, now_ms):
        if self.etype!="archer": return None
        if now_ms - self.shoot_timer >= self.shoot_interval:
            self.shoot_timer = now_ms
            dx,dy = player.centerx - self.rect.centerx, player.centery - self.rect.centery
            d = math.hypot(dx,dy) or 1
            vx,vy = 8*dx/d, 8*dy/d
            proj = pygame.Rect(self.rect.centerx-4, self.rect.centery-4,8,8)
            return {"rect":proj,"vx":vx,"vy":vy,"damage":DEFAULTS["archer_shot_damage"]}
        return None

    def apply_status(self, now_ms):
        if self.burn_ms_left > 0 or self.poison_ms_left > 0:
            if self.last_status_tick == 0 or (now_ms - self.last_status_tick) >= 1000:
                self.last_status_tick = now_ms
                if self.burn_ms_left > 0:
                    self.hp -= 5
                    small_dots.append({"x": self.rect.centerx, "y": self.rect.top - 6, "color": ORANGE, "ttl": 40, "vy": -0.2})
                    floating_texts.append({"x": self.rect.centerx, "y": self.rect.top - 20, "txt": "-5", "color": ORANGE, "ttl": 1200, "vy": -0.6, "alpha": 255})
                    self.burn_ms_left = max(0, self.burn_ms_left - 1000)
                if self.poison_ms_left > 0:
                    self.hp -= 5
                    small_dots.append({"x": self.rect.centerx, "y": self.rect.top - 6, "color": PURPLE, "ttl": 40, "vy": -0.2})
                    floating_texts.append({"x": self.rect.centerx, "y": self.rect.top - 20, "txt": "-5", "color": PURPLE, "ttl": 1200, "vy": -0.6, "alpha": 255})
                    self.poison_ms_left = max(0, self.poison_ms_left - 1000)
        else:
            self.last_status_tick = now_ms

class Arrow:
    # Optional curving target for Mad Scientist
    def __init__(self, x, y, tx, ty, pierce=0, target=None, turn_rate=0.22, color=BLACK):
        self.rect = pygame.Rect(0,0,30,6)
        dx,dy = tx-x, ty-y
        d = math.hypot(dx,dy) or 1.0
        self.vx = DEFAULTS["arrow_speed"]*dx/d
        self.vy = DEFAULTS["arrow_speed"]*dy/d
        self.rect.center = (x, y)  # always start at player, not offset toward cursor
        self.angle = math.atan2(self.vy, self.vx)
        self.pierce_remaining = pierce
        self.target = target
        self.turn_rate = float(turn_rate)
        self.color = color

    def update(self):
        if self.target is not None:
            try:
                if getattr(self.target, "hp", 1) <= 0 or self.target not in enemies:
                    self.target = None
            except Exception:
                self.target = None

        if self.target is not None:
            tx, ty = self.target.rect.centerx, self.target.rect.centery
            dx = tx - self.rect.centerx
            dy = ty - self.rect.centery
            d = math.hypot(dx,dy) or 1.0
            desired_vx = DEFAULTS["arrow_speed"]*dx/d
            desired_vy = DEFAULTS["arrow_speed"]*dy/d
            tr = self.turn_rate
            self.vx = (1.0-tr)*self.vx + tr*desired_vx
            self.vy = (1.0-tr)*self.vy + tr*desired_vy
            sp = math.hypot(self.vx,self.vy) or 1.0
            scale = DEFAULTS["arrow_speed"]/sp
            self.vx *= scale
            self.vy *= scale

        self.rect.x += int(self.vx)
        self.rect.y += int(self.vy)
        self.angle = math.atan2(self.vy, self.vx)
        return screen.get_rect().colliderect(self.rect)

    def draw(self, surf):
        arr_surf = pygame.Surface((30,6), pygame.SRCALPHA)
        arr_surf.fill(self.color)
        rot = pygame.transform.rotate(arr_surf, -math.degrees(self.angle))
        surf.blit(rot,(self.rect.x,self.rect.y))

class EnemyArrow:
    def __init__(self,rect,vx,vy,dmg):
        self.rect = rect
        self.vx = vx
        self.vy = vy
        self.damage = dmg
    def update(self):
        self.rect.x += int(self.vx)
        self.rect.y += int(self.vy)
        return screen.get_rect().colliderect(self.rect)
    def draw(self,surf):
        pygame.draw.rect(surf,DARK_RED,self.rect)

# Remote arrow visual (friends' arrows)
class RemoteArrow:
    def __init__(self, x, y, vx, vy, ttl_ms=900):
        self.x = float(x); self.y = float(y)
        self.vx = float(vx); self.vy = float(vy)
        self.ttl = int(ttl_ms)
        self.angle = math.atan2(self.vy, self.vx)
    def update(self, dt):
        self.x += self.vx
        self.y += self.vy
        self.ttl -= dt
        self.angle = math.atan2(self.vy, self.vx)
        return (0 <= self.x <= WIDTH and 0 <= self.y <= HEIGHT and self.ttl > 0)
    def draw(self, surf):
        arr = pygame.Surface((26,5), pygame.SRCALPHA)
        arr.fill((60,160,255))
        rot = pygame.transform.rotate(arr, -math.degrees(self.angle))
        surf.blit(rot, (int(self.x), int(self.y)))

# ---------- PLAYER CLASS SYSTEM ----------
class PlayerClass:
    name = "Base"
    color = GREEN
    def on_arrow_fire(self, mx, my): return False
    def on_arrow_hit(self, enemy, damage): pass
    def on_update(self, now_ms): pass

class NoClass(PlayerClass):
    name = "No Class"
    color = (173, 216, 230)  # light blue


class FlameArcher(PlayerClass):
    name = "Flame Archer"
    color = (255, 24, 0)  # #FF1800
    def on_arrow_hit(self, enemy, damage):
        enemy.burn_ms_left = 3000
        enemy.last_status_tick = pygame.time.get_ticks()

# ----- Additional Purchasable Classes -----
class PoisonArcher(PlayerClass):
    name = "Poison Archer"
    color = PURPLE
    def on_arrow_hit(self, enemy, damage):
        enemy.poison_ms_left = 3000
        enemy.last_status_tick = pygame.time.get_ticks()

class LightningArcher(PlayerClass):
    name = "Lightning Archer"
    color = YELLOW
    def on_arrow_hit(self, enemy, damage):
        # small chain effect to up to 2 nearby enemies
        ox, oy = enemy.rect.centerx, enemy.rect.centery
        lightning_lines.append({"x1": ox, "y1": oy, "x2": ox, "y2": oy, "ttl": 200})
        others = [e for e in enemies if e is not enemy and getattr(e, "hp", 0) > 0]
        others.sort(key=lambda e: math.hypot(e.rect.centerx - ox, e.rect.centery - oy))
        hit = 0
        for e in others:
            if hit >= 2:
                break
            d = math.hypot(e.rect.centerx - ox, e.rect.centery - oy)
            if d <= 120:
                dmg2 = max(1, int(damage * 0.5))
                e.hp -= dmg2
                floating_texts.append({"x": e.rect.centerx, "y": e.rect.top-12, "txt": f"-{dmg2}", "color": YELLOW, "ttl": 1000, "vy": -0.6, "alpha": 255})
                lightning_lines.append({"x1": ox, "y1": oy, "x2": e.rect.centerx, "y2": e.rect.centery, "ttl": 260})
                hit += 1

class Ranger(PlayerClass):
    name = "Ranger"
    color = (40, 180, 120)
    # built-in double shot (doesn't require the Double Shot ability)
    def on_arrow_fire(self, mx, my):
        a1 = Arrow(player.centerx, player.centery, mx, my - 10, pierce=pierce_level)
        a2 = Arrow(player.centerx, player.centery, mx, my + 10, pierce=pierce_level)
        arrows.append(a1); arrows.append(a2)
        if online_mode and net is not None:
            net.send_shoot(player.centerx, player.centery, a1.vx, a1.vy)
            net.send_shoot(player.centerx, player.centery, a2.vx, a2.vy)
        return True

class MadScientist(PlayerClass):
    name = "Mad Scientist"
    color = (120,255,120)
    rarity_tier = "Advanced"
    SPLASH_RANGE = 100
    SPLASH_RATIO = 0.35  # 35% damage to one nearby enemy
    OVERCHARGE_DURATION_MS = 4500   # V: fire 3 homing arrows per shot
    OVERCHARGE_COOLDOWN_MS = 28000

    def on_arrow_fire(self, mx, my):
        if not enemies:
            return False
        now_ms = pygame.time.get_ticks()
        overcharge = now_ms < globals().get("mad_scientist_overcharge_until_ms", 0)
        sorted_enemies = sorted(enemies, key=lambda e: math.hypot(e.rect.centerx - player.centerx, e.rect.centery - player.centery))
        if overcharge:
            targets = (sorted_enemies * 2)[:3]  # 3 arrows, repeat closest if fewer enemies
        else:
            targets = sorted_enemies[:1]
        for t in targets:
            arrows.append(Arrow(player.centerx, player.centery, t.rect.centerx, t.rect.centery, pierce=pierce_level, target=t, turn_rate=0.24, color=BLUE))
        return True

    def on_arrow_hit(self, enemy, damage):
        # Lab splash: deal bonus damage to closest other enemy in range
        ox, oy = enemy.rect.centerx, enemy.rect.centery
        others = [e for e in enemies if e is not enemy and getattr(e, "hp", 0) > 0]
        if not others:
            return
        closest = min(others, key=lambda e: math.hypot(e.rect.centerx - ox, e.rect.centery - oy))
        d = math.hypot(closest.rect.centerx - ox, closest.rect.centery - oy)
        if d <= self.SPLASH_RANGE:
            dmg2 = max(1, int(damage * self.SPLASH_RATIO))
            closest.hp -= dmg2
            floating_texts.append({"x": closest.rect.centerx, "y": closest.rect.top - 12, "txt": f"-{dmg2}", "color": (120, 255, 120), "ttl": 1000, "vy": -0.6, "alpha": 255})
            if closest.hp <= 0:
                record_assassin_kill(closest)
                spawn_orb(closest.rect.centerx, closest.rect.centery, amount=1)
                globals()["score"] += 1
                try: enemies.remove(closest)
                except: pass

class Robber(PlayerClass):
    """Secret class: 5 guns. Unlock by clicking Gems in class shop with >= 15000 gems. Replaces bow."""
    name = "Robber"
    color = (80, 60, 40)  # dark tan
    rarity_tier = "Secret"
    def on_arrow_fire(self, mx, my):
        return True  # Robber uses guns, not bow; firing handled in game loop
    def try_deflect(self, enemy_arrow):
        return False

class Knight(PlayerClass):
    name = "Knight"
    color = (180,180,180)
    def try_deflect(self, enemy_arrow):
        if globals().get("weapon","bow") != "sword":
            return False
        try: enemy_arrows.remove(enemy_arrow)
        except: pass
        if enemies:
            closest = min(enemies, key=lambda e: math.hypot(e.rect.centerx - player.centerx, e.rect.centery - player.centery))
            arrows.append(Arrow(player.centerx, player.centery, closest.rect.centerx, closest.rect.centery, pierce=pierce_level))
        floating_texts.append({"x": player.centerx, "y": player.centery - 34, "txt": "DEFLECT!", "color": (120,120,120), "ttl": 40, "vy": -0.7, "alpha": 255})
        return True

class Vampire(PlayerClass):
    name = "Vampire"
    color = (100, 20, 40)  # dark red
    LIFESTEAL_RATIO = 0.25   # heal 25% of damage dealt
    FLY_DURATION_MS = 3000
    FLY_COOLDOWN_MS = 30000
    FLY_SPEED_MULT = 1.5
    def on_arrow_hit(self, enemy, damage):
        heal = max(1, int(damage * self.LIFESTEAL_RATIO))
        globals()["player_hp"] = min(globals()["max_hp"], globals()["player_hp"] + heal)
        floating_texts.append({"x": player.centerx, "y": player.centery - 20, "txt": f"+{heal}", "color": GREEN, "ttl": 1000, "vy": -0.6, "alpha": 255})
    def try_deflect(self, enemy_arrow):
        return False

class Assassin(PlayerClass):
    name = "Assassin"
    color = (60, 60, 80)  # dark slate
    INVIS_DURATION_MS = 5500   # ~5.5 sec (was 3)
    INVIS_COOLDOWN_MS = 30000
    KNIFE_RANGE = 70
    BACKSTAB_BOSS_DAMAGE = 100
    def try_deflect(self, enemy_arrow):
        return False

# Assassin hit list: 3 active bounties, refresh on timer
ASSASSIN_BOUNTY_REFRESH_MS = 120000  # 2 min
ASSASSIN_BOUNTY_POOL = [
    {"id": "normal_10", "name": "10 Normals", "etype": "normal", "count": 10, "reward": ("arrow_damage", 5)},
    {"id": "fast_10", "name": "10 Speedsters", "etype": "fast", "count": 10, "reward": ("speed", 1)},
    {"id": "tank_10", "name": "10 Tanks", "etype": "tank", "count": 10, "reward": ("max_hp", 10)},
    {"id": "archer_10", "name": "10 Archers", "etype": "archer", "count": 10, "reward": ("arrow_damage", 5)},
    {"id": "boss_1", "name": "1 Boss", "etype": "boss", "count": 1, "reward": ("max_hp", 15)},
]

def _pick_random_assassin_bounty():
    b = random.choice(ASSASSIN_BOUNTY_POOL)
    return {"id": b["id"], "name": b["name"], "etype": b["etype"], "count": b["count"], "reward": b["reward"], "progress": 0}

def refresh_assassin_bounties():
    global assassin_active_bounties, assassin_bounty_refresh_at_ms
    now_ms = pygame.time.get_ticks()
    assassin_active_bounties = [_pick_random_assassin_bounty() for _ in range(4)]
    assassin_bounty_refresh_at_ms = now_ms + ASSASSIN_BOUNTY_REFRESH_MS

PLAYER_CLASS_ORDER = [
    NoClass,
    FlameArcher,
    PoisonArcher,
    LightningArcher,
    Ranger,
    Knight,
    Vampire,
    Assassin,
    MadScientist,
    Robber,
]

CLASS_COSTS = {
    "No Class": 0,
    "Flame Archer": 100,
    "Poison Archer": 500,
    "Lightning Archer": 1500,
    "Ranger": 3000,
    "Knight": 2000,
    "Vampire": 4000,
    "Assassin": 5500,
    "Mad Scientist": 10000,
    "Robber": 15000,
}

ROBBER_GEM_COST = 15000
ROBBER_MIN_GEMS_TO_SHOW = 15000

def class_rarity_label(cls_name):
    if cls_name == "Robber":
        return "Secret"
    if cls_name == "Mad Scientist":
        return "Advanced"
    if cls_name in ("Knight", "Ranger", "Vampire", "Assassin"):
        return "Epic"
    if cls_name in ("Lightning Archer",):
        return "Rare"
    if cls_name in ("Poison Archer", "Flame Archer"):
        return "Uncommon"
    return "Normal"

# ---------- GLOBALS ----------
small_dots = []
floating_texts = []
lightning_lines = []
explosive_fx = []  # {cx, cy, ttl_ms} for Explosive 65px area visual
arrows = []
enemy_arrows = []
enemies = []
pending_orbs = []
remote_arrows = []  # <-- friends arrows

# Overdraw (Epic): first arrow hit each wave gets +50% damage
first_arrow_hit_this_wave = False
# Berserk (Legendary): on kill, next shot within 2.5s does +35% damage (one stack)
berserk_until_ms = 0

# Assassin hit list: 3 active bounties, refresh on timer (persists in save)
assassin_active_bounties = []
assassin_bounty_refresh_at_ms = 0
assassin_kills = {"normal": 0, "fast": 0, "tank": 0, "archer": 0, "boss": 0}
assassin_completed_bounties = set()

# Robber class: 5 guns (replaces bow)
robbers_gun = "ak47"
ROBBER_AK_INTERVAL_MS = 111   # 3x faster than ~333ms bow click = ~9/sec
ROBBER_MINIGUN_CHARGE_MS = 1670
ROBBER_MINIGUN_FIRE_DURATION_MS = 13142   # 13.141592653s
ROBBER_MINIGUN_BULLETS_PER_SEC = 25
ROBBER_MINIGUN_OVERHEAT_MS = 6767
ROBBER_MINIGUN_DAMAGE_MULT = 1.0 / 3.0
ROBBER_SHOTGUN_PELLETS = 5
ROBBER_SHOTGUN_MAGAZINE = 5
ROBBER_SHOTGUN_FIRE_INTERVAL_MS = 500   # 0.5 s between shots
ROBBER_SHOTGUN_RELOAD_MS = 2500         # 2.5 s reload after 5 shots
ROBBER_FLAME_TICK_MS = 100
ROBBER_FLAME_BURN_MS = 5000
ROBBER_FLAME_CONE_RANGE = 350           # taller/longer cone
ROBBER_FLAME_CONE_ANGLE_RAD = math.radians(60)   # narrower cone
ROBBER_FLAME_DMG_PER_TICK = 0.2   # fraction of arrow_damage per tick
ROBBER_SNIPER_INTERVAL_MS = 3142  # 3.141592653s
ROBBER_SNIPER_DAMAGE_MULT = 6.0
last_robber_ak_ms = 0
minigun_charge_start_ms = 0
minigun_firing_until_ms = 0
minigun_overheat_until_ms = 0
minigun_last_bullet_ms = 0
last_robber_sniper_ms = 0
last_robber_flame_tick_ms = 0
robber_flame_active = False  # True while flamethrower is firing (for drawing cone)
shotgun_shots_left = 5
last_shotgun_shot_ms = 0
shotgun_reload_until_ms = 0

# ---------- CHAT (client + offline) ----------
chat_open = False
chat_input = ""
chat_messages = []  # each: {"name": str, "msg": str, "ts": ms}

def add_chat_message(name: str, msg: str):
    msg = (msg or "").strip()
    if not msg:
        return
    chat_messages.append({"name": str(name)[:16], "msg": msg[:160], "ts": pygame.time.get_ticks()})
    if len(chat_messages) > 60:
        del chat_messages[:-60]

def record_assassin_kill(enemy):
    """When Assassin kills an enemy, update active bounties and grant permanent boosts for completed ones."""
    global assassin_active_bounties, assassin_completed_bounties, arrow_damage, max_hp, player_speed
    if not isinstance(player_class, Assassin) or not assassin_active_bounties:
        return
    etype = getattr(enemy, "etype", "normal")
    is_boss = getattr(enemy, "is_boss", False)
    assassin_kills[etype] = assassin_kills.get(etype, 0) + 1
    if is_boss:
        assassin_kills["boss"] = assassin_kills.get("boss", 0) + 1
    for i, slot in enumerate(assassin_active_bounties):
        key = slot["etype"]
        if key == "boss":
            if not is_boss:
                continue
        else:
            if etype != key or is_boss:
                continue
        slot["progress"] = slot.get("progress", 0) + 1
        if slot["progress"] >= slot["count"]:
            reward_type, amount = slot["reward"]
            if reward_type == "arrow_damage":
                arrow_damage += amount
                floating_texts.append({"x": player.centerx, "y": player.centery - 40, "txt": f"Bounty! +{amount} Dmg", "color": GREEN, "ttl": 1500, "vy": -0.5, "alpha": 255})
            elif reward_type == "max_hp":
                max_hp += amount
                globals()["player_hp"] = min(max_hp, globals()["player_hp"] + amount)
                floating_texts.append({"x": player.centerx, "y": player.centery - 40, "txt": f"Bounty! +{amount} HP", "color": GREEN, "ttl": 1500, "vy": -0.5, "alpha": 255})
            elif reward_type == "speed":
                player_speed += amount
                floating_texts.append({"x": player.centerx, "y": player.centery - 40, "txt": f"Bounty! +{amount} Speed", "color": GREEN, "ttl": 1500, "vy": -0.5, "alpha": 255})
            assassin_completed_bounties.add(slot["id"])
            assassin_active_bounties[i] = _pick_random_assassin_bounty()
        break  # one kill counts for one matching bounty only

# ---------- FX (floating text + particles) ----------
def update_fx(dt_ms: int):
    # floating combat text
    for ft in floating_texts[:]:
        ft["ttl"] -= dt_ms
        ft["y"] += ft.get("vy", -0.5) * (dt_ms / 16.0)

        # fade near the end
        if ft["ttl"] < 250:
            ft["alpha"] = max(0, int(255 * (ft["ttl"] / 250.0)))

        if ft["ttl"] <= 0:
            try: floating_texts.remove(ft)
            except: pass

    # tiny dot particles
    for d in small_dots[:]:
        d["ttl"] -= dt_ms
        d["y"] += d.get("vy", -0.2) * (dt_ms / 16.0)
        if d["ttl"] <= 0:
            try: small_dots.remove(d)
            except: pass

    # lightning lines (chain lightning FX)
    for ll in lightning_lines[:]:
        ll["ttl"] = ll.get("ttl", 0) - dt_ms
        if ll["ttl"] <= 0:
            try: lightning_lines.remove(ll)
            except: pass

    # explosive area FX (65px radius visual)
    for ex in explosive_fx[:]:
        ex["ttl"] = ex.get("ttl", 0) - dt_ms
        if ex["ttl"] <= 0:
            try: explosive_fx.remove(ex)
            except: pass

def draw_fx(surface):
    # dots first
    for d in small_dots:
        pygame.draw.circle(surface, d.get("color", BLACK),
                           (int(d.get("x", 0)), int(d.get("y", 0))), 3)

    # lightning lines (chain lightning)
    for ll in lightning_lines:
        ttl = int(ll.get("ttl", 0))
        if ttl <= 0:
            continue
        alpha = min(255, 80 + ttl // 2)
        x1, y1 = int(ll.get("x1", 0)), int(ll.get("y1", 0))
        x2, y2 = int(ll.get("x2", 0)), int(ll.get("y2", 0))
        min_x, min_y = min(x1, x2) - 2, min(y1, y2) - 2
        w = max(abs(x2 - x1), 1) + 4
        h = max(abs(y2 - y1), 1) + 4
        line_surf = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.line(line_surf, (*YELLOW, alpha), (x1 - min_x, y1 - min_y), (x2 - min_x, y2 - min_y), 4)
        surface.blit(line_surf, (min_x, min_y))

    # explosive area (65px radius)
    for ex in explosive_fx:
        ttl = int(ex.get("ttl", 0))
        if ttl <= 0:
            continue
        cx, cy = int(ex.get("cx", 0)), int(ex.get("cy", 0))
        alpha = min(255, 80 + ttl // 2)
        color = (255, 180, 80)
        surf = pygame.Surface((132, 132), pygame.SRCALPHA)
        pygame.draw.circle(surf, (*color, alpha), (66, 66), 65, 4)
        surface.blit(surf, (cx - 66, cy - 66))

    # floating text (damage numbers, etc.) — with outline for readability
    for ft in floating_texts:
        txt = str(ft.get("txt", ""))
        if not txt:
            continue
        color = ft.get("color", BLACK)
        alpha = int(ft.get("alpha", 255))
        x, y = int(ft.get("x", 0)), int(ft.get("y", 0))
        surf_main = FONT_SM.render(txt, True, color)
        surf_outline = FONT_SM.render(txt, True, BLACK)
        if alpha < 255:
            surf_main = surf_main.convert_alpha()
            surf_main.set_alpha(alpha)
            surf_outline = surf_outline.convert_alpha()
            surf_outline.set_alpha(alpha)
        for dx, dy in ((-1,0),(1,0),(0,-1),(0,1),(-1,-1),(-1,1),(1,-1),(1,1)):
            surface.blit(surf_outline, (x + dx, y + dy))
        surface.blit(surf_main, (x, y))

def draw_chat(surface):
    # show last few messages
    lines = chat_messages[-6:]
    if not lines and not chat_open:
        return

    pad = 10
    box_w = min(520, WIDTH - 24)
    box_h = 160 if chat_open else 120
    x = 12
    y = HEIGHT - box_h - 12

    bg = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
    bg.fill((0, 0, 0, 140))
    surface.blit(bg, (x, y))

    ty = y + pad
    for m in lines:
        name = str(m.get("name", ""))
        msg = str(m.get("msg", ""))
        r = FONT_SM.render(f"{name}: {msg}", True, WHITE)
        surface.blit(r, (x + pad, ty))
        ty += 22

    if chat_open:
        hint = FONT_SM.render("Enter to send • Esc to close", True, (180, 180, 180))
        surface.blit(hint, (x + pad, y + box_h - 54))
        prompt = FONT_SM.render("> " + chat_input, True, (220, 220, 220))
        surface.blit(prompt, (x + pad, y + box_h - 30))

admin_unlocked = False
admin_available_next_game = False
admin_god_mode = False  # when True, player takes no damage (admin panel toggle)
bg_color = WHITE

# save-slot meta shown in menus (from meta file; persists across New Game)
slot_meta_cache = {1: {"gems":0,"player_class":"No Class"},
                   2: {"gems":0,"player_class":"No Class"},
                   3: {"gems":0,"player_class":"No Class"}}

def load_slot_meta(slot):
    """Read meta for menu display. When online, use cache (filled by refresh_all_slot_meta)."""
    slot = int(slot)
    if online_mode and net is not None and net.connected:
        return slot_meta_cache.get(slot, {"gems": 0, "player_class": "No Class"})
    path = get_meta_path(slot)
    if not os.path.exists(path):
        # Fallback: read from run save file if no meta file yet
        run_path = get_save_path(slot)
        if os.path.exists(run_path):
            try:
                with open(run_path, "r") as f:
                    data = json.load(f)
                meta = {"gems": int(data.get("gems", 0)), "player_class": str(data.get("player_class", "No Class"))}
                slot_meta_cache[slot] = meta
                return meta
            except Exception:
                pass
        slot_meta_cache[slot] = {"gems": 0, "player_class": "No Class"}
        return slot_meta_cache[slot]
    try:
        with open(path, "r") as f:
            data = json.load(f)
        meta = {"gems": int(data.get("gems", 0)), "player_class": str(data.get("player_class", "No Class"))}
        slot_meta_cache[slot] = meta
        return meta
    except Exception:
        slot_meta_cache[slot] = {"gems": 0, "player_class": "No Class"}
        return slot_meta_cache[slot]

def refresh_all_slot_meta():
    if online_mode and net is not None and net.connected:
        net.send_meta_get(None)
        for _ in range(100):  # ~5 sec at 20 fps
            pygame.event.pump()
            r = net.get_meta_result()
            if r is not None and r.get("slots"):
                for s, m in r["slots"].items():
                    slot_meta_cache[int(s)] = {"gems": int(m.get("gems", 0)), "player_class": str(m.get("player_class", "No Class"))}
                return
            clock.tick(20)
    for s in (1, 2, 3):
        load_slot_meta(s)

def confirm_popup(message, yes_text="Yes", no_text="No"):
    """Blocking modal: show message and Yes/No buttons. Returns True if Yes, False if No/Esc."""
    panel_w, panel_h = 420, 180
    panel = pygame.Rect(WIDTH//2 - panel_w//2, HEIGHT//2 - panel_h//2, panel_w, panel_h)
    btn_w, btn_h = 110, 44
    yes_rect = pygame.Rect(panel.centerx - btn_w - 24, panel.bottom - btn_h - 28, btn_w, btn_h)
    no_rect = pygame.Rect(panel.centerx + 24, panel.bottom - btn_h - 28, btn_w, btn_h)
    while True:
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill(UI_OVERLAY_DARK)
        screen.blit(overlay, (0, 0))
        pygame.draw.rect(screen, UI_PANEL_BG, panel)
        pygame.draw.rect(screen, UI_BORDER, panel, 4)
        mx, my = pygame.mouse.get_pos()
        lines = wrap_text_to_width(FONT_MD, message, panel_w - 48)
        y = panel.y + 28
        for line in lines:
            t = FONT_MD.render(line, True, UI_TEXT)
            screen.blit(t, (panel.centerx - t.get_width()//2, y))
            y += t.get_height() + 6
        draw_button(yes_rect, yes_text, hover=yes_rect.collidepoint(mx, my), text_color=UI_TEXT)
        draw_button(no_rect, no_text, hover=no_rect.collidepoint(mx, my), text_color=UI_TEXT)
        pygame.display.flip()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return False
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                return False
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if yes_rect.collidepoint(ev.pos):
                    play_sound("menu_click")
                    return True
                if no_rect.collidepoint(ev.pos):
                    play_sound("menu_click")
                    return False
        clock.tick(FPS)

def delete_save_slot(slot):
    """Delete save and meta for the given slot (1–3). When online, tell server."""
    global slot_meta_cache
    s = max(1, min(3, int(slot)))
    if online_mode and net is not None and net.connected:
        net.send_delete_save(s)
    else:
        save_path = get_save_path(s)
        meta_path = get_meta_path(s)
        for path in (save_path, meta_path):
            if os.path.isfile(path):
                try:
                    os.remove(path)
                except Exception:
                    pass
    slot_meta_cache[s] = {"gems": 0, "player_class": "No Class"}
    refresh_all_slot_meta()

def load_meta_into_game():
    """Load gems, owned_classes, player_class from current slot (file or server when online)."""
    global gems, owned_classes, player_class
    if online_mode and net is not None and net.connected:
        net.send_meta_get(current_save_slot)
        for _ in range(100):  # ~5 sec at 20 fps
            pygame.event.pump()
            r = net.get_meta_result()
            if r is not None and r.get("data"):
                data = r["data"]
                gems = int(data.get("gems", 0))
                raw = data.get("owned_classes", [])
                owned_classes.clear()
                if isinstance(raw, list):
                    for c in raw:
                        if isinstance(c, str) and c.strip():
                            owned_classes.add(c.strip())
                if not owned_classes:
                    owned_classes.add("No Class")
                class_name = str(data.get("player_class", "No Class"))
                if class_name not in owned_classes:
                    owned_classes.add(class_name)
                for cls in PLAYER_CLASS_ORDER:
                    if cls.name == class_name:
                        player_class = cls()
                        return
                player_class = NoClass()
                return
            clock.tick(20)
        return
    path = get_meta_path()
    if not os.path.exists(path):
        return
    try:
        with open(path, "r") as f:
            data = json.load(f)
        gems = int(data.get("gems", 0))
        raw = data.get("owned_classes", [])
        owned_classes.clear()
        if isinstance(raw, list):
            for c in raw:
                if isinstance(c, str) and c.strip():
                    owned_classes.add(c.strip())
        if not owned_classes:
            owned_classes.add("No Class")
        class_name = str(data.get("player_class", "No Class"))
        if class_name not in owned_classes:
            owned_classes.add(class_name)
        for cls in PLAYER_CLASS_ORDER:
            if cls.name == class_name:
                player_class = cls()
                return
        player_class = NoClass()
    except Exception:
        pass

def save_meta():
    """Write current slot's meta (gems, owned_classes, player_class). When online, send to server."""
    try:
        existing_classes = set()
        if not (online_mode and net is not None and net.connected) and os.path.exists(get_meta_path()):
            try:
                with open(get_meta_path(), "r") as f:
                    existing = json.load(f)
                for c in existing.get("owned_classes", []):
                    if isinstance(c, str) and c.strip():
                        existing_classes.add(c.strip())
            except Exception:
                pass
        merged = existing_classes | (owned_classes if owned_classes else {player_class.name})
        classes_to_save = list(merged)
        data = {"gems": gems, "owned_classes": classes_to_save, "player_class": player_class.name}
        if online_mode and net is not None and net.connected:
            net.send_meta_set(current_save_slot, data)
            slot_meta_cache[current_save_slot] = {"gems": gems, "player_class": player_class.name}
            return
        with open(get_meta_path(), "w") as f:
            json.dump(data, f)
        load_slot_meta(current_save_slot)
    except Exception as e:
        print("Meta save failed:", e)

# ---------- Save / Load ----------
def save_game():
    global owned_classes
    try:
        classes_to_save = list(owned_classes) if owned_classes else [player_class.name]
        data = {
            "player": [player.x, player.y, player.width, player.height],
            "player_hp": player_hp,
            "max_hp": max_hp,
            "arrow_damage": arrow_damage,
            "player_exp": player_exp,
            "player_level": player_level,
            "exp_required": exp_required,
            "wave": wave,
            "score": score,
            "gems": gems,
            "pierce_level": pierce_level,
            "knockback_level": knockback_level,
            "owned_abilities": owned_abilities,
            "owned_classes": classes_to_save,
            "corrosive_level": corrosive_level,
            "enemies_per_wave": enemies_per_wave,
            "player_class": player_class.name,
            "assassin_kills": assassin_kills,
            "assassin_completed_bounties": list(assassin_completed_bounties),
            "assassin_active_bounties": assassin_active_bounties,
            "assassin_bounty_refresh_remaining_ms": max(0, assassin_bounty_refresh_at_ms - pygame.time.get_ticks()),
        }
        if online_mode and net is not None and net.connected:
            net.send_save(current_save_slot, data)
            save_meta()
            return
        with open(get_save_path(), "w") as f:
            json.dump(data, f)
        save_meta()
    except Exception as e:
        print("Save failed:", e)

def load_game():
    global player_hp, max_hp, arrow_damage, player_exp, player_level, exp_required
    global wave, score, gems, pierce_level, knockback_level, owned_abilities, owned_classes, corrosive_level
    global enemies_per_wave, player_class
    global vampire_fly_until_ms, vampire_fly_cooldown_until_ms
    global assassin_invis_until_ms, assassin_invis_cooldown_until_ms
    global assassin_kills, assassin_completed_bounties, assassin_active_bounties, assassin_bounty_refresh_at_ms

    if online_mode and net is not None and net.connected:
        net.send_load(current_save_slot)
        for _ in range(100):  # ~5 sec at 20 fps
            pygame.event.pump()
            r = net.get_load_result()
            if r is not None:
                if r.get("error") == "no_save" or r.get("data") is None:
                    return False
                data = r["data"]
                break
            clock.tick(20)
        else:
            return False
    else:
        if not os.path.exists(get_save_path()):
            return False
        try:
            with open(get_save_path(), "r") as f:
                data = json.load(f)
        except Exception:
            return False

    try:
        px, py, w, h = data.get("player", [WIDTH//2, HEIGHT//2, 40, 40])

        player.x, player.y, player.width, player.height = px,py,w,h

        player_hp = int(data.get("player_hp", DEFAULTS["max_hp"]))
        max_hp = int(data.get("max_hp", DEFAULTS["max_hp"]))
        player_hp = min(max_hp, max(1, player_hp))  # clamp to valid range
        arrow_damage = int(data.get("arrow_damage", DEFAULTS["arrow_damage"]))
        player_exp = int(data.get("player_exp", 0))
        player_level = int(data.get("player_level", 1))
        exp_required = max(1, int(data.get("exp_required", 10)))

        wave = int(data.get("wave", 1))
        score = int(data.get("score", 0))
        gems = int(data.get("gems", 0))

        pierce_level = int(data.get("pierce_level", 0))
        knockback_level = int(data.get("knockback_level", 1))
        raw_abilities = dict(data.get("owned_abilities", {}))
        # Keep only abilities that still exist (sanitize old saves that had removed abilities)
        owned_abilities = {k: bool(v) for k, v in raw_abilities.items() if k in ABILITY_RARITY}
        corrosive_level = int(data.get("corrosive_level", 0))
        enemies_per_wave = int(data.get("enemies_per_wave", DEFAULTS["enemies_per_wave_start"]))

        class_name = data.get("player_class","No Class")
        owned_classes.clear()
        raw = data.get("owned_classes", [class_name])
        if isinstance(raw, list):
            for c in raw:
                if isinstance(c, str) and c.strip():
                    owned_classes.add(c.strip())
        if not owned_classes:
            owned_classes.add("No Class")
        if class_name not in owned_classes:
            owned_classes.add(class_name)
        found = False
        for cls in PLAYER_CLASS_ORDER:
            if cls.name == class_name:
                player_class = cls()
                found = True
                break
        if not found:
            player_class = NoClass()

        enemies.clear(); arrows.clear(); enemy_arrows.clear(); pending_orbs.clear()
        remote_arrows.clear()
        floating_texts.clear(); small_dots.clear(); lightning_lines.clear(); explosive_fx.clear()
        chat_messages.clear()
        vampire_fly_until_ms = 0
        vampire_fly_cooldown_until_ms = 0
        assassin_invis_until_ms = 0
        assassin_invis_cooldown_until_ms = 0
        globals()["mad_scientist_overcharge_until_ms"] = 0
        globals()["mad_scientist_overcharge_cooldown_until_ms"] = 0
        assassin_kills = dict(data.get("assassin_kills", {"normal": 0, "fast": 0, "tank": 0, "archer": 0, "boss": 0}))
        assassin_completed_bounties = set(data.get("assassin_completed_bounties", []))
        assassin_active_bounties = list(data.get("assassin_active_bounties", []))
        for slot in assassin_active_bounties:
            if "progress" not in slot:
                slot["progress"] = 0
        now = pygame.time.get_ticks()
        assassin_bounty_refresh_at_ms = now + int(data.get("assassin_bounty_refresh_remaining_ms", 0))
        return True
    except Exception as e:
        print("Load failed:", e)
        return False

def hit_list_menu():
    """Assassin hit list: 3 bounties, timer until refresh. Close with button or Esc."""
    close_rect = pygame.Rect(WIDTH//2 - 100, HEIGHT - 80, 200, 50)
    while True:
        now_ms = pygame.time.get_ticks()
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill(UI_OVERLAY_DARK)
        screen.blit(overlay, (0, 0))
        draw_text_centered(FONT_LG, "Hit List", 50, WHITE)
        if assassin_bounty_refresh_at_ms > now_ms:
            sec = (assassin_bounty_refresh_at_ms - now_ms) // 1000
            draw_text_centered(FONT_SM, f"Refreshes in {sec}s", 110, (200, 204, 208))
        else:
            draw_text_centered(FONT_SM, "Refreshing next frame...", 110, (200, 204, 208))
        y = 160
        for slot in assassin_active_bounties:
            rwd = f"+{slot['reward'][1]} {slot['reward'][0].replace('_', ' ')}"
            line = f"{slot['name']} ({slot.get('progress', 0)}/{slot['count']}) → {rwd}"
            txt = FONT_MD.render(line, True, WHITE)
            screen.blit(txt, (WIDTH//2 - txt.get_width()//2, y))
            y += 48
        mx, my = pygame.mouse.get_pos()
        draw_button(close_rect, "Close", hover=close_rect.collidepoint(mx, my), border_color=(120, 124, 132), text_color=UI_TEXT)
        pygame.display.flip()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                return
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if close_rect.collidepoint(ev.pos):
                    play_sound("menu_click")
                    return
        clock.tick(FPS)

def pause_menu():
    """Shows Paused overlay with Resume / Save / Quit. Returns 'resume' or 'quit'."""
    btn_w, btn_h = 280, 56
    center_x = WIDTH // 2
    resume_rect = pygame.Rect(center_x - btn_w//2, HEIGHT//2 - 80, btn_w, btn_h)
    save_rect   = pygame.Rect(center_x - btn_w//2, HEIGHT//2 - 10, btn_w, btn_h)
    quit_rect   = pygame.Rect(center_x - btn_w//2, HEIGHT//2 + 60, btn_w, btn_h)
    while True:
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill(UI_OVERLAY_PAUSE)
        screen.blit(overlay, (0, 0))
        draw_text_centered(FONT_LG, "Paused", HEIGHT//2 - 180, WHITE, y_is_center=True)
        draw_text_centered(FONT_MD, f"Wave {wave}  •  Score {score}", HEIGHT//2 - 125, (220, 220, 220), y_is_center=True)
        mx, my = pygame.mouse.get_pos()
        for rect, label in [(resume_rect, "Resume"), (save_rect, "Save"), (quit_rect, "Quit to Menu")]:
            draw_button(rect, label, hover=rect.collidepoint(mx, my), border_color=(100, 104, 112), text_color=UI_TEXT)
        pygame.display.flip()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return "quit"
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                return "resume"
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if resume_rect.collidepoint(ev.pos):
                    play_sound("menu_click")
                    return "resume"
                if save_rect.collidepoint(ev.pos):
                    play_sound("menu_click")
                    save_game()
                    floating_texts.append({"x": center_x, "y": HEIGHT//2 + 120, "txt": "Saved!", "color": BLUE, "ttl": 100, "vy": -0.5, "alpha": 255})
                if quit_rect.collidepoint(ev.pos):
                    play_sound("menu_click")
                    return "quit"
        clock.tick(FPS)

# ========== END PART 2 ==========
# =========================
# FULL REPLACEMENT (PART 3/3)
# =========================

# ---------- Reset / init ----------
def reset_game():
    global player, player_hp, player_speed, max_hp
    global arrow_damage, sword_damage, sword_arc_half
    global knockback_level, pierce_level, pierce_max_level, owned_abilities, first_arrow_hit_this_wave
    global berserk_until_ms
    global wave, enemies_per_wave, score
    global weapon, gems
    global player_level, player_exp, exp_required
    global in_collection_phase, collection_start_ms, collection_duration_ms
    global spawn_pattern_positions, spawn_preview_ms, spawn_preview_active, spawn_preview_start_ms
    global corrosive_level
    global player_class
    global owned_classes
    global net, online_mode
    global vampire_fly_until_ms, vampire_fly_cooldown_until_ms
    global assassin_invis_until_ms, assassin_invis_cooldown_until_ms
    global assassin_kills, assassin_completed_bounties, assassin_active_bounties, assassin_bounty_refresh_at_ms
    global mad_scientist_overcharge_until_ms, mad_scientist_overcharge_cooldown_until_ms

    size = DEFAULTS["player_size"]
    player = pygame.Rect(WIDTH//2 - size//2, HEIGHT//2 - size//2, size, size)
    player_speed = DEFAULTS["player_speed"]
    max_hp = DEFAULTS["max_hp"]
    player_hp = max_hp

    arrow_damage = DEFAULTS["arrow_damage"]
    sword_damage = DEFAULTS["sword_damage"]
    sword_arc_half = math.radians(DEFAULTS["sword_arc_half_deg"])

    knockback_level = 1
    pierce_level = 0
    pierce_max_level = 3

    owned_abilities = {
        "Flame": False, "Poison": False, "Lightning": False, "Frost": False, "Bounty": False,
        "Scavenger": False, "Haste": False,
        "Knockback": False, "Piercing": False, "Critical": False, "Splash": False,
        "Overdraw": False,
        "Double Shot": False, "Explosive": False,
        "Vampiric": False,
        "Heartseeker": False, "Berserk": False, "Shatter": False,
        "Corrosive": False, "Execution": False,
        "Lucky": False, "Tough": False
    }

    enemies.clear(); arrows.clear(); enemy_arrows.clear(); pending_orbs.clear()
    remote_arrows.clear()
    floating_texts.clear(); small_dots.clear(); lightning_lines.clear(); explosive_fx.clear()
    chat_messages.clear()

    wave = 1
    enemies_per_wave = DEFAULTS["enemies_per_wave_start"]
    score = 0
    weapon = "bow"
    robbers_gun = "ak47"
    globals()["last_robber_ak_ms"] = 0
    globals()["minigun_charge_start_ms"] = 0
    globals()["minigun_firing_until_ms"] = 0
    globals()["minigun_overheat_until_ms"] = 0
    globals()["minigun_last_bullet_ms"] = 0
    globals()["last_robber_sniper_ms"] = 0
    globals()["last_robber_flame_tick_ms"] = 0
    globals()["shotgun_shots_left"] = ROBBER_SHOTGUN_MAGAZINE
    globals()["last_shotgun_shot_ms"] = 0
    globals()["shotgun_reload_until_ms"] = 0

    player_level = 1
    player_exp = 0
    exp_required = 10 + 10*(player_level-1)

    gems = 0
    first_arrow_hit_this_wave = False
    berserk_until_ms = 0

    in_collection_phase = False
    collection_start_ms = None
    collection_duration_ms = 5000

    spawn_pattern_positions = generate_spawn_pattern(120)
    spawn_preview_ms = 2500  # faster start
    spawn_preview_active = False
    spawn_preview_start_ms = None

    corrosive_level = 0
    player_class = NoClass()
    owned_classes = {"No Class"}

    # Load persistent meta (gems, owned classes, equipped class) so New Game keeps them
    load_meta_into_game()

    vampire_fly_until_ms = 0
    vampire_fly_cooldown_until_ms = 0
    assassin_invis_until_ms = 0
    assassin_invis_cooldown_until_ms = 0
    mad_scientist_overcharge_until_ms = 0
    mad_scientist_overcharge_cooldown_until_ms = 0
    assassin_kills = {"normal": 0, "fast": 0, "tank": 0, "archer": 0, "boss": 0}
    assassin_completed_bounties = set()
    assassin_active_bounties = []
    assassin_bounty_refresh_at_ms = 0

    # online
    if (not ONLINE_ENABLED) and online_mode:
        online_mode = False

    if ONLINE_ENABLED and online_mode and websockets is not None:
        url = os.environ.get("IA_SERVER", "ws://localhost:8765")
        net = NetClient(url)
        net.start()
    else:
        net = None

# ---------- Spawning (offline) ----------
def spawn_wave_at_positions(positions):
    enemies.clear()
    for pos in positions:
        etype = random.choices(["normal","fast","tank","archer"], weights=[50,30,10,10])[0]
        rect = pygame.Rect(pos[0]-15, pos[1]-15, 30, 30)
        enemies.append(Enemy(rect, etype))

def spawn_wave(count):
    spawn_wave_at_positions(spawn_pattern_positions[:int(count)])

def spawn_boss():
    rect = pygame.Rect(WIDTH//2 - 60, -140, 120, 120)
    boss = Enemy(rect, "tank", is_mini=False, hp_override=DEFAULTS["boss_hp"])
    boss.is_boss = True
    boss.max_hp = DEFAULTS["boss_hp"]
    boss.color = (100, 10, 60)
    boss.speed = 1.4
    boss.damage = DEFAULTS["archer_shot_damage"] * 6
    boss.summon_timer = pygame.time.get_ticks() + 4000
    enemies.append(boss)

def boss_try_summon(boss_enemy):
    now = pygame.time.get_ticks()
    if getattr(boss_enemy, "summon_timer", 0) and now >= boss_enemy.summon_timer:
        n = random.randint(4, 7)
        for _ in range(n):
            rx = boss_enemy.rect.centerx + random.randint(-100, 100)
            ry = boss_enemy.rect.centery + random.randint(-100, 100)
            rect = pygame.Rect(rx, ry, 20, 20)
            enemies.append(Enemy(rect, "fast", is_mini=True))
        boss_enemy.summon_timer = now + 4000

def draw_boss_bar(boss):
    """Draw a boss HP bar at top center when a boss is alive."""
    bar_w = min(500, WIDTH - 80)
    bar_h = 28
    x = WIDTH//2 - bar_w//2
    y = 10
    max_hp = getattr(boss, "max_hp", DEFAULTS["boss_hp"])
    frac = (boss.hp / max_hp) if max_hp > 0 else 0
    frac = max(0, min(1, frac))
    pygame.draw.rect(screen, DARK_GRAY, (x, y, bar_w, bar_h))
    pygame.draw.rect(screen, (80, 0, 40), (x, y, int(bar_w * frac), bar_h))
    pygame.draw.rect(screen, (180, 20, 80), (x, y, bar_w, bar_h), 4)
    label = FONT_SM.render("BOSS", True, WHITE)
    screen.blit(label, (x + 8, y + (bar_h - label.get_height())//2))
    hp_txt = FONT_SM.render(f"{int(boss.hp)} / {int(max_hp)}", True, WHITE)
    screen.blit(hp_txt, (x + bar_w - hp_txt.get_width() - 8, y + (bar_h - hp_txt.get_height())//2))

# ---------- FX / Orbs / UI ----------
def spawn_orb(x,y,amount=1):
    for _ in range(int(amount)):
        pending_orbs.append({"x": float(x+random.randint(-10,10)), "y": float(y+random.randint(-10,10)), "amount": 1})

def draw_hp_bar(hp):
    w, h = 300, 28
    x, y = 12, 12
    pygame.draw.rect(screen, (50, 52, 56), (x, y, w, h))
    frac = (hp / max_hp) if max_hp > 0 else 0
    pygame.draw.rect(screen, GREEN, (x, y, int(w * max(0, min(1, frac))), h))
    pygame.draw.rect(screen, UI_BORDER, (x, y, w, h), 3)

def draw_exp_bar():
    margin = 12
    w = WIDTH - margin * 2
    h = 18
    x = margin
    y = HEIGHT - h - 12
    pygame.draw.rect(screen, (50, 52, 56), (x, y, w, h))
    frac = min(1.0, player_exp / exp_required) if exp_required > 0 else 0.0
    pygame.draw.rect(screen, BLUE, (x, y, int(w * frac), h))
    pygame.draw.rect(screen, UI_BORDER, (x, y, w, h), 3)
    lvl_txt = FONT_SM.render(f"Level: {player_level}  EXP: {player_exp}/{exp_required}", True, UI_TEXT)
    screen.blit(lvl_txt, (x + 6, y - 24))

def notify_once(msg, duration=900):
    start = pygame.time.get_ticks()
    while pygame.time.get_ticks() - start < duration:
        screen.fill(bg_color)
        # Subtle panel behind message for readability
        msg_surf = FONT_LG.render(msg, True, BLACK)
        pw, ph = msg_surf.get_width() + 80, msg_surf.get_height() + 40
        pr = pygame.Rect(WIDTH//2 - pw//2, HEIGHT//2 - ph//2 - 20, pw, ph)
        pygame.draw.rect(screen, UI_PANEL_BG, pr)
        pygame.draw.rect(screen, UI_BORDER_LIGHT, pr, 3)
        draw_text_centered(FONT_LG, msg, HEIGHT//2 - 20, UI_TEXT, y_is_center=True)
        pygame.display.flip()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                save_game(); pygame.quit(); sys.exit()
        clock.tick(FPS)

# ---------- Ability choice between waves (repeat allowed) ----------
def ability_choice_between_waves():
    global player_hp, arrow_damage, knockback_level, pierce_level, corrosive_level, max_hp

    all_options = list(ABILITY_RARITY.keys())
    # Don't offer these again if already owned
    one_shot_abilities = ("Flame", "Poison", "Lightning", "Frost", "Bounty", "Scavenger", "Haste", "Double Shot", "Corrosive", "Execution", "Critical", "Splash", "Lucky", "Tough", "Overdraw", "Explosive", "Vampiric", "Heartseeker", "Berserk", "Shatter")
    def already_owned_no_repeat(ability):
        if ability in one_shot_abilities and owned_abilities.get(ability, False):
            return True
        return False
    available_options = [a for a in all_options if not already_owned_no_repeat(a)]
    if not available_options:
        available_options = all_options[:]

    rarity_weights = [("Common",45),("Rare",28),("Epic",14),("Legendary",10),("Mythical",3)]
    tiers, weights = zip(*rarity_weights)
    chosen_rarity = random.choices(tiers, weights=weights, k=1)[0]

    pool = [a for a in available_options if ABILITY_RARITY[a] == chosen_rarity]
    if not pool:
        pool = available_options[:]
    choices = random.sample(pool, min(2, len(pool)))

    def ability_display_name(ability_label):
        if ability_label == "Knockback":
            return f"Knockback (Lv {knockback_level}/5)"
        if ability_label == "Piercing":
            return f"Piercing (Lv {pierce_level}/3)"
        if ability_label == "Corrosive":
            return f"Corrosive (Lv {corrosive_level}/5)"
        if ability_label == "Execution":
            return "Execution (execute ≤45% HP)"
        if ability_label == "Critical":
            return "Critical (20% 2x dmg)"
        if ability_label == "Splash":
            return "Splash (30% dmg in 50px)"
        if ability_label == "Lucky":
            return "Lucky (10% 1.5x dmg)"
        if ability_label == "Bounty":
            return "Bounty (25% +1 gem on collect)"
        if ability_label == "Scavenger":
            return "Scavenger (20% +5 exp on collect)"
        if ability_label == "Overdraw":
            return "Overdraw (1st hit each wave +50%)"
        if ability_label == "Explosive":
            return "Explosive (25% dmg in 65px)"
        if ability_label == "Tough":
            return "Tough (+15 max HP)"
        if ability_label == "Haste":
            return "Haste (12% slow 1s on hit)"
        if ability_label == "Vampiric":
            return "Vampiric (8% lifesteal)"
        if ability_label == "Heartseeker":
            return "Heartseeker (+15% vs high HP)"
        if ability_label == "Berserk":
            return "Berserk (kill: next +35%)"
        if ability_label == "Shatter":
            return "Shatter (35% dmg in 40px)"
        return ability_label

    def ability_description(ability_label):
        descs = {
            "Heal +20 HP": "Restore 20 HP.",
            "Damage +5": "Arrows deal +5 damage.",
            "Steady": "Arrows deal +3 damage.",
            "Vitality": "Restore 15 HP.",
            "Tough": "Permanently gain 15 max HP.",
            "Lucky": "10% chance arrows deal 1.5x damage.",
            "Flame": "Arrows set enemies on fire (DoT).",
            "Poison": "Arrows poison enemies (DoT, slow).",
            "Lightning": "Chain to 2 nearby enemies (50% dmg).",
            "Frost": "Arrows slow enemies for 2s.",
            "Bounty": "25% chance +1 gem when collecting orbs.",
            "Scavenger": "20% chance +5 exp when collecting orbs.",
            "Haste": "12% chance to slow enemy 1s on hit.",
            "Knockback": "Melee pushes enemies back (level 1–5).",
            "Piercing": "Arrows pierce through enemies (level 1–3).",
            "Critical": "20% chance arrows deal 2x damage.",
            "Splash": "30% damage to enemies within 50px.",
            "Overdraw": "First arrow hit each wave deals +50%.",
            "Double Shot": "Fire 2 arrows per shot.",
            "Explosive": "25% damage to enemies within 65px.",
            "Vampiric": "Heal 8% of arrow damage dealt.",
            "Heartseeker": "+15% damage vs enemies above 70% HP.",
            "Berserk": "On kill, next shot within 2.5s deals +35%.",
            "Shatter": "35% damage to enemies within 40px.",
            "Corrosive": "Acid field around you (level 1–5).",
            "Execution": "Execute enemies at or below 45% HP.",
        }
        return descs.get(ability_label, "")

    box_width = 260
    padding_x = 12
    padding_top = 12
    gap = 10
    padding_bottom = 14
    max_text_width = box_width - padding_x * 2

    def get_button_height(label):
        display = ability_display_name(label)
        desc = ability_description(label)
        desc_short = (desc[:56] + ("…" if len(desc) > 56 else "")) if desc else ""
        title_font = FONT_MD if FONT_MD.render(display, True, BLACK).get_width() <= max_text_width else FONT_SM
        title_lines = wrap_text_to_width(title_font, display, max_text_width)
        if not title_lines:
            title_lines = [display]
        line_height = title_font.render("Ay", True, BLACK).get_height()
        title_height = len(title_lines) * line_height
        desc_lines = wrap_text_to_width(FONT_SM, desc_short, max_text_width) if desc_short else []
        desc_line_h = FONT_SM.render("Ay", True, BLACK).get_height()
        desc_height = len(desc_lines) * desc_line_h if desc_lines else 0
        return padding_top + title_height + (gap + desc_height if desc_height else 0) + padding_bottom

    need_h = max(get_button_height(c) for c in choices)
    need_h = max(need_h, 72)

    buttons = []
    for i, c in enumerate(choices):
        rect = pygame.Rect(WIDTH//2 - 220 + i*280, HEIGHT//2 - need_h//2, box_width, need_h)
        buttons.append((rect, c))

    while True:
        screen.fill(bg_color)
        draw_text_centered(FONT_LG, f"Choose an Upgrade ({chosen_rarity})", HEIGHT//2 - 160, RARITY_COLORS.get(chosen_rarity, BLUE), y_is_center=True)
        mx, my = pygame.mouse.get_pos()
        for rect, label in buttons:
            display = ability_display_name(label)
            desc = ability_description(label)
            desc_short = (desc[:56] + ("…" if len(desc) > 56 else "")) if desc else ""
            rarity = ABILITY_RARITY.get(label, "Common")
            pygame.draw.rect(screen, LIGHT_GRAY, rect)
            pygame.draw.rect(screen, RARITY_COLORS.get(rarity, BLACK), rect, 5)

            title_font = FONT_MD if FONT_MD.render(display, True, BLACK).get_width() <= max_text_width else FONT_SM
            title_lines = wrap_text_to_width(title_font, display, max_text_width)
            if not title_lines:
                title_lines = [display]
            line_height = title_font.render("Ay", True, BLACK).get_height()
            y = rect.y + padding_top
            for line in title_lines:
                txt = title_font.render(line, True, BLACK)
                screen.blit(txt, (rect.x + padding_x, y))
                y += line_height
            y += gap
            if desc_short:
                desc_lines = wrap_text_to_width(FONT_SM, desc_short, max_text_width)
                desc_line_h = FONT_SM.render("Ay", True, BLACK).get_height()
                for line in desc_lines:
                    desc_txt = FONT_SM.render(line, True, DARK_GRAY)
                    screen.blit(desc_txt, (rect.x + padding_x, y))
                    y += desc_line_h
        pygame.display.flip()

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                save_game(); pygame.quit(); sys.exit()
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                return
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                for rect,label in buttons:
                    if rect.collidepoint(mx,my):
                        if label == "Heal +20 HP":
                            player_hp = min(max_hp, player_hp + 20)
                        elif label == "Damage +5":
                            arrow_damage += 5
                        elif label == "Steady":
                            arrow_damage += 3
                        elif label == "Vitality":
                            player_hp = min(max_hp, player_hp + 15)
                        elif label == "Tough":
                            max_hp += 15
                            player_hp = min(max_hp, player_hp + 15)
                            owned_abilities["Tough"] = True
                        elif label == "Lucky":
                            owned_abilities["Lucky"] = True
                        elif label == "Flame":
                            owned_abilities["Flame"] = True
                        elif label == "Poison":
                            owned_abilities["Poison"] = True
                        elif label == "Lightning":
                            owned_abilities["Lightning"] = True
                        elif label == "Frost":
                            owned_abilities["Frost"] = True
                        elif label == "Bounty":
                            owned_abilities["Bounty"] = True
                        elif label == "Scavenger":
                            owned_abilities["Scavenger"] = True
                        elif label == "Haste":
                            owned_abilities["Haste"] = True
                        elif label == "Knockback":
                            knockback_level = min(5, knockback_level + 1)
                            owned_abilities["Knockback"] = True
                        elif label == "Piercing":
                            pierce_level = min(pierce_max_level, pierce_level + 1)
                            owned_abilities["Piercing"] = True
                        elif label == "Critical":
                            owned_abilities["Critical"] = True
                        elif label == "Splash":
                            owned_abilities["Splash"] = True
                        elif label == "Overdraw":
                            owned_abilities["Overdraw"] = True
                        elif label == "Double Shot":
                            owned_abilities["Double Shot"] = True
                        elif label == "Explosive":
                            owned_abilities["Explosive"] = True
                        elif label == "Vampiric":
                            owned_abilities["Vampiric"] = True
                        elif label == "Heartseeker":
                            owned_abilities["Heartseeker"] = True
                        elif label == "Berserk":
                            owned_abilities["Berserk"] = True
                        elif label == "Shatter":
                            owned_abilities["Shatter"] = True
                        elif label == "Corrosive":
                            owned_abilities["Corrosive"] = True
                            corrosive_level = min(5, max(1, corrosive_level + 1))
                        elif label == "Execution":
                            owned_abilities["Execution"] = True
                        return

# ---------- Combat ----------
CORROSIVE_BASE_RADIUS = 360
CORROSIVE_DPS = 12.5

def draw_corrosive_field_visual(actual_radius, alpha=80, outline=True):
    """Draw the corrosive/acid field around the player (Mythical Corrosive ability)."""
    size = int(actual_radius * 2)
    cx, cy = player.centerx, player.centery
    left = cx - actual_radius
    top = cy - actual_radius
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    surf.fill((*ACID_YELLOW, alpha))
    screen.blit(surf, (left, top))
    if outline:
        pygame.draw.rect(screen, ACID_YELLOW, (left, top, size, size), 3)

def handle_arrow_hit(enemy, dmg=None):
    global first_arrow_hit_this_wave, berserk_until_ms, player_hp
    dmg = dmg if dmg is not None else arrow_damage
    now = pygame.time.get_ticks()
    # Berserk (Legendary): consume stack for +35% damage on next shot
    if owned_abilities.get("Berserk", False) and berserk_until_ms and now < berserk_until_ms:
        dmg = int(dmg * 1.35)
        berserk_until_ms = 0
    # Overdraw (Epic): first arrow hit each wave +50% damage
    if owned_abilities.get("Overdraw", False) and not first_arrow_hit_this_wave:
        dmg = int(dmg * 1.5)
        first_arrow_hit_this_wave = True
    # Heartseeker (Legendary): +15% damage to enemies above 70% HP
    enemy_max = getattr(enemy, "max_hp", enemy.hp)
    if owned_abilities.get("Heartseeker", False) and enemy_max > 0 and enemy.hp / enemy_max > 0.70:
        dmg = int(dmg * 1.15)
    # Lucky (Common): 10% chance for 1.5x damage
    if owned_abilities.get("Lucky", False) and random.random() < 0.10:
        dmg = int(dmg * 1.5)
    # Critical (Epic): 20% chance for 2x damage
    if owned_abilities.get("Critical", False) and random.random() < 0.20:
        dmg = int(dmg * 2)
    # Execution (Mythical): enemies below 45% max HP die instantly
    executed = False
    if owned_abilities.get("Execution", False) and enemy.hp <= 0.45 * enemy_max and enemy_max > 0:
        enemy.hp = 0
        executed = True
    else:
        enemy.hp -= dmg
    play_sound("hit")
    if executed:
        floating_texts.append({"x":enemy.rect.centerx,"y":enemy.rect.top-12,"txt":"EXECUTE!","color":PURPLE,"ttl":1200,"vy":-0.6,"alpha":255})
    else:
        floating_texts.append({"x":enemy.rect.centerx,"y":enemy.rect.top-12,"txt":f"-{int(dmg)}","color":RED,"ttl":1000,"vy":-0.6,"alpha":255})

    # Vampiric (Legendary): heal 8% of arrow damage
    if owned_abilities.get("Vampiric", False) and not executed and dmg > 0:
        heal = max(1, int(dmg * 0.08))
        player_hp = min(max_hp, player_hp + heal)
        floating_texts.append({"x": player.centerx, "y": player.centery - 20, "txt": f"+{heal}", "color": GREEN, "ttl": 700, "vy": -0.5, "alpha": 255})

    try:
        player_class.on_arrow_hit(enemy, dmg)
    except:
        pass

    if owned_abilities.get("Flame", False):
        enemy.burn_ms_left = 3000
        enemy.last_status_tick = 0  # next apply_status will tick and show -5
    if owned_abilities.get("Poison", False):
        enemy.poison_ms_left = 3000
        enemy.last_status_tick = 0
    if owned_abilities.get("Frost", False):
        enemy.slow_until_ms = now + 2000
    if owned_abilities.get("Haste", False) and random.random() < 0.12:
        enemy.slow_until_ms = now + 1000

    # Lightning ability: chain to up to 2 nearby enemies (same as Lightning Archer class)
    if owned_abilities.get("Lightning", False):
        ox, oy = enemy.rect.centerx, enemy.rect.centery
        lightning_lines.append({"x1": ox, "y1": oy, "x2": ox, "y2": oy, "ttl": 200})
        others = [e for e in enemies if e is not enemy and getattr(e, "hp", 0) > 0]
        others.sort(key=lambda e: math.hypot(e.rect.centerx - ox, e.rect.centery - oy))
        hit = 0
        for e in others:
            if hit >= 2:
                break
            dist = math.hypot(e.rect.centerx - ox, e.rect.centery - oy)
            if dist <= 120:
                dmg2 = max(1, int(dmg * 0.5))
                e.hp -= dmg2
                floating_texts.append({"x": e.rect.centerx, "y": e.rect.top - 12, "txt": f"-{dmg2}", "color": YELLOW, "ttl": 1000, "vy": -0.6, "alpha": 255})
                lightning_lines.append({"x1": ox, "y1": oy, "x2": e.rect.centerx, "y2": e.rect.centery, "ttl": 260})
                hit += 1
                if e.hp <= 0:
                    record_assassin_kill(e)
                    spawn_orb(e.rect.centerx, e.rect.centery, amount=1)
                    globals()["score"] += 1
                    try: enemies.remove(e)
                    except: pass

    # Splash (Epic): 30% damage to enemies within 50px
    if owned_abilities.get("Splash", False) and dmg > 0:
        splash_dmg = max(1, int(dmg * 0.30))
        ox, oy = enemy.rect.centerx, enemy.rect.centery
        for e in enemies[:]:
            if e is enemy or getattr(e, "hp", 0) <= 0:
                continue
            dist = math.hypot(e.rect.centerx - ox, e.rect.centery - oy)
            if dist <= 50 and dist > 0:
                e.hp -= splash_dmg
                floating_texts.append({"x": e.rect.centerx, "y": e.rect.top - 12, "txt": f"-{splash_dmg}", "color": (200, 200, 255), "ttl": 900, "vy": -0.6, "alpha": 255})
                if e.hp <= 0:
                    record_assassin_kill(e)
                    spawn_orb(e.rect.centerx, e.rect.centery, amount=1)
                    globals()["score"] += 1
                    try: enemies.remove(e)
                    except: pass

    # Explosive (Legendary): 25% damage to enemies within 65px
    if owned_abilities.get("Explosive", False) and dmg > 0:
        exp_dmg = max(1, int(dmg * 0.25))
        ox, oy = enemy.rect.centerx, enemy.rect.centery
        explosive_fx.append({"cx": ox, "cy": oy, "ttl": 500})
        for e in enemies[:]:
            if e is enemy or getattr(e, "hp", 0) <= 0:
                continue
            dist = math.hypot(e.rect.centerx - ox, e.rect.centery - oy)
            if dist <= 65 and dist > 0:
                e.hp -= exp_dmg
                floating_texts.append({"x": e.rect.centerx, "y": e.rect.top - 12, "txt": f"-{exp_dmg}", "color": (255, 180, 80), "ttl": 900, "vy": -0.6, "alpha": 255})
                if e.hp <= 0:
                    record_assassin_kill(e)
                    spawn_orb(e.rect.centerx, e.rect.centery, amount=1)
                    globals()["score"] += 1
                    try: enemies.remove(e)
                    except: pass

    # Shatter (Legendary): 35% damage to enemies within 40px
    if owned_abilities.get("Shatter", False) and dmg > 0:
        shat_dmg = max(1, int(dmg * 0.35))
        ox, oy = enemy.rect.centerx, enemy.rect.centery
        for e in enemies[:]:
            if e is enemy or getattr(e, "hp", 0) <= 0:
                continue
            dist = math.hypot(e.rect.centerx - ox, e.rect.centery - oy)
            if dist <= 40 and dist > 0:
                e.hp -= shat_dmg
                floating_texts.append({"x": e.rect.centerx, "y": e.rect.top - 12, "txt": f"-{shat_dmg}", "color": (200, 100, 150), "ttl": 900, "vy": -0.6, "alpha": 255})
                if e.hp <= 0:
                    record_assassin_kill(e)
                    spawn_orb(e.rect.centerx, e.rect.centery, amount=1)
                    globals()["score"] += 1
                    try: enemies.remove(e)
                    except: pass

    if enemy.hp <= 0:
        if owned_abilities.get("Berserk", False):
            globals()["berserk_until_ms"] = now + 2500
        record_assassin_kill(enemy)
        spawn_orb(enemy.rect.centerx, enemy.rect.centery, amount=1)
        globals()["score"] += 1
        try: enemies.remove(enemy)
        except: pass

def handle_sword_attack(mx, my):
    global score, player_hp
    kb = DEFAULTS["base_knockback"] * max(1, knockback_level)
    angle_to_mouse = math.atan2(my - player.centery, mx - player.centerx)
    melee_range = Assassin.KNIFE_RANGE if isinstance(player_class, Assassin) else DEFAULTS["sword_range"]
    now_ms = pygame.time.get_ticks()
    assassin_backstab = isinstance(player_class, Assassin) and now_ms < assassin_invis_until_ms

    for enemy in enemies[:]:
        ex = enemy.rect.centerx - player.centerx
        ey = enemy.rect.centery - player.centery
        dist = math.hypot(ex, ey)
        if dist <= melee_range:
            enemy_angle = math.atan2(ey, ex)
            diff = abs((enemy_angle - angle_to_mouse + math.pi) % (2*math.pi) - math.pi)
            if diff <= math.radians(DEFAULTS["sword_arc_half_deg"]) * 1.05:
                if assassin_backstab:
                    if getattr(enemy, "is_boss", False):
                        enemy.hp -= Assassin.BACKSTAB_BOSS_DAMAGE
                        floating_texts.append({"x":enemy.rect.centerx,"y":enemy.rect.top-12,"txt":"BACKSTAB! -100","color":PURPLE,"ttl":1000,"vy":-0.6,"alpha":255})
                    else:
                        enemy.hp = 0
                        floating_texts.append({"x":enemy.rect.centerx,"y":enemy.rect.top-12,"txt":"BACKSTAB!", "color":PURPLE,"ttl":1000,"vy":-0.6,"alpha":255})
                else:
                    enemy.hp -= DEFAULTS["sword_damage"]
                    floating_texts.append({"x":enemy.rect.centerx,"y":enemy.rect.top-12,"txt":f"-{DEFAULTS['sword_damage']}","color":RED,"ttl":1000,"vy":-0.6,"alpha":255})
                    if isinstance(player_class, Vampire):
                        heal = max(1, int(DEFAULTS["sword_damage"] * Vampire.LIFESTEAL_RATIO))
                        player_hp = min(max_hp, player_hp + heal)
                        floating_texts.append({"x": player.centerx, "y": player.centery - 20, "txt": f"+{heal}", "color": GREEN, "ttl": 1000, "vy": -0.6, "alpha": 255})
                if dist != 0 and not assassin_backstab:
                    enemy.rect.x += int(kb*(ex/dist))
                    enemy.rect.y += int(kb*(ey/dist))
                if enemy.hp <= 0:
                    record_assassin_kill(enemy)
                    score += 1
                    spawn_orb(enemy.rect.centerx, enemy.rect.centery, amount=1)
                    try: enemies.remove(enemy)
                    except: pass

def shoot_bow(mx, my):
    # Class hook
    try:
        if player_class.on_arrow_fire(mx, my):
            # if online, still send the arrow event (use last created arrow velocity)
            if online_mode and net is not None and arrows:
                a = arrows[-1]
                net.send_shoot(player.centerx, player.centery, a.vx, a.vy)
            return
    except:
        pass

    play_sound("arrow")
    num_shots = 2 if owned_abilities.get("Double Shot", False) else 1
    if num_shots == 2:
        a1 = Arrow(player.centerx, player.centery, mx, my - 10, pierce=pierce_level)
        a2 = Arrow(player.centerx, player.centery, mx, my + 10, pierce=pierce_level)
        arrows.append(a1); arrows.append(a2)
        if online_mode and net is not None:
            net.send_shoot(player.centerx, player.centery, a1.vx, a1.vy)
            net.send_shoot(player.centerx, player.centery, a2.vx, a2.vy)
    else:
        a = Arrow(player.centerx, player.centery, mx, my, pierce=pierce_level)
        arrows.append(a)
        if online_mode and net is not None:
            net.send_shoot(player.centerx, player.centery, a.vx, a.vy)

def spawn_robber_bullet(mx, my, damage_mult=1.0, spread_deg=0):
    """Spawn one bullet (Arrow with damage_override) for Robber guns."""
    dx = mx - player.centerx
    dy = my - player.centery
    if spread_deg:
        ang = math.atan2(dy, dx) + math.radians(random.uniform(-spread_deg, spread_deg))
        dist = math.hypot(dx, dy) or 1.0
        tx = player.centerx + dist * math.cos(ang)
        ty = player.centery + dist * math.sin(ang)
    else:
        tx, ty = mx, my
    a = Arrow(player.centerx, player.centery, tx, ty, pierce=0)
    a.damage_override = max(1, int(arrow_damage * damage_mult))
    arrows.append(a)

def update_robber_guns(now_ms, mx, my, mouse_held, clicked):
    """Handle Robber gun firing: AK (hold), minigun (charge then auto), shotgun (5 shots, 0.5s rate, 2.5s reload), flamethrower (hold), sniper (slow)."""
    global last_robber_ak_ms, minigun_charge_start_ms, minigun_firing_until_ms, minigun_overheat_until_ms, minigun_last_bullet_ms
    global last_robber_sniper_ms, last_robber_flame_tick_ms, score, robber_flame_active
    global shotgun_shots_left, last_shotgun_shot_ms, shotgun_reload_until_ms
    robber_flame_active = False
    gun = robbers_gun
    # Shotgun: when reload finishes, refill magazine
    if shotgun_reload_until_ms and now_ms >= shotgun_reload_until_ms:
        shotgun_reload_until_ms = 0
        shotgun_shots_left = ROBBER_SHOTGUN_MAGAZINE
    # --- AK-47: automatic, 3x bow rate, hold to fire ---
    if gun == "ak47":
        if mouse_held and now_ms - last_robber_ak_ms >= ROBBER_AK_INTERVAL_MS:
            last_robber_ak_ms = now_ms
            play_sound("arrow")
            spawn_robber_bullet(mx, my, 1.0)
        return
    # --- Minigun: charge 1.67s, then 10 bullets/sec for 13.14s, then overheat 6.77s ---
    if gun == "minigun":
        if minigun_overheat_until_ms and now_ms >= minigun_overheat_until_ms:
            minigun_overheat_until_ms = 0
        if minigun_firing_until_ms and now_ms >= minigun_firing_until_ms:
            minigun_firing_until_ms = 0
            minigun_overheat_until_ms = now_ms + ROBBER_MINIGUN_OVERHEAT_MS
        if minigun_firing_until_ms and now_ms < minigun_firing_until_ms:
            if now_ms - minigun_last_bullet_ms >= 1000 // ROBBER_MINIGUN_BULLETS_PER_SEC:
                minigun_last_bullet_ms = now_ms
                play_sound("arrow")
                spawn_robber_bullet(mx, my, ROBBER_MINIGUN_DAMAGE_MULT)
        elif not minigun_overheat_until_ms or now_ms >= minigun_overheat_until_ms:
            if clicked and not minigun_charge_start_ms:
                minigun_charge_start_ms = now_ms
            if minigun_charge_start_ms:
                if not mouse_held:
                    minigun_charge_start_ms = 0
                elif now_ms - minigun_charge_start_ms >= ROBBER_MINIGUN_CHARGE_MS:
                    minigun_charge_start_ms = 0
                    minigun_firing_until_ms = now_ms + ROBBER_MINIGUN_FIRE_DURATION_MS
                    minigun_last_bullet_ms = now_ms
                    play_sound("arrow")
                    spawn_robber_bullet(mx, my, ROBBER_MINIGUN_DAMAGE_MULT)
        return
    # --- Shotgun: 5 shots, 0.5s fire rate, 5 pellets per shot, then 2.5s reload ---
    if gun == "shotgun":
        if shotgun_reload_until_ms and now_ms < shotgun_reload_until_ms:
            return
        if (clicked or mouse_held) and shotgun_shots_left > 0 and now_ms - last_shotgun_shot_ms >= ROBBER_SHOTGUN_FIRE_INTERVAL_MS:
            last_shotgun_shot_ms = now_ms
            shotgun_shots_left -= 1
            play_sound("arrow")
            for _ in range(ROBBER_SHOTGUN_PELLETS):
                spawn_robber_bullet(mx, my, 1.0, spread_deg=8)
            if shotgun_shots_left == 0:
                shotgun_reload_until_ms = now_ms + ROBBER_SHOTGUN_RELOAD_MS
        return
    # --- Flamethrower: AOE cone + 5s burn (tick every 100ms while held) ---
    if gun == "flamethrower":
        robber_flame_active = mouse_held
        if mouse_held and now_ms - last_robber_flame_tick_ms >= ROBBER_FLAME_TICK_MS:
            last_robber_flame_tick_ms = now_ms
            ang = math.atan2(my - player.centery, mx - player.centerx)
            half = ROBBER_FLAME_CONE_ANGLE_RAD / 2
            dmg = max(1, int(arrow_damage * ROBBER_FLAME_DMG_PER_TICK))
            for enemy in enemies[:]:
                ex = enemy.rect.centerx - player.centerx
                ey = enemy.rect.centery - player.centery
                dist = math.hypot(ex, ey)
                if dist > ROBBER_FLAME_CONE_RANGE:
                    continue
                eang = math.atan2(ey, ex)
                diff = abs((eang - ang + math.pi) % (2 * math.pi) - math.pi)
                if diff <= half:
                    enemy.hp -= dmg
                    enemy.burn_ms_left = ROBBER_FLAME_BURN_MS
                    enemy.last_status_tick = now_ms - 1000
                    floating_texts.append({"x": enemy.rect.centerx, "y": enemy.rect.top - 12, "txt": f"-{dmg}", "color": ORANGE, "ttl": 800, "vy": -0.5, "alpha": 255})
                    if enemy.hp <= 0:
                        record_assassin_kill(enemy)
                        score += 1
                        spawn_orb(enemy.rect.centerx, enemy.rect.centery, amount=1)
                        try: enemies.remove(enemy)
                        except: pass
        return
    # --- Sniper: 1 shot every 3.14s, 6x damage ---
    if gun == "sniper":
        if (clicked or mouse_held) and now_ms - last_robber_sniper_ms >= ROBBER_SNIPER_INTERVAL_MS:
            last_robber_sniper_ms = now_ms
            play_sound("arrow")
            spawn_robber_bullet(mx, my, ROBBER_SNIPER_DAMAGE_MULT)
        return

# ---------- Menus ----------
# Short class descriptions for shop (fits in button width)
CLASS_SHORT_DESC = {
    "No Class": "Default",
    "Flame Archer": "Burn on hit",
    "Poison Archer": "Poison DOT",
    "Lightning Archer": "Chain lightning",
    "Ranger": "Double shot",
    "Knight": "Deflect + armor",
    "Vampire": "Life steal + fly (V)",
    "Assassin": "Invis + backstab knife (V)",
    "Mad Scientist": "Homing + splash, V: Overcharge",
    "Robber": "5 guns (1–5), replaces bow",
}

def class_shop_menu():
    global gems, player_class, owned_classes
    show_robber = False  # becomes True when player clicks on Gems (if gems >= 15000)
    # Build list of classes to show (Robber only if show_robber and gems >= ROBBER_MIN_GEMS_TO_SHOW)
    def visible_classes():
        out = []
        for cls in PLAYER_CLASS_ORDER:
            if cls.name == "Robber":
                if show_robber and gems >= ROBBER_MIN_GEMS_TO_SHOW:
                    out.append(cls)
            else:
                out.append(cls)
        return out
    # Layout: fixed compact class boxes (don't grow on big screens)
    area_top = 160
    back_height = 72
    max_w = min(520, WIDTH - 80)
    gem_label_rect = None  # set each frame for click detection
    while True:
        vis = visible_classes()
        n_classes = len(vis)
        row_h = min(70, max(52, (HEIGHT - area_top - back_height) // max(n_classes, 1)))
        btn_h = row_h - 6
        y_start = area_top
        screen.fill(bg_color)
        draw_text_centered(FONT_LG, "Class Shop", 60)
        gem_txt = f"Gems: {gems}"
        gem_surf = FONT_MD.render(gem_txt, True, BLUE)
        gem_x = WIDTH//2 - gem_surf.get_width()//2
        gem_y = 118
        gem_label_rect = pygame.Rect(gem_x, gem_y - 4, gem_surf.get_width(), gem_surf.get_height() + 8)
        screen.blit(gem_surf, (gem_x, gem_y))
        if gems >= ROBBER_MIN_GEMS_TO_SHOW:
            hint = FONT_XS.render("(click gems to reveal secret class)", True, UI_TEXT_MUTED)
            screen.blit(hint, (WIDTH//2 - hint.get_width()//2, gem_y + 22))

        mx_cs, my_cs = pygame.mouse.get_pos()
        buttons = []
        for i, cls in enumerate(vis):
            y = y_start + i * row_h
            rect = pygame.Rect(WIDTH//2 - max_w//2, y, max_w, btn_h)
            cost = CLASS_COSTS[cls.name]
            selected = (player_class.name == cls.name)
            owned = (cls.name in owned_classes)
            fill = UI_BUTTON_HOVER if rect.collidepoint(mx_cs, my_cs) else UI_BUTTON_BG
            pygame.draw.rect(screen, fill, rect)
            pygame.draw.rect(screen, cls.color, rect, 5)

            rarity = class_rarity_label(cls.name)
            if selected:
                line1 = f"{cls.name} — Selected"
            elif owned:
                line1 = f"{cls.name} [{rarity}] — Owned (click to equip)"
            else:
                line1 = f"{cls.name} [{rarity}] — {cost} gems"
            line2 = CLASS_SHORT_DESC.get(cls.name, "")
            t1 = FONT_MD.render(line1[:48] + ("…" if len(line1) > 48 else ""), True, UI_TEXT)
            t2 = FONT_SM.render(line2, True, UI_TEXT_MUTED)
            screen.blit(t1, (rect.x + 12, rect.y + 6))
            screen.blit(t2, (rect.x + 12, rect.y + 34))
            buttons.append((rect, cls, cost, selected, owned))

        back_y = y_start + n_classes * row_h + 8
        back_rect = pygame.Rect(WIDTH//2 - 120, min(back_y, HEIGHT - 60), 240, 56)
        draw_button(back_rect, "Back", hover=back_rect.collidepoint(mx_cs, my_cs), text_color=UI_TEXT)
        pygame.display.flip()

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                save_game(); pygame.quit(); sys.exit()
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                save_game(); return
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                mx,my = ev.pos
                if gem_label_rect and gem_label_rect.collidepoint(mx, my) and gems >= ROBBER_MIN_GEMS_TO_SHOW:
                    show_robber = True
                    play_sound("menu_click")
                for r, cls, cost, selected, owned in buttons:
                    if r.collidepoint(mx,my):
                        play_sound("menu_click")
                        if selected:
                            return
                        if owned:
                            player_class = cls()
                            save_game()
                            notify_once(f"{cls.name} equipped!", 800)
                            return
                        if gems >= cost:
                            gems -= cost
                            owned_classes.add(cls.name)
                            player_class = cls()
                            save_game()
                            notify_once(f"{cls.name} purchased!", 800)
                            return
                        else:
                            notify_once("Not enough Gems!", 800)
                if back_rect.collidepoint(mx,my):
                    play_sound("menu_click")
                    save_game(); return

# ---------- Lobby (create / join for online) ----------
def lobby_screen():
    """Create or join a lobby with name + password. Returns 'ok' when in a lobby, 'back' to cancel."""
    lobby_name = ""
    lobby_password = ""
    focus = 0  # 0 = name, 1 = password
    bar_w = 320
    bar_h = 40
    bar_x = WIDTH//2 - bar_w//2
    name_y = HEIGHT//2 - 120
    pass_y = HEIGHT//2 - 50
    create_rect = pygame.Rect(WIDTH//2 - 110, HEIGHT//2 + 20, 100, 44)
    join_rect = pygame.Rect(WIDTH//2 + 10, HEIGHT//2 + 20, 100, 44)
    back_rect = pygame.Rect(WIDTH//2 - 60, HEIGHT//2 + 90, 120, 44)
    waiting = None  # "create" or "join" while waiting for server

    while True:
        screen.fill(bg_color)
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill(UI_OVERLAY_DARK)
        screen.blit(overlay, (0, 0))
        draw_text_centered(FONT_LG, "Online Lobby", HEIGHT//2 - 200, WHITE, y_is_center=True)
        draw_text_centered(FONT_SM, "Lobby name", name_y - 24, (200, 200, 200))
        draw_text_centered(FONT_SM, "Password", pass_y - 24, (200, 200, 200))
        mx, my = pygame.mouse.get_pos()

        for (y, text, is_pass) in [(name_y, lobby_name, False), (pass_y, lobby_password, True)]:
            disp = ("*" * len(text)) if is_pass else text
            border = (120, 180, 120) if (y == name_y and focus == 0) or (y == pass_y and focus == 1) else (80, 80, 80)
            pygame.draw.rect(screen, (40, 40, 40), (bar_x, y, bar_w, bar_h))
            pygame.draw.rect(screen, border, (bar_x, y, bar_w, bar_h), 3)
            prompt = FONT_MD.render(disp + ("|" if (pygame.time.get_ticks() // 500) % 2 and ((y == name_y and focus == 0) or (y == pass_y and focus == 1)) else ""), True, (220, 220, 220))
            screen.blit(prompt, (bar_x + 12, y + (bar_h - prompt.get_height())//2))

        can_use = net and net.connected
        if waiting and can_use:
            status = net.get_lobby_status()
            if status == "created" or status == "joined":
                return "ok"
            if isinstance(status, tuple) and status[0] == "error":
                notify_once(status[1][:50], 2000)
                waiting = None
            draw_text_centered(FONT_SM, "Waiting...", HEIGHT//2 + 75, (200, 200, 100), y_is_center=True)
        else:
            draw_button(create_rect, "Create", hover=can_use and create_rect.collidepoint(mx, my), text_color=UI_TEXT)
            draw_button(join_rect, "Join", hover=can_use and join_rect.collidepoint(mx, my), text_color=UI_TEXT)
            draw_button(back_rect, "Back", hover=back_rect.collidepoint(mx, my), text_color=UI_TEXT)

        if not (net and net.connected):
            draw_text_centered(FONT_MD, "Connecting...", HEIGHT//2 - 160, (200, 200, 100), y_is_center=True)
            if net and net.last_error:
                err = (net.last_error[:50] + "..") if len(net.last_error) > 50 else net.last_error
                draw_text_centered(FONT_XS, err, HEIGHT//2 - 120, (220, 120, 120), y_is_center=True)
            draw_text_centered(FONT_XS, "Start server: python game.py --server", HEIGHT//2 - 90, (140, 140, 140), y_is_center=True)
        else:
            draw_text_centered(FONT_XS, "Create a new lobby or join one with name + password", HEIGHT//2 - 250, (160, 160, 160), y_is_center=True)
        pygame.display.flip()

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return "back"
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    return "back"
                if ev.key == pygame.K_TAB:
                    focus = 1 - focus
                    continue
                if waiting:
                    continue
                target = lobby_name if focus == 0 else lobby_password
                if ev.key == pygame.K_BACKSPACE:
                    target = target[:-1]
                elif ev.unicode and ev.unicode.isprintable() and len(target) < 32:
                    target += ev.unicode
                if focus == 0:
                    lobby_name = target
                else:
                    lobby_password = target
                continue
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1 and not waiting:
                if pygame.Rect(bar_x, name_y, bar_w, bar_h).collidepoint(ev.pos):
                    focus = 0
                elif pygame.Rect(bar_x, pass_y, bar_w, bar_h).collidepoint(ev.pos):
                    focus = 1
                elif create_rect.collidepoint(ev.pos) and can_use:
                    if not lobby_name.strip():
                        notify_once("Enter a lobby name", 1200)
                    else:
                        play_sound("menu_click")
                        net.send_create_lobby(lobby_name.strip(), lobby_password)
                        waiting = "create"
                elif join_rect.collidepoint(ev.pos) and can_use:
                    if not lobby_name.strip():
                        notify_once("Enter a lobby name", 1200)
                    else:
                        play_sound("menu_click")
                        net.send_join_lobby(lobby_name.strip(), lobby_password)
                        waiting = "join"
                elif back_rect.collidepoint(ev.pos):
                    play_sound("menu_click")
                    return "back"
        clock.tick(FPS)


# Admin: type 6543 in game to get black screen, then type code in bar and Submit. Valid codes:
ADMIN_TRIGGER = (pygame.K_6, pygame.K_5, pygame.K_4, pygame.K_3)  # 6543 to open code screen
ADMIN_VALID_CODES = ("3.141592653", "3141592653")
ADMIN_CODE_DISPLAY = "3.141592653  or  3141592653"  # shown in admin panel

def admin_code_entry_screen():
    """Black screen with text bar and Submit. Correct code (3.141592653 or 3141592653) opens admin panel; wrong code kicks out."""
    input_text = ""
    bar_w = 400
    bar_h = 44
    bar_x = WIDTH//2 - bar_w//2
    bar_y = HEIGHT//2 - bar_h//2 - 30
    submit_w, submit_h = 120, 44
    submit_rect = pygame.Rect(WIDTH//2 - submit_w//2, HEIGHT//2 + 24, submit_w, submit_h)
    while True:
        screen.fill(BLACK)
        draw_text_centered(FONT_MD, "Enter code", HEIGHT//2 - 100, (200, 200, 200), y_is_center=True)
        mx, my = pygame.mouse.get_pos()
        pygame.draw.rect(screen, (60, 60, 60), (bar_x - 2, bar_y - 2, bar_w + 4, bar_h + 4))
        pygame.draw.rect(screen, (40, 40, 40), (bar_x, bar_y, bar_w, bar_h))
        pygame.draw.rect(screen, (100, 100, 100), (bar_x, bar_y, bar_w, bar_h), 3)
        prompt = FONT_MD.render(input_text + ("|" if (pygame.time.get_ticks() // 500) % 2 else " "), True, (220, 220, 220))
        screen.blit(prompt, (bar_x + 12, bar_y + (bar_h - prompt.get_height())//2))
        sub_c = (100, 100, 100) if submit_rect.collidepoint(mx, my) else (70, 70, 70)
        pygame.draw.rect(screen, sub_c, submit_rect)
        pygame.draw.rect(screen, (150, 150, 150), submit_rect, 3)
        screen.blit(FONT_MD.render("Submit", True, (220, 220, 220)), (submit_rect.x + (submit_rect.w - FONT_MD.size("Submit")[0])//2, submit_rect.y + (submit_rect.h - FONT_MD.get_height())//2))
        draw_text_centered(FONT_XS, "Escape to cancel", HEIGHT - 40, (100, 100, 100))
        pygame.display.flip()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    return
                if ev.key == pygame.K_RETURN or ev.key == pygame.K_KP_ENTER:
                    code = input_text.strip()
                    if code in ADMIN_VALID_CODES:
                        admin_panel()
                    return
                if ev.key == pygame.K_BACKSPACE:
                    input_text = input_text[:-1]
                elif ev.unicode and ev.unicode.isprintable() and len(input_text) < 20:
                    input_text += ev.unicode
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if submit_rect.collidepoint(ev.pos):
                    code = input_text.strip()
                    if code in ADMIN_VALID_CODES:
                        admin_panel()
                    return
        clock.tick(FPS)

def admin_panel():
    """In-game admin panel. Codes: 3.141592653 or 3141592653. Scrollable, all abilities individual, extra cheats."""
    global gems, player_speed, owned_abilities, corrosive_level, arrow_damage, max_hp, player_hp
    global knockback_level, pierce_level, player_level, player_exp, exp_required, wave
    global in_collection_phase, collection_start_ms, collection_duration_ms, enemies
    global admin_god_mode
    btn_w = 200
    btn_h = 36
    row = 40
    pad = 24
    panel_center_x = WIDTH // 2
    left_x = panel_center_x - 320
    right_x = panel_center_x - 100
    y_start = 130
    # Fixed list of ability names (same order as owned_abilities keys for consistent toggles)
    ability_names = [
        "Flame", "Poison", "Lightning", "Frost", "Bounty", "Scavenger", "Haste",
        "Knockback", "Piercing", "Critical", "Splash", "Overdraw",
        "Double Shot", "Explosive", "Vampiric",
        "Heartseeker", "Berserk", "Shatter", "Corrosive", "Execution",
        "Lucky", "Tough"
    ]
    ab_cols = 4
    ab_w = 148
    ab_h = 32

    def build_buttons():
        """Returns list of (rect in content coords, action_key, label). action_key: str or ('ability', name) or ('wave', n)."""
        rects, keys, labels = [], [], []
        y = y_start
        def add(x, w, label, key):
            rects.append(pygame.Rect(x, y, w, btn_h))
            keys.append(key)
            labels.append(label)
        # ---- Stats (left column) ----
        add(left_x, btn_w, "Full Heal", "heal")
        y += row
        add(left_x, btn_w, f"Speed: {player_speed}", "speed")
        y += row
        add(left_x, btn_w, "+5000 Gems", "gems")
        y += row
        add(left_x, btn_w, "+100 Arrow Dmg", "dmg")
        y += row
        add(left_x, btn_w, "Set 500 Max HP + heal", "max_hp")
        y += row
        add(left_x, btn_w, "Set Level 20", "level20")
        y += row
        add(left_x, btn_w, "Skip to next wave", "skip_wave")
        y += row
        add(left_x, btn_w, "+5 Knockback", "knockback")
        y += row
        add(left_x, btn_w, "Max Piercing (3)", "pierce")
        y += row + 8
        # ---- Set Wave (small row) ----
        for idx, n in enumerate((1, 5, 10, 25)):
            rects.append(pygame.Rect(left_x + idx * 76, y, 72, btn_h))
            keys.append(("wave", n))
            labels.append(f"Wave {n}")
        y += row
        # ---- Cheats ----
        add(left_x, btn_w, "God Mode: " + ("ON" if admin_god_mode else "OFF"), "god")
        y += row
        add(left_x, btn_w, "Clear all enemies", "clear_enemies")
        y += row
        add(left_x, btn_w, "Give ALL abilities + max", "all_abilities")
        y += row
        add(left_x, btn_w, "Corrosive (max only)", "corrosive_max")
        y += row + 12
        # ---- Abilities section header (non-clickable) ----
        rects.append(pygame.Rect(left_x, y, 380, 22))
        keys.append("noop")
        labels.append("--- Abilities (click to toggle) ---")
        y += 26
        for i, name in enumerate(ability_names):
            col = i % ab_cols
            row_i = i // ab_cols
            x = left_x + col * (ab_w + 6)
            ay = y + row_i * (ab_h + 4)
            rects.append(pygame.Rect(x, ay, ab_w, ab_h))
            keys.append(("ability", name))
            on = owned_abilities.get(name, False)
            labels.append(name + (" ✓" if on else ""))
        y += (len(ability_names) + ab_cols - 1) // ab_cols * (ab_h + 4) + 16
        # ---- Back ----
        add(panel_center_x - 90, 180, "Back", "back")
        return rects, keys, labels

    content_height = 1400
    scroll_y = 0
    max_scroll = max(0, content_height - HEIGHT + 60)
    panel_margin = 40
    panel_rect = pygame.Rect(panel_margin, 30, WIDTH - 2 * panel_margin, HEIGHT - 60)
    while True:
        rects, keys, labels = build_buttons()
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 200))
        screen.blit(overlay, (0, 0))
        pygame.draw.rect(screen, (28, 45, 35), panel_rect)
        pygame.draw.rect(screen, (60, 120, 80), panel_rect, 5)
        draw_text_centered(FONT_LG, "Admin Panel", 52, (220, 255, 220))
        draw_text_centered(FONT_SM, f"Code: {ADMIN_CODE_DISPLAY}", 92, (180, 200, 180))
        draw_text_centered(FONT_XS, f"HP: {player_hp}/{max_hp}  Dmg: {arrow_damage}  Gems: {gems}  Wave: {wave}" + ("  [GOD]" if admin_god_mode else ""), 118, (140, 160, 140))
        mx, my = pygame.mouse.get_pos()
        content_my = my + scroll_y
        for i, (rect, label) in enumerate(zip(rects, labels)):
            draw_y = rect.y - scroll_y
            if draw_y + rect.h < 130 or draw_y > HEIGHT - 30:
                continue
            draw_rect = pygame.Rect(rect.x, draw_y, rect.w, rect.h)
            hover = draw_rect.collidepoint(mx, my)
            c = (70, 110, 85) if hover else (50, 85, 65)
            pygame.draw.rect(screen, c, draw_rect)
            pygame.draw.rect(screen, (90, 150, 100), draw_rect, 3)
            font = FONT_XS if rect.w <= 72 else (FONT_SM if rect.w < 200 else FONT_MD)
            w = font.size(label)[0]
            screen.blit(font.render(label, True, (220, 240, 220)), (draw_rect.x + (draw_rect.w - w) // 2, draw_rect.y + (draw_rect.h - font.get_height()) // 2))
        if max_scroll > 0:
            draw_text_centered(FONT_XS, "Scroll: mouse wheel", HEIGHT - 26, (120, 140, 120))
        pygame.display.flip()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                return
            if ev.type == pygame.MOUSEWHEEL:
                scroll_y = max(0, min(max_scroll, scroll_y - ev.y * 50))
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                click_content_y = ev.pos[1] + scroll_y
                for i, rect in enumerate(rects):
                    if not rect.collidepoint(ev.pos[0], click_content_y):
                        continue
                    key = keys[i]
                    if key == "heal":
                        player_hp = max_hp
                    elif key == "speed":
                        player_speed = 8 if player_speed == 5 else (12 if player_speed == 8 else 5)
                    elif key == "gems":
                        gems += 5000
                    elif key == "dmg":
                        arrow_damage += 100
                    elif key == "max_hp":
                        max_hp = 500
                        player_hp = 500
                    elif key == "level20":
                        player_level = 20
                        player_exp = 0
                        exp_required = 10 + 10 * (player_level - 1)
                    elif key == "skip_wave":
                        enemies.clear()
                        in_collection_phase = True
                        collection_start_ms = pygame.time.get_ticks() - collection_duration_ms - 100
                    elif key == "knockback":
                        knockback_level = min(5, knockback_level + 5)
                    elif key == "pierce":
                        pierce_level = 3
                    elif isinstance(key, tuple) and key[0] == "wave":
                        wave = key[1]
                    elif key == "god":
                        admin_god_mode = not admin_god_mode
                    elif key == "clear_enemies":
                        enemies.clear()
                    elif key == "all_abilities":
                        for k in owned_abilities:
                            owned_abilities[k] = True
                        knockback_level = 5
                        pierce_level = 3
                        corrosive_level = 5
                    elif key == "corrosive_max":
                        owned_abilities["Corrosive"] = True
                        corrosive_level = 5
                    elif key == "back":
                        return
                    elif key == "noop":
                        pass
                    elif isinstance(key, tuple) and key[0] == "ability":
                        ab_name = key[1]
                        owned_abilities[ab_name] = not owned_abilities.get(ab_name, False)
                        if ab_name == "Knockback" and owned_abilities[ab_name]:
                            knockback_level = min(5, knockback_level + 1)
                        if ab_name == "Piercing" and owned_abilities[ab_name]:
                            pierce_level = min(3, pierce_level + 1)
                        if ab_name == "Corrosive" and owned_abilities[ab_name]:
                            corrosive_level = min(5, max(1, corrosive_level + 1))
                    break
        clock.tick(FPS)

def settings_menu():
    global settings, screen, WIDTH, HEIGHT
    panel_w, panel_h = 380, 260
    panel = pygame.Rect(WIDTH//2 - panel_w//2, HEIGHT//2 - panel_h//2, panel_w, panel_h)
    slider_w, slider_h = 280, 22
    slider_x = panel.centerx - slider_w//2
    slider_y = panel.y + 78
    dragging = None
    back_rect = pygame.Rect(panel.centerx - 90, panel.bottom - 54, 180, 44)
    fullscreen_rect = pygame.Rect(panel.centerx - 100, panel.y + 168, 200, 44)
    while True:
        screen.fill(bg_color)
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill(UI_OVERLAY_DARK)
        screen.blit(overlay, (0, 0))
        pygame.draw.rect(screen, UI_PANEL_BG, panel)
        pygame.draw.rect(screen, UI_BORDER, panel, 4)
        title_surf = FONT_LG.render("Settings", True, UI_TEXT)
        title_x = panel.x + (panel.w - title_surf.get_width()) // 2
        screen.blit(title_surf, (title_x, panel.y + 14))
        mx, my = pygame.mouse.get_pos()
        vol = settings.get("volume", 0.7)
        vol_label = FONT_MD.render("Volume", True, UI_TEXT)
        screen.blit(vol_label, (slider_x, slider_y - 26))
        pygame.draw.rect(screen, DARK_GRAY, (slider_x, slider_y, slider_w, slider_h))
        pygame.draw.rect(screen, BLUE, (slider_x, slider_y, int(slider_w * vol), slider_h))
        knob_x = slider_x + max(0, int((slider_w - 14) * vol))
        pygame.draw.rect(screen, (248, 248, 252), (knob_x, slider_y - 3, 14, 28))
        pygame.draw.rect(screen, UI_BORDER, (knob_x, slider_y - 3, 14, 28), 2)
        fs_label = FONT_MD.render("Fullscreen", True, UI_TEXT)
        screen.blit(fs_label, (fullscreen_rect.x, fullscreen_rect.y - 24))
        pygame.draw.rect(screen, UI_BUTTON_HOVER if fullscreen_rect.collidepoint(mx, my) else UI_BUTTON_BG, fullscreen_rect)
        pygame.draw.rect(screen, UI_BORDER, fullscreen_rect, 3)
        fs_text = "On" if settings.get("fullscreen", True) else "Off"
        fst = FONT_MD.render(fs_text, True, UI_TEXT)
        screen.blit(fst, (fullscreen_rect.x + (fullscreen_rect.w - fst.get_width()) // 2, fullscreen_rect.y + (fullscreen_rect.h - fst.get_height()) // 2 - 1))
        draw_button(back_rect, "Back", hover=back_rect.collidepoint(mx, my), text_color=UI_TEXT)
        pygame.display.flip()

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                mx, my = ev.pos
                if back_rect.collidepoint(mx, my):
                    play_sound("menu_click")
                    return
                if fullscreen_rect.collidepoint(mx, my):
                    play_sound("menu_click")
                    settings["fullscreen"] = not settings.get("fullscreen", True)
                    apply_display_mode()
                    save_settings()
                if slider_x <= mx <= slider_x + slider_w and slider_y - 4 <= my <= slider_y + 32:
                    dragging = True
            if ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
                dragging = None
            if ev.type == pygame.MOUSEMOTION and dragging:
                mx = ev.pos[0]
                v = max(0, min(1, (mx - slider_x) / (slider_w or 1)))
                settings["volume"] = v
                save_settings()
        clock.tick(FPS)

def main_menu():
    global online_mode, current_save_slot, net
    refresh_all_slot_meta()

    while True:
        screen.fill(bg_color)
        # Title with subtle shadow for depth
        title_shadow = FONT_LG.render("Infinite Archer", True, (180, 184, 192))
        screen.blit(title_shadow, (WIDTH//2 - title_shadow.get_width()//2 + 2, HEIGHT//6 + 2))
        draw_text_centered(FONT_LG, "Infinite Archer", HEIGHT//6, BLACK)
        mx, my = pygame.mouse.get_pos()

        btn_w, btn_h = 360, 70
        new_rect = pygame.Rect(WIDTH//2 - btn_w//2, HEIGHT//2 - 140, btn_w, btn_h)
        resume_rect = pygame.Rect(WIDTH//2 - btn_w//2, HEIGHT//2 - 40, btn_w, btn_h)
        quit_rect = pygame.Rect(WIDTH//2 - btn_w//2, HEIGHT//2 + 60, btn_w, btn_h)
        class_rect = pygame.Rect(WIDTH//2 - btn_w//2, HEIGHT//2 + 160, btn_w, btn_h)
        online_rect = pygame.Rect(WIDTH//2 - btn_w//2, HEIGHT//2 + 260, btn_w, btn_h)

        for rect, label in [(new_rect, "Create New Game"), (resume_rect, "Resume Game"), (quit_rect, "Quit")]:
            draw_button(rect, label, hover=rect.collidepoint(mx, my))
        draw_button(class_rect, "Classes", hover=class_rect.collidepoint(mx, my))
        if not ONLINE_ENABLED:
            online_label = "Online (closed)"
        else:
            online_label = "Online" if websockets is not None else "Online (pip install websockets)"
        draw_button(online_rect, online_label, hover=online_rect.collidepoint(mx, my))

        meta_now = load_slot_meta(current_save_slot)
        g = int(meta_now.get("gems", 0))
        gem_txt = FONT_MD.render(f"Gems: {g}  (Slot {current_save_slot})", True, BLUE)
        screen.blit(gem_txt, (WIDTH - gem_txt.get_width() - 22, 18))

        settings_rect = pygame.Rect(16, 14, 100, 36)
        draw_button(settings_rect, "Settings", font=FONT_SM, hover=settings_rect.collidepoint(mx, my))

        slot_y = HEIGHT//2 + 360
        slot_w, slot_h = 180, 60
        del_btn_w, del_btn_h = 56, 24
        slot_gap = 8
        slot1 = pygame.Rect(WIDTH//2 - slot_w - 200, slot_y, slot_w, slot_h)
        slot2 = pygame.Rect(WIDTH//2 - slot_w//2, slot_y, slot_w, slot_h)
        slot3 = pygame.Rect(WIDTH//2 + 200, slot_y, slot_w, slot_h)
        del1 = pygame.Rect(slot1.x, slot1.bottom + slot_gap, del_btn_w, del_btn_h)
        del2 = pygame.Rect(slot2.x, slot2.bottom + slot_gap, del_btn_w, del_btn_h)
        del3 = pygame.Rect(slot3.x, slot3.bottom + slot_gap, del_btn_w, del_btn_h)
        for s, r in [(1, slot1), (2, slot2), (3, slot3)]:
            meta = load_slot_meta(s)
            sel = (s == current_save_slot)
            fill = UI_BUTTON_HOVER if r.collidepoint(mx, my) else UI_BUTTON_BG
            pygame.draw.rect(screen, fill, r)
            pygame.draw.rect(screen, BLUE if sel else UI_BORDER, r, 5 if sel else 3)
            screen.blit(FONT_MD.render(f"Slot {s}", True, UI_TEXT), (r.x + 12, r.y + 14))
        for d in [del1, del2, del3]:
            dc = (255, 200, 200) if d.collidepoint(mx, my) else (248, 220, 220)
            pygame.draw.rect(screen, dc, d)
            pygame.draw.rect(screen, RED, d, 3)
            screen.blit(FONT_XS.render("Delete", True, UI_TEXT), (d.x + (d.w - FONT_XS.size("Delete")[0])//2, d.y + 5))
        pygame.display.flip()

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if del1.collidepoint(ev.pos):
                    play_sound("menu_click")
                    if confirm_popup("Are you sure you want to delete Slot 1? This cannot be undone."):
                        delete_save_slot(1)
                        notify_once("Slot 1 deleted", 800)
                    continue
                if del2.collidepoint(ev.pos):
                    play_sound("menu_click")
                    if confirm_popup("Are you sure you want to delete Slot 2? This cannot be undone."):
                        delete_save_slot(2)
                        notify_once("Slot 2 deleted", 800)
                    continue
                if del3.collidepoint(ev.pos):
                    play_sound("menu_click")
                    if confirm_popup("Are you sure you want to delete Slot 3? This cannot be undone."):
                        delete_save_slot(3)
                        notify_once("Slot 3 deleted", 800)
                    continue
                if slot1.collidepoint(ev.pos): current_save_slot = 1; notify_once("Selected Slot 1", 400); continue
                if slot2.collidepoint(ev.pos): current_save_slot = 2; notify_once("Selected Slot 2", 400); continue
                if slot3.collidepoint(ev.pos): current_save_slot = 3; notify_once("Selected Slot 3", 400); continue

                if new_rect.collidepoint(ev.pos):
                    play_sound("menu_click")
                    online_mode = False
                    reset_game()
                    return "new"
                if resume_rect.collidepoint(ev.pos):
                    play_sound("menu_click")
                    reset_game()
                    if load_game():
                        notify_once("Loaded Save", 700)
                        return "resume"
                    notify_once("No save found — starting new", 900)
                    return "new"
                if class_rect.collidepoint(ev.pos):
                    play_sound("menu_click")
                    reset_game()
                    load_game()  # load slot gems/class for shop if exists
                    class_shop_menu()
                if online_rect.collidepoint(ev.pos):
                    play_sound("menu_click")
                    if not ONLINE_ENABLED:
                        notify_once("Online is temporarily closed", 1200)
                    elif websockets is None:
                        notify_once("Install websockets first", 1200)
                    else:
                        online_mode = True
                        reset_game()
                        result = lobby_screen()
                        if result == "ok":
                            return "new"
                        online_mode = False
                        net = None
                if settings_rect.collidepoint(ev.pos):
                    play_sound("menu_click")
                    settings_menu()
                    continue
                if quit_rect.collidepoint(ev.pos):
                    play_sound("menu_click")
                    pygame.quit(); sys.exit()

            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                pygame.quit(); sys.exit()

        clock.tick(FPS)

def game_over_screen():
    while True:
        screen.fill(bg_color)
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill(UI_OVERLAY_DARK)
        screen.blit(overlay, (0, 0))
        draw_text_centered(FONT_LG, "Game Over", HEIGHT//2 - 120, (220, 60, 60), y_is_center=True)
        stats = f"Wave: {wave}  •  Score: {score}  •  Gems this run: {gems_this_run}"
        stats_font = FONT_MD if FONT_MD.render(stats, True, BLACK).get_width() <= WIDTH - 40 else FONT_SM
        draw_text_centered(stats_font, stats, HEIGHT//2 - 50, (240, 244, 248), y_is_center=True)
        draw_text_centered(FONT_SM, "Click or press Enter to return to menu", HEIGHT//2 + 20, UI_TEXT_MUTED, y_is_center=True)
        pygame.display.flip()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if ev.type == pygame.MOUSEBUTTONDOWN or (ev.type == pygame.KEYDOWN and ev.key == pygame.K_RETURN):
                return
        clock.tick(FPS)

# ---------- Main Loop ----------
def game_loop():
    global weapon, wave, enemies_per_wave, score, player_hp
    global player_exp, player_level, exp_required, gems
    global gems_this_run
    global in_collection_phase, collection_start_ms, collection_duration_ms
    global spawn_preview_active, spawn_preview_start_ms, spawn_preview_ms
    global corrosive_level
    global net
    global vampire_fly_until_ms, vampire_fly_cooldown_until_ms
    global assassin_invis_until_ms, assassin_invis_cooldown_until_ms
    global mad_scientist_overcharge_until_ms, mad_scientist_overcharge_cooldown_until_ms
    global assassin_active_bounties, assassin_bounty_refresh_at_ms
    global robbers_gun

    gems_this_run = 0
    player.center = (WIDTH//2, HEIGHT//2)

    spawn_preview_active = True
    spawn_preview_start_ms = pygame.time.get_ticks()
    running = True
    admin_code_buffer = []
    last_corrosive_damage_ms = 0
    wave_banner_until_ms = 0
    wave_banner_number = 0

    while running:
        dt = clock.tick(FPS)
        now_ms = pygame.time.get_ticks()
        update_fx(dt)
        # class passive update
        try:
            player_class.on_update(now_ms)
        except Exception:
            pass

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                save_game(); pygame.quit(); sys.exit()

            if ev.type == pygame.KEYDOWN:
                global chat_open, chat_input

                # open chat with '/'
                if not chat_open and ev.key == pygame.K_SLASH:
                    chat_open = True
                    chat_input = ""
                    continue

                # typing mode
                if chat_open:
                    if ev.key == pygame.K_ESCAPE:
                        chat_open = False
                        chat_input = ""
                        continue

                    if ev.key == pygame.K_RETURN:
                        if online_mode and net is not None:
                            net.send_chat(chat_input)
                        else:
                            add_chat_message(ONLINE_USERNAME, chat_input)
                        chat_input = ""
                        chat_open = False
                        continue

                    if ev.key == pygame.K_BACKSPACE:
                        chat_input = chat_input[:-1]
                        continue

                    if ev.unicode and ev.unicode.isprintable():
                        if len(chat_input) < 160:
                            chat_input += ev.unicode
                        continue

                # Admin trigger: 6543 in sequence → black screen to type code and Submit
                if ev.key in ADMIN_TRIGGER:
                    expected = ADMIN_TRIGGER[len(admin_code_buffer)]
                    if ev.key == expected:
                        admin_code_buffer.append(ev.key)
                        if len(admin_code_buffer) == 4:
                            admin_code_buffer = []
                            admin_code_entry_screen()
                            continue
                    else:
                        admin_code_buffer = []
                else:
                    admin_code_buffer = []

                # normal controls
                if ev.key == pygame.K_ESCAPE:
                    action = pause_menu()
                    if action == "quit":
                        save_game()
                        return
                    continue
                if ev.key == pygame.K_1:
                    if isinstance(player_class, Robber):
                        robbers_gun = "ak47"
                    else:
                        weapon = "bow"
                if ev.key == pygame.K_2:
                    if isinstance(player_class, Robber):
                        robbers_gun = "minigun"
                    else:
                        weapon = "sword"
                if isinstance(player_class, Robber):
                    if ev.key == pygame.K_3: robbers_gun = "shotgun"
                    if ev.key == pygame.K_4: robbers_gun = "flamethrower"
                    if ev.key == pygame.K_5: robbers_gun = "sniper"
                if ev.key == pygame.K_v and isinstance(player_class, Vampire):
                    if now_ms >= vampire_fly_cooldown_until_ms and now_ms >= vampire_fly_until_ms:
                        vampire_fly_until_ms = now_ms + Vampire.FLY_DURATION_MS
                        vampire_fly_cooldown_until_ms = now_ms + Vampire.FLY_COOLDOWN_MS
                        floating_texts.append({"x": player.centerx, "y": player.centery - 30, "txt": "Flying!", "color": PURPLE, "ttl": 800, "vy": -0.5, "alpha": 255})
                if ev.key == pygame.K_v and isinstance(player_class, Assassin):
                    if now_ms >= assassin_invis_cooldown_until_ms and now_ms >= assassin_invis_until_ms:
                        assassin_invis_until_ms = now_ms + Assassin.INVIS_DURATION_MS
                        assassin_invis_cooldown_until_ms = now_ms + Assassin.INVIS_COOLDOWN_MS
                        floating_texts.append({"x": player.centerx, "y": player.centery - 30, "txt": "Invisible!", "color": PURPLE, "ttl": 800, "vy": -0.5, "alpha": 255})
                if ev.key == pygame.K_v and isinstance(player_class, MadScientist):
                    if now_ms >= mad_scientist_overcharge_cooldown_until_ms and now_ms >= mad_scientist_overcharge_until_ms:
                        mad_scientist_overcharge_until_ms = now_ms + MadScientist.OVERCHARGE_DURATION_MS
                        mad_scientist_overcharge_cooldown_until_ms = now_ms + MadScientist.OVERCHARGE_COOLDOWN_MS
                        floating_texts.append({"x": player.centerx, "y": player.centery - 30, "txt": "Overcharge!", "color": (120, 255, 120), "ttl": 800, "vy": -0.5, "alpha": 255})
                if ev.key == pygame.K_b and isinstance(player_class, Assassin):
                    hit_list_menu()
                    continue
                if in_collection_phase and ev.key == pygame.K_SPACE:
                    for orb in pending_orbs[:]:
                        player_exp += orb["amount"]
                        gems += orb["amount"]
                        gems_this_run += orb["amount"]
                        if owned_abilities.get("Bounty", False) and random.random() < 0.25:
                            gems += 1
                            gems_this_run += 1
                        if owned_abilities.get("Scavenger", False) and random.random() < 0.20:
                            player_exp += 5
                        try: pending_orbs.remove(orb)
                        except: pass
                    collection_start_ms = now_ms - collection_duration_ms - 1

            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                mx,my = ev.pos

                # Save button
                save_btn = pygame.Rect(WIDTH - 120, HEIGHT - 60, 100, 40)
                if save_btn.collidepoint(mx,my):
                    save_game()
                    floating_texts.append({"x":save_btn.centerx,"y":save_btn.top-10,"txt":"Saved!","color":BLUE,"ttl":45,"vy":-0.6,"alpha":255})
                    continue
                # Hit List button (Assassin only)
                if isinstance(player_class, Assassin):
                    hitlist_btn = pygame.Rect(WIDTH - 230, HEIGHT - 60, 100, 40)
                    if hitlist_btn.collidepoint(mx, my):
                        hit_list_menu()
                        continue

                if in_collection_phase:
                    for orb in pending_orbs[:]:
                        rect = pygame.Rect(orb["x"]-8, orb["y"]-8, 16, 16)
                        if rect.collidepoint(mx,my):
                            player_exp += orb["amount"]
                            gems += orb["amount"]
                            gems_this_run += orb["amount"]
                            if owned_abilities.get("Bounty", False) and random.random() < 0.25:
                                gems += 1
                                gems_this_run += 1
                            if owned_abilities.get("Scavenger", False) and random.random() < 0.20:
                                player_exp += 5
                            try: pending_orbs.remove(orb)
                            except: pass
                            break
                    continue

                if isinstance(player_class, Robber):
                    update_robber_guns(now_ms, mx, my, True, True)
                elif weapon == "bow":
                    shoot_bow(mx,my)
                else:
                    handle_sword_attack(mx,my)

        # movement (disabled while typing). Vampire fly = 1.5x speed
        keys = pygame.key.get_pressed()
        if not chat_open:
            speed = player_speed * (Vampire.FLY_SPEED_MULT if (isinstance(player_class, Vampire) and now_ms < vampire_fly_until_ms) else 1.0)
            if keys[pygame.K_w]: player.y -= speed
            if keys[pygame.K_s]: player.y += speed
            if keys[pygame.K_a]: player.x -= speed
            if keys[pygame.K_d]: player.x += speed
        player.clamp_ip(screen.get_rect())

        # Robber: hold-to-fire (AK, flamethrower) and minigun auto-fire
        if isinstance(player_class, Robber):
            mx, my = pygame.mouse.get_pos()
            update_robber_guns(now_ms, mx, my, pygame.mouse.get_pressed()[0], False)

        vampire_fly = isinstance(player_class, Vampire) and now_ms < vampire_fly_until_ms
        assassin_invis = isinstance(player_class, Assassin) and now_ms < assassin_invis_until_ms

        # Assassin: init or refresh bounties on timer
        if isinstance(player_class, Assassin):
            if not assassin_active_bounties or now_ms >= assassin_bounty_refresh_at_ms:
                refresh_assassin_bounties()

        # online snapshots
        net_players = {}
        net_enemies = {}
        net_shots = []
        net_chat = []
        if online_mode and net is not None:
            net.send_input_throttled(player.centerx, player.centery, weapon)
            net_players, net_enemies, net_shots, net_chat = net.snapshot()

            if net_chat:
                chat_messages[:] = [{"name": m.get("name", ""), "msg": m.get("msg", ""), "ts": 0} for m in net_chat][-60:]

            # remote arrows -> spawn visuals
            # only add shots that are not ours
            myid = net.id
            for s in net_shots:
                if s.get("pid") == myid:
                    continue
                # create a short-lived remote arrow
                remote_arrows.append(RemoteArrow(s.get("x",0), s.get("y",0), s.get("vx",0), s.get("vy",0), ttl_ms=650))

        # server-authoritative enemies (mirror)
        if online_mode and online_coop_enemies and net is not None and net_enemies:
            enemies.clear()
            for eid, ed in net_enemies.items():
                r = pygame.Rect(int(ed.get("x",0)), int(ed.get("y",0)), int(ed.get("w",30)), int(ed.get("h",30)))
                obj = Enemy(r, str(ed.get("etype","normal")))
                obj.hp = float(ed.get("hp", 1))
                obj._net_id = str(eid)
                enemies.append(obj)

        # spawn preview (offline only)
        if not online_mode:
            if spawn_preview_active and now_ms - spawn_preview_start_ms >= spawn_preview_ms:
                spawn_preview_active = False
                globals()["first_arrow_hit_this_wave"] = False
                if wave % 10 == 0:
                    spawn_boss()
                else:
                    spawn_wave(enemies_per_wave)

        # update arrows
        for a in arrows[:]:
            if not a.update():
                try: arrows.remove(a)
                except: pass

        # remote arrows update
        for ra in remote_arrows[:]:
            if not ra.update(dt):
                try: remote_arrows.remove(ra)
                except: pass

        # enemy arrows update
        for ea in enemy_arrows[:]:
            if not ea.update():
                try: enemy_arrows.remove(ea)
                except: pass

        # Corrosive ability: damage enemies in field (offline only)
        if not online_mode and owned_abilities.get("Corrosive", False) and corrosive_level >= 1:
            if now_ms - last_corrosive_damage_ms >= 500:
                last_corrosive_damage_ms = now_ms
                radius = CORROSIVE_BASE_RADIUS * (0.6 + 0.08 * min(corrosive_level, 5))
                dmg = max(1, int(CORROSIVE_DPS * 0.5 * min(corrosive_level, 5)))
                cx, cy = player.centerx, player.centery
                for enemy in enemies[:]:
                    ex, ey = enemy.rect.centerx, enemy.rect.centery
                    if math.hypot(ex - cx, ey - cy) <= radius:
                        enemy.hp -= dmg
                        floating_texts.append({"x": enemy.rect.centerx, "y": enemy.rect.top - 12, "txt": f"-{dmg}", "color": ACID_YELLOW, "ttl": 800, "vy": -0.5, "alpha": 255})
                        if enemy.hp <= 0:
                            record_assassin_kill(enemy)
                            score += 1
                            spawn_orb(enemy.rect.centerx, enemy.rect.centery, amount=1)
                            try: enemies.remove(enemy)
                            except: pass

        # enemies update (offline/local side only)
        if not online_mode:
            for enemy in enemies[:]:
                if getattr(enemy,"is_boss",False):
                    boss_try_summon(enemy)

                if not assassin_invis:
                    proj = enemy.try_shoot(now_ms)
                    if proj:
                        enemy_arrows.append(EnemyArrow(proj["rect"], proj["vx"], proj["vy"], proj["damage"]))

                if not assassin_invis:
                    enemy.move_towards(player.centerx, player.centery)
                enemy.apply_status(now_ms)

                if enemy.hp <= 0:
                    record_assassin_kill(enemy)
                    score += 1
                    spawn_orb(enemy.rect.centerx, enemy.rect.centery, amount=1)
                    try: enemies.remove(enemy)
                    except: pass
                    continue

                if player.colliderect(enemy.rect):
                    if not vampire_fly and not assassin_invis:
                        dmg = enemy.damage
                        if isinstance(player_class, Knight):
                            dmg = int(math.ceil(dmg*0.90))
                        if not admin_god_mode:
                            player_hp -= dmg
                        try: enemies.remove(enemy)
                        except: pass
                        if not admin_god_mode and player_hp <= 0:
                            play_sound("death")
                            game_over_screen(); reset_game(); return

        # enemy arrows hit player (only Assassin invis blocks; Vampire fly = archers can hit)
        for ea in enemy_arrows[:]:
            if player.colliderect(ea.rect) and not assassin_invis:
                if isinstance(player_class, Knight) and weapon == "sword":
                    if player_class.try_deflect(ea):
                        continue
                dmg = ea.damage
                if isinstance(player_class, Knight):
                    dmg = int(math.ceil(dmg*0.90))
                if not admin_god_mode:
                    player_hp -= dmg
                try: enemy_arrows.remove(ea)
                except: pass
                if not admin_god_mode and player_hp <= 0:
                    play_sound("death")
                    game_over_screen(); reset_game(); return
            elif player.colliderect(ea.rect) and assassin_invis:
                try: enemy_arrows.remove(ea)
                except: pass

        # player arrows hit enemies
        for a in arrows[:]:
            for enemy in enemies[:]:
                if enemy.rect.colliderect(a.rect):
                    dmg_override = getattr(a, "damage_override", None)
                    hit_dmg = dmg_override if dmg_override is not None else arrow_damage
                    if online_mode and net is not None and hasattr(enemy, "_net_id"):
                        net.send_hit(enemy._net_id, hit_dmg)


                        # online EXP + gems (client-side immediate)
                        player_exp += 1
                        gems += 1
                        gems_this_run += 1
                        while player_exp >= exp_required:
                            player_exp -= exp_required
                            player_level += 1
                            exp_required = 10 + 10 * (player_level - 1)
                            play_sound("levelup")
                    else:
                        handle_arrow_hit(enemy, hit_dmg)
                    if getattr(a,"pierce_remaining",0) > 0:
                        a.pierce_remaining -= 1
                    else:
                        try: arrows.remove(a)
                        except: pass
                    break

        # collection phase (offline only)
        if not online_mode:
            if not enemies and not in_collection_phase and not spawn_preview_active:
                in_collection_phase = True
                collection_start_ms = pygame.time.get_ticks()

            if in_collection_phase:
                for orb in pending_orbs[:]:
                    dx = player.centerx - orb["x"]; dy = player.centery - orb["y"]
                    dist = math.hypot(dx,dy) or 1.0
                    speed = 4 + min(8, dist/20.0)
                    orb["x"] += (dx/dist)*speed
                    orb["y"] += (dy/dist)*speed
                    if math.hypot(orb["x"]-player.centerx, orb["y"]-player.centery) < 20:
                        player_exp += orb["amount"]
                        gems += orb["amount"]
                        gems_this_run += orb["amount"]
                        if owned_abilities.get("Bounty", False) and random.random() < 0.25:
                            gems += 1
                            gems_this_run += 1
                        if owned_abilities.get("Scavenger", False) and random.random() < 0.20:
                            player_exp += 5
                        try: pending_orbs.remove(orb)
                        except: pass

                if pygame.time.get_ticks() - collection_start_ms >= collection_duration_ms:
                    for orb in pending_orbs[:]:
                        player_exp += orb["amount"]
                        gems += orb["amount"]
                        gems_this_run += orb["amount"]
                        if owned_abilities.get("Bounty", False) and random.random() < 0.25:
                            gems += 1
                            gems_this_run += 1
                        if owned_abilities.get("Scavenger", False) and random.random() < 0.20:
                            player_exp += 5
                        try: pending_orbs.remove(orb)
                        except: pass
                    in_collection_phase = False

                    leveled = False
                    while player_exp >= exp_required:
                        player_exp -= exp_required
                        player_level += 1
                        exp_required = 10 + 10*(player_level-1)
                        leveled = True

                    if leveled:
                        play_sound("levelup")
                        ability_choice_between_waves()

                    save_game()
                    spawn_preview_active = True
                    spawn_preview_start_ms = pygame.time.get_ticks()
                    player.center = (WIDTH//2, HEIGHT//2)
                    wave += 1
                    wave_banner_number = wave
                    wave_banner_until_ms = now_ms + 2200
                    enemies_per_wave = max(1, int(round(enemies_per_wave*1.1)))

        # ---------- DRAW ----------
        screen.fill(bg_color)

        # Wave banner (after clearing a wave) — fades out in last 0.4s
        if wave_banner_until_ms and now_ms < wave_banner_until_ms:
            remain = wave_banner_until_ms - now_ms
            alpha = 255 if remain > 400 else int(255 * remain / 400)
            banner_text = f"Wave {wave_banner_number}"
            banner_surf = FONT_LG.render(banner_text, True, (255, 255, 200))
            if alpha < 255:
                banner_surf = banner_surf.convert_alpha()
                banner_surf.set_alpha(alpha)
            bx = WIDTH//2 - banner_surf.get_width()//2
            by = HEIGHT//2 - banner_surf.get_height()//2 - 40
            outline = FONT_LG.render(banner_text, True, (40, 40, 20))
            for dx, dy in [(-1,-1),(-1,1),(1,-1),(1,1),(0,-1),(0,1),(-1,0),(1,0)]:
                screen.blit(outline, (bx + dx, by + dy))
            screen.blit(banner_surf, (bx, by))

        # corrosive field visual (Mythical ability only)
        if owned_abilities.get("Corrosive", False) and corrosive_level >= 1:
            radius = CORROSIVE_BASE_RADIUS * (0.6 + 0.08 * min(corrosive_level, 5))
            draw_corrosive_field_visual(radius, alpha=90, outline=True)

        # local player (Assassin: faint when invisible)
        if assassin_invis:
            player_surf = pygame.Surface((player.width, player.height), pygame.SRCALPHA)
            player_surf.fill((*player_class.color, 70))
            screen.blit(player_surf, (player.x, player.y))
        else:
            pygame.draw.rect(screen, player_class.color, player)

        # remote players
        if online_mode and net is not None:
            for pid, p in net_players.items():
                if net.id is not None and pid == net.id:
                    continue
                rx, ry = int(p.get("x",0)), int(p.get("y",0))
                r = pygame.Rect(rx - player.width//2, ry - player.height//2, player.width, player.height)
                pygame.draw.rect(screen, (60,160,255), r)
                nm = str(p.get("name", pid))
                tag = FONT_SM.render(nm, True, BLACK)
                screen.blit(tag, (r.x, r.y - 18))

        # weapon visuals (hidden when Assassin invisible)
        if not assassin_invis and isinstance(player_class, Robber):
            mx, my = pygame.mouse.get_pos()
            ang = math.atan2(my - player.centery, mx - player.centerx)
            gun_len = 50
            tipx = int(player.centerx + gun_len * math.cos(ang))
            tipy = int(player.centery + gun_len * math.sin(ang))
            gun_colors = {"ak47": (60, 60, 60), "minigun": (80, 70, 60), "shotgun": (90, 50, 30), "flamethrower": (200, 100, 0), "sniper": (40, 50, 40)}
            pygame.draw.line(screen, gun_colors.get(robbers_gun, (60, 60, 60)), (player.centerx, player.centery), (tipx, tipy), 5)
            # Visible flamethrower cone when firing
            if robbers_gun == "flamethrower" and robber_flame_active:
                half = ROBBER_FLAME_CONE_ANGLE_RAD / 2
                cx, cy = player.centerx, player.centery
                r = ROBBER_FLAME_CONE_RANGE
                left_ang = ang - half
                right_ang = ang + half
                x1 = cx + r * math.cos(left_ang)
                y1 = cy + r * math.sin(left_ang)
                x2 = cx + r * math.cos(right_ang)
                y2 = cy + r * math.sin(right_ang)
                pts = [(cx, cy), (x1, y1), (x2, y2)]
                flame_surf = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
                pygame.draw.polygon(flame_surf, (255, 140, 0, 140), pts)
                pygame.draw.polygon(flame_surf, (255, 200, 50, 90), [(cx, cy), (cx + 0.7*r*math.cos(left_ang), cy + 0.7*r*math.sin(left_ang)), (cx + 0.7*r*math.cos(right_ang), cy + 0.7*r*math.sin(right_ang))])
                screen.blit(flame_surf, (0, 0))
        elif not assassin_invis and weapon == "bow":
            bow_len = 60
            arc_rect = pygame.Rect(player.centerx - 12, player.centery - bow_len, 24, bow_len*2)
            bow_color = BLUE if isinstance(player_class, MadScientist) else BROWN
            string_color = BLUE if isinstance(player_class, MadScientist) else BLACK
            try:
                pygame.draw.arc(screen, bow_color, arc_rect, math.radians(270), math.radians(90), 4)
            except:
                pass
            top = (player.centerx + 4, player.centery - int(bow_len*0.9))
            bottom = (player.centerx + 4, player.centery + int(bow_len*0.9))
            pygame.draw.line(screen, string_color, top, bottom, 4)
        elif not assassin_invis:
            mx,my = pygame.mouse.get_pos()
            ang = math.atan2(my - player.centery, mx - player.centerx)
            melee_range = Assassin.KNIFE_RANGE if isinstance(player_class, Assassin) else DEFAULTS["sword_range"]
            tipx = player.centerx + melee_range*math.cos(ang)
            tipy = player.centery + melee_range*math.sin(ang)
            pygame.draw.line(screen, (192,192,192), (player.centerx, player.centery), (tipx, tipy), 6 if isinstance(player_class, Assassin) else 8)

        # spawn preview red X markers (offline only)
        if (spawn_preview_active and (not online_mode)) or (online_mode and (now_ms - spawn_preview_start_ms < spawn_preview_ms)):
            preview_positions = spawn_pattern_positions[:int(enemies_per_wave)]
            for (rx, ry) in preview_positions:
                size = 34
                rect = pygame.Rect(int(rx - size//2), int(ry - size//2), size, size)
                s = pygame.Surface((size, size), pygame.SRCALPHA)
                s.fill((200, 40, 40, 120))
                screen.blit(s, rect.topleft)
                pygame.draw.rect(screen, RED, rect, 3)
                pygame.draw.line(screen, RED, (rect.left+6, rect.top+6), (rect.right-6, rect.bottom-6), 3)
                pygame.draw.line(screen, RED, (rect.right-6, rect.top+6), (rect.left+6, rect.bottom-6), 3)

        # local arrows
        for a in arrows:
            a.draw(screen)

        # remote arrows
        for ra in remote_arrows:
            ra.draw(screen)

        # enemy arrows
        for ea in enemy_arrows:
            ea.draw(screen)

        # enemies (and burn/poison DoT indicators)
        for enemy in enemies:
            pygame.draw.rect(screen, enemy.color, enemy.rect)
            cx, top = enemy.rect.centerx, enemy.rect.top
            if getattr(enemy, "burn_ms_left", 0) > 0:
                pygame.draw.circle(screen, ORANGE, (cx - 5, top - 5), 4)
            if getattr(enemy, "poison_ms_left", 0) > 0:
                pygame.draw.circle(screen, PURPLE, (cx + 5, top - 5), 4)

        # orbs (small box when enemy dies — use small font for the number)
        for orb in pending_orbs:
            pygame.draw.rect(screen, BLUE, (int(orb["x"])-6, int(orb["y"])-6, 12, 12))
            txt = FONT_XS.render(str(orb.get("amount", 1)), True, BLACK)
            screen.blit(
                txt,
                (int(orb["x"]) - txt.get_width()//2,
                 int(orb["y"]) - txt.get_height()//2)
            )

        # HUD (slight background for readability)
        hud_text = f"Score: {score}  Wave: {wave}  HP: {player_hp}  Dmg: {arrow_damage}  Gems: {gems}  Class: {player_class.name}"
        hud = FONT_SM.render(hud_text, True, BLACK)
        hud_rect = pygame.Rect(10, 52, hud.get_width() + 16, hud.get_height() + 8)
        hud_bg = pygame.Surface((hud_rect.w, hud_rect.h), pygame.SRCALPHA)
        hud_bg.fill((255, 255, 255, 200))
        screen.blit(hud_bg, hud_rect.topleft)
        pygame.draw.rect(screen, UI_BORDER_LIGHT, hud_rect, 2)
        screen.blit(hud, (18, 56))
        if isinstance(player_class, Vampire):
            if now_ms < vampire_fly_until_ms:
                ability_txt = FONT_MD.render("Flying!", True, PURPLE)
            elif now_ms < vampire_fly_cooldown_until_ms:
                sec = (vampire_fly_cooldown_until_ms - now_ms) // 1000
                ability_txt = FONT_MD.render(f"V fly: {sec}s", True, DARK_GRAY)
            else:
                ability_txt = FONT_MD.render("V: Fly ready", True, GREEN)
            screen.blit(ability_txt, (12, 84))
        if isinstance(player_class, Assassin):
            if now_ms < assassin_invis_until_ms:
                ability_txt = FONT_MD.render("Invisible!", True, PURPLE)
            elif now_ms < assassin_invis_cooldown_until_ms:
                sec = (assassin_invis_cooldown_until_ms - now_ms) // 1000
                ability_txt = FONT_MD.render(f"V invis: {sec}s", True, DARK_GRAY)
            else:
                ability_txt = FONT_MD.render("V: Invis ready", True, GREEN)
            screen.blit(ability_txt, (12, 84))
        if isinstance(player_class, MadScientist):
            if now_ms < mad_scientist_overcharge_until_ms:
                ability_txt = FONT_MD.render("Overcharge!", True, (120, 255, 120))
            elif now_ms < mad_scientist_overcharge_cooldown_until_ms:
                sec = (mad_scientist_overcharge_cooldown_until_ms - now_ms) // 1000
                ability_txt = FONT_MD.render(f"V overcharge: {sec}s", True, DARK_GRAY)
            else:
                ability_txt = FONT_MD.render("V: Overcharge ready", True, GREEN)
            screen.blit(ability_txt, (12, 84))
        if isinstance(player_class, Robber):
            gun_names = {"ak47": "AK-47", "minigun": "Minigun", "shotgun": "Shotgun", "flamethrower": "Flamethrower", "sniper": "Sniper"}
            g = robbers_gun
            ability_txt = FONT_SM.render(f"1:AK-47  2:Minigun  3:Shotgun  4:Flame  5:Sniper  [{gun_names.get(g, g)}]", True, BLACK)
            screen.blit(ability_txt, (12, 84))
            if minigun_charge_start_ms and now_ms < minigun_charge_start_ms + ROBBER_MINIGUN_CHARGE_MS:
                pct = min(100, int(100 * (now_ms - minigun_charge_start_ms) / ROBBER_MINIGUN_CHARGE_MS))
                charge_txt = FONT_XS.render(f"Minigun charging {pct}%", True, ORANGE)
                screen.blit(charge_txt, (12, 108))
            elif minigun_firing_until_ms and now_ms < minigun_firing_until_ms:
                charge_txt = FONT_XS.render("Minigun FIRING", True, RED)
                screen.blit(charge_txt, (12, 108))
            elif minigun_overheat_until_ms and now_ms < minigun_overheat_until_ms:
                sec = (minigun_overheat_until_ms - now_ms) / 1000.0
                charge_txt = FONT_XS.render(f"Minigun cooling {sec:.1f}s", True, DARK_GRAY)
                screen.blit(charge_txt, (12, 108))
            if g == "shotgun":
                if shotgun_reload_until_ms and now_ms < shotgun_reload_until_ms:
                    sec = (shotgun_reload_until_ms - now_ms) / 1000.0
                    charge_txt = FONT_XS.render(f"Shotgun reloading {sec:.1f}s", True, ORANGE)
                else:
                    charge_txt = FONT_XS.render(f"Shotgun {shotgun_shots_left}/{ROBBER_SHOTGUN_MAGAZINE}", True, BLACK)
                screen.blit(charge_txt, (12, 108))

        # Hit List button (Assassin only)
        hitlist_btn = pygame.Rect(WIDTH - 230, HEIGHT - 60, 100, 40)
        save_btn = pygame.Rect(WIDTH - 120, HEIGHT - 60, 100, 40)
        mx_hud, my_hud = pygame.mouse.get_pos()
        if isinstance(player_class, Assassin):
            draw_button(hitlist_btn, "Hit List", font=FONT_SM, hover=hitlist_btn.collidepoint(mx_hud, my_hud))
        draw_button(save_btn, "Save", font=FONT_SM, hover=save_btn.collidepoint(mx_hud, my_hud))

        for e in enemies:
            if getattr(e, "is_boss", False):
                draw_boss_bar(e)
                break
        draw_hp_bar(player_hp)
        draw_exp_bar()

        # FX + chat overlay
        draw_fx(screen)
        draw_chat(screen)
        pygame.display.flip()

# ---------- ENTRY ----------
if __name__ == "__main__":
    # CLI name (client)
    if "--name" in sys.argv:
        try:
            i = sys.argv.index("--name")
            if i+1 < len(sys.argv):
                ONLINE_USERNAME = sys.argv[i+1]
        except:
            pass

    # server
    if "--server" in sys.argv:
        if not ONLINE_ENABLED:
            print("Online is temporarily closed. Server start disabled.")
            sys.exit(1)
        if websockets is None:
            print("websockets not installed. Run: python -m pip install websockets")
            sys.exit(1)
        asyncio.run(run_server("0.0.0.0", 8765, 20))
        sys.exit(0)

    reset_game()
    while True:
        choice = main_menu()
        if choice == "resume":
            pass
        game_loop()

# ========== END PART 3 ==========  