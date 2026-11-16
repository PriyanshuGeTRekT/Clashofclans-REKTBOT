# Reconstructed from Pyarmor-decrypted bytecode (recovery, Python 3.10).
import time
from actions import click_point

PACKAGE = 'com.supercell.clashofclans'


def run(adb, vision, pause_if_needed):
    adb_ = adb
    pause = pause_if_needed
    print('[RECOVERY]Running recovery')
    pause()
    dialog = vision.find_error_dialog()
    if dialog:
        _, button_pos = dialog
        import fixed_points as fp
        if vision.match_template(vision.grab(), 'error_device', 0.8, region=fp.ERROR_POPUP_CHECK_REGION):
            # 'Another device is connecting to this Village': leave the village to that device for the
            # configured time (Schedule > Another device) before reconnecting.
            import main
            from control import BotControl
            wait_seconds = main.device_conflict_wait_seconds()
            if wait_seconds > 0 and not BotControl.hold_until:
                print(f'[ERROR] Another device is connecting to this village. '
                      f'Reconnecting in {wait_seconds / 60:g} minute(s)')
                deadline = time.time() + wait_seconds
                while time.time() < deadline and BotControl.running:
                    time.sleep(0.5)
                if not vision.match_template(vision.grab(), 'error_device', 0.8, region=fp.ERROR_POPUP_CHECK_REGION):
                    print('[ERROR] Wait is over, the popup is gone - carrying on')
                    return
                print('[ERROR] Wait is over, reconnecting to the village')
        click_point(adb_, button_pos)
        pause()
        time.sleep(8)
        return
    import smart
    if smart.on_lost(smart.config(), vision, adb_):     # Smart page: get home with safe taps (optional)
        return
    adb_.force_stop(PACKAGE)
    pause()
    time.sleep(2)
    adb_.launch_app(PACKAGE)
    pause()
    time.sleep(10)
    print('[RECOVERY]Relaunched')
