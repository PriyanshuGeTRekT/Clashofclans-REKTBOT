# supertroop.py - boost Super Troops (new module, Pro feature; MyBot PHMOD BoostSuperTroop.au3).
#
# Captured live at 1600x900:
#   super-troop barrel on the home village (label "Boost" above it) -> window with the yellow skull
#   badge, counter "N/2" top-left, a grid of troop cards (4 columns, rows scroll) with a red name
#   banner each -> tap a card -> "<Troop> Level N" dialog: "Activate <cost> dark elixir" (green,
#   right) and "Activate Super Potion" (grey, left) -> boosted for 3 days.
# Cards that are already boosted show a timer over the banner; we only tap cards whose banner
# matches and re-read the "N/2" counter before and after to confirm the boost.
import os
import time

import cv2

from adb import swipe, tap
from ui2_zoom import zoom_out, zoom_out_home

BARREL_SEARCH = (100, 100, 700, 450)
BARREL_LABEL_KEY = 'collect_label'      # not used; the barrel is found by the "Boost" badge below
WINDOW_BADGE_REGION = (650, 20, 950, 200)
COUNTER_REGION = (200, 55, 360, 115)
CLOSE_REGION = (1300, 30, 1450, 140)
CARD_COLUMNS = (345, 645, 945, 1245)
CARD_ROWS = (370, 745)                   # banner y of the two visible rows
CARD_TAP_DY = 160                        # banner -> card picture
SCROLL = (800, 800, 800, 420)
DIALOG_CLOSE_REGION = (1350, 20, 1470, 120)
ACTIVATE_REGION = (980, 700, 1260, 850)
POTION_REGION = (740, 740, 1000, 850)
CHECK_SECONDS = 6 * 3600

_state = {'next_run': 0.0}


def _log(msg):
    print(f'[SUPERTROOP] {msg}')


def due(cfg):
    return (bool(cfg.get('SUPER_TROOP_ENABLED', False)) and _wanted(cfg)
            and time.time() >= _state['next_run'])


def _wanted(cfg):
    return [t.strip().lower().replace(' ', '_') for t in str(cfg.get('SUPER_TROOPS', '') or '').split(',')
            if t.strip()]


def _window_open(vision):
    return vision.match_template_region(WINDOW_BADGE_REGION, 'supertroop_window_badge', 0.8) is not None


def open_window(vision):
    """Tap the barrel: it is found by its 'Boost' badge (templates/supertroop/boost_badge.png) or,
    without that template, by the known position after a zoom-out."""
    zoom_out_home(vision)
    time.sleep(0.6)
    badge = vision.match_template(vision.grab(), 'supertroop_boost_badge', 0.8)
    if badge:
        tap(badge[0], badge[1] + 55)
    else:
        tap(225, 215)
    time.sleep(1.5)
    return _window_open(vision)


def close_window(vision):
    for _ in range(3):
        if vision.match_template_region(DIALOG_CLOSE_REGION, 'supertroop_dialog_close', 0.8):
            tap(1413, 68)
            time.sleep(0.8)
            continue
        if _window_open(vision):
            tap(1370, 85)
            time.sleep(0.8)
            continue
        return


def _find_card(vision, screen, name):
    key = f'card_{name}'
    hit = vision.match_template(screen, key, 0.8)
    return hit


def boost(vision, name, use_potion):
    """Open the card of `name` and activate it. Returns True when the dialog accepted the boost."""
    screen = vision.grab()
    hit = None
    for _scroll in range(4):
        hit = _find_card(vision, screen, name)
        if hit:
            break
        swipe(*SCROLL, duration=400)
        time.sleep(0.8)
        screen = vision.grab()
    if not hit:
        _log(f'{name}: card not found (no template templates/supertroop/card_{name}.png or not unlocked)')
        return False
    tap(hit[0], hit[1] + CARD_TAP_DY)
    time.sleep(1.5)
    dialog = vision.grab()
    if not vision.match_template(dialog, 'supertroop_dialog_close', 0.8, region=DIALOG_CLOSE_REGION):
        _log(f'{name}: boost dialog did not open')
        return False
    if use_potion and vision.match_template(dialog, 'supertroop_potion', 0.8, region=POTION_REGION):
        tap(865, 785)
    else:
        button = vision.match_template(dialog, 'supertroop_activate', 0.8, region=ACTIVATE_REGION)
        if not button:
            _log(f'{name}: already boosted or not affordable')
            tap(1413, 68)
            time.sleep(0.8)
            return False
        tap(1120, 785)
    time.sleep(1.5)
    after = vision.grab()
    # "Boost? Boost Barbarian into Super Barbarian for 3d?" with one green cost button.
    if vision.match_template(after, 'supertroop_confirm_title', 0.8, region=(600, 100, 1000, 220)):
        button = vision.match_template(after, 'supertroop_confirm_button', 0.7, region=(560, 580, 1020, 760))
        tap(*(button or (790, 665)))
        time.sleep(1.5)
        after = vision.grab()
    os.makedirs('logs', exist_ok=True)
    cv2.imwrite(os.path.join('logs', f"supertroop_{name}_{time.strftime('%H-%M-%S')}.png"), after)
    _log(f'{name}: boost activated')
    tap(1413, 68)
    time.sleep(0.8)
    return True


def run(vision, cfg):
    _state['next_run'] = time.time() + CHECK_SECONDS
    if not open_window(vision):
        _log('Super troop window did not open')
        return 0
    done = 0
    for name in _wanted(cfg)[:2]:
        if boost(vision, name, bool(cfg.get('SUPER_TROOP_USE_POTION', False))):
            done += 1
        if not _window_open(vision):
            if not open_window(vision):
                break
    close_window(vision)
    return done
