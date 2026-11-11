# Reconstructed from Pyarmor-protected bytecode (main.dis.txt, Python 3.10).
# Local variable names are reconstructed; globals/attributes/strings are original.
from startup import get_selected_emulator, start_adb, ensure_emulator_config_ready
import adb
import time
import random  # imported but unused in this module
import threading
from vision import Vision
from stats import Stats
from profiles.profile_manager import ProfileManager
from profiles.config_manager import ConfigManager
from clangames import ClanGames
import control
from control import BotControl
from adb import tap, swipe, save_treasure_screenshot
from actions import click_point, resolve_chest_reward_sequence
import fixed_points as fp
from error_popup_watcher import ErrorPopupWatcher
import farming
import recovery
import new_ui_intro

# RECON: the module body uses STORE_GLOBAL for the names below, which implies a
# module-level `global` declaration in the original source.
global active_config, active_profiles, last_profile_switch, current_profile_index
global loot_full_confirmed_profiles, pending_under_attack_check

PACKAGE = 'com.supercell.clashofclans'
LAUNCH_GRACE_SECONDS = 90          # a just-launched game may sit on splash / loading screens this long
GLOBAL_STATS = None
GLOBAL_VISION = None
MAIN_DEBUG = False
active_config = {}
active_profiles = []
last_profile_switch = None
current_profile_index = 0
loot_full_confirmed_profiles = set()
pending_under_attack_check = True
runtime_recovery_state = {'active_profile': '__global__', 'mode': 'startup', 'updated_at': 0.0}
REQUIRED_ERROR_TEMPLATES = (
    'error_rating', 'error_rating_button',
    'error_client', 'error_client_button',
    'error_connection', 'error_connection_button',
    'error_device', 'error_device_button',
    'error_inactivity', 'error_inactivity_button',
)


def apply_config(cfg):
    for key, value in cfg.items():
        globals()[key] = value


def _set_runtime_recovery_state(profile=None, mode=None):
    if profile is not None:
        runtime_recovery_state['active_profile'] = profile
    if mode is not None:
        runtime_recovery_state['mode'] = mode
    runtime_recovery_state['updated_at'] = time.time()


def _get_runtime_recovery_profile():
    profile = runtime_recovery_state.get('active_profile')
    if profile and profile != '__global__':
        return profile
    if active_profiles and 0 <= current_profile_index < len(active_profiles):
        return active_profiles[current_profile_index]
    return None


def stop_error_popup_watchdog_for_cleanup():
    vision = globals().get('GLOBAL_VISION')
    stop_event = getattr(vision, '_error_popup_thread_stop', None) if vision else None
    if stop_event is not None:
        stop_event.set()
    watcher = getattr(vision, '_error_popup_watcher', None) if vision else None
    if watcher is not None:
        try:
            watcher.stop()
        except Exception:
            pass


def pause_if_needed():
    vision = globals().get('GLOBAL_VISION')
    process_events = getattr(vision, 'process_error_popup_events', None) if vision else None
    if callable(process_events):
        process_events()
    while control.BotControl.paused:
        if callable(process_events):
            process_events()
        time.sleep(0.2)


def _warn_missing_error_templates(vision):
    missing = [name for name in REQUIRED_ERROR_TEMPLATES if name not in vision.templates]
    if missing:
        print(f'[WATCHDOG] Missing popup templates: {missing}')


def wait_for_village_under_attack_to_clear(vision, max_wait_seconds=180, poll_interval_seconds=5):
    under_attack = vision.match_template(vision.grab(), 'village_under_attack', 0.85)
    if not under_attack:
        return
    print('[MAIN]Village under attack, waiting until finish')
    deadline = time.time() + max_wait_seconds
    while time.time() < deadline:
        time.sleep(poll_interval_seconds)
        still_attacked = vision.match_template(vision.grab(), 'village_under_attack', 0.85)
        if not still_attacked:
            return


def _handle_return_bonus(vision, settle_frame=None):
    if settle_frame is None:
        settle_frame = vision.grab()
    region = (1200, 620, 1360, 740)
    claim = vision.match_template(settle_frame, 'claim_daily', 0.85, region=region)
    if not claim:
        return None
    print('[MAIN]Return bonus detected, claiming daily reward')
    tap(224, 333)
    time.sleep(0.8)
    tap(1304, 701)
    time.sleep(0.6)
    tap(1346, 129)
    time.sleep(0.8)
    return 'return_bonus'


def run_pre_home_village_checks(vision, settle_frame=None, maintenance_wait_seconds=0):
    if settle_frame is None:
        settle_frame = vision.grab()

    if vision.match_template(settle_frame, 'maintenance_break', 0.85):
        if maintenance_wait_seconds > 0:
            print('[STARTUP]Maintenance break detected, waiting')
            time.sleep(maintenance_wait_seconds)
        else:
            print('[MAIN]Maintenance break detected during settle')
        return 'maintenance_break'

    event_dialog = vision.match_template(settle_frame, 'event_dialog', 0.85)
    if event_dialog:
        import new_ui_intro as intro_mod
        if intro_mod.run_new_ui_intro_if_present(vision):
            return 'new_ui'
        print('[MAIN]Event dialog detected, dismissing')
        for _ in range(10):
            if intro_mod.run_new_ui_intro_if_present(vision):
                return 'new_ui'
            tap(*fp.SAFE_CLOSE_POINT)
            time.sleep(0.5)
        card_continue = None
        if vision.templates.get('card_continue'):
            card_continue = vision.match_template(vision.grab(), 'card_continue', 0.85)
        if card_continue:
            print('[MAIN]Card detected, continuing')
            tap(*card_continue)
            time.sleep(0.5)
        return 'event_dialog'

    piggy = None
    if vision.templates.get('piggy_bank'):
        piggy = vision.match_template(settle_frame, 'piggy_bank', 0.85)
    if piggy:
        print('[MAIN]Piggy bank detected, tapping through')
        for _ in range(4):
            tap(800, 813)
            time.sleep(0.4)
        return 'piggy_bank'

    card = None
    if vision.templates.get('card_screen'):
        card = vision.match_template(settle_frame, 'card_screen', 0.85)
    if card:
        print('[MAIN]Card detected, tapping through')
        for _ in range(3):
            tap(int(card[0]), int(card[1]))
            time.sleep(0.4)
        time.sleep(2)
        card_continue = None
        if vision.templates.get('card_continue'):
            card_continue = vision.match_template(vision.grab(), 'card_continue', 0.85)
        if card_continue:
            print('[MAIN]Continuing')
            tap(*card_continue)
            time.sleep(0.5)
        return 'card_open'

    chest = vision.find_treasure_chest()
    if chest:
        print('[TREASURE]Chest detected, opening')
        resolve_chest_reward_sequence(vision, tap, save_treasure_screenshot)
        return 'treasure_chest'

    bonus = _handle_return_bonus(vision, settle_frame=settle_frame)
    if bonus:
        return bonus
    return None


def check_and_switch_profile_if_needed(profile_manager, adb, vision, global_config, recovery,
                                       clan_games=None, force=False):
    global current_profile_index, last_profile_switch, pending_under_attack_check, active_config
    if not (active_config.get('MULTI_VILLAGE_ENABLED', False) and active_profiles and last_profile_switch):
        return False
    if (active_config.get('SWITCH_ON_LOOT_FULL', False) or
            active_config.get('SWITCH_ON_BUILDERS_BUSY', False)) and not force:   # farming decides these
        return False
    now = time.time()
    interval = active_config.get('VILLAGE_SWITCH_MINUTES', 30) * 60
    elapsed = int(now - last_profile_switch)
    if MAIN_DEBUG:
        print(f'[PROFILE TIMER]Elapsed: {elapsed}s / Interval: {interval}s (Need {interval - elapsed}s more)')
    if force or now - last_profile_switch >= interval:
        current_profile_index = (current_profile_index + 1) % len(active_profiles)
        next_profile = active_profiles[current_profile_index]
        _set_runtime_recovery_state(profile=next_profile)
        print(f'[PROFILE]Switching to {next_profile}')
        if not profile_manager.switch_to_profile(next_profile):
            recovery.run(adb, vision, pause_if_needed)
            last_profile_switch = time.time()
            pending_under_attack_check = True
            return True
        profile_config = ConfigManager().load(next_profile)
        merged = global_config.copy()
        merged.update(profile_config)
        active_config = merged
        apply_config(active_config)
        vision.apply_runtime_config(active_config)
        BotControl.emit_config(active_config, next_profile)
        if clan_games:
            clan_games.active_config = active_config
        if clan_games:
            clan_games.cached_cg_super = None
            clan_games.cg_super_selected = False
            clan_games.cached_cg_edit_challenge = None
            clan_games.cg_army_temp_active = False
            clan_games.cg_army_restore_pending = False
        last_profile_switch = time.time()
        pending_under_attack_check = True
        return True
    return False


def main(stats):
    global pending_under_attack_check, active_config, active_profiles, loot_full_confirmed_profiles
    global current_profile_index, last_profile_switch

    pending_under_attack_check = True
    BotControl.running = True
    BotControl.paused = False
    _set_runtime_recovery_state(profile='__global__', mode='startup')
    print('[STARTUP]Launching bot + Starting ADB server')
    emulator = get_selected_emulator()
    adb.set_emulator(emulator)
    ensure_emulator_config_ready(emulator)
    start_adb()
    adb.ensure_ready()
    vision = Vision()
    adb.DEBUG_VISION = vision
    globals()['GLOBAL_VISION'] = vision
    _warn_missing_error_templates(vision)

    if not getattr(vision, '_error_popup_watcher_enabled', False):
        try:
            vision._error_popup_original_grab = vision.grab
            vision._error_popup_pending = None
            vision._hard_popup_reset_requested = False
            vision._error_popup_action_until = 0.0
            vision._error_popup_action_hard = False
            vision._error_popup_restarting = False
            vision._error_popup_latest_logic_frame = None
            vision._error_popup_latest_full_frame = None
            vision._error_popup_full_shape = None
            vision._error_popup_last_subprocess_result_at = 0.0
            vision._error_popup_last_local_check = 0.0
            vision._error_popup_last_health_check = 0.0
            vision._error_popup_last_tick = 0.0
            vision._error_popup_tick_interval_seconds = 60.0
            vision._error_popup_health_interval_seconds = 60.0
            vision._error_popup_popup_threshold = 0.8
            vision._error_popup_button_threshold = 0.8
            vision._error_popup_lock = threading.Lock()
            vision._error_popup_watcher = ErrorPopupWatcher(fp.ERROR_POPUP_CHECK_REGION)
            vision._error_popup_watcher.start()

            def _restart_after_hard_popup():
                global pending_under_attack_check
                if getattr(vision, '_error_popup_restarting', False):
                    return
                vision._error_popup_restarting = True
                try:
                    try:
                        print('[ERROR] Hard popup handled, restarting bot flow')
                        vision._error_popup_pending = None
                        _set_runtime_recovery_state(mode='hard_popup_recovery')
                        profile = _get_runtime_recovery_profile()
                        if profile:
                            active_config['START_PROFILE'] = profile
                            _set_runtime_recovery_state(profile=profile)
                            print(f'[PROFILE] Preserving active profile in memory: {profile}')
                        adb.force_stop(PACKAGE)
                        time.sleep(1)
                        adb.launch_app(PACKAGE)
                        time.sleep(15)
                        deadline = time.time() + 90
                        while time.time() < deadline:
                            if not adb.is_app_in_foreground(PACKAGE):
                                adb.launch_app(PACKAGE)
                                time.sleep(15)
                                continue
                            frame = vision.grab()
                            if frame is not None and vision.match_template(frame, 'app_loading'):
                                time.sleep(2)
                                continue
                            if vision.is_home_village():
                                break
                            time.sleep(1)
                        pending_under_attack_check = True
                        vision._hard_popup_reset_requested = True
                        _set_runtime_recovery_state(mode='home')
                    except Exception as e:
                        print(f'[ERROR] Hard popup restart failed: {e}')
                        vision._hard_popup_reset_requested = True
                finally:
                    vision._error_popup_restarting = False

            def _watched_grab():
                frame = vision._error_popup_original_grab()
                if frame is not None:
                    vision._error_popup_latest_logic_frame = frame
                    full_frame = frame
                    full_shape = getattr(vision, '_error_popup_full_shape', None)
                    if full_shape is None:
                        full_frame = vision.grab_full()
                        if full_frame is not None:
                            vision._error_popup_full_shape = full_frame.shape[:2]
                    elif frame.shape[:2] != full_shape:
                        full_frame = vision.grab_full()
                    if full_frame is not None:
                        if vision._error_popup_full_shape is None:
                            vision._error_popup_full_shape = full_frame.shape[:2]
                        vision._error_popup_latest_full_frame = full_frame
                        vision._error_popup_watcher.submit_frame(full_frame)
                return frame

            def _process_error_popup_events(force=False):
                now = time.time()
                lock = getattr(vision, '_error_popup_lock', None)
                if lock is None:
                    return None
                if not lock.acquire(blocking=False):
                    return None
                try:
                    if not force and now - vision._error_popup_last_tick < vision._error_popup_tick_interval_seconds:
                        return None
                    vision._error_popup_last_tick = now
                    if now - vision._error_popup_last_health_check >= vision._error_popup_health_interval_seconds:
                        vision._error_popup_last_health_check = now
                        watcher = getattr(vision, '_error_popup_watcher', None)
                        if watcher and not watcher.is_alive():
                            print('[WATCHDOG] Popup watcher process died, restarting')
                            watcher.start()
                    detection = vision._error_popup_watcher.poll_detection()
                    if detection:
                        vision._error_popup_pending = detection
                        vision._error_popup_last_subprocess_result_at = now
                    subprocess_stale = now - vision._error_popup_last_subprocess_result_at > 1.5
                    if (not vision._error_popup_pending and subprocess_stale
                            and now - vision._error_popup_last_local_check >= 0.4):
                        vision._error_popup_last_local_check = now
                        full_frame = getattr(vision, '_error_popup_latest_full_frame', None)
                        if full_frame is not None:
                            x1, y1, x2, y2 = fp.ERROR_POPUP_CHECK_REGION
                            crop = full_frame[y1:y2, x1:x2]
                            if crop.size:
                                for popup_key, button_key, is_hard in (
                                    ('error_rating', 'error_rating_button', False),
                                    ('error_client', 'error_client_button', True),
                                    ('error_connection', 'error_connection_button', True),
                                    ('error_device', 'error_device_button', True),
                                    ('error_inactivity', 'error_inactivity_button', True),
                                ):
                                    popup_match = vision.match_template(crop, popup_key, vision._error_popup_popup_threshold)
                                    if not popup_match:
                                        continue
                                    button_match = vision.match_template(crop, button_key, vision._error_popup_button_threshold)
                                    if not button_match:
                                        continue
                                    vision._error_popup_pending = {
                                        'popup_key': popup_key,
                                        'button_key': button_key,
                                        'is_hard': is_hard,
                                        'button_pos': (button_match[0] + x1, button_match[1] + y1),
                                    }
                                    print(f'[ERROR] Local fallback detected popup: {popup_key}')
                                    break
                    if now < vision._error_popup_action_until:
                        return None
                    if vision._error_popup_action_hard:
                        vision._error_popup_action_hard = False
                        _restart_after_hard_popup()
                        return None
                    pending = vision._error_popup_pending
                    if pending and pending.get('button_pos'):
                        vision._error_popup_pending = None
                        tap(*pending['button_pos'])
                        popup_key = pending.get('popup_key', 'error_popup')
                        print(f'[ERROR] Dismissed popup: {popup_key}')
                        if pending.get('is_hard', False):
                            vision._error_popup_action_hard = True
                            vision._error_popup_action_until = now + 15
                        else:
                            vision._error_popup_action_hard = False
                            vision._error_popup_action_until = now + 0.3
                        return pending
                    return None
                finally:
                    lock.release()

            vision.grab = _watched_grab
            vision.process_error_popup_events = _process_error_popup_events
            vision.check_error_popup_once = _process_error_popup_events
            vision._error_popup_thread_stop = threading.Event()

            def _watchdog_background_loop():
                while BotControl.running and not vision._error_popup_thread_stop.is_set():
                    try:
                        _process_error_popup_events()
                    except Exception as e:
                        print(f'[WATCHDOG] Background loop error: {e}')
                    time.sleep(0.2)

            vision._error_popup_thread = threading.Thread(
                target=_watchdog_background_loop, name='error-popup-watchdog', daemon=True)
            vision._error_popup_thread.start()
            vision._error_popup_watcher_enabled = True
        except Exception as e:
            print(f'[WATCHDOG] Failed to start subprocess watcher: {e}')

    try:
        try:
            print('[STARTUP] Checking game state')
            # ---- Startup: make sure CoC is running and sitting on the home village ----
            # FIX: the game was force-stopped and relaunched 5 s after a launch whenever the splash /
            # Supercell screen (no 'app_loading' template) was showing, so a cold emulator start
            # could loop. Now a fresh launch gets LAUNCH_GRACE_SECONDS to reach the village.
            launched_at = 0.0
            while True:
                if not adb.is_app_running(PACKAGE):
                    adb.launch_app(PACKAGE)
                    launched_at = time.time()
                    time.sleep(5)
                frame = vision.grab()
                if frame is None:
                    print('[STARTUP] No frame available yet, retrying')
                    time.sleep(1)
                    continue
                pause_if_needed()
                if vision.match_template(frame, 'app_loading'):
                    print('[STARTUP] Loading screen detected, waiting 5s')
                    time.sleep(5)
                    continue
                pre_result = run_pre_home_village_checks(vision, settle_frame=frame, maintenance_wait_seconds=5)
                if pre_result:
                    continue
                if vision.is_home_village():
                    break
                if time.time() - launched_at < LAUNCH_GRACE_SECONDS:
                    time.sleep(3)
                    continue
                print('[STARTUP]Not on home village, relaunching app')
                adb.force_stop(PACKAGE)
                time.sleep(1)
                adb.launch_app(PACKAGE)
                launched_at = time.time()
                time.sleep(15)

            print('[STARTUP]App ready')
            globals()['GLOBAL_STATS'] = stats
            profile_manager = ProfileManager(vision)
            config_manager = ConfigManager()
            global_config = config_manager.load()
            apply_config(global_config)
            active_config = global_config
            vision.apply_runtime_config(active_config)
            if MAIN_DEBUG:
                print(f'[MAIN]Loaded global_config keys: {list(active_config.keys())}')
                print(f"[MAIN]CG_TROOP_CHALLENGES in config: {active_config.get('CG_TROOP_CHALLENGES', 'NOT FOUND')}")
            clan_games = ClanGames(vision, active_config)
            clan_games.active_config = active_config
            active_profiles = []
            loot_full_confirmed_profiles = set()

            # ---- Multi-village (profile) setup ----
            if active_config.get('MULTI_VILLAGE_ENABLED', False):
                village_count = active_config.get('VILLAGE_COUNT', 0)
                calibrated_count = profile_manager.get_calibrated_profile_count()
                if not profile_manager.profiles_initialized() or village_count > calibrated_count:
                    print('[PROFILES]Calibrating profiles')
                    profile_manager.calibrate_profiles(village_count)
                    BotControl.emit_config(active_config, None)
                    print('[PROFILES]Closing profile screen')
                    tap(*fp.HOME_CLOSE_PROFILES)
                    time.sleep(1)
                    tap(*fp.HOME_CLOSE_SETTINGS)
                    time.sleep(1)
                    tap(*fp.SAFE_CLOSE_POINT)
                    time.sleep(2)
                    calib_start = time.time()
                    while not vision.is_home_village():
                        pause_if_needed()
                        if time.time() - calib_start > 30:
                            print('[WATCHDOG] Calibration home timeout')
                            recovery.run(adb, vision, pause_if_needed)
                            return None
                        print('[PROFILES]Waiting for home village after calibration')
                        time.sleep(1)
                active_profiles = profile_manager.get_enabled_profiles()
                if active_profiles:
                    if active_config.get('START_PROFILE') in active_profiles:
                        current_profile_index = active_profiles.index(active_config.get('START_PROFILE'))
                    start_profile = active_profiles[current_profile_index]
                    _set_runtime_recovery_state(profile=start_profile)
                    print(f'[PROFILES]Starting on {start_profile}')
                    if not profile_manager.switch_to_profile(start_profile):
                        recovery.run(adb, vision, pause_if_needed)
                        return None
                    time.sleep(3)
                    profile_config = config_manager.load(start_profile)
                    merged = global_config.copy()
                    merged.update(profile_config)
                    active_config = merged
                    apply_config(active_config)
                    vision.apply_runtime_config(active_config)
                    BotControl.emit_config(active_config, start_profile)
                    clan_games.active_config = active_config
                    last_profile_switch = time.time()

            # ---- Main loop ----
            print('[BOT]Main loop started')
            while BotControl.running:
                pause_if_needed()

                frame = vision.grab()
                maintenance = vision.match_template(vision.grab(), 'maintenance_break', 0.85)
                if maintenance:
                    print('[MAIN]Maintenance break detected')
                    next_restart_at = 0.0
                    while BotControl.running:
                        pause_if_needed()
                        still_maintenance = vision.match_template(vision.grab(), 'maintenance_break', 0.85)
                        if not still_maintenance:
                            print('[MAIN]Maintenance break cleared')
                            break
                        now = time.time()
                        if now >= next_restart_at:
                            print('[MAIN]Restarting Clash of Clans for maintenance retry')
                            adb.force_stop(PACKAGE)
                            time.sleep(1)
                            adb.launch_app(PACKAGE)
                            time.sleep(20)
                            next_restart_at = now + 300
                        else:
                            time.sleep(2)
                    continue

                if pending_under_attack_check:
                    wait_for_village_under_attack_to_clear(vision, max_wait_seconds=180, poll_interval_seconds=5)
                    pending_under_attack_check = False

                print('[MAIN]Loading village...')
                settle_deadline = time.time() + 30
                while time.time() < settle_deadline:
                    pause_if_needed()
                    settle_frame = vision.grab()
                    if vision.match_template(settle_frame, 'bb_detection', 0.85):
                        print('[MAIN]Detected Builder Base during settle, returning to home village')
                        swipe(*fp.BUILDER_SWIPE_DOWN)
                        time.sleep(0.5)
                        swipe(*fp.BUILDER_SWIPE_LEFT)
                        time.sleep(0.5)
                        bb_home = vision.match_template(vision.grab(), 'bb_home', 0.6)
                        if bb_home:
                            tap(*bb_home)
                        time.sleep(1)
                        continue
                    if vision.match_template(settle_frame, 'maintenance_break', 0.85):
                        print('[MAIN]Maintenance break detected during settle')
                        break
                    pre_result = run_pre_home_village_checks(vision, settle_frame=settle_frame)
                    if pre_result == 'maintenance_break':
                        break
                    if pre_result:
                        continue
                    if vision.match_template_region(fp.HOME_ATTACK_BUTTON_REGION, 'attack_button'):
                        break
                    time.sleep(1)

                new_ui_intro.run_new_ui_intro_if_present(vision)

                if check_and_switch_profile_if_needed(profile_manager, adb, vision, global_config, recovery, clan_games):
                    continue

                frame = vision.grab()
                if vision.match_template(frame, 'bb_detection', 0.85):
                    print('[HOME]Detected Builder Base, returning to home village')
                    swipe(*fp.BUILDER_SWIPE_DOWN)
                    time.sleep(0.5)
                    swipe(*fp.BUILDER_SWIPE_LEFT)
                    time.sleep(0.5)
                    bb_frame = vision.grab()
                    bb_home = vision.match_template(bb_frame, 'bb_home', 0.6)
                    if bb_home:
                        tap(*bb_home)
                    continue

                _set_runtime_recovery_state(mode='farming')
                result = farming.run_farming(
                    adb=adb,
                    vision=vision,
                    stats=stats,
                    active_config=active_config,
                    pause_if_needed=pause_if_needed,
                    profile_manager=profile_manager,
                    global_config=global_config,
                    recovery=recovery,
                    clan_games=clan_games,
                )
                if result == 'RECOVERY':
                    recovery.run(adb, vision, pause_if_needed)
                    time.sleep(2)
                    continue
                elif result == 'STOP_BOT':
                    print('[BOT] ✅ All profiles have full loot! Stopping bot.')
                    BotControl.running = False
                    break
                elif result == 'END_CONDITION':
                    print('[BOT] End condition reached, stopping the bot')
                    BotControl.running = False
                    break
                elif result == 'PROFILE_SWITCH':
                    check_and_switch_profile_if_needed(profile_manager, adb, vision, global_config, recovery,
                                                       clan_games, force=True)
                    continue
            return stats
        except Exception as e:
            print(f'[WATCHDOG] Main loop error: {e.__class__.__name__}: {e}')
            raise
    finally:
        stop_error_popup_watchdog_for_cleanup()


if __name__ == '__main__':
    main(Stats())
