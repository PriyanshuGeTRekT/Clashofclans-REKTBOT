# smart/economy.py - pick bases by loot per HOUR, not loot per base.
#
# Pressing Next costs a few seconds and a little gold; an attack costs minutes. So the question for
# every base is not "is this a lot of loot?" but "would I earn more per hour by taking it, or by
# searching on for a richer one?". That has an exact answer once four things are known, and the bot
# measures all four itself:
#   * what bases offer here      - every base it is shown is remembered (logs/economy.json)
#   * how long an attack takes   - from accepting a base to seeing the next one
#   * how long a Next takes      - between two bases when skipping
#   * what a win is worth on top - the league bonus, learned by the ledger
# For every possible cut-off "attack only bases worth at least X" the loot per hour is
#     (average loot of the bases above X + bonus - gold spent on Nexts) / (attack time + Next time)
# and the bot uses the X with the highest result (the break-even point). A resource whose storage is
# full counts as nothing. Until MIN_HISTORY bases have been seen it only watches and learns.
import glob
import json
import re
import time
from pathlib import Path

from utils.runtime_paths import resolve_writable_path

MIN_HISTORY = 20              # bases seen before the rule is trusted
MAX_HISTORY = 400             # remember this many bases (older ones drop out as the league changes)
MIN_ABOVE = 3                 # a cut-off needs at least this many remembered bases above it ...
# ... and at least sqrt(bases remembered): with few bases the richest ones are luck, and a cut-off
# set just above everything normal makes the bot search for a base that rarely comes.
DEFAULT_CYCLE, DEFAULT_NEXT = 200.0, 6.0
_state = {'loaded': False, 'offers': [], 'cycle': DEFAULT_CYCLE, 'next': DEFAULT_NEXT}
_rt = {'last_offer': None, 'last_at': 0.0, 'last_verdict': None, 'accepted_at': None, 'candidate_at': None,
       'skips': 0, 'announced': None}


def _log(msg):
    print(f'[ECONOMY] {msg}')


def _path():
    return Path(resolve_writable_path('logs')) / 'economy.json'


def _load():
    if _state['loaded']:
        return
    _state['loaded'] = True
    try:
        data = json.loads(_path().read_text(encoding='utf-8'))
        _state.update(offers=[list(o) for o in data.get('offers', [])][-MAX_HISTORY:],
                      cycle=float(data.get('cycle', DEFAULT_CYCLE)), next=float(data.get('next', DEFAULT_NEXT)))
    except Exception:
        _state['offers'] = seed_from_logs()


def _save():
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'offers': _state['offers'][-MAX_HISTORY:], 'cycle': round(_state['cycle'], 1),
                                'next': round(_state['next'], 1)}), encoding='utf-8')


def seed_from_logs():
    """First use: the bases already printed in the session logs."""
    offers = []
    for f in sorted(glob.glob(str(Path(resolve_writable_path('logs')) / 'log-*.txt'))):
        last = None
        try:
            text = open(f, encoding='utf-8', errors='replace').read()
        except OSError:
            continue
        for m in re.finditer(r'\[SEARCH\]G:(\d+) E:(\d+) D:(\d+)', text):
            offer = [int(x) for x in m.groups()]
            if offer != last and any(offer):
                offers.append(offer)
            last = offer
    return offers[-MAX_HISTORY:]


# ------------------------------------------------------------------ the rule
def worth(offer, full, dark_weight):
    """Value of a base in gold-equivalents; a full resource is worth nothing."""
    full = full or {}
    return ((0 if full.get('gold') else offer[0]) + (0 if full.get('elixir') else offer[1])
            + (0 if full.get('dark') else offer[2] * dark_weight))


def win_stats():
    """(share of attacks that earn the bonus, share of the offered loot that is taken)."""
    from smart import ledger
    rows = [e for e in ledger.attacks() if not e.get('flags')][-60:]
    if len(rows) < 5:
        return 0.9, 0.85
    wins = sum(1 for e in rows if e['stars'] >= 1) / len(rows)
    three = sum(1 for e in rows if e['stars'] == 3) / len(rows)
    return wins, three + (1 - three) * 0.5


def best_cutoff(values, bonus_value, cycle, next_seconds, next_cost, max_skips, capture=0.85):
    """(cut-off, loot per second with it, loot per second attacking everything, expected Nexts)."""
    values = sorted(values)
    n = len(values)

    def rate(start):                               # attack only values[start:]
        above = values[start:]
        skips = n / len(above) - 1
        take = capture * sum(above) / len(above) + bonus_value - next_cost * skips
        return take / (cycle + next_seconds * skips), skips

    base_rate, _ = rate(0)
    best = (values[0], base_rate, 0.0)
    for start in range(1, n):
        if values[start] == values[start - 1]:
            continue
        above = n - start
        if above < max(MIN_ABOVE, n ** 0.5) or n / above - 1 > max_skips:
            break
        r, skips = rate(start)
        if r > best[1]:
            best = (values[start], r, skips)
    return best[0], best[1], base_rate, best[2]


def plan(cfg, full):
    """Current rule as a dict, or None while still learning."""
    from smart import ledger
    _load()
    ledger.ensure_seeded()
    offers = _state['offers']
    if len(offers) < MIN_HISTORY:
        return None
    weight = int(cfg.get('SMART_ECON_DARK_WEIGHT', 60) or 60)
    b = ledger.bonus()
    wins, capture = win_stats()
    bonus_value = wins * worth([b['gold'], b['elixir'], b['dark']], full, weight)
    next_cost = 0 if (full or {}).get('gold') else ledger.SEARCH_COST
    cutoff, rate, base_rate, skips = best_cutoff(
        [worth(o, full, weight) for o in offers], bonus_value, _state['cycle'], _state['next'], next_cost,
        int(cfg.get('SMART_ECON_MAX_SKIPS', 15) or 15), capture)
    return {'cutoff': cutoff, 'per_hour': rate * 3600, 'per_hour_all': base_rate * 3600, 'skips': skips,
            'bases': len(offers), 'cycle': _state['cycle'], 'next': _state['next'], 'bonus_value': bonus_value,
            'weight': weight}


def verdict(cfg, vision, gold, elixir, dark, full=None):
    """'skip' when searching on pays more per hour than attacking this base, else None."""
    _load()
    now = time.time()
    offer = [int(gold), int(elixir), int(dark)]
    if offer == _rt['last_offer']:
        return _rt['last_verdict']                 # same base read again
    # ---- measure
    if _rt['last_verdict'] == 'skip' and _rt['last_at']:
        sample = now - _rt['last_at']
        if 1.0 <= sample <= 40.0:
            _state['next'] += 0.2 * (sample - _state['next'])
    if _rt['accepted_at']:
        sample = now - _rt['accepted_at']
        if 45.0 <= sample <= 900.0:
            _state['cycle'] += 0.2 * (sample - _state['cycle'])
        _rt['accepted_at'] = None
    if any(offer):
        _state['offers'].append(offer)
        del _state['offers'][:-MAX_HISTORY]
    _save()
    # ---- decide
    result = None
    rule = plan(cfg, full)
    if rule is None:
        if _rt['announced'] != 'learning':
            _rt['announced'] = 'learning'
            _log(f"Learning what bases offer here ({len(_state['offers'])}/{MIN_HISTORY} seen), no skipping yet")
    elif full and all(full.get(k) for k in ('gold', 'elixir', 'dark')):
        if _rt['announced'] != 'full':
            _rt['announced'] = 'full'
            _log('Every storage is full: no base is worth anything right now. Spend something, or switch '
                 'on "Rest when every storage is full"')
    else:
        _rt['announced'] = None
        value = worth(offer, full, rule['weight'])
        max_skips = int(cfg.get('SMART_ECON_MAX_SKIPS', 15) or 15)
        if value < rule['cutoff'] and _rt['skips'] < max_skips:
            _rt['skips'] += 1
            result = 'skip'
            _log(f"Base worth {value / 1000:,.0f}k, break-even {rule['cutoff'] / 1000:,.0f}k -> Next "
                 f"({_rt['skips']}/{max_skips})")
        elif value < rule['cutoff']:
            _log(f"Base worth {value / 1000:,.0f}k, break-even {rule['cutoff'] / 1000:,.0f}k, but "
                 f"{max_skips} bases were skipped in a row -> attack")
            _rt['skips'] = 0
        else:
            _log(f"Base worth {value / 1000:,.0f}k, break-even {rule['cutoff'] / 1000:,.0f}k -> attack "
                 f"(about {rule['per_hour'] / 1e6:.0f}M an hour this way, {rule['per_hour_all'] / 1e6:.0f}M "
                 f"attacking everything)")
            _rt['skips'] = 0
    if result is None:
        _rt['candidate_at'] = now
    _rt.update(last_offer=offer, last_at=now, last_verdict=result)
    return result


def note_battle_end():
    """An attack really happened: time the cycle from the moment its base was accepted."""
    _rt['accepted_at'] = _rt['candidate_at']
    _rt.update(last_offer=None, last_verdict=None, skips=0)


def report(cfg, full=None):
    rule = plan(cfg or {}, full)
    if rule is None:
        return f"Economy: still learning ({len(_state['offers'])}/{MIN_HISTORY} bases seen)."
    return (f"Economy: {rule['bases']} bases remembered. Break-even is a base worth {rule['cutoff']:,.0f} "
            f"(about {rule['skips']:.1f} Next per attack). Expected {rule['per_hour'] / 1e6:.0f}M an hour, "
            f"against {rule['per_hour_all'] / 1e6:.0f}M attacking everything. Measured: {rule['cycle']:.0f} s per "
            f"attack, {rule['next']:.1f} s per Next.")


# ------------------------------------------------------------------ rest when nothing fits
def idle_gate(cfg, vision, full, pause_if_needed=None):
    """Close the game for a while when every storage is full. Returns a farming gate or None."""
    if not (cfg or {}).get('SMART_ECON_IDLE_WHEN_FULL') or not full:
        return None
    if not all(full.get(k) for k in ('gold', 'elixir', 'dark')):
        return None
    if cfg.get('UPGRADE_WALLS') and (vision.read_builders_free() or 0) > 0:
        return None                                # walls will take the overflow in a moment
    import scheduler
    minutes = int(cfg.get('SMART_ECON_IDLE_MINUTES', 30) or 30)
    ok = scheduler._idle(minutes * 60, 'Every storage is full, nothing more can be kept', pause_if_needed)
    return 'RECOVERY' if ok else 'END_CONDITION'
