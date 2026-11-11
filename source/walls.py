# walls.py -- reconstructed from statically-decrypted Pyarmor bytecode (ACBot Basic v1.6.7)
# Python 3.10. Pyarmor enter/exit wrappers stripped; local names re-chosen from usage.
import time
import random
import numpy as np
import cv2
from actions import click_point, click_point_raw, open_home_menu, close_home_menu, close_home_menu_and_reset
import fixed_points as fp

MAX_SCROLLS = 8
MAX_SEARCH_LOOPS = 11
MAX_CLICKS = 15
WALL_DEBUG = False
COST_CHECK_Y_OFFSET = -38
COST_CHECK_WIDTH = 38
COST_CHECK_HEIGHT = 15
COST_CHECK_X_OFFSET = 30
ADD1_CHECK_X_OFFSET = 0
ADD1_CHECK_Y_OFFSET = 52
WALL_COST_ROI_DEBUG = False
WALL_UPGRADE_BOTTOM_THRESHOLD = 0.85
WALL_NO_SCROLL_Y_CENTER_THRESHOLD = 690
WALL_LOOT_BAR_READY_THRESHOLD = 0.9
# FIX: once every wall is at the highest level the game allows, "Wall" disappears from the upgrade
# list. Storages then stay full, so the original searched the whole list (~2.5 min) before every
# attack and found nothing. After a search finds no wall at all, skip the wall step for this long.
WALL_NONE_RECHECK_SECONDS = 3600
_no_walls_until = 0.0


def _random_point_in_region(region):
    x1, y1, x2, y2 = [int(v) for v in region]
    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1
    # Humanization: uniformly random point inside the swipe region.
    return (random.randint(x1, x2), random.randint(y1, y2))


def _scroll_wall_list_down(adb):
    x1, y1 = _random_point_in_region(fp.HOME_UPGRADE_LIST_BOTTOM_REGION)
    x2, y2 = _random_point_in_region(fp.HOME_UPGRADE_LIST_TOP_REGION)
    adb.swipe(x1, y1, x2, y2, 150)


def _scroll_wall_list_up(adb):
    x1, y1 = _random_point_in_region(fp.HOME_UPGRADE_LIST_UP_START_REGION)
    x2, y2 = _random_point_in_region(fp.HOME_UPGRADE_LIST_BOTTOM_REGION)
    y2 -= int(fp.HOME_LIST_SCROLL_UP_SHORTEN_PX)
    adb.swipe(x1, y1, x2, y2, 600)


def cost_region_from_gold_button(gold_btn):
    x, y = gold_btn
    y = y + COST_CHECK_Y_OFFSET
    x = x + COST_CHECK_X_OFFSET
    half_w = COST_CHECK_WIDTH // 2
    half_h = COST_CHECK_HEIGHT // 2
    return (x - half_w, y - half_h, x + half_w, y + half_h)


def cost_region_from_elixir_button(elixir_btn):
    x, y = elixir_btn
    y = y + COST_CHECK_Y_OFFSET
    x = x + COST_CHECK_X_OFFSET
    half_w = COST_CHECK_WIDTH // 2
    half_h = COST_CHECK_HEIGHT // 2
    return (x - half_w, y - half_h, x + half_w, y + half_h)


def cost_region_from_add_button(add1_btn):
    x, y = add1_btn
    y = y + ADD1_CHECK_Y_OFFSET
    x = x + ADD1_CHECK_X_OFFSET
    half_w = COST_CHECK_WIDTH // 2
    half_h = COST_CHECK_HEIGHT // 2
    return (x - half_w, y - half_h, x + half_w, y + half_h)


def save_cost_roi_debug_image(vision, region, tag):
    if not WALL_DEBUG:
        return None
    screen = vision.grab()
    if screen is None or screen.size == 0:
        return None
    x1, y1, x2, y2 = region
    x1 = max(0, x1)
    y1 = max(0, y1)
    x2 = min(screen.shape[1] - 1, x2)
    y2 = min(screen.shape[0] - 1, y2)
    debug_img = screen.copy()
    cv2.rectangle(debug_img, (x1, y1), (x2, y2), (0, 255, 255), 2)
    cv2.putText(debug_img, f'cost-roi:{tag}', (x1, max(20, y1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
    ts = int(time.time() * 1000)
    filename = f'debug_wall_cost_roi_{tag}_{ts}.png'
    cv2.imwrite(filename, debug_img)
    print(f'[WALL]Saved debug ROI image: {filename}')


def _get_storage_fill_ratios(vision):
    ratios = vision.get_loot_bar_fill_ratios()
    return {'gold': ratios.get('gold', 0.0), 'elixir': ratios.get('elixir', 0.0)}


def find_upgrade_buttons(vision):
    v = vision
    screen = v.grab()
    buttons = v.match_two_templates(screen, 'wall_chain', 0.8)
    if not buttons:
        buttons = v.match_two_templates(screen, 'wall_single', 0.8)
    if not buttons:
        return (None, None)
    # Sorted left-to-right: first = gold upgrade button, second = elixir upgrade button.
    buttons.sort(key=lambda p: p[0])
    gold_btn = buttons[0] if len(buttons) > 0 else None
    elixir_btn = buttons[1] if len(buttons) > 1 else None
    return (gold_btn, elixir_btn)


def find_wall_adjust_buttons(vision):
    v = vision
    add1_btn = v.match_template_region(fp.WALL_BUTTON_REGION, 'wall_add1', 0.7)
    add10_btn = v.match_template_region(fp.WALL_BUTTON_REGION, 'wall_add10', 0.7)
    if add1_btn and add10_btn and add10_btn[0] >= add1_btn[0]:
        add10_btn = None
    remove_btn = v.match_template_region(fp.WALL_BUTTON_REGION, 'wall_remove', 0.7)
    return (add1_btn, add10_btn, remove_btn)


def should_scroll_wall_list(vision):
    # RECON: bytecode body is only `return True` (source lines 44-53 were compiled
    # away as unreachable). co_names still reference match_template_region,
    # fp.WALL_UPGRADE_BOTTOM_SEARCH_REGION, WALL_UPGRADE_BOTTOM_THRESHOLD,
    # WALL_DEBUG, print and WALL_NO_SCROLL_Y_CENTER_THRESHOLD, i.e. a disabled
    # "small panel" detector existed in source but is dead code in this build.
    return True


def find_wall_entry(adb, vision, pause_if_needed=None):
    pause = pause_if_needed
    v = vision
    dev = adb
    for attempt in range(2):
        open_home_menu(dev)
        can_scroll = should_scroll_wall_list(v)
        if can_scroll:
            # Scroll builder/upgrade list fully to the bottom first.
            for _ in range(MAX_SCROLLS):
                _scroll_wall_list_down(dev)
                time.sleep(0.5)
        for _ in range(MAX_SEARCH_LOOPS):
            if callable(pause):
                pause()
            time.sleep(1)
            wall_pos = v.find_wall_upgrade()
            if wall_pos:
                print('[WALL]Found wall upgrade')
                click_point_raw(dev, wall_pos)
                time.sleep(0.5)
                close_home_menu(dev)
                time.sleep(1)
                level = v.detect_wall_level()
                print(f'[WALL]Detected level {level} wall')
                more_btn = v.match_template_region(fp.WALL_BUTTON_REGION, 'upgrade_more', 0.85)
                if more_btn:
                    screen = v.grab()
                    bx, by = more_btn
                    pad = 10
                    x1 = max(bx - pad, 0)
                    y1 = max(by - pad, 0)
                    x2 = min(bx + pad, screen.shape[1])
                    y2 = min(by + pad, screen.shape[0])
                    roi = screen[y1:y2, x1:x2]
                    h, w = roi.shape[:2]
                    roi = roi[h // 4:3 * h // 4, w // 4:3 * w // 4]
                    avg = roi.mean(axis=(0, 1))
                    b, g, r = avg
                    if WALL_DEBUG:
                        print(f'[WALL] avg BGR at button: {avg}')
                    if r > 180 and r > g + 40:
                        # "Select more" button is red -> only a single wall can be afforded.
                        if WALL_DEBUG:
                            print('[WALL] RED button → upgrading single')
                        gold_btn, elixir_btn = find_upgrade_buttons(v)
                        if gold_btn is not None:
                            click_point(dev, gold_btn)
                            time.sleep(0.3)
                            click_point(dev, fp.WALL_CONFIRM_BUTTON)
                            time.sleep(0.5)
                            print('[WALL] Final wall upgraded')
                            return True
                        # RECON: falls through to the scroll logic below when no gold button found
                    else:
                        if WALL_DEBUG:
                            print('[WALL] GREY button → opening more')
                        click_point(dev, more_btn)
                        time.sleep(0.5)
                        return True
            if not can_scroll:
                print('[WALL]Scroll disabled in small panel mode')
                break
            _scroll_wall_list_up(dev)
            time.sleep(1.5)
        if attempt == 0:
            print('[WALL]Wall not found on first pass, retrying search')
        if callable(pause):
            pause()
    print('[WALL]No more walls')
    close_home_menu_and_reset(dev, v)
    return False


def perform_wall_upgrade(adb, vision, stats, use_gold, use_elixir):
    v = vision
    dev = adb
    gold_btn, elixir_btn = find_upgrade_buttons(v)
    if gold_btn is None and elixir_btn is None:
        print('[WALL]Upgrade buttons not detected')
        return None
    if gold_btn is not None and elixir_btn is None:
        if use_elixir and not use_gold:
            print('[WALL]Elixir upgrade not available')
            return None
        use_elixir = False

    add1_btn, add10_btn, remove_btn = find_wall_adjust_buttons(v)
    if not add1_btn or not remove_btn:
        print('[WALL]Adjust buttons not detected')
        return None

    gold_region = cost_region_from_gold_button(gold_btn) if gold_btn is not None else None
    elixir_region = cost_region_from_elixir_button(elixir_btn) if elixir_btn is not None else None
    add1_region = cost_region_from_add_button(add1_btn)
    add10_region = cost_region_from_add_button(add10_btn) if add10_btn is not None else None
    if gold_region is not None:
        save_cost_roi_debug_image(v, gold_region, 'gold_base')
    if elixir_region is not None:
        save_cost_roi_debug_image(v, elixir_region, 'elixir_base')
    save_cost_roi_debug_image(v, add1_region, 'add1_base')
    if add10_region is not None:
        save_cost_roi_debug_image(v, add10_region, 'add10_base')

    # ---------------- GOLD ----------------
    if use_gold and gold_btn is not None:
        count = 0
        while True:
            can_add10 = add10_btn is not None and not v.is_cost_red(add10_region)
            if add10_btn is not None and not can_add10:
                save_cost_roi_debug_image(v, add10_region, 'gold_add10_blocked')
            if can_add10:
                click_point(dev, add10_btn)
                count += 10
                time.sleep(0.1)
                continue
            if v.is_cost_red(add1_region):
                save_cost_roi_debug_image(v, add1_region, 'gold_add1_blocked')
                if v.is_cost_red(gold_region):
                    save_cost_roi_debug_image(v, gold_region, 'gold_upgrade_blocked')
                    while count > 0 and v.is_cost_red(gold_region):
                        click_point(dev, remove_btn)
                        count -= 1
                        time.sleep(0.2)
                    time.sleep(0.3)
                break
            click_point(dev, add1_btn)
            count += 1
            time.sleep(0.1)
            if v.is_cost_red(gold_region):
                save_cost_roi_debug_image(v, gold_region, 'gold_upgrade_blocked')
                while count > 0 and v.is_cost_red(gold_region):
                    click_point(dev, remove_btn)
                    count -= 1
                    time.sleep(0.2)
                time.sleep(0.3)
                break
        if count <= 0 and v.is_cost_red(gold_region):
            save_cost_roi_debug_image(v, gold_region, 'gold_upgrade_blocked')
            print('[WALL]Aborting')
            close_home_menu_and_reset(dev, v)
            return 'aborted'
        print('[WALL]Attempting GOLD upgrade')
        save_cost_roi_debug_image(v, gold_region, 'gold_upgrade_affordable')
        click_point(dev, gold_btn)
        time.sleep(0.5)
        screen = v.grab()
        okay = v.match_template(screen, 'okay_button', 0.85)
        if okay:
            click_point(dev, okay)
            print('[WALL]Successfully upgraded using GOLD')
            if stats:
                stats.walls_upgraded += count + 1

    # ---------------- ELIXIR ----------------
    if use_elixir and elixir_btn is not None:
        count = 0
        while True:
            can_add10 = add10_btn is not None and not v.is_cost_red(add10_region)
            if add10_btn is not None and not can_add10:
                save_cost_roi_debug_image(v, add10_region, 'elixir_add10_blocked')
            if can_add10:
                click_point(dev, add10_btn)
                count += 10
                time.sleep(0.15)
                continue
            if v.is_cost_red(add1_region):
                save_cost_roi_debug_image(v, add1_region, 'elixir_add1_blocked')
                if v.is_cost_red(elixir_region):
                    save_cost_roi_debug_image(v, elixir_region, 'elixir_upgrade_blocked')
                    while count > 0 and v.is_cost_red(elixir_region):
                        click_point(dev, remove_btn)
                        count -= 1
                        time.sleep(0.2)
                    time.sleep(0.3)
                break
            click_point(dev, add1_btn)
            count += 1
            time.sleep(0.15)
            if v.is_cost_red(elixir_region):
                save_cost_roi_debug_image(v, elixir_region, 'elixir_upgrade_blocked')
                while count > 0 and v.is_cost_red(elixir_region):
                    click_point(dev, remove_btn)
                    count -= 1
                    time.sleep(0.2)
                time.sleep(0.3)
                break
        if count <= 0 and v.is_cost_red(elixir_region):
            save_cost_roi_debug_image(v, elixir_region, 'elixir_upgrade_blocked')
            print('[WALL]Aborting')
            close_home_menu_and_reset(dev, v)
            return 'aborted'
        print('[WALL]Attempting ELIXIR upgrade')
        save_cost_roi_debug_image(v, elixir_region, 'elixir_upgrade_affordable')
        click_point(dev, elixir_btn)
        time.sleep(0.5)
        screen = v.grab()
        okay = v.match_template(screen, 'okay_button', 0.85)
        if okay:
            click_point(dev, okay)
            print('[WALL]Successfully upgraded using ELIXIR')
            if stats:
                stats.walls_upgraded += count + 1
    return None


def upgrade_walls(adb, vision, stats=None, cfg=None, pause_if_needed=None):
    global _no_walls_until
    pause = pause_if_needed
    st = stats
    dev = adb
    v = vision
    if time.time() < _no_walls_until:
        return None  # FIX: no upgradeable walls on the last search (logged then)
    print('[WALL]Checking loot for wall upgrades')
    ratios = _get_storage_fill_ratios(v)
    gold_ratio = ratios.get('gold', 0.0)
    elixir_ratio = ratios.get('elixir', 0.0)
    gold_ready = gold_ratio >= WALL_LOOT_BAR_READY_THRESHOLD
    elixir_ready = elixir_ratio >= WALL_LOOT_BAR_READY_THRESHOLD
    if not gold_ready and not elixir_ready:
        print('[WALL]Insufficient loot for wall upgrades, waiting for 90%')
        return None
    if gold_ready and elixir_ready:
        print('[WALL]Sufficient Gold/Elixir detected, starting wall upgrades')
    elif gold_ready:
        print('[WALL]Sufficient Gold detected, starting wall upgrades')
    else:
        print('[WALL]Sufficient Elixir detected, starting wall upgrades')
    if gold_ready:
        if find_wall_entry(dev, v, pause_if_needed=pause):
            if perform_wall_upgrade(dev, v, st, use_gold=True, use_elixir=False) == 'aborted':
                return None
        else:
            elixir_ready = False  # FIX: the list had no wall at all; the elixir pass would search it again
            _no_walls_until = time.time() + WALL_NONE_RECHECK_SECONDS
    if elixir_ready:
        if find_wall_entry(dev, v, pause_if_needed=pause):
            if perform_wall_upgrade(dev, v, st, use_gold=False, use_elixir=True) == 'aborted':
                return None
        else:
            _no_walls_until = time.time() + WALL_NONE_RECHECK_SECONDS
    if _no_walls_until > time.time():
        print('[WALL]No upgradeable walls, skipping wall upgrades until '
              + time.strftime('%H:%M', time.localtime(_no_walls_until)))
    close_home_menu_and_reset(dev, v)
    print('[WALL]Wall upgrades finished')
    return None
