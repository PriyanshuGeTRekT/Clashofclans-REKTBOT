# rewards.py - claim free event rewards (new module, Pro feature).
#
# Current Clash of Clans has no achievements list in the profile any more; free rewards are claimed
# from the Events window (calendar button in the bottom bar, red badge when something is waiting).
# Each event card has a green "Claim" button when rewards are ready. Event pages differ per event,
# so only the generic Claim button on the Events list is used (templates/collect/events_*.png).
import time

from adb import tap

EVENTS_BUTTON = (395, 838)
EVENTS_TITLE_REGION = (650, 30, 950, 105)
EVENTS_CLOSE = (1318, 66)
CLAIM_THRESHOLD = 0.82
INTERVAL_SECONDS = 3 * 3600

_state = {'next_run': 0.0}


def _log(msg):
    print(f'[REWARDS] {msg}')


def due(cfg):
    return bool(cfg.get('CLAIM_EVENT_REWARDS', False)) and time.time() >= _state['next_run']


def _events_open(vision):
    return vision.match_template_region(EVENTS_TITLE_REGION, 'events_title', 0.8) is not None


def run(vision, cfg):
    _state['next_run'] = time.time() + INTERVAL_SECONDS
    tap(*EVENTS_BUTTON)
    time.sleep(2.0)
    if not _events_open(vision):
        _log('Events window did not open')
        return 0
    claimed = 0
    tapped = []
    for _ in range(5):
        claim = vision.match_template(vision.grab(), 'events_claim', CLAIM_THRESHOLD)
        # A Claim button that is still there after a visit has nothing more to give (the event
        # page shows everything collected): tap each event once per run.
        if not claim or any(abs(claim[0] - x) < 30 and abs(claim[1] - y) < 30 for x, y in tapped):
            break
        tapped.append(claim)
        tap(*claim)
        time.sleep(2.0)
        # A claim opens the event page: close it to get back to the Events list.
        close = vision.match_template_region((1300, 20, 1460, 120), 'upgrade_window_close', 0.8)
        if close:
            tap(*close)
            time.sleep(1.5)
        if not _events_open(vision):
            tap(*EVENTS_BUTTON)
            time.sleep(2.0)
        claimed += 1
    if claimed:
        _log(f'Claimed rewards from {claimed} event(s)')
    for _ in range(2):
        if _events_open(vision):
            tap(*EVENTS_CLOSE)
            time.sleep(1.0)
    return claimed
