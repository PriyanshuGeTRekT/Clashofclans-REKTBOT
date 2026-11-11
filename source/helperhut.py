# helperhut.py - Builder's Apprentice and Lab Assistant (new module, Pro feature).
#
# Flow from MyBot PHMOD HelperHut.au3, re-captured at 1600x900 once the hut is found:
#   tap the Helper Hut -> info bar -> "Builder's Apprentice" / "Lab Assistant" button -> window
#   with a list of running upgrades, each with a green "Assign" button and its remaining time.
#   Assign the helper to the longest upgrade (PHMOD: only when the remaining time exceeds what the
#   helper saves, level x 1 h), then "Confirm". A helper already working shows a small helper
#   head on its job; it has a 22 h cooldown after a job, so the window is checked every 2-4 hours.
# The hut's position is learned once: HELPER_HUT_POS in the profile config, or found by the
# 'helperhut_building' template (templates/helperhut/) on the zoomed-out village.
import os
import random
import time

import cv2
import numpy as np

from adb import swipe, tap
from ui2_zoom import zoom_out, zoom_out_home

WINDOW_CLOSE_REGION = (1300, 20, 1480, 130)
BAR_REGION = (300, 600, 1300, 800)
ASSIGN_REGION = (900, 150, 1500, 800)
CONFIRM_REGION = (500, 500, 1100, 800)
SAFE_TAP = (1544, 578)
LIST_SCROLL = (1100, 700, 1100, 300)

_state = {'next_run': 0.0}


def _log(msg):
    print(f'[HELPER] {msg}')


def due(cfg):
    return bool(cfg.get('HELPER_HUT_ENABLED', False)) and time.time() >= _state['next_run']


def _save(vision, tag):
    os.makedirs('logs', exist_ok=True)
    path = os.path.join('logs', f"helper_{tag}_{time.strftime('%H-%M-%S')}.png")
    cv2.imwrite(path, vision.grab())
    return path


def _find_hut(vision, cfg):
    pos = cfg.get('HELPER_HUT_POS')
    if pos and len(pos) == 2:
        return int(pos[0]), int(pos[1])
    hit = vision.match_template(vision.grab(), 'helperhut_building', 0.8)
    return hit


def _green_buttons(screen, region):
    """Centres of solid green buttons inside `region`, top to bottom."""
    x1, y1, x2, y2 = region
    hsv = cv2.cvtColor(screen[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([35, 110, 110]), np.array([85, 255, 255]))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask)
    out = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if 90 <= w <= 320 and 36 <= h <= 110 and area >= 0.6 * w * h:
            out.append((int(x1 + centroids[i][0]), int(y1 + centroids[i][1])))
    return sorted(out, key=lambda p: p[1])


def _open_helper_window(vision, cfg, kind):
    """kind: 'builder' or 'lab'. Returns True when the helper window is open."""
    hut = _find_hut(vision, cfg)
    if not hut:
        _log('Helper Hut position unknown: set HELPER_HUT_POS or add templates/helperhut/helperhut_building.png')
        return False
    zoom_out_home(vision)                 # HELPER_HUT_POS is at the reference zoom
    time.sleep(0.6)
    tap(*hut)
    time.sleep(1.2)
    bar = vision.grab()
    if not vision.match_template(bar, 'helperhut_title', 0.8, region=(600, 560, 1000, 640)):
        _log(f'{kind}: tapping HELPER_HUT_POS did not open the Helper Hut, saved {_save(vision, "bar")}')
        tap(*SAFE_TAP)
        return False
    key = 'helperhut_bar_builder' if kind == 'builder' else 'helperhut_bar_lab'
    button = vision.match_template(bar, key, 0.8, region=BAR_REGION)
    if not button:
        _log(f'{kind}: helper card not recognised, saved {_save(vision, "bar")}')
        tap(*SAFE_TAP)
        return False
    # "Available in: 12h 15m" above the card = helper on cooldown: nothing to assign now.
    x, y = button
    cooldown = vision.match_template(bar, 'helperhut_available_in', 0.8, region=(x - 90, y - 90, x + 90, y - 20))
    if cooldown:
        _log(f'{kind}: helper on cooldown (Available in ...), skipping')
        tap(*SAFE_TAP)
        return False
    tap(*button)
    time.sleep(1.5)
    return vision.match_template_region(WINDOW_CLOSE_REGION, 'upgrade_window_close', 0.8) is not None


def _assign(vision, kind):
    """Press the first Assign button (the longest job is listed first), then Confirm."""
    screen = vision.grab()
    buttons = _green_buttons(screen, ASSIGN_REGION)
    if not buttons:
        _log(f'{kind}: no Assign button (helper busy / on cooldown), saved {_save(vision, "window")}')
        return False
    tap(*buttons[0])
    time.sleep(1.2)
    confirm = _green_buttons(vision.grab(), CONFIRM_REGION)
    if confirm:
        tap(*confirm[0])
        time.sleep(1.0)
    _log(f'{kind}: helper assigned')
    return True


def _close(vision):
    for _ in range(3):
        x = vision.match_template_region(WINDOW_CLOSE_REGION, 'upgrade_window_close', 0.8)
        if not x:
            break
        tap(*x)
        time.sleep(0.8)
    tap(*SAFE_TAP)
    time.sleep(0.4)


def run(vision, cfg):
    _state['next_run'] = time.time() + random.uniform(2, 4) * 3600
    done = 0
    for kind, flag in (('builder', 'HELPER_APPRENTICE'), ('lab', 'HELPER_LAB_ASSISTANT')):
        if not cfg.get(flag, True):
            continue
        if _open_helper_window(vision, cfg, kind):
            if _assign(vision, kind):
                done += 1
        _close(vision)
    return done
