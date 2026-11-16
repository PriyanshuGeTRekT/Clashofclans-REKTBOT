# smart/planner.py - upgrade planning helpers used by upgrades.py.
#
#   never idle        look for a free builder / lab every few minutes instead of every 30
#   upgrade order     start the cheapest (or the most expensive) affordable upgrade on screen first
#   war-aware heroes  while a clan war is on, do not start King / Queen / Warden / Champion / Prince
#                     upgrades (an upgrading hero cannot fight)
import re

HERO_WORDS = ('king', 'queen', 'warden', 'champion', 'prince')
WAR_BUTTON_REGION = (0, 500, 220, 660)        # home screen war button with its countdown
WINDOW_TITLE_REGION = (300, 20, 1300, 200)    # upgrade window: the building / hero name
COST_X = (1400, 1570)
NEVER_IDLE_SECONDS = 300


def _log(msg):
    print(f'[SMART] {msg}')


def _ocr(image, config='--psm 6'):
    import cv2
    import pytesseract
    big = cv2.resize(image, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    return pytesseract.image_to_string(big, config=config)


def interval(cfg, default):
    """Seconds between upgrade checks."""
    return NEVER_IDLE_SECONDS if (cfg or {}).get('SMART_NEVER_IDLE') else default


def read_cost(screen, card):
    """Cost shown on a Build-menu row, or None when it cannot be read."""
    y1, y2 = card
    text = _ocr(screen[y1:y2, COST_X[0]:COST_X[1]], '--psm 7 -c tessedit_char_whitelist=0123456789')
    digits = re.sub(r'\D', '', text)
    return int(digits) if digits else None


def order_cards(cfg, screen, cards):
    mode = str((cfg or {}).get('SMART_UPGRADE_ORDER', 'list'))
    if mode not in ('cheapest', 'priciest') or len(cards) < 2:
        return cards
    cards = [tuple(c) for c in cards]
    costs = {card: read_cost(screen, card) for card in cards}
    known = [c for c in cards if costs[c] is not None]
    unknown = [c for c in cards if costs[c] is None]
    known.sort(key=lambda c: costs[c], reverse=(mode == 'priciest'))
    return known + unknown


def war_active(vision, screen=None):
    """True when the home screen's war button shows a countdown (preparation or battle day)."""
    screen = vision.grab() if screen is None else screen
    x1, y1, x2, y2 = WAR_BUTTON_REGION
    text = _ocr(screen[y1:y2, x1:x2], '--psm 11').lower()
    return bool(re.search(r'\d+\s*[dhm]\b', text))


_war = {'active': False}


def note_home_screen(cfg, vision):
    """Call on the home village before the Build menu opens."""
    if (cfg or {}).get('SMART_WAR_AWARE_HEROES'):
        _war['active'] = war_active(vision)


def block_hero_upgrade(cfg, vision, window):
    """True when the open upgrade window is a hero and a war is on."""
    if not (cfg or {}).get('SMART_WAR_AWARE_HEROES') or not _war['active']:
        return False
    x1, y1, x2, y2 = WINDOW_TITLE_REGION
    title = _ocr(window[y1:y2, x1:x2]).lower()
    if any(word in title for word in HERO_WORDS):
        _log('War is on: leaving this hero upgrade for after the war')
        return True
    return False
