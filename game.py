# =========================
# Infinite Archer — game.py
# FULL REPLACEMENT (PART 1/3)
# =========================
import os, sys, json, math, random, time, threading, asyncio
import wave
import io
import struct

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
ONLINE_ENABLED = False

online_mode = False
online_coop_enemies = True  # server-authoritative enemies
net = None

# Settings (volume, fullscreen, music); loaded on startup
def load_settings():
    out = {"volume": 0.7, "fullscreen": True, "music": True}
    try:
        if os.path.isfile(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r") as f:
                data = json.load(f)
            out["volume"] = max(0, min(1, float(data.get("volume", 0.7))))
            out["fullscreen"] = bool(data.get("fullscreen", True))
            out["music"] = bool(data.get("music", True))
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

def _make_music_loop():
    """Gentle ambient pad loop: slow swell, low notes, no melody. ~6 sec."""
    sample_rate = 44100
    duration_sec = 6.0
    n_frames = int(sample_rate * duration_sec)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        frames = []
        for i in range(n_frames):
            t = i / sample_rate
            # Slow breathing envelope (one swell per ~3 sec)
            env = 0.5 + 0.5 * math.sin(2 * math.pi * 0.32 * t)
            # Two low pad notes, no attack - just sustained and soft
            a = math.sin(2 * math.pi * 65 * t) * 0.5
            b = math.sin(2 * math.pi * 98 * t) * 0.35
            s = int(32767 * 0.045 * env * (a + b))
            frames.append(struct.pack("h", max(-32768, min(32767, s))))
        w.writeframes(b"".join(frames))
    return buf.getvalue()

_music_loop_bytes = None
if _mixer_ok:
    try:
        _music_loop_bytes = _make_music_loop()
    except Exception:
        pass

def start_music():
    if not _mixer_ok or not settings.get("music", False):
        return
    base = os.path.dirname(os.path.abspath(__file__))
    for name in ("music.ogg", "music.wav"):
        path = os.path.join(base, name)
        if os.path.isfile(path):
            try:
                pygame.mixer.music.load(path)
                pygame.mixer.music.set_volume(0.4 * settings.get("volume", 0.7))
                pygame.mixer.music.play(-1)
            except Exception:
                pass
            return
    # No file: use gentle built-in pad loop
    if _music_loop_bytes is not None:
        try:
            buf = io.BytesIO(_music_loop_bytes)
            pygame.mixer.music.load(buf)
            pygame.mixer.music.set_volume(0.35 * settings.get("volume", 0.7))
            pygame.mixer.music.play(-1)
        except Exception:
            pass

def stop_music():
    try:
        pygame.mixer.music.stop()
    except Exception:
        pass

def _init_sounds():
    if not _mixer_ok:
        return
    try:
        _sounds["shoot"] = pygame.mixer.Sound(buffer=io.BytesIO(_make_tone(380, 0.06, 0.15)))
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
    "Flame": "Rare",
    "Poison": "Rare",
    "Lightning": "Rare",
    "Knockback": "Epic",
    "Piercing": "Epic",
    "Double Shot": "Legendary",
    "Corrosive": "Mythical"
}

DEFAULTS = {
    "player_size": 40,
    "player_speed": 5,
    "max_hp": 100,
    "arrow_speed": 18,
    "arrow_damage": 20,
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

def draw_text_centered(font, text, y, color=BLACK):
    surf = font.render(text, True, color)
    screen.blit(surf, (WIDTH//2 - surf.get_width()//2, y))

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

        self.players = {}   # pid -> dict
        self.enemies = {}   # eid -> dict
        self.shots = []     # list of shot dicts (remote arrows)
        self.chat = []
        

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
                    ping_interval=20,
                    ping_timeout=20,
                    max_size=2_000_000,
                    open_timeout=6,
                    close_timeout=3,
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
                        if t == "hello":
                            self.id = data.get("id")
                            self.last_status = "ONLINE"
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

            await asyncio.sleep(1.0)

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

    def snapshot(self):
        with self._lock:
            return dict(self.players), dict(self.enemies), list(self.shots), list(self.chat)

# ---------- ONLINE (SERVER) ----------
async def run_server(host="0.0.0.0", port=8765, tick_hz=20):
    if websockets is None:
        print("websockets not installed. Run: python -m pip install websockets")
        return

    import uuid
    players = {}   # pid -> dict
    enemies = {}   # eid -> dict
    shots = []     # recent arrows fired (for other clients)
    chat = []      # recent chat messages
    connected = set()

    wave = 1
    enemies_per_wave = 5
    next_enemy_id = 1

    def spawn_wave():
        nonlocal enemies, next_enemy_id, enemies_per_wave
        enemies = {}
        n = int(enemies_per_wave)
        for _ in range(n):
            eid = str(next_enemy_id); next_enemy_id += 1
            etype = random.choices(["normal","fast","tank","archer"], weights=[50,30,10,10])[0]

            side = random.choice(["top","bottom","left","right"])
            if side == "top":
                x, y = random.randint(80, 1200), -40
            elif side == "bottom":
                x, y = random.randint(80, 1200), 900
            elif side == "left":
                x, y = -40, random.randint(80, 700)
            else:
                x, y = 1400, random.randint(80, 700)

            if etype == "normal": hp, spd = 40, 2.0
            elif etype == "fast": hp, spd = 30, 3.0
            elif etype == "tank": hp, spd = 80, 1.2
            else: hp, spd = 36, 2.0

            enemies[eid] = {"id":eid,"x":float(x),"y":float(y),"w":30,"h":30,"hp":float(hp),"etype":etype,"spd":float(spd)}

    spawn_wave()

    async def handler(ws):
        pid = uuid.uuid4().hex[:8]

        # Ghost fix: not active until first input arrives
        players[pid] = {"x":0.0,"y":0.0,"weapon":"bow","name":"Player","active":False,"last":time.time()}
        connected.add(ws)
        await ws.send(json.dumps({"type":"hello","id":pid}))
        # send current chat history
        try:
            await ws.send(json.dumps({"type": "chat", "messages": chat[-60:]}))
        except Exception:
            pass

        try:
            async for msg in ws:
                try:
                    data = json.loads(msg)
                except Exception:
                    continue

                t = data.get("type")
                if t == "input":
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

                elif t == "shoot":
                    # store a remote arrow event
                    p = players.get(pid)
                    if not p or not p.get("active", False):
                        continue
                    sx = float(data.get("x", p["x"]))
                    sy = float(data.get("y", p["y"]))
                    vx = float(data.get("vx", 0))
                    vy = float(data.get("vy", 0))
                    shots.append({"pid":pid,"x":sx,"y":sy,"vx":vx,"vy":vy,"ts":time.time()})
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
                            websockets.broadcast(connected, json.dumps({"type": "chat", "messages": chat[-60:]}))
                        except Exception:
                            pass

        finally:
            players.pop(pid, None)
            connected.discard(ws)

    async def tick_loop():
        nonlocal wave, enemies_per_wave, shots
        while True:
            # prune inactive / stale
            now = time.time()
            for pid in list(players.keys()):
                if now - float(players[pid].get("last", now)) > 15:
                    players.pop(pid, None)

            # move enemies toward closest active player
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

            # next wave
            if not enemies:
                wave += 1
                enemies_per_wave = max(1, int(round(enemies_per_wave*1.10)))
                spawn_wave()

            # only broadcast active players
            payload_players = {pid:p for pid,p in players.items() if p.get("active", False)}

            # prune old shots (keep ~2 seconds)
            shots = [s for s in shots if now - s.get("ts", now) < 2.0]
            # prune chat older than 10 minutes
            chat[:] = [c for c in chat if now - float(c.get("ts", now)) < 600]

            if connected:
                try:
                    websockets.broadcast(connected, json.dumps({"type":"state","players":payload_players}))
                    websockets.broadcast(connected, json.dumps({"type":"enemies","enemies":list(enemies.values())}))
                    websockets.broadcast(connected, json.dumps({"type":"shots","shots":shots}))
                except Exception:
                    pass

            await asyncio.sleep(1.0 / float(tick_hz))

    async with websockets.serve(handler, host, port, ping_interval=20, ping_timeout=20, max_size=2_000_000):
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

        self.burn_ms_left = 0
        self.poison_ms_left = 0
        self.last_status_tick = 0
        self.shoot_timer = 0
        self.shoot_interval = 1800 + random.randint(-400,400)
        self.summon_timer = 0

    def move_towards(self, tx, ty):
        dx, dy = tx - self.rect.centerx, ty - self.rect.centery
        dist = math.hypot(dx, dy)
        if dist==0: return
        spd = self.speed*(0.5 if self.poison_ms_left>0 else 1.0)
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
        if self.burn_ms_left>0 or self.poison_ms_left>0:
            if now_ms - self.last_status_tick >= 1000:
                self.last_status_tick = now_ms
                if self.burn_ms_left>0:
                    self.hp -= 5
                    small_dots.append({"x":self.rect.centerx,"y":self.rect.top-6,"color":ORANGE,"ttl":30,"vy":-0.2})
                    floating_texts.append({"x":self.rect.centerx,"y":self.rect.top-18,"txt":"-5","color":ORANGE,"ttl":1000,"vy":-0.6,"alpha":255})
                    self.burn_ms_left = max(0,self.burn_ms_left-1000)
                if self.poison_ms_left>0:
                    self.hp -= 5
                    small_dots.append({"x":self.rect.centerx,"y":self.rect.top-6,"color":PURPLE,"ttl":30,"vy":-0.2})
                    floating_texts.append({"x":self.rect.centerx,"y":self.rect.top-18,"txt":"-5","color":PURPLE,"ttl":1000,"vy":-0.6,"alpha":255})
                    self.poison_ms_left = max(0,self.poison_ms_left-1000)
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
    color = ORANGE
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
    def on_arrow_fire(self, mx, my):
        if not enemies:
            return False
        closest = min(enemies, key=lambda e: math.hypot(e.rect.centerx - player.centerx, e.rect.centery - player.centery))
        arrows.append(Arrow(player.centerx, player.centery, mx, my, pierce=pierce_level, target=closest, turn_rate=0.24, color=BLUE))
        return True

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
}

def class_rarity_label(cls_name):
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
arrows = []
enemy_arrows = []
enemies = []
pending_orbs = []
remote_arrows = []  # <-- friends arrows

# Assassin hit list: 3 active bounties, refresh on timer (persists in save)
assassin_active_bounties = []
assassin_bounty_refresh_at_ms = 0
assassin_kills = {"normal": 0, "fast": 0, "tank": 0, "archer": 0, "boss": 0}
assassin_completed_bounties = set()

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
        pygame.draw.line(line_surf, (*YELLOW, alpha), (x1 - min_x, y1 - min_y), (x2 - min_x, y2 - min_y), 2)
        surface.blit(line_surf, (min_x, min_y))

    # floating text (damage numbers, etc.)
    for ft in floating_texts:
        txt = str(ft.get("txt", ""))
        if not txt:
            continue
        color = ft.get("color", BLACK)
        alpha = int(ft.get("alpha", 255))
        surf = FONT_SM.render(txt, True, color)
        if alpha < 255:
            surf = surf.convert_alpha()
            surf.set_alpha(alpha)
        surface.blit(surf, (int(ft.get("x", 0)), int(ft.get("y", 0))))

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
bg_color = WHITE

# save-slot meta shown in menus
slot_meta_cache = {1: {"gems":0,"player_class":"No Class"},
                   2: {"gems":0,"player_class":"No Class"},
                   3: {"gems":0,"player_class":"No Class"}}

def load_slot_meta(slot):
    path = get_save_path(slot)
    if not os.path.exists(path):
        slot_meta_cache[int(slot)] = {"gems":0,"player_class":"No Class"}
        return slot_meta_cache[int(slot)]
    try:
        with open(path,"r") as f:
            data = json.load(f)
        meta = {"gems": int(data.get("gems",0)),
                "player_class": str(data.get("player_class","No Class"))}
        slot_meta_cache[int(slot)] = meta
        return meta
    except Exception:
        slot_meta_cache[int(slot)] = {"gems":0,"player_class":"No Class"}
        return slot_meta_cache[int(slot)]

def refresh_all_slot_meta():
    for s in (1,2,3):
        load_slot_meta(s)

# ---------- Save / Load ----------
def save_game():
    try:
        data = {
            "player": [player.x, player.y, player.width, player.height],
            "player_hp": player_hp,
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
            "corrosive_level": corrosive_level,
            "enemies_per_wave": enemies_per_wave,
            "player_class": player_class.name,
            "assassin_kills": assassin_kills,
            "assassin_completed_bounties": list(assassin_completed_bounties),
            "assassin_active_bounties": assassin_active_bounties,
            "assassin_bounty_refresh_remaining_ms": max(0, assassin_bounty_refresh_at_ms - pygame.time.get_ticks()),
        }
        with open(get_save_path(),"w") as f:
            json.dump(data,f)
        load_slot_meta(current_save_slot)
    except Exception as e:
        print("Save failed:", e)

def load_game():
    global player_hp, arrow_damage, player_exp, player_level, exp_required
    global wave, score, gems, pierce_level, knockback_level, owned_abilities, corrosive_level
    global enemies_per_wave, player_class
    global vampire_fly_until_ms, vampire_fly_cooldown_until_ms
    global assassin_invis_until_ms, assassin_invis_cooldown_until_ms
    global assassin_kills, assassin_completed_bounties, assassin_active_bounties, assassin_bounty_refresh_at_ms

    if not os.path.exists(get_save_path()):
        return False
    try:
        with open(get_save_path(),"r") as f:
            data = json.load(f)

        px,py,w,h = data.get("player",[WIDTH//2, HEIGHT//2, 40, 40])
        player.x, player.y, player.width, player.height = px,py,w,h

        player_hp = int(data.get("player_hp", DEFAULTS["max_hp"]))
        arrow_damage = int(data.get("arrow_damage", DEFAULTS["arrow_damage"]))
        player_exp = int(data.get("player_exp", 0))
        player_level = int(data.get("player_level", 1))
        exp_required = int(data.get("exp_required", 10))

        wave = int(data.get("wave", 1))
        score = int(data.get("score", 0))
        gems = int(data.get("gems", 0))

        pierce_level = int(data.get("pierce_level", 0))
        knockback_level = int(data.get("knockback_level", 1))
        owned_abilities = dict(data.get("owned_abilities", {}))
        corrosive_level = int(data.get("corrosive_level", 0))
        enemies_per_wave = int(data.get("enemies_per_wave", DEFAULTS["enemies_per_wave_start"]))

        class_name = data.get("player_class","No Class")
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
        floating_texts.clear(); small_dots.clear(); lightning_lines.clear()
        chat_messages.clear()
        vampire_fly_until_ms = 0
        vampire_fly_cooldown_until_ms = 0
        assassin_invis_until_ms = 0
        assassin_invis_cooldown_until_ms = 0
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
        overlay.fill((0, 0, 0, 180))
        screen.blit(overlay, (0, 0))
        draw_text_centered(FONT_LG, "Hit List", 50, WHITE)
        if assassin_bounty_refresh_at_ms > now_ms:
            sec = (assassin_bounty_refresh_at_ms - now_ms) // 1000
            draw_text_centered(FONT_SM, f"Refreshes in {sec}s", 110, LIGHT_GRAY)
        else:
            draw_text_centered(FONT_SM, "Refreshing next frame...", 110, LIGHT_GRAY)
        y = 160
        for slot in assassin_active_bounties:
            rwd = f"+{slot['reward'][1]} {slot['reward'][0].replace('_', ' ')}"
            line = f"{slot['name']} ({slot.get('progress', 0)}/{slot['count']}) -> {rwd}"
            txt = FONT_MD.render(line, True, WHITE)
            screen.blit(txt, (WIDTH//2 - txt.get_width()//2, y))
            y += 48
        pygame.draw.rect(screen, LIGHT_GRAY, close_rect)
        pygame.draw.rect(screen, WHITE, close_rect, 2)
        screen.blit(FONT_MD.render("Close", True, BLACK), (close_rect.x + 68, close_rect.y + 12))
        pygame.display.flip()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                return
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if close_rect.collidepoint(ev.pos):
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
        # dim overlay
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 140))
        screen.blit(overlay, (0, 0))
        draw_text_centered(FONT_LG, "Paused", HEIGHT//2 - 180, WHITE)
        mx, my = pygame.mouse.get_pos()
        for rect, label in [(resume_rect, "Resume"), (save_rect, "Save"), (quit_rect, "Quit to Menu")]:
            color = LIGHT_GRAY if rect.collidepoint(mx, my) else (200, 200, 200)
            pygame.draw.rect(screen, color, rect)
            pygame.draw.rect(screen, WHITE, rect, 2)
            screen.blit(FONT_MD.render(label, True, BLACK), (rect.x + (rect.w - FONT_MD.size(label)[0])//2, rect.y + 14))
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
                    floating_texts.append({"x": center_x, "y": HEIGHT//2 + 120, "txt": "Saved!", "color": BLUE, "ttl": 60, "vy": -0.5, "alpha": 255})
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
    global knockback_level, pierce_level, pierce_max_level, owned_abilities
    global wave, enemies_per_wave, score
    global weapon, gems
    global player_level, player_exp, exp_required
    global in_collection_phase, collection_start_ms, collection_duration_ms
    global spawn_pattern_positions, spawn_preview_ms, spawn_preview_active, spawn_preview_start_ms
    global corrosive_level
    global player_class
    global net, online_mode
    global vampire_fly_until_ms, vampire_fly_cooldown_until_ms
    global assassin_invis_until_ms, assassin_invis_cooldown_until_ms
    global assassin_kills, assassin_completed_bounties, assassin_active_bounties, assassin_bounty_refresh_at_ms

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
        "Flame": False, "Poison": False, "Lightning": False,
        "Knockback": False, "Piercing": False, "Double Shot": False, "Corrosive": False
    }

    enemies.clear(); arrows.clear(); enemy_arrows.clear(); pending_orbs.clear()
    remote_arrows.clear()
    floating_texts.clear(); small_dots.clear(); lightning_lines.clear()
    chat_messages.clear()

    wave = 1
    enemies_per_wave = DEFAULTS["enemies_per_wave_start"]
    score = 0
    weapon = "bow"

    player_level = 1
    player_exp = 0
    exp_required = 10 + 10*(player_level-1)

    meta = load_slot_meta(current_save_slot)
    gems = int(meta.get("gems",0))

    in_collection_phase = False
    collection_start_ms = None
    collection_duration_ms = 5000

    spawn_pattern_positions = generate_spawn_pattern(120)
    spawn_preview_ms = 2500  # faster start
    spawn_preview_active = False
    spawn_preview_start_ms = None

    corrosive_level = 0
    player_class = NoClass()

    vampire_fly_until_ms = 0
    vampire_fly_cooldown_until_ms = 0
    assassin_invis_until_ms = 0
    assassin_invis_cooldown_until_ms = 0
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
    pygame.draw.rect(screen, (180, 20, 80), (x, y, bar_w, bar_h), 3)
    label = FONT_SM.render("BOSS", True, WHITE)
    screen.blit(label, (x + 8, y + (bar_h - label.get_height())//2))
    hp_txt = FONT_SM.render(f"{int(boss.hp)} / {int(max_hp)}", True, WHITE)
    screen.blit(hp_txt, (x + bar_w - hp_txt.get_width() - 8, y + (bar_h - hp_txt.get_height())//2))

# ---------- FX / Orbs / UI ----------
def spawn_orb(x,y,amount=1):
    for _ in range(int(amount)):
        pending_orbs.append({"x": float(x+random.randint(-10,10)), "y": float(y+random.randint(-10,10)), "amount": 1})

def draw_hp_bar(hp):
    w,h = 300,28
    x,y = 12,12
    pygame.draw.rect(screen, DARK_GRAY, (x,y,w,h))
    frac = (hp/max_hp) if max_hp>0 else 0
    pygame.draw.rect(screen, GREEN, (x,y,int(w*max(0,min(1,frac))),h))
    pygame.draw.rect(screen, BLACK, (x,y,w,h),2)

def draw_exp_bar():
    margin = 12
    w = WIDTH - margin*2
    h = 18
    x = margin
    y = HEIGHT - h - 12
    pygame.draw.rect(screen, DARK_GRAY, (x,y,w,h))
    frac = min(1.0, player_exp/exp_required) if exp_required>0 else 0.0
    pygame.draw.rect(screen, BLUE, (x,y,int(w*frac),h))
    pygame.draw.rect(screen, BLACK, (x,y,w,h),2)
    lvl_txt = FONT_SM.render(f"Level: {player_level}  EXP: {player_exp}/{exp_required}", True, BLACK)
    screen.blit(lvl_txt, (x+6, y-24))

def notify_once(msg, duration=900):
    start = pygame.time.get_ticks()
    while pygame.time.get_ticks() - start < duration:
        screen.fill(bg_color)
        draw_text_centered(FONT_LG, msg, HEIGHT//2)
        pygame.display.flip()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                save_game(); pygame.quit(); sys.exit()
        clock.tick(FPS)

# ---------- Ability choice between waves (repeat allowed) ----------
def ability_choice_between_waves():
    global player_hp, arrow_damage, knockback_level, pierce_level, corrosive_level

    all_options = list(ABILITY_RARITY.keys())
    # Don't offer Flame, Poison, Lightning, Double Shot again if already owned
    one_shot_abilities = ("Flame", "Poison", "Lightning", "Double Shot")
    def already_owned_no_repeat(ability):
        if ability in one_shot_abilities and owned_abilities.get(ability, False):
            return True
        return False
    available_options = [a for a in all_options if not already_owned_no_repeat(a)]
    if not available_options:
        available_options = all_options[:]

    rarity_weights = [("Common",50),("Rare",30),("Epic",15),("Legendary",4),("Mythical",1)]
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
        return ability_label

    buttons = []
    for i,c in enumerate(choices):
        rect = pygame.Rect(WIDTH//2 - 220 + i*280, HEIGHT//2 - 50, 260, 80)
        buttons.append((rect,c))

    while True:
        screen.fill(bg_color)
        draw_text_centered(FONT_LG, f"Choose an Upgrade ({chosen_rarity})", HEIGHT//2 - 160, RARITY_COLORS.get(chosen_rarity, BLUE))
        mx,my = pygame.mouse.get_pos()
        for rect,label in buttons:
            display = ability_display_name(label)
            rarity = ABILITY_RARITY.get(label,"Common")
            pygame.draw.rect(screen, LIGHT_GRAY, rect)
            pygame.draw.rect(screen, RARITY_COLORS.get(rarity, BLACK), rect, 4)
            txt = FONT_MD.render(display, True, BLACK)
            if txt.get_width() > rect.w - 24:
                txt = FONT_SM.render(display, True, BLACK)
            screen.blit(txt, (rect.x+12, rect.y+18))
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
                        elif label == "Flame":
                            owned_abilities["Flame"] = True
                        elif label == "Poison":
                            owned_abilities["Poison"] = True
                        elif label == "Lightning":
                            owned_abilities["Lightning"] = True
                        elif label == "Knockback":
                            knockback_level = min(5, knockback_level + 1)
                            owned_abilities["Knockback"] = True
                        elif label == "Piercing":
                            pierce_level = min(pierce_max_level, pierce_level + 1)
                            owned_abilities["Piercing"] = True
                        elif label == "Double Shot":
                            owned_abilities["Double Shot"] = True
                        elif label == "Corrosive":
                            owned_abilities["Corrosive"] = True
                            corrosive_level = min(5, max(1, corrosive_level + 1))
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
        pygame.draw.rect(screen, ACID_YELLOW, (left, top, size, size), 2)

def handle_arrow_hit(enemy, dmg=None):
    dmg = dmg if dmg is not None else arrow_damage
    enemy.hp -= dmg
    play_sound("hit")
    floating_texts.append({"x":enemy.rect.centerx,"y":enemy.rect.top-12,"txt":f"-{int(dmg)}","color":RED,"ttl":1000,"vy":-0.6,"alpha":255})

    try:
        player_class.on_arrow_hit(enemy, dmg)
    except:
        pass

    now = pygame.time.get_ticks()
    if owned_abilities.get("Flame", False):
        enemy.burn_ms_left = 3000; enemy.last_status_tick = now - 1000

    if enemy.hp <= 0:
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

    play_sound("shoot")
    if owned_abilities.get("Double Shot", False):
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
    "Mad Scientist": "Curving AI arrows",
}

def class_shop_menu():
    global gems, player_class
    # Layout: fixed compact class boxes (don't grow on big screens)
    n_classes = len(PLAYER_CLASS_ORDER)
    area_top = 160
    back_height = 72
    row_h = min(70, max(52, (HEIGHT - area_top - back_height) // n_classes))
    btn_h = row_h - 6
    y_start = area_top
    max_w = min(520, WIDTH - 80)
    while True:
        screen.fill(bg_color)
        draw_text_centered(FONT_LG, "Class Shop", 60)
        draw_text_centered(FONT_MD, f"Gems: {gems}", 120)

        buttons = []
        for i, cls in enumerate(PLAYER_CLASS_ORDER):
            y = y_start + i * row_h
            rect = pygame.Rect(WIDTH//2 - max_w//2, y, max_w, btn_h)
            cost = CLASS_COSTS[cls.name]
            selected = (player_class.name == cls.name)

            pygame.draw.rect(screen, LIGHT_GRAY, rect)
            pygame.draw.rect(screen, cls.color, rect, 4)

            rarity = class_rarity_label(cls.name)
            line1 = f"{cls.name} [{rarity}] — {cost} gems" if not selected else f"{cls.name} — Selected"
            line2 = CLASS_SHORT_DESC.get(cls.name, "")
            t1 = FONT_MD.render(line1[:42] + ("…" if len(line1) > 42 else ""), True, BLACK)
            t2 = FONT_SM.render(line2, True, DARK_GRAY)
            screen.blit(t1, (rect.x + 12, rect.y + 6))
            screen.blit(t2, (rect.x + 12, rect.y + 34))
            buttons.append((rect, cls, cost, selected))

        back_y = y_start + n_classes * row_h + 8
        back_rect = pygame.Rect(WIDTH//2 - 120, min(back_y, HEIGHT - 60), 240, 56)
        pygame.draw.rect(screen, LIGHT_GRAY, back_rect)
        pygame.draw.rect(screen, BLACK, back_rect, 3)
        screen.blit(FONT_MD.render("Back", True, BLACK), (back_rect.x + 82, back_rect.y + 14))
        pygame.display.flip()

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                save_game(); pygame.quit(); sys.exit()
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                save_game(); return
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                mx,my = ev.pos
                for r, cls, cost, selected in buttons:
                    if r.collidepoint(mx,my):
                        play_sound("menu_click")
                        if selected:
                            return
                        if gems >= cost:
                            gems -= cost
                            player_class = cls()
                            save_game()
                            notify_once(f"{cls.name} Selected!", 800)
                            return
                        else:
                            notify_once("Not enough Gems!", 800)
                if back_rect.collidepoint(mx,my):
                    play_sound("menu_click")
                    save_game(); return

ADMIN_CODE = (pygame.K_6, pygame.K_5, pygame.K_4, pygame.K_3)

def admin_panel():
    """In-game admin panel: type 6543 during play."""
    global gems, player_speed, owned_abilities, corrosive_level, arrow_damage, max_hp, player_hp
    global knockback_level, pierce_level, player_level, player_exp, exp_required, wave
    global in_collection_phase, collection_start_ms, collection_duration_ms, enemies
    btn_w = 280
    btn_h = 40
    row = 44
    left_x = WIDTH//2 - 320
    right_x = WIDTH//2 + 40
    y_start = 120

    def mk_rects():
        r, rects, labels = 0, [], []
        def add(x, y, label):
            nonlocal r
            rects.append(pygame.Rect(x, y, btn_w, btn_h))
            labels.append(label)
            r += 1
        add(left_x, y_start + 0*row, "Full Heal")
        add(left_x, y_start + 1*row, f"Speed: {player_speed}")
        add(left_x, y_start + 2*row, "Give Corrosive (max)")
        add(left_x, y_start + 3*row, "Give ALL abilities")
        add(left_x, y_start + 4*row, "+5000 Gems")
        add(left_x, y_start + 5*row, "+100 Arrow Dmg")
        add(left_x, y_start + 6*row, "Set 500 Max HP + heal")
        add(right_x, y_start + 0*row, "Set Level 20")
        add(right_x, y_start + 1*row, "Skip to next wave")
        add(right_x, y_start + 2*row, "+5 Knockback")
        add(right_x, y_start + 3*row, "Max Piercing (3)")
        add(right_x, y_start + 4*row, "Back")
        return rects, labels

    rects, labels = mk_rects()
    while True:
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 200))
        screen.blit(overlay, (0, 0))
        draw_text_centered(FONT_LG, "Admin Panel", 45, WHITE)
        draw_text_centered(FONT_SM, f"HP: {player_hp}/{max_hp}  Dmg: {arrow_damage}  Gems: {gems}  Wave: {wave}", 88, LIGHT_GRAY)
        mx, my = pygame.mouse.get_pos()
        rects, labels = mk_rects()
        for i, (rect, label) in enumerate(zip(rects, labels)):
            c = (220, 240, 220) if rect.collidepoint(mx, my) else (180, 200, 180)
            pygame.draw.rect(screen, c, rect)
            pygame.draw.rect(screen, (40, 80, 40), rect, 2)
            w = FONT_MD.size(label)[0]
            screen.blit(FONT_MD.render(label, True, BLACK), (rect.x + (rect.w - w)//2, rect.y + 8))
        pygame.display.flip()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                return
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                for i, rect in enumerate(rects):
                    if not rect.collidepoint(ev.pos):
                        continue
                    if i == 0:
                        player_hp = max_hp
                    elif i == 1:
                        player_speed = 8 if player_speed == 5 else (12 if player_speed == 8 else 5)
                    elif i == 2:
                        owned_abilities["Corrosive"] = True
                        corrosive_level = 5
                    elif i == 3:
                        owned_abilities["Flame"] = owned_abilities["Poison"] = owned_abilities["Lightning"] = True
                        owned_abilities["Knockback"] = owned_abilities["Piercing"] = True
                        owned_abilities["Double Shot"] = owned_abilities["Corrosive"] = True
                        knockback_level = 5
                        pierce_level = 3
                        corrosive_level = 5
                    elif i == 4:
                        gems += 5000
                    elif i == 5:
                        arrow_damage += 100
                    elif i == 6:
                        max_hp = 500
                        player_hp = 500
                    elif i == 7:
                        player_level = 20
                        player_exp = 0
                        exp_required = 10 + 10 * (player_level - 1)
                    elif i == 8:
                        enemies.clear()
                        in_collection_phase = True
                        collection_start_ms = pygame.time.get_ticks() - collection_duration_ms - 100
                    elif i == 9:
                        knockback_level = min(5, knockback_level + 5)
                    elif i == 10:
                        pierce_level = 3
                    elif i == 11:
                        return
                    break
        clock.tick(FPS)

def settings_menu():
    global settings, screen, WIDTH, HEIGHT
    panel_w, panel_h = 380, 320
    panel = pygame.Rect(WIDTH//2 - panel_w//2, HEIGHT//2 - panel_h//2, panel_w, panel_h)
    slider_w, slider_h = 280, 22
    slider_x = panel.centerx - slider_w//2
    slider_y = panel.y + 78
    dragging = None
    back_rect = pygame.Rect(panel.centerx - 90, panel.bottom - 54, 180, 44)
    fullscreen_rect = pygame.Rect(panel.centerx - 100, panel.y + 168, 200, 44)
    music_rect = pygame.Rect(panel.centerx - 100, panel.y + 228, 200, 44)
    while True:
        screen.fill(bg_color)
        # Panel background and border first
        pygame.draw.rect(screen, (248, 248, 248), panel)
        pygame.draw.rect(screen, BLACK, panel, 3)
        # Title inside panel (so it's inside the box)
        title_surf = FONT_LG.render("Settings", True, BLACK)
        title_x = panel.x + (panel.w - title_surf.get_width()) // 2
        screen.blit(title_surf, (title_x, panel.y + 14))
        mx, my = pygame.mouse.get_pos()
        vol = settings.get("volume", 0.7)
        # Volume label (black)
        vol_label = FONT_MD.render("Volume", True, BLACK)
        screen.blit(vol_label, (slider_x, slider_y - 26))
        pygame.draw.rect(screen, DARK_GRAY, (slider_x, slider_y, slider_w, slider_h))
        pygame.draw.rect(screen, BLUE, (slider_x, slider_y, int(slider_w * vol), slider_h))
        knob_x = slider_x + max(0, int((slider_w - 14) * vol))
        pygame.draw.rect(screen, (240, 240, 240), (knob_x, slider_y - 3, 14, 28))
        pygame.draw.rect(screen, BLACK, (knob_x, slider_y - 3, 14, 28), 1)
        # Fullscreen (black label + toggle)
        fs_label = FONT_MD.render("Fullscreen", True, BLACK)
        screen.blit(fs_label, (fullscreen_rect.x, fullscreen_rect.y - 24))
        pygame.draw.rect(screen, LIGHT_GRAY if fullscreen_rect.collidepoint(mx, my) else (220, 220, 220), fullscreen_rect)
        pygame.draw.rect(screen, BLACK, fullscreen_rect, 2)
        fs_text = "On" if settings.get("fullscreen", True) else "Off"
        fst = FONT_MD.render(fs_text, True, BLACK)
        screen.blit(fst, (fullscreen_rect.x + (fullscreen_rect.w - fst.get_width()) // 2, fullscreen_rect.y + (fullscreen_rect.h - fst.get_height()) // 2 - 1))
        # Music (black label + toggle)
        music_label = FONT_MD.render("Music", True, BLACK)
        screen.blit(music_label, (music_rect.x, music_rect.y - 24))
        pygame.draw.rect(screen, LIGHT_GRAY if music_rect.collidepoint(mx, my) else (220, 220, 220), music_rect)
        pygame.draw.rect(screen, BLACK, music_rect, 2)
        mus_text = "On" if settings.get("music", True) else "Off"
        mst = FONT_MD.render(mus_text, True, BLACK)
        screen.blit(mst, (music_rect.x + (music_rect.w - mst.get_width()) // 2, music_rect.y + (music_rect.h - mst.get_height()) // 2 - 1))
        # Back button
        pygame.draw.rect(screen, LIGHT_GRAY if back_rect.collidepoint(mx, my) else (220, 220, 220), back_rect)
        pygame.draw.rect(screen, BLACK, back_rect, 2)
        bt = FONT_MD.render("Back", True, BLACK)
        screen.blit(bt, (back_rect.x + (back_rect.w - bt.get_width()) // 2, back_rect.y + (back_rect.h - bt.get_height()) // 2 - 1))
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
                if music_rect.collidepoint(mx, my):
                    play_sound("menu_click")
                    settings["music"] = not settings.get("music", True)
                    if settings["music"]:
                        start_music()
                    else:
                        stop_music()
                    save_settings()
                if slider_x <= mx <= slider_x + slider_w and slider_y - 4 <= my <= slider_y + 32:
                    dragging = True
            if ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
                dragging = None
            if ev.type == pygame.MOUSEMOTION and dragging:
                mx = ev.pos[0]
                v = max(0, min(1, (mx - slider_x) / slider_w))
                settings["volume"] = v
                save_settings()
                try:
                    if pygame.mixer.music.get_busy():
                        pygame.mixer.music.set_volume(0.25 * v)
                except Exception:
                    pass
        clock.tick(FPS)

def main_menu():
    global online_mode, current_save_slot
    refresh_all_slot_meta()
    start_music()

    while True:
        screen.fill(bg_color)
        draw_text_centered(FONT_LG, "Infinite Archer", HEIGHT//6)
        mx,my = pygame.mouse.get_pos()

        btn_w, btn_h = 360, 70
        new_rect = pygame.Rect(WIDTH//2 - btn_w//2, HEIGHT//2 - 140, btn_w, btn_h)
        resume_rect = pygame.Rect(WIDTH//2 - btn_w//2, HEIGHT//2 - 40, btn_w, btn_h)
        quit_rect = pygame.Rect(WIDTH//2 - btn_w//2, HEIGHT//2 + 60, btn_w, btn_h)
        class_rect = pygame.Rect(WIDTH//2 - btn_w//2, HEIGHT//2 + 160, btn_w, btn_h)
        online_rect = pygame.Rect(WIDTH//2 - btn_w//2, HEIGHT//2 + 260, btn_w, btn_h)

        for rect,label in [(new_rect,"Create New Game"), (resume_rect,"Resume Game"), (quit_rect,"Quit")]:
            color = LIGHT_GRAY if rect.collidepoint(mx,my) else (220,220,220)
            pygame.draw.rect(screen, color, rect)
            pygame.draw.rect(screen, BLACK, rect, 3)
            screen.blit(FONT_MD.render(label, True, BLACK), (rect.x+18, rect.y+18))

        pygame.draw.rect(screen, LIGHT_GRAY if class_rect.collidepoint(mx,my) else (220,220,220), class_rect)
        pygame.draw.rect(screen, BLACK, class_rect, 3)
        screen.blit(FONT_MD.render("Classes", True, BLACK), (class_rect.x+18, class_rect.y+18))

        pygame.draw.rect(screen, LIGHT_GRAY if online_rect.collidepoint(mx,my) else (220,220,220), online_rect)
        pygame.draw.rect(screen, BLACK, online_rect, 3)
        if not ONLINE_ENABLED:
            online_label = "Online (closed)"
        else:
            online_label = "Online" if websockets is not None else "Online (pip install websockets)"
        screen.blit(FONT_MD.render(online_label, True, BLACK), (online_rect.x+18, online_rect.y+18))

        meta_now = load_slot_meta(current_save_slot)
        g = int(meta_now.get("gems",0))
        gem_txt = FONT_MD.render(f"Gems: {g}  (Slot {current_save_slot})", True, BLUE)
        screen.blit(gem_txt, (WIDTH - gem_txt.get_width() - 22, 18))

        # Settings button: top-left; use FONT_SM so "Settings" fits inside the box
        settings_rect = pygame.Rect(16, 14, 100, 36)
        pygame.draw.rect(screen, LIGHT_GRAY if settings_rect.collidepoint(mx,my) else (220,220,220), settings_rect)
        pygame.draw.rect(screen, BLACK, settings_rect, 2)
        stxt = FONT_SM.render("Settings", True, BLACK)
        sx = settings_rect.x + (settings_rect.w - stxt.get_width()) // 2
        sy = settings_rect.y + (settings_rect.h - stxt.get_height()) // 2
        screen.blit(stxt, (sx, sy))

        slot_y = HEIGHT//2 + 360
        slot_w, slot_h = 180, 60
        slot1 = pygame.Rect(WIDTH//2 - slot_w - 200, slot_y, slot_w, slot_h)
        slot2 = pygame.Rect(WIDTH//2 - slot_w//2, slot_y, slot_w, slot_h)
        slot3 = pygame.Rect(WIDTH//2 + 200, slot_y, slot_w, slot_h)
        for s, r in [(1,slot1),(2,slot2),(3,slot3)]:
            meta = load_slot_meta(s)
            sel = (s==current_save_slot)
            fill = LIGHT_GRAY if r.collidepoint(mx,my) else (220,220,220)
            pygame.draw.rect(screen, fill, r)
            pygame.draw.rect(screen, BLUE if sel else BLACK, r, 4 if sel else 3)
            screen.blit(FONT_MD.render(f"Slot {s}: {int(meta.get('gems',0))}", True, BLACK), (r.x+14, r.y+14))

        pygame.display.flip()

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
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
                    online_mode = False
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
                        return "new"
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
        draw_text_centered(FONT_LG, "Game Over", HEIGHT//2 - 100)
        draw_text_centered(FONT_MD, f"Wave: {wave}  •  Score: {score}  •  Gems this run: {gems_this_run}", HEIGHT//2 - 40)
        draw_text_centered(FONT_MD, "Click or press Enter to return to menu", HEIGHT//2 + 30)
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
    global assassin_active_bounties, assassin_bounty_refresh_at_ms

    gems_this_run = 0
    player.center = (WIDTH//2, HEIGHT//2)

    spawn_preview_active = True
    spawn_preview_start_ms = pygame.time.get_ticks()
    running = True
    admin_code_buffer = []
    last_corrosive_damage_ms = 0

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

                # Admin code: 6, 5, 4, 3 in sequence (only when not in chat)
                if ev.key in ADMIN_CODE:
                    expected = ADMIN_CODE[len(admin_code_buffer)]
                    if ev.key == expected:
                        admin_code_buffer.append(ev.key)
                        if len(admin_code_buffer) == 4:
                            admin_code_buffer = []
                            admin_panel()
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
                if ev.key == pygame.K_1: weapon = "bow"
                if ev.key == pygame.K_2: weapon = "sword"
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
                if ev.key == pygame.K_b and isinstance(player_class, Assassin):
                    hit_list_menu()
                    continue
                if in_collection_phase and ev.key == pygame.K_SPACE:
                    for orb in pending_orbs[:]:
                        player_exp += orb["amount"]
                        gems += orb["amount"]
                        gems_this_run += orb["amount"]
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
                            try: pending_orbs.remove(orb)
                            except: pass
                            break
                    continue

                if weapon == "bow":
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
                        player_hp -= dmg
                        try: enemies.remove(enemy)
                        except: pass
                        if player_hp <= 0:
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
                player_hp -= dmg
                try: enemy_arrows.remove(ea)
                except: pass
                if player_hp <= 0:
                    play_sound("death")
                    game_over_screen(); reset_game(); return
            elif player.colliderect(ea.rect) and assassin_invis:
                try: enemy_arrows.remove(ea)
                except: pass

        # player arrows hit enemies
        for a in arrows[:]:
            for enemy in enemies[:]:
                if enemy.rect.colliderect(a.rect):
                    if online_mode and net is not None and hasattr(enemy, "_net_id"):
                        net.send_hit(enemy._net_id, arrow_damage)


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
                        handle_arrow_hit(enemy)
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
                        try: pending_orbs.remove(orb)
                        except: pass

                if pygame.time.get_ticks() - collection_start_ms >= collection_duration_ms:
                    for orb in pending_orbs[:]:
                        player_exp += orb["amount"]
                        gems += orb["amount"]
                        gems_this_run += orb["amount"]
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
                    enemies_per_wave = max(1, int(round(enemies_per_wave*1.1)))

        # ---------- DRAW ----------
        screen.fill(bg_color)

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
        if not assassin_invis and weapon == "bow":
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
            pygame.draw.line(screen, string_color, top, bottom, 2)
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
                pygame.draw.rect(screen, RED, rect, 2)
                pygame.draw.line(screen, RED, (rect.left+6, rect.top+6), (rect.right-6, rect.bottom-6), 2)
                pygame.draw.line(screen, RED, (rect.right-6, rect.top+6), (rect.left+6, rect.bottom-6), 2)

        # local arrows
        for a in arrows:
            a.draw(screen)

        # remote arrows
        for ra in remote_arrows:
            ra.draw(screen)

        # enemy arrows
        for ea in enemy_arrows:
            ea.draw(screen)

        # enemies
        for enemy in enemies:
            pygame.draw.rect(screen, enemy.color, enemy.rect)

        # orbs (small box when enemy dies — use small font for the number)
        for orb in pending_orbs:
            pygame.draw.rect(screen, BLUE, (int(orb["x"])-6, int(orb["y"])-6, 12, 12))
            txt = FONT_XS.render(str(orb.get("amount", 1)), True, BLACK)
            screen.blit(
                txt,
                (int(orb["x"]) - txt.get_width()//2,
                 int(orb["y"]) - txt.get_height()//2)
            )

        # HUD
        hud = FONT_SM.render(f"Score:{score} Wave:{wave} HP:{player_hp} Dmg:{arrow_damage} Gems:{gems} Class:{player_class.name}", True, BLACK)
        screen.blit(hud, (12,56))
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

        # Hit List button (Assassin only)
        hitlist_btn = pygame.Rect(WIDTH - 230, HEIGHT - 60, 100, 40)
        if isinstance(player_class, Assassin):
            pygame.draw.rect(screen, LIGHT_GRAY, hitlist_btn)
            pygame.draw.rect(screen, BLACK, hitlist_btn, 2)
            screen.blit(FONT_SM.render("Hit List", True, BLACK), (hitlist_btn.x + 14, hitlist_btn.y + 10))

        # Save button
        save_btn = pygame.Rect(WIDTH - 120, HEIGHT - 60, 100, 40)
        pygame.draw.rect(screen, LIGHT_GRAY, save_btn)
        pygame.draw.rect(screen, BLACK, save_btn, 2)
        screen.blit(FONT_SM.render("Save", True, BLACK), (save_btn.x+26, save_btn.y+10))

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