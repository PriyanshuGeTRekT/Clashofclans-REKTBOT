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
CARD_XS = [178 + round(126.4 * i) for i in range(11)]      # 20 Nov: the first card is at x=186
CARD_Y = 815
CARD_LIVE_BRIGHTNESS = 110
DEPLOY_ROUNDS = 4
DEPLOY_STEP = (200, 90)
# Spots from the middle of the map outwards; clear of End Battle (bottom left), the card bar and the
# 1x button. Checked live: 15 of these put all 10 squads down in a half-destroyed district.
DEPLOY_SPOTS = sorted(((x, y) for x in range(430, 1231, DEPLOY_STEP[0]) for y in range(240, 601, DEPLOY_STEP[1])),
                      key=lambda p: (p[0] - 830) ** 2 + ((p[1] - 420) * 1.6) ** 2)
BATTLE_TIMEOUT_SECONDS = 240
RECHECK_SECONDS = 4 * 3600
RETRY_SECONDS = 10 * 60              # the trip to the capital failed: try again soon...
MAX_FAILED_TRIPS = 3                 # ...but after this many in a row wait RECHECK_SECONDS
AIRSHIP_THRESHOLD = 0.7
AIRSHIP_SCALES = (1.0, 1.05, 1.1, 0.95, 0.9, 1.15, 1.2, 0.85, 0.8, 0.7, 0.6, 0.5)

_state = {'next_run': 0.0, 'failed_trips': 0}


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


def _find_airship(vision, looks=3):
    """(position, score) of the airship on the shore, position None below AIRSHIP_THRESHOLD.

    FIX (20 Nov): one look right after the map drag missed it (the map still glides for a moment, and
    at this zoom the picture fits best at 105 %, a size that was not tried: 0.64 at 100 %, 0.89 at
    105 %). Now several sizes and up to `looks` frames."""
    tpl = vision.templates.get('capital_airship')
    if not tpl:
        return None, 0.0
    img = tpl['img']
    if img.ndim == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    best, best_score = None, 0.0
    for look in range(looks):
        if look:
            time.sleep(0.8)
        gray = cv2.cvtColor(vision.grab(), cv2.COLOR_BGR2GRAY)
        for s in AIRSHIP_SCALES:
            t = img if s == 1.0 else cv2.resize(img, None, fx=s, fy=s,
                                                interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
            _mn, score, _ml, loc = cv2.minMaxLoc(cv2.matchTemplate(gray, t, cv2.TM_CCOEFF_NORMED))
            if score > best_score:
                best, best_score = (loc[0] + t.shape[1] // 2, loc[1] + t.shape[0] // 2), score
        if best_score >= AIRSHIP_THRESHOLD:
            return best, best_score
    return None, best_score


def go_to_capital(vision):
    from ui2_zoom import zoom_out
    zoom_out()
    time.sleep(0.5)
    seen = 0.0
    for pan in (None,) + AIRSHIP_PANS:
        if pan:
            swipe(*pan, duration=500)
            time.sleep(1.5)
        hit, score = _find_airship(vision)
        seen = max(seen, score)
        if hit:
            _log(f'Airship found at {hit} (score {score:.2f}), flying to the Clan Capital')
            tap(*hit)
            if _wait(lambda: _on_capital(vision), 15):
                return True
            _log(f'The Clan Capital did not open, saved {_save(vision, "no_capital")}')
            return False
    _log(f'Airship not found (best score {seen:.2f}), saved {_save(vision, "no_airship")}')
    for x1, y1, x2, y2 in reversed(AIRSHIP_PANS):        # put the map back where the home routines expect it
        swipe(x2, y2, x1, y1, duration=500)
        time.sleep(1.0)
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


def _in_battle(screen):
    """The red Surrender / End Battle button is on screen (0.67-0.69 of that spot is red in a battle,
    0.00-0.01 on the raid map, the Attack Now? window and the result screens)."""
    h = cv2.cvtColor(screen[645:695, 35:195], cv2.COLOR_BGR2HSV)
    red = ((h[..., 0] < 8) | (h[..., 0] > 172)) & (h[..., 1] > 150) & (h[..., 2] > 140)
    return float(red.mean()) > 0.4


def _live_cards(screen):
    """Slots of the raid battle bar that hold a card with something left: a live card is bright
    (mean brightness 155-180), a used one is grey and an empty slot shows the dimmed map (44-84).
    Empty outside a battle."""
    if not _in_battle(screen):
        return []
    hsv = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)
    return [i for i, x in enumerate(CARD_XS)
            if float(hsv[770:860, x - 40:x + 40, 2].mean()) > CARD_LIVE_BRIGHTNESS]


def _deploy_all(vision=None):
    """Play every card of the raid battle bar. Returns how many cards still have something left.

    FIX (20 Nov, two raid attacks ended at 0 %): the first slot (the troops) was never tapped, the
    list started at the second one, so only spells were played; and troops only land inside the area
    the game highlights, which is not the old line along the bottom. Now every live card is tapped,
    followed by a grid of spots from the middle of the map outwards: taps outside the highlighted
    area are ignored by the game, the others drop a squad each. Repeated while a card stays lit."""
    from adb import tap_batch_small
    for round_no in range(DEPLOY_ROUNDS):
        live = _live_cards(vision.grab()) if vision is not None else list(range(len(CARD_XS)))
        if not live:
            return 0
        shift = (0, 0) if round_no % 2 == 0 else (DEPLOY_STEP[0] // 2, DEPLOY_STEP[1] // 2)
        spots = [(x + shift[0], y + shift[1]) for x, y in DEPLOY_SPOTS]
        for i in live:
            tap(CARD_XS[i], CARD_Y)
            time.sleep(0.25)
            # every spot twice: on a fresh district the highlighted area is a narrow strip that only
            # a few spots hit, and each tap inside it drops one more squad
            tap_batch_small([p for p in spots for _ in range(2)])
            time.sleep(0.3)
    return len(_live_cards(vision.grab())) if vision is not None else 0


CONFIRM_TITLE_REGION = (500, 80, 1100, 180)
CONFIRM_ATTACK_REGION = (1150, 440, 1500, 580)
NEXT_RAID_REGION = (600, 740, 1000, 860)


def _next_raid_if_offered(vision):
    """UPDATE (seen 20 Nov): when the clan finishes a raid, a "Congratulations ... Next Raid" window
    covers the raid map. Tap Next Raid to get the map of the next enemy capital."""
    btn = vision.match_template_region(NEXT_RAID_REGION, 'capital_next_raid', 0.8)
    if not btn:
        return False
    _log('Raid finished by the clan, moving on to the next raid')
    tap(*btn)
    time.sleep(3.0)
    return True


def _confirm_attack(vision):
    """UPDATE (seen 20 Nov): the district's Attack button now opens "Attack Now?" (the army, a green
    Attack and Edit Army). The battle only starts from that green Attack; without this step the bot
    sat on the window until the battle timeout."""
    if not _wait(lambda: vision.match_template_region(CONFIRM_TITLE_REGION, 'capital_attack_now', 0.8) is not None,
                 6, 0.5):
        return
    btn = vision.match_template_region(CONFIRM_ATTACK_REGION, 'capital_attack_confirm', 0.8)
    _log('Attack Now? window: starting the raid attack')
    tap(*(btn or (1321, 514)))
    time.sleep(1.0)


def _raid_battle(vision):
    """Deploy everything, then wait for the end screen ('Map' button) and tap it."""
    _confirm_attack(vision)
    # wait for the battle screen: a lit card in the bar (the district loads for a few seconds)
    _wait(lambda: bool(_live_cards(vision.grab())), 20, 1.0)
    time.sleep(1.0)
    left = _deploy_all(vision)
    _log('Everything deployed' if not left else f'{left} card(s) could not be played completely')
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
        # FIX (20 Nov): one missed airship switched the raids off for 4 hours. Try again after
        # RETRY_SECONDS, up to MAX_FAILED_TRIPS times in a row.
        _state['failed_trips'] += 1
        if _state['failed_trips'] < MAX_FAILED_TRIPS:
            _state['next_run'] = time.time() + RETRY_SECONDS
            _log(f'Trying again in {RETRY_SECONDS // 60} minutes')
        else:
            _state['failed_trips'] = 0
            _log(f'Giving up for {RECHECK_SECONDS // 3600} hours')
        return 'skipped' if vision.is_home_village() else 'RECOVERY'
    _state['failed_trips'] = 0
    tap(*RAID_MAP_BUTTON)
    time.sleep(2.0)
    _next_raid_if_offered(vision)
    if not _wait(lambda: _on_raid_map(vision), 10):
        _log('No raid weekend running (Raid Map did not open)')
        return 'done' if go_home(vision) else 'RECOVERY'
    attacks = 0
    for _attempt in range(int(cfg.get('CAPITAL_MAX_RAIDS', 6) or 6)):
        if callable(pause_if_needed):
            pause_if_needed()
        _next_raid_if_offered(vision)
        attacked = False
        for pos in DISTRICTS:
            tap(*pos)
            time.sleep(1.2)
            screen = vision.grab()
            # FIX (20 Nov, two bugs seen with 5 attacks left and only Capital Peak standing):
            #  - the picture is compared in greyscale, so the red live Attack matched the grey one
            #    (score >= 0.85) and was taken for "no attacks left": the colour decides now
            #    (share of saturated pixels: 0.85 on the red button, 0.00 on the grey one);
            #  - a grey Attack also means "this district is already destroyed", so a grey button only
            #    skips that district.
            attack = None
            if vision.match_template(screen, 'capital_attack_grey', 0.6, region=ATTACK_REGION):
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
            _log('No district can be attacked now (all destroyed, or no raid attacks left)')
            break
        if not _raid_battle(vision):
            return 'RECOVERY'
        attacks += 1
    _log(f'{attacks} raid attack(s) made')
    return 'done' if go_home(vision) else 'RECOVERY'
