# smart/canary.py - "what broke?" check after a game update.
#
# Walks the screens every attack needs (home village -> Battle menu -> army screen -> saved armies)
# WITHOUT attacking or changing anything, and scores each button picture against what is on screen.
# Runs by itself when the game's version number changes (Smart page switch), or from the
# "Run update check" button. The report is printed and saved to logs/canary_report_<version>.txt.
import json
import re
import time
from pathlib import Path

import cv2

import fixed_points as fp
from adb import adb_target, tap
from utils.runtime_paths import resolve_writable_path

PACKAGE = 'com.supercell.clashofclans'
OK_SCORE = 0.85


def _log(msg):
    print(f'[UPDATE CHECK] {msg}')


def game_version():
    out = adb_target(['shell', 'dumpsys', 'package', PACKAGE]) or ''
    m = re.search(r'versionName=(\S+)', out)
    return m.group(1) if m else None


def _state_path():
    return Path(resolve_writable_path('logs')) / 'canary.json'


def _load_state():
    try:
        return json.loads(_state_path().read_text(encoding='utf-8'))
    except Exception:
        return {}


def _score(vision, screen, key, region=None):
    tpl = vision.templates.get(key)
    if not tpl:
        return None
    img = screen if region is None else screen[region[1]:region[3], region[0]:region[2]]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    t = tpl['img'] if len(tpl['img'].shape) == 2 else cv2.cvtColor(tpl['img'], cv2.COLOR_BGR2GRAY)
    if gray.shape[0] < t.shape[0] or gray.shape[1] < t.shape[1]:
        return None
    res = cv2.matchTemplate(gray, t, cv2.TM_CCOEFF_NORMED)
    _, score, _, loc = cv2.minMaxLoc(res)
    ox, oy = (region[0], region[1]) if region else (0, 0)
    return float(score), (ox + loc[0] + t.shape[1] // 2, oy + loc[1] + t.shape[0] // 2)


def run(cfg, vision):
    """Read-only walk. Returns (report text, list of failed template keys)."""
    from smart import selfheal
    lines, failed = [], []
    version = game_version() or 'unknown'
    lines.append(f'Clash of Clans {version} - checked {time.strftime("%Y-%m-%d %H:%M")}')

    def check(screen, title, keys, region=None):
        lines.append(f'{title}:')
        found = {}
        for key in keys:
            result = _score(vision, screen, key, region)
            if result is None:
                lines.append(f'  - {key}: no picture loaded')
                continue
            score, pos = result
            ok = score >= OK_SCORE
            healed = False
            if not ok and (cfg or {}).get('SMART_SELF_HEAL') and selfheal.can_heal(key):
                healed = selfheal.heal(cfg, vision, key, screen=screen)
                if healed:
                    score, pos = _score(vision, screen, key, region)
                    ok = score >= OK_SCORE
            mark = 'OK ' if ok else 'BROKEN'
            note = ' (repaired by self-healing)' if healed and ok else ''
            if not ok:
                failed.append(key)
                if selfheal.can_heal(key) and not (cfg or {}).get('SMART_SELF_HEAL'):
                    note = ' (self-healing can repair this one)'
            lines.append(f'  {mark} {key}: {score:.2f}{note}')
            if ok:
                found[key] = pos
        return found

    if not vision.is_home_village():
        lines.append('Not on the home village: open your village (no windows) and run the check again.')
        return '\n'.join(lines), ['home']
    home = vision.grab()
    check(home, 'Home village', ['attack_button', 'build_button', 'shop_button_home'])

    tap(*fp.HOME_ATTACK_BUTTON)
    time.sleep(2.0)
    menu = vision.grab()
    found = check(menu, 'Battle menu', ['army_button'], fp.HOME_BUTTONS_LEFT_REGION)

    if 'army_button' in found:
        tap(*found['army_button'])
        time.sleep(2.5)
        army = vision.grab()
        found = check(army, 'Army screen', ['army_dropdown', 'battle_button'])
        if 'army_dropdown' in found:
            tap(*found['army_dropdown'])
            time.sleep(1.5)
            bars = vision.find_army_bars()
            lines.append('Saved armies list:')
            lines.append(f'  {"OK " if bars else "BROKEN"} army_bar: {len(bars)} slot(s) found')
            if not bars:
                failed.append('army_bar')
            tap(1420, 330)                              # outside the list: closes it
            time.sleep(0.8)
        tap(*fp.HOME_ARMY_TAB_CLOSE)
        time.sleep(1.0)
    tap(*fp.SAFE_CLOSE_POINT)
    time.sleep(1.0)
    if not vision.is_home_village():
        tap(*fp.SAFE_CLOSE_POINT)
        time.sleep(1.0)
    lines.append('Nothing broken: attacks should work.' if not failed
                 else f'{len(failed)} picture(s) need attention: {", ".join(failed)}')
    report = '\n'.join(lines)
    out = Path(resolve_writable_path('logs')) / f'canary_report_{version}.txt'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report + '\n', encoding='utf-8')
    for line in lines:
        _log(line)
    return report, failed


def check_version(cfg, vision):
    """On the home village: run the walk once when the game version changed."""
    state = _load_state()
    version = game_version()
    if not version or state.get('version') == version:
        return None
    _log(f'Game version changed ({state.get("version") or "first run"} -> {version}), checking the screens')
    report, failed = run(cfg, vision)
    if failed != ['home']:
        _state_path().write_text(json.dumps({'version': version, 'failed': failed,
                                             'checked': time.strftime('%Y-%m-%d %H:%M')}), encoding='utf-8')
    return report
