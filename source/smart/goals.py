# smart/goals.py - goals in plain words, turned into settings by keyword rules (no AI).
#
# "save 5k dark, stop after 3 hours, only play at night, don't upgrade walls" is split into parts;
# each part is matched against the rules below and becomes one or more setting changes. Nothing is
# applied until you confirm the list in the app, and parts no rule understands are listed back.
# Connection settings, account switching, tokens and passwords are never changed from here.
import re

PROTECTED_PREFIXES = ('EMULATOR_', 'SMART_TELEGRAM_', 'SMART_DISCORD_', 'SMART_WEB_', 'SMART_FARM_', 'SMART_GOAL')
PROTECTED_KEYS = {'MULTI_VILLAGE_ENABLED', 'START_PROFILE', 'VILLAGE_COUNT', 'TEMPLATES_DIR',
                  'PROFILE_MATCH_THRESHOLD'}
NEGATIONS = ("don't", 'dont', 'do not', 'no ', 'not ', 'without', 'stop ', 'never ', 'disable', 'turn off',
             'switch off')
NUMBER = r'(\d+(?:[.,]\d+)?)\s*(k|m|thousand|million)?'

# (pattern, setting to switch on/off) - checked on every part of the goal
SWITCHES = [
    (r'\bwalls?\b', 'UPGRADE_WALLS'),
    (r'\b(upgrade|build)\w*\b(?!.*\bwalls?\b)(?!.*\b(lab|research|pets?|equipment)\b)', 'AUTO_UPGRADE_BUILDINGS'),
    (r'\b(lab|laboratory|research)\b', 'AUTO_UPGRADE_LAB'),
    (r'\bpets?\b', 'AUTO_UPGRADE_PETS'),
    (r'\bequipment\b', 'AUTO_UPGRADE_EQUIPMENT'),
    (r'\bcollect', 'COLLECT_RESOURCES'),
    (r'\bobstacles?\b', 'REMOVE_OBSTACLES'),
    (r'\b(event )?rewards?\b', 'CLAIM_EVENT_REWARDS'),
    (r'\bdonat', 'DONATE_ENABLED'),
    (r'\brequest', 'REQUEST_DONATIONS'),
    (r'\bclan games\b', 'CLAN_GAMES'),
    (r'\b(clan )?capital\b', 'CAPITAL_RAIDS_ENABLED'),
    (r'\bbuilder base\b', 'BB_ATTACKS_ENABLED'),
    (r'\b(loot ?max\w*|50 ?%|fast attacks?|quick attacks?)', 'LOOTMAX_ENABLED'),
    (r'\bxp\b', 'XP_FARMING'),
    (r'\bbreaks?\b', 'SCHED_BREAKS_ENABLED'),
    (r'\b(full|wast\w+|overflow)\b', 'SMART_SPEND_AWARE'),
    (r'\b(idle|free builders?)\b', 'SMART_NEVER_IDLE'),
    (r'\bwar\b.*\bhero|\bhero\w*\b.*\bwar\b', 'SMART_WAR_AWARE_HEROES'),
    (r'\breplay\b', 'SMART_REPLAY'),
]


def _allowed(key):
    return key not in PROTECTED_KEYS and not key.startswith(PROTECTED_PREFIXES)


def _number(match):
    value = float(match.group(1).replace(',', '.'))
    unit = (match.group(2) or '').lower()
    if unit in ('k', 'thousand'):
        value *= 1_000
    elif unit in ('m', 'million'):
        value *= 1_000_000
    return int(value)


def _negated(part):
    return any(n in part + ' ' for n in NEGATIONS)


def _hours(part):
    """(start, end) play hours named in this part, or None."""
    if re.search(r'\b(at night|nights?|overnight|while i sleep)\b', part):
        return 22, 7
    if re.search(r'\b(day ?time|during the day)\b', part):
        return 8, 22
    m = re.search(r'\b(?:from|between)?\s*(\d{1,2})\s*(am|pm)?\s*(?:to|and|-|until|till)\s*(\d{1,2})\s*(am|pm)?', part)
    if m and re.search(r'\b(play|hours?|only|between|from|run|farm)\b', part):
        def hour(text, half):
            value = int(text) % 24
            if half == 'pm' and value < 12:
                value += 12
            if half == 'am' and value == 12:
                value = 0
            return value
        return hour(m.group(1), m.group(2)), hour(m.group(3), m.group(4))
    return None


def parse(goal):
    """Returns ([(key, raw value, why)], [parts that were not understood])."""
    changes, unknown = [], []
    text = goal.lower().replace('’', "'")
    for part in re.split(r'[,;\n]|(?<!\d)\.|\.(?!\d)|\bbut\b|\band then\b|\band\b(?! \d)', text):
        part = part.strip()
        if not part:
            continue
        found = []
        # ---- when to stop
        m = re.search(r'(?:stop|quit|end|finish)\w*\s+(?:after|in)\s+' + NUMBER + r'\s*(hours?|hrs?|h\b|attacks?|raids?)', part) \
            or re.search(r'\bfor\s+' + NUMBER + r'\s*(hours?|hrs?|h\b|attacks?|raids?)', part)
        if m:
            key = 'END_AFTER_ATTACKS' if m.group(3).startswith(('attack', 'raid')) else 'END_AFTER_HOURS'
            found += [('END_CONDITIONS_ENABLED', True, 'you gave a stopping point'),
                      (key, int(float(m.group(1).replace(',', '.'))), f'"{part}"')]
        # ---- loot wanted from a base
        if not found:
            for word, key in (('dark', 'ATTACK_MIN_DARK'), ('gold', 'ATTACK_MIN_GOLD'), ('elixir', 'ATTACK_MIN_ELIXIR')):
                if word == 'elixir' and 'dark' in part:
                    continue
                m = re.search(NUMBER + r'\s*(?:of\s+)?' + word, part) or \
                    re.search(word + r'\D{0,25}?' + NUMBER, part)
                if m:
                    found.append((key, _number(m), f'"{part}"'))
                elif word == 'dark' and re.search(r'\b(save|need|want|farm|more|get)\b.*\bdark\b', part):
                    found.append((key, 3000, 'bases with dark elixir are preferred (3,000 or more)'))
        # ---- play hours
        if not found:
            hours = _hours(part)
            if hours:
                found += [('SCHED_ACTIVE_HOURS_ENABLED', True, f'"{part}"'),
                          ('SCHED_START_HOUR', hours[0], 'start hour'), ('SCHED_END_HOUR', hours[1], 'end hour')]
        # ---- switches (also when the same part named loot or hours: "no walls and 1.5m gold")
        for pattern, key in SWITCHES:
            if re.search(pattern, part):
                found.append((key, not _negated(part), f'"{part}"'))
        if found:
            changes += found
        else:
            unknown.append(part)
    return changes, unknown


def _coerce(meta, value):
    kind = meta['kind']
    if kind == 'bool':
        return bool(value)
    if kind in ('int', 'float'):
        value = float(value)
        if meta.get('min') is not None:
            value = max(meta['min'], value)
        if meta.get('max') is not None:
            value = min(meta['max'], value)
        return int(value) if kind == 'int' else round(value, 2)
    return value


def plan(cfg, goal):
    """Returns (summary, [(key, new value, why)]) or (message, None) when nothing can be done."""
    from crb import schema
    goal = (goal or '').strip()
    if not goal:
        return 'Type a goal first.', None
    raw, unknown = parse(goal)
    changes, seen = [], set()
    for key, value, why in raw:
        meta = schema.BY_KEY.get(key)
        if not meta or not _allowed(key) or key in seen:
            continue
        seen.add(key)
        value = _coerce(meta, value)
        if value != cfg.get(key, meta.get('default')):
            changes.append((key, value, why))
    summary = f'Understood {len(seen)} setting(s) from your goal.'
    if unknown:
        summary += ' Not understood: ' + '; '.join(f'"{u}"' for u in unknown) + '.'
    if not seen:
        return summary + ' Try phrases like "stop after 3 hours", "at least 5k dark", ' \
                         '"only play at night", "upgrade walls", "don\'t donate".', None
    return summary, changes
