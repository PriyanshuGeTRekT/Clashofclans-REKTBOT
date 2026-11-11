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
PATH_SPELLS = ('spell_rage', 'spell_haste', 'spell_heal', 'spell_jump', 'spell_invis')
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


# ------------------------------------------------------------------ the attack
def run_attack(adb, vision, active_config=None):
    cfg = active_config or {}
    set_attack_runtime_settings(cfg)
    human = bool(cfg.get('LOOTMAX_HUMANIZE', True))
    print('=== LOOTMAX ATTACK START ===')
    tabs = vision.detect_tabs()
    snapshot = read_battle_snapshot(vision, tabs, log_prefix='LOOTMAX')
    th = vision.get_townhall_pos()

    # 1) dragons: the whole stack, spread round three sides, ~90 ms apart
    main = next((t for t in MAIN_TROOPS if t in tabs), None)
    if main is None:
        troops = [k for k in tabs if k.startswith('troop_')]
        main = max(troops, key=lambda k: snapshot.get(k, 0), default=None)
    if main:
        count = int(snapshot.get(main, 0) or 0) or 11
        points = _sample_runs(_dragon_path(human), count, human)
        if human and random.random() < 0.5:
            points.reverse()                     # sweep right-to-left this time
        _log(f'{count}x {main.replace("troop_", "")} round three sides')
        tap(*tabs[main])
        _pause(0.12, 0.3, human)
        for p in points:                         # adb adds ~80 ms per tap: ~11 drops/s like the replay
            tap_raw(*_wobble(p, 14, human))
            _pause(0.0, 0.06, human)
    else:
        _log('no main troop found in the troop bar')

    # 1b) any other troops in the army (e.g. Dragon Riders) go round the same three sides
    for extra in [k for k in tabs if k.startswith('troop_') and k != main]:
        n = int(snapshot.get(extra, 0) or 0)
        if n <= 0:
            continue
        _pause(0.2, 0.6, human)
        _log(f'{n}x {extra.replace("troop_", "")} round three sides')
        tap(*tabs[extra])
        _pause(0.1, 0.25, human)
        for p in _sample_runs(_dragon_path(human), n, human):
            tap_raw(*_wobble(p, 16, human))
            _pause(0.03, 0.12, human)

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

    def on_path(start_f, step):
        return lambda i: _lerp(hero_center, th, min(0.85, start_f + i * step))

    # 2b) Rage (and other troop-boost spells) on the heroes' path as they walk in
    path_spells = [sp for sp in PATH_SPELLS if sp in tabs]
    if path_spells:
        _pause(0.6, 1.5, human)
        for sp in path_spells:
            cast(sp, on_path(random.uniform(0.32, 0.48) if human else 0.4, 0.12), "on the heroes' path")

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
        cast(sp, lambda i: th, 'on the core')

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
