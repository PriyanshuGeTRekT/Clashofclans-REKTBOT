# collect.py - collect resources, the loot cart and the gem box (new module, Pro feature).
#
# MyBot PHMOD: Collect.au3 / CheckTombs.au3 / the loot cart. Re-implemented on our 1600x900 home view:
#   * full collectors show a gold / elixir / dark elixir bubble; tapping a bubble collects that
#     collector (templates/collect/collect_bubble_*.png, matched in colour so the three never mix).
#   * the loot cart shows a "Collect" label; tapping the cart opens a window with a Collect button.
#   * a gem box / gem mine shows a blue gem bubble.
# Each bubble is tapped once per pass; the pass repeats until nothing is left (max 3 passes).
import os
import time

import cv2

from adb import tap

BUBBLES = ('collect_bubble_gold', 'collect_bubble_elixir', 'collect_bubble_dark', 'collect_bubble_gem')
BUBBLE_THRESHOLD = 0.78
# HUD panels (x1, y1, x2, y2) masked out of the search.
HUD = ((0, 0, 360, 320), (1230, 0, 1600, 330), (0, 380, 160, 660), (0, 700, 340, 900),
       (340, 780, 820, 900), (1270, 380, 1600, 900))
CART_LABEL_TO_CART_DY = 40
CART_WINDOW_REGION = (500, 500, 1100, 800)
INTERVAL_SECONDS = 600
SAFE_TAP = (1544, 578)        # fixed_points.SAFE_CLOSE_POINT: empty ground, deselects buildings

_state = {'next_run': 0.0}


def _log(msg):
    print(f'[COLLECT] {msg}')


def due(cfg):
    return bool(cfg.get('COLLECT_RESOURCES', False)) and time.time() >= _state['next_run']


def _find_all(vision, screen, key, threshold=BUBBLE_THRESHOLD):
    tpl = vision.colour_templates.get(key) if hasattr(vision, 'colour_templates') else None
    if tpl is None:
        path = os.path.join('templates', 'collect', f'{key}.png')
        if not os.path.exists(path):      # optional template (e.g. the BB cart before it is cut)
            return []
        tpl = cv2.imread(path)
        if tpl is None:
            return []
        if not hasattr(vision, 'colour_templates'):
            vision.colour_templates = {}
        vision.colour_templates[key] = tpl
    search = screen.copy()
    for x1, y1, x2, y2 in HUD:
        search[y1:y2, x1:x2] = 0
    import zoomnorm                       # scenery that zooms out less than the reference
    res, tpl = zoomnorm.match_world(search, tpl, threshold)
    h, w = tpl.shape[:2]
    hits = []
    while len(hits) < 20:
        _mn, score, _ml, loc = cv2.minMaxLoc(res)
        if score < threshold:
            break
        hits.append((loc[0] + w // 2, loc[1] + h // 2))
        res[max(0, loc[1] - h):loc[1] + h, max(0, loc[0] - w):loc[0] + w] = -1
    return hits


def _collect_cart(vision, screen):
    label = _find_all(vision, screen, 'collect_label', 0.75)
    if not label:
        return False
    x, y = label[0]
    tap(x, y + CART_LABEL_TO_CART_DY)
    time.sleep(1.5)
    window = vision.grab()
    button = vision.match_template(window, 'collect_cart_button', 0.8, region=CART_WINDOW_REGION)
    if button:
        tap(*button)
        _log('Loot cart collected')
    else:
        os.makedirs('logs', exist_ok=True)
        path = os.path.join('logs', f"loot_cart_{time.strftime('%H-%M-%S')}.png")
        cv2.imwrite(path, window)
        _log(f'Loot cart window not recognised, saved {path}')
    time.sleep(1.0)
    _close_popup(vision)
    return True


def _deselect(vision):
    """A tap on a collector whose storage is full selects the building instead: tap empty space so
    the next tap cannot land on its info bar (Lab Assistant, Upgrade, ...), and close any window."""
    tap(*SAFE_TAP)
    time.sleep(0.5)
    _close_popup(vision)


BB_BUBBLES = ('collect_bubble_bb_gold', 'collect_bubble_bb_elixir')


def run_bb(vision):
    """Builder Base collectors (one tap per type, like the home village)."""
    taps = 0
    for key in BB_BUBBLES:
        hits = _find_all(vision, vision.grab(), key)
        if hits:
            tap(*hits[0])
            taps += 1
            time.sleep(0.8)
            _deselect(vision)
    if taps:
        _log(f'Builder Base: collected {taps} resource type(s)')
    return taps


BB_CART_SEARCH = (300, 60, 1300, 500)      # the cart sits above the base, under the resource bars
BB_CART_BUTTON_REGION = (300, 600, 1300, 800)


def collect_bb_cart(vision):
    """Builder Base Elixir Cart: the elixir won in battles lands here and is only banked when the
    cart is tapped and its "Collect" button pressed (MyBot PHMOD Collect.au3, elixir cart).
    Template: templates/collect/collect_bb_cart.png. Until it exists the screen is saved once per
    run to logs/bb_cart_<time>.png so the cart can be cut from a live frame."""
    screen = vision.grab()
    cart = _find_all(vision, screen, 'collect_bb_cart', 0.75)
    if not cart:
        if not _state.get('bb_cart_saved'):
            _state['bb_cart_saved'] = True
            os.makedirs('logs', exist_ok=True)
            path = os.path.join('logs', f"bb_cart_{time.strftime('%H-%M-%S')}.png")
            cv2.imwrite(path, screen)
            _log(f'Builder Base elixir cart not found (template missing or cart empty), saved {path}')
        return False
    x, y = cart[0]
    tap(x, y)
    time.sleep(1.2)
    bar = vision.grab()
    # The info bar has a green "Collect" button (same look as the home loot cart's).
    button = vision.match_template(bar, 'collect_cart_button', 0.75, region=BB_CART_BUTTON_REGION)
    if not button:
        from upgrades import _green_button
        button = _green_button(bar)
    if not button:
        os.makedirs('logs', exist_ok=True)
        path = os.path.join('logs', f"bb_cart_bar_{time.strftime('%H-%M-%S')}.png")
        cv2.imwrite(path, bar)
        _log(f'Elixir cart bar not recognised, saved {path}')
        _deselect(vision)
        return False
    tap(*button)
    time.sleep(1.0)
    _log('Builder Base elixir cart collected')
    _deselect(vision)
    return True


def run(vision, cfg):
    """Collect everything visible on the (zoomed-out) home village. Returns the number of taps.

    One tap per resource type: the game collects every collector of that type at once. A type
    whose bubbles stay after the tap has a full storage and is left alone."""
    _state['next_run'] = time.time() + INTERVAL_SECONDS
    taps = 0
    for key in BUBBLES:
        hits = _find_all(vision, vision.grab(), key)
        if not hits:
            continue
        tap(*hits[0])
        taps += 1
        time.sleep(0.8)
        _deselect(vision)
        left = _find_all(vision, vision.grab(), key)
        name = key.rsplit('_', 1)[1]
        if len(left) >= len(hits):
            _log(f'{name}: storage full, not collected')
        else:
            _log(f'{name}: collected from {len(hits) - len(left)} collector(s)')
    if cfg.get('COLLECT_LOOT_CART', True):
        _collect_cart(vision, vision.grab())
        _deselect(vision)
    return taps


def _close_popup(vision):
    """Close a window opened from the village (red X at the top right), if any."""
    for _ in range(2):
        x = vision.match_template_region((1100, 0, 1600, 200), 'upgrade_window_close', 0.8)
        if not x:
            return
        tap(*x)
        time.sleep(0.8)
