# donate.py - donate troops / spells to clan requests (new module, Pro feature).
#
# MyBot PHMOD DonateCC.au3, simplified and re-captured at 1600x900:
#   chat button (left) -> clan chat panel (x 0-610) -> request bubbles carry a green "Donate"
#   button on their right -> Donate window opens to the right of the chat -> troop / spell slots
#   are portraits: tap the wanted slot N times -> close the window (tap the Donate button again).
# The Donate button is found by colour (a large green rounded button inside the chat column) and the
# slots by the troop-bar tab templates (same portraits, matched at several scales). Until a live
# request has been seen, every Donate window is also saved to logs/donate_window_*.png.
import os
import time

import cv2
import numpy as np

from adb import swipe, tap

CHAT_BUTTON = (85, 450)
CHAT_PANEL = (0, 90, 610, 800)
CHAT_CLOSE = (655, 410)
CHAT_SCROLL_DOWN = (300, 650, 300, 250)
DONATE_MIN_W, DONATE_MIN_H = 110, 38
WINDOW_REGION = (600, 60, 1600, 860)
SLOT_SCALES = (0.8, 0.9, 1.0, 1.1)
SLOT_THRESHOLD = 0.72
INTERVAL_SECONDS = 300
MAX_PASSES = 3

_state = {'next_run': 0.0, 'saved_windows': 0}


def _log(msg):
    print(f'[DONATE] {msg}')


def due(cfg):
    return (bool(cfg.get('DONATE_ENABLED', False)) and bool(_wanted(cfg))
            and time.time() >= _state['next_run'])


def _wanted(cfg):
    """[(tab_key, count), ...] from DONATE_TROOPS, e.g. 'troop_edragon:2, spell_rage:1'."""
    out = []
    for part in str(cfg.get('DONATE_TROOPS', '') or '').split(','):
        part = part.strip()
        if not part:
            continue
        key, _, n = part.partition(':')
        try:
            out.append((key.strip(), max(1, int(n or 1))))
        except ValueError:
            out.append((key.strip(), 1))
    return out


def find_donate_buttons(screen):
    """Centres of green buttons in the chat column, top to bottom."""
    x1, y1, x2, y2 = CHAT_PANEL
    hsv = cv2.cvtColor(screen[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([35, 120, 120]), np.array([85, 255, 255]))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask)
    buttons = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if w >= DONATE_MIN_W and h >= DONATE_MIN_H and area >= 0.6 * w * h and w < 260 and h < 90:
            cx, cy = centroids[i]
            buttons.append((int(x1 + cx), int(y1 + cy)))
    # The "Challenge" button at the bottom of the chat is also green: it sits below the panel.
    return sorted(buttons, key=lambda p: p[1])


def _find_slot(vision, screen, key):
    tpl = getattr(vision, 'tab_templates', {}).get(key, {}).get('img')
    if tpl is None:
        return None
    x1, y1, x2, y2 = WINDOW_REGION
    roi = screen[y1:y2, x1:x2]
    if roi.ndim == 3 and tpl.ndim == 2:
        roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    best, best_score = None, SLOT_THRESHOLD
    for s in SLOT_SCALES:
        t = tpl if s == 1.0 else cv2.resize(tpl, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        if t.shape[0] >= roi.shape[0] or t.shape[1] >= roi.shape[1]:
            continue
        _mn, score, _ml, loc = cv2.minMaxLoc(cv2.matchTemplate(roi, t, cv2.TM_CCOEFF_NORMED))
        if score > best_score:
            best = (x1 + loc[0] + t.shape[1] // 2, y1 + loc[1] + t.shape[0] // 2)
            best_score = score
    return best


def _donate_into_window(vision, cfg, button):
    tap(*button)
    time.sleep(1.2)
    window = vision.grab()
    if _state['saved_windows'] < 5:
        _state['saved_windows'] += 1
        os.makedirs('logs', exist_ok=True)
        cv2.imwrite(os.path.join('logs', f"donate_window_{time.strftime('%H-%M-%S')}.png"), window)
    given = 0
    for key, count in _wanted(cfg):
        slot = _find_slot(vision, window, key)
        if not slot:
            continue
        for _ in range(count):
            tap(*slot)
            time.sleep(0.25)
            given += 1
        _log(f'Donated {count} x {key}')
    tap(*button)                     # tapping Donate again closes the window
    time.sleep(0.8)
    return given


def run(vision, cfg):
    _state['next_run'] = time.time() + INTERVAL_SECONDS
    tap(*CHAT_BUTTON)
    time.sleep(1.5)
    done = 0
    for _ in range(MAX_PASSES):
        screen = vision.grab()
        buttons = find_donate_buttons(screen)
        if not buttons:
            break
        for button in buttons:
            done += _donate_into_window(vision, cfg, button)
        swipe(*CHAT_SCROLL_DOWN, duration=400)
        time.sleep(0.8)
    if done:
        _log(f'{done} troop(s) / spell(s) donated')
    tap(*CHAT_CLOSE)
    time.sleep(1.0)
    return done
