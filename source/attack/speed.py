# attack/speed.py - the battle speed button of the speed events.
#
# During these events a green "1x" button appears at the bottom right of the battle screen once the
# first troop is down. One tap turns it into "4x": the battle then runs four times faster, so an attack
# that takes minutes is over in seconds.
#
# The button is only pressed when it is seen showing "1x" (never blind: a tap on a button that already
# shows "4x" would slow the battle down again). `seen` remembers for the session that the event is on,
# so the next attacks drop their whole army in one burst and press the button straight after.
import os
import time

import cv2

from adb import tap_raw

TEMPLATE = 'fastforward'                 # templates/fastforward.png: the green "1x" button
REGION = (800, 300, 1600, 900)           # the right half below the top bar
SCALES = (1.0, 0.9, 1.1, 0.8, 1.2, 0.7, 1.3)
THRESHOLD = 0.80
FAST_FACTOR = 0.25                       # pauses after the press shrink with the battle clock (4x)
PROBE_ATTACKS = 3                        # look for the button in the first attacks of a session...
PROBE_EVERY = 10                         # ...and then now and again, in case an event starts

seen = False                             # the button was on screen in this session
pos = None                               # where it was (x, y)
scale = 1.0                              # template scale that matched
attacks = 0
_saved = 0
_missed = 0


def _log(msg):
    print(f'[SPEED] {msg}')


def enabled(cfg):
    return bool((cfg or {}).get('EVENT_SPEED_BOOST', True))


def should_probe():
    """Is it worth one screenshot to look for the button during this attack?"""
    return seen or attacks <= PROBE_ATTACKS or attacks % PROBE_EVERY == 0


def new_attack():
    global attacks
    attacks += 1


def _match(gray, tpl, scales):
    best = (0.0, None, 1.0)
    th, tw = tpl.shape[:2]
    for s in scales:
        w, h = max(8, int(round(tw * s))), max(8, int(round(th * s)))
        if h > gray.shape[0] or w > gray.shape[1]:
            continue
        t = tpl if s == 1.0 else cv2.resize(tpl, (w, h), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
        res = cv2.matchTemplate(gray, t, cv2.TM_CCOEFF_NORMED)
        _mn, mx, _mnl, loc = cv2.minMaxLoc(res)
        if mx > best[0]:
            best = (float(mx), (loc[0] + w // 2, loc[1] + h // 2), s)
    return best


def find(vision, screen=None):
    """(x, y, score) of the "1x" button, or None."""
    global seen, pos, scale
    entry = vision.templates.get(TEMPLATE)
    if not entry:
        return None
    tpl = entry['img']
    if tpl.ndim == 3:
        tpl = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)
    if screen is None:
        screen = vision.grab()
    gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY) if screen.ndim == 3 else screen
    if pos:                              # it never moves: look where it was first
        r = 90
        x1, y1 = max(0, pos[0] - r), max(0, pos[1] - r)
        score, p, s = _match(gray[y1:pos[1] + r, x1:pos[0] + r], tpl, (scale,))
        if p and score >= THRESHOLD:
            return x1 + p[0], y1 + p[1], score
    x1, y1, x2, y2 = REGION
    score, p, s = _match(gray[y1:y2, x1:x2], tpl, SCALES)
    if not p or score < THRESHOLD:
        return None
    seen, pos, scale = True, (x1 + p[0], y1 + p[1]), s
    return pos[0], pos[1], score


def _save(screen, tag):
    """Keep the first few button pictures of a session (logs/speed_*.png), to check the press by eye."""
    global _saved
    if _saved >= 6 or pos is None:
        return
    _saved += 1
    try:
        os.makedirs('logs', exist_ok=True)
        x, y = pos
        cv2.imwrite(os.path.join('logs', f'speed_{_saved}_{tag}.png'), screen[max(0, y - 110):y + 110, max(0, x - 160):x + 160])
    except Exception:
        pass


def press(vision, tries=3, wait=0.25):
    """Tap the "1x" button if it is on screen. True when the battle now runs faster."""
    for attempt in range(tries):
        screen = vision.grab()
        hit = find(vision, screen)
        if hit:
            x, y, score = hit
            _save(screen, 'before')
            tap_raw(x, y)
            time.sleep(0.2)
            after = vision.grab()
            _save(after, 'after')
            still = find(vision, after)
            if still and still[2] >= score - 0.02:        # the picture did not change: tap missed
                _log(f'"1x" still showing after the tap (match {still[2]:.2f}), tapping again')
                tap_raw(x, y)
            _log(f'4x speed on (button at {x},{y}, match {score:.2f})')
            return True
        if attempt < tries - 1:
            time.sleep(wait)
    global _missed
    if _missed < 3:                      # keep a few full frames, to see what the screen looked like
        _missed += 1
        try:
            os.makedirs('logs', exist_ok=True)
            cv2.imwrite(os.path.join('logs', f'speed_notfound_{_missed}.png'), screen)
        except Exception:
            pass
    return False
