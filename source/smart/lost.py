# smart/lost.py - vision-model fallback for screens the bot does not know.
#
# Normally a lost bot force-restarts the game. With this switched on it first shows Claude the
# screenshot and asks for ONE safe tap that leads back to the home village (close a window, press
# Continue, Return Home...). At most MAX_STEPS taps, then the normal restart happens anyway.
# Claude is told never to spend anything, and a tap it flags as spending is not made.
import time

from adb import tap

MAX_STEPS = 4
SYSTEM = (
    'You help an automation tool that got stuck in the mobile game Clash of Clans. You see a '
    '1600x900 landscape screenshot. The goal is to get back to the home village main screen with no '
    'window open. Choose exactly one action. Prefer the red X close button, "Okay"/"Continue" on '
    'information screens, "Return Home", "Reload" or "Try again". Never choose a tap that spends '
    'gems, gold, elixir, dark elixir or real money, starts an upgrade, a purchase, an attack or a '
    'donation, changes settings, or logs in or out of an account. If the only way forward would do '
    'one of those, or you are unsure, choose "none". Coordinates are screenshot pixels.'
)
SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['screen', 'action', 'x', 'y', 'spends_or_commits', 'reason'],
    'properties': {
        'screen': {'type': 'string', 'description': 'What this screen is, in a few words'},
        'action': {'type': 'string', 'enum': ['tap', 'wait', 'none']},
        'x': {'type': 'integer'}, 'y': {'type': 'integer'},
        'spends_or_commits': {'type': 'boolean',
                              'description': 'True if the tap could spend, buy, upgrade, attack or change settings'},
        'reason': {'type': 'string'},
    },
}


def _log(msg):
    print(f'[SMART AI] {msg}')


def rescue(cfg, vision, adb=None):
    from smart import ai
    import adb as adb_module
    if not adb_module.is_app_in_foreground('com.supercell.clashofclans'):
        return False                              # game closed or crashed: the normal restart handles it
    tapped = False
    for step in range(1, MAX_STEPS + 1):
        if vision.is_home_village():
            if tapped:
                _log('Back on the home village, no restart needed')
            return tapped                         # already home with no tap: let the restart happen
        screen = vision.grab()
        answer = ai.ask_json(cfg, 'Where should the tool tap to get back to the home village?', SCHEMA,
                             image_bgr=screen, system=SYSTEM)
        if not answer:
            return False
        _log(f'Step {step}: screen is "{answer.get("screen")}" -> {answer.get("action")} '
             f'({answer.get("reason")})')
        action = answer.get('action')
        if action == 'none' or answer.get('spends_or_commits'):
            return False
        if action == 'wait':
            time.sleep(4)
            continue
        x, y = int(answer.get('x', -1)), int(answer.get('y', -1))
        if not (0 <= x < screen.shape[1] and 0 <= y < screen.shape[0]):
            return False
        tap(x, y)
        tapped = True
        time.sleep(2.5)
    return tapped and bool(vision.is_home_village())
