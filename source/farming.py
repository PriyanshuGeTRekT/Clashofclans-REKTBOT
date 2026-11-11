# farming.py -- reconstructed from statically-decrypted Pyarmor bytecode (ACBot Basic v1.6.7)
# Python 3.10. Pyarmor enter/exit wrappers stripped; local names re-chosen from usage.
# Nested helper names (R, s, F, t, Z) are the real (minified) co_names from the binary.
import time
from adb import tap, save_treasure_screenshot, swipe
from actions import click_point, resolve_chest_reward_sequence, dismiss_home_star_bonus
import fixed_points as fp
from walls import upgrade_walls
import random  # imported but unused in this module
from ui2_zoom import zoom_out, zoom_out_home
from attack import edragon as attack_edragon
from attack import dragon as attack_dragon
from attack import csv_script as attack_csv
import war
import builder_base
import ranked
import scheduler
import battle_end
import collect
import upgrades
import capital
import donate
import rewards
import obstacles
import supertroop
import helperhut

from attack import scripted as attack_scripted
from attack import lootmax as attack_lootmax
ATTACK_STRATEGY_MODULES = {'edragon': attack_edragon, 'dragon': attack_dragon, 'csv': attack_csv,
                           **attack_scripted.strategy_modules()}
MIN_HOME_GOLD_BEFORE_ATTACK = 1700
LOW_GOLD_RECHECK_SECONDS = 180
CURRENT_ARMY_SLOT_INDEX = 8
BATTLE_END_KEYS = ('return_home', 'claim_reward', 'card_claim')
SEARCH_UNABLE_REGION = (420, 440, 1180, 550)
SEARCH_UNABLE_RETURN_HOME = (105, 800)
SEARCH_UNABLE_WAIT_SECONDS = 60
SEARCH_CLOUD_REGION = (0, 700, 300, 900)       # "Return Home" on the "Searching for opponents..." screen
_state_cloud = {'count': 0}


# FIX: the original returned 'RECOVERY' on a battle timeout without recording what was on screen.
# Save the frame and score the end-of-battle buttons on the whole screen (is_battle_end only looks
# at the bottom-centre region). Returns True when one of them is visible after all.
def _save_frame(vision, tag):
    # FIX: write the current screen to logs/<tag>_<time>.png before a recovery; returns the frame.
    import os
    import cv2
    screen = vision.grab()
    stamp = time.strftime('%Y-%m-%d_%H-%M-%S')
    os.makedirs('logs', exist_ok=True)
    path = os.path.join('logs', f'{tag}_{stamp}.png')
    cv2.imwrite(path, screen)
    print(f'[WATCHDOG] Screen saved to {path}')
    return screen


def _battle_timeout_snapshot(vision):
    import cv2
    try:
        screen = _save_frame(vision, 'battle_timeout')
        gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        found = False
        for key in BATTLE_END_KEYS:
            res = cv2.matchTemplate(gray, vision.templates[key]['img'], cv2.TM_CCOEFF_NORMED)
            _mn, score, _ml, loc = cv2.minMaxLoc(res)
            print(f'[WATCHDOG] Timeout screen saved; {key} best={score:.3f} at {loc}')
            found = found or score >= 0.85
        return found
    except Exception as e:
        print(f'[WATCHDOG] Timeout snapshot failed: {e.__class__.__name__}: {e}')
        return False


def run_farming(adb, vision, stats, active_config, pause_if_needed,
                profile_manager=None, global_config=None, recovery=None, clan_games=None):
    cfg = active_config
    # 50% Loot Maxxing trains its own saved army (the replay's army) when a slot is set for it.
    if cfg.get('LOOTMAX_ENABLED', False) and int(cfg.get('LOOTMAX_ARMY_SLOT', CURRENT_ARMY_SLOT_INDEX)) != CURRENT_ARMY_SLOT_INDEX:
        cfg = dict(cfg, SELECTED_ARMY_SLOT=int(cfg['LOOTMAX_ARMY_SLOT']))
    cg = clan_games

    HOME = 'HOME'
    UPGRADE_WALLS = 'UPGRADE_WALLS'
    CHOOSE_ARMY = 'CHOOSE_ARMY'
    ARMY_DROPDOWN = 'ARMY_DROPDOWN'
    ARMY_BARS = 'ARMY_BARS'
    READY_TO_ATTACK = 'READY_TO_ATTACK'
    SEARCHING = 'SEARCHING'
    ATTACKING = 'ATTACKING'
    IN_BATTLE = 'IN_BATTLE'
    BATTLE_END = 'BATTLE_END'
    MAX_UI_RETRIES = 4
    MAX_SEARCH_FAILS = 11

    state = HOME
    army_selected = False
    attack_menu_opened = False
    fast_forwarded = False
    retry_count = 0
    skip_count = 0
    home_wait_start = None
    next_wait_log = 0.0
    home_close_next = 0.0  # FIX: rate-limits the close-X attempts in the home wait loop
    low_gold_recovery = False
    vision.cached_siege_tab = None

    def R():
        # Run the error-popup watcher once, if the vision object provides it.
        checker = getattr(vision, 'check_error_popup_once', None)
        if not callable(checker):
            return None
        return checker()

    def s():
        # Ensure home gold >= MIN_HOME_GOLD_BEFORE_ATTACK before going to attack;
        # otherwise tap the gold collector and re-check every LOW_GOLD_RECHECK_SECONDS.
        nonlocal low_gold_recovery
        fails = 0

        def F():
            click_point(adb, fp.SAFE_CLOSE_POINT)
            click_point(adb, fp.SAFE_CLOSE_POINT)
            gold, _elixir = vision.read_loot()
            return gold

        gold = F()
        if gold >= MIN_HOME_GOLD_BEFORE_ATTACK:
            return True
        fails += 1
        if fails >= 3:
            return 'RECOVERY'
        low_gold_recovery = True
        print('[STATUS] Gold below threshold for attacking, collecting collectors before next attack')
        next_check = time.time()
        while True:
            pause_if_needed()
            now = time.time()
            if now < next_check:
                time.sleep(min(1.0, next_check - now))
                continue
            print('[STATUS] Checking resource collectors')
            collector = vision.match_template(vision.grab(), 'gold_collector', 0.75,
                                              region=fp.COLLECTOR_SEARCH_REGION)
            if collector:
                print('[STATUS] Gold collector found, collecting resources')
                pause_if_needed()
                tap(*collector)
                time.sleep(0.6)
            else:
                print('[STATUS] No gold collector found')
            gold = F()
            if gold >= MIN_HOME_GOLD_BEFORE_ATTACK:
                print('[STATUS] Sufficient gold, resuming attacks')
                return True
            fails += 1
            if fails >= 3:
                return 'RECOVERY'
            print('[STATUS] Gold still below threshold, waiting for next check')
            next_check = time.time() + LOW_GOLD_RECHECK_SECONDS

    def t():
        # Open the attack ("Find a Match") screen from the home village.
        zoom_out()
        print('[SEARCH]Finding battle')
        attack_btn = vision.match_template_region(fp.HOME_ATTACK_BUTTON_REGION, 'attack_button')
        if attack_btn:
            tap(*attack_btn)
            time.sleep(0.5)
        else:
            print('[SEARCH] Attack button not found, ensure game language is set to English')
            tap(*fp.HOME_ATTACK_BUTTON)
            time.sleep(0.5)
        league = vision.match_template(vision.grab(), 'league_overview', 0.85)
        if league:
            tap(*fp.LEAGUE_OVERVIEW_CLOSE)
            time.sleep(0.3)
            tap(*fp.HOME_ATTACK_BUTTON)
            time.sleep(0.3)
            return None
        return None

    def Z():
        # True when the configured army slot is the "current army" slot (index 8) -> no army switch.
        return int(cfg.get('SELECTED_ARMY_SLOT', 0) or 0) == CURRENT_ARMY_SLOT_INDEX

    while True:
        pause_if_needed()
        if getattr(vision, '_hard_popup_reset_requested', False):
            vision._hard_popup_reset_requested = False
            retry_count = 0
            skip_count = 0
            army_selected = False
            state = HOME
            print('[ERROR] Resuming from HOME')
            continue

        # ------------------------------------------------------------ HOME
        if state == HOME:
            if vision.match_template(vision.grab(), 'bb_detection', 0.85):
                print('[HOME]Detected Builder Base, returning to home village')
                swipe(*fp.BUILDER_SWIPE_DOWN)
                time.sleep(0.5)
                swipe(*fp.BUILDER_SWIPE_LEFT)
                time.sleep(0.5)
                bb_home = vision.match_template(vision.grab(), 'bb_home', 0.6)
                if bb_home:
                    tap(*bb_home)
                continue
            popup = R()
            if popup and popup.get('is_hard'):
                continue
            if not vision.is_home_village():
                now = time.time()
                if home_wait_start is None:
                    home_wait_start = now
                    next_wait_log = 0.0
                if now - home_wait_start > 45:
                    print('[HOME]Village wait timeout, triggering recovery')
                    return 'RECOVERY'
                # FIX: a CoC window left open (army, picker, info panel) hides the home markers;
                # try the standard top-right close X before falling back to a full CoC restart.
                if now - home_wait_start > 6 and now >= home_close_next:
                    print('[HOME]Not home yet, tapping window close')
                    click_point(adb, fp.HOME_ARMY_TAB_CLOSE)
                    home_close_next = now + 4.0
                if now >= next_wait_log:
                    print('[HOME]Waiting for home village')
                    next_wait_log = now + 2.0
                time.sleep(0.5)
                continue
            home_wait_start = None
            next_wait_log = 0.0
            if cg and cg.cached_cg_edit_challenge and getattr(cg, 'cg_army_temp_active', False):
                print('[ARMY]Resetting army to remove CG challenge troops')
                cg.reset_army_slot(adb, cfg)
                cg.cg_army_temp_active = False
                time.sleep(0.5)
            # FIX: is_home_village() also matches the Builder Base, and CoC reopens on the village that
            # was open last (e.g. a recovery relaunch right after a Builder Base visit). Sail home first.
            if cfg.get('BB_ONLY', False):
                # new (Pro): Builder Base only mode - no home village attacks, stay on the BB.
                gate = scheduler.gate(stats, cfg, pause_if_needed)
                if gate:
                    return gate
                bb_result = builder_base.run_only(adb, vision, cfg, stats, pause_if_needed)
                if bb_result == 'RECOVERY':
                    return 'RECOVERY'
                if bb_result == 'skipped':
                    time.sleep(5)
                continue
            if builder_base.on_builder_base(vision):
                print('[HOME]On the Builder Base, taking the boat home')
                if not builder_base.go_home(vision):
                    return 'RECOVERY'
                continue
            click_point(adb, fp.SAFE_CLOSE_POINT)
            print('[HOME]Home Village confirmed')
            gate = scheduler.gate(stats, cfg, pause_if_needed)   # new: active hours / breaks / end conditions
            if gate:
                return gate
            print('[ZOOM] Zooming out')
            # Village-object chores need the reference zoom (zoomnorm.py: ~6 s on sceneries that zoom
            # out further); a plain zoom-out is enough when none of them is due.
            if collect.due(cfg) or helperhut.due(cfg) or supertroop.due(cfg) or obstacles.due(cfg):
                zoom_out_home(vision)
            else:
                zoom_out()
            if collect.due(cfg):                  # new: collectors, loot cart, gem box
                collect.run(vision, cfg)
                time.sleep(0.5)
            if helperhut.due(cfg):                # new: Builder's Apprentice / Lab Assistant
                helperhut.run(vision, cfg)
            if supertroop.due(cfg):               # new: boost super troops
                supertroop.run(vision, cfg)
            if obstacles.due(cfg):                # new: remove obstacles
                obstacles.run(vision, cfg)
            if rewards.due(cfg):                  # new: claim free event rewards
                rewards.run(vision, cfg)
            if donate.due(cfg):                   # new: donate to clan requests
                donate.run(vision, cfg)
            if any(upgrades.due(cfg, k) for k in ('builders', 'lab', 'pets', 'equipment')):
                upgrades.run(vision, cfg)         # new: builder / lab / pet / equipment upgrades
                zoom_out()
                time.sleep(0.5)
            if cg and cg.consume_cg_army_restore_pending():
                army_selected = False
            if profile_manager and global_config and recovery:
                import main
                if cfg.get('MULTI_VILLAGE_ENABLED', False) and main.active_profiles and main.last_profile_switch:
                    should_switch = False
                    if cfg.get('SWITCH_ON_LOOT_FULL', False):
                        loot_full = vision.is_loot_full()
                        if all(loot_full.values()):
                            profile_name = None
                            if 0 <= main.current_profile_index < len(main.active_profiles):
                                profile_name = main.active_profiles[main.current_profile_index]
                            if profile_name:
                                main.loot_full_confirmed_profiles.add(profile_name)
                            confirmed = len(main.loot_full_confirmed_profiles)
                            total = len(main.active_profiles)
                            if total > 0 and confirmed >= total:
                                return 'STOP_BOT'
                            print('[FARMING] All loot storages full, switching profile')
                            should_switch = True
                        else:
                            not_full = [name for name, full in loot_full.items() if not full]
                            print(f"[FARMING] Loot not full yet: {', '.join(not_full)}")
                    elif cfg.get('SWITCH_ON_BUILDERS_BUSY', False):
                        # new (Pro): leave a village once all its builders are working and it
                        # has been played for the minimum time (VILLAGE_SWITCH_MINUTES).
                        builders_free = vision.read_builders_free()
                        played = time.time() - main.last_profile_switch
                        if (builders_free == 0 and
                                played >= cfg.get('VILLAGE_SWITCH_MINUTES', 30) * 60):
                            print('[FARMING] All builders busy, switching profile')
                            should_switch = True
                    else:
                        now = time.time()
                        switch_interval = cfg.get('VILLAGE_SWITCH_MINUTES', 30) * 60
                        if now - main.last_profile_switch >= switch_interval:
                            print('[FARMING] Profile switch timer reached, returning to main loop')
                            should_switch = True
                    if should_switch:
                        return 'PROFILE_SWITCH'
            if cfg.get('CLAN_GAMES', False):
                print('[CLAN GAMES]Checking challenges')
                if cg:
                    cg.run()
                time.sleep(1.0)
            if war.due(cfg):  # new: Clan War / CWL attack when one is available (WAR_ATTACKS_ENABLED)
                war_result = war.run(adb, vision, cfg, ATTACK_STRATEGY_MODULES, pause_if_needed)
                if war_result == 'RECOVERY':
                    return 'RECOVERY'
                if war_result == 'attacked':
                    continue
            if capital.due(cfg):  # new: Clan Capital raid attacks (raid weekends)
                if capital.run(adb, vision, cfg, pause_if_needed) == 'RECOVERY':
                    return 'RECOVERY'
                continue
            if builder_base.due(cfg):  # new: Builder Base battles every BB_INTERVAL_MINUTES
                if builder_base.run(adb, vision, cfg, pause_if_needed) == 'RECOVERY':
                    return 'RECOVERY'
                continue
            if cfg.get('UPGRADE_WALLS', False):
                state = UPGRADE_WALLS
                continue
            if (cfg.get('CLAN_GAMES', False) and cg and cg.cached_cg_edit_challenge
                    and cg.has_pending_non_exempt_edit(cfg) and army_selected):
                print('[ARMY]Resetting base army before army edit')
                army_selected = False
            if not army_selected:
                if Z():
                    print('[ARMY]Army selection OFF')
                    army_selected = True
                    state = READY_TO_ATTACK
                    continue
                state = CHOOSE_ARMY
                continue
            state = READY_TO_ATTACK
            continue

        # ------------------------------------------------------------ UPGRADE_WALLS
        elif state == UPGRADE_WALLS:
            builders_free = vision.read_builders_free()
            no_builders = (builders_free == 0) if builders_free is not None else False
            goblin_helper = vision.match_template_region(fp.UPGRADE_ZONE_REGION, 'upgrade_goblin_helper')
            if no_builders or goblin_helper:
                print('[WALLS]Builders busy, skipping wall upgrade')
            else:
                upgrade_walls(adb, vision, stats, cfg)
            if not army_selected:
                if Z():
                    print('[ARMY]army selection off attacking')
                    army_selected = True
                    state = READY_TO_ATTACK
                else:
                    state = CHOOSE_ARMY
            else:
                state = READY_TO_ATTACK
            continue

        # ------------------------------------------------------------ CHOOSE_ARMY
        elif state == CHOOSE_ARMY:
            if Z():
                print('[ARMY]army selection off attacking')
                army_selected = True
                state = READY_TO_ATTACK
                continue
            if not attack_menu_opened:
                pause_if_needed()
                s()  # return value (True / 'RECOVERY') is discarded
                click_point(adb, fp.SAFE_CLOSE_POINT)
                t()
                attack_menu_opened = True
            btn = None
            for _ in range(10):
                btn = vision.find_army_button()
                if btn:
                    break
                time.sleep(0.2)
            if not btn:
                print('[ARMY]Edit Army button not found, triggering recovery')
                return 'RECOVERY'
            print('[ARMY]Opening army menu')
            click_point(adb, btn)
            time.sleep(0.5)
            state = ARMY_DROPDOWN
            continue

        # ------------------------------------------------------------ ARMY_DROPDOWN
        elif state == ARMY_DROPDOWN:
            btn = vision.find_army_dropdown()
            if btn:
                retry_count = 0
                click_point(adb, btn)
                state = ARMY_BARS
                continue
            retry_count += 1
            if retry_count == 1:
                print('[ARMY]Army dropdown not found, ensure you have saved armies available and try again')
            if retry_count >= MAX_UI_RETRIES:
                print('[ARMY]Army dropdown not found after max retries, triggering recovery')
                tap(*fp.SAFE_CLOSE_POINT)
                time.sleep(0.2)
                retry_count = 0
                return 'RECOVERY'
            time.sleep(0.1)
            continue

        # ------------------------------------------------------------ ARMY_BARS
        elif state == ARMY_BARS:
            if Z():
                print('[ARMY]army selection off attacking')
                click_point(adb, fp.HOME_ARMY_TAB_CLOSE)
                army_selected = True
                time.sleep(0.2)
                state = READY_TO_ATTACK
                continue
            bars = vision.find_army_bars()
            if not bars:
                retry_count += 1
                if retry_count < MAX_UI_RETRIES:
                    time.sleep(0.2)
                    continue
                print('[ARMY]Army bars not found after max retries, triggering recovery')
                tap(*fp.SAFE_CLOSE_POINT)
                time.sleep(0.2)
                retry_count = 0
                return 'RECOVERY'
            retry_count = 0
            slot = cfg.get('SELECTED_ARMY_SLOT', 0)
            strategy_name = cfg.get('SELECTED_ATTACK_STRATEGY', 'unknown')
            print(f'[ARMY]Setting army to ({strategy_name})')
            if slot < len(bars):
                click_point(adb, bars[slot])
                print(f'[ARMY]({strategy_name}) Successfully selected')
                time.sleep(0.1)
            okay = vision.find_okay_button()
            if okay:
                click_point(adb, okay)
                time.sleep(0.1)
            okay2 = vision.find_okay_button()
            if okay2:
                click_point(adb, okay2)
                time.sleep(0.1)
            click_point(adb, fp.HOME_ARMY_TAB_CLOSE)
            army_selected = True
            time.sleep(0.5)
            state = READY_TO_ATTACK
            continue

        # ------------------------------------------------------------ READY_TO_ATTACK
        elif state == READY_TO_ATTACK:
            pause_if_needed()
            if not attack_menu_opened:
                s()  # return value discarded
                t()
            attack_menu_opened = False
            ranked_action = ranked.handle_battle_menu(vision, cfg)  # new: Ranked Battle sign-up / attacks
            if ranked_action == 'match':
                ranked_result = ranked.run_match(adb, vision, cfg, ATTACK_STRATEGY_MODULES, pause_if_needed)
                if ranked_result == 'RECOVERY':
                    return 'RECOVERY'
                if ranked_result == 'attacked':
                    state = HOME
                    continue
            elif ranked_action:
                time.sleep(1.0)
            if vision.match_template_region(fp.HOME_ATTACK_TIMEOUT_REGION, 'attack_timeout'):
                print('[SEARCH]Attack unavailable, waiting')
                while vision.match_template_region(fp.HOME_ATTACK_TIMEOUT_REGION, 'attack_timeout'):
                    time.sleep(5)
                    pause_if_needed()
            click_point(adb, fp.HOME_FIND_BATTLE_BUTTON)
            time.sleep(0.5)
            if cg and not cfg.get('CLAN_GAMES', False):
                if (cg.cached_cg_super or cg.cg_super_selected or cg.cached_cg_edit_challenge
                        or cg.cg_army_temp_active or cg.cg_army_restore_pending):
                    cg.cached_cg_super = None
                    cg.cg_super_selected = False
                    cg.cached_cg_edit_challenge = None
                    cg.cg_army_temp_active = False
                    cg.cg_army_restore_pending = False
            # FIX: with "Current Army" (slot 8) undo the previous challenge edit before attacking again
            if cg and getattr(cg, 'slot8_restore', None) and not cg.cg_army_temp_active:
                cg.restore_slot8_edit()
                time.sleep(0.3)
            if cfg.get('CLAN_GAMES', False) and cg and cg.cached_cg_edit_challenge:
                cg.apply_cg_edit_if_needed(adb, cfg)
                if getattr(cg, 'cg_army_restore_pending', False):
                    print('[ARMY]CG edit failed after removal, restoring base army before attacking')
                    army_selected = False
                    # FIX: SAFE_CLOSE_POINT lands inside the full-screen "My Army" window and closes
                    # nothing, so the home check then waited 45 s and force-restarted CoC. The red X
                    # closes the troop picker first, then the army window.
                    for _ in range(3):
                        click_point(adb, fp.HOME_ARMY_TAB_CLOSE)
                        time.sleep(0.8)
                        if vision.is_home_village():
                            break
                    state = HOME
                    continue
                time.sleep(0.4)
            if cfg.get('CLAN_GAMES', False) and cg and cg.cached_cg_super:
                print('[FARMING]Handling CG troop request')
                cg._handle_cg_troops()
                time.sleep(0.5)
            elif cfg.get('REQUEST_DONATIONS', False):
                request_btn = vision.find_request_available()
                if request_btn:
                    print('[CC]Requesting donations')
                    tap(*request_btn)
                    time.sleep(0.1)
                    tap(*fp.HOME_SEND_TROOP_REQUEST)
                    time.sleep(0.6)
            click_point(adb, fp.HOME_CONFIRM_ATTACK_BUTTON)
            print('[SEARCH]Searching')
            state = SEARCHING
            continue

        # ------------------------------------------------------------ SEARCHING
        elif state == SEARCHING:
            if vision.is_in_battle():
                retry_count = 0
                loot = vision.stable_loot_read()
                if not loot:
                    print('[SEARCH]Loot read failed, retrying search...')
                    click_point(adb, fp.BATTLE_NEXT_BUTTON)
                    time.sleep(2)
                    continue
                gold, elixir, dark = loot
                print(f'[SEARCH]G:{gold} E:{elixir} D:{dark}')
                if gold == 0 and elixir == 0 and dark == 0:
                    R()
                    time.sleep(1)
                    continue
                if low_gold_recovery:
                    low_gold_recovery = False
                    skip_count = 0
                    print('[SEARCH]Low-gold recovery active. Ignoring attack filters for this attack')
                    state = ATTACKING
                    time.sleep(1.5)
                    continue
                if cfg.get('XP_FARMING', False):
                    # new (Pro): XP farming - attack every base regardless of loot (experience
                    # comes from destroyed buildings, not loot; pair with END_BATTLE_* to keep
                    # attacks short).
                    skip_count = 0
                    print('[SEARCH]XP farming: attacking regardless of loot')
                    state = ATTACKING
                elif (gold >= cfg.get('ATTACK_MIN_GOLD', 0)
                        and elixir >= cfg.get('ATTACK_MIN_ELIXIR', 0)
                        and dark >= cfg.get('ATTACK_MIN_DARK', 0)):
                    skip_count = 0
                    print('[SEARCH]Loot good. Attacking')
                    state = ATTACKING
                elif gold >= 2000000 or elixir >= 2000000:
                    skip_count = 0
                    print('[SEARCH]High loot detected, attacking')
                    state = ATTACKING
                else:
                    R()
                    skip_count += 1
                    if skip_count > 5:
                        R()
                    print('[SEARCH]Loot bad, skipping')
                    click_point(adb, fp.BATTLE_NEXT_BUTTON)
            else:
                retry_count += 1
                # FIX: "Unable to attack Village! Try again later." (shown while the server still
                # holds a previous battle, e.g. after CoC was killed mid-attack). Go home and wait
                # instead of relaunching CoC, which only restarts the same wait.
                if vision.match_template_region(SEARCH_UNABLE_REGION, 'search_unable_to_attack', 0.8):
                    print(f'[SEARCH] Unable to attack right now, returning home and waiting {SEARCH_UNABLE_WAIT_SECONDS} s')
                    tap(*SEARCH_UNABLE_RETURN_HOME)
                    retry_count = 0
                    time.sleep(SEARCH_UNABLE_WAIT_SECONDS)
                    state = HOME
                    continue
                if retry_count >= MAX_SEARCH_FAILS:
                    # FIX: most "stuck" searches (5 of 7 saved screens) are the game's own "Searching
                    # for opponents..." cloud taking long. Its Return Home button gets us out without
                    # killing the game; only a third cloud in a row still restarts it.
                    cloud = vision.match_template_region(SEARCH_CLOUD_REGION, 'search_cloud_return_home', 0.85)
                    if cloud and _state_cloud['count'] < 2:
                        _state_cloud['count'] += 1
                        print(f"[SEARCH] Opponent search is hanging, returning home and searching again "
                              f"({_state_cloud['count']}/2)")
                        tap(*cloud)
                        retry_count = 0
                        time.sleep(5)
                        state = HOME
                        continue
                    _state_cloud['count'] = 0
                    print('[SEARCH] Stuck searching, triggering recovery')
                    try:  # FIX: record what CoC was showing instead of restarting it blind
                        _save_frame(vision, 'search_stuck')
                    except Exception as e:
                        print(f'[WATCHDOG] Screen save failed: {e.__class__.__name__}: {e}')
                    return 'RECOVERY'
            time.sleep(1.5)
            continue

        # ------------------------------------------------------------ ATTACKING
        elif state == ATTACKING:
            _state_cloud['count'] = 0
            strategy = str(cfg.get('SELECTED_ATTACK_STRATEGY', '')).strip()
            module = ATTACK_STRATEGY_MODULES.get(strategy)
            if cfg.get('LOOTMAX_ENABLED', False):      # "50% Loot Maxxing" switch overrides the strategy
                strategy, module = 'lootmax', attack_lootmax
            if not module:
                strategy = 'edragon'
                module = ATTACK_STRATEGY_MODULES[strategy]
                print('[ATTACK] Locked strategy selected in config; using edragon fallback')
            try:
                used = module.run_attack(adb, vision, cfg)
                if isinstance(used, str):        # a strategy handed the attack to another one
                    strategy = used
                print('[BATTLE] Attack finished, waiting for battle to end')
            except Exception as e:
                print(f"[ATTACK] Strategy '{strategy}' crashed: {e.__class__.__name__}: {e}")
                return 'RECOVERY'
            fast_forwarded = False
            state = IN_BATTLE
            continue

        # ------------------------------------------------------------ IN_BATTLE
        elif state == IN_BATTLE:
            battle_start = time.time()
            battle_end.reset()
            frozen = builder_base._FreezeCheck()   # new: a hung game (dimmed, clock stopped) -> recover now
            while True:
                pause_if_needed()
                if frozen.update(vision.grab()):
                    print(f'[WATCHDOG] Game frozen for {builder_base.FROZEN_SECONDS} s during the battle, recovering')
                    _save_frame(vision, 'battle_frozen')
                    return 'RECOVERY'
                if battle_end.enabled(cfg) and battle_end.check(vision, cfg):
                    time.sleep(1.0)        # new: ended early (stars / damage / no progress)
                if time.time() - battle_start > 240:
                    popup = R()
                    if popup:
                        if popup.get('is_hard'):
                            print('[WATCHDOG] Battle timeout: hard error, resetting')
                            break
                        print('[WATCHDOG] Battle timeout: error dismissed, retrying')
                        battle_start = time.time()
                        continue
                    print('[WATCHDOG] Battle timeout with no popup handled')
                    if _battle_timeout_snapshot(vision):
                        print('[BATTLE] End screen found outside the expected region')
                        retry_count = 0
                        state = BATTLE_END
                        break
                    return 'RECOVERY'
                if not fast_forwarded:
                    screen = vision.grab()
                    ff = vision.match_template(screen, 'fastforward', 0.85, region=fp.BATTLE_FASTFORWARD_REGION)
                    if ff:
                        tap(*ff)
                        fast_forwarded = True
                        print('[BATTLE] Fast Forwarding')
                if vision.is_battle_end():
                    retry_count = 0
                    state = BATTLE_END
                    break
                if fp.PICK_BATTLE_REWARD_ENABLED:
                    screen = vision.grab()
                    pick = vision.match_template(screen, 'pick_battle_reward', fp.PICK_BATTLE_REWARD_THRESHOLD,
                                                 region=fp.PICK_BATTLE_REWARD_REGION)
                    pick_end = None if pick else vision.match_template(
                        screen, 'pick_end_battle_reward', fp.PICK_BATTLE_REWARD_THRESHOLD,
                        region=fp.PICK_BATTLE_REWARD_REGION)
                    if pick or pick_end:
                        print('[BATTLE] Claiming In-Battle rewards')
                        time.sleep(2)
                        tap(*(fp.PICK_BATTLE_REWARD_TAP if pick else fp.PICK_END_BATTLE_REWARD_TAP))
                time.sleep(1.5)
            continue

        # ------------------------------------------------------------ BATTLE_END
        elif state == BATTLE_END:
            print('[BATTLE]Battle ended')
            gold, elixir, dark = vision.read_battle_end_loot()
            stats.gold_gained += gold
            stats.elixir_gained += elixir
            stats.dark_gained += dark
            stats.update_hourly_rates()
            stars = vision.detect_battle_end_stars()
            stats.total_attacks += 1
            stats.record_stars(stars)
            # new: per-battle result line, so strategies can be compared from the session log
            print(f"[BATTLE] Result: {stars} star(s), loot {gold}/{elixir}/{dark} "
                  f"({strategy or '?'})")
            chest = None
            if vision.templates.get('claim_reward'):
                chest = vision.match_template(vision.grab(), 'claim_reward', 0.85)
            card = None
            if vision.templates.get('card_claim'):
                card = vision.match_template(vision.grab(), 'card_claim', 0.85)
            if card:
                print('[CARD] Card Detected')
                tap(*card)
                time.sleep(5)
                for _ in range(5):
                    tap(832, 584)
                    time.sleep(0.1)
                time.sleep(4)
                tap(832, 784)
            elif chest:
                print('[TREASURE] Treasure Chest detected')
                tap(*chest)
                resolve_chest_reward_sequence(vision, tap, save_treasure_screenshot)
            else:
                click_point(adb, fp.BATTLE_RETURN_HOME_BUTTON)
            time.sleep(3)
            dismiss_home_star_bonus(adb, vision)
            vision.cached_siege_tab = None
            if cg:
                if stars >= 1:
                    cg.mark_cg_army_attack_completed()
            state = HOME
            continue
