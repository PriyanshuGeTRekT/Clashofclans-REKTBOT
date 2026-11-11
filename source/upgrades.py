# upgrades.py - auto upgrades through the in-game Build menu (new module, Pro feature).
#
# Same approach as MyBot PHMOD's AutoUpgrade / AutoLabUpgrade: let the game's own list decide.
# The Build menu (hammer button, bottom right) has four tabs, captured live at 1600x900:
#   Builders   "Buildings & Heroes"  buildings and heroes          counter "free/total" (builders)
#   Lab        "Army Upgrades"       troops, spells, sieges        counter "free/1"
#   Blacksmith "Hero Equipment"      equipment (ores, no counter)
#   Pets       "Hero Pets"           pets                          counter "free/1"
# Each tab lists in-progress items first (green rows), then "Suggested upgrades", then the rest.
# A row's cost is white when affordable and red when not. Tapping a row opens "Upgrade X to Level
# N?" with a green Confirm button showing the cost. Lab / pet windows also offer "Confirm Hammer of
# ..." (spends a magic item) - only the GREEN resource Confirm is ever pressed.
import os
import time

import cv2
import numpy as np

from adb import swipe, tap

BUILD_BUTTON = (1495, 800)
MENU_CLOSE = (1572, 28)
TABS = {'builders': (1222, 850), 'lab': (1330, 850), 'equipment': (1440, 850), 'pets': (1547, 850),
        # Builder Base menu: two tabs only (Buildings & Heroes incl. walls, Star Laboratory)
        'bb_builders': (1275, 850), 'bb_lab': (1493, 850)}
COUNTER_BOX = 45                     # half width of the "free/total" counter under each tab icon
COUNTER_Y = (846, 880)
LIST_X = (1175, 1598)
LIST_Y = (60, 800)
CARD_PROBE_X = 1183                  # left edge inside the cards: brown = upgradable, green = running
MIN_CARD_HEIGHT = 40
COST_X = (1400, 1570)
SAFE_TAP = (1544, 578)              # empty ground: deselects a building
RED_PIXELS_UNAFFORDABLE = 25
WINDOW_CLOSE_REGION = (1240, 0, 1480, 130)   # home windows: X ~(1413,70); Builder Base windows: ~(1300,35)
CONFIRM_REGION = (950, 700, 1460, 860)
SCROLL = (1385, 700, 1385, 380)
MAX_SCROLLS = 6
MAX_PER_RUN = 3
INTERVAL_SECONDS = 1800

_state = {'next_run': {}, 'skip_rows': set()}


def _log(msg):
    print(f'[UPGRADE] {msg}')


def due(cfg, kind):
    key = {'builders': 'AUTO_UPGRADE_BUILDINGS', 'lab': 'AUTO_UPGRADE_LAB',
           'equipment': 'AUTO_UPGRADE_EQUIPMENT', 'pets': 'AUTO_UPGRADE_PETS',
           'bb_builders': 'BB_AUTO_UPGRADE', 'bb_lab': 'BB_AUTO_LAB'}[kind]
    return bool(cfg.get(key, False)) and time.time() >= _state['next_run'].get(kind, 0.0)


def _menu_open(vision):
    return vision.match_template_region((1540, 5, 1600, 55), 'upgrade_menu_close', 0.8) is not None


def open_menu(vision):
    if not _menu_open(vision):
        tap(*BUILD_BUTTON)
        # FIX: a fixed 1.5 s wait was too short on MEmu ("Build menu did not open" with the menu
        # opening a moment later). Poll for up to 4.5 s.
        for _ in range(6):
            time.sleep(0.75)
            if _menu_open(vision):
                return True
    return _menu_open(vision)


def close_menu(vision):
    for _ in range(3):
        if not _menu_open(vision):
            return
        tap(*MENU_CLOSE)
        time.sleep(0.8)


def tab_free_count(vision, screen, kind):
    """0 / 1 for the lab and pet counters ("0/1"): the first glyph is narrow for 1, wide for 0."""
    cx = TABS[kind][0]
    y1, y2 = COUNTER_Y
    hsv = cv2.cvtColor(screen[y1:y2, cx - COUNTER_BOX:cx + COUNTER_BOX], cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([0, 0, 200]), np.array([180, 60, 255]))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = sorted((cv2.boundingRect(c) for c in contours), key=lambda b: b[0])
    boxes = [b for b in boxes if b[3] >= 7]
    if not boxes:
        return None
    return 1 if boxes[0][2] <= 6 else 0


def find_cards(screen):
    """[(y1, y2), ...] of upgradable rows (brown cards, not the green in-progress rows)."""
    y1, y2 = LIST_Y
    col = screen[y1:y2, CARD_PROBE_X].astype(int)
    cards, start = [], None
    for i, (b, g, r) in enumerate(col):
        is_card = r > 100 and r > b + 25 and not (g > r + 30 and g > b + 30)
        if is_card and start is None:
            start = i
        elif not is_card and start is not None:
            if i - start >= MIN_CARD_HEIGHT:
                cards.append((y1 + start, y1 + i))
            start = None
    if start is not None and y2 - y1 - start >= MIN_CARD_HEIGHT:
        cards.append((y1 + start, y2))
    return cards


def card_affordable(screen, card):
    y1, y2 = card
    roi = screen[y1 + (y2 - y1) // 3:y2, COST_X[0]:COST_X[1]].astype(int)
    b, g, r = roi[..., 0], roi[..., 1], roi[..., 2]
    red = (r > 200) & (g < 140) & (b < 140)
    return int(red.sum()) < RED_PIXELS_UNAFFORDABLE


def _signature(screen, card):
    y1, y2 = card
    small = cv2.resize(cv2.cvtColor(screen[y1:y2, 1240:1460], cv2.COLOR_BGR2GRAY), (32, 8))
    return small.tobytes()


GREEN_BUTTON_REGION = (100, 330, 1500, 900)


def _green_button(screen):
    """Purchase button of an upgrade window without a "Confirm" label (Builder Base windows): a
    solid green button holding white digits and a gold or elixir icon. Grass, "Select" and
    "Defense Overview" buttons have no resource icon and are ignored. Returns (x, y) or None."""
    x1, y1, x2, y2 = GREEN_BUTTON_REGION
    hsv_all = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)
    hsv = hsv_all[y1:y2, x1:x2]
    mask = cv2.inRange(hsv, np.array([35, 110, 110]), np.array([85, 255, 255]))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((11, 11), np.uint8))
    n, _labels, stats, _c = cv2.connectedComponentsWithStats(mask)
    best = None
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if not (120 <= w <= 520 and 45 <= h <= 140 and area >= 0.45 * w * h):
            continue
        box = hsv_all[y1 + y:y1 + y + h, x1 + x:x1 + x + w]
        H, S, V = box[..., 0], box[..., 1], box[..., 2]
        white = float(((S < 50) & (V > 215)).mean())
        icon = float((((H >= 125) & (H <= 165) & (S > 80) & (V > 80)) |
                      ((H >= 18) & (H <= 32) & (S > 150) & (V > 170))).mean())
        if white < 0.03 or icon < 0.015:
            continue
        if best is None or area > best[0]:
            best = (area, x1 + x + w // 2, y1 + y + h // 2, w, h)
    if not best:
        return None
    _area, cx, cy, w, h = best
    cost = screen[cy - h // 2:cy + h // 2, cx - w // 2:cx + w // 2].astype(int)
    red = ((cost[..., 2] > 200) & (cost[..., 1] < 140) & (cost[..., 0] < 140)).sum()
    return None if red >= RED_PIXELS_UNAFFORDABLE else (cx, cy)


def _green_confirm(vision, screen):
    """Centre of the green resource Confirm button, or None (never the grey hammer button)."""
    tpl = vision.templates.get('upgrade_confirm_label')
    if not tpl:
        return _green_button(screen)
    x1, y1, x2, y2 = CONFIRM_REGION
    gray = cv2.cvtColor(screen[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    res = cv2.matchTemplate(gray, tpl['img'], cv2.TM_CCOEFF_NORMED)
    for _ in range(3):
        _mn, score, _ml, loc = cv2.minMaxLoc(res)
        if score < 0.7:
            return _crafted_confirm(screen, tpl) or _green_button(screen)
        cx, cy = x1 + loc[0] + tpl['w'] // 2, y1 + loc[1] + tpl['h'] // 2
        # Green button: a large share of green-hue pixels (the grey hammer button has none).
        hsv = cv2.cvtColor(screen[cy - 15:cy + 50, cx - 110:cx + 110], cv2.COLOR_BGR2HSV)
        green = ((hsv[..., 0] >= 35) & (hsv[..., 0] <= 85) & (hsv[..., 1] >= 90)).mean()
        if green >= 0.35:
            cost = screen[cy + 10:cy + 50, cx - 110:cx + 110].astype(int)
            red = ((cost[..., 2] > 200) & (cost[..., 1] < 140) & (cost[..., 0] < 140)).sum()
            if red >= RED_PIXELS_UNAFFORDABLE:
                return None              # cost on the button is red: not affordable
            return cx, cy + 20
        res[max(0, loc[1] - 20):loc[1] + 20, max(0, loc[0] - 60):loc[0] + 60] = -1
    return None


CRAFTED_REGION = (750, 140, 1460, 860)
CRAFTED_SCALE = 0.75


def _crafted_confirm(screen, tpl):
    """Crafted defenses (e.g. Hot Candle): the window lists the module stats, and the selected
    row's Confirm button sits mid-window with its label drawn at 75%, so the normal search near
    the bottom misses it (skipped every visit since 27 Oct). Same green / red-cost checks."""
    small = cv2.resize(tpl['img'], None, fx=CRAFTED_SCALE, fy=CRAFTED_SCALE, interpolation=cv2.INTER_AREA)
    x1, y1, x2, y2 = CRAFTED_REGION
    gray = cv2.cvtColor(screen[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    _mn, score, _ml, loc = cv2.minMaxLoc(cv2.matchTemplate(gray, small, cv2.TM_CCOEFF_NORMED))
    if score < 0.7:
        return None
    cx, cy = x1 + loc[0] + small.shape[1] // 2, y1 + loc[1] + small.shape[0] // 2
    hsv = cv2.cvtColor(screen[cy - 12:cy + 38, cx - 80:cx + 80], cv2.COLOR_BGR2HSV)
    if ((hsv[..., 0] >= 35) & (hsv[..., 0] <= 85) & (hsv[..., 1] >= 90)).mean() < 0.35:
        return None
    cost = screen[cy + 8:cy + 38, cx - 80:cx + 80].astype(int)
    if ((cost[..., 2] > 200) & (cost[..., 1] < 140) & (cost[..., 0] < 140)).sum() >= RED_PIXELS_UNAFFORDABLE:
        return None
    return cx, cy + 15


def _close_window(vision):
    for _ in range(2):
        x = vision.match_template_region(WINDOW_CLOSE_REGION, 'upgrade_window_close', 0.55)
        if not x:
            return
        tap(*x)
        time.sleep(0.8)


def _save(screen, tag):
    os.makedirs('logs', exist_ok=True)
    path = os.path.join('logs', f"upgrade_{tag}_{time.strftime('%H-%M-%S')}.png")
    cv2.imwrite(path, screen)
    return path


def _free_count(vision, kind, screen=None):
    """Free builders / lab / pet slots for the success check (None when unreadable)."""
    if kind in ('builders', 'bb_builders'):
        return vision.read_builders_free(screen)
    if kind in ('lab', 'pets', 'bb_lab'):
        return tab_free_count(vision, screen if screen is not None else vision.grab(), kind)
    return None


def _try_card(vision, screen, card, kind, dry_run, free_before=None):
    sig = _signature(screen, card)
    if sig in _state['skip_rows']:
        return False
    y1, y2 = card
    tap((LIST_X[0] + LIST_X[1]) // 2, (y1 + y2) // 2)
    time.sleep(1.5)
    window = vision.grab()
    # With no builder free the row only selects the building (no window): never "confirm" there.
    if not vision.match_template(window, 'upgrade_window_close', 0.55, region=WINDOW_CLOSE_REGION):
        _log(f'{kind}: row at y={y1} opened no upgrade window')
        tap(*SAFE_TAP)
        time.sleep(0.6)
        return False
    confirm = _green_confirm(vision, window)
    if not confirm:
        _state['skip_rows'].add(sig)    # crafting station, max level, ... : skip this session
        _log(f'{kind}: row at y={y1} has no affordable Confirm, window saved to {_save(window, "skip")}')
        _close_window(vision)
        return False
    if dry_run:
        _log(f'{kind}: dry run, would confirm at {confirm}')
        _close_window(vision)
        return True
    tap(*confirm)
    time.sleep(1.5)
    after = vision.grab()
    if vision.match_template_region(WINDOW_CLOSE_REGION, 'upgrade_window_close', 0.55):
        # Still open: a follow-up (gems / not enough resources). Never buy with gems.
        _log(f'{kind}: confirm did not go through, saved {_save(after, "stuck")}')
        _close_window(vision)
        return False
    close_menu(vision)
    time.sleep(1.0)
    # Success check as in MyBot: the free counter must have dropped.
    if free_before is not None and kind != 'equipment':
        now = _free_count(vision, kind)
        if now is not None and now >= free_before:
            _state['skip_rows'].add(sig)
            _log(f'{kind}: counter did not drop ({free_before} -> {now}), upgrade not started')
            return False
    _log(f'{kind}: upgrade started')
    return True


def run_tab(vision, cfg, kind, free=None, dry_run=False):
    """Start up to `free` upgrades from one tab. Returns how many were started."""
    _state['next_run'][kind] = time.time() + INTERVAL_SECONDS
    if not open_menu(vision):
        _log('Build menu did not open')
        return 0
    tap(*TABS[kind])
    time.sleep(1.2)
    screen = vision.grab()
    if free is None:
        free = tab_free_count(vision, screen, kind) if kind in ('lab', 'pets', 'bb_lab') else MAX_PER_RUN
    if not free:
        _log(f'{kind}: nothing free')
        close_menu(vision)
        return 0
    started = 0
    tried_y = set()            # rows already opened in this run (some rows animate, e.g. crafting)
    scrolled = 0
    for _scroll in range(MAX_SCROLLS + 4):
        for card in find_cards(screen):
            key_y = (scrolled, card[0] // 20)
            if (not card_affordable(screen, card) or key_y in tried_y
                    or _signature(screen, card) in _state['skip_rows']):
                continue
            tried_y.add(key_y)
            free_before = None if dry_run else _free_count(vision, kind, screen)
            if _try_card(vision, screen, card, kind, dry_run, free_before):
                started += 1
                if dry_run or started >= min(free, MAX_PER_RUN):
                    close_menu(vision)
                    return started
            # Closing an upgrade window also closes the Build menu: reopen it on the same tab
            # and rescan from the top (the list changes after an upgrade starts).
            if not open_menu(vision):
                return started
            tap(*TABS[kind])
            time.sleep(1.2)
            for _ in range(scrolled):
                swipe(*SCROLL, duration=500)
                time.sleep(0.8)
            screen = vision.grab()
            break
        else:
            if scrolled >= MAX_SCROLLS:
                break
            swipe(*SCROLL, duration=500)
            scrolled += 1
            time.sleep(1.0)
            screen = vision.grab()
            continue
    close_menu(vision)
    if not started:
        _log(f'{kind}: no affordable upgrade found')
    return started


def run_bb(vision, cfg, dry_run=False):
    """Builder Base upgrades (call while on the Builder Base)."""
    total = 0
    if due(cfg, 'bb_builders'):
        free = vision.read_builders_free()
        if free:
            total += run_tab(vision, cfg, 'bb_builders', free, dry_run)
        else:
            _state['next_run']['bb_builders'] = time.time() + INTERVAL_SECONDS
    if due(cfg, 'bb_lab'):
        total += run_tab(vision, cfg, 'bb_lab', None, dry_run)
    return total


def run(vision, cfg, dry_run=False):
    """Run every enabled tab. Builders use the home-screen free-builder counter."""
    total = 0
    if due(cfg, 'builders'):
        free = vision.read_builders_free()
        reserve = int(cfg.get('AUTO_UPGRADE_KEEP_BUILDERS', 0) or 0)
        free = None if free is None else max(0, free - reserve)
        if free:
            total += run_tab(vision, cfg, 'builders', free, dry_run)
        else:
            _state['next_run']['builders'] = time.time() + INTERVAL_SECONDS
    for kind in ('lab', 'pets', 'equipment'):
        if due(cfg, kind):
            total += run_tab(vision, cfg, kind, None if kind != 'equipment' else 1, dry_run)
    return total
