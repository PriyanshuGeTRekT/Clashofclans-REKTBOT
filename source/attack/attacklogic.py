# attack.attacklogic - Reconstructed from attack.attacklogic.dis.txt (Pyarmor 015394, Python 3.10).
# Shared deployment primitives used by attack.dragon / attack.edragon.
#
# Note: the low-level adb.tap() adds its own random offset (x +-5, y +-2) and
# adb.tap_batch_small() adds +-2/+-2 per point (see adb module); tap_raw() is used
# for hero drops.


def closest_point_on_line_with_margin(point, line, margin):
    # Project `point` onto segment `line`, clamping the parameter so the result
    # stays at least `margin` pixels away from either endpoint.
    (x1, y1), (x2, y2) = line
    px, py = point
    dx = x2 - x1
    dy = y2 - y1
    length = (dx ** 2 + dy ** 2) ** 0.5
    if length == 0:
        return (x1, y1)
    t = ((px - x1) * dx + (py - y1) * dy) / length ** 2
    m = margin / length
    t = max(m, min(1 - m, t))
    cx = x1 + t * dx
    cy = y1 + t * dy
    return (int(cx), int(cy))


import time
import random
import math
from adb import tap, tap_raw, tap_batch_small
from attack.threeside_coords import THREE_SIDES

RAGE_SPACING_SIDE = 140
RAGE_FORWARD_1 = 160
RAGE_FORWARD_2 = 300
RAGE_RIGHT_SHIFT = 50
QUAKE_NEAR = 130
QUAKE_FAR = 250
FREEZE_FORWARD_1 = RAGE_FORWARD_2            # 300
FREEZE_FORWARD_2 = RAGE_FORWARD_2 + 120      # 420
FREEZE_SIDE = 60
EVENT_TROOP_COUNTS = {                        # defined but not referenced anywhere in this module
    'event_azuredragon': 3,
    'event_icegolem': 4,
    'event_giangiant': 5,
    'event_iceminion': 10,
    'event_firecracker': 10,
    'event_ramrider': 8,
}
EVENT_FALLBACK = 10
EVENT_TROOP_WIDTH = 280
MIN_DUMP_SPELLS_PER_SLOT = 16
MAX_DUMP_SPELLS_PER_SLOT = 32
DROP_SPEED = 0.5


def wait(t, speed=DROP_SPEED):
    # All "wait(x)" delays are scaled by DROP_SPEED: real sleep = x * 0.5 s.
    time.sleep(t * speed)


# RECON: these four are written with STORE_GLOBAL at module level (i.e. a
# module-scope `global` declaration); semantically identical to plain assignment.
_HERO_TAP_DELAY_ENABLED = False
_HERO_TAP_DELAY_SECONDS = 1
_AIR_TROOP_WIDTH_ENABLED = False
_AIR_TROOP_WIDTH = 300


def set_attack_runtime_settings(config=None):
    global _HERO_TAP_DELAY_ENABLED, _HERO_TAP_DELAY_SECONDS, _AIR_TROOP_WIDTH_ENABLED, _AIR_TROOP_WIDTH
    cfg = config
    _HERO_TAP_DELAY_ENABLED = False
    _HERO_TAP_DELAY_SECONDS = 1
    _AIR_TROOP_WIDTH_ENABLED = False
    _AIR_TROOP_WIDTH = 300
    if not isinstance(cfg, dict):
        return None
    _HERO_TAP_DELAY_ENABLED = bool(cfg.get('HERO_TAP_DELAY_ENABLED', False))
    delay = int(cfg.get('HERO_TAP_DELAY_SECONDS', 1) or 1)
    _HERO_TAP_DELAY_SECONDS = max(1, min(15, delay))
    _AIR_TROOP_WIDTH_ENABLED = bool(cfg.get('AIR_TROOP_WIDTH_ENABLED', False))
    width = int(cfg.get('AIR_TROOP_WIDTH', 300) or 300)
    _AIR_TROOP_WIDTH = max(50, min(500, width))


def wait_before_retap(default_seconds):
    # Delay before hero ability re-tap. wait() halves the value, so with the
    # user option enabled the real delay is exactly HERO_TAP_DELAY_SECONDS.
    if _HERO_TAP_DELAY_ENABLED:
        wait(_HERO_TAP_DELAY_SECONDS * 2)
    else:
        wait(default_seconds)


def get_troop_drop_width(default_width):
    if _AIR_TROOP_WIDTH_ENABLED:
        return _AIR_TROOP_WIDTH
    return default_width


def jitter(x, y):
    # Defined but not called by any attack module reconstructed here.
    dx = random.randint(-7, 6)
    dy = random.randint(-4, 5)
    return (x + dx, y + dy)


def closest_side_midpoint(th_pos, sides):
    tx, ty = th_pos
    best = None
    best_dist = 1000000000.0
    for p1, p2 in sides:
        mx = (p1[0] + p2[0]) // 2
        my = (p1[1] + p2[1]) // 2
        d = (mx - tx) ** 2 + (my - ty) ** 2
        if d < best_dist:
            best_dist = d
            best = (mx, my)
    return best


def closest_side_index(th_pos, sides):
    tx, ty = th_pos
    best_idx = 0
    best_dist = 1000000000.0
    for idx, (p1, p2) in enumerate(sides):
        mx = (p1[0] + p2[0]) // 2
        my = (p1[1] + p2[1]) // 2
        d = (mx - tx) ** 2 + (my - ty) ** 2
        if d < best_dist:
            best_dist = d
            best_idx = idx
    return best_idx


def adjacent_side(idx):
    return (idx + 1) % len(THREE_SIDES)


def build_line_points(side_line, center, width, count):
    # `count` points evenly spread along the side's direction over a span of
    # `width` px centred on `center`.
    w = width
    c = center
    n = count
    if n <= 0:
        return []
    if n == 1:
        return [c]
    (x1, y1), (x2, y2) = side_line
    dx = x2 - x1
    dy = y2 - y1
    length = (dx ** 2 + dy ** 2) ** 0.5
    if length == 0:
        return []
    ux = dx / length
    uy = dy / length
    half = w / 2
    start = -half
    step = w / (n - 1)
    points = []
    for i in range(n):
        off = start + step * i
        px = int(c[0] + ux * off)
        py = int(c[1] + uy * off)
        points.append((px, py))
    return points


def build_direction_vectors(start, target):
    sx, sy = start
    tx, ty = target
    dx = tx - sx
    dy = ty - sy
    length = math.hypot(dx, dy) or 1
    fx = dx / length
    fy = dy / length
    side_x = -fy
    side_y = fx
    return ((fx, fy), (side_x, side_y))


def offset_point(origin, forward, side, f_dist, s_dist):
    s = s_dist
    f = f_dist
    ox, oy = origin
    fx, fy = forward
    sx, sy = side
    return (int(ox + fx * f + sx * s), int(oy + fy * f + sy * s))


def deploy_troop(tab_pos, coords):
    tap(*tab_pos)
    wait(0.1)
    tap_batch_small(coords)


def deploy_heroes(tabs, drop_point, hero_list):
    point = drop_point
    for hero in hero_list:
        name = hero['name']
        if name not in tabs:
            continue
        tap(*tabs[name])
        wait(0.05)
        tap_raw(point[0], point[1])
        wait(0.1)


def retap_heroes(tabs, hero_list):
    # Re-tapping a deployed hero's tab triggers its ability.
    for hero in hero_list:
        name = hero['name']
        if name in tabs:
            tap(*tabs[name])
            wait(0.1)


def choose_event_troop_side(hero_side, mode='same'):
    m = mode
    side = hero_side
    n_sides = len(THREE_SIDES)
    if m == 'same':
        return side
    if m == 'adjacent':
        return (side + 1) % n_sides
    if m == 'random':
        return random.randint(0, n_sides - 1)
    return side


def read_battle_snapshot(vision, tabs, prefixes=('troop_', 'event_', 'spell_'), log_prefix=None):
    v = vision
    prefix_label = log_prefix
    counts = {}
    tab_matches = getattr(v, 'tab_matches', {})
    frame = v.grab()
    for name, pos in tabs.items():
        if not any(name.startswith(p) for p in prefixes):
            continue
        positions = tab_matches.get(name, [pos])
        total = 0
        for p in positions:
            c = v.read_troop_count(p, frame)
            if c and c > 0:
                total += int(c)
        counts[name] = total
    if prefix_label:
        def F(prefix):
            return [f'{k[len(prefix):]}={counts[k]}' for k in sorted(counts) if k.startswith(prefix)]

        events = F('event_')
        troops = F('troop_')
        spells = F('spell_')
        print(f'[{prefix_label}] Troop/Spell Counts:')
        print(f"[{prefix_label}] EVENT: {', '.join(events) if events else '-'}")
        print(f"[{prefix_label}] TROOPS: {', '.join(troops) if troops else '-'}")
        print(f"[{prefix_label}] SPELLS: {', '.join(spells) if spells else '-'}")
    return counts


def build_dragon_spell_targets(entry, th_pos):
    # 5 rage + 5 freeze points laid out along the entry->TH axis.
    origin = entry
    forward, side = build_direction_vectors(origin, th_pos)
    targets = []
    for s in (-70, 70):
        targets.append(('rage', offset_point(origin, forward, side, RAGE_FORWARD_1, s)))
    for s in (-RAGE_SPACING_SIDE + RAGE_RIGHT_SHIFT, 0 + RAGE_RIGHT_SHIFT, RAGE_SPACING_SIDE + RAGE_RIGHT_SHIFT):
        targets.append(('rage', offset_point(origin, forward, side, RAGE_FORWARD_2, s)))
    for s in (-FREEZE_SIDE, FREEZE_SIDE):
        targets.append(('freeze', offset_point(origin, forward, side, FREEZE_FORWARD_1, s)))
    for s in (-FREEZE_SIDE, 0, FREEZE_SIDE):
        targets.append(('freeze', offset_point(origin, forward, side, FREEZE_FORWARD_2, s)))
    return targets


def deploy_dragon_spells(tabs, entry_point, th_pos, spell_counts=None):
    t = tabs
    counts = spell_counts
    targets = build_dragon_spell_targets(entry_point, th_pos)
    rage_points = [p for kind, p in targets if kind == 'rage']
    freeze_points = [p for kind, p in targets if kind == 'freeze']
    if counts is not None:
        rage_points = rage_points[:max(0, counts.get('spell_rage', 0))]
        freeze_points = freeze_points[:max(0, counts.get('spell_freeze', 0))]
    if 'spell_rage' in t and rage_points:
        tap(*t['spell_rage'])
        time.sleep(0.1)
        for x, y in rage_points:
            tap(x, y)
            time.sleep(0.15)
        if counts is not None:
            counts['spell_rage'] = max(0, int(counts.get('spell_rage', 0)) - len(rage_points))
    if 'spell_freeze' in t and freeze_points:
        tap(*t['spell_freeze'])
        time.sleep(0.1)
        for x, y in freeze_points:
            tap(x, y)
            time.sleep(0.15)
        if counts is not None:
            counts['spell_freeze'] = max(0, int(counts.get('spell_freeze', 0)) - len(freeze_points))


def find_siege_tab(tabs):
    for name, pos in tabs.items():
        if name.startswith('siege_'):
            return (name, pos)
    return None


def deploy_siege_if_present(tabs, drop_point, vision=None):
    v = vision
    siege = find_siege_tab(tabs)
    if not siege:
        return False
    name, pos = siege
    if v:
        v.cached_siege_tab = pos
    tap(*pos)
    time.sleep(0.1)
    tap(*drop_point)
    time.sleep(0.1)
    return True


def dump_remaining_spells_on_th(vision, tabs, th_pos, spell_counts=None):
    # Every remaining spell of every type is dropped directly on the Town Hall.
    th = th_pos
    counts = spell_counts
    v = vision
    if not th or not counts:
        return None
    tx, ty = th
    tab_matches = getattr(v, 'tab_matches', {}) if v else {}
    for name, pos in tabs.items():
        if not name.startswith('spell_'):
            continue
        remaining = int(counts.get(name, 0) or 0)
        if remaining <= 0:
            continue
        if remaining > MIN_DUMP_SPELLS_PER_SLOT:
            per_slot = random.randint(MIN_DUMP_SPELLS_PER_SLOT, min(remaining, MAX_DUMP_SPELLS_PER_SLOT))
        else:
            per_slot = min(remaining, MAX_DUMP_SPELLS_PER_SLOT)
        remaining = min(remaining, per_slot)
        positions = tab_matches.get(name, [pos])
        slots = []
        for p in positions:
            c = v.read_troop_count(p) if v else None
            if c and c > 0:
                slots.append((p, int(c)))
        if not slots:
            slots = [(pos, remaining)]
        used = 0
        for p, c in slots:
            if remaining <= 0:
                break
            n = min(remaining, int(c), per_slot)
            if n <= 0:
                continue
            tap(*p)
            time.sleep(0.2)
            for _ in range(n):
                tap(tx, ty)
                time.sleep(0.25)
            remaining -= n
            used += n
        counts[name] = max(0, int(counts.get(name, 0) or 0) - used)


def dump_remaining_troops(tabs, vision, side_line, center, troop_counts=None, exclude_names=None, width=280):
    counts = troop_counts
    excluded = set(exclude_names or [])
    dumped = []
    for name, tab_pos in tabs.items():
        if not name.startswith('troop_'):
            continue
        if name in excluded:
            continue
        ocr = vision.read_troop_count(tab_pos)
        if ocr is not None:
            remaining = ocr
            if counts is not None and name in counts:
                counts[name] = ocr
        elif counts is not None and name in counts:
            remaining = counts[name]
        else:
            remaining = None
        if not remaining or remaining <= 0:
            continue
        points = build_line_points(side_line=side_line, center=center, width=width, count=int(remaining))
        n = int(remaining)
        deploy_troop(tab_pos, points[:n])
        if counts is not None and name in counts:
            counts[name] = max(0, int(counts.get(name, 0)) - n)
        dumped.append(name)
        wait(0.3)
    if dumped:                                          # whatever the game refused: try again
        redeploy_missing(vision, tabs, dumped, side_line, center, width, counts)


def quake_targets(hero_pos, th_pos):
    th = th_pos
    hx, hy = hero_pos
    tx, ty = th
    dx = tx - hx
    dy = ty - hy
    dist = math.hypot(dx, dy)
    if dist == 0:
        return []
    dx /= dist
    dy /= dist
    return [
        th,
        (int(hx + dx * QUAKE_NEAR), int(hy + dy * QUAKE_NEAR)),
        (int(hx + dx * QUAKE_FAR), int(hy + dy * QUAKE_FAR)),
    ]


def deploy_quakes(tab_pos, targets):
    pts = targets
    tap(*tab_pos)
    wait(0.4)
    x0, y0 = pts[0]
    for _ in range(3):
        tap(x0, y0)
        wait(0.18)
    for x, y in pts[1:]:
        for _ in range(4):
            tap(x, y)
            wait(0.18)


def deploy_event_troops(tabs, vision, side_line, snapshot_counts=None):
    line = side_line
    snap = snapshot_counts
    (x1, y1), (x2, y2) = line
    for name, tab_pos in tabs.items():
        if not name.startswith('event_'):
            continue
        if snap is not None and name in snap:
            count = snap[name]
        else:
            count = vision.read_troop_count(tab_pos)
        if not count or count <= 0:
            count = EVENT_FALLBACK
            print(f'[EVENT] {name} OCR failed, using fallback: {count}')
        else:
            print(f'[EVENT] {name}={count}')
        points = build_line_points(side_line=line, center=((x1 + x2) // 2, (y1 + y2) // 2),
                                   width=EVENT_TROOP_WIDTH, count=count)
        deploy_troop(tab_pos, points)
        if snap is not None and name in snap:
            snap[name] = max(0, int(snap.get(name, 0)) - int(count))


def deploy_event_troops_air(tabs, vision, side_line, snapshot_counts=None):
    line = side_line
    snap = snapshot_counts
    (x1, y1), (x2, y2) = line
    mid = ((x1 + x2) // 2, (y1 + y2) // 2)
    for name, tab_pos in tabs.items():
        if not name.startswith('event_'):
            continue
        if snap is not None and name in snap:
            count = snap[name]
        else:
            count = vision.read_troop_count(tab_pos)
        if not count or count <= 0:
            count = EVENT_FALLBACK
            print(f'[EVENT] {name} OCR failed, using fallback: {count}')
        else:
            print(f'[EVENT] {name}={count}')
        points = build_line_points(side_line=line, center=mid, width=EVENT_TROOP_WIDTH, count=count)
        deploy_troop(tab_pos, points)
        if snap is not None and name in snap:
            snap[name] = max(0, int(snap.get(name, 0)) - int(count))
        wait(0.3)


# ---------------------------------------------------------------------------------------------
# FIX (reported on MuMu Player, 17 Nov): taps that land inside the red no-deploy zone are ignored
# by the game. When a base reaches over the fixed deploy edge, most of the air line was ignored and
# the troops only went in with the end-of-attack dump, 10+ s later and alone - some never.
# After a line is dropped, read what is still in the troop bar and drop it again right away,
# further out from the base, then on the other sides.
BASE_CENTRE = (800, 430)
SCREEN_MARGIN = 12
HUD_BOXES = (                       # battle screen areas a tap must never reach (1600 x 900)
    (0, 0, 340, 255),               # attacker name and available loot
    (690, 0, 910, 100),             # battle timer
    (1225, 0, 1600, 215),           # own resources
    (0, 600, 235, 720),             # End Battle / Surrender
    (215, 625, 485, 720),           # Boost Heroes (next to End Battle before the first troop; seen 22 Nov)
    (1320, 560, 1600, 720),         # damage and stars
    (0, 712, 1600, 900),            # troop bar
)
SMALL_SHIFT = 30                    # px further out: the map usually goes on a little past the edge
MIN_TH_DISTANCE = 140               # a deploy point this close to the Town Hall is a misread red line


def tap_is_safe(point):
    x, y = point
    if not (SCREEN_MARGIN <= x <= 1600 - SCREEN_MARGIN and SCREEN_MARGIN <= y <= 900 - SCREEN_MARGIN):
        return False
    return not any(x1 <= x <= x2 and y1 <= y <= y2 for x1, y1, x2, y2 in HUD_BOXES)


def shift_line_outward(side_line, distance):
    """The side moved `distance` px away from the base (perpendicular to it)."""
    (x1, y1), (x2, y2) = side_line
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / length, dx / length
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    cx, cy = BASE_CENTRE
    if math.hypot(mx + nx - cx, my + ny - cy) < math.hypot(mx - cx, my - cy):
        nx, ny = -nx, -ny
    return ((x1 + nx * distance, y1 + ny * distance), (x2 + nx * distance, y2 + ny * distance))


def _safe_points(side_line, center, width, count):
    pts = [p for p in build_line_points(side_line, center, width, count) if tap_is_safe(p)]
    if not pts:
        pts = [p for p in build_line_points(side_line, center, width, 9) if tap_is_safe(p)]
    if not pts:
        return []
    return (pts * count)[:count]


def _red_line_points(vision, side_line, center, width, count, th_pos):
    """Points on the detected red line (attack/redline.py) of this side, or []."""
    try:
        from attack import redline
        from attack.geometry import FOUR_SIDES
        depths = redline.detect(vision.grab())
    except Exception:
        return []
    if not depths:
        return []
    mid = ((side_line[0][0] + side_line[1][0]) / 2, (side_line[0][1] + side_line[1][1]) / 2)
    j = min(range(len(FOUR_SIDES)), key=lambda i: math.hypot((FOUR_SIDES[i][0][0] + FOUR_SIDES[i][1][0]) / 2 - mid[0],
                                                            (FOUR_SIDES[i][0][1] + FOUR_SIDES[i][1][1]) / 2 - mid[1]))
    if j not in depths:
        return []
    (x1, y1), (x2, y2) = FOUR_SIDES[j]
    length = math.hypot(x2 - x1, y2 - y1) or 1.0
    t0 = ((center[0] - x1) * (x2 - x1) + (center[1] - y1) * (y2 - y1)) / length ** 2
    span = width / length
    ts = [min(1.0, max(0.0, t0 - span / 2 + span * i / max(1, count - 1))) for i in range(count)] if count > 1 else [t0]
    pts = []
    for t in ts:
        x, y = redline.point_on_line(j, depths[j], t)
        p = (int(x), int(y))
        if tap_is_safe(p) and (th_pos is None or math.hypot(p[0] - th_pos[0], p[1] - th_pos[1]) >= MIN_TH_DISTANCE):
            pts.append(p)
    return (pts * count)[:count] if pts else []


def redeploy_missing(vision, tabs, names, side_line, center, width, counts=None, th_pos=None):
    """Drop again whatever of `names` is still in the troop bar. Every try first reads the bar, so
    it stops as soon as everything is in:
      1. the same line again (a missed tap or a card that was not selected);
      2. this side's detected red line (when the base reaches over the usual line);
      3. a little further out on this side;
      4. the other sides."""
    th_pos = th_pos or getattr(vision, 'last_th_pos', None)
    plain = lambda line, c: (lambda n: _safe_points(line, c, width, n))                  # noqa: E731
    others = [s for s in THREE_SIDES if [tuple(p) for p in s] != [tuple(p) for p in side_line]]
    plans = [('again on the same line', plain(side_line, center)),
             ('on the red line of this side', lambda n: _red_line_points(vision, side_line, center, width, n, th_pos))]
    out = shift_line_outward(side_line, SMALL_SHIFT)
    plans.append(('a little further out', plain(out, closest_point_on_line_with_margin(center, out, width / 2))))
    for s in others:
        plans.append(('on another side', plain(s, closest_point_on_line_with_margin(th_pos or BASE_CENTRE, s, width / 2))))
    for label, make_points in plans:
        screen = vision.grab()
        left = {}
        for name in names:
            if name in tabs:
                n = vision.read_troop_count(tabs[name], screen=screen)
                if n:
                    left[name] = int(n)
        if not left:
            return
        print('[DEPLOY] Not deployed yet: ' + ', '.join(f'{v} {k.split("_", 1)[1]}' for k, v in left.items())
              + f' - dropping {label}')
        for name, n in left.items():
            pts = make_points(n)
            if pts:
                deploy_troop(tabs[name], pts)
            if counts is not None and name in counts:
                counts[name] = 0
        wait(0.5)
    left = [k for k in names if k in tabs and vision.read_troop_count(tabs[k])]
    if left:
        print('[DEPLOY] Still not deployed after every try: ' + ', '.join(left))


def sweep_leftover_troops(vision):
    """After any strategy (CSV scripts, Loot Maxxing, ...): nothing that could fight stays in the
    troop bar. Every troop / event troop card that still shows a count is dropped from the side
    nearest the Town Hall (further out first, then the other sides)."""
    if not vision.is_in_battle():
        return
    tabs = vision.detect_tabs()
    names = [n for n in tabs if n.startswith(('troop_', 'event_'))]
    if not names:
        return
    th_pos = vision.last_th_pos or BASE_CENTRE
    side = THREE_SIDES[closest_side_index(th_pos, THREE_SIDES)]
    redeploy_missing(vision, tabs, names, side, closest_point_on_line_with_margin(th_pos, side, 160), 320)



# ------------------------------------------------------------------ cards beyond the bar's right edge
# UPDATE (seen 20 Nov): with 13 or more cards the battle bar no longer shrinks, it scrolls. The last
# cards (usually spells: a Revive in the army where this was seen) sit beyond the right edge behind a
# small arrow, are never detected and so were never played.
BAR_FULL_X = 1400                    # a card centred right of this: the bar is filled up to the edge
BAR_SCROLL_LEFT = (1300, 812, 300, 812, 500)
BAR_SCROLL_BACK = (300, 812, 1300, 812, 500)
HIDDEN_SPELL_MAX_TAPS = 11
HIDDEN_TROOP_MAX_TAPS = 12


def bar_is_full(vision, tabs):
    """True when a detected card reaches the right end of the battle bar (more may follow)."""
    xs = [p[0] for p in (tabs or {}).values()]
    for positions in (getattr(vision, 'tab_matches', {}) or {}).values():
        xs += [p[0] for p in positions]
    return bool(xs) and max(xs) >= BAR_FULL_X


def deploy_hidden_cards(vision, tabs, th_pos, point_for=None, log_prefix='ATTACK', troop_point=None):
    """Scroll the battle bar to its end and play what was beyond the right edge.

    `tabs` is what was detected before scrolling. Spells are cast on `point_for(name)` (default: the
    Town Hall, or the middle of the map). Troop, event and hero cards, and cards without a picture that
    still show a count (seen 21 Nov: the Clan Castle troops), are dropped on `troop_point` (default: the
    side nearest the Town Hall). Returns the number of taps that played something."""
    from adb import swipe
    if not bar_is_full(vision, tabs):
        return 0
    target = th_pos or BASE_CENTRE
    if troop_point is None:
        side = THREE_SIDES[closest_side_index(target, THREE_SIDES)]
        troop_point = closest_point_on_line_with_margin(target, side, 160)
    troop_point = (int(troop_point[0]), int(troop_point[1]))
    known = set(tabs or {})
    others = [s for s in THREE_SIDES if closest_point_on_line_with_margin(target, s, 160) != troop_point]
    second_spot = closest_point_on_line_with_margin(target, others[0], 160) if others else troop_point
    second_spot = (int(second_spot[0]), int(second_spot[1]))

    def play(pos, n, cap, spots):
        """Tap the card and its spot n times; when the card still shows a count afterwards (the spot
        was refused, or the card is not what its picture said), try the next spot."""
        done = 0
        for spot in spots:
            tap(int(pos[0]), int(pos[1]))
            time.sleep(0.25)
            for _ in range(n):
                tap(int(spot[0]), int(spot[1]))
                time.sleep(0.25)
            done += n
            time.sleep(0.4)
            left = vision.read_troop_count(pos)
            if not left or left <= 0:
                break
            n = min(int(left), cap)
        return done

    swipe(*BAR_SCROLL_LEFT)
    time.sleep(1.0)
    played = 0
    try:
        now = vision.detect_tabs() or {}
        fresh = {k: p for k, p in now.items() if k not in known}
        counts = read_battle_snapshot(vision, fresh, prefixes=('spell_', 'troop_', 'event_'), log_prefix=None)
        for name, pos in fresh.items():
            if name.startswith('siege_'):
                continue                         # the one siege card was already handled before the scroll
            if name.startswith('spell_'):
                n = min(int(counts.get(name, 0) or 0) or 1, HIDDEN_SPELL_MAX_TAPS)
                point = (point_for(name) if point_for else None) or target
                print(f'[{log_prefix}] {n}x {name[6:]} from beyond the end of the bar')
                played += play(pos, n, HIDDEN_SPELL_MAX_TAPS, (point, troop_point))
            else:
                n = min(int(counts.get(name, 0) or 0) or 1, HIDDEN_TROOP_MAX_TAPS)
                print(f'[{log_prefix}] {n}x {name.split("_", 1)[1]} from beyond the end of the bar')
                played += play(pos, n, HIDDEN_TROOP_MAX_TAPS, (troop_point, second_spot))
        # cards no picture recognises that still show a count: unplayed, whatever they are
        try:
            from attack.lootmax import find_unknown_cards
            unknown = find_unknown_cards(vision, now, vision.grab())
        except Exception as e:
            unknown = []
            print(f'[{log_prefix}] unknown cards beyond the bar were not checked: {e.__class__.__name__}: {e}')
        for x, y, n, _kind in unknown:
            n = min(int(n), HIDDEN_TROOP_MAX_TAPS)
            print(f'[{log_prefix}] {n}x card without a picture (x={x}) from beyond the end of the bar')
            played += play((x, y), n, HIDDEN_TROOP_MAX_TAPS, (troop_point, second_spot))
    finally:
        swipe(*BAR_SCROLL_BACK)
        time.sleep(0.8)
        try:
            vision.detect_tabs()                 # card positions as the caller knows them
        except Exception:
            pass
    return played
