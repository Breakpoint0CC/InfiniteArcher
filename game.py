# =========================
# Infinite Archer — game.py
# FULL REPLACEMENT (PART 1/3)
# =========================
import os, sys, json, math, random, time, threading, asyncio

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
FULLSCREEN = True
DEFAULT_WIDTH, DEFAULT_HEIGHT = 1280, 800
SAVE_SLOTS = ["save1.json", "save2.json", "save3.json"]
current_save_slot = 1  # 1..3

# Online defaults
ONLINE_USERNAME = os.environ.get("IA_NAME", "Player")
online_mode = False
online_coop_enemies = True  # server-authoritative enemies
net = None

def get_save_path(slot=None):
    s = current_save_slot if slot is None else int(slot)
    s = max(1, min(3, s))
    return SAVE_SLOTS[s - 1]

# Display
if FULLSCREEN:
    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    WIDTH, HEIGHT = screen.get_size()
else:
    WIDTH, HEIGHT = DEFAULT_WIDTH, DEFAULT_HEIGHT
    screen = pygame.display.set_mode((WIDTH, HEIGHT))

pygame.display.set_caption("Infinite Archer")
clock = pygame.time.Clock()
FPS = 60

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
    "boss_hp": 2000,
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
                    floating_texts.append({"x":self.rect.centerx,"y":self.rect.top-18,"txt":"-5","color":ORANGE,"ttl":60,"vy":-0.6,"alpha":255})
                    self.burn_ms_left = max(0,self.burn_ms_left-1000)
                if self.poison_ms_left>0:
                    self.hp -= 5
                    small_dots.append({"x":self.rect.centerx,"y":self.rect.top-6,"color":PURPLE,"ttl":30,"vy":-0.2})
                    floating_texts.append({"x":self.rect.centerx,"y":self.rect.top-18,"txt":"-5","color":PURPLE,"ttl":60,"vy":-0.6,"alpha":255})
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
        self.rect.center = (x+dx*0.18, y+dy*0.18)
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
    color = DARK_GRAY

class FlameArcher(PlayerClass):
    name = "Flame Archer"
    color = ORANGE
    def on_arrow_hit(self, enemy, damage):
        enemy.burn_ms_left = 3000
        enemy.last_status_tick = pygame.time.get_ticks()

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

PLAYER_CLASS_ORDER = [NoClass, FlameArcher, Knight, MadScientist]
CLASS_COSTS = {
    "No Class": 0,
    "Flame Archer": 100,
    "Knight": 2000,
    "Mad Scientist": 10000
}
def class_rarity_label(cls_name):
    if cls_name == "Mad Scientist": return "Advanced"
    if cls_name == "Knight": return "Epic"
    if cls_name == "Flame Archer": return "Uncommon"
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

def draw_fx(surface):
    # dots first
    for d in small_dots:
        pygame.draw.circle(surface, d.get("color", BLACK),
                           (int(d.get("x", 0)), int(d.get("y", 0))), 3)

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
        return True
    except Exception as e:
        print("Load failed:", e)
        return False

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

    # online
    if online_mode and websockets is not None:
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
    boss.color = (100,10,60)
    boss.speed = 1.0
    boss.damage = DEFAULTS["archer_shot_damage"] * 3
    boss.summon_timer = pygame.time.get_ticks() + 5000
    enemies.append(boss)

def boss_try_summon(boss_enemy):
    now = pygame.time.get_ticks()
    if getattr(boss_enemy, "summon_timer", 0) and now >= boss_enemy.summon_timer:
        n = random.randint(2,4)
        for _ in range(n):
            rx = boss_enemy.rect.centerx + random.randint(-80,80)
            ry = boss_enemy.rect.centery + random.randint(-80,80)
            rect = pygame.Rect(rx, ry, 20, 20)
            enemies.append(Enemy(rect, "fast", is_mini=True))
        boss_enemy.summon_timer = now + 5000

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
    rarity_weights = [("Common",50),("Rare",30),("Epic",15),("Legendary",4),("Mythical",1)]
    tiers, weights = zip(*rarity_weights)
    chosen_rarity = random.choices(tiers, weights=weights, k=1)[0]

    pool = [a for a in all_options if ABILITY_RARITY[a] == chosen_rarity] or all_options[:]
    choices = random.sample(pool, min(2, len(pool)))

    buttons = []
    for i,c in enumerate(choices):
        rect = pygame.Rect(WIDTH//2 - 220 + i*280, HEIGHT//2 - 50, 260, 80)
        buttons.append((rect,c))

    while True:
        screen.fill(bg_color)
        draw_text_centered(FONT_LG, f"Choose an Upgrade ({chosen_rarity})", HEIGHT//2 - 160, RARITY_COLORS.get(chosen_rarity, BLUE))
        mx,my = pygame.mouse.get_pos()
        for rect,label in buttons:
            rarity = ABILITY_RARITY.get(label,"Common")
            pygame.draw.rect(screen, LIGHT_GRAY, rect)
            pygame.draw.rect(screen, RARITY_COLORS.get(rarity, BLACK), rect, 4)
            screen.blit(FONT_MD.render(label, True, BLACK), (rect.x+12, rect.y+18))
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

def draw_corrosive_field_visual(actual_radius):
    size = int(actual_radius*2)
    surf = pygame.Surface((size,size), pygame.SRCALPHA)
    surf.fill((*ACID_YELLOW, 80))
    screen.blit(surf, (player.centerx - actual_radius, player.centery - actual_radius))
    pygame.draw.rect(screen, ACID_YELLOW, (player.centerx - actual_radius, player.centery - actual_radius, size, size), 2)

def handle_arrow_hit(enemy, dmg=None):
    dmg = dmg if dmg is not None else arrow_damage
    enemy.hp -= dmg
    floating_texts.append({"x":enemy.rect.centerx,"y":enemy.rect.top-12,"txt":f"-{int(dmg)}","color":RED,"ttl":60,"vy":-0.6,"alpha":255})

    try:
        player_class.on_arrow_hit(enemy, dmg)
    except:
        pass

    now = pygame.time.get_ticks()
    if owned_abilities.get("Flame", False):
        enemy.burn_ms_left = 3000; enemy.last_status_tick = now - 1000

    if enemy.hp <= 0:
        spawn_orb(enemy.rect.centerx, enemy.rect.centery, amount=1)
        globals()["score"] += 1
        try: enemies.remove(enemy)
        except: pass

def handle_sword_attack(mx, my):
    global score
    kb = DEFAULTS["base_knockback"] * max(1, knockback_level)
    angle_to_mouse = math.atan2(my - player.centery, mx - player.centerx)

    for enemy in enemies[:]:
        ex = enemy.rect.centerx - player.centerx
        ey = enemy.rect.centery - player.centery
        dist = math.hypot(ex, ey)
        if dist <= DEFAULTS["sword_range"]:
            enemy_angle = math.atan2(ey, ex)
            diff = abs((enemy_angle - angle_to_mouse + math.pi) % (2*math.pi) - math.pi)
            if diff <= math.radians(DEFAULTS["sword_arc_half_deg"]) * 1.05:
                enemy.hp -= DEFAULTS["sword_damage"]
                floating_texts.append({"x":enemy.rect.centerx,"y":enemy.rect.top-12,"txt":f"-{DEFAULTS['sword_damage']}","color":RED,"ttl":60,"vy":-0.6,"alpha":255})
                if dist != 0:
                    enemy.rect.x += int(kb*(ex/dist))
                    enemy.rect.y += int(kb*(ey/dist))
                if enemy.hp <= 0:
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
def class_shop_menu():
    global gems, player_class
    while True:
        screen.fill(bg_color)
        draw_text_centered(FONT_LG, "Class Shop", 80)
        draw_text_centered(FONT_MD, f"Gems: {gems}", 150)

        buttons = []
        for i, cls in enumerate(PLAYER_CLASS_ORDER):
            y = 220 + i*90
            rect = pygame.Rect(WIDTH//2 - 240, y, 480, 70)
            cost = CLASS_COSTS[cls.name]
            selected = (player_class.name == cls.name)

            pygame.draw.rect(screen, LIGHT_GRAY, rect)
            pygame.draw.rect(screen, cls.color, rect, 4)

            rarity = class_rarity_label(cls.name)
            text = f"{cls.name} [{rarity}] — Cost: {cost}"
            if cls.name == "Mad Scientist": text += " (Curving AI Bow)"
            if cls.name == "Knight": text += " (Deflect + Armor)"
            if selected: text = f"{cls.name} [{rarity}] — Selected"
            screen.blit(FONT_MD.render(text, True, BLACK), (rect.x+16, rect.y+18))
            buttons.append((rect, cls, cost, selected))

        back_rect = pygame.Rect(WIDTH//2 - 120, HEIGHT - 90, 240, 60)
        pygame.draw.rect(screen, LIGHT_GRAY, back_rect)
        pygame.draw.rect(screen, BLACK, back_rect, 3)
        screen.blit(FONT_MD.render("Back", True, BLACK), (back_rect.x+70, back_rect.y+14))
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
                    save_game(); return

def main_menu():
    global online_mode, current_save_slot
    refresh_all_slot_meta()

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
        online_label = "Online" if websockets is not None else "Online (pip install websockets)"
        screen.blit(FONT_MD.render(online_label, True, BLACK), (online_rect.x+18, online_rect.y+18))

        meta_now = load_slot_meta(current_save_slot)
        g = int(meta_now.get("gems",0))
        gem_txt = FONT_MD.render(f"Gems: {g}  (Slot {current_save_slot})", True, BLUE)
        screen.blit(gem_txt, (WIDTH - gem_txt.get_width() - 22, 18))

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
                    online_mode = False
                    reset_game()
                    return "new"
                if resume_rect.collidepoint(ev.pos):
                    online_mode = False
                    reset_game()
                    if load_game():
                        notify_once("Loaded Save", 700)
                        return "resume"
                    notify_once("No save found — starting new", 900)
                    return "new"
                if class_rect.collidepoint(ev.pos):
                    reset_game()
                    load_game()  # load slot gems/class for shop if exists
                    class_shop_menu()
                if online_rect.collidepoint(ev.pos):
                    if websockets is None:
                        notify_once("Install websockets first", 1200)
                    else:
                        online_mode = True
                        reset_game()
                        return "new"
                if quit_rect.collidepoint(ev.pos):
                    pygame.quit(); sys.exit()

            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                pygame.quit(); sys.exit()

        clock.tick(FPS)

def game_over_screen():
    while True:
        screen.fill(bg_color)
        draw_text_centered(FONT_LG, "Game Over", HEIGHT//2 - 80)
        draw_text_centered(FONT_MD, f"Score: {score}", HEIGHT//2 - 20)
        draw_text_centered(FONT_MD, "Click or press Enter to return to menu", HEIGHT//2 + 40)
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
    global in_collection_phase, collection_start_ms, collection_duration_ms
    global spawn_preview_active, spawn_preview_start_ms, spawn_preview_ms
    global corrosive_level
    global net

    player.center = (WIDTH//2, HEIGHT//2)

    spawn_preview_active = True
    spawn_preview_start_ms = pygame.time.get_ticks()
    running = True

    while running:
        dt = clock.tick(FPS)
        now_ms = pygame.time.get_ticks()
        update_fx(dt)

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

                # normal controls
                if ev.key == pygame.K_ESCAPE:
                    save_game(); return
                if ev.key == pygame.K_1: weapon = "bow"
                if ev.key == pygame.K_2: weapon = "sword"
                if in_collection_phase and ev.key == pygame.K_SPACE:
                    for orb in pending_orbs[:]:
                        player_exp += orb["amount"]
                        gems += orb["amount"]
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

                if in_collection_phase:
                    for orb in pending_orbs[:]:
                        rect = pygame.Rect(orb["x"]-8, orb["y"]-8, 16, 16)
                        if rect.collidepoint(mx,my):
                            player_exp += orb["amount"]
                            gems += orb["amount"]
                            try: pending_orbs.remove(orb)
                            except: pass
                            break
                    continue

                if weapon == "bow":
                    shoot_bow(mx,my)
                else:
                    handle_sword_attack(mx,my)

        # movement (disabled while typing)
        keys = pygame.key.get_pressed()
        if not chat_open:
            if keys[pygame.K_w]: player.y -= DEFAULTS["player_speed"]
            if keys[pygame.K_s]: player.y += DEFAULTS["player_speed"]
            if keys[pygame.K_a]: player.x -= DEFAULTS["player_speed"]
            if keys[pygame.K_d]: player.x += DEFAULTS["player_speed"]
        player.clamp_ip(screen.get_rect())

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

        # enemies update (offline/local side only)
        if not online_mode:
            for enemy in enemies[:]:
                if getattr(enemy,"is_boss",False):
                    boss_try_summon(enemy)

                proj = enemy.try_shoot(now_ms)
                if proj:
                    enemy_arrows.append(EnemyArrow(proj["rect"], proj["vx"], proj["vy"], proj["damage"]))

                enemy.move_towards(player.centerx, player.centery)
                enemy.apply_status(now_ms)

                if enemy.hp <= 0:
                    score += 1
                    spawn_orb(enemy.rect.centerx, enemy.rect.centery, amount=1)
                    try: enemies.remove(enemy)
                    except: pass
                    continue

                if player.colliderect(enemy.rect):
                    dmg = enemy.damage
                    if isinstance(player_class, Knight):
                        dmg = int(math.ceil(dmg*0.90))
                    player_hp -= dmg
                    try: enemies.remove(enemy)
                    except: pass
                    if player_hp <= 0:
                        game_over_screen(); reset_game(); return

        # enemy arrows hit player
        for ea in enemy_arrows[:]:
            if player.colliderect(ea.rect):
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
                    game_over_screen(); reset_game(); return

        # player arrows hit enemies
        for a in arrows[:]:
            for enemy in enemies[:]:
                if enemy.rect.colliderect(a.rect):
                    if online_mode and net is not None and hasattr(enemy, "_net_id"):
                        net.send_hit(enemy._net_id, arrow_damage)
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
                        try: pending_orbs.remove(orb)
                        except: pass

                if pygame.time.get_ticks() - collection_start_ms >= collection_duration_ms:
                    for orb in pending_orbs[:]:
                        player_exp += orb["amount"]
                        gems += orb["amount"]
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
                        ability_choice_between_waves()

                    save_game()
                    spawn_preview_active = True
                    spawn_preview_start_ms = pygame.time.get_ticks()
                    player.center = (WIDTH//2, HEIGHT//2)
                    wave += 1
                    enemies_per_wave = max(1, int(round(enemies_per_wave*1.1)))

        # ---------- DRAW ----------
        screen.fill(bg_color)

        # local player
        pygame.draw.rect(screen, GREEN, player)

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

        # weapon visuals
        if weapon == "bow":
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
        else:
            mx,my = pygame.mouse.get_pos()
            ang = math.atan2(my - player.centery, mx - player.centerx)
            tipx = player.centerx + DEFAULTS["sword_range"]*math.cos(ang)
            tipy = player.centery + DEFAULTS["sword_range"]*math.sin(ang)
            pygame.draw.line(screen, (192,192,192), (player.centerx, player.centery), (tipx, tipy), 8)

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

        # orbs
        for orb in pending_orbs:
            pygame.draw.rect(screen, BLUE, (int(orb["x"])-6, int(orb["y"])-6, 12, 12))

        # HUD
        hud = FONT_SM.render(f"Score:{score} Wave:{wave} HP:{player_hp} Dmg:{arrow_damage} Gems:{gems} Class:{player_class.name}", True, BLACK)
        screen.blit(hud, (12,56))

        # online status
        if online_mode:
            url = os.environ.get("IA_SERVER", "ws://localhost:8765")
            sid = net.id if (net and net.id) else "?"
            st = net.last_status if net else "NO CLIENT"
            screen.blit(FONT_SM.render(f"MODE: ONLINE ({st}) ID:{sid}", True, BLUE), (12,84))
            screen.blit(FONT_SM.render(f"URL: {url}", True, (30,110,220)), (12,108))
            if net and st != "ONLINE" and net.last_error:
                err = net.last_error[:90] + ("…" if len(net.last_error)>90 else "")
                screen.blit(FONT_SM.render(f"NET ERR: {err}", True, (180,60,60)), (12,132))
        else:
            screen.blit(FONT_SM.render("MODE: OFFLINE", True, (90,90,90)), (12,84))

        # Save button
        save_btn = pygame.Rect(WIDTH - 120, HEIGHT - 60, 100, 40)
        pygame.draw.rect(screen, LIGHT_GRAY, save_btn)
        pygame.draw.rect(screen, BLACK, save_btn, 2)
        screen.blit(FONT_SM.render("Save", True, BLACK), (save_btn.x+26, save_btn.y+10))

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