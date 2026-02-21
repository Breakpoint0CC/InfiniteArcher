# =========================
# Infinite Archer — game.py
# FULL REPLACEMENT (PART 1/3)
# =========================
import os, sys, json, math, random, time, threading, asyncio
import wave
import io
import base64
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

    def _send(self, payload: dict):
        """Thread-safe send; sets last_error on failure."""
        if not self.connected or self._ws is None or self._loop is None:
            return False
        try:
            asyncio.run_coroutine_threadsafe(self._ws.send(json.dumps(payload)), self._loop)
            return True
        except Exception as e:
            self.last_error = str(e)
            return False

    def send_input_throttled(self, x, y, weapon):
        if not self.connected or self._ws is None or self._loop is None:
            return
        now = pygame.time.get_ticks()
        if now - self._last_send_ms < 50:  # 20hz
            return
        self._last_send_ms = now
        self._send({"type":"input","x":float(x),"y":float(y),"weapon":weapon,"name":str(ONLINE_USERNAME)[:16]})

    def send_shoot(self, x, y, vx, vy):
        self._send({"type":"shoot","x":float(x),"y":float(y),"vx":float(vx),"vy":float(vy)})

    def send_hit(self, enemy_id, dmg):
        self._send({"type":"hit","enemy_id":str(enemy_id),"dmg":float(dmg)})

    def send_chat(self, msg: str):
        self._send({"type": "chat", "msg": str(msg)[:160], "name": str(ONLINE_USERNAME)[:16]})

    def send_create_lobby(self, name: str, password: str):
        if not self.connected or self._ws is None or self._loop is None:
            return
        with self._lock:
            self._lobby_status = None
        self._send({"type": "create_lobby", "name": str(name)[:32], "password": str(password)[:32]})

    def send_join_lobby(self, name: str, password: str):
        if not self.connected or self._ws is None or self._loop is None:
            return
        with self._lock:
            self._lobby_status = None
        self._send({"type": "join_lobby", "name": str(name)[:32], "password": str(password)[:32]})

    def get_lobby_status(self):
        with self._lock:
            out = self._lobby_status
            self._lobby_status = None
        return out

    def send_save(self, slot: int, data: dict):
        self._send({"type": "save", "slot": max(1, min(3, slot)), "data": data})

    def send_load(self, slot: int):
        if not self.connected or self._ws is None or self._loop is None:
            return
        with self._lock:
            self._load_result = None
        self._send({"type": "load", "slot": max(1, min(3, slot))})

    def send_meta_get(self, slot=None):
        if not self.connected or self._ws is None or self._loop is None:
            return
        with self._lock:
            self._meta_result = None
        payload = {"type": "meta_get"}
        if slot is not None:
            payload["slot"] = max(1, min(3, slot))
        self._send(payload)

    def send_meta_set(self, slot: int, data: dict):
        self._send({"type": "meta_set", "slot": max(1, min(3, slot)), "data": data})

    def send_delete_save(self, slot: int):
        self._send({"type": "delete_save", "slot": max(1, min(3, slot))})

    def get_load_result(self, expected_slot=None):
        """Return load result; if expected_slot is set, only return when result slot matches (ignore stale)."""
        with self._lock:
            out = self._load_result
            if out is not None and expected_slot is not None:
                got_slot = out.get("slot")
                if got_slot is not None and got_slot != expected_slot:
                    return None  # wrong slot, keep for later
            if out is not None:
                self._load_result = None
        return out

    def get_meta_result(self, expected_slot=None):
        """Return meta result. For single-slot (data), expected_slot must match; for 'slots' dict, ignore slot."""
        with self._lock:
            out = self._meta_result
            if out is not None:
                if out.get("slots") is not None:
                    pass  # full slots response, always accept
                elif expected_slot is not None and out.get("slot") is not None and out.get("slot") != expected_slot:
                    return None
            if out is not None:
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
                if not isinstance(t, str):
                    continue

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
                # ignore unknown message types

        finally:
            try:
                if lobby_id and lobby_id in lobbies:
                    lob = lobbies[lobby_id]
                    lob["connections"].discard(ws)
                    if pid and pid in lob.get("players", {}):
                        lob["players"].pop(pid, None)
                    if not lob["connections"]:
                        lobbies.pop(lobby_id, None)
            except Exception:
                pass
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

    try:
        async with websockets.serve(handler, host, port, ping_interval=30, ping_timeout=10, max_size=2_000_000):
            print(f"Infinite Archer server listening on {host}:{port}")
            print(f"  Local:   ws://127.0.0.1:{port}")
            print(f"  Remote:  ws://<this-machine-ip>:{port}  (e.g. DigitalOcean Droplet IP)")
            print(f"  Clients: set IA_SERVER=ws://<server-ip>:{port} or use in-game server URL. Press Ctrl+C to stop.")
            await tick_loop()
    except OSError as e:
        if "48" in str(e) or "in use" in str(e).lower() or "Address already" in str(e):
            print(f"Port {port} already in use. Stop the other process or set PORT=8766 (or another port).")
        else:
            print(f"Server failed to start: {e}")
        raise

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
                    if self.hp <= 0:
                        self._killed_by_burn_dot = True
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
    BURN_MS_BASE = 3000
    def on_arrow_hit(self, enemy, damage):
        duration = FlameArcher.BURN_MS_BASE * 2 if globals().get("flame_mastery_unlocked", False) else FlameArcher.BURN_MS_BASE
        enemy.burn_ms_left = duration
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

# Flame Archer Mastery: progress and unlock (persisted in save)
flame_mastery_kills_burning = 0      # kills on enemies that were burning
flame_mastery_kills_dot_final = 0    # kills where flame DoT was final blow
flame_mastery_bosses_burning = 0     # bosses killed while burning
flame_mastery_unlocked = False
# Flame Bomb (mastery ability): ball in flight or zone active
flame_bomb_ball = None   # {"x", "y", "vx", "vy"} or None
flame_bomb_zone = None   # {"cx", "cy", "ttl_ms", "radius", "last_burn_tick_ms"} or None
FLAME_BOMB_BALL_SPEED = 14
FLAME_BOMB_ZONE_RADIUS = 85
FLAME_BOMB_ZONE_DURATION_MS = 8000
FLAME_BOMB_ZONE_BURN_MS = 4000

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

def record_flame_mastery_progress(enemy, dot_final_blow=False):
    """Track Flame Archer mastery: kills on burning enemies, DoT final blows, bosses while burning."""
    global flame_mastery_kills_burning, flame_mastery_kills_dot_final, flame_mastery_bosses_burning, flame_mastery_unlocked
    if flame_mastery_unlocked:
        return
    was_burning = getattr(enemy, "burn_ms_left", 0) > 0
    is_boss = getattr(enemy, "is_boss", False)
    if was_burning:
        flame_mastery_kills_burning = min(1000, flame_mastery_kills_burning + 1)
    if dot_final_blow:
        flame_mastery_kills_dot_final = min(350, flame_mastery_kills_dot_final + 1)
    if is_boss and was_burning:
        flame_mastery_bosses_burning = min(5, flame_mastery_bosses_burning + 1)
    if flame_mastery_kills_burning >= 1000 and flame_mastery_kills_dot_final >= 350 and flame_mastery_bosses_burning >= 5:
        flame_mastery_unlocked = True

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

    # explosive area (65px radius) — multi-layer effect
    for ex in explosive_fx:
        ttl = int(ex.get("ttl", 0))
        if ttl <= 0:
            continue
        start_ttl = ex.get("start_ttl", 500)
        progress = 1.0 - (ttl / max(1, start_ttl))  # 0 at start, 1 at end
        cx, cy = int(ex.get("cx", 0)), int(ex.get("cy", 0))
        size = 150
        half = size // 2
        surf = pygame.Surface((size, size), pygame.SRCALPHA)
        # Outer glow: soft orange, expands and fades
        glow_r = int(65 + 25 * progress)
        glow_alpha = int(90 * (1 - progress) * (1 - progress))
        if glow_alpha > 0 and glow_r > 0:
            pygame.draw.circle(surf, (255, 140, 50, glow_alpha), (half, half), glow_r)
        # Main ring: expands from 20 to 65, then fades
        ring_r = 20 + 45 * min(1.0, progress * 1.8)
        ring_alpha = int(220 * (1 - progress * 1.2))
        if ring_alpha > 0:
            pygame.draw.circle(surf, (255, 180, 60, ring_alpha), (half, half), int(ring_r), 5)
        # Inner bright core: shrinks and fades
        core_r = int(25 * (1 - progress))
        core_alpha = int(255 * (1 - progress * 2))
        if core_r > 0 and core_alpha > 0:
            pygame.draw.circle(surf, (255, 220, 150, core_alpha), (half, half), core_r)
            pygame.draw.circle(surf, (255, 255, 200, min(180, core_alpha)), (half, half), max(0, core_r - 4))
        # Radiating sparks (8 lines)
        num_sparks = 8
        for i in range(num_sparks):
            angle = (i / num_sparks) * 2 * math.pi + progress * 0.5
            length = 40 + 35 * progress
            spark_alpha = int(200 * (1 - progress) * (1 - progress))
            if spark_alpha > 0 and length > 0:
                ex_x = half + length * math.cos(angle)
                ex_y = half + length * math.sin(angle)
                pygame.draw.line(surf, (255, 200, 100, spark_alpha), (half, half), (ex_x, ex_y), 3)
        surface.blit(surf, (cx - half, cy - half))

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
            r = net.get_meta_result()  # full slots response, no slot filter
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
            r = net.get_meta_result(expected_slot=current_save_slot)
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
            "flame_mastery_kills_burning": flame_mastery_kills_burning,
            "flame_mastery_kills_dot_final": flame_mastery_kills_dot_final,
            "flame_mastery_bosses_burning": flame_mastery_bosses_burning,
            "flame_mastery_unlocked": flame_mastery_unlocked,
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
    global flame_mastery_kills_burning, flame_mastery_kills_dot_final, flame_mastery_bosses_burning, flame_mastery_unlocked

    if online_mode and net is not None and net.connected:
        net.send_load(current_save_slot)
        for _ in range(100):  # ~5 sec at 20 fps
            pygame.event.pump()
            r = net.get_load_result(expected_slot=current_save_slot)
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
        flame_mastery_kills_burning = int(data.get("flame_mastery_kills_burning", 0))
        flame_mastery_kills_dot_final = int(data.get("flame_mastery_kills_dot_final", 0))
        flame_mastery_bosses_burning = int(data.get("flame_mastery_bosses_burning", 0))
        flame_mastery_unlocked = bool(data.get("flame_mastery_unlocked", False))
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
    global flame_bomb_ball, flame_bomb_zone
    global flame_mastery_kills_burning, flame_mastery_kills_dot_final, flame_mastery_bosses_burning, flame_mastery_unlocked

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
    flame_bomb_ball = None
    flame_bomb_zone = None
    flame_mastery_kills_burning = 0
    flame_mastery_kills_dot_final = 0
    flame_mastery_bosses_burning = 0
    flame_mastery_unlocked = False

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
        url = os.environ.get("IA_SERVER", "ws://127.0.0.1:8765")
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
    # Flame Bomb zone (Flame Archer mastery): 1.5x damage while inside
    if flame_bomb_zone and isinstance(player_class, FlameArcher):
        if math.hypot(player.centerx - flame_bomb_zone["cx"], player.centery - flame_bomb_zone["cy"]) <= flame_bomb_zone["radius"]:
            dmg = int(dmg * 1.5)
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
        enemy.burn_ms_left = 6000 if flame_mastery_unlocked else 3000
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
                    record_flame_mastery_progress(e, dot_final_blow=False)
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
                    record_flame_mastery_progress(e, dot_final_blow=False)
                    record_assassin_kill(e)
                    spawn_orb(e.rect.centerx, e.rect.centery, amount=1)
                    globals()["score"] += 1
                    try: enemies.remove(e)
                    except: pass

    # Explosive (Legendary): 25% damage to enemies within 65px
    if owned_abilities.get("Explosive", False) and dmg > 0:
        exp_dmg = max(1, int(dmg * 0.25))
        ox, oy = enemy.rect.centerx, enemy.rect.centery
        explosive_fx.append({"cx": ox, "cy": oy, "ttl": 500, "start_ttl": 500})
        for e in enemies[:]:
            if e is enemy or getattr(e, "hp", 0) <= 0:
                continue
            dist = math.hypot(e.rect.centerx - ox, e.rect.centery - oy)
            if dist <= 65 and dist > 0:
                e.hp -= exp_dmg
                floating_texts.append({"x": e.rect.centerx, "y": e.rect.top - 12, "txt": f"-{exp_dmg}", "color": (255, 180, 80), "ttl": 900, "vy": -0.6, "alpha": 255})
                if e.hp <= 0:
                    record_flame_mastery_progress(e, dot_final_blow=False)
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
                    record_flame_mastery_progress(e, dot_final_blow=False)
                    record_assassin_kill(e)
                    spawn_orb(e.rect.centerx, e.rect.centery, amount=1)
                    globals()["score"] += 1
                    try: enemies.remove(e)
                    except: pass

    if enemy.hp <= 0:
        if owned_abilities.get("Berserk", False):
            globals()["berserk_until_ms"] = now + 2500
        record_flame_mastery_progress(enemy, dot_final_blow=False)
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
    sword_dmg_mult = 1.5 if (flame_bomb_zone and isinstance(player_class, FlameArcher) and math.hypot(player.centerx - flame_bomb_zone["cx"], player.centery - flame_bomb_zone["cy"]) <= flame_bomb_zone["radius"]) else 1.0

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
                    sw_dmg = int(DEFAULTS["sword_damage"] * sword_dmg_mult)
                    enemy.hp -= sw_dmg
                    floating_texts.append({"x":enemy.rect.centerx,"y":enemy.rect.top-12,"txt":f"-{sw_dmg}","color":RED,"ttl":1000,"vy":-0.6,"alpha":255})
                    if isinstance(player_class, Vampire):
                        heal = max(1, int(DEFAULTS["sword_damage"] * Vampire.LIFESTEAL_RATIO))
                        player_hp = min(max_hp, player_hp + heal)
                        floating_texts.append({"x": player.centerx, "y": player.centery - 20, "txt": f"+{heal}", "color": GREEN, "ttl": 1000, "vy": -0.6, "alpha": 255})
                if dist != 0 and not assassin_backstab:
                    enemy.rect.x += int(kb*(ex/dist))
                    enemy.rect.y += int(kb*(ey/dist))
                if enemy.hp <= 0:
                    record_flame_mastery_progress(enemy, dot_final_blow=False)
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

# Embedded Flame Archer art (single file, no external image)
_FLAME_ARCHER_IMAGE_B64 = (
'/9j/4AAQSkZJRgABAQAAAQABAAD/4gHYSUNDX1BST0ZJTEUAAQEAAAHIAAAAAAQwAABtbnRyUkdCIFhZ'
'WiAH4AABAAEAAAAAAABhY3NwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAQAA9tYAAQAAAADTLQAA'
'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAlkZXNjAAAA8AAA'
'ACRyWFlaAAABFAAAABRnWFlaAAABKAAAABRiWFlaAAABPAAAABR3dHB0AAABUAAAABRyVFJDAAABZAAA'
'AChnVFJDAAABZAAAAChiVFJDAAABZAAAAChjcHJ0AAABjAAAADxtbHVjAAAAAAAAAAEAAAAMZW5VUwAA'
'AAgAAAAcAHMAUgBHAEJYWVogAAAAAAAAb6IAADj1AAADkFhZWiAAAAAAAABimQAAt4UAABjaWFlaIAAA'
'AAAAACSgAAAPhAAAts9YWVogAAAAAAAA9tYAAQAAAADTLXBhcmEAAAAAAAQAAAACZmYAAPKnAAANWQAA'
'E9AAAApbAAAAAAAAAABtbHVjAAAAAAAAAAEAAAAMZW5VUwAAACAAAAAcAEcAbwBvAGcAbABlACAASQBu'
'AGMALgAgADIAMAAxADb/2wBDAAMCAgMCAgMDAwMEAwMEBQgFBQQEBQoHBwYIDAoMDAsKCwsNDhIQDQ4R'
'DgsLEBYQERMUFRUVDA8XGBYUGBIUFRT/2wBDAQMEBAUEBQkFBQkUDQsNFBQUFBQUFBQUFBQUFBQUFBQU'
'FBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBT/wAARCAYACAADASIAAhEBAxEB/8QAHQABAAEE'
'AwEAAAAAAAAAAAAAAAYBBAUHAwgJAv/EAF4QAAIBAwIDBAUGCAoHBAgDCQABAgMEBQYRByExEhNBUQgi'
'YXGBCRQykaGxIzRCUmJywdEVFhckMzZVdIKTN0NTc5Ky4TVUotIYGUVWY4OU8CUmREZklcI4daOz8f/E'
'AB0BAQACAgMBAQAAAAAAAAAAAAAEBQMGAQIHCAn/xABJEQEAAgECAwMIBwYFAgUEAgMAAQIDBBEFEiEG'
'MVEiMkFhcYGRsQcTFDNCodE0UlNyweEVI2KS8BaCQ6Ky0vEXJFTCJTVEY+L/2gAMAwEAAhEDEQA/AO1Y'
'APzfe8AAAAAAAAAAAAAAAAAAAHBd3cLSn2m+fgvM+rivC3puc3skRq7upXdVyl08F5GfFj+snr3JOHDO'
'SevcuJZm5dXtdpKKf0djN2lyrqhGoltv1IvCnKrNRit2+RJrK3+bW8Kfiupmz1pWI2jqz6mlK1jaOq5A'
'BCV4AAAAAAAAAAAAAAAAAAAAAo3sm29kvMj+SyDuZuMX6i+0vMzfd3DuYP1pfSa8EYRsnYMf45WWmw/j'
'sAy+Ixyku+qR/VTPq+w3bl2qOyb6x8DL9dWLcrPOopF+WXBh76cKqoPnF9PYZ4xGNxU7et3lTk10SMuQ'
's01m+9VfqJrN96gAMKMAAAAAAAAAAAAAAAAAAAAUlJQi5SeyXiBU4K95Rt1681v5GKvsxKrvCj6sena8'
'WYuTcnu22/aS6aeZ62Tselm3W/RlrjOt7qjHb2sxdSpKrJynJyb8WfKi2+SbZeW+KrXHVdiPmyVEUxQn'
'RXHhjwWfiiT4+Xas6T9hiFg6ymk5Ls+Zm6FJUKMYLolsRs962iIhD1OSt4iKy5QAQ1eAAAAAAAAAAAAA'
'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB8znGnFyk9kgDe3N9DF3+XjBuFHnLxkW+RyrrN06Tah4vzM'
'YlsybiwfisscOn/Fd9Tk5ycpNtvzCi2t9uQS7TKzn2uS6LoTVh6ofJz2ds7qsoLp4vyRxU6cqs1GK3ky'
'RWNkrSml1m+rMOXJyR62DNljHX1rqnCNOKjFbJLY+j5S2Poq1KAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB'
'SUlFbt7LzZxV7qnbx3m9vYYG+yU7uWybjT8EvEy48c3n1M+LDbJPqX99mFDeFH1n4yMLObnJyk92/EoX'
'FpZTu29ltFeJYVrXFC1rSmGq2e5msNa0pU+96zT25+Bh5RcJOLWzT2ZlsD2tqy/J5fWdc3mTMOmo+7mY'
'lmCpRIqVimAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAApKSjFtvZID5q1Y0YOU32UvMwN/lZ3Dc'
'Kb7NP7z5yV/K6qOK5U10XmWSXaey5ssMWGKxzW71rgwRWOa3eH0qcnFy7L7K6syVjiHU2nV5R/NMuren'
'Gn2FFdnboc3z1rO0dXbJqa0naOqKdSQ4mj3NpHdbSfPmVjh7eNTt9l7+W/Iu1HZbLoYMuaLxtCLnzxkj'
'lq+kipTmOZFQlQU5jmBUAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAo2kuYFThuLm'
'FtHtTl2S0vcvChvGntOfT2Iwla4ncTcpybZJx4Zt1nuTMWntfrbpDJ189PfamuXmylvm59tKok0/ExIJ'
'f1NNttk77Pj222S6ElOKkujPotsdUjO0pest+yXJVzG0zCntG0zAAA6gAAAAAAAAAAAAAAABR8kVLa/u'
'Fb205eO2yOYiZnaHMRzTtDhr5ejQqdjnNrrsc9td07uO8HzXVMi75tvzOS3uJ21VTg+fl5k6dPG3TvWV'
'tLXl8nvSroz6OC0uVd0VNLZ+JzkGY2naVbMbTtIADhwAAAAAAAAAAAAAAAAAAAAAAAAAAAUb2Tb6IqY/'
'L3fcUXGL2lLkdq1m07Q70rN7RWGIvbyd1VlzfY35RLZLd7IoZfD2Pa/DTXL8nctLTGKq6tauGjmxOPdG'
'PezXrvp7DJJbMquRUq7Wm87ypr3m87yAA6sYAAAAAAAAAAAAAAAAAABb3t1G0pOTfreC9pzykoxbfJIj'
'eRu/nVdtP1VyiZsVOe3qSMOP6y3XuWtSpKrUc5Pdvmy5x1n87rrdfg482W9OnKrUjCK3bZJrO1jbUlFL'
'n4k3Lk5K7R3rDPl+rrtHe5oRUYpJbJH0AVinAAAAAAAAAAAAAAAAAAAAAAAAEtzBZe+dWo6MHtBdfaZe'
'7q9xbVJ+SItKTlJt82yXp6bzNpTtLj5p5p9ChkLTETrJTm+zHyGIslXqd5Nbxj0XtM92djJmzTWeWrLn'
'zzSeWrgo2VGjt2Irf2lxsglsVIMzM96tmZnvAAcOAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'
'AAAAAAAPirVjQg5TeyHsI69IVqVI0YOUmlFeJHsjkZXc9o8qa8PMpf5CV1Npbqmui8yyLDFh5fKt3rXB'
'g5PKt3qt7gDZ9fAlJxvy2CTbSXNsbbmXxONaaq1V+qjpe8UjeWLJkjHXeVzi7BW1PtyW9SX2IyBRLYqV'
'VrTad5UlrTeeaQAHV0AAAAAAAAAAAAAAAAAAAAAAAAACjey3fJAVLK+ydO0Wy9ap5FrkssknTovn4yMN'
'Jub3b3ftJePBv1snYdPzeVd91rmdxUcpy3bPgp2T7pU5VpqEVu2T+kQs+lYclpayuqqhH4sktC3jb01C'
'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'
'LQJ7NNdVzOto5o2l0vXmrNZTAHFa1e+t4T80cpTzG07KCY2nYABw4AAAAAAAAAAAAAAAAAAAAAAAAADG'
'Z3U2J0xaSucvkrXG28Vu6l1VjBfad6UtktFaRvM+DiZisbyyYXtOs/EX5QPhboZ1aFjdXOpryG6VPGw/'
'B7+2pLl9W51e4h/KYa61B3tDS+JsNNW0t1GtPe4r7ee72in8DfuGdg+P8U2tTByVn038n8vO/JT6jjGi'
'0/S1959XV6ZXV7b2NF1bmvSt6S61Ks1GK+LNVa59K/hbw/U45LVlnVuIb/gLOXfT38to7nkjrPjTrniD'
'WlV1DqjI5LtfkVK7UF7orZL6iFyqOb3k235tnqvDvoixxtbiOpmfVSNvznf5Nbz9p5npgx/H9I/V6O62'
'+VB09YOpS0xpe7yk+kK97VVGH1Ld/caC1t8orxZ1P3tLG3Nhpu2n0jYWylUX+Oe7+rY6uhvc9L0HYPs9'
'w/aaaaLzHpv5X5T0/Jr+fjOuz9+TaPV0SzU/FnWes686uc1PlMnKfNqvdTcf+HfYis6sqku1JuT829z5'
'6nNbWde8qKnQo1K030jTi5P6kbziw4dPXlxVisR4REQp7Xvkne07y4u0xuzYOl/R94i6xlBYnSGVuYz6'
'VHbyjD63sjcGmfk6eLWcVOpd2+Ow1KXX53dJyS/Vimym1naHhGg/adVSvq5o3+Hel4tFqs/3eOZ9zq7z'
'9o3Z6A6V+SxclGWotc9nzp4203f/ABTf7DbGnfk3+E2F7Er+GWzdSPX5zd9iL+EEjSdX9JnZ3TbxTJbJ'
'P+ms/O20LXFwDXZO+sV9s/o8qIpy9pz2+NuryW1C1rVn5U6bl9x7G2/oocKdMUoVcbonGwnDrOrB1W/j'
'JskWO0fgsPBRscPY2sV07q3jH7ka3l+ljSTG+m0tp/mmI+XMvdN2Ry5Y3vliPZEz+jx0xHCTWeda+Y6Y'
'ylyn0cbWe32omuM9EbitloqVHSV1TT8azjD72etcKUKaSjCMUvCK2Poos30q6+33OnpX2zM/ouMXY3Tx'
'97lmfZtH6vMvA/J58WM1CM52dhYxf/eLuO6+C3JvjPkvdb3CTvdTYe036qCqVNvsPRXA1udSm30W6Mxt'
'uarqvpP7Q2tMUtSvsr+sy4t2b0OG01mJn2z+jz3sPkrbxtO817QivFULGT++SJLY/JZ6bgl881rk6r8e'
'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'
'17DtUa9J7prxT8mvFHhM293zPRr5OTJ3V1wmzNpVqynb22Sfcwb5Q7UE5JfE937X9gOH8D4ZXW6O9uas'
'xFuaYnffpv3dJ3/Jq3BOMZdfrPqM0RtO8xt6nbN83uADxh6eAAOTbckWKs/m1BOS9eXNmKxVm7mspv6M'
'Hvz8SRkHUX/BCt1WT8EAAXUhK5Tfb2EJ1Rxt0HoypOnmdWYuxrQ60qlzFzXwXM6tfKD+kvmNAystB6Zu'
'54++vLdXV/e0pbVIUm2o04vw32bb8tjziuruvfV51ritOvVm95TqScpN+9nt3ZX6Nr8b0ddfrc046X82'
'IjeZjxmZ6Rv6O9qXEePRpMs4cVeaY79+57I470xOEWUzNPGUNY2nzipLsxlNSjTb8u01sblo1qdxShVp'
'TjUpzSlGcHupJ9GmeAkW4tefsPZL0M7nL3no56SqZp1ZXXcyUHW37TpKT7G+/s2I/bjsPpOzOlxavSZb'
'Wi1uWYttv3TO8bRHh1d+EcXycQyWx5KxG0b9G7AGa94k8fdBcJUo6n1Fa4+u1vG2T7dV/wCGO7PItPps'
'+syRh09JvafRETM/CGzXyUx15rztHrbCBprh/wCl3wt4lZaji8PqSmsjWfZpW91TlRlN+S7S2bNymXWa'
'HVcPyfVavFbHbwtExP5uMebHmjmx2iY9QAUILKqC0ymXssJZzu8hd0bK2gt5Va9RQil72asu/S34R2WU'
'WPqa4xvzjtdl9mTcE/1ktifptBq9bEzpsNr7d/LWZ2+EMOTNjxfeWiPbLbwLPE5ixz2Po32Ou6N9Z1o9'
'qnXoTUoSXsaLwg2rNZmto2mGWJiY3gOonp0+lR/Jbg6mjNN3SWp8hS2r1qb52dFrr7JPwN4ekFxqx3Av'
'hxkNQXkozvOy6VjbN7OtWa9Ve5dX7jxj1bqzJ651JkM7mLqd5kr6rKtWqze+8m/DyXgke0fRz2SjjGo/'
'xLWV3w456RP4rfpHp8Z2jxarx3iX2XH9Riny7flDFVq87irOpVlKpUm3KU5PdtvxZuvgr6MOc4o6T1Bq'
'67U8dpjEWlWv84a2dzUjFtQhv7ubOL0WfR3yHpAa+pWfZnQwFlKNXI3aXKMN/oJ/nS6Hpzxmx+I4aejf'
'qmwxttTsMZZYerQo0aa2S3j2V8W2evdru2M8K1OHhPD53z3tWJn92JmP/NPo8I6+DWeF8K+047anN5sR'
'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'
'G6yLp3FXuaToVd5+W0G19pl+K6UdeZVLoppfYjCYDH18nfO2t12qs6VRxivHaLe32EmMn1umjJM7bxv7'
'OjBNPq83JHXaWMa2bXU2pwl4pWmlbeOJvrfsW1So5u6i92m/NeRqySfaaa2fkUONXpcWtxTiyx0k0+e+'
'myRkp3u6lCtC5owq0pKdOa7UZRe6aMbndU4vTdLvMjeU7dPopPeT9y6s1Rwq4ivH6NytG8l25Y2HeUd/'
'GL6R+v7zUudzt3qHI1r28qyqVakm+b5RXkjQdL2fvk1F8eWdq1nv8fZ7m4ZuMVx4a3pG9rfk2fxR4t47'
'U2CqYrGQrtTqRlOvOKiml4Jb7moIspsVinJpLm30N80ejxaHF9Vi7u9qOp1OTV5PrMney1pqrK4+yVpa'
'31a3t02+xTl2VuWFa9uLmTdWvVqN825zbJTi+EuqMmoyhjZUaclup15KKa+8leP9HjJ1UneZG3oLxjTj'
'Kb/YRcmv0GnmZm9d/V1n8memk1maIiKzMev+7UjfMpsdgcf6PeHopO6vLm5fio7QRlLjgbpqtZyo06VW'
'hUfSsqjckQLdotDWdo3n3JdeDaqY3mI+LSHD7LXmK1Xj5Wc5JzqxhKEekot800dsVzSIFpHg/idJ36vV'
'UqXtzH6Equ20fgvEnxp/Gtdg12atsEdIjv8AFsvCtLl0mOa5Z7/QAA15dgAAAAAAAAAAAAAAAAAAAAAb'
't9E/KfNdfXVm3srm1ly83FpmkjYvo+5FY3ixhJN7KtKVF/4ov9uxS8axfXcOz0/0z+XVlxdLxLvGChU+'
'cVsAAAAAAAAAAAAAAAAAAAAABjMzZKrT76K9aPUyZSUVJNNbpnatppbmh3peaWi0IgC7yVm7Ws9l6kuj'
'LQt62i0bwva2i0bwuLG8dpWUt/UfVEmp1FVgpRe6ZETK4a+7ElRm/VfRkbPj3jmhE1OLmjnjvZsAFeqg'
'jfEf+oWf/uVX/lZJCN8R/wCoWf8A7lV/5WSdL9/j/mj5pui/asX80fOHnaAD6kfZwAAAAAAAAAAAAAAA'
'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAEx4Pf6T9N/'
'3uP3MhxMeD3+k/Tf97j9zIWu/ZMv8tvlKt4l+w5/5LfKXoIuhUouhU+X3xsAAAAABDuMWrq2guFeq9Q2'
'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'
)
_FLAME_ARCHER_IMAGE_B64 = "".join(_FLAME_ARCHER_IMAGE_B64)
def _flame_archer_image_path():
    """Find the Flame Archer picture: flame_archer.png in assets/, or any .png in assets/, or next to game.py."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    cwd = os.getcwd()
    # 1) Exact name in assets
    for base in [script_dir, cwd]:
        p = os.path.join(base, "assets", "flame_archer.png")
        if p and os.path.isfile(p):
            return os.path.normpath(p)
    # 2) Any PNG in assets/ (so you can drop your exact picture there)
    for base in [script_dir, cwd]:
        adir = os.path.join(base, "assets")
        if os.path.isdir(adir):
            try:
                for name in sorted(os.listdir(adir)):
                    if name.lower().endswith(".png"):
                        p = os.path.join(adir, name)
                        if os.path.isfile(p):
                            return os.path.normpath(p)
            except OSError:
                pass
    # 3) flame_archer.png next to game.py
    p = os.path.join(script_dir, "flame_archer.png")
    if os.path.isfile(p):
        return os.path.normpath(p)
    return None

def _flame_archer_expected_path():
    """Tell user where to put their picture so it loads."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(script_dir, "assets", "flame_archer.png"))

def _load_flame_archer_image():
    """Load Flame Archer picture: optional file in assets/ or next to game.py, else embedded (single file, no install)."""
    path = _flame_archer_image_path()
    if path:
        try:
            surf = pygame.image.load(path)
            return surf.convert_alpha() if surf.get_flags() & pygame.SRCALPHA else surf.convert()
        except Exception:
            pass
    try:
        data = base64.b64decode(_FLAME_ARCHER_IMAGE_B64)
        surf = pygame.image.load(io.BytesIO(data))
        return surf.convert_alpha() if surf.get_flags() & pygame.SRCALPHA else surf.convert()
    except Exception:
        return None

def draw_flame_archer_placeholder(surface, rect):
    """Draw the exact lava pit scene (no image file needed): same as the picture you gave — yellow-orange sky, wavy heat lines, lava, "Lava pit" sign, red block, "swim time" bubble."""
    w, h = rect.w, rect.h
    if w <= 0 or h <= 0:
        return
    x0, y0 = rect.x, rect.y
    # Scale factors so layout works at any size
    sw, sh = w / 320.0, h / 240.0
    def sx(v):
        return x0 + int(v * sw)
    def sy(v):
        return y0 + int(v * sh)
    # Upper ~2/3: vibrant yellow-orange background
    sky_h = int(h * 0.67)
    for y in range(0, sky_h, 2):
        t = y / max(1, sky_h)
        r, g, b = 255, int(235 - t * 60), int(100 - t * 70)
        pygame.draw.line(surface, (r, g, b), (x0, y0 + y), (x0 + w, y0 + y))
    # Wavy vertical darker orange lines (heat)
    step = max(2, sky_h // 35)
    for i in range(6, 18):
        ox = x0 + (w * i // 18) + int(6 * sw * math.sin(i * 0.7))
        pts = [(ox + int(5 * sw * math.sin(y * 0.04)), y0 + y) for y in range(0, sky_h, step)]
        if len(pts) >= 2:
            pygame.draw.lines(surface, (255, 180, 70), False, pts, max(1, int(2 * min(sw, sh))))
    # Bottom 1/3: bright orange lava
    lava_y = y0 + sky_h - int(12 * sh)
    lava_h = h - (lava_y - y0) + int(15 * sh)
    pygame.draw.rect(surface, (255, 120, 40), (x0, lava_y, w, lava_h))
    for px in range(x0, x0 + w, max(2, w // 80)):
        wave = int(10 * sh * math.sin((px - x0) * 0.02))
        pygame.draw.line(surface, (255, 140, 50), (px, lava_y), (px, lava_y + max(0, wave)))
    # Left: gray rocky structure (jagged) + brown sign "Lava pit" with arrow
    rock_pts = [(sx(8), sy(165)), (sx(15), sy(140)), (sx(35), sy(115)), (sx(55), sy(125)), (sx(62), sy(160)), (sx(8), sy(165))]
    pygame.draw.polygon(surface, (100, 95, 90), rock_pts)
    pygame.draw.polygon(surface, (70, 65, 60), rock_pts, 1)
    for _ in range(10):
        sx1 = x0 + int(random.uniform(0.03 * w, 0.18 * w))
        sy1 = lava_y - int(0.12 * h) + random.randint(0, int(0.15 * h))
        pygame.draw.line(surface, (75, 70, 65), (sx1, sy1), (sx1 + random.randint(-3, 3), sy1 + random.randint(1, 6)))
    post_w, post_h = max(2, int(5 * sw)), int(55 * sh)
    pygame.draw.rect(surface, (100, 75, 45), (sx(28), lava_y - post_h, post_w, post_h))
    sign_w, sign_h = int(44 * sw), int(18 * sh)
    sign_brd = pygame.Rect(sx(10), lava_y - post_h - sign_h + 4, sign_w, sign_h)
    pygame.draw.rect(surface, (120, 85, 50), sign_brd)
    pygame.draw.rect(surface, (80, 55, 30), sign_brd, 1)
    lbl = FONT_XS.render("Lava pit", True, (20, 20, 20))
    surface.blit(lbl, (sign_brd.x + (sign_brd.w - lbl.get_width()) // 2, sign_brd.y + (sign_brd.h - lbl.get_height()) // 2))
    ax1, ay1 = sx(52), lava_y - int(50 * sh)
    pygame.draw.line(surface, (20, 20, 20), (ax1, ay1), (ax1 + int(14 * sw), ay1), max(1, int(2 * sw)))
    pygame.draw.polygon(surface, (20, 20, 20), [(ax1 + int(14 * sw), ay1 - int(4 * sh)), (ax1 + int(14 * sw), ay1 + int(4 * sh)), (ax1 + int(20 * sw), ay1)])
    # Center-right: solid red block on lava
    block_w, block_h = max(24, int(0.12 * w)), max(22, int(0.11 * h))
    block_x = x0 + w - block_w - w // 5
    block_y = lava_y - block_h + int(8 * sh)
    pygame.draw.rect(surface, (220, 50, 45), (block_x, block_y, block_w, block_h))
    pygame.draw.rect(surface, (180, 35, 35), (block_x, block_y, block_w, block_h), 2)
    # Speech bubble: "swim time" (tail toward block)
    bubble_w, bubble_h = int(72 * sw), int(32 * sh)
    bubble_cx = block_x + block_w // 2 + int(20 * sw)
    bubble_cy = block_y - int(28 * sh)
    bubble_r = pygame.Rect(bubble_cx - bubble_w // 2, bubble_cy - bubble_h // 2, bubble_w, bubble_h)
    pygame.draw.ellipse(surface, (255, 255, 255), bubble_r)
    pygame.draw.ellipse(surface, (20, 20, 20), bubble_r, 2)
    tail_pts = [(bubble_cx - int(8 * sw), bubble_cy + int(14 * sh)), (bubble_cx + int(4 * sw), bubble_cy + int(18 * sh)), (bubble_cx + int(2 * sw), block_y - 2)]
    pygame.draw.polygon(surface, (255, 255, 255), tail_pts)
    pygame.draw.polygon(surface, (20, 20, 20), tail_pts, 2)
    st = FONT_XS.render("swim time", True, (20, 20, 20))
    surface.blit(st, (bubble_r.centerx - st.get_width() // 2, bubble_r.centery - st.get_height() // 2))

def draw_flame_archer_bow_icon(surface, rect, unlocked=False):
    """Draw a simple bow icon in the given rect. Black/white when locked, gold when mastery unlocked."""
    cx = rect.x + rect.w // 2
    cy = rect.y + rect.h // 2
    r = min(rect.w, rect.h) // 3
    color = (220, 185, 50) if unlocked else (80, 80, 80)
    pygame.draw.arc(surface, color, (cx - r, cy - r, r * 2, r * 2), math.pi * 0.2, math.pi * 0.8, 3)
    pygame.draw.line(surface, color, (cx - r - 2, cy), (cx + r + 2, cy), 2)

def flame_archer_mastery_panel():
    """Panel: picture in middle, description left, rewards + quests right. Large panel."""
    global flame_mastery_unlocked
    panel_w = min(1100, WIDTH - 24)
    panel_h = min(720, HEIGHT - 24)
    panel = pygame.Rect((WIDTH - panel_w) // 2, (HEIGHT - panel_h) // 2, panel_w, panel_h)
    back_rect = pygame.Rect(panel.right - 120, panel.bottom - 52, 100, 44)
    # Load image when panel opens (pygame display already init)
    img_surf = _load_flame_archer_image()
    # Layout: [ description | PICTURE (square) | rewards + quests ]
    col_w = panel_w // 3
    left_x = panel.x + 24
    mid_x = panel.x + col_w
    right_x = panel.x + col_w * 2 + 20
    # Square picture area, centered in middle column
    pic_avail_w = col_w - 32
    pic_avail_h = panel_h - 140
    pic_size = min(pic_avail_w, pic_avail_h)
    pic_x = mid_x + 16 + (pic_avail_w - pic_size) // 2
    pic_y = panel.y + 64 + (pic_avail_h - pic_size) // 2
    pic_rect = pygame.Rect(pic_x, pic_y, pic_size, pic_size)
    while True:
        screen.fill(bg_color)
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        screen.blit(overlay, (0, 0))
        pygame.draw.rect(screen, UI_PANEL_BG, panel)
        pygame.draw.rect(screen, (255, 140, 50), panel, 4)
        mx, my = pygame.mouse.get_pos()
        # Title
        draw_text_centered(FONT_LG, "Flame Archer Mastery", panel.y + 24, (255, 180, 60), y_is_center=False)
        # Middle: square picture with shadow and frame
        shadow = pygame.Rect(pic_rect.x + 4, pic_rect.y + 4, pic_rect.w, pic_rect.h)
        pygame.draw.rect(screen, (20, 18, 16), shadow)
        pygame.draw.rect(screen, (50, 45, 42), pic_rect)
        if img_surf is not None and pic_size > 0:
            iw, ih = img_surf.get_size()
            # Scale to fit inside square, preserve aspect ratio
            scale = min(pic_size / max(1, iw), pic_size / max(1, ih), 1.0)
            nw, nh = int(iw * scale), int(ih * scale)
            if nw > 0 and nh > 0:
                scaled = pygame.transform.smoothscale(img_surf, (nw, nh))
                blit_x = pic_rect.centerx - nw // 2
                blit_y = pic_rect.centery - nh // 2
                screen.blit(scaled, (blit_x, blit_y))
        else:
            t = FONT_SM.render("Image unavailable", True, (180, 160, 140))
            screen.blit(t, (pic_rect.centerx - t.get_width() // 2, pic_rect.centery - t.get_height() // 2))
        pygame.draw.rect(screen, (255, 180, 80), pic_rect, 3)
        pygame.draw.rect(screen, (200, 140, 60), pic_rect, 1)
        # Left: description
        desc_text = "500000 Fahrenheit is light work."
        desc_max_w = col_w - 32
        lines = wrap_text_to_width(FONT_MD, desc_text, desc_max_w)
        desc_y = pic_rect.centery - (len(lines) * 28) // 2
        for i, line in enumerate(lines):
            screen.blit(FONT_MD.render(line, True, (240, 220, 180)), (left_x, desc_y + i * 28))
        # Right: rewards then quest list
        rew_y = pic_y + 8
        screen.blit(FONT_SM.render("Rewards:", True, (255, 200, 80)), (right_x, rew_y))
        rewards = ["Flame duration x2", "Flame Bomb (F)", "1.5x speed & damage in zone"]
        for i, r in enumerate(rewards):
            screen.blit(FONT_SM.render(r, True, (255, 200, 100)), (right_x, rew_y + 24 + i * 22))
        quest_y = rew_y + 24 + len(rewards) * 22 + 16
        screen.blit(FONT_SM.render("Quests:", True, (255, 200, 80)), (right_x, quest_y))
        quests = [
            ("1000 kills (enemies burning)", flame_mastery_kills_burning, 1000),
            ("350 kills (flame DoT final blow)", flame_mastery_kills_dot_final, 350),
            ("5 bosses (while burning)", flame_mastery_bosses_burning, 5),
        ]
        for i, (label, current, target) in enumerate(quests):
            txt = f"{current}/{target} {label}"
            color = (120, 255, 120) if current >= target else UI_TEXT
            screen.blit(FONT_SM.render(txt, True, color), (right_x, quest_y + 22 + i * 22))
        if flame_mastery_unlocked:
            draw_text_centered(FONT_MD, "Mastery Unlocked!", panel.bottom - 80, (255, 220, 80), y_is_center=False)
        draw_button(back_rect, "Back", hover=back_rect.collidepoint(mx, my), text_color=UI_TEXT)
        pygame.display.flip()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                return
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if back_rect.collidepoint(ev.pos):
                    play_sound("menu_click")
                    return
        clock.tick(FPS)

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
            # Flame Archer: bow icon (B&W or gold when mastery unlocked); click icon = mastery panel
            mastery_rect = None
            if cls.name == "Flame Archer":
                icon_rect = pygame.Rect(rect.x + 8, rect.y + (rect.h - 28) // 2, 28, 28)
                draw_flame_archer_bow_icon(screen, icon_rect, unlocked=flame_mastery_unlocked)
                mastery_rect = icon_rect
            rarity = class_rarity_label(cls.name)
            txt_x = rect.x + 44 if cls.name == "Flame Archer" else rect.x + 12
            if selected:
                line1 = f"{cls.name} — Selected"
            elif owned:
                line1 = f"{cls.name} [{rarity}] — Owned (click to equip)"
            else:
                line1 = f"{cls.name} [{rarity}] — {cost} gems"
            line2 = CLASS_SHORT_DESC.get(cls.name, "")
            t1 = FONT_MD.render(line1[:48] + ("…" if len(line1) > 48 else ""), True, UI_TEXT)
            t2 = FONT_SM.render(line2, True, UI_TEXT_MUTED)
            screen.blit(t1, (txt_x, rect.y + 6))
            screen.blit(t2, (txt_x, rect.y + 34))
            buttons.append((rect, cls, cost, selected, owned, mastery_rect))

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
                for r, cls, cost, selected, owned, mastery_rect in buttons:
                    if r.collidepoint(mx, my):
                        play_sound("menu_click")
                        # Flame Archer: bow icon opens mastery panel; rest of row = equip/buy
                        if mastery_rect is not None and mastery_rect.collidepoint(mx, my):
                            flame_archer_mastery_panel()
                            break
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
    waiting_since_ms = None  # when we started waiting (for timeout)

    while True:
        screen.fill(bg_color)
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill(UI_OVERLAY_DARK)
        screen.blit(overlay, (0, 0))
        draw_text_centered(FONT_LG, "Online Lobby", HEIGHT//2 - 200, WHITE, y_is_center=True)
        draw_text_centered(FONT_SM, "Lobby name", name_y - 24, (200, 200, 200))
        draw_text_centered(FONT_SM, "Password", pass_y - 24, (200, 200, 200))
        mx, my = pygame.mouse.get_pos()
        now_ms = pygame.time.get_ticks()

        for (y, text, is_pass) in [(name_y, lobby_name, False), (pass_y, lobby_password, True)]:
            disp = ("*" * len(text)) if is_pass else text
            border = (120, 180, 120) if (y == name_y and focus == 0) or (y == pass_y and focus == 1) else (80, 80, 80)
            pygame.draw.rect(screen, (40, 40, 40), (bar_x, y, bar_w, bar_h))
            pygame.draw.rect(screen, border, (bar_x, y, bar_w, bar_h), 3)
            prompt = FONT_MD.render(disp + ("|" if (pygame.time.get_ticks() // 500) % 2 and ((y == name_y and focus == 0) or (y == pass_y and focus == 1)) else ""), True, (220, 220, 220))
            screen.blit(prompt, (bar_x + 12, y + (bar_h - prompt.get_height())//2))

        can_use = net and net.connected
        if waiting and can_use:
            if waiting_since_ms is None:
                waiting_since_ms = now_ms
            if now_ms - waiting_since_ms > 15000:
                notify_once("No response from server - try again", 2500)
                waiting = None
                waiting_since_ms = None
            else:
                status = net.get_lobby_status()
                if status == "created" or status == "joined":
                    return "ok"
                if isinstance(status, tuple) and status[0] == "error":
                    notify_once(str(status[1])[:50], 2000)
                    waiting = None
                    waiting_since_ms = None
                else:
                    draw_text_centered(FONT_SM, "Waiting...", HEIGHT//2 + 75, (200, 200, 100), y_is_center=True)
        else:
            waiting_since_ms = None
            draw_button(create_rect, "Create", hover=can_use and create_rect.collidepoint(mx, my), text_color=UI_TEXT)
            draw_button(join_rect, "Join", hover=can_use and join_rect.collidepoint(mx, my), text_color=UI_TEXT)
            draw_button(back_rect, "Back", hover=back_rect.collidepoint(mx, my), text_color=UI_TEXT)

        if not (net and net.connected):
            draw_text_centered(FONT_MD, "Connecting...", HEIGHT//2 - 168, (200, 200, 100), y_is_center=True)
            if net and net.last_error:
                err = net.last_error
                if "61" in err or "refused" in err.lower() or "Connection refused" in err:
                    draw_text_centered(FONT_SM, "Run in a terminal:  python game.py --server", HEIGHT//2 - 142, (220, 180, 120), y_is_center=True)
                else:
                    err = (err[:50] + "..") if len(err) > 50 else err
                    draw_text_centered(FONT_XS, err, HEIGHT//2 - 148, (220, 120, 120), y_is_center=True)
            else:
                draw_text_centered(FONT_XS, "Run in a terminal:  python game.py --server", HEIGHT//2 - 132, (140, 140, 140), y_is_center=True)
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
    global flame_mastery_kills_burning, flame_mastery_kills_dot_final, flame_mastery_bosses_burning, flame_mastery_unlocked
    global flame_bomb_ball, flame_bomb_zone
    btn_w = 200
    btn_h = 36
    row = 40
    pad = 24
    panel_center_x = WIDTH // 2
    left_x = panel_center_x - 320
    right_x = panel_center_x - 100
    y_start = 130
    # Every ability from ABILITY_RARITY so admin can toggle each one
    ability_names = list(ABILITY_RARITY.keys())
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
        # ---- Flame Mastery ----
        rects.append(pygame.Rect(left_x, y, 380, 22))
        keys.append("noop")
        labels.append("--- Flame Mastery ---")
        y += 26
        progress_txt = "Unlocked" if flame_mastery_unlocked else f"{flame_mastery_kills_burning}/1000, {flame_mastery_kills_dot_final}/350, {flame_mastery_bosses_burning}/5"
        rects.append(pygame.Rect(left_x, y, 380, 24))
        keys.append("noop")
        labels.append(str(progress_txt))
        y += 26
        add(left_x, btn_w, "Flame Mastery: " + ("Lock" if flame_mastery_unlocked else "Unlock"), "flame_mastery_toggle")
        y += row
        add(left_x, btn_w, "Set max progress + unlock", "flame_mastery_max")
        y += row + 12
        # ---- Flame Bomb ----
        rects.append(pygame.Rect(left_x, y, 380, 22))
        keys.append("noop")
        labels.append("--- Flame Bomb ---")
        y += 26
        fb_status = "ball" if flame_bomb_ball else ("zone" if flame_bomb_zone else "none")
        rects.append(pygame.Rect(left_x, y, 380, 24))
        keys.append("noop")
        labels.append(str(fb_status))
        y += 26
        add(left_x, btn_w, "Clear Flame Bomb", "flame_bomb_clear")
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

    content_height = 1700
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
                        for k in ABILITY_RARITY:
                            owned_abilities[k] = True
                        knockback_level = 5
                        pierce_level = 3
                        corrosive_level = 5
                    elif key == "corrosive_max":
                        owned_abilities["Corrosive"] = True
                        corrosive_level = 5
                    elif key == "flame_mastery_toggle":
                        flame_mastery_unlocked = not flame_mastery_unlocked
                    elif key == "flame_mastery_max":
                        flame_mastery_kills_burning = 1000
                        flame_mastery_kills_dot_final = 350
                        flame_mastery_bosses_burning = 5
                        flame_mastery_unlocked = True
                    elif key == "flame_bomb_clear":
                        flame_bomb_ball = None
                        flame_bomb_zone = None
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
    global net, online_mode
    global vampire_fly_until_ms, vampire_fly_cooldown_until_ms
    global assassin_invis_until_ms, assassin_invis_cooldown_until_ms
    global mad_scientist_overcharge_until_ms, mad_scientist_overcharge_cooldown_until_ms
    global assassin_active_bounties, assassin_bounty_refresh_at_ms
    global robbers_gun
    global flame_bomb_ball, flame_bomb_zone

    gems_this_run = 0
    player.center = (WIDTH//2, HEIGHT//2)

    spawn_preview_active = True
    spawn_preview_start_ms = pygame.time.get_ticks()
    running = True
    admin_code_buffer = []
    last_corrosive_damage_ms = 0
    wave_banner_until_ms = 0
    wave_banner_number = 0
    online_disconnect_since_ms = None  # set when we detect disconnect in online mode

    while running:
        dt = clock.tick(FPS) 
        now_ms = pygame.time.get_ticks()
        # Online: detect disconnect and return to menu after 3s
        if online_mode and net is not None:
            if not net.connected:
                if online_disconnect_since_ms is None:
                    online_disconnect_since_ms = now_ms
                elif now_ms - online_disconnect_since_ms >= 3000:
                    for _ in range(60):
                        screen.fill((30, 20, 20))
                        draw_text_centered(FONT_LG, "Disconnected", HEIGHT//2 - 30, (220, 100, 100), y_is_center=True)
                        draw_text_centered(FONT_SM, "Returning to menu...", HEIGHT//2 + 20, (180, 180, 180), y_is_center=True)
                        pygame.display.flip()
                        pygame.event.pump()
                        clock.tick(20)
                    online_mode = False
                    net = None
                    return
            else:
                online_disconnect_since_ms = None
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
                # Flame Bomb (Flame Archer mastery): F = throw ball, F again = create zone
                if ev.key == pygame.K_f and isinstance(player_class, FlameArcher) and flame_mastery_unlocked:
                    if flame_bomb_zone is not None:
                        pass  # zone active, ignore
                    elif flame_bomb_ball is not None:
                        flame_bomb_zone = {
                            "cx": flame_bomb_ball["x"], "cy": flame_bomb_ball["y"],
                            "ttl_ms": FLAME_BOMB_ZONE_DURATION_MS, "radius": FLAME_BOMB_ZONE_RADIUS,
                            "last_burn_tick_ms": now_ms,
                        }
                        flame_bomb_ball = None
                    else:
                        mx, my = pygame.mouse.get_pos()
                        dx = mx - player.centerx
                        dy = my - player.centery
                        d = math.hypot(dx, dy) or 1.0
                        flame_bomb_ball = {
                            "x": float(player.centerx), "y": float(player.centery),
                            "vx": FLAME_BOMB_BALL_SPEED * dx / d, "vy": FLAME_BOMB_BALL_SPEED * dy / d,
                        }
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

        # Flame Bomb: update ball position; update zone ttl and apply burn to enemies in zone
        if flame_bomb_ball is not None:
            flame_bomb_ball["x"] += flame_bomb_ball["vx"]
            flame_bomb_ball["y"] += flame_bomb_ball["vy"]
            if not screen.get_rect().collidepoint(flame_bomb_ball["x"], flame_bomb_ball["y"]):
                flame_bomb_ball = None
        if flame_bomb_zone is not None:
            flame_bomb_zone["ttl_ms"] -= dt
            if flame_bomb_zone["ttl_ms"] <= 0:
                flame_bomb_zone = None
            elif not online_mode:
                if now_ms - flame_bomb_zone.get("last_burn_tick_ms", 0) >= 1000:
                    flame_bomb_zone["last_burn_tick_ms"] = now_ms
                    cx = flame_bomb_zone["cx"]
                    cy = flame_bomb_zone["cy"]
                    r = flame_bomb_zone["radius"]
                    for e in enemies[:]:
                        if math.hypot(e.rect.centerx - cx, e.rect.centery - cy) <= r:
                            e.burn_ms_left = max(getattr(e, "burn_ms_left", 0), FLAME_BOMB_ZONE_BURN_MS)
                            e.last_status_tick = 0

        def _player_in_flame_bomb_zone():
            if flame_bomb_zone is None:
                return False
            return math.hypot(player.centerx - flame_bomb_zone["cx"], player.centery - flame_bomb_zone["cy"]) <= flame_bomb_zone["radius"]

        # movement (disabled while typing). Vampire fly = 1.5x speed; Flame Bomb zone = 1.5x speed
        keys = pygame.key.get_pressed()
        if not chat_open:
            speed = player_speed * (Vampire.FLY_SPEED_MULT if (isinstance(player_class, Vampire) and now_ms < vampire_fly_until_ms) else 1.0)
            if isinstance(player_class, FlameArcher) and _player_in_flame_bomb_zone():
                speed *= 1.5
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

            # remote arrows: only show other players' shots (skip our own; need id from server)
            myid = net.id
            if myid is not None:
                for s in net_shots:
                    if s.get("pid") == myid:
                        continue
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
                    record_flame_mastery_progress(enemy, dot_final_blow=getattr(enemy, "_killed_by_burn_dot", False))
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

        # Flame Bomb zone (orange tint circle)
        if flame_bomb_zone is not None:
            cx, cy = int(flame_bomb_zone["cx"]), int(flame_bomb_zone["cy"])
            rad = flame_bomb_zone["radius"]
            alpha = min(80, 40 + flame_bomb_zone["ttl_ms"] // 100)
            surf = pygame.Surface((rad * 2 + 10, rad * 2 + 10), pygame.SRCALPHA)
            pygame.draw.circle(surf, (255, 140, 50, alpha), (rad + 5, rad + 5), rad)
            screen.blit(surf, (cx - rad - 5, cy - rad - 5))
        # Flame Bomb ball (red projectile)
        if flame_bomb_ball is not None:
            bx, by = int(flame_bomb_ball["x"]), int(flame_bomb_ball["y"])
            pygame.draw.circle(screen, (220, 40, 40), (bx, by), 12)
            pygame.draw.circle(screen, (255, 80, 80), (bx, by), 8)

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

    # server (e.g. DigitalOcean Droplet: set PORT=8765, open port in firewall, then python game.py --server)
    if "--server" in sys.argv:
        if not ONLINE_ENABLED:
            print("Online is temporarily closed. Server start disabled.")
            sys.exit(1)
        if websockets is None:
            print("websockets not installed. Run: python -m pip install websockets")
            sys.exit(1)
        host = os.environ.get("HOST", "0.0.0.0")
        try:
            port = int(os.environ.get("PORT", "8765"))
        except ValueError:
            port = 8765
        asyncio.run(run_server(host, port, 20))
        sys.exit(0)

    reset_game()
    while True:
        choice = main_menu()
        if choice == "resume":
            pass
        game_loop()

# ========== END PART 3 ==========  