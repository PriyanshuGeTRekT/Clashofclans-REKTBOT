# capital.py - Clan Capital raids (new module, Pro feature; MyBot PHMOD has no raid attacks).
#
# Flow captured live at 1600x900:
#   home village (zoomed out, panned to the bottom-left shore) -> airship -> "Clan Capital" map
#   -> "Raid Map" (bottom right; the red badge shows the raid attacks left)
#   -> "Attacking Raid" map: districts with "NN% stars" labels -> tap a district
#   -> panel "Scout / Attack / Details" (Attack is grey when no attacks are left)
#   -> Attack -> raid battle (troop bar like a normal battle) -> deploy all -> end screen "Map"
#   -> back on the raid map -> "Map" (bottom left) -> capital -> "Return Home".
# Districts are tapped in a fixed order (cheapest first); a district at 100% is skipped by the game
# (no Attack button). Deployment taps every card and drops along the bottom edge of the district.
import os
import time

import cv2

from adb import swipe, tap

AIRSHIP_PANS = ((400, 600, 1100, 300),)
TITLE_REGION = (640, 25, 960, 100)
RAID_MAP_BUTTON = (1495, 815)
RETURN_HOME_BUTTON = (105, 800)
MAP_BUTTON = (105, 800)
ATTACK_REGION = (840, 740, 1050, 860)
# District label positions on the raid map (centre of the district building), cheap ones first.
DISTRICTS = [(905, 840), (580, 830), (1130, 790), (770, 650), (975, 565), (410, 870), (760, 380)]
CARD_XS = [304 + round(126.4 * i) for i in range(10)]
CARD_Y = 795
DEPLOY_LINE = ((420, 700), (1180, 700))
BATTLE_TIMEOUT_SECONDS = 240
RECHECK_SECONDS = 4 * 3600

_state = {'next_run': 0.0}


def _log(msg):
    print(f'[CAPITAL] {msg}')


def due(cfg):
    return bool(cfg.get('CAPITAL_RAIDS_ENABLED', False)) and time.time() >= _state['next_run']


def _wait(cond, seconds, step=1.0):
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(step)
    return cond()


def _save(vision, tag):
    os.makedirs('logs', exist_ok=True)
    path = os.path.join('logs', f"capital_{tag}_{time.strftime('%H-%M-%S')}.png")
    cv2.imwrite(path, vision.grab())
    return path


def _on_capital(vision):
    return vision.match_template_region(TITLE_REGION, 'capital_title', 0.8) is not None


def _on_raid_map(vision):
    return vision.match_template_region(TITLE_REGION, 'capital_attacking_raid', 0.8) is not None


def go_to_capital(vision):
    from ui2_zoom import zoom_out
    zoom_out()
    time.sleep(0.5)
    for pan in (None,) + AIRSHIP_PANS:
        if pan:
            swipe(*pan, duration=500)
            time.sleep(1.0)
        from builder_base import _match_multiscale
        hit, _score = _match_multiscale(vision, vision.grab(), 'capital_airship', 0.7)
        if hit:
            tap(*hit)
            return _wait(lambda: _on_capital(vision), 15)
    _log(f'Airship not found, saved {_save(vision, "no_airship")}')
    return False


def go_home(vision):
    for _ in range(3):
        if _on_raid_map(vision):
            tap(*MAP_BUTTON)
            _wait(lambda: _on_capital(vision), 10)
        if _on_capital(vision):
            tap(*RETURN_HOME_BUTTON)
            if _wait(lambda: vision.is_home_village(), 20):
                return True
        time.sleep(1.0)
    return vision.is_home_village()


def _deploy_all():
    (x1, y1), (x2, y2) = DEPLOY_LINE
    for i, x in enumerate(CARD_XS):
        tap(x, CARD_Y)
        time.sleep(0.25)
        for j in range(6):           # a few taps per card spreads each troop type
            t = (j + 0.5) / 6
            tap(int(x1 + (x2 - x1) * t), int(y1 + (y2 - y1) * t))
            time.sleep(0.12)


def _raid_battle(vision):
    """Deploy everything, then wait for the end screen ('Map' button) and tap it."""
    time.sleep(3.0)
    _deploy_all()
    _deploy_all()                    # second pass catches cards that were still loading
    start = time.time()
    while time.time() - start < BATTLE_TIMEOUT_SECONDS:
        end_btn = vision.match_template_region((300, 330, 1300, 900), 'capital_end_map', 0.8)
        if end_btn:
            _log(f'Raid battle finished after {int(time.time() - start)} s')
            tap(*end_btn)
            return _wait(lambda: _on_raid_map(vision), 20)
        time.sleep(2.0)
    _log(f'Raid battle did not finish, saved {_save(vision, "battle_timeout")}')
    return False


def run(adb, vision, cfg, pause_if_needed=None):
    """Use the raid attacks left this weekend. Returns 'done', 'skipped' or 'RECOVERY'."""
    _state['next_run'] = time.time() + RECHECK_SECONDS
    if not go_to_capital(vision):
        return 'skipped' if vision.is_home_village() else 'RECOVERY'
    tap(*RAID_MAP_BUTTON)
    if not _wait(lambda: _on_raid_map(vision), 10):
        _log('No raid weekend running (Raid Map did not open)')
        return 'done' if go_home(vision) else 'RECOVERY'
    attacks = 0
    for _attempt in range(int(cfg.get('CAPITAL_MAX_RAIDS', 6) or 6)):
        if callable(pause_if_needed):
            pause_if_needed()
        attacked = False
        for pos in DISTRICTS:
            tap(*pos)
            time.sleep(1.2)
            screen = vision.grab()
            if vision.match_template(screen, 'capital_attack_grey', 0.85, region=ATTACK_REGION):
                _log('No raid attacks left this weekend')
                tap(1590, 400)
                return 'done' if go_home(vision) else 'RECOVERY'
            attack = None
            if vision.match_template(screen, 'capital_attack_grey', 0.6, region=ATTACK_REGION):
                # Same button shape but not grey: the Attack button is live (colour checked).
                hsv = cv2.cvtColor(screen[765:830, 870:1018], cv2.COLOR_BGR2HSV)
                if float((hsv[..., 1] > 90).mean()) > 0.35:
                    attack = (944, 797)
            if attack:
                tap(*attack)
                attacked = True
                break
            tap(1590, 400)           # close the district panel
            time.sleep(0.6)
        if not attacked:
            break
        if not _raid_battle(vision):
            return 'RECOVERY'
        attacks += 1
    _log(f'{attacks} raid attack(s) made')
    return 'done' if go_home(vision) else 'RECOVERY'
