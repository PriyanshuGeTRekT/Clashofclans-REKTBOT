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
            dismiss_home_popups(adb, vision)
            return True
        time.sleep(0.5)
    # UPDATE (Clash of Titans, 16 Nov 2026): the Star Bonus now pays out in milestones (Snack Packs at
    # 2 and 5 stars, loot into the Clan Castle Treasury); close a window that leaves open with its X.
    return dismiss_home_popups(adb, vision) is not None


RETURN_HOME_REGION = (300, 560, 1300, 900)
WINDOW_CLOSE_REGION = (900, 0, 1600, 320)


def tap_return_home(adb, vision):
    """Battle end screen: tap Return Home where it actually is (the update adds an emote picker to the
    victory screen, which may move it), falling back to the classic position."""
    pos = vision.match_template(vision.grab(), 'return_home', 0.8, region=RETURN_HOME_REGION)
    click_point(adb, pos if pos else fp.BATTLE_RETURN_HOME_BUTTON)
    return bool(pos)


# UPDATE (seen 20 Nov): "Welcome Back Chief! / While you were away..." opens at login (e.g. "Your
# Village was Attacked"). It has no close X, only a green Okay. The window is recognised by its title,
# so this Okay cannot be the Okay of a confirmation dialog. Across 741 saved screens the title scores
# 1.00 on this window and at most 0.43 anywhere else.
WELCOME_BACK_TITLE_REGION = (300, 40, 1300, 190)
WELCOME_BACK_OKAY_REGION = (500, 600, 1100, 880)
WELCOME_BACK_OKAY_POINT = (818, 750)


def dismiss_welcome_back(adb, vision, screen=None):
    """Tap Okay on the "Welcome Back Chief!" window. True when the window was there."""
    if not vision.templates.get('welcome_back'):
        return False
    if screen is None:
        screen = vision.grab()
    if not vision.match_template(screen, 'welcome_back', 0.8, region=WELCOME_BACK_TITLE_REGION):
        return False
    okay = None
    if vision.templates.get('welcome_back_okay'):
        okay = vision.match_template(screen, 'welcome_back_okay', 0.8, region=WELCOME_BACK_OKAY_REGION)
    print('[HOME]Welcome Back window, tapping Okay')
    click_point(adb, okay or WELCOME_BACK_OKAY_POINT)
    time.sleep(1.0)
    return True


def dismiss_home_popups(adb, vision, rounds=3):
    """Close windows over the home village: the red close X, and the Okay of the Welcome Back window.
    Returns 'close', 'okay' or None.
    A generic green Okay is deliberately NOT tapped: across 737 saved screens it matched confirmation
    dialogs ("End battle?", "Remove challenge?"), and an Okay can confirm spending gems."""
    tapped = None
    for _ in range(rounds):
        if dismiss_welcome_back(adb, vision):
            tapped = 'okay'
            continue
        close = vision.match_template(vision.grab(), 'upgrade_window_close', 0.6, region=WINDOW_CLOSE_REGION)
        if close:
            print('[HOME]Window over the village, tapping its close X')
            click_point(adb, close)
            tapped = 'close'
            time.sleep(1.0)
            continue
        break
    return tapped


# UPDATE (Clash of Titans): a Star Bonus Snack Pack opens on a full-screen scene (kitchen table, no
# village buttons): tap the pack a few times, the snack appears, then a green Continue button closes it.
# It is the same Continue button as on the chest screen, so the chest template finds it.
REWARD_CONTINUE_SCALES = [1.0, 0.97, 0.94, 0.9, 1.04, 1.08]
REWARD_HIT_AREA = (730, 400, 870, 500)      # middle of the scene, above where dialogs keep their buttons


REWARD_TEXT_REGION = (450, 540, 1150, 880)   # where a reward scene keeps its Continue button
REWARD_TEXT_SCALES = [1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8]


def find_continue_button(vision):
    """Green Continue button: the whole button first, then just its lettering (any button width)."""
    pos = None
    # the Snack Pack / Battle Bake reward (20 Nov: its Continue is ~15 % bigger than the chest one and
    # neither older picture reached 0.7 on it)
    if vision.templates.get('snack_continue'):
        pos = vision.match_template_region_multiscale(REWARD_TEXT_REGION, 'snack_continue', 0.8,
                                                      scales=[1.0, 0.95, 1.05, 0.9, 1.1])
        if pos:
            return pos
    if vision.templates.get('chest_continue'):
        pos = vision.match_template_region_multiscale(fp.CHEST_CONTINUE_SEARCH_REGION, 'chest_continue', 0.8,
                                                      scales=REWARD_CONTINUE_SCALES)
    if not pos and vision.templates.get('card_continue'):
        pos = vision.match_template_region_multiscale(REWARD_TEXT_REGION, 'card_continue', 0.8,
                                                      scales=REWARD_TEXT_SCALES)
    return pos


def looks_like_snack_table(screen):
    """The Snack Pack scene is a wooden kitchen table filling the screen: in the video of the update
    87-91 % of the middle band is wood-coloured; no other saved game screen gets above 52 %."""
    import cv2
    h, w = screen.shape[:2]
    band = cv2.cvtColor(screen[int(h * 0.50):int(h * 0.80), int(w * 0.10):int(w * 0.90)], cv2.COLOR_BGR2HSV)
    wood = (band[..., 0] >= 6) & (band[..., 0] <= 24) & (band[..., 1] >= 90) & (band[..., 2] >= 70)
    return float(wood.mean()) >= 0.68


def village_buttons_hidden(vision, screen):
    """True when no home-village button is on screen at all, lit or dimmed: a full-screen scene, not a
    window over the village (a window leaves the dimmed buttons visible round it)."""
    from vision import HOME_MARKERS
    return not any(vision.match_template(screen, key, 0.7, region=region) for key, region in HOME_MARKERS)


def resolve_reward_scene(adb, vision, allow_hits=False):
    """Full-screen reward scene (Snack Pack, chest): tap Continue when it is there; with allow_hits,
    tap the pack on the Snack Pack table a few times to open it first.
    Returns 'continue', 'hit' or None (nothing done)."""
    # The whole scene is worked through in one go (20 Nov, Battle Bake after a battle): the pack takes
    # four taps, a flash, then the snack with a green Continue; several rewards can follow each other.
    done = None
    x1, y1, x2, y2 = REWARD_HIT_AREA
    deadline = time.time() + 30.0
    quiet = 0                                    # looks in a row with nothing to tap
    while time.time() < deadline and quiet < 6:
        pos = find_continue_button(vision)
        if pos:
            print('[HOME]Reward screen, tapping Continue')
            click_point(adb, pos)
            time.sleep(0.8)
            done, quiet = 'continue', 0
            continue
        if not allow_hits:
            break
        screen = vision.grab()
        if vision.is_home_village():
            break
        if (not looks_like_snack_table(screen) or not village_buttons_hidden(vision, screen)
                or vision.is_in_battle() or vision.is_battle_end()):
            if done is None:
                break                            # not a reward scene at all
            quiet += 1                           # between two rewards (flash, fade): look again
            time.sleep(0.4)
            continue
        if done != 'hit' or quiet == 0:
            print('[HOME]Snack Pack screen, tapping the pack to open it')
        for _ in range(4):
            adb.tap(random.randint(x1, x2), random.randint(y1, y2))
            time.sleep(random.uniform(0.18, 0.3))
        done = done or 'hit'
        quiet += 1 if done == 'continue' else 0
        time.sleep(0.5)
    return done


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
