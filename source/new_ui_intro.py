# new_ui_intro.py -- reconstructed from Pyarmor-decrypted CPython 3.10 bytecode
# (decrypted/new_ui_intro.dis.txt). Local names were obfuscated and are renamed.
import time
import adb
import fixed_points as fp

_NEW_UI_INTRO_STEPS = fp.NEW_UI_INTRO_STEPS


def _run_steps(steps):
    # Each step: (delay_ms, kind, x, y, *extra)
    for delay_ms, kind, x, y, *extra in steps:
        if delay_ms > 0:
            time.sleep(delay_ms / 1000)
        if kind == 'swipe':
            x2, y2, duration = extra
            adb.swipe(x, y, x2, y2, duration)
        elif kind == 'hold':
            adb.swipe(x, y, x, y, extra[0])   # long-press implemented as a zero-length swipe
        else:
            adb.tap_raw(x, y)


def run_new_ui_intro_if_present(vision):
    v = vision
    if not v.match_template(v.grab(), 'new_ui', fp.NEW_UI_MATCH_THRESHOLD):
        return False
    print('[NEW_UI] New UI intro detected, running walkthrough')
    _run_steps(_NEW_UI_INTRO_STEPS)
    print('[NEW_UI] New UI intro complete')
    time.sleep(2)
    return True
