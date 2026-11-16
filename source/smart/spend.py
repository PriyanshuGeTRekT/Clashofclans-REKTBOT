# smart/spend.py - spend-aware targeting.
#
# Loot that does not fit in a full storage is lost. On the home village the bot reads how full the
# gold / elixir / dark bars are; a full resource then stops counting when a base is judged:
#   * one of gold / elixir full  -> the base must offer enough of the OTHER one (or enough dark)
#   * gold and elixir both full  -> only dark elixir counts
import time

_state = {'full': {}, 'read_at': 0.0, 'skips': 0}
MAX_SKIPS_IN_A_ROW = 25
FULL_RATIO = 0.985


def read_home(vision):
    """Call on the home village: remember which storages are full."""
    ratios = vision.get_loot_bar_fill_ratios()
    full = {k: v >= FULL_RATIO for k, v in ratios.items()}
    if full != _state['full']:
        names = [k for k, v in full.items() if v]
        print('[SMART] Storages full: ' + (', '.join(names) if names else 'none'))
    _state.update(full=full, read_at=time.time())
    return full


def full():
    return dict(_state['full'])


def verdict(cfg, vision, gold, elixir, dark):
    f = _state['full']
    gold_full, elixir_full, dark_full = f.get('gold'), f.get('elixir'), f.get('dark')
    if not (gold_full or elixir_full):
        _state['skips'] = 0
        return None
    if _state['skips'] >= MAX_SKIPS_IN_A_ROW:
        _state['skips'] = 0
        print('[SMART] Many bases skipped in a row, attacking this one anyway')
        return None
    want_other = int(cfg.get('SMART_FULL_MIN_OTHER', 400000) or 0)
    want_dark = int(cfg.get('SMART_FULL_MIN_DARK', 4000) or 0)
    dark_ok = (not dark_full) and dark >= want_dark
    if gold_full and elixir_full:
        ok, why = dark_ok, f'gold and elixir are full, dark {dark} < {want_dark}'
    elif gold_full:
        ok, why = elixir >= want_other or dark_ok, f'gold is full, elixir {elixir} < {want_other}'
    else:
        ok, why = gold >= want_other or dark_ok, f'elixir is full, gold {gold} < {want_other}'
    if ok:
        _state['skips'] = 0
        return None
    _state['skips'] += 1
    print(f'[SMART] Skipping base: {why}')
    return 'skip'
