# smart/ledger.py - the bot audits its own numbers.
#
# The game's arithmetic is a free test: after a 3-star attack, loot won = loot offered + the league
# bonus, and the village's gold / elixir must go up by what was won, minus what searching cost.
# With "Check every attack's numbers" on, each attack is checked against those rules:
#   * a 3-star win whose bonus is missing, or that reads LESS than the base offered
#   * any attack that reads more loot than the base plus the bonus could give
#   * village counters that did not move by what the attack reported (when nothing else spends)
# A failed check saves the result screen to logs/ledger/ and is flagged in logs/ledger.jsonl, so a
# misread counter, a redrawn result screen or a new game rule shows up by itself. Loot that did not
# fit into a full storage is counted as wasted.
import collections
import glob
import json
import os
import re
import time
from pathlib import Path

from utils.runtime_paths import resolve_writable_path

SEARCH_COST = 1700            # gold per base shown (Find a Match / Next) at this Town Hall level
RESOURCES = ('gold', 'elixir', 'dark')
TOLERANCE = {'gold': 1500, 'elixir': 1500, 'dark': 60}
_rt = {'offer': None, 'offers_seen': 0, 'home': None, 'pending': None, 'seeded': False}
_cache = {'entries': None, 'mtime': None}


def _log(msg):
    print(f'[LEDGER] {msg}')


def _path():
    return Path(resolve_writable_path('logs')) / 'ledger.jsonl'


def _write(entry):
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry) + '\n')
    _cache['entries'] = None


def entries():
    path = _path()
    if not path.exists():
        return []
    mtime = path.stat().st_mtime
    if _cache['entries'] is not None and _cache['mtime'] == mtime:
        return _cache['entries']
    out = []
    for line in path.read_text(encoding='utf-8').splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    _cache.update(entries=out, mtime=mtime)
    return out


def attacks():
    return [e for e in entries() if e.get('type') == 'attack']


# ------------------------------------------------------------------ what the bonus is
def bonus():
    """{'gold': n, 'elixir': n, 'dark': n} league bonus learned from clean 3-star wins (0 = unknown)."""
    out = {}
    for i, name in enumerate(RESOURCES):
        step = 1000 if name != 'dark' else 25
        seen = collections.Counter()
        for e in attacks():
            if e.get('stars') == 3 and e.get('offer') and e.get('won'):
                diff = e['won'][i] - e['offer'][i]
                if diff > TOLERANCE[name]:
                    seen[round(diff / step) * step] += 1
        best = seen.most_common(1)
        out[name] = best[0][0] if best and best[0][1] >= 2 else 0
    return out


# ------------------------------------------------------------------ checks
def check_attack(offer, stars, won, known_bonus):
    """Flags for one attack: [] when the numbers are consistent."""
    flags = []
    if not offer:
        return flags
    for i, name in enumerate(RESOURCES):
        tol, b = TOLERANCE[name], known_bonus.get(name, 0)
        diff = won[i] - offer[i]
        if stars == 3:
            if diff < -tol:
                flags.append(f'{name}: won {won[i]:,} but the base offered {offer[i]:,} (3 stars take it all)')
            elif b and abs(diff) <= tol:
                flags.append(f'{name}: bonus of {b:,} is missing')
            elif b and abs(diff - b) > max(tol, b * 0.02):
                flags.append(f'{name}: bonus reads {diff:,}, expected {b:,}')
        elif b and diff > b + tol:
            flags.append(f'{name}: won {won[i]:,}, more than base {offer[i]:,} + bonus {b:,}')
    return flags


def _spending_on(cfg):
    """True when something besides attacking changes the village counters."""
    keys = ('UPGRADE_WALLS', 'AUTO_UPGRADE_BUILDINGS', 'AUTO_UPGRADE_LAB', 'AUTO_UPGRADE_PETS',
            'AUTO_UPGRADE_EQUIPMENT', 'COLLECT_RESOURCES', 'DONATE_ENABLED', 'CLAIM_EVENT_REWARDS')
    return any((cfg or {}).get(k) for k in keys)


# ------------------------------------------------------------------ hooks
def ensure_seeded():
    if not _rt['seeded']:
        _rt['seeded'] = True
        seed_from_logs()


def note_offer(gold, elixir, dark, vision=None):
    ensure_seeded()
    offer = [int(gold), int(elixir), int(dark)]
    if offer != _rt['offer']:
        _rt['offer'] = offer
        _rt['offers_seen'] += 1
        # keep the picture of the "Available Loot" numbers this was read from (the bot's last frame)
        frame = getattr(vision, '_error_popup_latest_logic_frame', None)
        _rt['offer_crop'] = frame[20:260, 0:360].copy() if frame is not None else None


def note_home(cfg, vision, full=None):
    """On the home village: compare the counters with what the last attack reported."""
    gold, elixir = vision.read_loot()
    now_home = {'gold': int(gold), 'elixir': int(elixir)}
    pending, before = _rt['pending'], _rt['home']
    if pending and before and now_home['gold'] and before['gold']:
        full = full or {}
        expected = {'gold': pending['won'][0] - SEARCH_COST * pending['searches'], 'elixir': pending['won'][1]}
        record = {'type': 'home', 'at': time.strftime('%Y-%m-%d %H:%M:%S'), 'before': before,
                  'after': now_home, 'expected': expected, 'wasted': {}, 'flags': []}
        for name in ('gold', 'elixir'):
            actual = now_home[name] - before[name]
            short = expected[name] - actual
            if full.get(name) and short > TOLERANCE[name]:
                record['wasted'][name] = short                 # storage full: the rest was lost
            elif not _spending_on(cfg) and abs(short) > max(TOLERANCE[name] * 2, abs(expected[name]) * 0.02):
                record['flags'].append(f'{name}: village changed by {actual:,}, the attack reported {expected[name]:,}')
        if record['wasted']:
            _log('Lost to full storage: ' + ', '.join(f'{v:,} {k}' for k, v in record['wasted'].items()))
        for flag in record['flags']:
            _log('CHECK FAILED - ' + flag)
        _write(record)
    _rt.update(home=now_home, pending=None, offers_seen=0, offer=None)


def note_battle_end(cfg, vision, strategy, stars, gold, elixir, dark, quiet=False):
    """Record one attack. quiet=True keeps the record (the economy needs it) without the checks' output."""
    ensure_seeded()
    offer = _rt['offer']
    won = [int(gold), int(elixir), int(dark)]
    flags = check_attack(offer, int(stars), won, bonus())
    entry = {'type': 'attack', 'at': time.strftime('%Y-%m-%d %H:%M:%S'), 'strategy': strategy,
             'stars': int(stars), 'offer': offer, 'won': won, 'searches': max(1, _rt['offers_seen']),
             'th': getattr(vision, 'last_th_name', None), 'flags': flags}
    if flags and not quiet:
        try:
            import cv2
            folder = Path(resolve_writable_path('logs')) / 'ledger'
            folder.mkdir(parents=True, exist_ok=True)
            shot = folder / f"{time.strftime('%Y%m%d-%H%M%S')}_result.png"
            cv2.imwrite(str(shot), vision.grab())
            entry['screen'] = shot.name
            if _rt.get('offer_crop') is not None:        # what the base offered, as the bot saw it
                cv2.imwrite(str(shot).replace('_result.png', '_offer.png'), _rt['offer_crop'])
        except Exception:
            pass
        for flag in flags:
            _log('CHECK FAILED - ' + flag + (f" (screen saved: logs/ledger/{entry.get('screen')})"
                                             if entry.get('screen') else ''))
    elif not quiet:
        _log('Numbers add up')
    _write(entry)
    _rt['pending'] = {'won': won, 'searches': entry['searches']}
    return entry


# ------------------------------------------------------------------ history and report
def seed_from_logs():
    """First use: import the attacks already in the session logs so the bonus is known at once."""
    if _path().exists():
        return 0
    count = 0
    for f in sorted(glob.glob(str(Path(resolve_writable_path('logs')) / 'log-*.txt'))):
        offer, seen = None, 0
        try:
            lines = open(f, encoding='utf-8', errors='replace').read().splitlines()
        except OSError:
            continue
        for line in lines:
            m = re.match(r'\[SEARCH\]G:(\d+) E:(\d+) D:(\d+)', line)
            if m:
                new = [int(x) for x in m.groups()]
                if new != offer:
                    offer, seen = new, seen + 1
                continue
            m = re.search(r'Result: (\d) star\(s\), loot (\d+)/(\d+)/(\d+) \((\w*)', line)
            if m and offer:
                _write({'type': 'attack', 'at': os.path.basename(f)[4:-4], 'strategy': m.group(5) or None,
                        'stars': int(m.group(1)), 'offer': offer, 'won': [int(m.group(i)) for i in (2, 3, 4)],
                        'searches': max(1, seen), 'th': None, 'flags': [], 'imported': True})
                count, seen = count + 1, 0
    if count:                                   # second pass: flag them now that the bonus is known
        known, rows = bonus(), entries()
        for e in rows:
            e['flags'] = check_attack(e['offer'], e['stars'], e['won'], known)
        _path().write_text(''.join(json.dumps(e) + '\n' for e in rows), encoding='utf-8')
        _cache['entries'] = None
        _log(f'Imported {count} attack(s) from the session logs')
    return count


def summary_text():
    ensure_seeded()
    rows = attacks()
    if not rows:
        return 'Ledger: no attacks checked yet.'
    flagged = [e for e in rows if e.get('flags')]
    wasted = collections.Counter()
    for e in entries():
        if e.get('type') == 'home':
            wasted.update(e.get('wasted') or {})
    b = bonus()
    lines = [f'Ledger: {len(rows)} attack(s) checked, {len(flagged)} with numbers that do not add up.']
    if any(b.values()):
        lines.append(f"League bonus per win: {b['gold']:,} gold, {b['elixir']:,} elixir, {b['dark']:,} dark.")
    if wasted:
        lines.append('Lost to full storages: ' + ', '.join(f'{v:,} {k}' for k, v in wasted.items()) + '.')
    kinds = collections.Counter(re.sub(r'[\d,]+', 'N', flag) for e in flagged for flag in e['flags'])
    for kind, n in kinds.most_common(4):
        lines.append(f'  {n}x {kind}')
    return '\n'.join(lines)
