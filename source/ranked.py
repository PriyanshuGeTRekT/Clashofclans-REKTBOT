# ranked.py - Ranked Battle tournaments (new module, Pro feature; flow captured live at 1600x900).
#
# The Battle menu (Multiplayer tab) shows a "Ranked Battle" card next to "Battle / Find a Match".
# Card states:
#   Sign Up!             -> tap -> "Sign up for the upcoming Tournament!" dialog -> Sign Up! (confirm)
#   Signed up!           -> "Preparing Tournament... Starts in: Ns" (nothing to do)
#   Find a Match  N/14   -> tournament running: tap -> "Ranked Battle" army overview -> Attack!
#                           -> "Confirm Attack" dialog -> Attack! -> battle (no loot, trophies only)
#                           -> end screen -> Return Home
# Any other state is saved to logs/ranked_state_<time>.png (at most hourly).
import copy
import os
import time

import cv2
import numpy as np

from adb import tap
from ui2_zoom import zoom_out
import fixed_points as fp
from actions import click_point

RANKED_CARD_REGION = (500, 590, 920, 780)
RANKED_TITLE_REGION = (500, 520, 920, 620)
SIGNUP_DIALOG_REGION = (380, 90, 1220, 180)
SIGNUP_CONFIRM_REGION = (880, 640, 1300, 780)
COUNTER_REGION = (660, 670, 800, 720)       # "N/14" under "Find a Match" on the ranked card
ARMY_TITLE_REGION = (20, 140, 300, 195)      # "Ranked Battle" in the army overview
ARMY_ATTACK_REGION = (1250, 750, 1580, 850)
CONFIRM_TITLE_REGION = (580, 195, 1020, 270)
CONFIRM_ATTACK_REGION = (820, 540, 1090, 650)
STATE_SNAPSHOT_SECONDS = 3600
BATTLE_TIMEOUT_SECONDS = 240

_state = {'last_snapshot': 0.0, 'signed_up': False, 'day': None, 'attacks_today': 0}


def _log(msg):
    print(f'[RANKED] {msg}')


def _digits(vision, screen, region):
    """Cream digits of the attack counter -> text (the '/' reads as one bogus glyph)."""
    x1, y1, x2, y2 = region
    roi = screen[y1:y2, x1:x2].astype(int)
    mask = ((roi[..., 0] > 130) & (roi[..., 1] > 215) & (roi[..., 2] > 215)).astype(np.uint8) * 255
    mask = cv2.resize(mask, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_LINEAR)
    _, mask = cv2.threshold(mask, 128, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = sorted((cv2.boundingRect(c) for c in contours), key=lambda b: b[0])
    text = ''
    for x, y, w, h in boxes:
        if h <= 14:
            continue
        glyph = cv2.copyMakeBorder(mask[y:y + h, x:x + w], 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=0)
        text += vision.match_digit(glyph) or '?'
    return text


def read_counter(vision, screen):
    """(used, total) from 'N/14', or None. The total is the last two glyphs, the slash the one
    before them, the used count everything else."""
    text = _digits(vision, screen, COUNTER_REGION)
    if len(text) < 4 or not text[-2:].isdigit():
        return None
    used = text[:-3]
    if not used.isdigit():
        return None
    used, total = int(used), int(text[-2:])
    return (used, total) if used <= total else None


def _attacks_left_today(cfg):
    today = time.strftime('%Y-%m-%d')
    if _state['day'] != today:
        _state['day'], _state['attacks_today'] = today, 0
    return int(cfg.get('RANKED_MAX_PER_DAY', 14) or 14) - _state['attacks_today']


def handle_battle_menu(vision, cfg):
    """Call while the Battle menu is open.

    Returns 'signup' after signing up (the caller should refresh the menu), 'match' when a ranked
    attack is available and wanted (the menu is still open: call run_match next), else None."""
    screen = vision.grab()
    # The sign-up button reads "Sign Up!" or (since the Nov 2026 update) "Join Tournament".
    signup = (vision.match_template(screen, 'ranked_signup', 0.85, region=RANKED_CARD_REGION) or
              vision.match_template(screen, 'ranked_join_tournament', 0.85, region=RANKED_CARD_REGION))
    if signup:
        if not cfg.get('RANKED_AUTO_SIGNUP', False) or _state['signed_up']:
            return None
        _log('Signing up for the upcoming Ranked Battle tournament')
        tap(*signup)
        time.sleep(1.5)
        screen = vision.grab()
        if not vision.match_template(screen, 'ranked_signup_dialog_title', 0.8, region=SIGNUP_DIALOG_REGION):
            _log('Sign-up dialog did not open')
            return 'signup'
        confirm = vision.match_template(screen, 'ranked_signup_confirm', 0.8, region=SIGNUP_CONFIRM_REGION)
        if confirm:
            tap(*confirm)
            time.sleep(1.5)
            _state['signed_up'] = True
            _log('Signed up')
        return 'signup'
    find = vision.match_template(screen, 'ranked_find_match_btn', 0.8, region=RANKED_CARD_REGION)
    if find:
        if not cfg.get('RANKED_ATTACKS_ENABLED', False):
            return None
        counter = read_counter(vision, screen)
        if counter is None:
            _log('Could not read the ranked attack counter')
            return None
        used, total = counter
        if used >= total or _attacks_left_today(cfg) <= 0:
            return None
        _log(f'Ranked attacks used {used}/{total}: attacking')
        return 'match'
    if vision.match_template(screen, 'ranked_title', 0.8, region=RANKED_TITLE_REGION):
        now = time.time()
        if now - _state['last_snapshot'] >= STATE_SNAPSHOT_SECONDS:
            _state['last_snapshot'] = now
            os.makedirs('logs', exist_ok=True)
            path = os.path.join('logs', f"ranked_state_{time.strftime('%Y-%m-%d_%H-%M-%S')}.png")
            cv2.imwrite(path, screen)
            _log(f'Ranked card is in a state without a template yet, saved {path}')
    return None


def _wait(cond, seconds, step=1.0):
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(step)
    return cond()


def run_match(adb, vision, cfg, attack_modules, pause_if_needed=None):
    """Start and play one ranked attack from the open Battle menu.

    Returns 'attacked', 'skipped' (menu state changed, nothing spent) or 'RECOVERY'."""
    screen = vision.grab()
    find = vision.match_template(screen, 'ranked_find_match_btn', 0.8, region=RANKED_CARD_REGION)
    if not find:
        return 'skipped'
    tap(*find)
    if not _wait(lambda: vision.match_template_region(ARMY_TITLE_REGION, 'ranked_army_title', 0.8), 8):
        _log('Ranked army overview did not open')
        return 'skipped'
    attack = vision.match_template_region(ARMY_ATTACK_REGION, 'ranked_army_attack', 0.8)
    if not attack:
        _log('Attack! button not found in the army overview')
        click_point(adb, fp.HOME_ARMY_TAB_CLOSE)
        return 'skipped'
    tap(*attack)
    if _wait(lambda: vision.match_template_region(CONFIRM_TITLE_REGION, 'ranked_confirm_title', 0.8), 5):
        confirm = vision.match_template_region(CONFIRM_ATTACK_REGION, 'ranked_confirm_attack', 0.8)
        if confirm:
            tap(*confirm)
    strategy = str(cfg.get('RANKED_ATTACK_STRATEGY') or cfg.get('SELECTED_ATTACK_STRATEGY') or 'edragon')
    module = attack_modules.get(strategy) or attack_modules['edragon']
    ranked_cfg = copy.copy(cfg)
    ranked_cfg['SELECTED_ATTACK_STRATEGY'] = strategy
    if not _wait(vision.is_in_battle, 60, 1.0):
        _log('Ranked battle screen did not load')
        return 'RECOVERY'
    _state['attacks_today'] += 1
    _log(f'Attacking with {strategy}')
    # The battle camera starts zoomed in here (no home-village zoom-out before it): the strategies'
    # drop points assume the zoomed-out view, otherwise every troop tap lands in the red zone.
    zoom_out()
    time.sleep(0.8)
    try:
        module.run_attack(adb, vision, ranked_cfg)
    except Exception as e:
        _log(f'Strategy crashed: {e.__class__.__name__}: {e}')
        return 'RECOVERY'
    start = time.time()
    while time.time() - start < BATTLE_TIMEOUT_SECONDS:
        if callable(pause_if_needed):
            pause_if_needed()
        if vision.is_battle_end():
            break
        time.sleep(1.5)
    else:
        _log('Ranked battle did not end in time')
        return 'RECOVERY'
    stars = vision.detect_battle_end_stars()
    _log(f'Ranked attack finished: {stars} star(s)')
    click_point(adb, fp.BATTLE_RETURN_HOME_BUTTON)
    time.sleep(5)
    return 'attacked' if _wait(vision.is_home_village, 15) else 'RECOVERY'
