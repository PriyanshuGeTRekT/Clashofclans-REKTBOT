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
        wait(0.3)


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
