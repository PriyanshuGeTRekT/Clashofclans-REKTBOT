# obstacles.py - remove obstacles (trees, bushes, rocks, ...) on the home village (Pro feature).
#
# MyBot PHMOD CleanBBYard / CheckTombs: image-search obstacles, tap one, tap "Remove" in the info
# bar, repeat. Here each obstacle kind is a template in templates/obstacles/ (cut from the village at
# the zoomed-out home view). Tapping an obstacle selects it and shows its info bar with a green
# "Remove" button (templates/obstacles/obstacle_remove_button.png, captured on first use: when the
# bar is not recognised, the screen is saved to logs/obstacle_bar_*.png for cutting it).
# Removing costs resources and a builder; the pass stops when no builder is free.
import glob
import os
import time

import cv2

from adb import tap

TEMPLATE_DIR = os.path.join('templates', 'obstacles')
MATCH_THRESHOLD = 0.8
HUD = ((0, 0, 360, 320), (1230, 0, 1600, 330), (0, 380, 160, 660), (0, 700, 340, 900),
       (340, 780, 820, 900), (1270, 380, 1600, 900))
REMOVE_REGION = (300, 600, 1300, 800)
SAFE_TAP = (1544, 578)
INTERVAL_SECONDS = 1800
MAX_PER_RUN = 3

_state = {'next_run': 0.0}


def _log(msg):
    print(f'[OBSTACLE] {msg}')


def due(cfg):
    return bool(cfg.get('REMOVE_OBSTACLES', False)) and time.time() >= _state['next_run']


def _templates():
    out = {}
    for path in glob.glob(os.path.join(TEMPLATE_DIR, 'obstacle_*.png')):
        name = os.path.splitext(os.path.basename(path))[0]
        if name == 'obstacle_remove_button':
            continue
        img = cv2.imread(path)
        if img is not None:
            out[name] = img
    return out


def find_obstacles(screen):
    """[(name, (x, y)), ...] of obstacle templates found on the village."""
    search = screen.copy()
    for x1, y1, x2, y2 in HUD:
        search[y1:y2, x1:x2] = 0
    found = []
    import zoomnorm                       # scenery that zooms out less than the reference
    for name, tpl in _templates().items():
        res, tpl = zoomnorm.match_world(search, tpl, MATCH_THRESHOLD)
        h, w = tpl.shape[:2]
        for _ in range(10):
            _mn, score, _ml, loc = cv2.minMaxLoc(res)
            if score < MATCH_THRESHOLD:
                break
            found.append((name, (loc[0] + w // 2, loc[1] + h // 2)))
            res[max(0, loc[1] - h):loc[1] + h, max(0, loc[0] - w):loc[0] + w] = -1
    return found


def _remove_selected(vision):
    screen = vision.grab()
    button = vision.match_template(screen, 'obstacle_remove_button', 0.8, region=REMOVE_REGION)
    if not button:
        os.makedirs('logs', exist_ok=True)
        path = os.path.join('logs', f"obstacle_bar_{time.strftime('%H-%M-%S')}.png")
        cv2.imwrite(path, screen)
        _log(f'Remove button not recognised, saved {path}')
        return False
    tap(*button)
    time.sleep(1.0)
    return True


def run(vision, cfg):
    _state['next_run'] = time.time() + INTERVAL_SECONDS
    if not _templates():
        _log('No obstacle templates in templates/obstacles yet')
        return 0
    removed = 0
    for _ in range(MAX_PER_RUN):
        free = vision.read_builders_free()
        if free is not None and free <= 0:
            _log('No free builder')
            break
        found = find_obstacles(vision.grab())
        if not found:
            break
        name, pos = found[0]
        tap(*pos)
        time.sleep(1.0)
        if _remove_selected(vision):
            removed += 1
            _log(f'Removing {name[len("obstacle_"):]}')
        tap(*SAFE_TAP)
        time.sleep(0.8)
    if removed:
        _log(f'{removed} obstacle(s) queued for removal')
    return removed
