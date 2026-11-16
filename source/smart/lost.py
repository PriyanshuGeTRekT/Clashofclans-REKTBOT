# smart/lost.py - get back to the village from an unknown screen without restarting the game.
#
# Normally a lost bot force-restarts Clash of Clans. With "Try to get home before restarting" on,
# it first tries up to MAX_STEPS safe moves, all decided on this computer (no AI, nothing sent out):
#   1. read the screen (Tesseract) and tap a harmless button: Return Home, Continue, Reload,
#      Try Again, Close, Later, Cancel
#   2. tap a red X close button in the upper part of the screen
#   3. press Android Back (closes most windows; on the bare village it opens "exit game?", which
#      step 1 then answers with Cancel)
# It never taps Okay, Confirm, Use, Buy, Upgrade or anything with a price, so it cannot spend.
import time

import cv2
import numpy as np

from adb import back, tap

MAX_STEPS = 5
STRICT, LOOSE = 0.9, 0.75    # word match needed for a one-word / a two-word button
PACKAGE = 'com.supercell.clashofclans'
# phrases that are safe to tap, most specific first
SAFE_PHRASES = [['return', 'home'], ['try', 'again'], ['continue'], ['reload'], ['close'], ['later'],
                ['cancel']]


def _log(msg):
    print(f'[RESCUE] {msg}')


def find_safe_button(screen):
    """((x, y), 'label') of a harmless button found by reading the screen, or None."""
    from smart import selfheal
    words = selfheal.ocr_words(screen)
    for phrase in SAFE_PHRASES:
        # one word alone must be near-exact ("Player" must not pass for "Later"); two words that
        # both appear are already unlikely by chance, and the game font needs the slack
        box = selfheal.match_words(words, phrase, fuzzy=STRICT if len(phrase) == 1 else LOOSE)
        if box:
            return ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2), ' '.join(phrase)
    return None


def find_close_x(screen):
    """Centre of a red X close button in the upper half of the screen, or None."""
    h, w = screen.shape[:2]
    top = screen[:int(h * 0.5)]
    hsv = cv2.cvtColor(top, cv2.COLOR_BGR2HSV)
    red = cv2.inRange(hsv, (0, 150, 140), (8, 255, 255)) | cv2.inRange(hsv, (172, 150, 140), (180, 255, 255))
    red = cv2.morphologyEx(red, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    white = cv2.inRange(hsv, (0, 0, 215), (180, 60, 255))
    contours, _ = cv2.findContours(red, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    for c in contours:
        x, y, bw, bh = cv2.boundingRect(c)
        if not (38 <= bw <= 110 and 38 <= bh <= 110 and 0.72 <= bw / bh <= 1.38):
            continue                                   # badges are smaller, banners are wider
        if cv2.contourArea(c) / float(bw * bh) < 0.45:
            continue
        cross = white[y:y + bh, x:x + bw].mean() / 255.0
        if not 0.06 <= cross <= 0.5:                   # the white X inside the red square
            continue
        if best is None or x > best[0]:                # close buttons sit at the right
            best = (x, y, bw, bh)
    if best is None:
        return None
    x, y, bw, bh = best
    return x + bw // 2, y + bh // 2


def rescue(cfg, vision, adb=None):
    """True when the bot is back on the home village and no restart is needed."""
    import adb as adb_module
    if not adb_module.is_app_in_foreground(PACKAGE):
        return False                                   # game closed or crashed: the restart handles it
    moved = False
    for step in range(1, MAX_STEPS + 1):
        if vision.is_home_village():
            if moved:
                _log('Back on the home village, no restart needed')
            return moved                               # already home with no move: let the restart happen
        screen = vision.grab()
        found = find_safe_button(screen)
        if found:
            pos, label = found
            _log(f'Step {step}: tapping "{label}"')
            tap(*pos)
        else:
            pos = find_close_x(screen)
            if pos:
                _log(f'Step {step}: tapping the close button at {pos}')
                tap(*pos)
            else:
                _log(f'Step {step}: nothing safe to tap, pressing Back')
                back()
        moved = True
        time.sleep(2.5)
    return moved and bool(vision.is_home_village())
