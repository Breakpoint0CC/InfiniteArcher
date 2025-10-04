# game.py
# Infinite Archer - Final Edition
# Full game: menu, abilities, bow/sword, elements, knockback, waves, bosses.
# Optional background music: place music.mp3 in same folder.

import pygame
import random
import math
import sys
import os

pygame.init()
try:
    pygame.mixer.init()
except Exception:
    pass

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

# Attempt to load optional music (safe if missing)
MUSIC_FILE = "music.mp3"
if os.path.exists(MUSIC_FILE):
    try:
        pygame.mixer.music.load(MUSIC_FILE)
        pygame.mixer.music.set_volume(0.25)
        pygame.mixer.music.play(-1)
    except Exception:
        print("Music file found but failed to play.")
else:
    print("Music file not found, skipping music.")

# --- Colors ---
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
RED = (220, 30, 30)
GREEN = (50, 200, 50)
YELLOW = (240, 240, 50)
DARK_RED = (150, 0, 0)
BROWN = (139, 69, 19)
SILVER = (192, 192, 192)
ORANGE = (255, 140, 0)
PURPLE = (160, 32, 240)
CYAN = (0, 200, 255)
LIGHT_GRAY = (230, 230, 230)
DARK_GRAY = (40, 40, 40)

FPS = 60
clock = pygame.time.Clock()

# --- Player ---
player_size = 40
player = pygame.Rect(WIDTH//2 - player_size//2, HEIGHT//2 - player_size//2, player_size, player_size)
player_speed = 5
player_hp = 100
max_hp = 100

# --- Weapon / combat stats ---
arrow_damage = 20
sword_damage = 40
arrow_speed = 18

weapon = "bow"  # "bow" or "sword"

# Sword config
sword_cooldown = 300  # ms between swings
last_sword_attack = -9999
sword_range = 120
sword_arc_half = math.radians(45)  # +/-45deg => 90deg cone
base_knockback = 6
knockback_level = 1  # 1..5

# --- Abilities (owned flags) ---
owned_abilities = {
    "Heal +20 HP": False,
    "Damage +10": False,
    "Flame": False,
    "Poison": False,
    "Lightning": False,
    "Knockback": False  # first purchase sets owned; you can buy multiple times until level 5
}

def elements_enabled():
    return {
        "flame": owned_abilities["Flame"],
        "poison": owned_abilities["Poison"],
        "lightning": owned_abilities["Lightning"]
    }

# --- Floating visuals ---
floating_texts = []   # {x,y,txt,color,ttl,vy}
lightning_lines = []  # {x1,y1,x2,y2,ttl}
small_dots = []       # {x,y,color,ttl}

# --- Enemies ---
class Enemy:
    def __init__(self, rect, etype, is_mini=False, hp_override=None):
        # etype: "normal","fast","tank"
        self.rect = rect
        self.etype = etype
        self.is_boss = False
        self.is_mini = is_mini

        # base stats BEFORE doubling
        if etype == "normal":
            base_hp, base_speed, base_damage = 20, 2, 10
            color = RED
        elif etype == "fast":
            base_hp, base_speed, base_damage = 15, 3, 8
            color = YELLOW
        elif etype == "tank":
            base_hp, base_speed, base_damage = 40, 1, 15
            color = DARK_RED
        else:
            base_hp, base_speed, base_damage = 20, 2, 10
            color = RED

        if is_mini:
            self.color = YELLOW
            self.speed = base_speed * 2
            # minis have half of doubled HP (i.e., base_hp)
            self.hp = (base_hp * 1) if hp_override is None else hp_override
            self.damage = base_damage
        else:
            self.color = color
            # all enemy HP doubled (user previously requested)
            self.hp = (base_hp * 2) if hp_override is None else hp_override
            self.speed = base_speed
            self.damage = base_damage

        self.burn_ms_left = 0
        self.poison_ms_left = 0
        self.last_status_tick = 0
        self.summon_timer = 0  # for bosses

    def move_towards(self, tx, ty):
        dx = tx - self.rect.centerx
        dy = ty - self.rect.centery
        dist = math.hypot(dx, dy)
        if dist == 0:
            return
        spd = self.speed
        if self.poison_ms_left > 0:
            spd *= 0.5
        self.rect.x += round(spd * dx / dist)
        self.rect.y += round(spd * dy / dist)

    def apply_status(self, now_ms):
        # tick every ~1000ms
        if self.burn_ms_left > 0 or self.poison_ms_left > 0:
            if now_ms - self.last_status_tick >= 1000:
                self.last_status_tick = now_ms
                if self.burn_ms_left > 0:
                    self.hp -= 5
                    small_dots.append({"x": self.rect.centerx, "y": self.rect.top - 6, "color": ORANGE, "ttl": 30})
                    floating_texts.append({"x": self.rect.centerx, "y": self.rect.top - 18, "txt": "-5", "color": ORANGE, "ttl": 60, "vy": -0.6})
                    self.burn_ms_left = max(0, self.burn_ms_left - 1000)
                if self.poison_ms_left > 0:
                    self.hp -= 5
                    small_dots.append({"x": self.rect.centerx, "y": self.rect.top - 6, "color": PURPLE, "ttl": 30})
                    floating_texts.append({"x": self.rect.centerx, "y": self.rect.top - 18, "txt": "-5", "color": PURPLE, "ttl": 60, "vy": -0.6})
                    self.poison_ms_left = max(0, self.poison_ms_left - 1000)
        else:
            self.last_status_tick = now_ms

# Arrow projectile
class Arrow:
    def __init__(self, x, y, tx, ty):
        self.rect = pygame.Rect(0,0,30,6)
        dx = tx - x; dy = ty - y
        dist = math.hypot(dx, dy)
        if dist == 0:
            dist = 1
        self.vx = arrow_speed * dx / dist
        self.vy = arrow_speed * dy / dist
        self.angle = math.atan2(dy, dx)
        # put arrow a little in front of player
        self.rect.center = (x + dx*0.18, y + dy*0.18)

    def update(self):
        self.rect.x += self.vx
        self.rect.y += self.vy
        return screen.get_rect().colliderect(self.rect)

    def draw(self, surf):
        surf_arrow = pygame.Surface((30,6), pygame.SRCALPHA)
        surf_arrow.fill(BLACK)
        rot = pygame.transform.rotate(surf_arrow, -math.degrees(self.angle))
        surf.blit(rot, (self.rect.x, self.rect.y))

# --- Game state ---
enemies = []
arrows = []
wave = 1
enemies_per_wave = 5  # initial number of enemies in wave 1
score = 0

# spawn wave (number of enemies multiplies each wave)
def spawn_wave(count):
    global enemies
    enemies = []
    for _ in range(int(count)):
        side = random.choice(["top","bottom","left","right"])
        etype = random.choice(["normal", "fast", "tank"])
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
    boss = Enemy(rect, "tank", is_mini=False, hp_override=2000)  # 2000 HP boss
    boss.is_boss = True
    boss.color = (100, 10, 60)
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

# apply lightning chains
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
            floating_texts.append({"x": e.rect.centerx, "y": e.rect.top - 12, "txt": f"-{dmg}", "color": YELLOW, "ttl": 60, "vy": -0.6})
            lightning_lines.append({"x1": ox, "y1": oy, "x2": e.rect.centerx, "y2": e.rect.centery, "ttl": 350})
            nearby += 1

# handle arrow hit
def handle_arrow_hit(enemy):
    global score
    enemy.hp -= arrow_damage
    floating_texts.append({"x": enemy.rect.centerx, "y": enemy.rect.top - 12, "txt": f"-{arrow_damage}", "color": RED, "ttl": 60, "vy": -0.6})
    now = pygame.time.get_ticks()
    if owned_abilities["Flame"]:
        enemy.burn_ms_left = 3000
        enemy.last_status_tick = now - 1000
    if owned_abilities["Poison"]:
        enemy.poison_ms_left = 3000
        enemy.last_status_tick = now - 1000
    if owned_abilities["Lightning"]:
        lightning_lines.append({"x1": enemy.rect.centerx, "y1": enemy.rect.centery, "x2": enemy.rect.centerx, "y2": enemy.rect.centery, "ttl": 250})
        apply_lightning_chain(enemy, arrow_damage)

# handle sword attack instant
def handle_sword_attack(mx, my):
    global enemies, score
    angle_to_mouse = math.atan2(my - player.centery, mx - player.centerx)
    kb = base_knockback * knockback_level
    for enemy in enemies[:]:
        ex = enemy.rect.centerx - player.centerx
        ey = enemy.rect.centery - player.centery
        dist = math.hypot(ex, ey)
        if dist <= sword_range:
            enemy_angle = math.atan2(ey, ex)
            diff = abs((enemy_angle - angle_to_mouse + math.pi) % (2*math.pi) - math.pi)
            if diff <= sword_arc_half:
                enemy.hp -= sword_damage
                floating_texts.append({"x": enemy.rect.centerx, "y": enemy.rect.top - 12, "txt": f"-{sword_damage}", "color": RED, "ttl": 60, "vy": -0.6})
                if dist != 0:
                    nx = int(kb * (ex / dist))
                    ny = int(kb * (ey / dist))
                    enemy.rect.x += nx
                    enemy.rect.y += ny
                now = pygame.time.get_ticks()
                if owned_abilities["Flame"]:
                    enemy.burn_ms_left = 3000
                    enemy.last_status_tick = now - 1000
                if owned_abilities["Poison"]:
                    enemy.poison_ms_left = 3000
                    enemy.last_status_tick = now - 1000
                if owned_abilities["Lightning"]:
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

# --- UI / Menus ---
FONT_LG = pygame.font.SysFont(None, 84)
FONT_MD = pygame.font.SysFont(None, 44)
FONT_SM = pygame.font.SysFont(None, 28)

def draw_text_centered(font, text, y, color=BLACK):
    surf = font.render(text, True, color)
    screen.blit(surf, (WIDTH//2 - surf.get_width()//2, y))

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
        items = list(owned_abilities.keys())
        start_x = WIDTH//2 - 420
        start_y = 160
        gap_x = 320
        gap_y = 100
        for i, key in enumerate(items):
            x = start_x + (i%2) * gap_x
            y = start_y + (i//2) * gap_y
            rect = pygame.Rect(x, y, 300, 72)
            owned = owned_abilities[key]
            bg = LIGHT_GRAY if not owned else (200,200,200)
            pygame.draw.rect(screen, bg, rect)
            pygame.draw.rect(screen, BLACK, rect, 2)
            label = FONT_SM.render(key if key!="Knockback" else f"Knockback Lv {knockback_level}", True, BLACK)
            screen.blit(label, (rect.x + 12, rect.y + 20))
            if owned:
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
    global player_hp, arrow_damage, knockback_level
    # Build available list excluding already-owned abilities (Knockback allowed until level 5)
    avail = []
    if not owned_abilities["Heal +20 HP"]:
        avail.append("Heal +20 HP")
    if not owned_abilities["Damage +10"]:
        avail.append("Damage +10")
    if not owned_abilities["Flame"]:
        avail.append("Flame")
    if not owned_abilities["Poison"]:
        avail.append("Poison")
    if not owned_abilities["Lightning"]:
        avail.append("Lightning")
    if knockback_level < 5:
        avail.append("Knockback")

    if len(avail) == 0:
        return

    if len(avail) == 1:
        choices = avail.copy()
    else:
        choices = random.sample(avail, min(2, len(avail)))

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
            display_label = label if label != "Knockback" else "Knockback +1"
            screen.blit(FONT_MD.render(display_label, True, BLACK), (rect.x+12, rect.y+18))
        pygame.display.flip()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                for rect, label in buttons:
                    if rect.collidepoint(mx,my):
                        # Apply selection
                        if label == "Heal +20 HP":
                            player_hp = min(max_hp, player_hp + 20)
                            owned_abilities[label] = True
                        elif label == "Damage +10":
                            arrow_damage += 10
                            owned_abilities[label] = True
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
                        picking = False
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                picking = False
        clock.tick(FPS)

# HP bar draw
def draw_hp_bar(hp):
    w, h = 300, 28
    x, y = 12, 12
    pygame.draw.rect(screen, DARK_GRAY, (x, y, w, h))
    pygame.draw.rect(screen, GREEN, (x, y, int(w * (hp / max_hp)), h))
    pygame.draw.rect(screen, BLACK, (x, y, w, h), 2)

# initial spawn
spawn_wave(enemies_per_wave)

# Main game loop
def game_loop():
    global weapon, last_sword_attack, arrows, enemies, wave, enemies_per_wave, score, player_hp, knockback_level

    running = True
    wave_cleared = False
    countdown = 0

    while running:
        dt = clock.tick(FPS)
        now_ms = pygame.time.get_ticks()

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    running = False
                if ev.key == pygame.K_1:
                    weapon = "bow"
                if ev.key == pygame.K_2:
                    weapon = "sword"
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                mx, my = pygame.mouse.get_pos()
                if weapon == "bow":
                    arrows.append(Arrow(player.centerx, player.centery, mx, my))
                elif weapon == "sword":
                    if now_ms - last_sword_attack >= sword_cooldown:
                        last_sword_attack = now_ms
                        handle_sword_attack(mx, my)

        # Movement
        keys = pygame.key.get_pressed()
        if keys[pygame.K_w]: player.y -= player_speed
        if keys[pygame.K_s]: player.y += player_speed
        if keys[pygame.K_a]: player.x -= player_speed
        if keys[pygame.K_d]: player.x += player_speed
        player.clamp_ip(screen.get_rect())

        # Update arrows
        for a in arrows[:]:
            alive = a.update()
            if not alive:
                try: arrows.remove(a)
                except ValueError: pass

        # Update enemies
        for enemy in enemies[:]:
            if getattr(enemy, "is_boss", False):
                boss_try_summon(enemy)

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
                    print("Game Over. Score:", score)
                    running = False
                continue

            # arrow collisions
            for a in arrows[:]:
                if enemy.rect.colliderect(a.rect):
                    handle_arrow_hit(enemy)
                    try:
                        if a in arrows: arrows.remove(a)
                    except ValueError: pass
                    break

        # Wave clear
        if not enemies:
            ability_choice_between_waves()
            # 5-second countdown
            for s in range(5, 0, -1):
                screen.fill(WHITE)
                txt = FONT_LG.render(f"Next Wave in {s}", True, BLACK)
                screen.blit(txt, (WIDTH//2 - txt.get_width()//2, HEIGHT//2 - txt.get_height()//2))
                draw_hp_bar(player_hp)
                pygame.display.flip()
                pygame.time.delay(1000)
            # increment wave and multiply enemy count
            wave += 1
            enemies_per_wave = max(1, int(enemies_per_wave * 1.25))
            spawn_wave(enemies_per_wave)

        # Update floating texts
        for t in floating_texts[:]:
            t["y"] += t.get("vy", -0.5)
            t["ttl"] -= 1
            if t["ttl"] <= 0:
                try: floating_texts.remove(t)
                except ValueError: pass

        # Update lightning visuals
        for L in lightning_lines[:]:
            L["ttl"] -= dt
            if L["ttl"] <= 0:
                try: lightning_lines.remove(L)
                except ValueError: pass

        # Update small dots
        for d in small_dots[:]:
            d["ttl"] -= 1
            if d["ttl"] <= 0:
                try: small_dots.remove(d)
                except ValueError: pass

        # Draw
        screen.fill(WHITE)
        pygame.draw.rect(screen, GREEN, player)

        # Weapon visuals: bow or sword line
        if weapon == "bow":
            # Static simple bow (curved) + static string
            bow_length = 60
            arc_rect = pygame.Rect(player.centerx - 12, player.centery - bow_length, 24, bow_length * 2)
            pygame.draw.arc(screen, BROWN, arc_rect, math.radians(270), math.radians(90), 4)
            top = (player.centerx + 4, player.centery - int(bow_length * 0.9))
            bottom = (player.centerx + 4, player.centery + int(bow_length * 0.9))
            pygame.draw.line(screen, BLACK, top, bottom, 2)
        else:
            mx, my = pygame.mouse.get_pos()
            angle = math.atan2(my - player.centery, mx - player.centerx)
            tip_x = player.centerx + sword_range * math.cos(angle)
            tip_y = player.centery + sword_range * math.sin(angle)
            pygame.draw.line(screen, SILVER, (player.centerx, player.centery), (tip_x, tip_y), 8)

        # Draw arrows
        for a in arrows:
            a.draw(screen)

        # Draw enemies
        for enemy in enemies:
            pygame.draw.rect(screen, enemy.color, enemy.rect)
            # status dots
            if enemy.burn_ms_left > 0:
                pygame.draw.circle(screen, ORANGE, (enemy.rect.centerx + 10, enemy.rect.top + 8), 5)
            if enemy.poison_ms_left > 0:
                pygame.draw.circle(screen, PURPLE, (enemy.rect.centerx - 10, enemy.rect.top + 8), 5)

        # Draw lightning lines
        for L in lightning_lines:
            pygame.draw.line(screen, YELLOW, (L["x1"], L["y1"]), (L["x2"], L["y2"]), 3)

        # Draw floating texts
        for t in floating_texts:
            surf = FONT_SM.render(t["txt"], True, t["color"])
            screen.blit(surf, (t["x"] - surf.get_width()//2, t["y"]))

        # Draw small dots
        for d in small_dots:
            pygame.draw.circle(screen, d["color"], (int(d["x"]), int(d["y"])), 4)

        # HUD
        hud = FONT_SM.render(f"Score: {score}  Wave: {wave}  HP: {player_hp}  Dmg: {arrow_damage}  KB Lv: {knockback_level}  Weapon: {weapon}", True, BLACK)
        screen.blit(hud, (12, 56))
        draw_hp_bar(player_hp)

        pygame.display.flip()

    pygame.quit()
    sys.exit()

# Start the game
if __name__ == "__main__":
    main_menu()
    game_loop()
