# attack.csv_script - scripted attacks in the MyBot.run / PHMOD CSV format (new module, not in Basic).
#
# A script is a list of `COMMAND |v1 |v2 |...` lines (see runtime/CSV/Attack/*.csv):
#   SIDE / SIDEB  weights per building type -> main attack side (only the Town Hall weight and the
#                 forced side are used here; other building locators need templates we don't have)
#   MAKE          A-Z drop vector: half-side, point count, tile offset, order, random jitter
#   DROP          deploy a troop / spell / hero / siege on one or more vectors
#   WAIT          pause (ms or min-max), ends early when the battle is over
#   RECALC        re-read the troop bar
#   TRAIN, REDLN, DRPLN, CCREQ, CCSPL, BOOST are army/GUI settings and are ignored during the attack.
#
# Geometry: PHMOD splits the outer deploy diamond into 8 half-sides (TOP-LEFT-UP ... BOTTOM-RIGHT-DOWN)
# and names them relative to the main side (FRONT-LEFT, LEFT-BACK, ...). Our outer deploy edges are
# attack.geometry.FOUR_SIDES. Index 1 of an INT-EXT vector is at the middle of the side, running to
# the corner; EXT-INT runs the other way. One "tile" is 8 px at PHMOD's 860x732 frame; at our
# 1600x900 zoomed-out view the village diamond is ~1.53x larger, so a tile is ~12 px.
import os
import random
import time

import cv2
import numpy as np

from adb import tap, tap_raw
from attack.attacklogic import read_battle_snapshot, retap_heroes, set_attack_runtime_settings, wait_before_retap
from attack import redline
from attack.geometry import FOUR_SIDES

CSV_DEBUG = True
TILE_PX = 12
JITTER_SCALE = 1.53
DEFAULT_SCRIPT = 'PHMOD-DragLoon'
SAFE_Y_MAX = 725          # keep drops above the troop bar
SAFE_X_MIN, SAFE_X_MAX = 5, 1595
SAFE_Y_MIN = 30
SIEGE_BAR_REGION = (17, 733, 1584, 884)   # fixed_points.TROOP_BAR_REGION
SIEGE_MIN_SCORE = 0.8
NO_DROP_ZONES = [         # (x1, y1, x2, y2): loot panel, surrender/end-battle buttons
    (0, 40, 240, 250),
    (0, 620, 240, 900),
]

# ---------------------------------------------------------------- geometry
# FOUR_SIDES order: bottom-left edge, top-left edge, top-right edge, bottom-right edge.
_EDGE_INDEX = {'BOTTOM-LEFT': 0, 'TOP-LEFT': 1, 'TOP-RIGHT': 2, 'BOTTOM-RIGHT': 3}
_EDGE_BY_NAME = {
    'BOTTOM-LEFT': FOUR_SIDES[0],
    'TOP-LEFT': FOUR_SIDES[1],
    'TOP-RIGHT': FOUR_SIDES[2],
    'BOTTOM-RIGHT': FOUR_SIDES[3],
}
# Outward direction of each edge (PHMOD's +l / -l per axis): positive tiles move away from the base.
_OUTWARD = {
    'TOP-LEFT': (-1, -1),
    'TOP-RIGHT': (1, -1),
    'BOTTOM-LEFT': (-1, 1),
    'BOTTOM-RIGHT': (1, 1),
}
_CENTER = (
    sum(p[0] for edge in FOUR_SIDES for p in edge) / 8.0,
    sum(p[1] for edge in FOUR_SIDES for p in edge) / 8.0,
)

# Relative side names -> real half-sides, per main side (ParseAttackCSV.au3
# __AttackCSV_ApplyMainSideAliases).
_ALIASES = {
    'BOTTOM-RIGHT': {'FRONT-LEFT': 'BOTTOM-RIGHT-DOWN', 'FRONT-RIGHT': 'BOTTOM-RIGHT-UP',
                     'RIGHT-FRONT': 'TOP-RIGHT-DOWN', 'RIGHT-BACK': 'TOP-RIGHT-UP',
                     'LEFT-FRONT': 'BOTTOM-LEFT-DOWN', 'LEFT-BACK': 'BOTTOM-LEFT-UP',
                     'BACK-LEFT': 'TOP-LEFT-DOWN', 'BACK-RIGHT': 'TOP-LEFT-UP'},
    'BOTTOM-LEFT': {'FRONT-LEFT': 'BOTTOM-LEFT-UP', 'FRONT-RIGHT': 'BOTTOM-LEFT-DOWN',
                    'RIGHT-FRONT': 'BOTTOM-RIGHT-DOWN', 'RIGHT-BACK': 'BOTTOM-RIGHT-UP',
                    'LEFT-FRONT': 'TOP-LEFT-DOWN', 'LEFT-BACK': 'TOP-LEFT-UP',
                    'BACK-LEFT': 'TOP-RIGHT-UP', 'BACK-RIGHT': 'TOP-RIGHT-DOWN'},
    'TOP-LEFT': {'FRONT-LEFT': 'TOP-LEFT-UP', 'FRONT-RIGHT': 'TOP-LEFT-DOWN',
                 'RIGHT-FRONT': 'BOTTOM-LEFT-UP', 'RIGHT-BACK': 'BOTTOM-LEFT-DOWN',
                 'LEFT-FRONT': 'TOP-RIGHT-UP', 'LEFT-BACK': 'TOP-RIGHT-DOWN',
                 'BACK-LEFT': 'BOTTOM-RIGHT-UP', 'BACK-RIGHT': 'BOTTOM-RIGHT-DOWN'},
    'TOP-RIGHT': {'FRONT-LEFT': 'TOP-RIGHT-DOWN', 'FRONT-RIGHT': 'TOP-RIGHT-UP',
                  'RIGHT-FRONT': 'TOP-LEFT-UP', 'RIGHT-BACK': 'TOP-LEFT-DOWN',
                  'LEFT-FRONT': 'BOTTOM-RIGHT-UP', 'LEFT-BACK': 'BOTTOM-RIGHT-DOWN',
                  'BACK-LEFT': 'BOTTOM-LEFT-DOWN', 'BACK-RIGHT': 'BOTTOM-LEFT-UP'},
}


def _half_side(name):
    """(edge_name, int_end, ext_end) of a real half-side such as 'TOP-LEFT-UP'."""
    edge_name, half = name.rsplit('-', 1)
    p1, p2 = _EDGE_BY_NAME[edge_name]
    mid = ((p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0)
    upper, lower = (p1, p2) if p1[1] < p2[1] else (p2, p1)
    corner = upper if half == 'UP' else lower
    return edge_name, mid, corner


def _safe(x, y):
    if not (SAFE_X_MIN <= x <= SAFE_X_MAX and SAFE_Y_MIN <= y <= SAFE_Y_MAX):
        return False
    return not any(x1 <= x <= x2 and y1 <= y <= y2 for x1, y1, x2, y2 in NO_DROP_ZONES)


def quadrant_of(point):
    """PHMOD main-side quadrant of a screen point (split at the diamond centre)."""
    x, y = point
    vert = 'TOP' if y < _CENTER[1] else 'BOTTOM'
    horiz = 'LEFT' if x < _CENTER[0] else 'RIGHT'
    return f'{vert}-{horiz}'


def make_vector(real_side, points, addtiles, versus, randx, randy, depths=None):
    """MakeDropPoints: `points` positions along a half-side, index 1 first. With `depths` (the
    red line of attack.redline for every edge) the points start on the detected red line, as in
    PHMOD; without it they start on the outer deploy edge."""
    edge_name, int_end, ext_end = _half_side(real_side)
    if versus == 'EXT-INT':
        start, end = ext_end, int_end
    else:  # INT-EXT; IGNORE behaves like EXT-INT in PHMOD only for building vectors
        start, end = int_end, ext_end
    n = max(1, int(points))
    ox, oy = _OUTWARD[edge_name]
    rx = random.randint(0, abs(int(randx))) * JITTER_SCALE
    ry = random.randint(0, abs(int(randy))) * JITTER_SCALE
    vec = []
    for i in range(n):
        t = (i + 0.5) / n
        bx = start[0] + (end[0] - start[0]) * t
        by = start[1] + (end[1] - start[1]) * t
        if depths:
            bx, by = redline.shift_point(_EDGE_INDEX[edge_name], depths[_EDGE_INDEX[edge_name]], (bx, by))
        tiles = int(addtiles)
        # Outward offsets back off until the point is still deployable (IsInsideDiamondRedArea);
        # inward offsets (into the base, for spells) always apply in full.
        steps = range(abs(tiles) * TILE_PX, -1, -1) if tiles > 0 else [abs(tiles) * TILE_PX]
        px, py = bx, by
        for l in steps:
            sign = 1 if tiles > 0 else -1
            px = bx + ox * sign * l + ox * rx
            py = by + oy * sign * l + oy * ry
            if tiles <= 0 or _safe(px, py):
                break
        vec.append((int(round(px)), int(round(py))))
    return vec


# ---------------------------------------------------------------- troop names
# PHMOD short names (MBR Global Variables.au3) -> our troop-bar tab keys (templates/tabs/*.png).
TROOP_TABS = {
    'BARB': 'troop_barbarian', 'SBARB': 'troop_super_barbarian', 'ARCH': 'troop_archer',
    'SARCH': 'troop_super_archer', 'GIANT': 'troop_giant', 'SGIANT': 'troop_super_giant',
    'GOBL': 'troop_goblin', 'SGOBL': 'troop_sneaky_goblin', 'WALL': 'troop_wall_breaker',
    'SWALL': 'troop_super_wall_breaker', 'BALL': 'troop_balloon', 'RBALL': 'troop_rocket_balloon',
    'WIZA': 'troop_wizard', 'SWIZA': 'troop_super_wizard', 'HEAL': 'troop_healer',
    'DRAG': 'troop_dragon', 'SDRAG': 'troop_super_dragon', 'PEKK': 'troop_pekka',
    'BABYD': 'troop_bdragon', 'INFERNOD': 'troop_inferno_dragon', 'MINE': 'troop_miner',
    'SMINE': 'troop_super_miner', 'EDRAG': 'troop_edragon', 'YETI': 'troop_yeti',
    'RDRAG': 'troop_dragon_rider', 'ETITAN': 'troop_titan', 'ROOTR': 'troop_root_rider',
    'THROW': 'troop_thrower', 'METEORG': 'troop_meteor_golem', 'MINI': 'troop_minion',
    'SMINI': 'troop_super_minion', 'HOGS': 'troop_hog_rider', 'SHOGS': 'troop_super_hog_rider',
    'VALK': 'troop_valkyrie', 'SVALK': 'troop_super_valkyrie', 'GOLE': 'troop_golem',
    'WITC': 'troop_witch', 'SWITC': 'troop_super_witch', 'LAVA': 'troop_lava_hound',
    'ICEH': 'troop_ice_hound', 'BOWL': 'troop_bowler', 'SBOWL': 'troop_super_bowler',
    'HUNT': 'troop_head_hunter', 'APPWARD': 'troop_warden_prince', 'DRUID': 'troop_druid',
    'FURN': 'troop_furnace', 'RUINW': 'troop_ruin_witch',
    # event troops
    'ERIDER': 'event_elephantrider', 'GGIANT': 'event_giantgiant', 'KANE': 'event_kane',
    'YEET': 'event_yeeter', 'YUNDER': 'event_yetiundertaker', 'KICKER': 'event_barbariankicker',
    'GTHROW': 'event_giantthrower', 'BROOM': 'event_broomwitch', 'MECHA': 'event_mecha',
    'ICEMINI': 'event_iceminion', 'ICEG': 'event_icegolem', 'PARTYWIZ': 'event_partywizard',
    'FIRE': 'event_firecracker', 'RAMR': 'event_ramrider', 'PBARB': 'event_pumpkinbarbarian',
    'ROYALG': 'event_royalghost', 'BARCHER': 'event_barcher', 'HOGWIZ': 'event_hogwizard',
    'LAVALOON': 'event_lavaloon', 'TTHROW': 'event_totemthrower', 'WITCHG': 'event_witchgolem',
    'SBARREL': 'event_skeletonbarrel', 'ADRAG': 'event_azuredragon', 'GDRAG': 'event_goldendragon',
    # spells
    'LSPELL': 'spell_zap', 'HSPELL': 'spell_heal', 'RSPELL': 'spell_rage', 'JSPELL': 'spell_jump',
    'FSPELL': 'spell_freeze', 'CSPELL': 'spell_clone', 'ISPELL': 'spell_invis', 'RESPELL': 'spell_recall',
    'RVSPELL': 'spell_revive', 'TSPELL': 'spell_totem', 'PSPELL': 'spell_poison', 'ESPELL': 'spell_equake',
    'HASPELL': 'spell_haste', 'SKSPELL': 'spell_skeleton', 'BTSPELL': 'spell_bats',
    'OGSPELL': 'spell_overgrowth', 'IBSPELL': 'spell_iceblock', 'ASPELL': 'spell_angry',
    # heroes
    'KING': 'hero_king', 'QUEEN': 'hero_queen', 'PRINCE': 'hero_prince', 'WARDEN': 'hero_warden',
    'CHAMPION': 'hero_rc', 'DUKE': 'hero_duke',
    # siege machines
    'WALLW': 'siege_wrecker', 'BATTLEB': 'siege_blimp', 'STONES': 'siege_slammer',
    'SIEGEB': 'siege_barracks', 'LOGL': 'siege_loglauncher', 'FLAMEF': 'siege_flame',
    'BATTLED': 'siege_drill', 'TROOPL': 'siege_launcher', 'SKYW': 'siege_wagon',
}
_SINGLE_DROP = ('hero_', 'siege_')


# ---------------------------------------------------------------- parsing
def _range(value, default=0):
    """'5' -> (5, 5); '12000-15000' -> (12000, 15000); '' -> (default, default)."""
    v = (value or '').strip()
    if not v:
        return (default, default)
    if '-' in v[1:]:
        a, b = v.split('-', 1)
        a, b = int(a), int(b)
        return (min(a, b), max(a, b))
    return (int(v), int(v))


def _pick(rng):
    return rng[0] if rng[0] == rng[1] else random.randint(rng[0], rng[1])


def _indexes(value):
    """'5' -> [5]; '1-5' -> [1..5]; '6-1' -> [6..1]; '9,7,5' -> [9, 7, 5]."""
    v = value.strip()
    if ',' in v:
        return [int(x) for x in v.split(',') if x.strip()]
    if '-' in v:
        a, b = (int(x) for x in v.split('-', 1))
        step = 1 if b >= a else -1
        return list(range(a, b + step, step))
    return [int(v)]


def parse_script(path):
    """Return {'side': [...], 'sideb': [...], 'revenge': bool, 'lines': [(cmd, values), ...]}."""
    script = {'side': [], 'sideb': [], 'revenge': False, 'lines': []}
    with open(path, encoding='utf-8-sig', errors='replace') as f:
        for raw in f:
            line = raw.rstrip('\r\n')
            if not line.strip() or line.lstrip()[:1] in (';', '#', "'"):
                continue
            parts = [p.strip().upper() for p in line.split('|')]
            cmd = parts[0]
            values = parts[1:] + [''] * max(0, 10 - len(parts))
            if not cmd:
                if 'REVENGE' in values[7]:
                    script['revenge'] = True
                continue
            if cmd == 'NOTE':
                continue
            if cmd == 'SIDE':
                script['side'] = values[:8]
            elif cmd == 'SIDEB':
                script['sideb'] = values[:8]
            elif cmd in ('MAKE', 'DROP', 'WAIT', 'RECALC'):
                script['lines'].append((cmd, values))
    return script


def list_scripts(root=None):
    folder = scripts_dir(root)
    if not os.path.isdir(folder):
        return []
    return sorted(os.path.splitext(n)[0] for n in os.listdir(folder) if n.lower().endswith('.csv'))


def scripts_dir(root=None):
    base = root or os.environ.get('APP_LAUNCH_DIR') or os.getcwd()
    return os.path.join(base, 'CSV', 'Attack')


# ---------------------------------------------------------------- engine
class CsvAttack:
    def __init__(self, vision, script, script_name='script', dry_run=False):
        self.v = vision
        self.script = script
        self.name = script_name
        self.dry_run = dry_run
        self.vectors = {}
        self.tabs = {}
        self.counts = {}
        self.main_side = 'BOTTOM-RIGHT'
        self.deployed_heroes = []
        self.missing = set()
        self.last_tab = None
        self.ended = False
        self._siege_cache = None
        self.use_redline = True
        self.depths = None
        self.outer_vectors = {}    # same vectors on the outer edges: fallback for refused taps

    # ---- setup
    def read_bar(self):
        self.tabs = self.v.detect_tabs()
        self.counts = read_battle_snapshot(self.v, self.tabs, prefixes=('troop_', 'event_', 'spell_'))
        self.last_tab = None
        self._siege_cache = None

    def choose_main_side(self):
        side_vals = self.script['side'] + [''] * 8
        forced = side_vals[7]
        if forced in _ALIASES:
            self.main_side = forced
            return f'forced {forced}'
        if forced in ('TOP', 'BOT'):
            vert = 'TOP' if forced == 'TOP' else 'BOTTOM'
            self.main_side = f"{vert}-{random.choice(('LEFT', 'RIGHT'))}"
            return f'random {forced} half'
        try:
            th_weight = int(side_vals[6] or 0)
        except ValueError:
            th_weight = 0
        if th_weight > 0 and not self.script['revenge']:
            th = self.v.find_townhall() if hasattr(self.v, 'find_townhall') else None
            if th:
                self.main_side = quadrant_of(th)
                return f'Town Hall at {th}'
        return 'default'

    def detect_redline(self):
        if not self.use_redline:
            return 'outer edges'
        try:
            self.depths = redline.detect(self.v.grab())
        except Exception as e:
            print(f'[CSV] Red line detection failed ({e.__class__.__name__}: {e}), using the outer edges')
            self.depths = None
            return 'outer edges'
        if not self.depths:
            return 'outer edges'
        avg = sum(sum(d) / len(d) for d in self.depths.values()) / len(self.depths)
        return f'red line, {avg:.0f} px inside the outer edges on average'

    def build_vectors(self):
        aliases = _ALIASES[self.main_side]
        for cmd, values in self.script['lines']:
            if cmd != 'MAKE':
                continue
            letter, side = values[0], values[1]
            if values[7]:
                print(f'[CSV] MAKE {letter}: building targets ({values[7]}) are not supported yet, '
                      'using the side line')
            if side == 'RANDOM':
                side = random.choice(list(aliases))
            real = aliases.get(side, side)
            if real.rsplit('-', 1)[0] not in _EDGE_BY_NAME:
                print(f'[CSV] MAKE {letter}: unknown side {side}, skipped')
                continue
            args = (real, _range(values[2], 1)[0], _range(values[3])[0], values[4] or 'INT-EXT',
                    _range(values[5])[0], _range(values[6])[0])
            self.vectors[letter] = make_vector(*args, depths=self.depths)
            self.outer_vectors[letter] = make_vector(*args) if self.depths else self.vectors[letter]

    # ---- actions
    def _select(self, tab_key):
        if self.dry_run or self.last_tab == tab_key:
            return
        tap(*self.tabs[tab_key])
        time.sleep(0.08)
        self.last_tab = tab_key

    def _real_siege(self):
        """The siege tab actually in the bar. detect_tabs matches sieges with TM_CCORR_NORMED at 0.7,
        which lets every siege template 'match' the one siege tile (0.87-0.97); re-score the
        candidates with TM_CCOEFF_NORMED (0.87 real vs <=0.65 others in testing) and keep the best."""
        if self._siege_cache is not None:
            return self._siege_cache or None
        frame = self.v.grab()
        x1, y1, x2, y2 = SIEGE_BAR_REGION
        roi = frame[y1:y2, x1:x2]
        best, best_score = '', SIEGE_MIN_SCORE
        for key in self.tabs:
            if not key.startswith('siege_') or key == 'siege_none':
                continue
            tpl = self.v.tab_templates.get(key, {}).get('img')
            if tpl is None or tpl.shape[0] > roi.shape[0] or tpl.shape[1] > roi.shape[1]:
                continue
            _mn, score, _ml, _loc = cv2.minMaxLoc(cv2.matchTemplate(roi, tpl, cv2.TM_CCOEFF_NORMED))
            if score > best_score:
                best, best_score = key, score
        self._siege_cache = best
        if best:
            print(f'[CSV] Siege in the bar: {best[6:]} ({best_score:.2f})')
        return best or None

    def _tab_for(self, troop):
        if troop == 'ANYS':
            return self._real_siege()
        key = TROOP_TABS.get(troop)
        if key and key.startswith('siege_'):
            return key if self._real_siege() == key else None
        if key and key in self.tabs:
            return key
        return None

    def drop(self, values):
        vec_names = [x for x in values[0].split('-') if x]
        idx = _indexes(values[1])
        qty = _pick(_range(values[2], 1))
        troop = values[3]
        delay_point = _range(values[4])
        delay_change = _range(values[5])
        sleep_after = _range(values[6])
        if troop == 'REMAIN':
            self.drop_remaining(vec_names, idx)
            return
        key = self._tab_for(troop)
        if not key:
            if troop not in self.missing:
                self.missing.add(troop)
                print(f'[CSV] {troop} not in the troop bar, skipping its drops')
            return
        vectors = [self.vectors[n] for n in vec_names if n in self.vectors]
        if not vectors:
            print(f'[CSV] DROP {troop}: vectors {values[0]} were not made')
            return
        single = key.startswith(_SINGLE_DROP)
        if single:
            point = self._point(vectors[0], idx[0])
            if point:
                self._deploy_single(key, point)
            self._sleep_ms(_pick(sleep_after))
            return
        per_point, extra = divmod(qty, len(idx))
        before = self.counts.get(key)
        self._select(key)
        for pos, index in enumerate(idx):
            n = per_point + (1 if pos < extra else 0)
            for j, vec in enumerate(vectors):
                point = self._point(vec, index)
                if point is None or n <= 0:
                    continue
                self._tap_n(point, n, _pick(delay_point))
                if key in self.counts:
                    self.counts[key] = max(0, self.counts[key] - n)
            if pos < len(idx) - 1:
                self._sleep_ms(_pick(delay_change))
        if before is not None and key.startswith(('troop_', 'event_')):
            tapped = min(before, sum(per_point + (1 if pos < extra else 0) for pos in range(len(idx)))
                         * len(vectors))
            self._redeploy_refused(key, before - tapped, vec_names, idx)
        self._sleep_ms(_pick(sleep_after))

    def _bar_count(self, key):
        """Troops of `key` still in the bar (None when the count cannot be read)."""
        frame = self.v.grab()
        positions = getattr(self.v, 'tab_matches', {}).get(key, [self.tabs[key]])
        total, seen = 0, False
        for p in positions:
            c = self.v.read_troop_count(p, frame)
            if c is not None:
                seen = True
                total += max(0, int(c))
        return total if seen else None

    def _redeploy_refused(self, key, expected_left, vec_names, idx):
        """Taps inside the red zone are ignored by the game. When more troops are left in the bar
        than expected, drop the difference on the same points of the outer-edge vectors."""
        if self.dry_run or not self.depths:
            return
        time.sleep(0.3)
        left = self._bar_count(key)
        if left is None or left <= expected_left:
            if left is not None:
                self.counts[key] = left
            return
        refused = left - expected_left
        points = [p for n in vec_names if n in self.outer_vectors
                  for p in (self._point(self.outer_vectors[n], i) for i in idx) if p]
        if not points:
            return
        print(f'[CSV] {refused} {key} taps were refused (red zone), redeploying on the outer edge')
        self._select(key)
        for i in range(refused):
            self._tap_n(points[i % len(points)], 1, 60)
        self.counts[key] = expected_left

    def drop_remaining(self, vec_names, idx):
        self.read_bar()
        vectors = [self.vectors[n] for n in vec_names if n in self.vectors] or list(self.vectors.values())[:1]
        if not vectors:
            return
        points = [p for vec in vectors for p in (self._point(vec, i) for i in idx) if p]
        for key, count in self.counts.items():
            if count <= 0 or not key.startswith(('troop_', 'event_')) or key not in self.tabs:
                continue
            print(f'[CSV] REMAIN: {key[len(key.split("_")[0]) + 1:]} x{count}')
            self._select(key)
            for i in range(count):
                self._tap_n(points[i % len(points)], 1, 40)
            self._redeploy_refused(key, 0, vec_names, idx)

    def _deploy_single(self, key, point):
        print(f'[CSV] {key} at {point}')
        if self.dry_run:
            return
        tap(*self.tabs[key])
        time.sleep(0.08)
        tap_raw(*point)
        time.sleep(0.1)
        self.last_tab = None
        if key.startswith('hero_'):
            self.deployed_heroes.append({'name': key})

    def _point(self, vec, index):
        if 1 <= index <= len(vec):
            return vec[index - 1]
        return None

    def _tap_n(self, point, n, delay_ms):
        if self.dry_run:
            return
        for _ in range(n):
            tap_raw(point[0] + random.randint(-2, 2), point[1] + random.randint(-2, 2))
            if delay_ms > 0:
                time.sleep(delay_ms / 1000.0)

    def _sleep_ms(self, ms):
        if ms <= 0 or self.dry_run:
            return
        deadline = time.time() + ms / 1000.0
        while time.time() < deadline:
            time.sleep(min(0.5, max(0.0, deadline - time.time())))

    def wait(self, values):
        ms = _pick(_range(values[0]))
        if values[1]:
            print(f'[CSV] WAIT {values[0]}: break condition "{values[1]}" is not supported, waiting the full time')
        if self.dry_run:
            return
        deadline = time.time() + ms / 1000.0
        while time.time() < deadline:
            if self.v.is_battle_end():
                print('[CSV] Battle ended during WAIT, stopping script')
                self.ended = True
                return
            time.sleep(0.5)

    # ---- main
    def run(self):
        self.read_bar()
        reason = self.choose_main_side()
        line = self.detect_redline()
        self.build_vectors()
        print(f'[CSV] Script {self.name}: main side {self.main_side} ({reason}), '
              f'{len(self.vectors)} vectors on the {line}')
        if CSV_DEBUG or self.dry_run:
            self.save_debug_image()
        for cmd, values in self.script['lines']:
            if self.ended:
                break
            if cmd == 'DROP':
                self.drop(values)
            elif cmd == 'WAIT':
                self.wait(values)
            elif cmd == 'RECALC':
                self.read_bar()
        if self.deployed_heroes and not self.dry_run and not self.ended:
            wait_before_retap(2.0)
            retap_heroes(self.tabs, self.deployed_heroes)

    def save_debug_image(self, path=None):
        frame = self.v.grab()
        if frame is None:
            return
        cv2.imwrite(os.path.join('logs', 'csv_frame.png'), frame)   # clean copy for red-line tuning
        img = frame.copy()
        if self.depths:
            for edge_index, depths in self.depths.items():
                pts = [redline.point_on_line(edge_index, depths, (i + 0.5) / len(depths))
                       for i in range(len(depths))]
                pts = np.array([[int(x), int(y)] for x, y in pts], np.int32)
                cv2.polylines(img, [pts], False, (255, 255, 0), 2)
        for letter, vec in sorted(self.vectors.items()):
            for i, (x, y) in enumerate(vec, 1):
                cv2.circle(img, (x, y), 4, (0, 0, 255), -1)
                if i == 1:
                    cv2.putText(img, letter, (x + 5, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        cv2.circle(img, (int(_CENTER[0]), int(_CENTER[1])), 6, (255, 0, 0), -1)
        out = path or os.path.join('logs', 'csv_debug.png')
        os.makedirs(os.path.dirname(out), exist_ok=True)
        cv2.imwrite(out, img)
        print(f'[CSV] Debug image saved to {out}')


def run_attack(adb, vision, active_config=None):
    cfg = active_config or {}
    set_attack_runtime_settings(cfg)
    name = str(cfg.get('CSV_ATTACK_SCRIPT') or DEFAULT_SCRIPT)
    path = os.path.join(scripts_dir(), name + '.csv')
    print(f'=== CSV ATTACK START ({name}) ===')
    if not os.path.isfile(path):
        raise FileNotFoundError(f'CSV script not found: {path}')
    attack = CsvAttack(vision, parse_script(path), name)
    attack.use_redline = bool(cfg.get('CSV_USE_REDLINE', True))
    attack.run()
    print('=== CSV ATTACK FINISHED ===')
