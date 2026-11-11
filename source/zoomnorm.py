# zoomnorm.py - scenery-independent zoom level (new module).
#
# Every template, fixed point and deploy line in the bot was captured at the zoom you get when
# fully zoomed out in the classic scenery (battle scouting views are at that zoom too). Some
# sceneries let the camera zoom out much further: the home village is then drawn at ~55% size
# (measured 11 Nov, "Dark knights" scenery) and building templates stop matching.
#
# measure_scale() finds the Town Hall at several template scales; the best one is the village's
# drawing scale relative to the reference (1.0). normalize() pinch-zooms in (or out) until the
# scale is within TOLERANCE of 1.0. Nothing is done when no Town Hall is visible (Builder Base,
# loading screens), so callers can run it after every zoom-out.
import os
import time

import cv2
import numpy as np

TARGET = 1.0
TOLERANCE = 0.08            # battle views measure 0.95-1.05
MIN_SCORE = 0.70            # below this the Town Hall was not really found (false hits score ~0.64)
COARSE_SCALES = [round(s, 2) for s in np.arange(0.30, 1.41, 0.06)]   # far-out sceneries to zoomed-in views
MAX_STEPS = 4

_state = {'template': None, 'last_scale': None, 'last_score': 0.0, 'world_scale': 1.0}


def _log(msg):
    print(f'[ZOOM] {msg}')


def _templates(vision):
    tpls = getattr(vision, 'th_templates', None) or {}
    if _state['template'] is None:
        _state['template'] = _load_cal().get('th_template')      # remembered across sessions
    if _state['template'] in tpls:
        # the player's own Town Hall level first: it is almost always the right one at home
        return [(_state['template'], tpls[_state['template']])] + \
               [(k, v) for k, v in tpls.items() if k != _state['template']]
    return list(tpls.items())


def _best(gray, tpl_gray, scales):
    best = (-1.0, None, None)
    for s in scales:
        t = cv2.resize(tpl_gray, None, fx=s, fy=s, interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
        if t.shape[0] >= gray.shape[0] or t.shape[1] >= gray.shape[1] or t.shape[0] < 8:
            continue
        r = cv2.matchTemplate(gray, t, cv2.TM_CCOEFF_NORMED)
        _, m, _, loc = cv2.minMaxLoc(r)
        if m > best[0]:
            best = (m, s, (loc[0] + t.shape[1] // 2, loc[1] + t.shape[0] // 2))
    return best


SEARCH_BOX = (120, 50, 1480, 760)      # skip the HUD (loot, buttons, troop bar)


def measure_scale(vision, screen=None):
    """(scale, score, pos) of the village drawing relative to the reference zoom, or (None, score, None).

    Colour matching like Vision.find_townhall (grey matching locks onto random walls)."""
    screen = vision.grab() if screen is None else screen
    if screen is None:
        return None, 0.0, None
    x1, y1, x2, y2 = SEARCH_BOX
    roi = screen[y1:y2, x1:x2]
    coarse = []
    for name, tpl in _templates(vision):
        img = tpl['img'] if tpl['img'].ndim == 3 else cv2.cvtColor(tpl['img'], cv2.COLOR_GRAY2BGR)
        # full resolution: at half size a 0.55x Town Hall template is only ~7x17 px and never matches
        m, sc, _pos = _best(roi, img, COARSE_SCALES)
        if sc is not None:
            coarse.append((m, sc, name, img))
        if name == _state['template'] and m >= MIN_SCORE:
            break                        # the player's own level (remembered, tried first) is there
        # (no early exit for other levels: a look-alike building scored 0.79 at the wrong scale, 11 Nov)
    if not coarse:
        return None, 0.0, None
    # Refine the three best levels: on the 0.06 coarse grid a neighbouring Town Hall level can win by
    # a hair (fresh install, no remembered level, 11 Nov) and then refine below MIN_SCORE.
    best = (-1.0, None, None, None)
    for _m, csc, cname, cimg in sorted(coarse, key=lambda c: -c[0])[:3]:
        fine = [round(csc + d, 3) for d in (-0.04, -0.02, 0.0, 0.02, 0.04) if csc + d > 0.2]
        fm, fsc, fpos = _best(roi, cimg, fine)
        if fm > best[0]:
            best = (fm, fsc, fpos, cname)
    m, sc, pos, name = best
    _state['last_scale'], _state['last_score'] = sc, m
    # A Town Hall template shrunk below ~0.5x is a few pixels tall and matches noise (0.73 at 0.30x on
    # a zoomed-in view): demand more the smaller it gets. Far-out sceneries then use the probe spread.
    need = MIN_SCORE + max(0.0, 0.5 - (sc or 0)) * 0.5
    if m < need or pos is None:
        return None, m, None
    if name != _state['template']:
        _state['template'] = name
        cal = _load_cal()
        if cal.get('th_template') != name and sc < 0.9:
            cal['th_template'] = name    # only remember it from the home view (battles vary)
            _save_cal(cal)
    return float(sc), float(m), (pos[0] + x1, pos[1] + y1)


CALIBRATION_FILE = os.path.join('logs', 'zoom_calibration.json')
PROBE_TRAVEL = 120                      # spread used when the Town Hall is too small to measure
TRAVEL_RANGE = (40, 320)                # finger travel (px) searched during calibration


def _load_cal():
    try:
        import json
        with open(CALIBRATION_FILE, encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return {}


def _save_cal(cal):
    try:
        import json
        os.makedirs(os.path.dirname(CALIBRATION_FILE), exist_ok=True)
        with open(CALIBRATION_FILE, 'w', encoding='utf-8') as fh:
            json.dump(cal, fh, indent=1)
    except Exception as exc:
        _log(f'could not save the zoom calibration: {exc}')


def _key(scale):
    # sceneries are told apart by how far they zoom out: the fully zoomed-out scale, to 0.05
    return f'{round(scale * 20) / 20:.2f}'


def normalize(vision, zoom_out_full, spread, label=''):
    """Bring a fully zoomed-out village to the reference scale with ONE calibrated spread.

    The game's pinch response is non-linear (dead zone, overshoot; step-by-step correction was
    erratic, 11 Nov), so every attempt starts from full zoom-out, a known state per scenery, and the
    spread length that reaches TARGET is found once by bisection and stored per scenery.
    zoom_out_full() zooms fully out, spread(px) spreads the fingers by px. Returns the final scale."""
    _state['world_scale'] = 1.0
    scale, _score, _pos = measure_scale(vision)
    probe = 0
    if scale is None:
        # A scenery that zooms out very far draws the Town Hall too small to measure (or this is
        # not the home village at all). One probe spread tells them apart.
        spread(PROBE_TRAVEL)
        time.sleep(1.0)
        scale, _score, _pos = measure_scale(vision)
        if scale is None:
            zoom_out_full()              # still nothing: not a home village view, undo the probe
            return None
        probe = PROBE_TRAVEL
        if abs(scale - TARGET) <= TOLERANCE:
            return scale
        zoom_out_full()
        time.sleep(0.8)
    if abs(scale - TARGET) <= TOLERANCE:
        return scale
    if scale > TARGET:
        # This scenery cannot zoom out as far as the reference: village objects are drawn bigger.
        # Zooming cannot fix that; world-object matching (collect bubbles, obstacles) uses the scale.
        _state['world_scale'] = scale
        _log(f'{label}village drawn at {scale:.2f}x even fully zoomed out; scaling village templates')
        return scale
    cal = _load_cal()
    key = ('probe-' if probe else '') + _key(scale)
    travel = cal.get(key)
    if travel:
        # the same spread lands at 0.96x most times and 0.90x now and then (the zoom animation
        # varies), so a miss is retried once from full zoom-out before recalibrating
        for attempt in range(2):
            if attempt:
                zoom_out_full()
                time.sleep(0.8)
            spread(travel)
            time.sleep(1.0)
            got, _s, _p = measure_scale(vision)
            if got is not None and abs(got - TARGET) <= TOLERANCE:
                return got
        _log(f'{label}stored spread for scenery {key} gave {got} twice, recalibrating')
    _log(f'{label}village drawn at {scale:.2f}x (scenery zooms out further), calibrating the zoom')
    lo, hi = TRAVEL_RANGE
    best = (9.0, None, None)
    for _ in range(7):
        mid = (lo + hi) / 2
        zoom_out_full()
        time.sleep(0.8)
        spread(mid)
        time.sleep(1.0)
        got, _s, _p = measure_scale(vision)
        if got is None:
            # No Town Hall: zoomed in so far it left the screen, unless this is a far-out scenery (it was
            # only measurable after the probe spread) and this spread is shorter than the probe.
            if probe and mid < probe:
                lo = mid
            else:
                hi = mid
            continue
        if abs(got - TARGET) < best[0]:
            best = (abs(got - TARGET), mid, got)
        if abs(got - TARGET) <= TOLERANCE / 2:
            break
        if got < TARGET:
            lo = mid
        else:
            hi = mid
    _err, travel, got = best
    if travel is None:
        _log(f'{label}zoom calibration failed')
        return scale
    if got is not None and abs(got - TARGET) > TOLERANCE:
        _state['world_scale'] = got
    if abs(got - TARGET) > TOLERANCE:
        # leave the view at the best spread found
        zoom_out_full(); time.sleep(0.6); spread(travel); time.sleep(0.6)
        got, _s, _p = measure_scale(vision)
        _log(f'{label}best reachable scale {got}')
    elif best[1] != mid:
        zoom_out_full(); time.sleep(0.6); spread(travel); time.sleep(0.6)
        got, _s, _p = measure_scale(vision)
    if got is not None and abs(got - TARGET) <= TOLERANCE:
        cal[key] = round(travel, 1)
        _save_cal(cal)
        _log(f'{label}scenery {key}: {round(travel)} px spread -> scale {got:.2f} (saved)')
    return got


def world_scale():
    """Scale village objects are drawn at after normalize() (1.0 unless the reference zoom could not
    be reached). Reset by reset_world_scale() whenever the view changes (battle, Builder Base)."""
    return _state['world_scale']


def reset_world_scale():
    _state['world_scale'] = 1.0


def match_world(screen, tpl, threshold, method=cv2.TM_CCOEFF_NORMED):
    """matchTemplate for a village-object template: the template as captured, and if that finds
    nothing while world_scale() is off, the template resized to the current world scale.
    Returns (result_map, template_used)."""
    res = cv2.matchTemplate(screen, tpl, method)
    ws = _state['world_scale']
    if abs(ws - 1.0) > TOLERANCE and cv2.minMaxLoc(res)[1] < threshold:
        t2 = cv2.resize(tpl, None, fx=ws, fy=ws, interpolation=cv2.INTER_AREA if ws < 1 else cv2.INTER_LINEAR)
        if t2.shape[0] < screen.shape[0] and t2.shape[1] < screen.shape[1]:
            res2 = cv2.matchTemplate(screen, t2, method)
            if cv2.minMaxLoc(res2)[1] > cv2.minMaxLoc(res)[1]:
                return res2, t2
    return res, tpl


def enabled():
    return os.environ.get('CRB_ZOOM_NORMALIZE', '1') != '0'
