# test.py
# Infinite Archer — Fixed: floating texts/dots/lighting + reset + archers + boss bar + piercing
# Run with: python test.py
import pygame, random, math, sys, os, time

pygame.init()

# --- Config ---
FULLSCREEN = True
DEFAULT_WIDTH, DEFAULT_HEIGHT = 1280, 800

if FULLSCREEN:
    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    WIDTH, HEIGHT = screen.get_size()
else:
    WIDTH, HEIGHT = DEFAULT_WIDTH, DEFAULT_HEIGHT
    screen = pygame.display.set_mode((WIDTH, HEIGHT))

pygame.display.set_caption("Infinite Archer")
clock = pygame.time.Clock()
FPS = 60

# --- Colors ---
WHITE = (255,255,255)
BLACK = (0,0,0)
RED = (220,30,30)
GREEN = (50,200,50)
YELLOW = (240,240,50)
DARK_RED = (150,0,0)
BROWN = (139,69,19)
SILVER = (192,192,192)
ORANGE = (255,140,0)
PURPLE = (160,32,240)
CYAN = (0,200,255)
LIGHT_GRAY = (230,230,230)
DARK_GRAY = (40,40,40)

FONT_LG = pygame.font.SysFont(None, 84)
FONT_MD = pygame.font.SysFont(None, 44)
FONT_SM = pygame.font.SysFont(None, 28)

# --- Defaults used on reset ---
DEFAULTS = {
    "player_size": 40,
    "player_speed": 5,
    "max_hp": 100,
    "arrow_speed": 18,
    "arrow_damage": 20,
    "sword_damage": 40,
    "sword_cooldown": 300,
    "sword_range": 120,
    "sword_arc_half_deg": 45,
    "base_knockback": 6,
    "enemies_per_wave_start": 5,
    "boss_hp": 2000,
    "archer_shot_damage": 10
}

# --- Globals that will be reset by reset_game() ---
def reset_game():
    global player, player_speed, max_hp, player_hp
    global arrow_speed, arrow_damage, sword_damage
    global sword_cooldown, sword_range, sword_arc_half, base_knockback, knockback_level
    global owned_abilities, pierce_level, pierce_max_level
    global enemies, arrows, enemy_arrows
    global wave, enemies_per_wave, score
    global floating_texts, lightning_lines, small_dots
    global weapon

    player_size = DEFAULTS["player_size"]
    player = pygame.Rect(WIDTH//2 - player_size//2, HEIGHT//2 - player_size//2, player_size, player_size)
    player_speed = DEFAULTS["player_speed"]
    max_hp = DEFAULTS["max_hp"]
    player_hp = max_hp

    arrow_speed = DEFAULTS["arrow_speed"]
    arrow_damage = DEFAULTS["arrow_damage"]
    sword_damage = DEFAULTS["sword_damage"]
    sword_cooldown = DEFAULTS["sword_cooldown"]
    sword_range = DEFAULTS["sword_range"]
    sword_arc_half = math.radians(DEFAULTS["sword_arc_half_deg"])
    base_knockback = DEFAULTS["base_knockback"]
    knockback_level = 1

    owned_abilities = {
        "Flame": False,
        "Poison": False,
        "Lightning": False,
        "Knockback": False,
        "Piercing": False
    }
    pierce_level = 0
    pierce_max_level = 3

    enemies = []
    arrows = []
    enemy_arrows = []

    floating_texts = []   # {x,y,txt,color,ttl,vy,alpha}
    lightning_lines = []  # {x1,y1,x2,y2,ttl}
    small_dots = []       # {x,y,color,ttl,vy}

    wave = 1
    enemies_per_wave = DEFAULTS["enemies_per_wave_start"]
    score = 0

    weapon = "bow"  # "bow" or "sword"

    # export to globals
    globals().update({
        "player": player, "player_speed": player_speed, "max_hp": max_hp, "player_hp": player_hp,
        "arrow_speed": arrow_speed, "arrow_damage": arrow_damage, "sword_damage": sword_damage,
        "sword_cooldown": sword_cooldown, "sword_range": sword_range, "sword_arc_half": sword_arc_half,
        "base_knockback": base_knockback, "knockback_level": knockback_level,
        "owned_abilities": owned_abilities, "pierce_level": pierce_level, "pierce_max_level": pierce_max_level,
        "enemies": enemies, "arrows": arrows, "enemy_arrows": enemy_arrows,
        "floating_texts": floating_texts, "lightning_lines": lightning_lines, "small_dots": small_dots,
        "wave": wave, "enemies_per_wave": enemies_per_wave, "score": score,
        "weapon": weapon
    })

# initialize for first run
reset_game()

# --- Helpers / Drawing ---
def draw_text_centered(font, text, y, color=BLACK):
    surf = font.render(text, True, color)
    screen.blit(surf, (WIDTH//2 - surf.get_width()//2, y))

def draw_hp_bar(hp):
    w, h = 300, 28
    x, y = 12, 12
    pygame.draw.rect(screen, DARK_GRAY, (x, y, w, h))
    pygame.draw.rect(screen, GREEN, (x, y, int(w * (hp / max_hp)), h))
    pygame.draw.rect(screen, BLACK, (x, y, w, h), 2)

def draw_bow(player_rect):
    bow_length = 60
    arc_rect = pygame.Rect(player_rect.centerx - 12, player_rect.centery - bow_length, 24, bow_length * 2)
    pygame.draw.arc(screen, BROWN, arc_rect, math.radians(270), math.radians(90), 4)
    top = (player_rect.centerx + 4, player_rect.centery - int(bow_length * 0.9))
    bottom = (player_rect.centerx + 4, player_rect.centery + int(bow_length * 0.9))
    pygame.draw.line(screen, BLACK, top, bottom, 2)

# --- Enemy class with archer behavior ---
class Enemy:
    def __init__(self, rect, etype="normal", is_mini=False, hp_override=None):
        self.rect = rect
        self.etype = etype  # normal, fast, tank, archer
        self.is_mini = is_mini
        self.is_boss = False

        # base stats before doubling
        if etype == "normal":
            base_hp, base_speed, base_damage = 20, 2, 10; color = RED
        elif etype == "fast":
            base_hp, base_speed, base_damage = 15, 3, 8; color = YELLOW
        elif etype == "tank":
            base_hp, base_speed, base_damage = 40, 1, 15; color = DARK_RED
        elif etype == "archer":
            base_hp, base_speed, base_damage = 18, 2, 8; color = CYAN
        else:
            base_hp, base_speed, base_damage = 20, 2, 10; color = RED

        if is_mini:
            self.color = YELLOW
            self.speed = base_speed * 2
            self.hp = (base_hp * 1) if hp_override is None else hp_override
            self.damage = base_damage
        else:
            self.color = color
            self.hp = (base_hp * 2) if hp_override is None else hp_override
            self.speed = base_speed
            self.damage = base_damage

        self.burn_ms_left = 0
        self.poison_ms_left = 0
        self.last_status_tick = 0
        # archer shooting timers
        self.shoot_timer = 0
        self.shoot_interval = 1800 + random.randint(-400, 400)
        self.summon_timer = 0

    def move_towards(self, tx, ty):
        dx = tx - self.rect.centerx
        dy = ty - self.rect.centery
        dist = math.hypot(dx, dy)
        if dist == 0: return
        spd = self.speed
        if self.poison_ms_left > 0:
            spd *= 0.5
        self.rect.x += round(spd * dx / dist)
        self.rect.y += round(spd * dy / dist)

    def try_shoot(self, now_ms):
        # archers shoot
        if self.etype != "archer": return None
        if now_ms - self.shoot_timer >= self.shoot_interval:
            self.shoot_timer = now_ms
            ex, ey = self.rect.centerx, self.rect.centery
            px, py = player.centerx, player.centery
            dx, dy = px - ex, py - ey
            d = math.hypot(dx, dy) or 1
            speed = 8
            vx = speed * dx / d
            vy = speed * dy / d
            proj = pygame.Rect(ex-4, ey-4, 8, 8)
            return {"rect": proj, "vx": vx, "vy": vy, "damage": DEFAULTS["archer_shot_damage"]}
        return None

    def apply_status(self, now_ms):
        if self.burn_ms_left > 0 or self.poison_ms_left > 0:
            if now_ms - self.last_status_tick >= 1000:
                self.last_status_tick = now_ms
                if self.burn_ms_left > 0:
                    self.hp -= 5
                    small_dots.append({"x": self.rect.centerx, "y": self.rect.top - 6, "color": ORANGE, "ttl": 30, "vy": -0.2})
                    floating_texts.append({"x": self.rect.centerx, "y": self.rect.top - 18, "txt": "-5", "color": ORANGE, "ttl": 60, "vy": -0.6, "alpha":255})
                    self.burn_ms_left = max(0, self.burn_ms_left - 1000)
                if self.poison_ms_left > 0:
                    self.hp -= 5
                    small_dots.append({"x": self.rect.centerx, "y": self.rect.top - 6, "color": PURPLE, "ttl": 30, "vy": -0.2})
                    floating_texts.append({"x": self.rect.centerx, "y": self.rect.top - 18, "txt": "-5", "color": PURPLE, "ttl": 60, "vy": -0.6, "alpha":255})
                    self.poison_ms_left = max(0, self.poison_ms_left - 1000)
        else:
            self.last_status_tick = now_ms

# Arrow (player) with piercing
class Arrow:
    def __init__(self, x, y, tx, ty, pierce=0):
        self.rect = pygame.Rect(0,0,30,6)
        dx = tx - x; dy = ty - y
        d = math.hypot(dx,dy) or 1.0
        self.vx = arrow_speed * dx / d
        self.vy = arrow_speed * dy / d
        self.angle = math.atan2(dy, dx)
        self.rect.center = (x + dx*0.18, y + dy*0.18)
        self.pierce_remaining = pierce
    def update(self):
        self.rect.x += self.vx
        self.rect.y += self.vy
        return screen.get_rect().colliderect(self.rect)
    def draw(self, surf):
        arr_surf = pygame.Surface((30,6), pygame.SRCALPHA)
        arr_surf.fill(BLACK)
        rot = pygame.transform.rotate(arr_surf, -math.degrees(self.angle))
        surf.blit(rot, (self.rect.x, self.rect.y))

# Enemy arrow projectile
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

# --- Spawn functions ---
def spawn_wave(count):
    global enemies
    enemies = []
    for _ in range(int(count)):
        side = random.choice(["top","bottom","left","right"])
        etype = random.choices(["normal","fast","tank","archer"], weights=[50,30,10,10])[0]
        if side == "top":
            rect = pygame.Rect(random.randint(0, WIDTH-30), -40, 30, 30)
        elif side == "bottom":
            rect = pygame.Rect(random.randint(0, WIDTH-30), HEIGHT+40, 30, 30)
        elif side == "left":
            rect = pygame.Rect(-40, random.randint(0, HEIGHT-30), 30, 30)
        else:
            rect = pygame.Rect(WIDTH+40, random.randint(0, HEIGHT-30), 30, 30)
        enemies.append(Enemy(rect, etype))

def spawn_boss():
    rect = pygame.Rect(WIDTH//2 - 60, -140, 120, 120)
    boss = Enemy(rect, "tank", is_mini=False, hp_override=DEFAULTS["boss_hp"])
    boss.is_boss = True
    boss.color = (100,10,60)
    boss.speed = 1.0
    boss.damage = 30 * 2
    boss.summon_timer = pygame.time.get_ticks() + 5000
    enemies.append(boss)

def boss_try_summon(boss_enemy):
    now = pygame.time.get_ticks()
    if now >= boss_enemy.summon_timer:
        n = random.randint(2,4)
        for _ in range(n):
            rx = boss_enemy.rect.centerx + random.randint(-80,80)
            ry = boss_enemy.rect.centery + random.randint(-80,80)
            rect = pygame.Rect(rx, ry, 20, 20)
            mini = Enemy(rect, "fast", is_mini=True)
            enemies.append(mini)
        boss_enemy.summon_timer = now + 5000

# --- Lightning chain ---
def apply_lightning_chain(origin_enemy, base_damage):
    nearby = 0
    ox, oy = origin_enemy.rect.centerx, origin_enemy.rect.centery
    others = [e for e in enemies if e is not origin_enemy and e.hp > 0]
    others.sort(key=lambda e: math.hypot(e.rect.centerx - ox, e.rect.centery - oy))
    for e in others:
        if nearby >= 2: break
        d = math.hypot(e.rect.centerx - ox, e.rect.centery - oy)
        if d <= 100:
            dmg = base_damage // 2
            e.hp -= dmg
            floating_texts.append({"x": e.rect.centerx, "y": e.rect.top - 12, "txt": f"-{dmg}", "color": YELLOW, "ttl": 60, "vy": -0.6, "alpha":255})
            lightning_lines.append({"x1": ox, "y1": oy, "x2": e.rect.centerx, "y2": e.rect.centery, "ttl": 350})
            nearby += 1

# --- Hit handlers ---
def handle_arrow_hit(enemy):
    global score
    enemy.hp -= arrow_damage
    floating_texts.append({"x": enemy.rect.centerx, "y": enemy.rect.top - 12, "txt": f"-{arrow_damage}", "color": RED, "ttl": 60, "vy": -0.6, "alpha":255})
    now = pygame.time.get_ticks()
    if owned_abilities.get("Flame", False):
        enemy.burn_ms_left = 3000
        enemy.last_status_tick = now - 1000
    if owned_abilities.get("Poison", False):
        enemy.poison_ms_left = 3000
        enemy.last_status_tick = now - 1000
    if owned_abilities.get("Lightning", False):
        lightning_lines.append({"x1": enemy.rect.centerx, "y1": enemy.rect.centery, "x2": enemy.rect.centerx, "y2": enemy.rect.centery, "ttl": 250})
        apply_lightning_chain(enemy, arrow_damage)

def handle_sword_attack(mx, my):
    global enemies, score
    now_ms = pygame.time.get_ticks()
    kb = base_knockback * knockback_level
    angle_to_mouse = math.atan2(my - player.centery, mx - player.centerx)
    hit_any = False
    for enemy in enemies[:]:
        ex = enemy.rect.centerx - player.centerx
        ey = enemy.rect.centery - player.centery
        dist = math.hypot(ex, ey)
        if dist <= sword_range:
            enemy_angle = math.atan2(ey, ex)
            diff = abs((enemy_angle - angle_to_mouse + math.pi) % (2*math.pi) - math.pi)
            if diff <= sword_arc_half * 1.05:
                hit_any = True
                enemy.hp -= sword_damage
                floating_texts.append({"x": enemy.rect.centerx, "y": enemy.rect.top - 12, "txt": f"-{sword_damage}", "color": RED, "ttl": 60, "vy": -0.6, "alpha":255})
                if dist != 0:
                    nx = int(kb * (ex / dist))
                    ny = int(kb * (ey / dist))
                    enemy.rect.x += nx
                    enemy.rect.y += ny
                if owned_abilities.get("Flame", False):
                    enemy.burn_ms_left = 3000
                if owned_abilities.get("Poison", False):
                    enemy.poison_ms_left = 3000
                if owned_abilities.get("Lightning", False):
                    lightning_lines.append({"x1": enemy.rect.centerx, "y1": enemy.rect.centery, "x2": enemy.rect.centerx, "y2": enemy.rect.centery, "ttl": 250})
                    apply_lightning_chain(enemy, sword_damage)
                if enemy.hp <= 0:
                    try:
                        if enemy.is_boss:
                            score += 25
                        else:
                            score += 1
                        enemies.remove(enemy)
                    except ValueError:
                        pass
    return hit_any

# --- Menus & UI ---
def main_menu():
    while True:
        screen.fill(WHITE)
        draw_text_centered(FONT_LG, "Infinite Archer", HEIGHT//6)
        mx, my = pygame.mouse.get_pos()
        btn_w = 360; btn_h = 70
        start_rect = pygame.Rect(WIDTH//2 - btn_w//2, HEIGHT//2 - 120, btn_w, btn_h)
        abilities_rect = pygame.Rect(WIDTH//2 - btn_w//2, HEIGHT//2 - 20, btn_w, btn_h)
        quit_rect = pygame.Rect(WIDTH//2 - btn_w//2, HEIGHT//2 + 80, btn_w, btn_h)
        for rect, label in [(start_rect, "Start Game"), (abilities_rect, "Abilities"), (quit_rect, "Quit")]:
            color = LIGHT_GRAY if rect.collidepoint(mx,my) else (220,220,220)
            pygame.draw.rect(screen, color, rect)
            pygame.draw.rect(screen, BLACK, rect, 3)
            surf = FONT_MD.render(label, True, BLACK)
            screen.blit(surf, (rect.x + 18, rect.y + 18))
        pygame.display.flip()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if start_rect.collidepoint(mx,my):
                    return
                if abilities_rect.collidepoint(mx,my):
                    abilities_menu()
                if quit_rect.collidepoint(mx,my):
                    pygame.quit(); sys.exit()
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                pygame.quit(); sys.exit()
        clock.tick(FPS)

def abilities_menu():
    showing = True
    while showing:
        screen.fill(WHITE)
        draw_text_centered(FONT_LG, "Abilities", HEIGHT//8)
        mx, my = pygame.mouse.get_pos()
        items = ["Flame","Poison","Lightning","Knockback","Piercing"]
        start_x = WIDTH//2 - 420
        start_y = 160
        gap_x = 320
        gap_y = 100
        for i, key in enumerate(items):
            x = start_x + (i%2) * gap_x
            y = start_y + (i//2) * gap_y
            rect = pygame.Rect(x, y, 300, 72)
            owned_flag = owned_abilities.get(key, False) if key != "Knockback" else (knockback_level > 1 or owned_abilities.get("Knockback", False))
            bg = LIGHT_GRAY if not owned_flag else (200,200,200)
            pygame.draw.rect(screen, bg, rect)
            pygame.draw.rect(screen, BLACK, rect, 2)
            label = FONT_SM.render(key if key!="Knockback" else f"Knockback Lv {knockback_level}", True, BLACK)
            screen.blit(label, (rect.x + 12, rect.y + 20))
            if owned_flag:
                note = FONT_SM.render("OWNED", True, (100,100,100))
                screen.blit(note, (rect.right - 100, rect.y + 20))
        back = pygame.Rect(WIDTH//2 - 80, HEIGHT - 120, 160, 56)
        pygame.draw.rect(screen, LIGHT_GRAY if back.collidepoint(mx,my) else (220,220,220), back)
        pygame.draw.rect(screen, BLACK, back, 2)
        screen.blit(FONT_MD.render("Back", True, BLACK), (back.x + 36, back.y + 12))
        pygame.display.flip()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if back.collidepoint(mx,my):
                    showing = False
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                showing = False
        clock.tick(FPS)

# Between-wave ability choice (2 clickable options)
def ability_choice_between_waves():
    global player_hp, arrow_damage, knockback_level, owned_abilities, pierce_level
    avail = []
    if not owned_abilities.get("Flame", False): avail.append("Flame")
    if not owned_abilities.get("Poison", False): avail.append("Poison")
    if not owned_abilities.get("Lightning", False): avail.append("Lightning")
    if knockback_level < 5: avail.append("Knockback")
    if pierce_level < pierce_max_level: avail.append("Piercing")

    if not avail:
        pool = ["Heal +20 HP", "Damage +10"]
    else:
        pool = avail.copy()
        pool.append("Heal +20 HP")
        pool.append("Damage +10")

    if len(pool) == 1:
        choices = pool.copy()
    else:
        choices = random.sample(pool, min(2, len(pool)))

    buttons = []
    for i, c in enumerate(choices):
        rect = pygame.Rect(WIDTH//2 - 220 + i*280, HEIGHT//2 - 50, 260, 80)
        buttons.append((rect, c))

    picking = True
    while picking:
        screen.fill(WHITE)
        draw_text_centered(FONT_LG, "Choose an Upgrade", HEIGHT//2 - 160)
        mx, my = pygame.mouse.get_pos()
        for rect, label in buttons:
            pygame.draw.rect(screen, LIGHT_GRAY, rect)
            pygame.draw.rect(screen, BLACK, rect, 3)
            display_label = label
            if label == "Knockback": display_label = f"Knockback +1 (to {min(5, knockback_level+1)})"
            if label == "Piercing": display_label = f"Piercing +1 (Lv {pierce_level+1})"
            screen.blit(FONT_MD.render(display_label, True, BLACK), (rect.x+12, rect.y+18))
        pygame.display.flip()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                for rect, label in buttons:
                    if rect.collidepoint(mx,my):
                        if label == "Heal +20 HP":
                            player_hp = min(max_hp, player_hp + 20)
                        elif label == "Damage +10":
                            globals()["arrow_damage"] = globals().get("arrow_damage", DEFAULTS["arrow_damage"]) + 10
                        elif label == "Flame":
                            owned_abilities["Flame"] = True
                        elif label == "Poison":
                            owned_abilities["Poison"] = True
                        elif label == "Lightning":
                            owned_abilities["Lightning"] = True
                        elif label == "Knockback":
                            if knockback_level < 5:
                                knockback_level += 1
                            owned_abilities["Knockback"] = True
                        elif label == "Piercing":
                            if pierce_level < pierce_max_level:
                                pierce_level += 1
                            owned_abilities["Piercing"] = True
                        picking = False
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                picking = False
        clock.tick(FPS)

def game_over_screen():
    while True:
        screen.fill(WHITE)
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

# initial spawn for first run
spawn_wave(enemies_per_wave := DEFAULTS["enemies_per_wave_start"])

# --- Main game loop ---
def game_loop():
    global weapon, arrows, enemies, enemy_arrows, wave, enemies_per_wave, score, player_hp
    global last_sword_attack, pierce_level

    last_sword_attack = -9999
    player.center = (WIDTH//2, HEIGHT//2)

    running = True
    while running:
        dt = clock.tick(FPS)
        now_ms = pygame.time.get_ticks()

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    return
                if ev.key == pygame.K_1:
                    weapon = "bow"
                if ev.key == pygame.K_2:
                    weapon = "sword"
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                mx, my = pygame.mouse.get_pos()
                if weapon == "bow":
                    arrows.append(Arrow(player.centerx, player.centery, mx, my, pierce=pierce_level))
                elif weapon == "sword":
                    now_ms = pygame.time.get_ticks()
                    if now_ms - last_sword_attack >= sword_cooldown:
                        last_sword_attack = now_ms
                        handle_sword_attack(mx, my)

        # movement
        keys = pygame.key.get_pressed()
        if keys[pygame.K_w]: player.y -= player_speed
        if keys[pygame.K_s]: player.y += player_speed
        if keys[pygame.K_a]: player.x -= player_speed
        if keys[pygame.K_d]: player.x += player_speed
        player.clamp_ip(screen.get_rect())

        # update player arrows
        for a in arrows[:]:
            alive = a.update()
            if not alive:
                try: arrows.remove(a)
                except ValueError: pass

        # update enemy arrows
        for ea in enemy_arrows[:]:
            alive = ea.update()
            if not alive:
                try: enemy_arrows.remove(ea)
                except ValueError: pass

        # enemies update
        for enemy in enemies[:]:
            if getattr(enemy, "is_boss", False):
                boss_try_summon(enemy)
            proj = enemy.try_shoot(now_ms)
            if proj:
                enemy_arrows.append(EnemyArrow(proj["rect"], proj["vx"], proj["vy"], proj["damage"]))

            enemy.move_towards(player.centerx, player.centery)
            enemy.apply_status(now_ms)

            if enemy.hp <= 0:
                try:
                    if getattr(enemy, "is_boss", False):
                        score += 25
                    else:
                        score += 1
                    enemies.remove(enemy)
                except ValueError:
                    pass
                continue

            # collision with player
            if player.colliderect(enemy.rect):
                player_hp -= enemy.damage
                try: enemies.remove(enemy)
                except ValueError: pass
                if player_hp <= 0:
                    game_over_screen()
                    return
                continue

        # enemy arrows hit player
        for ea in enemy_arrows[:]:
            if player.colliderect(ea.rect):
                player_hp -= ea.damage
                try: enemy_arrows.remove(ea)
                except ValueError: pass
                if player_hp <= 0:
                    game_over_screen()
                    return

        # arrows hitting enemies with piercing
        for a in arrows[:]:
            for enemy in enemies[:]:
                if enemy.rect.colliderect(a.rect):
                    handle_arrow_hit(enemy)
                    if getattr(a, "pierce_remaining", 0) > 0:
                        a.pierce_remaining -= 1
                        # arrow persists
                    else:
                        try: arrows.remove(a)
                        except ValueError: pass
                        break

        # wave clear
        if not enemies:
            ability_choice_between_waves()
            # 5-second countdown visual
            for s in range(5, 0, -1):
                screen.fill(WHITE)
                txt = FONT_LG.render(f"Next Wave in {s}", True, BLACK)
                screen.blit(txt, (WIDTH//2 - txt.get_width()//2, HEIGHT//2 - txt.get_height()//2))
                draw_hp_bar(player_hp)
                pygame.display.flip()
                pygame.time.delay(1000)

            wave += 1
            enemies_per_wave = max(1, int(round(enemies_per_wave * 1.1)))
            player.center = (WIDTH//2, HEIGHT//2)
            if wave % 10 == 0:
                spawn_boss()
            else:
                spawn_wave(enemies_per_wave)

        # floating texts update
        for t in floating_texts[:]:
            t["y"] += t.get("vy", -0.5)
            t["ttl"] -= 1
            if "alpha" in t:
                t["alpha"] = max(0, t.get("alpha",255) - 4)
            if t["ttl"] <= 0:
                try: floating_texts.remove(t)
                except ValueError: pass

        # lightning visuals update
        for L in lightning_lines[:]:
            L["ttl"] -= dt
            if L["ttl"] <= 0:
                try: lightning_lines.remove(L)
                except ValueError: pass

        # small dots update
        for d in small_dots[:]:
            d["y"] += d.get("vy", -0.2)
            d["ttl"] -= 1
            if d["ttl"] <= 0:
                try: small_dots.remove(d)
                except ValueError: pass

        # --- draw ---
        screen.fill(WHITE)
        pygame.draw.rect(screen, GREEN, player)

        # weapon visuals
        if weapon == "bow":
            draw_bow(player)
        else:
            mx, my = pygame.mouse.get_pos()
            angle = math.atan2(my - player.centery, mx - player.centerx)
            tip_x = player.centerx + sword_range * math.cos(angle)
            tip_y = player.centery + sword_range * math.sin(angle)
            pygame.draw.line(screen, SILVER, (player.centerx, player.centery), (tip_x, tip_y), 8)

        # draw arrows
        for a in arrows: a.draw(screen)

        # draw enemy arrows
        for ea in enemy_arrows: ea.draw(screen)

        # draw enemies
        for enemy in enemies:
            pygame.draw.rect(screen, enemy.color, enemy.rect)
            if enemy.burn_ms_left > 0:
                pygame.draw.circle(screen, ORANGE, (enemy.rect.centerx + 10, enemy.rect.top + 8), 5)
            if enemy.poison_ms_left > 0:
                pygame.draw.circle(screen, PURPLE, (enemy.rect.centerx - 10, enemy.rect.top + 8), 5)

        # draw lightning lines
        for L in lightning_lines:
            pygame.draw.line(screen, YELLOW, (L["x1"], L["y1"]), (L["x2"], L["y2"]), 3)

        # draw floating texts (respect alpha if present)
        for t in floating_texts:
            surf = FONT_SM.render(t["txt"], True, t["color"])
            screen.blit(surf, (t["x"] - surf.get_width()//2, t["y"]))

        # draw small dots
        for d in small_dots:
            pygame.draw.circle(screen, d["color"], (int(d["x"]), int(d["y"])), 4)

        # HUD
        hud = FONT_SM.render(
            f"Score: {score}  Wave: {wave}  HP: {player_hp}  Dmg: {arrow_damage}  KB Lv: {knockback_level}  Pierce Lv: {pierce_level}  Weapon: {weapon}",
            True, BLACK)
        screen.blit(hud, (12,56))
        draw_hp_bar(player_hp)

        # boss bar if present
        boss = None
        for e in enemies:
            if getattr(e, "is_boss", False):
                boss = e; break
        if boss:
            bw = int(WIDTH * 0.6)
            x = WIDTH//2 - bw//2
            y = 18
            frac = max(0, min(1, boss.hp / DEFAULTS["boss_hp"]))
            pygame.draw.rect(screen, DARK_RED, (x,y,bw,18))
            pygame.draw.rect(screen, GREEN, (x,y,int(bw*frac),18))
            pygame.draw.rect(screen, BLACK, (x,y,bw,18),2)
            txt = FONT_SM.render(f"Boss HP: {int(boss.hp)}", True, BLACK)
            screen.blit(txt, (WIDTH//2 - txt.get_width()//2, y + 22))

        pygame.display.flip()

    return

# --- Program entry point ---
if __name__ == "__main__":
    while True:
        # reset everything when returning to menu to ensure fresh run
        reset_game()
        # initial spawn
        spawn_wave(enemies_per_wave := DEFAULTS["enemies_per_wave_start"])
        main_menu()
        game_loop()
