# builder_base.py - Builder Base battles (new module; flow learned from MyBot PHMOD's AttackBB and
# re-captured live at 1600x900 for Builder Base 2.0).
#
#   home village -> boat -> Builder Base -> Battle -> "Find Now!" -> stage 1 (night map)
#   -> after stage 1 a second, smaller base loads with its own "Battle starts in" countdown
#      (stage 2: surviving troops plus fresh ones) -> end screen "Return Home"
#   -> optional "Star Bonus!" popup (Okay) -> boat back to the home village.
#
# Troop cards are not identified: every card slot is tapped in turn followed by a drop point.
# Empty slots and dead (grey) cards ignore the tap, so no per-troop templates are needed.
# The Battle Machine / Battle Copter card (left) is tapped again during the battle, which fires
# its ability whenever it is charged.
import json
import os
import random
import time

import cv2

from adb import swipe, tap
from ui2_zoom import zoom_out

BB_DEBUG = False
BB_BOAT_REGION = (1350, 120, 1600, 320)
BB_BATTLE_REGION = (0, 700, 220, 900)
BB_BATTLE_BUTTON = (104, 800)
BB_FIND_NOW_REGION = (1000, 520, 1380, 660)
BB_TIMER_REGION = (650, 10, 950, 55)
BB_END_REGION = (600, 700, 1000, 820)
BB_BONUS_REGION = (600, 130, 1000, 230)
BB_OKAY_REGION = (650, 640, 950, 760)
MACHINE_CARD = (160, 795)
CARD_XS = [304 + round(126.4 * i) for i in range(10)]
CARD_Y = 795
# Deploy edges validated live: stage 1 (large night map, default zoom) top-left edge outside the
# red line; stage 2 (smaller day map) right-hand edge.
STAGE_LINES = {
    1: ((360, 285), (590, 136)),
    2: ((1290, 530), (1465, 390)),
}
ABILITY_TAP_SECONDS = 5
BATTLE_TIMEOUT_SECONDS = 420     # two 3-minute stages plus loading

STATE_FILE = os.path.join('logs', 'bb_state.json')   # keeps the visit interval across bot restarts


def _load_state():
    try:
        with open(STATE_FILE, encoding='utf-8') as f:
            return {'next_visit': float(json.load(f).get('next_visit', 0.0))}
    except (OSError, ValueError, TypeError):
        return {'next_visit': 0.0}


def _save_state():
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(_state, f)
    except OSError:
        pass


_state = _load_state()


def _log(msg):
    print(f'[BB] {msg}')


def due(cfg):
    return bool(cfg.get('BB_ATTACKS_ENABLED', False)) and time.time() >= _state['next_visit']


def _on_bb(vision):
    return vision.match_template_region(BB_BATTLE_REGION, 'bb_battle_axes', 0.8) is not None


def _wait(cond, seconds, step=1.0):
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(step)
    return cond()


def _line_points(line, n):
    (x1, y1), (x2, y2) = line
    pts = []
    for i in range(n):
        t = (i + 0.5) / n
        pts.append((int(x1 + (x2 - x1) * t) + random.randint(-4, 4),
                    int(y1 + (y2 - y1) * t) + random.randint(-3, 3)))
    return pts


def _deploy_stage(stage):
    line = STAGE_LINES.get(stage, STAGE_LINES[1])
    points = _line_points(line, len(CARD_XS) + 1)
    _log(f'Deploying stage {stage}')
    tap(*MACHINE_CARD)
    time.sleep(0.3)
    tap(*points[0])
    time.sleep(0.4)
    for x, point in zip(CARD_XS, points[1:]):
        tap(x, CARD_Y)
        time.sleep(0.25)
        tap(*point)
        time.sleep(0.3)


BOAT_SCALES = (1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 1.1, 1.2)
# Fully zoomed out, the home village boat sits below the bottom-left corner of the view: drag the
# map up and to the right to bring that shore into view.
HOME_BOAT_PANS = ((400, 450, 800, 150), (400, 450, 800, 150))
# On the Builder Base the boat sits top-right, partly under the resource bars: drag the map down-left.
BB_BOAT_PANS = ((1000, 350, 750, 600), (600, 600, 1100, 250))
# The Builder Base boat sits on the shore above-right of the base. After battles / upgrades the
# camera can be anywhere, so first drag the world to its top-right limit (the map clamps there),
# which puts the boat in view at a predictable place.
BB_CORNER_PANS = ((1400, 150, 500, 750),) * 3
SAFE_TAP = (1544, 578)
# Home village HUD (x1, y1, x2, y2): the Gold Pass / Battle buttons scored 0.82 against the boat badge.
HOME_UI_ZONES = ((0, 0, 400, 320), (1230, 0, 1600, 330), (0, 380, 160, 660), (0, 700, 340, 900),
                 (340, 780, 820, 900), (1270, 380, 1600, 900))


def _match_multiscale(vision, screen, key, threshold):
    tpl = vision.templates.get(key)
    if not tpl:
        return None, 0.0
    img = tpl['img']
    if img.ndim == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
    best, best_score = None, threshold
    for s in BOAT_SCALES:
        t = img if s == 1.0 else cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        _mn, score, _ml, loc = cv2.minMaxLoc(cv2.matchTemplate(gray, t, cv2.TM_CCOEFF_NORMED))
        if score > best_score:
            best, best_score = (loc[0] + t.shape[1] // 2, loc[1] + t.shape[0] // 2), score
    return best, best_score


def _find_boat(vision, keys, pans=(), ui_zones=(), pre_pans=()):
    """The camera zoom differs between the home village (the bot zooms out), the Builder Base on
    arrival and after a battle (zoomed in and panned), so zoom out and search the whole screen at
    several scales. `pans` are map drags tried in turn when the boat is outside the view."""
    zoom_out()
    time.sleep(0.5)
    for pan in pre_pans:
        swipe(*pan, duration=350)
        time.sleep(0.6)
    for pan in (None,) + tuple(pans):
        if pan:
            swipe(*pan, duration=500)
            time.sleep(1.0)
        screen = vision.grab()
        search = screen.copy()
        for x1, y1, x2, y2 in ui_zones:
            search[y1:y2, x1:x2] = 0
        for key in keys:
            pos, score = _match_multiscale(vision, search, key, 0.72)
            if pos:
                if BB_DEBUG:
                    _log(f'{key} found at {pos} ({score:.2f})')
                return pos
    os.makedirs('logs', exist_ok=True)
    path = os.path.join('logs', f"bb_no_boat_{time.strftime('%Y-%m-%d_%H-%M-%S')}.png")
    cv2.imwrite(path, screen)
    _log(f'Boat not found, screen saved to {path}')
    return None


def on_builder_base(vision):
    return _on_bb(vision)


def _at_home_village(vision):
    # is_home_village() also matches the Builder Base (shared Shop/chat markers).
    return not _on_bb(vision) and vision.is_home_village()


def go_to_builder_base(vision):
    if _on_bb(vision):
        return True
    boat = _find_boat(vision, ('bb_boat_home',), HOME_BOAT_PANS, HOME_UI_ZONES)
    if not boat:
        _log('Boat not found on the home village')
        return False
    tap(*boat)
    return _wait(lambda: _on_bb(vision), 15)


def _close_dialogs(vision, attempts=3):
    """Close Builder Base windows (Start Attack, shop, ...) that hide the boat."""
    for _ in range(attempts):
        close = vision.match_template(vision.grab(), 'bb_dialog_close', 0.85)
        if not close:
            return
        tap(*close)
        time.sleep(1.0)


def go_home(vision):
    if not _on_bb(vision):
        return vision.is_home_village()
    _close_dialogs(vision)
    tap(*SAFE_TAP)                   # deselect a building (its info bar can cover the boat area)
    time.sleep(0.5)
    boat = _find_boat(vision, ('bb_home', 'bb_boat_bb'), BB_BOAT_PANS, pre_pans=BB_CORNER_PANS)
    if not boat:
        _log('Boat not found on the Builder Base')
        return False
    tap(*boat)
    return _wait(lambda: _at_home_village(vision), 15)


def _dismiss_bonus(vision):
    screen = vision.grab()
    if vision.match_template(screen, 'bb_star_bonus_title', 0.8, region=BB_BONUS_REGION):
        okay = vision.match_template(screen, 'bb_okay', 0.8, region=BB_OKAY_REGION)
        _log('Star Bonus collected')
        tap(*(okay or (800, 700)))
        time.sleep(2)


FROZEN_SECONDS = 45


class _FreezeCheck:
    """True once the screen has not changed at all for FROZEN_SECONDS (the game hung: seen on MEmu
    right after a restart, the countdown stopped and the screen dimmed)."""
    def __init__(self):
        self.prev, self.since = None, time.time()

    def update(self, screen):
        small = cv2.resize(cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY), (160, 90))
        if self.prev is None or float((cv2.absdiff(small, self.prev) > 12).mean()) > 0.002:
            self.prev, self.since = small, time.time()
            return False
        return time.time() - self.since >= FROZEN_SECONDS


def attack_once(vision, pause_if_needed=None):
    """One Builder Base battle (both stages). Returns True when it reached the end screen."""
    tap(*BB_BATTLE_BUTTON)
    find_now = None
    for _ in range(10):
        time.sleep(0.5)
        find_now = vision.match_template_region(BB_FIND_NOW_REGION, 'bb_find_now', 0.8)
        if find_now:
            break
    if not find_now:
        _log('"Find Now!" not found')
        return False
    tap(*find_now)
    if not _wait(lambda: vision.match_template_region(BB_TIMER_REGION, 'bb_battle_starts_label', 0.75), 60):
        _log('Battle did not load within 60 s')
        return False
    time.sleep(1.0)
    _deploy_stage(1)
    stage = 1
    seen_live_after_stage1 = False
    start = time.time()
    next_ability = time.time() + ABILITY_TAP_SECONDS
    frozen = _FreezeCheck()
    while time.time() - start < BATTLE_TIMEOUT_SECONDS:
        if callable(pause_if_needed):
            pause_if_needed()
        screen = vision.grab()
        if frozen.update(screen):
            _log(f'Game frozen for {FROZEN_SECONDS} s (no screen change), restarting it')
            return False
        end_btn = vision.match_template(screen, 'bb_return_home', 0.8, region=BB_END_REGION)
        if end_btn:
            _log(f'Battle finished after {int(time.time() - start)} s')
            tap(*end_btn)
            time.sleep(4)
            _dismiss_bonus(vision)
            return True
        countdown = vision.match_template(screen, 'bb_battle_starts_label', 0.75, region=BB_TIMER_REGION)
        if stage == 1 and not countdown:
            seen_live_after_stage1 = True
        if stage == 1 and countdown and seen_live_after_stage1:
            time.sleep(1.0)
            stage = 2
            _deploy_stage(2)
            next_ability = time.time() + ABILITY_TAP_SECONDS
            continue
        if time.time() >= next_ability:
            tap(*MACHINE_CARD)
            next_ability = time.time() + ABILITY_TAP_SECONDS
        time.sleep(1.0)
    _log('Battle did not finish in time')
    return False


def _bb_chores(vision, cfg):
    """Collect and upgrade while on the Builder Base (Pro: BB collectors, master builder, Star Lab)."""
    import collect
    import upgrades
    if cfg.get('COLLECT_RESOURCES', False):
        collect.run_bb(vision)
    if upgrades.due(cfg, 'bb_builders') or upgrades.due(cfg, 'bb_lab'):
        upgrades.run_bb(vision, cfg)
        zoom_out()


def _bb_collect_after(vision, cfg):
    """Collect the Builder Base gold mines / elixir collectors again after the battles."""
    if not cfg.get('COLLECT_RESOURCES', False):
        return
    import collect
    _close_dialogs(vision)
    zoom_out()
    time.sleep(0.5)
    # No Elixir Cart here: Builder Base 2.0 pays battles (Star Bonus) straight into the storages
    # (measured 27 Oct: +401,000 gold / +255,000 elixir with no collect in between), and a full
    # title scan of the base found no cart. Only the collectors need emptying.
    collect.run_bb(vision)


def run_only(adb, vision, cfg, stats=None, pause_if_needed=None):
    """Builder Base only mode (BB_ONLY): stay on the Builder Base and battle back to back.

    Runs BB_ATTACKS_PER_VISIT battles, then returns so the caller can run the scheduler / end
    conditions. Returns 'done' or 'RECOVERY'."""
    if not go_to_builder_base(vision):
        return 'skipped' if not _on_bb(vision) else 'RECOVERY'
    _close_dialogs(vision)
    _dismiss_bonus(vision)
    _bb_chores(vision, cfg)
    attacks = int(cfg.get('BB_ATTACKS_PER_VISIT', 3) or 3)
    for i in range(attacks):
        _log(f'Builder Base only: battle {i + 1}/{attacks}')
        if not attack_once(vision, pause_if_needed):
            return 'RECOVERY'
        if stats is not None:
            stats.total_attacks += 1      # end conditions count these battles
        if not _wait(lambda: _on_bb(vision), 15):
            return 'RECOVERY'
    _bb_collect_after(vision, cfg)
    return 'done'


def run(adb, vision, cfg, pause_if_needed=None):
    """Visit the Builder Base, make up to BB_ATTACKS_PER_VISIT battles, return home.

    Returns 'done' or 'RECOVERY'."""
    _state['next_visit'] = time.time() + 60 * int(cfg.get('BB_INTERVAL_MINUTES', 60) or 60)
    _save_state()
    if not go_to_builder_base(vision):
        # Still on the home village: skip this visit instead of restarting CoC.
        return 'skipped' if not _on_bb(vision) else 'RECOVERY'
    _dismiss_bonus(vision)
    _bb_chores(vision, cfg)
    attacks = int(cfg.get('BB_ATTACKS_PER_VISIT', 3) or 3)
    for i in range(attacks):
        _log(f'Builder Base battle {i + 1}/{attacks}')
        if not attack_once(vision, pause_if_needed):
            return 'RECOVERY'
        if not _wait(lambda: _on_bb(vision), 15):
            return 'RECOVERY'
    _bb_collect_after(vision, cfg)
    return 'done' if go_home(vision) else 'RECOVERY'
