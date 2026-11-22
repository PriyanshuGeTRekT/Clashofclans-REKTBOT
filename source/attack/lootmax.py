# attack/lootmax.py - "50% Loot Maxxing" (new strategy, switched on with LOOTMAX_ENABLED).
#
# Tactic, taken from a replay of the strategy (11 Nov, 55% / 1 star, 451k gold, 863k elixir, 11.6k DE):
#   army  11 Electro Dragons, Queen / King / Warden / Minion Prince (+ pets), 11 Earthquakes
#         (2 Freeze, Totem and a siege were brought but never used)
#   t+0.0  all dragons in ~1 s, evenly spread round the base on THREE sides: left corner, both
#          bottom edges, right corner, just outside the outer ring (collectors / storages)
#   t+1.1  heroes on the fourth side, the two top edges, ~0.6 s apart: Queen on one top edge, King
#          near the top corner, Warden and Minion Prince on the other top edge
#   t+3.5  all Earthquakes stacked on the Town Hall / core within ~1.5 s
#   ~t+10  50%+ and 1 star reached -> End Battle a few seconds later (the replay ended at 55%)
# The aim is the outer-ring loot plus the 1-star bonus in ~15 s instead of a full 3-minute attack.
#
# Every attack is varied so no two look the same: sweep direction and spacing, tap spots, which top
# edge the Queen / Warden take, all pauses (drawn around the replay's own rhythm), Earthquake spots
# scattered over the Town Hall, hero abilities at random moments in random order, and the exit point
# (a random target between LOOTMAX_TARGET_DAMAGE and +6 %, then a short pause). This makes the bot
# look less mechanical; it cannot make it undetectable.
import math
import random
import time

from adb import tap, tap_raw
from attack.attacklogic import find_siege_tab, read_battle_snapshot, set_attack_runtime_settings
from attack.geometry import FOUR_SIDES

NAME = 'lootmax'
FIELD = (40, 30, 1560, 690)          # deployable screen area (above the troop bar)
MAIN_TROOPS = ('troop_edragon', 'troop_dragon', 'troop_super_dragon')
HERO_ORDER = ('hero_queen', 'hero_king', 'hero_warden', 'hero_prince', 'hero_rc', 'hero_duke')
# Spells that go on the Town Hall / core: the replay's 11 Earthquakes; Lightning works the same way for
# armies built around it. Freeze, Totem (and the siege) were carried but never used in the replay, so
# support spells are kept, not cast.
CORE_SPELLS = ('spell_equake', 'spell_zap')
# The rest of the army is used too (the replay never got to it before ending at 55%): the siege leads the
# heroes in, Rage goes on the heroes' path, Freeze and Totem on the core once the heroes close in,
# Revive over the heroes later, anything else on the core at the end.
# Heroic Spell (Clash of Titans update): less damage taken, more speed, ground troops walk through walls
# -> on the heroes' path like Rage (its speed boost does not stack with Rage/Haste; the fastest wins).
PATH_SPELLS = ('spell_heroic', 'spell_rage', 'spell_haste', 'spell_heal', 'spell_jump', 'spell_invis')
CORE_SUPPORT_SPELLS = ('spell_freeze', 'spell_totem', 'spell_iceblock', 'spell_poison')
LATE_SPELLS = ('spell_revive', 'spell_recall', 'spell_overgrowth')
REPLAY_ARMY = ('11 Electro Dragons; Archer Queen, Barbarian King, Grand Warden, Minion Prince (with pets); '
               '11 Earthquake, 2 Freeze, 1 Totem; any siege machine')
DEFAULT_TARGET = 50
MAX_BATTLE_SECONDS = 170


def _log(msg):
    print(f'[LOOTMAX] {msg}')


# ------------------------------------------------------------------ randomness helpers
def _pause(lo, hi, human=True):
    """Sleep a random time in [lo, hi] s (skewed towards the middle, like a hand)."""
    t = random.triangular(lo, hi) if human else (lo + hi) / 2
    time.sleep(max(0.0, t))


def _clamp(p):
    x1, y1, x2, y2 = FIELD
    return int(min(max(p[0], x1), x2)), int(min(max(p[1], y1), y2))


def _lerp(a, b, t):
    return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t


def _wobble(p, r, human=True):
    if not human or r <= 0:
        return _clamp(p)
    return _clamp((p[0] + random.gauss(0, r / 2), p[1] + random.gauss(0, r / 2.5)))


# ------------------------------------------------------------------ geometry
# FOUR_SIDES (attack/geometry.py): 0 bottom-left, 1 top-left, 2 top-right, 3 bottom-right; each side
# is ((x1, y1), (x2, y2)). Corners: left = between 0 and 1, top = between 1 and 2, right = 2 / 3.
LEFT_CORNER = _lerp(FOUR_SIDES[0][1], FOUR_SIDES[1][0], 0.5)
TOP_CORNER = _lerp(FOUR_SIDES[1][1], FOUR_SIDES[2][0], 0.5)
RIGHT_CORNER = _lerp(FOUR_SIDES[2][1], FOUR_SIDES[3][0], 0.5)


def _dragon_path(human=True):
    """Polyline round the left corner, both bottom edges and the right corner (the bottom corner
    itself is under the troop bar, so the path is split in two runs)."""
    top_left_start = 0.30 + (random.uniform(-0.06, 0.06) if human else 0)      # fraction up the edge
    top_right_end = 0.70 + (random.uniform(-0.06, 0.06) if human else 0)
    left_run = [_lerp(LEFT_CORNER, FOUR_SIDES[1][1], top_left_start), LEFT_CORNER, FOUR_SIDES[0][0]]
    right_run = [FOUR_SIDES[3][1], RIGHT_CORNER, _lerp(FOUR_SIDES[2][0], RIGHT_CORNER, top_right_end)]
    return [left_run, right_run]


def _sample_runs(runs, count, human=True):
    """`count` points spread over the runs in proportion to their length, with uneven spacing."""
    def length(run):
        return sum(((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5 for a, b in zip(run, run[1:]))

    lengths = [length(r) for r in runs]
    total = sum(lengths)
    counts = [max(1, round(count * l / total)) for l in lengths]
    while sum(counts) > count:
        counts[counts.index(max(counts))] -= 1
    while sum(counts) < count:
        counts[counts.index(min(counts))] += 1
    points = []
    for run, n, run_len in zip(runs, counts, lengths):
        for i in range(n):
            f = (i + 0.5) / n
            if human:
                f = min(0.98, max(0.02, f + random.uniform(-0.35, 0.35) / n))   # uneven spacing
            d = f * run_len
            for a, b in zip(run, run[1:]):
                seg = ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
                if d <= seg or (a, b) == (run[-2], run[-1]):
                    points.append(_lerp(a, b, min(1.0, d / seg if seg else 0)))
                    break
                d -= seg
    return points


def _hero_spots(heroes, human=True):
    """Top-edge drop points: Queen on one top edge, King near the top corner, the rest on the other
    top edge (which edge is which is mirrored at random)."""
    left_edge = (FOUR_SIDES[1][0], FOUR_SIDES[1][1])    # left corner -> top
    right_edge = (FOUR_SIDES[2][1], FOUR_SIDES[2][0])   # right corner -> top
    if human and random.random() < 0.5:
        left_edge, right_edge = right_edge, left_edge
    spots = {}
    others = [h for h in heroes if h not in ('hero_queen', 'hero_king')]
    if 'hero_queen' in heroes:
        spots['hero_queen'] = _lerp(*left_edge, random.uniform(0.55, 0.78) if human else 0.66)
    if 'hero_king' in heroes:
        edge = left_edge if (not human or random.random() < 0.5) else right_edge
        spots['hero_king'] = _lerp(*edge, random.uniform(0.84, 0.95) if human else 0.9)
    for i, h in enumerate(others):
        base = 0.62 + 0.09 * i
        spots[h] = _lerp(*right_edge, min(0.95, base + (random.uniform(-0.07, 0.07) if human else 0)))
    return spots


# ------------------------------------------------------------------ cards without a picture
# New troops, Squads and spells (every game update adds some) have no picture in templates/tabs yet, so
# detect_tabs does not see them. Their cards still carry a white "xN" count in the top right corner:
# every count that belongs to no recognised card is a card to use. Order in the bar is troops and
# Squads, siege machine, heroes, spells, so a card right of a hero is a spell, the rest are troops.
COUNT_LABEL_MIN_W, COUNT_LABEL_MAX_W = 16, 78
UNKNOWN_CARD_MAX = 6


def _count_label_runs(vision, frame, tab_y):
    """(left, right) pixel columns of every white count label in the troop bar."""
    import cv2
    import numpy as np
    import fixed_points as fp
    small = getattr(vision, 'use_smallest_troop_bar_size', False)
    y_off = fp.TROOP_COUNT_Y_OFFSET_SMALL if small else fp.TROOP_COUNT_Y_OFFSET
    box_h = fp.TROOP_COUNT_BOX_HEIGHT_SMALL if small else fp.TROOP_COUNT_BOX_HEIGHT
    y2 = int(tab_y - y_off)
    y1 = max(0, y2 - box_h)
    bx1, _by1, bx2, _by2 = fp.TROOP_BAR_REGION
    band = frame[y1:y2 + 24, bx1:bx2]
    if band.size == 0:
        return []
    mask = cv2.inRange(cv2.cvtColor(band, cv2.COLOR_BGR2HSV), np.array([0, 0, 200]), np.array([180, 60, 255]))
    label_rows = y2 - y1
    # a count label is short: white that carries on below it is something else (the "!" on an empty
    # Clan Castle / siege card, the white frame round the selected card)
    cols = ((mask[:label_rows] > 0).sum(axis=0) >= 3) & ((mask[label_rows + 4:] > 0).sum(axis=0) < 3)
    runs, start, end, gap = [], None, 0, 0
    for x, on in enumerate(list(cols) + [False] * 12):
        if on:
            if start is None:
                start = x
            end, gap = x, 0
        elif start is not None:
            gap += 1
            if gap > 9:
                runs.append((bx1 + start, bx1 + end))
                start = None
    return runs


def find_unknown_cards(vision, tabs, frame):
    """[(x, y, count, kind)] for troop-bar cards no template recognised; kind is 'troop' or 'spell'."""
    known = []
    for name, pos in tabs.items():
        for p in getattr(vision, 'tab_matches', {}).get(name, [pos]):
            known.append((name, int(p[0]), int(p[1])))
    cards = [k for k in known if k[0].startswith(('troop_', 'spell_', 'event_', 'squad_'))]
    if not cards:
        return []
    ys = sorted(k[2] for k in cards)
    tab_y = ys[len(ys) // 2]
    runs = [r for r in _count_label_runs(vision, frame, tab_y)
            if COUNT_LABEL_MIN_W <= r[1] - r[0] <= COUNT_LABEL_MAX_W]
    # where a label ends relative to its card's centre, learnt from the recognised cards
    offsets = [r[1] - x for _n, x, _y in cards for r in runs if x + 5 <= (r[0] + r[1]) / 2 <= x + 85]
    if not offsets:
        return []
    offsets.sort()
    right_off = offsets[len(offsets) // 2]
    heroes = [x for n, x, _y in known if n.startswith('hero_')]
    spells = [x for n, x, _y in known if n.startswith('spell_')]
    found = []
    for _left, right in runs:
        x = right - right_off
        if any(abs(x - kx) < 58 for n, kx, _y in known if not n.startswith('siege_')):
            continue
        if any(abs(x - fx) < 58 for fx, _fy, _c, _k in found):
            continue
        count = vision.read_troop_count((x, tab_y), frame)
        if not count or count <= 0 or count > 300:
            continue
        if heroes:
            kind = 'spell' if x > max(heroes) else 'troop'
        else:
            kind = 'spell' if (spells and x > min(spells)) else 'troop'
        found.append((int(x), int(tab_y), int(count), kind))
    return found[:UNKNOWN_CARD_MAX]


# ------------------------------------------------------------------ spells go where the troops are
# FIX (22 Nov): every Rage went on one strip of the heroes' route (the line from the heroes to the
# detected Town Hall, which is often misread or left over from the previous base) while the Dragons
# fought along the other three sides. Troop spells are now aimed from where the troops were really
# dropped: the drop points are split into groups round the base, and each spell goes a little inside
# its group, towards the middle of the map.
MAP_CENTRE = (800, 430)
RAGE_DEPTH = 125                     # px inside the drop line: where troops meet the first buildings
SUPPORT_DEPTH = 215                  # Freeze and the like: just ahead of the troops
RUN_GAP = 300                        # px between two drops that are not one line of troops
TROOP_SPELLS = ('spell_rage', 'spell_haste', 'spell_heal')
_drop_log = []                       # every troop drop of the running attack (screen points)


def _inside(p, depth):
    """`p` moved `depth` px towards the middle of the map (never past it)."""
    dx, dy = MAP_CENTRE[0] - p[0], MAP_CENTRE[1] - p[1]
    dist = math.hypot(dx, dy) or 1.0
    step = min(depth, dist * 0.8)
    return p[0] + dx / dist * step, p[1] + dy / dist * step


def _troop_groups(drops, k):
    """The middle points of k groups of drop points going round the base, biggest groups first.
    The drops are first cut into runs wherever two neighbours are far apart (the bottom corner under
    the troop bar, the side left free for the heroes), so no group reaches across such a gap; the k
    groups are then shared out over the runs by their size. Empty when nothing was dropped."""
    if not drops or k <= 0:
        return []
    pts = sorted(drops, key=lambda p: math.atan2(p[1] - MAP_CENTRE[1], p[0] - MAP_CENTRE[0]))
    gaps = [math.dist(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))]
    cut = (gaps.index(max(gaps)) + 1) % len(pts)
    pts = pts[cut:] + pts[:cut]
    runs = [[pts[0]]]
    for a, b in zip(pts, pts[1:]):
        if math.dist(a, b) > RUN_GAP:
            runs.append([])
        runs[-1].append(b)
    k = min(k, len(pts))
    # share the groups out: the biggest run first, one more group where a group covers most points
    shares = [0] * len(runs)
    for _ in range(k):
        i = max(range(len(runs)), key=lambda j: len(runs[j]) / (shares[j] + 1))
        shares[i] += 1
    groups = []
    for run, n in zip(runs, shares):
        for i in range(n):
            chunk = run[i * len(run) // n:(i + 1) * len(run) // n]
            if chunk:
                groups.append((len(chunk), (sum(p[0] for p in chunk) / len(chunk),
                                            sum(p[1] for p in chunk) / len(chunk))))
    groups.sort(key=lambda g: -g[0])
    return [g[1] for g in groups]


def _spell_targets(drops, n, depth):
    """n spell targets `depth` px inside the troop groups (several spells on one group are spread
    along it instead of stacked)."""
    groups = _troop_groups(drops, n)
    if not groups:
        return []
    return [_inside(groups[i % len(groups)], depth + 70 * (i // len(groups))) for i in range(n)]


# ------------------------------------------------------------------ nothing stays in the bar
def _tap_field(p, r, human):
    """Drop on `p` (wobbled by r). A point on a button (End Battle, Boost Heroes, Next, the loot
    panel...) is not tapped: the troop stays in the bar and the leftover pass places it."""
    from attack.attacklogic import tap_is_safe
    q = _wobble(p, r, human)
    if not tap_is_safe(q):
        q = _clamp(p)
        if not tap_is_safe(q):
            return False
    tap_raw(*q)
    _drop_log.append(q)
    return True


BAR_READ_SECONDS = 8                 # how long to wait for the battle bar at the start of an attack


def _read_bar(vision):
    """The cards of the battle bar. FIX (22 Nov): one look, taken while the battle screen was still
    coming up, found no card at all; the attack then dropped nothing and waited out the whole battle.
    Now the bar is read again for up to BAR_READ_SECONDS until a troop or hero card is there."""
    tabs = {}
    start = time.time()
    tries = 0
    while True:
        tabs = vision.detect_tabs() or {}
        tries += 1
        if any(k.startswith(('troop_', 'event_', 'squad_', 'hero_')) for k in tabs):
            break
        if time.time() - start > BAR_READ_SECONDS:
            _log('the battle bar shows no troop or hero card')
            break
        if tries == 3:                           # the card size may have been judged on a bad frame
            vision._tab_scale_locked = False
        time.sleep(0.6)
    if tries > 1 and tabs:
        _log(f'battle bar read on try {tries}')
    return tabs


def _drop_leftovers(vision, tabs, unknown, th):
    """Every troop card that still shows a count is played again until the bar is empty.

    FIX (22 Nov): the troops went down in one pass and the bar was never looked at again, so a tap
    the game refused (red zone, the edge of the map, a button) left that troop in the bar for the
    whole battle: "17 dragons" regularly ended with one unused. Cards with a picture go through
    attacklogic.redeploy_missing (same line, the red line, further out, the other sides); cards
    without a picture get the same sides in turn."""
    try:
        from attack import attacklogic as al
        from attack.geometry import THREE_SIDES
        if not vision.is_in_battle():
            return
        ref = th or al.BASE_CENTRE
        side = THREE_SIDES[al.closest_side_index(ref, THREE_SIDES)]
        center = al.closest_point_on_line_with_margin(ref, side, 160)
        names = [k for k in tabs if k.startswith(('troop_', 'event_', 'squad_'))]
        if names:
            al.redeploy_missing(vision, tabs, names, side, center, 320, th_pos=ref)
        sides = [side] + [s for s in THREE_SIDES if s is not side]
        for x, y, _n, kind in unknown:
            if kind != 'troop':
                continue
            for s in sides:
                left = vision.read_troop_count((x, y))
                if not left or left <= 0:
                    break
                pts = al._safe_points(s, al.closest_point_on_line_with_margin(ref, s, 160), 320, min(int(left), 40))
                if not pts:
                    continue
                _log(f'{left} of the card without a picture (x={x}) still in the bar: dropping again')
                tap(x, y)
                time.sleep(0.2)
                for p in pts:
                    tap_raw(int(p[0]), int(p[1]))
                    time.sleep(0.1)
                time.sleep(0.5)
    except Exception as e:                       # a check, never a reason to lose the attack
        _log(f'leftover check failed: {e.__class__.__name__}: {e}')


# ------------------------------------------------------------------ the attack
def run_attack(adb, vision, active_config=None):
    cfg = active_config or {}
    set_attack_runtime_settings(cfg)
    human = bool(cfg.get('LOOTMAX_HUMANIZE', True))
    print('=== LOOTMAX ATTACK START ===')
    tabs = _read_bar(vision)
    snapshot = read_battle_snapshot(vision, tabs, prefixes=('troop_', 'event_', 'spell_', 'squad_'),
                                    log_prefix='LOOTMAX')
    del _drop_log[:]
    # the Town Hall of this base only: get_townhall_pos falls back to the previous base's position
    th = vision.find_townhall() or MAP_CENTRE
    try:
        unknown = find_unknown_cards(vision, tabs, vision.grab()) if cfg.get('LOOTMAX_USE_UNKNOWN', True) else []
    except Exception as e:                       # never let this extra stop the attack
        _log(f'unknown-card check failed: {e.__class__.__name__}: {e}')
        unknown = []
    if unknown:
        _log('cards without a picture: ' + ', '.join(f'{k} x{c} at x={x}' for x, _y, c, k in unknown))

    # 1) dragons: the whole stack, spread round three sides, ~90 ms apart
    main = next((t for t in MAIN_TROOPS if t in tabs), None)
    if main is None:
        troops = [k for k in tabs if k.startswith(('troop_', 'event_', 'squad_'))]
        main = max(troops, key=lambda k: snapshot.get(k, 0), default=None)
    if main:
        count = int(snapshot.get(main, 0) or 0) or 11
        points = _sample_runs(_dragon_path(human), count, human)
        if human and random.random() < 0.5:
            points.reverse()                     # sweep right-to-left this time
        _log(f'{count}x {main.split("_", 1)[1]} round three sides')
        tap(*tabs[main])
        _pause(0.12, 0.3, human)
        for p in points:                         # adb adds ~80 ms per tap: ~11 drops/s like the replay
            _tap_field(p, 14, human)
            _pause(0.0, 0.06, human)
    else:
        _log('no main troop found in the troop bar')

    # 1b) any other troops in the army (e.g. Dragon Riders) go round the same three sides
    # (Squads from the Clash of Titans update deploy a whole group per tap: same path as the troops;
    # event troops too)
    for extra in [k for k in tabs if k.startswith(('troop_', 'squad_', 'event_')) and k != main]:
        n = int(snapshot.get(extra, 0) or 0)
        if n <= 0:
            continue
        _pause(0.2, 0.6, human)
        _log(f'{n}x {extra.split("_", 1)[1]} round three sides')
        tap(*tabs[extra])
        _pause(0.1, 0.25, human)
        for p in _sample_runs(_dragon_path(human), n, human):
            _tap_field(p, 16, human)
            _pause(0.03, 0.12, human)

    # 1c) troop or Squad cards without a picture: same three sides
    for x, y, n, kind in unknown:
        if kind != 'troop':
            continue
        n = min(n, 40)
        _pause(0.2, 0.6, human)
        _log(f'{n}x unknown troop card (x={x}) round three sides')
        tap(x, y)
        _pause(0.1, 0.25, human)
        for p in _sample_runs(_dragon_path(human), n, human):
            _tap_field(p, 16, human)
            _pause(0.03, 0.12, human)

    # 1d) the bar is read again: whatever the game refused (a tap on a spot it does not accept leaves
    # that troop in the bar) goes in now, not after the battle
    _drop_leftovers(vision, tabs, unknown, th)

    # 2) heroes on the fourth side
    heroes = [h for h in HERO_ORDER if h in tabs]
    if human and len(heroes) > 2 and random.random() < 0.3:
        i = random.randrange(len(heroes) - 1)            # sometimes two heroes swap places in the order
        heroes[i], heroes[i + 1] = heroes[i + 1], heroes[i]
    spots = _hero_spots(heroes, human)
    _pause(0.7, 1.6, human)
    deployed = []
    siege = find_siege_tab(tabs)
    if siege and siege[0] == 'siege_none':       # empty siege slot
        siege = None
    siege_after = random.randrange(len(heroes)) if (human and heroes) else 0
    if heroes:
        _log('heroes: ' + ', '.join(h.replace('hero_', '') for h in heroes)
             + (f' + siege {siege[0].replace("siege_", "")}' if siege else ''))
    for i, h in enumerate(heroes):
        tap(*tabs[h])
        _pause(0.08, 0.2, human)
        tap_raw(*_wobble(spots[h], 10, human))
        deployed.append(h)
        _pause(0.35, 0.9, human)
        if siege and i == siege_after:           # the siege goes in with the hero group
            tap(*siege[1])
            _pause(0.08, 0.2, human)
            tap_raw(*_wobble(spots[h], 14, human))
            siege = None
            _pause(0.3, 0.8, human)
    if siege and not heroes:                     # no heroes: siege on the fourth side alone
        tap(*siege[1])
        _pause(0.08, 0.2, human)
        tap_raw(*_wobble(_lerp(LEFT_CORNER, TOP_CORNER, 0.8), 14, human))
    hero_center = (sum(p[0] for p in spots.values()) / len(spots), sum(p[1] for p in spots.values()) / len(spots))         if spots else TOP_CORNER
    used = set()

    def cast(spell, points_fn, label):
        """Cast every copy of `spell`; points_fn(i) gives the i-th target."""
        if spell not in tabs:
            return
        n = int(snapshot.get(spell, 0) or 0) or 1
        _log(f'{n}x {spell.replace("spell_", "")} {label}')
        tap(*tabs[spell])
        _pause(0.1, 0.25, human)
        for i in range(n):
            tap_raw(*_wobble(points_fn(i), 22, human))
            _pause(0.08, 0.3, human)
        used.add(spell)

    # the heroes walk in from where most of them were dropped, towards the middle of the map
    hero_from = hero_center
    if spots:
        placed = list(spots.values())
        hero_from = max(placed, key=lambda p: sum(1 for q in placed if math.dist(p, q) < 220))

    def on_path(start_f, step):
        return lambda i: _lerp(hero_from, MAP_CENTRE, min(0.85, start_f + i * step))

    def cast_on_troops(sp, depth, label):
        """Cast `sp` on the troop groups; with heroes on the field and 4 or more copies, one copy goes
        on the heroes' route. False when no troop was dropped (the caller then uses the heroes' route)."""
        n = int(snapshot.get(sp, 0) or 0) or 1
        for_heroes = 1 if (deployed and n >= 4) else 0
        targets = _spell_targets(_drop_log, n - for_heroes, depth)
        if not targets:
            return False
        if for_heroes:
            targets.append(on_path(0.3, 0.0)(0))
        cast(sp, lambda i: targets[min(i, len(targets) - 1)], label)
        return True

    # 2b) Rage, Haste and Heal on the troops (one on the heroes when there are enough); spells made for
    # the heroes (Heroic, Jump, Invisibility) on the heroes' route
    path_spells = [sp for sp in PATH_SPELLS if sp in tabs]
    if path_spells:
        _pause(0.6, 1.5, human)
        for sp in path_spells:
            if sp in TROOP_SPELLS and cast_on_troops(sp, RAGE_DEPTH, 'on the troops'):
                continue
            cast(sp, on_path(random.uniform(0.25, 0.35) if human else 0.3, 0.12), "on the heroes' route")

    # 2c) spell cards without a picture (e.g. a new spell): on the heroes' path as well, where a boost,
    # a heal or a damage spell all do some good
    for x, y, n, kind in unknown:
        if kind != 'spell':
            continue
        n = min(n, 11)
        _pause(0.3, 0.9, human)
        _log(f"{n}x unknown spell card (x={x}) on the heroes' path")
        tap(x, y)
        _pause(0.1, 0.25, human)
        point = on_path(random.uniform(0.4, 0.6) if human else 0.5, 0.1)
        for i in range(n):
            tap_raw(*_wobble(point(i), 22, human))
            _pause(0.08, 0.3, human)

    # 3) every Earthquake (or Lightning) on the Town Hall / core
    first_spell = True
    for spell in CORE_SPELLS:
        if spell not in tabs:
            continue
        n = int(snapshot.get(spell, 0) or 0) or (11 if spell == 'spell_equake' else 0)
        if n <= 0:
            continue
        _pause(0.6, 1.6, human) if first_spell else _pause(0.2, 0.6, human)
        first_spell = False
        _log(f'{n}x {spell.replace("spell_", "")} on the Town Hall {th}')
        tap(*tabs[spell])
        _pause(0.1, 0.25, human)
        for _ in range(n):                       # replay: 11 Earthquakes in ~1.5 s
            tap_raw(*_wobble(th, 36, human))
            _pause(0.02, 0.10, human)

    # 3b) Freeze / Totem on the core once the heroes close in
    core_support = [sp for sp in CORE_SUPPORT_SPELLS if sp in tabs]
    if core_support:
        _pause(2.0, 4.0, human)
        for sp in core_support:
            if cast_on_troops(sp, SUPPORT_DEPTH, 'ahead of the troops'):
                continue
            ring = random.uniform(0, 6.28) if human else 0
            cast(sp, lambda i, r=ring: (th[0] + 55 * math.cos(r + i * 2.1),
                                        th[1] + 40 * math.sin(r + i * 2.1)), 'on the core')

    # 4) hero abilities at random moments, in random order
    if cfg.get('LOOTMAX_USE_ABILITIES', True) and deployed:
        order = deployed[:]
        if human:
            random.shuffle(order)
        _pause(1.0, 3.5, human)
        for h in order:
            tap(*tabs[h])
            _pause(0.4, 1.4, human)

    # 4b) Revive (and late spells) over the heroes further along their path
    late = [sp for sp in LATE_SPELLS if sp in tabs]
    if late:
        _pause(1.5, 3.5, human)
        for sp in late:
            cast(sp, on_path(random.uniform(0.55, 0.7) if human else 0.62, 0.08), 'over the heroes')

    # 4c) anything not covered above goes on the core, so nothing is left unused
    leftover = [k for k in tabs if k.startswith('spell_') and k not in used and k not in CORE_SPELLS]
    for sp in leftover:
        _pause(0.3, 0.9, human)
        if not cast_on_troops(sp, RAGE_DEPTH + 40, 'on the troops'):
            cast(sp, lambda i: th, 'on the core')

    # 4d) spells beyond the right edge of a scrolling bar (13+ cards): Revive and the like over the
    # heroes, the rest on the core
    try:
        from attack.attacklogic import deploy_hidden_cards
        over_heroes = _lerp(hero_from, MAP_CENTRE, 0.45)
        # troops found there go where a hero went in: a spot the game accepted
        hidden_spot = spots[deployed[0]] if deployed else TOP_CORNER
        deploy_hidden_cards(vision, tabs, th, log_prefix='LOOTMAX', troop_point=hidden_spot,
                            point_for=lambda name: over_heroes if name in LATE_SPELLS + PATH_SPELLS else th)
    except Exception as e:
        _log(f'cards beyond the bar were not played: {e.__class__.__name__}: {e}')

    # 4e) last look at the bar before the wait for the result
    _drop_leftovers(vision, tabs, unknown, th)

    print('=== LOOTMAX ATTACK DEPLOYED ===')
    _finish(vision, cfg, human)
    return NAME


def _finish(vision, cfg, human):
    """Wait for 1 star + the target damage (randomised), then end the battle like a player would."""
    import battle_end
    base = int(cfg.get('LOOTMAX_TARGET_DAMAGE', DEFAULT_TARGET) or DEFAULT_TARGET)
    target = base + (random.randint(0, 6) if human else 0)
    _log(f'ending at {target}% with 1 star')
    start = last_change = time.time()
    last = None
    stall = random.uniform(18, 28) if human else 22
    while time.time() - start < MAX_BATTLE_SECONDS:
        _pause(1.0, 2.2, human)
        screen = vision.grab()
        in_battle = (vision.match_template(screen, 'battle_end_button', 0.8, region=battle_end.END_BUTTON_REGION)
                     or vision.match_template(screen, 'battle_surrender_button', 0.8,
                                              region=battle_end.END_BUTTON_REGION))
        if not in_battle:
            if vision.is_battle_end():
                _log('battle over on its own')
                return
            continue
        damage = battle_end.read_damage(vision, screen)
        stars = battle_end.count_stars(vision, screen)
        if damage != last:
            last, last_change = damage, time.time()
        if damage is not None and damage >= target and stars >= 1:
            _pause(0.4, 3.0, human)                     # a player watches a moment before leaving
            battle_end._end_battle(vision, f'{damage}% and {stars} star(s): loot taken')
            return
        if damage is not None and damage >= 40 and time.time() - last_change > stall:
            battle_end._end_battle(vision, f'damage stuck at {damage}% for {int(stall)} s')
            return
    _log('time limit reached, leaving the battle to finish')
