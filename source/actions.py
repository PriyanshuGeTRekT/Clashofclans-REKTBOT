# Reconstructed from Pyarmor-decrypted bytecode (actions, Python 3.10).
import random
import time
import fixed_points as fp


def is_home_menu_open(screen):
    img = screen
    if img is None or img.size == 0:
        return False
    x1, y1, x2, y2 = fp.HOME_MENU_OPEN_CHECK_REGION
    crop = img[y1:y2, x1:x2].astype(int)
    b, g, r = crop[:, :, 0], crop[:, :, 1], crop[:, :, 2]
    return float(((r > 170) & (g < 90) & (b < 90)).mean()) >= fp.HOME_MENU_OPEN_MIN_RED_FRACTION


def open_home_menu(adb):
    a = adb
    if not is_home_menu_open(a.screenshot()):
        click_point(a, fp.HOME_BUILD_BUTTON)
        time.sleep(1.5)
    click_point(a, fp.HOME_MENU_BUILDERS_TAB)
    time.sleep(1)


def close_home_menu(adb, vision=None):
    v = vision
    if v is not None and not is_home_menu_open(v.grab()):
        return
    click_point(adb, fp.HOME_MENU_CLOSE)
    time.sleep(0.5)


def close_home_menu_and_reset(adb, vision):
    from ui2_zoom import zoom_out_home
    close_home_menu(adb, vision)
    zoom_out_home(vision)
    time.sleep(0.3)
    click_point(adb, fp.SAFE_CLOSE_POINT)
    time.sleep(0.4)


def dismiss_home_star_bonus(adb, vision, timeout=3.0):
    v = vision
    deadline = time.time() + timeout
    while time.time() < deadline:
        if v.match_template(v.grab(), 'home_star_bonus', 0.85):
            print('[HOME]Star bonus received, tapping Okay')
            click_point(adb, fp.HOME_STAR_BONUS_OKAY)
            time.sleep(1.0)
            return True
        time.sleep(0.5)
    return False


def click_army_bar(adb, bars, slot_index):
    idx = slot_index
    if idx >= len(bars):
        raise ValueError('Selected army slot does not exist')
    x, y = bars[idx]
    adb.tap(x, y)


def click_point(adb, pos):
    x, y = pos
    adb.tap(x, y)


def click_point_raw(adb, pos):
    x, y = pos
    adb.tap_raw(x, y)


def scroll_down(adb):
    adb.swipe(815, 550, 813, 0, 150)


def scroll_up(adb):
    adb.swipe(813, 295, 815, 576, 600)


def wait_for_chest_continue(vision, timeout=10.0, poll_interval=0.3):
    v = vision
    deadline = time.time() + timeout
    while time.time() < deadline:
        if v.templates.get('chest_continue'):
            match = v.match_template_region_multiscale(
                fp.CHEST_CONTINUE_SEARCH_REGION,
                'chest_continue',
                fp.CHEST_CONTINUE_MATCH_THRESHOLD,
                scales=[1.0, 0.97],
            )
            if match:
                return match
        time.sleep(poll_interval)
    return None


def resolve_chest_reward_sequence(vision, tap_fn, save_screenshot_fn=None):
    tap = tap_fn
    save_shot = save_screenshot_fn
    time.sleep(1)
    match = None
    deadline = time.time() + 20.0
    while time.time() < deadline:
        match = wait_for_chest_continue(vision, timeout=0.1, poll_interval=0.1)
        if match:
            break
        # Tap random spots in the middle of the screen to skip the chest animation.
        for _ in range(3):
            tap(random.randint(600, 1000), random.randint(350, 650))
            time.sleep(0.1)
    if match:
        if save_shot:
            save_shot()
        tap(*match)
    else:
        if save_shot:
            save_shot()
        tap(*fp.EVENT_CHEST_CONTINUE_BUTTON)
    time.sleep(1)
