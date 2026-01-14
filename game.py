# Infinite Archer — Full replacement game.py (Single file)
# Features:
# - Waves + boss every 10
# - Abilities (can repeat) with rarities; Damage upgrade is +5
# - Class Shop (spend gems): start with No Class
#   * Flame Archer (100 gems)
#   * Mad Scientist (10,000 gems) “Advanced” rarity (between Rare and Epic) + blue bow + curving AI arrow
#   * Knight: sword deflects enemy arrows + 10% damage reduction
# - In-game Save button
# - Optional Online (MVP): sync players positions/weapon only (enemies remain local)
#   Host: python game.py --server
#   Join: click Online (MVP) in menu. Server url: env IA_SERVER or ws://localhost:8765
#
# NOTE: Online requires: python -m pip install websockets

import pygame, random, math, sys, os, json, time
# Headless safe mode for server (no window needed)
# Must be set before importing/initializing pygame display on Linux servers.
if "--server" in sys.argv:
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import threading, asyncio
try:
    import websockets
except Exception:
    websockets = None

pygame.init()

# ---------- CONFIG ----------
FULLSCREEN = True
DEFAULT_WIDTH, DEFAULT_HEIGHT = 1280, 800
SAVE_SLOTS = ["save1.json", "save2.json", "save3.json"]
current_save_slot = 1  # 1..3

def get_save_path(slot=None):
    s = current_save_slot if slot is None else int(slot)
    s = max(1, min(3, s))
    return SAVE_SLOTS[s - 1]

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
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
RED = (220, 30, 30)
GREEN = (50, 200, 50)
YELLOW = (240, 240, 50)
DARK_RED = (150, 0, 0)
ORANGE = (255, 140, 0)
PURPLE = (160, 32, 240)
CYAN = (0, 200, 255)
LIGHT_GRAY = (230, 230, 230)
DARK_GRAY = (40, 40, 40)
BLUE = (40, 140, 255)
BROWN = (139, 69, 19)
ACID_YELLOW = (200, 230, 50)

FONT_LG = pygame.font.SysFont(None, 84)
FONT_MD = pygame.font.SysFont(None, 44)
FONT_SM = pygame.font.SysFont(None, 28)

RARITY_COLORS = {
    "Common": (0, 200, 0),
    "Rare": (0, 100, 255),
    "Advanced": (80, 170, 255),   # between Rare and Epic
    "Epic": (160, 32, 240),
    "Legendary": (255, 140, 0),
    "Mythical": (220, 20, 20)
}

# Abilities (can repeat; repeats re-apply effect like +damage again, +levels again, etc.)
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
    screen.blit(surf, (WIDTH // 2 - surf.get_width() // 2, y))

# ---------- ONLINE (MVP) NETWORKING ----------
# MVP: syncs player positions + weapon only. Enemies are local.
# Host: python game.py --server
# Join: Click Online (MVP) in menu
# Default: IA_SERVER env var or ws://localhost:8765

class NetClient:
    def __init__(self, url):
        self.url = url
        self.id = None
        self.players = {}
        self.enemies = {}
        self.connected = False
        self.last_error = ""
        self.last_status = "DISCONNECTED"
        self.last_hello_ms = 0
        self._loop = None
        self._ws = None
        self._lock = threading.Lock()

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._main())

    async def _main(self):
        if websockets is None:
            self.connected = False
            self.last_status = "NO_WEBSOCKETS"
            self.last_error = "websockets package not installed"
            return

        # Reconnect loop
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
                    # Wait for messages; server should send hello immediately
                    async for msg in ws:
                        try:
                            data = json.loads(msg)
                        except Exception:
                            continue
                        if data.get("type") == "hello":
                            self.id = data.get("id")
                            self.last_hello_ms = pygame.time.get_ticks()
                            self.last_status = "ONLINE"
                        elif data.get("type") == "state":
                            with self._lock:
                                self.players = data.get("players", {})
                        elif data.get("type") == "enemies":
                            with self._lock:
                                self.enemies = {str(e.get("id")): e for e in data.get("enemies", [])}
            except Exception as e:
                self.connected = False
                self._ws = None
                # keep id if you want; but show clearly we're not online
                if not self.id:
                    self.last_status = "DISCONNECTED"
                else:
                    self.last_status = "RECONNECTING"
                self.last_error = str(e)

            # backoff before retry
            await asyncio.sleep(1.0)

    def send_input(self, x, y, weapon):
        if not self.connected or self._ws is None or self._loop is None:
            return
        payload = {"type": "input", "x": float(x), "y": float(y), "weapon": weapon, "name": str(ONLINE_USERNAME)}
        try:
            asyncio.run_coroutine_threadsafe(self._ws.send(json.dumps(payload)), self._loop)
        except Exception as e:
            self.last_error = str(e)

    def send_hit(self, enemy_id, dmg):
        if not self.connected or self._ws is None or self._loop is None:
            return
        payload = {"type": "hit", "enemy_id": str(enemy_id), "dmg": float(dmg)}
        try:
            asyncio.run_coroutine_threadsafe(self._ws.send(json.dumps(payload)), self._loop)
        except Exception as e:
            self.last_error = str(e)

    def get_players(self):
        with self._lock:
            return dict(self.players)

    def get_enemies(self):
        with self._lock:
            return dict(self.enemies)

async def run_server(host="0.0.0.0", port=8765, tick_hz=20):
    if websockets is None:
        print("websockets not installed. Run: python -m pip install websockets")
        return

    import uuid, time as _time
    players = {}
    enemies = {}
    wave = 1
    enemies_per_wave = 5
    next_enemy_id = 1
    connected = set()

    def spawn_wave():
        nonlocal enemies, next_enemy_id, wave, enemies_per_wave
        enemies = {}
        n = int(enemies_per_wave)
        for _ in range(n):
            eid = str(next_enemy_id); next_enemy_id += 1
            etype = random.choices(["normal", "fast", "tank", "archer"], weights=[50, 30, 10, 10])[0]
            # spawn around edges
            side = random.choice(["top", "bottom", "left", "right"])
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

            enemies[eid] = {"id": eid, "x": float(x), "y": float(y), "w": 30, "h": 30, "hp": float(hp), "etype": etype, "spd": float(spd)}

    spawn_wave()

    async def handler(ws):
        pid = uuid.uuid4().hex[:8]
        players[pid] = {"x": 300.0, "y": 300.0, "weapon": "bow", "name": "Player", "last": _time.time()}
        connected.add(ws)
        await ws.send(json.dumps({"type": "hello", "id": pid}))
        try:
            async for msg in ws:
                try:
                    data = json.loads(msg)
                except Exception:
                    continue
                if data.get("type") == "input":
                    p = players.get(pid)
                    if not p:
                        continue
                    p["last"] = _time.time()
                    if "x" in data and "y" in data:
                        p["x"] = float(data["x"])
                        p["y"] = float(data["y"])
                    if "weapon" in data:
                        p["weapon"] = data["weapon"]
                    if "name" in data and str(data["name"]).strip():
                        p["name"] = str(data["name"])[:16]
                elif data.get("type") == "hit":
                    eid = str(data.get("enemy_id"))
                    dmg = float(data.get("dmg", 0))
                    if eid in enemies and dmg > 0:
                        enemies[eid]["hp"] -= dmg
                        if enemies[eid]["hp"] <= 0:
                            enemies.pop(eid, None)
        finally:
            players.pop(pid, None)
            try:
                connected.discard(ws)
            except Exception:
                pass

    async def tick_loop():
        while True:
            # Simulate enemies toward closest player (server-authoritative enemies)
            if players:
                # pick a representative target per enemy: closest player
                plist = list(players.values())
                for e in list(enemies.values()):
                    ex = e["x"] + e["w"] / 2
                    ey = e["y"] + e["h"] / 2
                    best = None
                    bestd = 1e18
                    for p in plist:
                        dx = float(p["x"]) - ex
                        dy = float(p["y"]) - ey
                        d = dx * dx + dy * dy
                        if d < bestd:
                            bestd = d
                            best = p
                    if best is not None:
                        dx = float(best["x"]) - ex
                        dy = float(best["y"]) - ey
                        dist = math.hypot(dx, dy) or 1.0
                        spd = float(e.get("spd", 2.0))
                        e["x"] += (dx / dist) * spd
                        e["y"] += (dy / dist) * spd

            # If all enemies are dead, next wave
            if not enemies:
                wave += 1
                enemies_per_wave = max(1, int(round(enemies_per_wave * 1.10)))
                spawn_wave()

            if connected:
                try:
                    websockets.broadcast(connected, json.dumps({"type": "state", "players": players}))
                    websockets.broadcast(connected, json.dumps({"type": "enemies", "enemies": list(enemies.values())}))
                except Exception:
                    pass

            await asyncio.sleep(1.0 / float(tick_hz))

    async with websockets.serve(handler, host, port, ping_interval=20, ping_timeout=20, max_size=2_000_000):
        print(f"Infinite Archer server running on ws://{host}:{port}")
        await tick_loop()

# ---------- GAME CLASSES ----------
class Enemy:
    def __init__(self, rect, etype="normal", is_mini=False, hp_override=None):
        self.rect = rect
        self.etype = etype
        self.is_mini = is_mini
        self.is_boss = False

        if etype == "normal": base_hp, base_speed, base_damage, color = 20, 2, 10, RED
        elif etype == "fast": base_hp, base_speed, base_damage, color = 15, 3, 8, YELLOW
        elif etype == "tank": base_hp, base_speed, base_damage, color = 40, 1, 15, DARK_RED
        elif etype == "archer": base_hp, base_speed, base_damage, color = 18, 2, 8, CYAN
        else: base_hp, base_speed, base_damage, color = 20, 2, 10, RED

        if is_mini:
            self.color = YELLOW
            self.speed = base_speed * 2
            self.hp = hp_override if hp_override is not None else base_hp
            self.damage = base_damage
        else:
            self.color = color
            self.hp = hp_override if hp_override is not None else base_hp * 2
            self.speed = base_speed
            self.damage = base_damage

        self.burn_ms_left = 0
        self.poison_ms_left = 0
        self.last_status_tick = 0
        self.shoot_timer = 0
        self.shoot_interval = 1800 + random.randint(-400, 400)
        self.summon_timer = 0

    def move_towards(self, tx, ty):
        dx, dy = tx - self.rect.centerx, ty - self.rect.centery
        dist = math.hypot(dx, dy)
        if dist == 0:
            return
        spd = self.speed * (0.5 if self.poison_ms_left > 0 else 1.0)
        self.rect.x += round(spd * dx / dist)
        self.rect.y += round(spd * dy / dist)

    def try_shoot(self, now_ms):
        if self.etype != "archer":
            return None
        if now_ms - self.shoot_timer >= self.shoot_interval:
            self.shoot_timer = now_ms
            dx, dy = player.centerx - self.rect.centerx, player.centery - self.rect.centery
            d = math.hypot(dx, dy) or 1
            vx, vy = 8 * dx / d, 8 * dy / d
            proj = pygame.Rect(self.rect.centerx - 4, self.rect.centery - 4, 8, 8)
            return {"rect": proj, "vx": vx, "vy": vy, "damage": DEFAULTS["archer_shot_damage"]}
        return None

    def apply_status(self, now_ms):
        if self.burn_ms_left > 0 or self.poison_ms_left > 0:
            if now_ms - self.last_status_tick >= 1000:
                self.last_status_tick = now_ms
                if self.burn_ms_left > 0:
                    self.hp -= 5
                    small_dots.append({"x": self.rect.centerx, "y": self.rect.top - 6, "color": ORANGE, "ttl": 30, "vy": -0.2})
                    floating_texts.append({"x": self.rect.centerx, "y": self.rect.top - 18, "txt": "-5", "color": ORANGE, "ttl": 60, "vy": -0.6, "alpha": 255})
                    self.burn_ms_left = max(0, self.burn_ms_left - 1000)
                if self.poison_ms_left > 0:
                    self.hp -= 5
                    small_dots.append({"x": self.rect.centerx, "y": self.rect.top - 6, "color": PURPLE, "ttl": 30, "vy": -0.2})
                    floating_texts.append({"x": self.rect.centerx, "y": self.rect.top - 18, "txt": "-5", "color": PURPLE, "ttl": 60, "vy": -0.6, "alpha": 255})
                    self.poison_ms_left = max(0, self.poison_ms_left - 1000)
        else:
            self.last_status_tick = now_ms

class Arrow:
    # Optional curving/target for Mad Scientist
    def __init__(self, x, y, tx, ty, pierce=0, target=None, turn_rate=0.18):
        self.rect = pygame.Rect(0, 0, 30, 6)
        dx, dy = tx - x, ty - y
        d = math.hypot(dx, dy) or 1.0
        self.vx = DEFAULTS["arrow_speed"] * dx / d
        self.vy = DEFAULTS["arrow_speed"] * dy / d
        self.angle = math.atan2(self.vy, self.vx)
        self.rect.center = (x + dx * 0.18, y + dy * 0.18)
        self.pierce_remaining = pierce
        self.target = target
        self.turn_rate = float(turn_rate)

    def update(self):
        if self.target is not None:
            try:
                if getattr(self.target, "hp", 1) <= 0 or self.target not in enemies:
                    self.target = None
            except Exception:
                self.target = None

        if self.target is not None:
            try:
                tx, ty = self.target.rect.centerx, self.target.rect.centery
            except Exception:
                self.target = None

            if self.target is not None:
                dx = tx - self.rect.centerx
                dy = ty - self.rect.centery
                d = math.hypot(dx, dy) or 1.0
                desired_vx = DEFAULTS["arrow_speed"] * dx / d
                desired_vy = DEFAULTS["arrow_speed"] * dy / d

                tr = self.turn_rate
                self.vx = (1.0 - tr) * self.vx + tr * desired_vx
                self.vy = (1.0 - tr) * self.vy + tr * desired_vy

                sp = math.hypot(self.vx, self.vy) or 1.0
                scale = DEFAULTS["arrow_speed"] / sp
                self.vx *= scale
                self.vy *= scale

        self.rect.x += int(self.vx)
        self.rect.y += int(self.vy)
        self.angle = math.atan2(self.vy, self.vx)
        return screen.get_rect().colliderect(self.rect)

    def draw(self, surf):
        arr_surf = pygame.Surface((30, 6), pygame.SRCALPHA)
        arr_surf.fill(BLACK)
        rot = pygame.transform.rotate(arr_surf, -math.degrees(self.angle))
        surf.blit(rot, (self.rect.x, self.rect.y))

class EnemyArrow:
    def __init__(self, rect, vx, vy, dmg):
        self.rect = rect
        self.vx = vx
        self.vy = vy
        self.damage = dmg

    def update(self):
        self.rect.x += int(self.vx)
        self.rect.y += int(self.vy)
        return screen.get_rect().colliderect(self.rect)

    def draw(self, surf):
        pygame.draw.rect(surf, DARK_RED, self.rect)

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

class PoisonArcher(PlayerClass):
    name = "Poison Archer"
    color = PURPLE
    def on_arrow_hit(self, enemy, damage):
        enemy.poison_ms_left = 4000
        enemy.last_status_tick = pygame.time.get_ticks()

class LightningArcher(PlayerClass):
    name = "Lightning Archer"
    color = YELLOW
    def on_arrow_hit(self, enemy, damage):
        lightning_lines.append({"x1": enemy.rect.centerx, "y1": enemy.rect.centery, "x2": enemy.rect.centerx, "y2": enemy.rect.centery, "ttl": 250})
        apply_lightning_chain(enemy, damage)

class CorrosiveChampion(PlayerClass):
    name = "Corrosive Champion"
    color = ACID_YELLOW
    def on_update(self, now_ms):
        # light passive tick
        if now_ms % 1000 > 40:
            return
        radius = 260
        field = pygame.Rect(player.centerx - radius, player.centery - radius, radius * 2, radius * 2)
        for e in enemies[:]:
            if field.colliderect(e.rect):
                e.hp -= 15
                floating_texts.append({"x": e.rect.centerx, "y": e.rect.top - 12, "txt": "-15", "color": ACID_YELLOW, "ttl": 60, "vy": -0.6, "alpha": 255})

class MadScientist(PlayerClass):
    name = "Mad Scientist"
    color = (120, 255, 120)
    rarity_tier = "Advanced"  # between Rare and Epic

    def on_arrow_fire(self, mx, my):
        # Curving AI bow: choose closest enemy, steer strongly
        if not enemies:
            return False
        closest = min(enemies, key=lambda e: math.hypot(e.rect.centerx - player.centerx, e.rect.centery - player.centery))
        # more accurate curve
        arrows.append(Arrow(player.centerx, player.centery, mx, my, pierce=pierce_level, target=closest, turn_rate=0.22))
        return True

class Knight(PlayerClass):
    name = "Knight"
    color = (180, 180, 180)

    def try_deflect(self, enemy_arrow):
        # only deflect when using sword
        if globals().get("weapon", "bow") != "sword":
            return False
        try:
            enemy_arrows.remove(enemy_arrow)
        except Exception:
            pass
        if enemies:
            closest = min(enemies, key=lambda e: math.hypot(e.rect.centerx - player.centerx, e.rect.centery - player.centery))
            arrows.append(Arrow(player.centerx, player.centery, closest.rect.centerx, closest.rect.centery, pierce=pierce_level))
        floating_texts.append({"x": player.centerx, "y": player.centery - 34, "txt": "DEFLECT!", "color": (120, 120, 120), "ttl": 40, "vy": -0.7, "alpha": 255})
        return True

PLAYER_CLASS_ORDER = [NoClass, FlameArcher, PoisonArcher, LightningArcher, CorrosiveChampion, Knight, MadScientist]

CLASS_COSTS = {
    "No Class": 0,
    "Flame Archer": 100,          # requested
    "Poison Archer": 250,
    "Lightning Archer": 500,
    "Corrosive Champion": 1000,
    "Knight": 2000,
    "Mad Scientist": 10000        # requested
}

def class_rarity_label(cls_name):
    if cls_name == "Mad Scientist":
        return "Advanced"  # between Rare and Epic
    if cls_name in ("Corrosive Champion", "Knight"):
        return "Epic"
    if cls_name in ("Poison Archer", "Lightning Archer"):
        return "Rare"
    if cls_name in ("Flame Archer",):
        return "Uncommon"
    return "Normal"

# ---------- Globals containers ----------
small_dots = []
floating_texts = []
lightning_lines = []
arrows = []
enemy_arrows = []
enemies = []
pending_orbs = []

# State flags
admin_unlocked = False
admin_available_next_game = False
bg_color = WHITE

ONLINE_USERNAME = os.environ.get("IA_NAME", "Player")
# Online (MVP) state
online_mode = False
net = None
net_players_cache = {}
online_coop_enemies = True  # when online, use server-authoritative enemies
net_enemies_cache = {}

# Save-slot meta shown in menus (instant gems display)
slot_meta_cache = {
    1: {"gems": 0, "player_class": "No Class"},
    2: {"gems": 0, "player_class": "No Class"},
    3: {"gems": 0, "player_class": "No Class"},
}

def load_slot_meta(slot):
    """Lightweight read for menu display (gems/class) without loading full state."""
    path = get_save_path(slot)
    if not os.path.exists(path):
        slot_meta_cache[int(slot)] = {"gems": 0, "player_class": "No Class"}
        return slot_meta_cache[int(slot)]
    try:
        with open(path, "r") as f:
            data = json.load(f)
        meta = {
            "gems": int(data.get("gems", 0)),
            "player_class": str(data.get("player_class", "No Class")),
        }
        slot_meta_cache[int(slot)] = meta
        return meta
    except Exception:
        slot_meta_cache[int(slot)] = {"gems": 0, "player_class": "No Class"}
        return slot_meta_cache[int(slot)]


def refresh_all_slot_meta():
    for s in (1, 2, 3):
        load_slot_meta(s)

# ---------- Save / Load ----------
def save_game():
    try:
        data = {
            "player": [player.x, player.y, player.width, player.height],
            "player_hp": player_hp if 'player_hp' in globals() else DEFAULTS["max_hp"],
            "arrow_damage": globals().get("arrow_damage", DEFAULTS["arrow_damage"]),
            "player_exp": globals().get("player_exp", 0),
            "player_level": globals().get("player_level", 1),
            "exp_required": globals().get("exp_required", 10),
            "wave": globals().get("wave", 1),
            "score": globals().get("score", 0),
            "gems": globals().get("gems", 0),
            "pierce_level": globals().get("pierce_level", 0),
            "knockback_level": globals().get("knockback_level", 1),
            "owned_abilities": globals().get("owned_abilities", {}),
            "corrosive_level": globals().get("corrosive_level", 0),
            "enemies_per_wave": globals().get("enemies_per_wave", DEFAULTS["enemies_per_wave_start"]),
            "player_class": player_class.name if 'player_class' in globals() else "No Class",
        }
        with open(get_save_path(), "w") as f:
            json.dump(data, f)
            load_slot_meta(current_save_slot)
    except Exception as e:
        print("Save failed:", e)

def load_game():
    global player, player_hp, arrow_damage, player_exp, player_level, exp_required
    global wave, score, gems, pierce_level, knockback_level, owned_abilities, corrosive_level
    global enemies_per_wave, player_class

    if not os.path.exists(get_save_path()):
        return False
    try:
        with open(get_save_path(), "r") as f:
            data = json.load(f)

        px, py, w, h = data.get("player", [WIDTH // 2, HEIGHT // 2, 40, 40])
        player.x, player.y, player.width, player.height = px, py, w, h

        player_hp = data.get("player_hp", DEFAULTS["max_hp"])
        arrow_damage = data.get("arrow_damage", DEFAULTS["arrow_damage"])
        player_exp = data.get("player_exp", 0)
        player_level = data.get("player_level", 1)
        exp_required = data.get("exp_required", 10)

        wave = data.get("wave", 1)
        score = data.get("score", 0)
        gems = data.get("gems", 0)

        pierce_level = data.get("pierce_level", 0)
        knockback_level = data.get("knockback_level", 1)
        owned_abilities = data.get("owned_abilities", {})
        corrosive_level = data.get("corrosive_level", 0)
        enemies_per_wave = data.get("enemies_per_wave", DEFAULTS["enemies_per_wave_start"])

        class_name = data.get("player_class", "No Class")
        found = False
        for cls in PLAYER_CLASS_ORDER:
            if cls.name == class_name:
                player_class = cls()
                found = True
                break
        if not found:
            player_class = NoClass()

        enemies.clear(); arrows.clear(); enemy_arrows.clear(); pending_orbs.clear()
        floating_texts.clear(); small_dots.clear(); lightning_lines.clear()
        return True
    except Exception as e:
        print("Load failed:", e)
        return False

# ---------- Reset / init ----------
def reset_game():
    global player, player_hp, player_speed, max_hp
    global arrow_damage, sword_damage, sword_arc_half
    global knockback_level, owned_abilities, pierce_level, pierce_max_level
    global wave, enemies_per_wave, score
    global weapon, music_enabled
    global admin_unlocked, admin_available_next_game
    global player_level, player_exp, exp_required, gems
    global in_collection_phase, collection_start_ms, collection_duration_ms
    global spawn_pattern_positions, spawn_preview_ms, spawn_preview_active, spawn_preview_start_ms
    global corrosive_level
    global player_class
    global online_mode, net, net_players_cache

    size = DEFAULTS["player_size"]
    player = pygame.Rect(WIDTH // 2 - size // 2, HEIGHT // 2 - size // 2, size, size)
    player_speed = DEFAULTS["player_speed"]
    max_hp = DEFAULTS["max_hp"]
    player_hp = max_hp

    arrow_damage = DEFAULTS["arrow_damage"]
    sword_damage = DEFAULTS["sword_damage"]
    sword_arc_half = math.radians(DEFAULTS["sword_arc_half_deg"])

    # IMPORTANT: start at 1 for knockback (so base works), 0 for pierce
    knockback_level = 1
    pierce_level = 0
    pierce_max_level = 3

    owned_abilities = {
        "Flame": False, "Poison": False, "Lightning": False,
        "Knockback": False, "Piercing": False, "Double Shot": False, "Corrosive": False
    }

    enemies.clear(); arrows.clear(); enemy_arrows.clear()
    floating_texts.clear(); lightning_lines.clear(); small_dots.clear()
    pending_orbs.clear()

    wave = 1
    enemies_per_wave = DEFAULTS["enemies_per_wave_start"]
    score = 0

    weapon = "bow"
    music_enabled = False

    admin_unlocked = False
    admin_available_next_game = False

    player_level = 1
    player_exp = 0
    exp_required = 10 + 10 * (player_level - 1)

    # Keep gems per save-slot (menu shows instantly; new game doesn't wipe gems)
    meta = load_slot_meta(current_save_slot)
    gems = int(meta.get("gems", 0))

    in_collection_phase = False
    collection_start_ms = None
    collection_duration_ms = 5000

    spawn_pattern_positions = generate_spawn_pattern(120)
    spawn_preview_ms = 5000
    spawn_preview_active = False
    spawn_preview_start_ms = None

    corrosive_level = 0
    player_class = NoClass()

    # Online client (MVP)
    net_players_cache = {}
    globals()["net_enemies_cache"] = {}
    if online_mode and websockets is not None:
        url = os.environ.get("IA_SERVER", "ws://localhost:8765")
        net = NetClient(url)
        net.start()
    else:
        net = None

# ---------- Spawning ----------
def spawn_wave_at_positions(positions):
    enemies.clear()
    for pos in positions:
        etype = random.choices(["normal", "fast", "tank", "archer"], weights=[50, 30, 10, 10])[0]
        rect = pygame.Rect(pos[0] - 15, pos[1] - 15, 30, 30)
        enemies.append(Enemy(rect, etype))

def spawn_wave(count):
    spawn_wave_at_positions(spawn_pattern_positions[:int(count)])

def spawn_boss():
    rect = pygame.Rect(WIDTH // 2 - 60, -140, 120, 120)
    boss = Enemy(rect, "tank", is_mini=False, hp_override=DEFAULTS["boss_hp"])
    boss.is_boss = True
    boss.color = (100, 10, 60)
    boss.speed = 1.0
    boss.damage = DEFAULTS["archer_shot_damage"] * 3
    boss.summon_timer = pygame.time.get_ticks() + 5000
    enemies.append(boss)

def boss_try_summon(boss_enemy):
    now = pygame.time.get_ticks()
    if getattr(boss_enemy, "summon_timer", 0) and now >= boss_enemy.summon_timer:
        n = random.randint(2, 4)
        for _ in range(n):
            rx = boss_enemy.rect.centerx + random.randint(-80, 80)
            ry = boss_enemy.rect.centery + random.randint(-80, 80)
            rect = pygame.Rect(rx, ry, 20, 20)
            enemies.append(Enemy(rect, "fast", is_mini=True))
        boss_enemy.summon_timer = now + 5000

# ---------- FX / Orbs / UI ----------
def apply_lightning_chain(origin_enemy, base_damage):
    nearby = 0
    ox, oy = origin_enemy.rect.centerx, origin_enemy.rect.centery
    others = [e for e in enemies if e is not origin_enemy and e.hp > 0]
    others.sort(key=lambda e: math.hypot(e.rect.centerx - ox, e.rect.centery - oy))
    for e in others:
        if nearby >= 2:
            break
        d = math.hypot(e.rect.centerx - ox, e.rect.centery - oy)
        if d <= 100:
            dmg = base_damage // 2
            e.hp -= dmg
            floating_texts.append({"x": e.rect.centerx, "y": e.rect.top - 12, "txt": f"-{dmg}", "color": YELLOW, "ttl": 60, "vy": -0.6, "alpha": 255})
            lightning_lines.append({"x1": ox, "y1": oy, "x2": e.rect.centerx, "y2": e.rect.centery, "ttl": 350})
            nearby += 1

def spawn_orb(x, y, amount=1):
    for _ in range(int(amount)):
        pending_orbs.append({"x": float(x + random.randint(-10, 10)), "y": float(y + random.randint(-10, 10)), "amount": 1})

def draw_hp_bar(hp):
    w, h = 300, 28
    x, y = 12, 12
    pygame.draw.rect(screen, DARK_GRAY, (x, y, w, h))
    frac = (hp / max_hp) if max_hp > 0 else 0
    pygame.draw.rect(screen, GREEN, (x, y, int(w * max(0, min(1, frac))), h))
    pygame.draw.rect(screen, BLACK, (x, y, w, h), 2)

def draw_exp_bar():
    margin = 12
    w = WIDTH - margin * 2
    h = 18
    x = margin
    y = HEIGHT - h - 12
    pygame.draw.rect(screen, DARK_GRAY, (x, y, w, h))
    frac = min(1.0, player_exp / exp_required) if exp_required > 0 else 0.0
    pygame.draw.rect(screen, BLUE, (x, y, int(w * frac), h))
    pygame.draw.rect(screen, BLACK, (x, y, w, h), 2)
    lvl_txt = FONT_SM.render(f"Level: {player_level}  EXP: {player_exp}/{exp_required}", True, BLACK)
    screen.blit(lvl_txt, (x + 6, y - 24))

def notify_once(msg, duration=900):
    start = pygame.time.get_ticks()
    while pygame.time.get_ticks() - start < duration:
        screen.fill(bg_color)
        draw_text_centered(FONT_LG, msg, HEIGHT // 2)
        pygame.display.flip()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                save_game()
                pygame.quit()
                sys.exit()
        clock.tick(FPS)

# ---------- Admin overlay ----------
def draw_admin_button():
    rect = pygame.Rect(WIDTH - 170, 12, 158, 36)
    pygame.draw.rect(screen, LIGHT_GRAY, rect)
    pygame.draw.rect(screen, BLACK, rect, 2)
    screen.blit(FONT_SM.render("Admin Panel", True, BLACK), (rect.x + 12, rect.y + 6))
    return rect

def admin_panel_overlay():
    global player_hp, max_hp, arrow_damage, score, player_speed, owned_abilities, pierce_level, knockback_level, player_exp, gems
    temp_max_hp = max_hp
    temp_damage = arrow_damage
    temp_score = score
    temp_speed = player_speed
    temp_pierce = pierce_level
    temp_kb = knockback_level
    temp_owned = owned_abilities.copy()

    def draw_overlay():
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill((255, 255, 255, 230))
        screen.blit(overlay, (0, 0))
        panel = pygame.Rect(WIDTH // 2 - 360, HEIGHT // 2 - 260, 720, 520)
        pygame.draw.rect(screen, WHITE, panel)
        pygame.draw.rect(screen, BLACK, panel, 2)
        screen.blit(FONT_LG.render("Admin Panel", True, BLACK), (panel.x + 20, panel.y + 18))

        labels = [
            ("Player Max HP", str(temp_max_hp)),
            ("Damage", str(temp_damage)),
            ("Score", str(temp_score)),
            ("Speed", str(temp_speed)),
            ("Pierce Lv", str(temp_pierce)),
            ("Knockback Lv", str(temp_kb)),
        ]
        for i, (lab, val) in enumerate(labels):
            y = panel.y + 110 + i * 56
            screen.blit(FONT_MD.render(lab, True, BLACK), (panel.x + 24, y))
            val_rect = pygame.Rect(panel.x + 220, y, 140, 40)
            pygame.draw.rect(screen, LIGHT_GRAY, val_rect)
            pygame.draw.rect(screen, BLACK, val_rect, 2)
            screen.blit(FONT_MD.render(val, True, BLACK), (val_rect.x + 12, val_rect.y + 6))
            minus = pygame.Rect(val_rect.right + 12, y, 40, 40)
            plus = pygame.Rect(val_rect.right + 60, y, 40, 40)
            pygame.draw.rect(screen, LIGHT_GRAY, minus); pygame.draw.rect(screen, BLACK, minus, 2)
            pygame.draw.rect(screen, LIGHT_GRAY, plus); pygame.draw.rect(screen, BLACK, plus, 2)
            screen.blit(FONT_MD.render("-", True, BLACK), (minus.x + 12, minus.y + 4))
            screen.blit(FONT_MD.render("+", True, BLACK), (plus.x + 10, plus.y + 4))

        ab_start_y = panel.y + 420
        ab_x = panel.x + 24
        abilities_order = ["Flame", "Poison", "Lightning", "Knockback", "Piercing", "Double Shot", "Corrosive"]
        for idx, k in enumerate(abilities_order):
            y = ab_start_y + idx * 36
            cb = pygame.Rect(ab_x, y, 24, 24)
            pygame.draw.rect(screen, LIGHT_GRAY, cb)
            pygame.draw.rect(screen, BLACK, cb, 2)
            if temp_owned.get(k, False):
                pygame.draw.line(screen, BLACK, (cb.x + 4, cb.y + 12), (cb.x + 10, cb.y + 18), 3)
                pygame.draw.line(screen, BLACK, (cb.x + 10, cb.y + 18), (cb.x + 20, cb.y + 6), 3)
            screen.blit(FONT_MD.render(k, True, BLACK), (cb.right + 12, y - 2))

        apply_rect = pygame.Rect(panel.right - 316, panel.bottom - 72, 88, 40)
        exp_rect = pygame.Rect(panel.right - 220, panel.bottom - 72, 88, 40)
        close_rect = pygame.Rect(panel.right - 112, panel.bottom - 72, 88, 40)
        pygame.draw.rect(screen, LIGHT_GRAY, apply_rect); pygame.draw.rect(screen, BLACK, apply_rect, 2)
        pygame.draw.rect(screen, LIGHT_GRAY, exp_rect); pygame.draw.rect(screen, BLACK, exp_rect, 2)
        pygame.draw.rect(screen, LIGHT_GRAY, close_rect); pygame.draw.rect(screen, BLACK, close_rect, 2)
        screen.blit(FONT_MD.render("Apply", True, BLACK), (apply_rect.x + 12, apply_rect.y + 6))
        screen.blit(FONT_MD.render("+EXP", True, BLACK), (exp_rect.x + 12, exp_rect.y + 6))
        screen.blit(FONT_MD.render("Close", True, BLACK), (close_rect.x + 12, close_rect.y + 6))

        return panel, apply_rect, exp_rect, close_rect

    while True:
        panel, apply_rect, exp_rect, close_rect = draw_overlay()
        pygame.display.flip()

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                save_game(); pygame.quit(); sys.exit()
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                mx, my = ev.pos

                # +/- rows
                for i, key in enumerate(["maxhp", "damage", "score", "speed", "pierce", "kb"]):
                    y = panel.y + 110 + i * 56
                    val_rect = pygame.Rect(panel.x + 220, y, 140, 40)
                    minus = pygame.Rect(val_rect.right + 12, y, 40, 40)
                    plus = pygame.Rect(val_rect.right + 60, y, 40, 40)
                    if minus.collidepoint(mx, my):
                        if key == "maxhp": temp_max_hp = max(1, temp_max_hp - 10)
                        if key == "damage": temp_damage = max(1, temp_damage - 1)
                        if key == "score": temp_score = max(0, temp_score - 1)
                        if key == "speed": temp_speed = max(1, temp_speed - 1)
                        if key == "pierce": temp_pierce = max(0, temp_pierce - 1)
                        if key == "kb": temp_kb = max(0, temp_kb - 1)
                    if plus.collidepoint(mx, my):
                        if key == "maxhp": temp_max_hp += 10
                        if key == "damage": temp_damage += 1
                        if key == "score": temp_score += 1
                        if key == "speed": temp_speed += 1
                        if key == "pierce": temp_pierce = min(pierce_max_level, temp_pierce + 1)
                        if key == "kb": temp_kb = min(5, temp_kb + 1)

                # ability toggles
                ab_start_y = panel.y + 420
                ab_x = panel.x + 24
                for idx, k in enumerate(["Flame", "Poison", "Lightning", "Knockback", "Piercing", "Double Shot", "Corrosive"]):
                    y = ab_start_y + idx * 36
                    cb = pygame.Rect(ab_x, y, 24, 24)
                    if cb.collidepoint(mx, my):
                        temp_owned[k] = not temp_owned.get(k, False)

                if apply_rect.collidepoint(mx, my):
                    globals()["max_hp"] = temp_max_hp
                    globals()["player_hp"] = min(player_hp, temp_max_hp)
                    globals()["arrow_damage"] = temp_damage
                    globals()["score"] = temp_score
                    globals()["player_speed"] = temp_speed
                    globals()["pierce_level"] = temp_pierce
                    globals()["knockback_level"] = temp_kb
                    for k, v in temp_owned.items():
                        owned_abilities[k] = v
                    notify_once("Admin applied", 700)
                    return

                if exp_rect.collidepoint(mx, my):
                    globals()["player_exp"] += 50
                    floating_texts.append({"x": WIDTH // 2, "y": HEIGHT // 2 - 40, "txt": "+50 EXP", "color": BLUE, "ttl": 60, "vy": -0.5, "alpha": 255})
                    return

                if close_rect.collidepoint(mx, my):
                    return

            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                return

# ---------- Ability choice between waves ----------
def ability_choice_between_waves():
    global player_hp, arrow_damage, knockback_level, owned_abilities, pierce_level, small_dots, corrosive_level

    all_options = list(ABILITY_RARITY.keys())
    rarity_weights = [("Common", 50), ("Rare", 30), ("Epic", 15), ("Legendary", 4), ("Mythical", 1)]
    tiers, weights = zip(*rarity_weights)
    chosen_rarity = random.choices(tiers, weights=weights, k=1)[0]

    pool = [a for a in all_options if ABILITY_RARITY[a] == chosen_rarity]
    if not pool:
        pool = all_options[:]
    choices = random.sample(pool, min(2, len(pool)))

    for _ in range(80):
        small_dots.append({"x": WIDTH // 2 + random.randint(-100, 100), "y": HEIGHT // 2 - 180 + random.randint(-40, 40),
                           "color": RARITY_COLORS.get(chosen_rarity, BLUE), "ttl": random.randint(40, 100), "vy": random.uniform(-1.5, 1.5)})

    buttons = []
    for i, c in enumerate(choices):
        rect = pygame.Rect(WIDTH // 2 - 220 + i * 280, HEIGHT // 2 - 50, 260, 80)
        buttons.append((rect, c))

    picking = True
    while picking:
        screen.fill(bg_color)
        draw_text_centered(FONT_LG, f"Choose an Upgrade ({chosen_rarity})", HEIGHT // 2 - 160, RARITY_COLORS.get(chosen_rarity, BLUE))

        mx, my = pygame.mouse.get_pos()
        for rect, label in buttons:
            rarity = ABILITY_RARITY.get(label, "Common")
            border_color = RARITY_COLORS.get(rarity, BLACK)
            pygame.draw.rect(screen, LIGHT_GRAY, rect)
            pygame.draw.rect(screen, border_color, rect, 4)
            screen.blit(FONT_MD.render(label, True, BLACK), (rect.x + 12, rect.y + 18))

        pygame.display.flip()

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                save_game(); pygame.quit(); sys.exit()
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                for rect, label in buttons:
                    if rect.collidepoint(mx, my):
                        # Apply chosen ability (repeat allowed)
                        if label == "Heal +20 HP":
                            globals()["player_hp"] = min(max_hp, player_hp + 20)
                        elif label == "Damage +5":
                            globals()["arrow_damage"] = globals().get("arrow_damage", DEFAULTS["arrow_damage"]) + 5
                        elif label == "Flame":
                            owned_abilities["Flame"] = True
                        elif label == "Poison":
                            owned_abilities["Poison"] = True
                        elif label == "Lightning":
                            owned_abilities["Lightning"] = True
                        elif label == "Knockback":
                            # FIXED: cap + keep consistent
                            globals()["knockback_level"] = min(5, globals().get("knockback_level", 1) + 1)
                            owned_abilities["Knockback"] = True
                        elif label == "Piercing":
                            # FIXED: cap
                            globals()["pierce_level"] = min(pierce_max_level, globals().get("pierce_level", 0) + 1)
                            owned_abilities["Piercing"] = True
                        elif label == "Double Shot":
                            owned_abilities["Double Shot"] = True
                        elif label == "Corrosive":
                            if not owned_abilities.get("Corrosive", False):
                                corrosive_level = max(1, corrosive_level)
                            else:
                                corrosive_level = min(5, corrosive_level + 1)
                                notify_once("Corrosive radius increased!", 900)
                            owned_abilities["Corrosive"] = True

                        for _ in range(40):
                            small_dots.append({"x": rect.centerx + random.randint(-30, 30), "y": rect.centery + random.randint(-24, 24),
                                               "color": RARITY_COLORS.get(chosen_rarity, BLUE), "ttl": random.randint(20, 60), "vy": random.uniform(-1, 1)})
                        picking = False
                        break
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                picking = False

        clock.tick(FPS)

# ---------- Corrosive field ----------
CORROSIVE_BASE_RADIUS = 360
CORROSIVE_DPS = 12.5

def draw_corrosive_field_visual(actual_radius):
    size = int(actual_radius * 2)
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    surf.fill((*ACID_YELLOW, 80))
    screen.blit(surf, (player.centerx - actual_radius, player.centery - actual_radius))
    pygame.draw.rect(screen, ACID_YELLOW, (player.centerx - actual_radius, player.centery - actual_radius, size, size), 2)

# ---------- Combat handlers ----------
def handle_arrow_hit(enemy, dmg=None):
    dmg = dmg if dmg is not None else globals().get("arrow_damage", DEFAULTS["arrow_damage"])
    enemy.hp -= dmg
    floating_texts.append({"x": enemy.rect.centerx, "y": enemy.rect.top - 12, "txt": f"-{int(dmg)}", "color": RED, "ttl": 60, "vy": -0.6, "alpha": 255})

    # Class hook
    try:
        player_class.on_arrow_hit(enemy, dmg)
    except Exception:
        pass

    now = pygame.time.get_ticks()
    if owned_abilities.get("Flame", False):
        enemy.burn_ms_left = 3000; enemy.last_status_tick = now - 1000
    if owned_abilities.get("Poison", False):
        enemy.poison_ms_left = 3000; enemy.last_status_tick = now - 1000
    if owned_abilities.get("Lightning", False):
        lightning_lines.append({"x1": enemy.rect.centerx, "y1": enemy.rect.centery, "x2": enemy.rect.centerx, "y2": enemy.rect.centery, "ttl": 250})
        apply_lightning_chain(enemy, dmg)

    if enemy.hp <= 0:
        if getattr(enemy, "is_boss", False):
            spawn_orb(enemy.rect.centerx, enemy.rect.centery, amount=10 + 10 * (wave - 1))
            globals()["score"] += 25
        else:
            spawn_orb(enemy.rect.centerx, enemy.rect.centery, amount=1)
            globals()["score"] += 1
        try:
            enemies.remove(enemy)
        except ValueError:
            pass

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
            diff = abs((enemy_angle - angle_to_mouse + math.pi) % (2 * math.pi) - math.pi)
            if diff <= math.radians(DEFAULTS["sword_arc_half_deg"]) * 1.05:
                enemy.hp -= DEFAULTS["sword_damage"]
                floating_texts.append({"x": enemy.rect.centerx, "y": enemy.rect.top - 12, "txt": f"-{DEFAULTS['sword_damage']}", "color": RED, "ttl": 60, "vy": -0.6, "alpha": 255})

                if dist != 0:
                    enemy.rect.x += int(kb * (ex / dist))
                    enemy.rect.y += int(kb * (ey / dist))

                now = pygame.time.get_ticks()
                if owned_abilities.get("Flame", False):
                    enemy.burn_ms_left = 3000; enemy.last_status_tick = now - 1000
                if owned_abilities.get("Poison", False):
                    enemy.poison_ms_left = 3000; enemy.last_status_tick = now - 1000
                if owned_abilities.get("Lightning", False):
                    lightning_lines.append({"x1": enemy.rect.centerx, "y1": enemy.rect.centery, "x2": enemy.rect.centerx, "y2": enemy.rect.centery, "ttl": 250})
                    apply_lightning_chain(enemy, DEFAULTS["sword_damage"])

                if enemy.hp <= 0:
                    if getattr(enemy, "is_boss", False):
                        score += 25
                        spawn_orb(enemy.rect.centerx, enemy.rect.centery, amount=10 + 10 * (wave - 1))
                    else:
                        score += 1
                        spawn_orb(enemy.rect.centerx, enemy.rect.centery, amount=1)
                    try:
                        enemies.remove(enemy)
                    except ValueError:
                        pass

def shoot_bow(mx, my):
    used = False
    try:
        used = player_class.on_arrow_fire(mx, my)
    except Exception:
        used = False

    if owned_abilities.get("Double Shot", False):
        if not used:
            arrows.append(Arrow(player.centerx, player.centery, mx, my - 10, pierce=pierce_level))
            arrows.append(Arrow(player.centerx, player.centery, mx, my + 10, pierce=pierce_level))
    else:
        if not used:
            arrows.append(Arrow(player.centerx, player.centery, mx, my, pierce=pierce_level))

# ---------- Menus ----------
def class_shop_menu():
    global gems, player_class
    while True:
        screen.fill(bg_color)
        draw_text_centered(FONT_LG, "Class Shop", 80)
        draw_text_centered(FONT_MD, f"Gems: {gems}", 150)

        buttons = []
        for i, cls in enumerate(PLAYER_CLASS_ORDER):
            y = 220 + i * 90
            rect = pygame.Rect(WIDTH // 2 - 240, y, 480, 70)
            cost = CLASS_COSTS[cls.name]
            selected = (player_class.name == cls.name)

            pygame.draw.rect(screen, LIGHT_GRAY, rect)
            pygame.draw.rect(screen, cls.color, rect, 4)

            rarity = class_rarity_label(cls.name)
            text = f"{cls.name} [{rarity}] — Cost: {cost}"
            if cls.name == "Mad Scientist":
                text += " (Curving AI Bow)"
            if cls.name == "Knight":
                text += " (Deflect + Armor)"
            if selected:
                text = f"{cls.name} [{rarity}] — Selected"

            screen.blit(FONT_MD.render(text, True, BLACK), (rect.x + 16, rect.y + 18))
            buttons.append((rect, cls, cost, selected))

        back_rect = pygame.Rect(WIDTH // 2 - 120, HEIGHT - 90, 240, 60)
        pygame.draw.rect(screen, LIGHT_GRAY, back_rect)
        pygame.draw.rect(screen, BLACK, back_rect, 3)
        screen.blit(FONT_MD.render("Back", True, BLACK), (back_rect.x + 70, back_rect.y + 14))

        pygame.display.flip()

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                save_game(); pygame.quit(); sys.exit()
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                save_game()
                return
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                mx, my = ev.pos
                for r, cls, cost, selected in buttons:
                    if r.collidepoint(mx, my):
                        if selected:
                            return
                        if gems >= cost:
                            gems -= cost
                            player_class = cls()
                            save_game()
                            load_slot_meta(current_save_slot)
                            notify_once(f"{cls.name} Selected!", 800)
                            return
                        else:
                            notify_once("Not enough Gems!", 800)
                if back_rect.collidepoint(mx, my):
                    save_game()
                    return

def main_menu():
    global admin_unlocked, admin_available_next_game, gems, online_mode
    secret_sequence = "openadminpanel"
    secret_buffer = ""

    refresh_all_slot_meta()

    while True:
        screen.fill(bg_color)
        draw_text_centered(FONT_LG, "Infinite Archer", HEIGHT // 6)
        mx, my = pygame.mouse.get_pos()

        btn_w, btn_h = 360, 70
        new_rect = pygame.Rect(WIDTH // 2 - btn_w // 2, HEIGHT // 2 - 140, btn_w, btn_h)
        resume_rect = pygame.Rect(WIDTH // 2 - btn_w // 2, HEIGHT // 2 - 40, btn_w, btn_h)
        quit_rect = pygame.Rect(WIDTH // 2 - btn_w // 2, HEIGHT // 2 + 60, btn_w, btn_h)
        class_rect = pygame.Rect(WIDTH // 2 - btn_w // 2, HEIGHT // 2 + 160, btn_w, btn_h)
        online_rect = pygame.Rect(WIDTH // 2 - btn_w // 2, HEIGHT // 2 + 260, btn_w, btn_h)

        # Save slots row
        slot_y = HEIGHT // 2 + 360
        slot_w = 180
        slot_h = 60
        slot1_rect = pygame.Rect(WIDTH // 2 - slot_w - 200, slot_y, slot_w, slot_h)
        slot2_rect = pygame.Rect(WIDTH // 2 - slot_w // 2, slot_y, slot_w, slot_h)
        slot3_rect = pygame.Rect(WIDTH // 2 + 200, slot_y, slot_w, slot_h)

        for rect, label in [(new_rect, "Create New Game"), (resume_rect, "Resume Game"), (quit_rect, "Quit")]:
            color = LIGHT_GRAY if rect.collidepoint(mx, my) else (220, 220, 220)
            pygame.draw.rect(screen, color, rect)
            pygame.draw.rect(screen, BLACK, rect, 3)
            screen.blit(FONT_MD.render(label, True, BLACK), (rect.x + 18, rect.y + 18))

        pygame.draw.rect(screen, LIGHT_GRAY if class_rect.collidepoint(mx, my) else (220, 220, 220), class_rect)
        pygame.draw.rect(screen, BLACK, class_rect, 3)
        screen.blit(FONT_MD.render("Classes", True, BLACK), (class_rect.x + 18, class_rect.y + 18))

        pygame.draw.rect(screen, LIGHT_GRAY if online_rect.collidepoint(mx, my) else (220, 220, 220), online_rect)
        pygame.draw.rect(screen, BLACK, online_rect, 3)
        online_label = "Online (MVP)" if websockets is not None else "Online (pip install websockets)"
        screen.blit(FONT_MD.render(online_label, True, BLACK), (online_rect.x + 18, online_rect.y + 18))

        # Gems shown are from current save-slot (instant)
        meta_now = load_slot_meta(current_save_slot)
        gems = int(meta_now.get("gems", gems))
        gem_txt = FONT_MD.render(f"Gems: {gems}  (Slot {current_save_slot})", True, BLUE)
        screen.blit(gem_txt, (WIDTH - gem_txt.get_width() - 22, 18))

        # current class display
        cls = player_class.name if 'player_class' in globals() else "No Class"
        screen.blit(FONT_SM.render(f"Class: {cls}", True, BLACK), (22, 18))

        hint = FONT_SM.render("WASD move • Mouse shoot • 1 Bow • 2 Sword • Esc menu", True, BLACK)
        screen.blit(hint, (WIDTH // 2 - hint.get_width() // 2, HEIGHT - 60))

        if websockets is None:
            tip = FONT_SM.render("To use Online: python -m pip install websockets", True, (90, 90, 90))
            screen.blit(tip, (WIDTH // 2 - tip.get_width() // 2, HEIGHT - 90))

        if admin_unlocked:
            m = FONT_SM.render("Admin unlocked — will appear next game", True, (150, 0, 50))
            screen.blit(m, (WIDTH // 2 - m.get_width() // 2, HEIGHT // 2 - 180))

        # Save slot buttons
        for s, r in [(1, slot1_rect), (2, slot2_rect), (3, slot3_rect)]:
            meta = load_slot_meta(s)
            is_sel = (s == current_save_slot)
            fill = LIGHT_GRAY if r.collidepoint(mx, my) else (220, 220, 220)
            pygame.draw.rect(screen, fill, r)
            pygame.draw.rect(screen, BLUE if is_sel else BLACK, r, 4 if is_sel else 3)
            label = f"Slot {s}: {int(meta.get('gems', 0))}"
            screen.blit(FONT_MD.render(label, True, BLACK), (r.x + 14, r.y + 14))

        slot_hint = FONT_SM.render("Pick a save slot (gems are separate per slot)", True, (60, 60, 60))
        screen.blit(slot_hint, (WIDTH // 2 - slot_hint.get_width() // 2, slot_y + 72))

        pygame.display.flip()

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                save_game(); pygame.quit(); sys.exit()

            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                # Save slot selection
                if slot1_rect.collidepoint(ev.pos):
                    globals()["current_save_slot"] = 1
                    notify_once("Selected Slot 1", 500)
                    continue
                if slot2_rect.collidepoint(ev.pos):
                    globals()["current_save_slot"] = 2
                    notify_once("Selected Slot 2", 500)
                    continue
                if slot3_rect.collidepoint(ev.pos):
                    globals()["current_save_slot"] = 3
                    notify_once("Selected Slot 3", 500)
                    continue

                if new_rect.collidepoint(ev.pos):
                    online_mode = False
                    reset_game()
                    return "new"

                if resume_rect.collidepoint(ev.pos):
                    online_mode = False
                    if load_game():
                        notify_once("Loaded Save", 700)
                        return "resume"
                    else:
                        notify_once("No save found — starting new", 900)
                        reset_game()
                        return "new"

                if class_rect.collidepoint(ev.pos):
                    class_shop_menu()

                if online_rect.collidepoint(ev.pos):
                    if websockets is None:
                        notify_once("Install websockets: python -m pip install websockets", 1500)
                    else:
                        online_mode = True
                        reset_game()
                        return "new"

                if quit_rect.collidepoint(ev.pos):
                    save_game(); pygame.quit(); sys.exit()

            if ev.type == pygame.KEYDOWN:
                secret_buffer += ev.unicode.lower()
                if len(secret_buffer) > len(secret_sequence):
                    secret_buffer = secret_buffer[-len(secret_sequence):]
                if secret_buffer == secret_sequence:
                    admin_unlocked = True
                    admin_available_next_game = True
                    notify_once("Admin unlocked — will appear next game", 1200)

                if ev.key == pygame.K_ESCAPE:
                    save_game(); pygame.quit(); sys.exit()

        clock.tick(FPS)

def game_over_screen():
    while True:
        screen.fill(bg_color)
        draw_text_centered(FONT_LG, "Game Over", HEIGHT // 2 - 80)
        draw_text_centered(FONT_MD, f"Score: {score}", HEIGHT // 2 - 20)
        draw_text_centered(FONT_MD, "Click or press Enter to return to menu", HEIGHT // 2 + 40)
        pygame.display.flip()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                save_game(); pygame.quit(); sys.exit()
            if ev.type == pygame.MOUSEBUTTONDOWN or (ev.type == pygame.KEYDOWN and ev.key == pygame.K_RETURN):
                return
        clock.tick(FPS)

# ---------- Main Game Loop ----------
def game_loop():
    global weapon, wave, enemies_per_wave, score, player_hp
    global player_exp, player_level, exp_required, gems
    global in_collection_phase, collection_start_ms, collection_duration_ms
    global spawn_preview_active, spawn_preview_start_ms, spawn_preview_ms, spawn_pattern_positions
    global corrosive_level
    global online_mode, net, net_players_cache
    global admin_available_next_game

    if 'player' not in globals():
        reset_game()

    player.center = (WIDTH // 2, HEIGHT // 2)
    show_admin_button = False
    if admin_available_next_game:
        show_admin_button = True
        admin_available_next_game = False

    spawn_preview_active = True
    spawn_preview_start_ms = pygame.time.get_ticks()
    running = True

    while running:
        dt = clock.tick(FPS)
        now_ms = pygame.time.get_ticks()

        # class passive update
        try:
            player_class.on_update(now_ms)
        except Exception:
            pass

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                save_game(); pygame.quit(); sys.exit()

            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    save_game()
                    return
                if ev.key == pygame.K_1:
                    weapon = "bow"
                if ev.key == pygame.K_2:
                    weapon = "sword"
                if in_collection_phase and ev.key == pygame.K_SPACE:
                    for orb in pending_orbs[:]:
                        player_exp += orb["amount"]
                        gems += orb["amount"]
                        try: pending_orbs.remove(orb)
                        except: pass
                    collection_start_ms = now_ms - collection_duration_ms - 1

            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                mx, my = ev.pos

                # Save button
                save_btn = pygame.Rect(WIDTH - 120, HEIGHT - 60, 100, 40)
                if save_btn.collidepoint(mx, my):
                    save_game()
                    floating_texts.append({"x": save_btn.centerx, "y": save_btn.top - 10, "txt": "Saved!", "color": BLUE, "ttl": 45, "vy": -0.6, "alpha": 255})
                    continue

                if show_admin_button:
                    admin_rect = pygame.Rect(WIDTH - 170, 12, 158, 36)
                    if admin_rect.collidepoint(mx, my):
                        admin_panel_overlay()
                        continue

                if in_collection_phase:
                    for orb in pending_orbs[:]:
                        rect = pygame.Rect(orb["x"] - 8, orb["y"] - 8, 16, 16)
                        if rect.collidepoint(mx, my):
                            player_exp += orb["amount"]
                            gems += orb["amount"]
                            try: pending_orbs.remove(orb)
                            except: pass
                            break
                    continue

                if weapon == "bow":
                    shoot_bow(mx, my)
                else:
                    handle_sword_attack(mx, my)

        # movement
        keys = pygame.key.get_pressed()
        if keys[pygame.K_w]: player.y -= player_speed
        if keys[pygame.K_s]: player.y += player_speed
        if keys[pygame.K_a]: player.x -= player_speed
        if keys[pygame.K_d]: player.x += player_speed
        player.clamp_ip(screen.get_rect())

        # Online send/receive
        if online_mode and net is not None:
            net.send_input(player.centerx, player.centery, weapon)
            net_players_cache = net.get_players()
            if online_coop_enemies:
                net_enemies_cache = net.get_enemies()

        # Server-authoritative enemies (true co-op MVP)
        if online_mode and online_coop_enemies and net is not None:
            # If we have server enemies, mirror them into local `enemies` list for drawing/collisions
            if net_enemies_cache:
                enemies.clear()
                for eid, ed in net_enemies_cache.items():
                    try:
                        r = pygame.Rect(int(ed.get("x", 0)), int(ed.get("y", 0)), int(ed.get("w", 30)), int(ed.get("h", 30)))
                        obj = Enemy(r, str(ed.get("etype", "normal")))
                        obj.hp = float(ed.get("hp", 1))
                        obj._net_id = str(eid)
                        enemies.append(obj)
                    except Exception:
                        continue

        # spawn preview
        if spawn_preview_active:
            if now_ms - spawn_preview_start_ms >= spawn_preview_ms:
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

        # update enemy arrows
        for ea in enemy_arrows[:]:
            if not ea.update():
                try: enemy_arrows.remove(ea)
                except: pass

        # update enemies
        for enemy in enemies[:]:
            if getattr(enemy, "is_boss", False):
                boss_try_summon(enemy)

            proj = enemy.try_shoot(now_ms)
            if proj:
                enemy_arrows.append(EnemyArrow(proj["rect"], proj["vx"], proj["vy"], proj["damage"]))

            enemy.move_towards(player.centerx, player.centery)
            enemy.apply_status(now_ms)

            if enemy.hp <= 0:
                if getattr(enemy, "is_boss", False):
                    score += 25
                    spawn_orb(enemy.rect.centerx, enemy.rect.centery, amount=10 + 10 * (wave - 1))
                else:
                    score += 1
                    spawn_orb(enemy.rect.centerx, enemy.rect.centery, amount=1)
                try: enemies.remove(enemy)
                except: pass
                continue

            if player.colliderect(enemy.rect):
                dmg = enemy.damage
                # Knight armor: 10% reduction
                if isinstance(player_class, Knight):
                    dmg = int(math.ceil(dmg * 0.90))
                player_hp -= dmg
                try: enemies.remove(enemy)
                except: pass
                if player_hp <= 0:
                    game_over_screen()
                    reset_game()
                    return

        # enemy arrows hitting player
        for ea in enemy_arrows[:]:
            if player.colliderect(ea.rect):
                # Knight deflect (only with sword)
                if isinstance(player_class, Knight) and weapon == "sword":
                    if player_class.try_deflect(ea):
                        continue
                dmg = ea.damage
                if isinstance(player_class, Knight):
                    dmg = int(math.ceil(dmg * 0.90))
                player_hp -= dmg
                try: enemy_arrows.remove(ea)
                except: pass
                if player_hp <= 0:
                    game_over_screen()
                    reset_game()
                    return

        # player arrows hit enemies
        for a in arrows[:]:
            for enemy in enemies[:]:
                if enemy.rect.colliderect(a.rect):
                    if online_mode and online_coop_enemies and net is not None and hasattr(enemy, "_net_id"):
                        net.send_hit(enemy._net_id, globals().get("arrow_damage", DEFAULTS["arrow_damage"]))
                    else:
                        handle_arrow_hit(enemy)
                    if getattr(a, "pierce_remaining", 0) > 0:
                        a.pierce_remaining -= 1
                    else:
                        try: arrows.remove(a)
                        except: pass
                    break

        # corrosive ability
        if owned_abilities.get("Corrosive", False):
            level = max(1, corrosive_level)
            actual_radius = CORROSIVE_BASE_RADIUS * (2 ** (level - 1))
            draw_corrosive_field_visual(actual_radius)

            if not hasattr(draw_corrosive_field_visual, "last_tick"):
                draw_corrosive_field_visual.last_tick = 0
            if now_ms - draw_corrosive_field_visual.last_tick >= 1000:
                draw_corrosive_field_visual.last_tick = now_ms
                field_rect = pygame.Rect(player.centerx - actual_radius, player.centery - actual_radius, int(actual_radius * 2), int(actual_radius * 2))
                for e in enemies[:]:
                    if field_rect.colliderect(e.rect):
                        e.hp -= CORROSIVE_DPS
                        small_dots.append({"x": e.rect.centerx, "y": e.rect.top - 6, "color": ACID_YELLOW, "ttl": 30, "vy": -0.2})
                        floating_texts.append({"x": e.rect.centerx, "y": e.rect.top - 18, "txt": f"-{CORROSIVE_DPS}", "color": ACID_YELLOW, "ttl": 60, "vy": -0.6, "alpha": 255})
                        if e.hp <= 0:
                            if getattr(e, "is_boss", False):
                                score += 25
                                spawn_orb(e.rect.centerx, e.rect.centery, amount=10 + 10 * (wave - 1))
                            else:
                                score += 1
                                spawn_orb(e.rect.centerx, e.rect.centery, amount=1)
                            try: enemies.remove(e)
                            except: pass

        # start collection if cleared
        if not enemies and not in_collection_phase and not spawn_preview_active:
            in_collection_phase = True
            collection_start_ms = pygame.time.get_ticks()

        # collection phase
        if in_collection_phase:
            for orb in pending_orbs[:]:
                dx = player.centerx - orb["x"]; dy = player.centery - orb["y"]
                dist = math.hypot(dx, dy) or 1.0
                speed = 4 + min(8, dist / 20.0)
                orb["x"] += (dx / dist) * speed
                orb["y"] += (dy / dist) * speed
                if math.hypot(orb["x"] - player.centerx, orb["y"] - player.centery) < 20:
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
                    exp_required = 10 + 10 * (player_level - 1)
                    leveled = True

                if leveled:
                    ability_choice_between_waves()

                save_game()
                spawn_preview_active = True
                spawn_preview_start_ms = pygame.time.get_ticks()
                player.center = (WIDTH // 2, HEIGHT // 2)
                wave += 1
                enemies_per_wave = max(1, int(round(enemies_per_wave * 1.1)))

        # update floating texts / particles
        for t in floating_texts[:]:
            t["y"] += t.get("vy", -0.5)
            t["ttl"] -= 1
            if "alpha" in t:
                t["alpha"] = max(0, t.get("alpha", 255) - 4)
            if t["ttl"] <= 0:
                try: floating_texts.remove(t)
                except: pass

        for d in small_dots[:]:
            d["y"] += d.get("vy", -0.2)
            d["ttl"] -= 1
            if d["ttl"] <= 0:
                try: small_dots.remove(d)
                except: pass

        for L in lightning_lines[:]:
            L["ttl"] -= dt
            if L["ttl"] <= 0:
                try: lightning_lines.remove(L)
                except: pass

        # ---------- DRAW ----------
        screen.fill(bg_color)

        # player
        pygame.draw.rect(screen, GREEN, player)

        # other online players
        if online_mode and net is not None:
            for pid, p in net_players_cache.items():
                if net.id is not None and pid == net.id:
                    continue
                try:
                    rx, ry = int(p.get("x", 0)), int(p.get("y", 0))
                except Exception:
                    continue
                r = pygame.Rect(rx - player.width // 2, ry - player.height // 2, player.width, player.height)
                pygame.draw.rect(screen, (60, 160, 255), r)
                nm = str(p.get("name", pid))
                tag = FONT_SM.render(nm, True, BLACK)
                screen.blit(tag, (r.x, r.y - 18))

        # weapon visuals (blue bow for Mad Scientist)
        if weapon == "bow":
            bow_length = 60
            arc_rect = pygame.Rect(player.centerx - 12, player.centery - bow_length, 24, bow_length * 2)
            bow_color = BLUE if isinstance(player_class, MadScientist) else BROWN
            string_color = BLUE if isinstance(player_class, MadScientist) else BLACK
            try:
                pygame.draw.arc(screen, bow_color, arc_rect, math.radians(270), math.radians(90), 4)
            except:
                pass
            top = (player.centerx + 4, player.centery - int(bow_length * 0.9))
            bottom = (player.centerx + 4, player.centery + int(bow_length * 0.9))
            pygame.draw.line(screen, string_color, top, bottom, 2)
        else:
            mx, my = pygame.mouse.get_pos()
            angle = math.atan2(my - player.centery, mx - player.centerx)
            tip_x = player.centerx + DEFAULTS["sword_range"] * math.cos(angle)
            tip_y = player.centery + DEFAULTS["sword_range"] * math.sin(angle)
            pygame.draw.line(screen, (192, 192, 192), (player.centerx, player.centery), (tip_x, tip_y), 8)

        # spawn preview squares
        if spawn_preview_active:
            preview_positions = spawn_pattern_positions[:int(enemies_per_wave)]
            for rx, ry in preview_positions:
                size = 34
                rect = pygame.Rect(rx - size // 2, ry - size // 2, size, size)
                s = pygame.Surface((size, size), pygame.SRCALPHA)
                s.fill((200, 40, 40, 120))
                screen.blit(s, rect.topleft)
                pygame.draw.rect(screen, RED, rect, 2)
                pygame.draw.line(screen, RED, (rect.left + 6, rect.top + 6), (rect.right - 6, rect.bottom - 6), 2)
                pygame.draw.line(screen, RED, (rect.right - 6, rect.top + 6), (rect.left + 6, rect.bottom - 6), 2)

        # arrows
        for a in arrows:
            a.draw(screen)
        for ea in enemy_arrows:
            ea.draw(screen)

        # enemies
        for enemy in enemies:
            pygame.draw.rect(screen, enemy.color, enemy.rect)
            if enemy.burn_ms_left > 0:
                pygame.draw.circle(screen, ORANGE, (enemy.rect.centerx + 10, enemy.rect.top + 8), 5)
            if enemy.poison_ms_left > 0:
                pygame.draw.circle(screen, PURPLE, (enemy.rect.centerx - 10, enemy.rect.top + 8), 5)

        # orbs (gems)
        for orb in pending_orbs:
            pygame.draw.rect(screen, BLUE, (int(orb["x"]) - 6, int(orb["y"]) - 6, 12, 12))
            txt = FONT_SM.render(str(orb["amount"]), True, BLACK)
            screen.blit(txt, (int(orb["x"]) - txt.get_width() // 2, int(orb["y"]) - txt.get_height() // 2))

        # floating text
        for t in floating_texts:
            surf = FONT_SM.render(t["txt"], True, t["color"])
            screen.blit(surf, (t["x"] - surf.get_width() // 2, t["y"]))

        # lightning
        for L in lightning_lines:
            pygame.draw.line(screen, YELLOW, (L["x1"], L["y1"]), (L["x2"], L["y2"]), 3)

        # particles
        for d in small_dots:
            pygame.draw.circle(screen, d["color"], (int(d["x"]), int(d["y"])), 4)

        # HUD
        hud = FONT_SM.render(
            f"Score: {score}  Wave: {wave}  HP: {player_hp}  Dmg: {arrow_damage}  Gems: {gems}  Class: {player_class.name}",
            True, BLACK
        )
        screen.blit(hud, (12, 56))

        # Always show mode status
        if online_mode:
            url = os.environ.get("IA_SERVER", "ws://localhost:8765")
            if net is None:
                screen.blit(FONT_SM.render(f"MODE: ONLINE (NO CLIENT)  URL:{url}", True, BLUE), (12, 84))
            else:
                sid = net.id if net.id else "?"
                st = getattr(net, "last_status", "CONNECTING")
                screen.blit(FONT_SM.render(f"MODE: ONLINE ({st})  ID:{sid}", True, BLUE), (12, 84))
                screen.blit(FONT_SM.render(f"URL: {url}", True, (30, 110, 220)), (12, 108))
                # show last error only if not online
                if st not in ("ONLINE",) and getattr(net, "last_error", ""):
                    err = net.last_error
                    if len(err) > 80:
                        err = err[:80] + "…"
                    screen.blit(FONT_SM.render(f"NET ERR: {err}", True, (180, 60, 60)), (12, 132))
        else:
            screen.blit(FONT_SM.render("MODE: OFFLINE", True, (90, 90, 90)), (12, 84))

        # in-game Save button
        save_btn = pygame.Rect(WIDTH - 120, HEIGHT - 60, 100, 40)
        pygame.draw.rect(screen, LIGHT_GRAY, save_btn)
        pygame.draw.rect(screen, BLACK, save_btn, 2)
        screen.blit(FONT_SM.render("Save", True, BLACK), (save_btn.x + 26, save_btn.y + 10))

        draw_hp_bar(player_hp)
        draw_exp_bar()

        # boss bar
        boss = None
        for e in enemies:
            if getattr(e, "is_boss", False):
                boss = e
                break
        if boss:
            bw = int(WIDTH * 0.6)
            x = WIDTH // 2 - bw // 2
            y = 18
            frac = max(0, min(1, boss.hp / DEFAULTS["boss_hp"]))
            pygame.draw.rect(screen, DARK_RED, (x, y, bw, 18))
            pygame.draw.rect(screen, GREEN, (x, y, int(bw * frac), 18))
            pygame.draw.rect(screen, BLACK, (x, y, bw, 18), 2)
            txt = FONT_SM.render(f"Boss HP: {int(boss.hp)}", True, BLACK)
            screen.blit(txt, (WIDTH // 2 - txt.get_width() // 2, y + 22))

        if show_admin_button:
            draw_admin_button()

        if in_collection_phase:
            prompt = FONT_MD.render("Collection phase: Orbs fly to you (Space to collect all)", True, BLACK)
            screen.blit(prompt, (WIDTH // 2 - prompt.get_width() // 2, HEIGHT // 2 - 160))
            remaining = max(0, int((collection_start_ms + collection_duration_ms - now_ms) / 1000) + 1)
            t2 = FONT_LG.render(f"Collecting: {remaining}s", True, BLACK)
            screen.blit(t2, (WIDTH // 2 - t2.get_width() // 2, HEIGHT // 2 - 100))

        pygame.display.flip()

# ---------- ENTRY ----------
if __name__ == "__main__":
    # CLI args (simple)
    if "--name" in sys.argv:
        try:
            i = sys.argv.index("--name")
            if i + 1 < len(sys.argv):
                ONLINE_USERNAME = sys.argv[i + 1]
        except Exception:
            pass

    # server mode
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
            # already loaded inside main_menu
            pass
        spawn_preview_active = True
        spawn_preview_start_ms = pygame.time.get_ticks()
        game_loop()