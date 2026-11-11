# war.py - Clan War / CWL attacks (new module; neither Basic nor MyBot PHMOD has one).
#
# Flow (captured from the live game, 1600x900):
#   home village -> war button (crossed swords, left side) -> war map
#   -> header shows "Battle Day" and "Attacks remaining" -> the game labels one enemy base
#      "Recommended target" -> tap that base -> target popup -> "Attack!"
#   -> war battle (same troop bar as multiplayer, no Next button) -> chosen strategy deploys
#   -> battle end screen -> Return Home (back to the war map) -> war-map "Return Home".
# A war attack is spent the moment "Attack!" is pressed, so the whole feature is off by default
# (WAR_ATTACKS_ENABLED) and limited per war (WAR_MAX_ATTACKS).
import copy
import time

import fixed_points as fp
from actions import click_point
from adb import tap
from ui2_zoom import zoom_out

WAR_DEBUG = False
WAR_ICON_REGION = (0, 500, 220, 660)
WAR_HEADER_REGION = (600, 100, 1000, 200)
WAR_ATTACKS_LEFT_REGION = (550, 180, 1050, 280)
WAR_MAP_REGION = (180, 230, 1420, 890)
WAR_POPUP_ATTACK_REGION = (880, 600, 1150, 760)
WAR_RETURN_HOME_REGION = (0, 700, 260, 900)
RECOMMENDED_LABEL_TO_BASE_DY = -92      # label sits ~92 px under the base it belongs to
WAR_RECHECK_SECONDS = 1800               # look at the war map at most every 30 min
BATTLE_TIMEOUT_SECONDS = 240

_state = {'next_check': 0.0, 'attacks_done': 0, 'war_key': None}


def _log(msg):
    print(f'[WAR] {msg}')


def _war_button(vision):
    return vision.match_template_region(WAR_ICON_REGION, 'war_icon_home', 0.8)


def _go_home_from_war_map(vision):
    btn = vision.match_template_region(WAR_RETURN_HOME_REGION, 'war_return_home', 0.8)
    tap(*(btn or (104, 822)))
    for _ in range(20):
        time.sleep(1)
        if vision.is_home_village():
            return True
    return False


def due(cfg):
    if not cfg.get('WAR_ATTACKS_ENABLED', False):
        return False
    if _state['attacks_done'] >= int(cfg.get('WAR_MAX_ATTACKS', 2) or 2):
        return False
    return time.time() >= _state['next_check']


def run(adb, vision, cfg, attack_modules, pause_if_needed=None):
    """Make one war attack if the war is on Battle Day and we have attacks left.

    Returns 'attacked', 'skipped' (nothing to do, home village restored) or 'RECOVERY'."""
    _state['next_check'] = time.time() + WAR_RECHECK_SECONDS
    btn = _war_button(vision)
    if not btn:
        if WAR_DEBUG:
            _log('No war button on the home village')
        return 'skipped'
    tap(*btn)
    time.sleep(4)
    screen = vision.grab()
    if not vision.match_template(screen, 'war_battle_day', 0.8, region=WAR_HEADER_REGION):
        _log('War is not on Battle Day, skipping')
        return 'skipped' if _go_home_from_war_map(vision) else 'RECOVERY'
    if not vision.match_template(screen, 'war_attacks_remaining', 0.8, region=WAR_ATTACKS_LEFT_REGION):
        _log('No war attacks remaining')
        _state['attacks_done'] = 99
        return 'skipped' if _go_home_from_war_map(vision) else 'RECOVERY'
    label = vision.match_template(screen, 'war_recommended_target', 0.8, region=WAR_MAP_REGION)
    if not label:
        _log('No "Recommended target" on screen, skipping this check')
        return 'skipped' if _go_home_from_war_map(vision) else 'RECOVERY'
    target = (label[0], label[1] + RECOMMENDED_LABEL_TO_BASE_DY)
    _log(f'Recommended target at {target}')
    tap(*target)
    time.sleep(2)
    attack_btn = vision.match_template_region(WAR_POPUP_ATTACK_REGION, 'war_attack_button', 0.8)
    if not attack_btn:
        _log('Target popup has no Attack! button (attacked already or not allowed), skipping')
        return 'skipped' if _go_home_from_war_map(vision) else 'RECOVERY'

    strategy = str(cfg.get('WAR_ATTACK_STRATEGY') or cfg.get('SELECTED_ATTACK_STRATEGY') or 'edragon')
    module = attack_modules.get(strategy) or attack_modules['edragon']
    war_cfg = copy.copy(cfg)
    war_cfg['SELECTED_ATTACK_STRATEGY'] = strategy
    if cfg.get('WAR_CSV_SCRIPT'):
        war_cfg['CSV_ATTACK_SCRIPT'] = cfg['WAR_CSV_SCRIPT']
    _log(f'Attacking with {strategy}' + (f" ({war_cfg.get('CSV_ATTACK_SCRIPT')})" if strategy == 'csv' else ''))
    tap(*attack_btn)
    deadline = time.time() + 30
    while time.time() < deadline and not vision.is_in_battle():
        time.sleep(1)
    if not vision.is_in_battle():
        _log('War battle screen did not load')
        return 'RECOVERY'
    _state['attacks_done'] += 1
    # The battle camera starts zoomed in here (no home-village zoom-out before it): the strategies'
    # drop points assume the zoomed-out view, otherwise every troop tap lands in the red zone.
    zoom_out()
    time.sleep(0.8)
    try:
        module.run_attack(adb, vision, war_cfg)
    except Exception as e:
        _log(f'Strategy crashed: {e.__class__.__name__}: {e}')
        return 'RECOVERY'
    start = time.time()
    while time.time() - start < BATTLE_TIMEOUT_SECONDS:
        if callable(pause_if_needed):
            pause_if_needed()
        if vision.is_battle_end():
            break
        time.sleep(1.5)
    else:
        _log('War battle did not end in time')
        return 'RECOVERY'
    stars = vision.detect_battle_end_stars()
    _log(f'War attack finished: {stars} star(s)')
    click_point(adb, fp.BATTLE_RETURN_HOME_BUTTON)
    time.sleep(5)
    if vision.is_home_village():
        return 'attacked'
    return 'attacked' if _go_home_from_war_map(vision) else 'RECOVERY'
