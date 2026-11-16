# smart/selfheal.py - repair a button picture after a game update changed the button.
#
# The bot finds buttons by comparing the screen with saved pictures (templates). When Supercell
# redraws a button, its picture stops matching and the bot is stuck. Buttons with text on them can
# be found again by READING the screen:
#   1. Tesseract OCR looks for the button's words inside the area where the button lives.
#   2. If OCR cannot read it and the Claude features are on, Claude is asked for the button's box.
# The area around the words is saved as the new picture (the old one goes to
# logs/selfheal_backup/), so the next start works without any of this.
import difflib
import os
import shutil
import time
from pathlib import Path

from utils.runtime_paths import resolve_resource_path, resolve_writable_path

# template key -> (words on the button, region to look in (x1, y1, x2, y2), padding (x, y))
LABELS = {
    'army_button': (['edit', 'army'], (0, 780, 420, 900), (14, 8)),
    'attack_button': (['battle'], (0, 700, 220, 900), (10, 8)),
    'build_button': (['build'], (1380, 700, 1600, 900), (10, 8)),
    'shop_button_home': (['shop'], (1420, 380, 1600, 540), (10, 8)),
    'return_home': (['return', 'home'], (600, 680, 1000, 860), (14, 10)),
    'end_battle': (['end', 'battle'], (0, 610, 260, 730), (12, 8)),
    'surrender_battle': (['surrender'], (0, 610, 260, 730), (12, 8)),
    'next_button': (['next'], (1340, 560, 1600, 720), (12, 8)),
    'okay_button': (['okay'], (380, 380, 1220, 760), (30, 14)),
}
FUZZY = 0.72
_recent = {}


def _log(msg):
    print(f'[SELF-HEAL] {msg}')


def can_heal(key):
    return key in LABELS


def _ocr_words(image):
    """[(lowercase word, x, y, w, h)] from Tesseract, on a 2x upscaled copy."""
    import cv2
    import pytesseract
    big = cv2.resize(image, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    words = []
    for psm in ('11', '6'):
        data = pytesseract.image_to_data(big, config=f'--psm {psm}', output_type=pytesseract.Output.DICT)
        for i, text in enumerate(data['text']):
            text = ''.join(ch for ch in text.lower() if ch.isalnum())
            if len(text) >= 3:
                words.append((text, data['left'][i] // 2, data['top'][i] // 2,
                              data['width'][i] // 2, data['height'][i] // 2))
    return words


def find_label(image, wanted):
    """Bounding box (x1, y1, x2, y2) of all `wanted` words in `image`, or None."""
    words = _ocr_words(image)
    boxes = []
    for want in wanted:
        best, best_score = None, FUZZY
        for text, x, y, w, h in words:
            score = difflib.SequenceMatcher(None, want, text).ratio()
            if score >= best_score:
                best, best_score = (x, y, x + w, y + h), score
        if best is None:
            return None
        boxes.append(best)
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def _ask_claude(cfg, screen, wanted, region):
    from smart import ai
    x1, y1, x2, y2 = region
    answer = ai.ask_json(
        cfg,
        f'This is a 1600x900 Clash of Clans screenshot. Find the button whose label reads '
        f'"{" ".join(wanted)}" inside the area x {x1}-{x2}, y {y1}-{y2}. Give the pixel box around the '
        f'label text only (not the whole button). Set found to false if it is not there.',
        {'type': 'object', 'additionalProperties': False,
         'required': ['found', 'x1', 'y1', 'x2', 'y2'],
         'properties': {'found': {'type': 'boolean'}, 'x1': {'type': 'integer'}, 'y1': {'type': 'integer'},
                        'x2': {'type': 'integer'}, 'y2': {'type': 'integer'}}},
        image_bgr=screen)
    if not answer or not answer.get('found'):
        return None
    box = (answer['x1'], answer['y1'], answer['x2'], answer['y2'])
    if not (x1 - 40 <= box[0] < box[2] <= x2 + 40 and y1 - 40 <= box[1] < box[3] <= y2 + 40):
        return None                                     # outside the expected area: do not trust it
    return box


def heal(cfg, vision, key, screen=None):
    """Re-crop template `key` from the current screen. True when a new picture is in use."""
    if key not in LABELS:
        return False
    if time.time() - _recent.get(key, 0) < 300:         # at most one attempt per key per 5 minutes
        return False
    _recent[key] = time.time()
    import cv2
    wanted, region, (pad_x, pad_y) = LABELS[key]
    screen = vision.grab() if screen is None else screen
    x1, y1, x2, y2 = region
    box = find_label(screen[y1:y2, x1:x2], wanted)
    if box:
        box = (box[0] + x1, box[1] + y1, box[2] + x1, box[3] + y1)
        how = 'OCR'
    elif (cfg or {}).get('SMART_VISION_FALLBACK'):
        box = _ask_claude(cfg, screen, wanted, region)
        how = 'Claude'
    if not box:
        _log(f'"{" ".join(wanted)}" was not found on screen, {key} left as it is')
        return False
    h, w = screen.shape[:2]
    cx1, cy1 = max(0, box[0] - pad_x), max(0, box[1] - pad_y)
    cx2, cy2 = min(w, box[2] + pad_x), min(h, box[3] + pad_y)
    if cx2 - cx1 < 20 or cy2 - cy1 < 12:
        return False
    crop = cv2.cvtColor(screen[cy1:cy2, cx1:cx2], cv2.COLOR_BGR2GRAY)
    path = Path(resolve_resource_path(f'templates/{key}.png'))
    if path.exists():
        backup = Path(resolve_writable_path('logs')) / 'selfheal_backup'
        backup.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup / f'{key}-{time.strftime("%Y%m%d-%H%M%S")}.png')
    os.makedirs(path.parent, exist_ok=True)
    cv2.imwrite(str(path), crop)
    tpl = vision.load_template(str(path), cv2.IMREAD_GRAYSCALE)
    if tpl is None:
        return False
    vision.templates[key] = tpl
    _log(f'{key} re-learned from the screen by {how} at ({cx1},{cy1})-({cx2},{cy2}); old picture kept in '
         f'logs/selfheal_backup')
    return True
