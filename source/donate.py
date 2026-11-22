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

ONLY_SLICE_SECONDS = 600          # donation-only mode: hand back to the main loop this often
ONLY_KEEPALIVE_SECONDS = 45       # ... and touch the chat this often so the game stays connected
ONLY_RETRY_SECONDS = 20           # a request nothing could be given to is left alone this long

_state = {'next_run': 0.0, 'saved_windows': 0, 'told_empty': False}


def _log(msg):
    print(f'[DONATE] {msg}')


def due(cfg):
    return (bool(cfg.get('DONATE_ENABLED', False)) and (bool(_wanted(cfg)) or _give_requested_on(cfg))
            and time.time() >= _state['next_run'])


def _give_requested_on(cfg):
    return bool(cfg.get('DONATE_REQUESTED', True))


FILL = 'max'                      # count of a "What to donate" entry: as many as the request takes
FILL_WORDS = ('max', 'all', 'fill', 'full', '*')


def _wanted(cfg):
    """[(tab_key, count), ...] from DONATE_TROOPS, e.g. 'troop_edragon:2, spell_rage:1, troop_valkyrie:max'.
    The count is 1 when left out, and FILL for max / all / fill / *: castles differ in size, so a
    fixed number is too many for a small one and too few for a big one."""
    out = []
    for part in str(cfg.get('DONATE_TROOPS', '') or '').split(','):
        part = part.strip()
        if not part:
            continue
        key, _, n = part.partition(':')
        n = n.strip().lower()
        if n in FILL_WORDS:
            out.append((key.strip(), FILL))
            continue
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


# ---------------------------------------------------------------------------------------------
# Requests that name what they want (UPDATE 22 Nov, asked for by a user): the request bubble then has a
# "Requested:" row of small cards (x1 Archer, x3 ..., x1 Rage), and in the donation window the game shows
# exactly those cards in colour and every other card in grey. So the bot does not need to know the
# troops: it taps the coloured cards until none is left. Seen on 5 saved windows (27 Oct): 3 troops +
# 2 spells requested -> 5 coloured cards; 2 troops + 1 spell -> 3.
CARD_AREA = (620, 170, 1480, 740)        # the troop and spell rows of the donation window
DONATED_STRIP = (640, 770, 1460, 860)    # "Donated Troops and Spells": changes when a tap gave something
CARD_PITCH = (114, 143)                  # card spacing, to split cards that touch
MAX_REQUEST_TAPS = 45                    # per request
MAX_TAPS_PER_CARD = 12
REQUEST_LABEL_ABOVE = (230, 110)         # the "Requested:" label sits this far above the Donate button


def request_is_specific(vision, screen, button):
    """True when the request above this Donate button has a "Requested:" row."""
    if not getattr(vision, 'templates', {}).get('donate_requested'):
        return False
    y1 = max(0, int(button[1]) - REQUEST_LABEL_ABOVE[0])
    y2 = max(y1 + 30, int(button[1]) - REQUEST_LABEL_ABOVE[1])
    return bool(vision.match_template(screen, 'donate_requested', 0.8, region=(0, y1, 420, y2)))


def donation_window_open(screen):
    """The donation window is a large light panel right of the chat (0.62 of that area is light with
    the window open, 0.02 on the village or in a battle)."""
    x1, y1, x2, y2 = 630, 180, 1470, 860
    hsv = cv2.cvtColor(screen[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
    if float(((hsv[..., 1] < 40) & (hsv[..., 2] > 170)).mean()) <= 0.35:
        return False
    # ... with the dimmed clan chat left of it (mean brightness about 35): other light windows, like
    # Settings, reach further left, and the Supercell ID screen is bright blue there
    left = cv2.cvtColor(screen[200:800, 330:600], cv2.COLOR_BGR2HSV)[..., 2]
    return float(left.mean()) < 90


def coloured_cards(screen):
    """Centres of the cards shown in colour in the donation window, row by row."""
    x1, y1, x2, y2 = CARD_AREA
    hsv = cv2.cvtColor(screen[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
    mask = ((hsv[..., 1] > 90) & (hsv[..., 2] > 90)).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask)
    cards = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if w < 70 or h < 90 or area < 0.45 * w * h:
            continue
        cols = max(1, round(w / CARD_PITCH[0]))
        rows = max(1, round(h / CARD_PITCH[1]))
        if cols > 7 or rows > 3:
            continue
        for r in range(rows):
            for c in range(cols):
                cards.append((int(x1 + x + (c + 0.5) * w / cols), int(y1 + y + (r + 0.5) * h / rows)))
    return sorted(cards, key=lambda p: (round(p[1] / 60), p[0]))


WINDOW_BODY = (620, 170, 1480, 870)      # the donation window below its title
CHANGED_PIXELS = 12                      # this many pixels differing by more than CHANGED_BY: a real change
CHANGED_BY = 35
MAX_FILL_TAPS = 40                       # per "max" entry and request


def _gave_something(before, after, card):
    """True when a tap on `card` changed the donation window somewhere else than on that card: the
    "Donate Troops: N/55" counter, the "Donated Troops and Spells" strip, or the window closing.
    FIX: the first version compared the mean of the strip only, which a second troop of the same
    kind (x1 becomes x2, a few pixels) did not move, so only one of several was given."""
    if not donation_window_open(after):
        return True                              # the game closes the window when the castle is full
    x1, y1, x2, y2 = WINDOW_BODY
    a = cv2.cvtColor(before[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY).astype(np.int16)
    b = cv2.cvtColor(after[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY).astype(np.int16)
    diff = np.abs(a - b) > CHANGED_BY
    cx, cy = int(card[0]) - x1, int(card[1]) - y1
    diff[max(0, cy - 80):cy + 80, max(0, cx - 62):cx + 62] = False     # the card itself (press, greying)
    return int(diff.sum()) >= CHANGED_PIXELS


def _fill_with(vision, slot, screen):
    """Tap one card until a tap gives nothing more. Returns (given, last screen)."""
    given = 0
    for _ in range(MAX_FILL_TAPS):
        if not donation_window_open(screen):
            break
        before = screen
        tap(*slot)
        time.sleep(0.45)
        screen = vision.grab()
        if not _gave_something(before, screen, slot):
            break                                # full, or this card cannot be given
        given += 1
    return given, screen


def _give_requested(vision, window):
    """Tap the coloured cards of the open donation window until none is left. Returns how many taps
    gave something (the window changed away from the card, or the card went grey)."""
    given = 0
    taps, dead = {}, set()
    screen = window
    for _ in range(MAX_REQUEST_TAPS):
        if not donation_window_open(screen):
            break                                # the game closes the window when the castle is full
        todo = [c for c in coloured_cards(screen) if (c[0] // 40, c[1] // 40) not in dead]
        if not todo:
            break
        card = todo[0]
        key = (card[0] // 40, card[1] // 40)
        before = screen
        tap(*card)
        time.sleep(0.45)
        screen = vision.grab()
        still_there = any((c[0] // 40, c[1] // 40) == key for c in coloured_cards(screen))
        changed = not still_there or _gave_something(before, screen, card)
        taps[key] = taps.get(key, 0) + 1
        if changed:
            given += 1
        if not changed or taps[key] >= MAX_TAPS_PER_CARD:
            dead.add(key)                        # this card gives nothing (more): leave it
    return given


def _donate_into_window(vision, cfg, button):
    tap(*button)
    time.sleep(1.2)
    window = vision.grab()
    if _state['saved_windows'] < 5:
        _state['saved_windows'] += 1
        os.makedirs('logs', exist_ok=True)
        cv2.imwrite(os.path.join('logs', f"donate_window_{time.strftime('%H-%M-%S')}.png"), window)
    if _give_requested_on(cfg) and donation_window_open(window) and request_is_specific(vision, window, button):
        given = _give_requested(vision, window)
        _log(f'Request names what it wants: {given} requested troop(s) / spell(s) given')
        if donation_window_open(vision.grab()):
            tap(*button)                 # tapping Donate again closes the window
            time.sleep(0.8)
        return given
    given = 0
    screen = window
    for key, count in _wanted(cfg):
        if count == FILL and not donation_window_open(screen):
            break                        # the castle is full: the game closed the window
        slot = _find_slot(vision, window, key)
        if not slot:
            continue
        if count == FILL:
            n, screen = _fill_with(vision, slot, screen)
            given += n
            _log(f'Donated {n} x {key} (as many as the request took)')
            continue
        for _ in range(count):
            tap(*slot)
            time.sleep(0.25)
            given += 1
        _log(f'Donated {count} x {key}')
        screen = vision.grab()
    if donation_window_open(vision.grab()):
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


# ---------------------------------------------------------------------------------------------
# Donation-only mode (DONATE_ONLY): no attacks. The clan chat stays open and the bot looks at it
# every DONATE_ONLY_POLL_SECONDS; the moment a request shows its green Donate button, it donates.
def chat_open(vision, screen=None):
    screen = vision.grab() if screen is None else screen
    return bool(vision.match_template(screen, 'chat_window', 0.8))


def _open_chat(vision):
    for _ in range(3):
        if chat_open(vision):
            return True
        tap(*CHAT_BUTTON)
        time.sleep(1.5)
    return chat_open(vision)


def run_only(adb, vision, cfg, stats=None, pause_if_needed=None):
    """One slice of donation-only mode. Returns 'RECOVERY' when the game needs restarting, else None."""
    from control import BotControl
    wanted = _wanted(cfg)
    if not wanted and not _give_requested_on(cfg):
        if not _state['told_empty']:
            _state['told_empty'] = True
            _log('Donation-only mode is on but "What to donate" is empty: nothing to give. '
                 'Fill it in on the Clan & Events page (for example troop_dragon:1, spell_rage:1)')
        time.sleep(5)
        return None
    poll = max(0.5, float(cfg.get('DONATE_ONLY_POLL_SECONDS', 2) or 2))
    if not _open_chat(vision):
        _log('The clan chat did not open')
        return 'RECOVERY'
    _log(f'Watching the clan chat for requests (every {poll:g} s)')
    started = time.time()
    keepalive = time.time() + ONLY_KEEPALIVE_SECONDS
    skip_until = 0.0
    total = 0
    while BotControl.running and time.time() - started < ONLY_SLICE_SECONDS:
        if callable(pause_if_needed):
            pause_if_needed()
        screen = vision.grab()
        if not chat_open(vision, screen):
            if vision.is_home_village():
                if not _open_chat(vision):        # something closed the chat: open it again
                    return 'RECOVERY'
                continue
            _log('The chat is gone and this is not the village: recovering')
            return 'RECOVERY'
        now = time.time()
        buttons = find_donate_buttons(screen) if now >= skip_until else []
        if buttons:
            given = 0
            for button in buttons:
                given += _donate_into_window(vision, cfg, button)
            if given:
                total += given
                if stats is not None:
                    stats.troops_donated = getattr(stats, 'troops_donated', 0) + given
                _log(f'Request answered: {given} troop(s) / spell(s) donated')
            else:
                # nothing of ours fits this request (wrong troops, already full): do not hammer it
                skip_until = time.time() + ONLY_RETRY_SECONDS
            keepalive = time.time() + ONLY_KEEPALIVE_SECONDS
            continue
        if now >= keepalive:
            swipe(*CHAT_SCROLL_DOWN, duration=300)   # stay on the newest messages and stay connected
            keepalive = now + ONLY_KEEPALIVE_SECONDS
            time.sleep(0.5)
            continue
        time.sleep(poll)
    if total:
        _log(f'{total} donated in this stretch')
    return None
