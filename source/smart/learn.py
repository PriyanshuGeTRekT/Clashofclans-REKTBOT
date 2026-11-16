# smart/learn.py - learn from the bot's own attacks.
#
# Every attack is appended to logs/attacks.jsonl (always, it is one line per attack). With
# "Skip bases this army fails on" switched on, the bot looks at the enemy Town Hall before attacking
# and presses Next when the chosen strategy has averaged too few stars against that Town Hall level.
import json
import time
from pathlib import Path

from utils.runtime_paths import resolve_writable_path

_offer = {}
_skips = {'count': 0}
MAX_SKIPS_IN_A_ROW = 15


def _path():
    return Path(resolve_writable_path('logs')) / 'attacks.jsonl'


def remember_offer(vision, gold, elixir, dark):
    _offer.update(gold=gold, elixir=elixir, dark=dark, at=time.time())


def record(cfg, vision, strategy, stars, gold, elixir, dark, write=True):
    entry = {'at': time.strftime('%Y-%m-%d %H:%M:%S'), 'strategy': strategy, 'stars': int(stars),
             'gold': int(gold), 'elixir': int(elixir), 'dark': int(dark),
             'offer_gold': _offer.get('gold'), 'offer_elixir': _offer.get('elixir'),
             'offer_dark': _offer.get('dark'), 'th': getattr(vision, 'last_th_name', None)}
    if write:
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry) + '\n')
    _skips['count'] = 0
    return entry


def history():
    path = _path()
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding='utf-8').splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def table(entries=None):
    """{(strategy, th): {'n', 'stars', 'gold', 'elixir', 'dark'}} with averages."""
    groups = {}
    for e in (history() if entries is None else entries):
        groups.setdefault((e.get('strategy'), e.get('th')), []).append(e)
    out = {}
    for key, rows in groups.items():
        n = len(rows)
        out[key] = {'n': n, **{k: sum(int(r.get(k) or 0) for r in rows) / n
                               for k in ('stars', 'gold', 'elixir', 'dark')}}
    return out


def summary_text(limit=8):
    rows = sorted(table().items(), key=lambda kv: -kv[1]['n'])[:limit]
    if not rows:
        return 'No attacks logged yet.'
    return '\n'.join(f"{s or '?'} vs {th or 'unknown TH'}: {v['n']} attacks, {v['stars']:.1f} stars, "
                     f"{v['gold'] / 1000:.0f}k gold, {v['elixir'] / 1000:.0f}k elixir"
                     for (s, th), v in rows)


def verdict(cfg, vision, strategy):
    """'skip' when this strategy has a poor record against the Town Hall on screen."""
    if _skips['count'] >= MAX_SKIPS_IN_A_ROW:
        return None                               # never search forever
    if not vision.find_townhall():
        return None
    th = getattr(vision, 'last_th_name', None)
    stats = table().get((strategy, th))
    need = int(cfg.get('SMART_LEARN_MIN_SAMPLES', 5) or 5)
    if not stats or stats['n'] < need:
        return None
    floor = float(cfg.get('SMART_LEARN_MIN_STARS', 1) or 1)
    if stats['stars'] < floor:
        _skips['count'] += 1
        print(f"[SMART] Skipping {th}: {strategy} averages {stats['stars']:.1f} stars there "
              f"over {stats['n']} attacks (wanted {floor:g})")
        return 'skip'
    return None
