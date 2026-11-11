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
        click_point(adb_, button_pos)
        pause()
        time.sleep(8)
        return
    adb_.force_stop(PACKAGE)
    pause()
    time.sleep(2)
    adb_.launch_app(PACKAGE)
    pause()
    time.sleep(10)
    print('[RECOVERY]Relaunched')
