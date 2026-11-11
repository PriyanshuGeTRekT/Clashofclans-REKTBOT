# scheduler.py - active hours, humanised breaks and end conditions (new module, Pro feature).
#
# Idea from MyBot PHMOD (IsSearchAttackEnabled / AddIdleTime / the PHMOD scheduler), re-implemented:
#   * active hours: the bot only plays between SCHED_START_HOUR and SCHED_END_HOUR (wraps midnight).
#   * breaks: after a random 40-90 min (configurable) of play, close CoC for a random 5-15 min.
#   * end conditions: stop the bot after N attacks, N hours, or once the gold / elixir / dark gained
#     in this session reach the targets.
# Outside active hours and during breaks CoC is closed (like a player putting the phone away);
# farming then returns 'RECOVERY', which relaunches the game and confirms the home village.
import random
import time
from datetime import datetime, timedelta

import adb
from control import BotControl

COC_PACKAGE = 'com.supercell.clashofclans'

_state = {'next_break': None, 'session_start': time.time()}


def _log(msg):
    print(f'[SCHEDULE] {msg}')


def _range(cfg, low_key, high_key, low_default, high_default):
    low = int(cfg.get(low_key, low_default) or low_default)
    high = int(cfg.get(high_key, high_default) or high_default)
    return min(low, high), max(low, high)


def in_active_hours(cfg, now=None):
    if not cfg.get('SCHED_ACTIVE_HOURS_ENABLED', False):
        return True
    now = now or datetime.now()
    start = int(cfg.get('SCHED_START_HOUR', 0)) % 24
    end = int(cfg.get('SCHED_END_HOUR', 24)) % 24
    if start == end:
        return True
    hour = now.hour
    return start <= hour < end if start < end else (hour >= start or hour < end)


def _seconds_until_active(cfg, now=None):
    now = now or datetime.now()
    start = int(cfg.get('SCHED_START_HOUR', 0)) % 24
    target = now.replace(hour=start, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def end_condition(stats, cfg):
    """Reason string when an end condition is met, else None."""
    if not cfg.get('END_CONDITIONS_ENABLED', False):
        return None
    attacks = int(cfg.get('END_AFTER_ATTACKS', 0) or 0)
    if attacks and getattr(stats, 'total_attacks', 0) >= attacks:
        return f'{attacks} attacks done'
    hours = float(cfg.get('END_AFTER_HOURS', 0) or 0)
    if hours and time.time() - _state['session_start'] >= hours * 3600:
        return f'{hours:g} hours played'
    for key, attr, label in (('END_AFTER_GOLD', 'gold_gained', 'gold'),
                             ('END_AFTER_ELIXIR', 'elixir_gained', 'elixir'),
                             ('END_AFTER_DARK', 'dark_gained', 'dark elixir')):
        target = int(cfg.get(key, 0) or 0)
        if target and getattr(stats, attr, 0) >= target:
            return f'{target:,} {label} gained'
    return None


def _schedule_next_break(cfg):
    low, high = _range(cfg, 'SCHED_BREAK_EVERY_MIN', 'SCHED_BREAK_EVERY_MAX', 40, 90)
    _state['next_break'] = time.time() + 60 * random.uniform(low, high)


def _idle(seconds, reason, pause_if_needed=None):
    """Close CoC and wait; returns False when the bot was stopped meanwhile."""
    resume = datetime.now() + timedelta(seconds=seconds)
    _log(f'{reason}: closing Clash of Clans until {resume:%H:%M}')
    try:
        adb.force_stop(COC_PACKAGE)
    except Exception as e:
        _log(f'Could not close CoC ({e.__class__.__name__}: {e})')
    deadline = time.time() + seconds
    while time.time() < deadline:
        if not BotControl.running:
            return False
        if callable(pause_if_needed):
            pause_if_needed()
        time.sleep(min(5.0, max(0.0, deadline - time.time())))
    _log('Resuming')
    return True


def gate(stats, cfg, pause_if_needed=None):
    """Call on the home village before starting tasks.

    Returns None to carry on, 'END_CONDITION' to stop the bot, or 'RECOVERY' after an idle period
    (CoC was closed and has to be relaunched)."""
    reason = end_condition(stats, cfg)
    if reason:
        _log(f'End condition reached: {reason}')
        return 'END_CONDITION'
    if not in_active_hours(cfg):
        wait = _seconds_until_active(cfg)
        return 'RECOVERY' if _idle(wait, 'Outside active hours', pause_if_needed) else 'END_CONDITION'
    if cfg.get('SCHED_BREAKS_ENABLED', False):
        if _state['next_break'] is None:
            _schedule_next_break(cfg)
        elif time.time() >= _state['next_break']:
            low, high = _range(cfg, 'SCHED_BREAK_LENGTH_MIN', 'SCHED_BREAK_LENGTH_MAX', 5, 15)
            length = 60 * random.uniform(low, high)
            _schedule_next_break(cfg)
            _state['next_break'] += length
            return 'RECOVERY' if _idle(length, 'Taking a break', pause_if_needed) else 'END_CONDITION'
    return None
