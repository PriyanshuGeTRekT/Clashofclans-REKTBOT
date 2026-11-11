# battle_end.py - end a battle early on stars / damage / no progress (new module, Pro feature).
#
# MyBot PHMOD ends battles from GoldElixirChangeEBO.au3 (loot stops changing) and on star / percent
# targets. Re-implemented on our 1600x900 captures:
#   * damage: "Overall Damage NN%" bottom-right, white glyphs read with the UI digit templates.
#   * stars: each earned star shows a silver star left of the damage (templates/battle_end).
#   * no progress: neither damage nor the available-loot counters changed for N seconds.
# Only runs after the attack strategy has deployed everything (farming IN_BATTLE state).
import os
import time

import cv2
import numpy as np

from adb import tap

DAMAGE_REGION = (1400, 648, 1590, 702)
STAR_REGION = (1180, 630, 1460, 710)
STAR_THRESHOLD = 0.8
END_BUTTON_REGION = (0, 600, 260, 740)
END_BUTTON = (115, 668)
CONFIRM_REGION = (500, 450, 1200, 800)
CHECK_SECONDS = 2.0

_state = {'last_check': 0.0, 'last_change': 0.0, 'last_damage': None, 'last_loot': None}


def _log(msg):
    print(f'[END BATTLE] {msg}')


def enabled(cfg):
    return bool(cfg.get('END_BATTLE_ENABLED', False))


def reset():
    now = time.time()
    _state.update(last_check=0.0, last_change=now, last_damage=None, last_loot=None)


def read_damage(vision, screen):
    """Overall damage percent, or None when it cannot be read."""
    x1, y1, x2, y2 = DAMAGE_REGION
    hsv = cv2.cvtColor(screen[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([0, 0, 200]), np.array([180, 60, 255]))
    mask = cv2.resize(mask, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_LINEAR)
    _, mask = cv2.threshold(mask, 180, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = sorted((cv2.boundingRect(c) for c in contours), key=lambda b: b[0])
    text = ''
    for x, y, w, h in boxes:
        if h <= 20 or w <= 4:
            continue
        glyph = cv2.copyMakeBorder(mask[y:y + h, x:x + w], 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=0)
        text += vision.match_digit(glyph)          # the '%' glyph matches no digit
    if not text:
        return None
    value = int(text)
    return value if 0 <= value <= 100 else None


def count_stars(vision, screen):
    tpl = vision.templates.get('battle_star_earned')
    if not tpl:
        return 0
    x1, y1, x2, y2 = STAR_REGION
    gray = cv2.cvtColor(screen[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    res = cv2.matchTemplate(gray, tpl['img'], cv2.TM_CCOEFF_NORMED)
    stars = 0
    while stars < 3:
        _mn, score, _ml, loc = cv2.minMaxLoc(res)
        if score < STAR_THRESHOLD:
            break
        stars += 1
        x, y = loc
        res[max(0, y - tpl['h']):y + tpl['h'], max(0, x - tpl['w']):x + tpl['w']] = -1
    return stars


def _end_battle(vision, reason):
    _log(f'Ending battle: {reason}')
    tap(*END_BUTTON)
    time.sleep(1.5)
    screen = vision.grab()
    okay = vision.match_template(screen, 'battle_end_okay', 0.8, region=CONFIRM_REGION)
    if okay:
        tap(*okay)
    else:
        # First run: no confirm template yet. Save the dialog so the button can be captured.
        os.makedirs('logs', exist_ok=True)
        path = os.path.join('logs', f"end_battle_dialog_{time.strftime('%H-%M-%S')}.png")
        cv2.imwrite(path, screen)
        _log(f'Confirm button not recognised, dialog saved to {path}')
    time.sleep(1.0)


def check(vision, cfg):
    """Call from the battle wait loop. Returns True when it ended the battle."""
    now = time.time()
    if now - _state['last_check'] < CHECK_SECONDS:
        return False
    _state['last_check'] = now
    screen = vision.grab()
    # The red button reads "Surrender" before the first star and "End Battle" after it.
    if (vision.match_template(screen, 'battle_end_button', 0.8, region=END_BUTTON_REGION) is None and
            vision.match_template(screen, 'battle_surrender_button', 0.8, region=END_BUTTON_REGION) is None):
        return False                    # not in the live battle phase (end screen, loading, ...)
    damage = read_damage(vision, screen)
    stars = count_stars(vision, screen)
    want_stars = int(cfg.get('END_BATTLE_STARS', 0) or 0)
    if want_stars and stars >= want_stars:
        _end_battle(vision, f'{stars} star(s) reached')
        return True
    want_damage = int(cfg.get('END_BATTLE_DAMAGE', 0) or 0)
    if want_damage and damage is not None and damage >= want_damage:
        _end_battle(vision, f'{damage}% damage reached')
        return True
    idle = int(cfg.get('END_BATTLE_NO_CHANGE_SECONDS', 0) or 0)
    if idle:
        try:
            loot = vision.detect_loot()
        except Exception:
            loot = None
        if damage != _state['last_damage'] or (loot and loot != _state['last_loot']):
            _state['last_change'] = now
        _state['last_damage'] = damage
        _state['last_loot'] = loot or _state['last_loot']
        if now - _state['last_change'] >= idle:
            _end_battle(vision, f'no damage or loot change for {idle} s ({damage}%, {stars} star(s))')
            return True
    return False
