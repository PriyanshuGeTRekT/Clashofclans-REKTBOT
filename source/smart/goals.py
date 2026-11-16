# smart/goals.py - plain-language goals.
#
# "Save 300k dark elixir for the Queen", "max my walls, don't touch dark", "only play at night"...
# Claude gets the list of the bot's settings (name, meaning, allowed values, current value) and
# answers with the settings to change. Nothing is applied until you confirm the list in the app.
# Connection settings, account switching and every key / password / token are never offered.
PROTECTED_PREFIXES = ('EMULATOR_', 'SMART_AI_', 'SMART_TELEGRAM_', 'SMART_WEB_', 'SMART_FARM_', 'SMART_GOAL')
PROTECTED_KEYS = {'MULTI_VILLAGE_ENABLED', 'START_PROFILE', 'VILLAGE_COUNT', 'TEMPLATES_DIR',
                  'PROFILE_MATCH_THRESHOLD'}
SCHEMA = {
    'type': 'object', 'additionalProperties': False, 'required': ['summary', 'changes'],
    'properties': {
        'summary': {'type': 'string', 'description': 'One or two plain sentences for the user'},
        'changes': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False, 'required': ['key', 'value', 'why'],
            'properties': {'key': {'type': 'string'},
                           'value': {'type': 'string', 'description': 'New value as text: true/false, a number, or a choice value'},
                           'why': {'type': 'string'}}}},
    },
}
SYSTEM = (
    'You configure a Clash of Clans farming bot. The user states a goal in plain language. Reply '
    'with the smallest set of setting changes that serves the goal. Use only keys from the list, '
    'and only values the setting allows. Settings that spend resources (upgrades, walls, donations) '
    'may be switched on only when the goal clearly asks for that spending. If the goal cannot be '
    'served by these settings, return no changes and say so in the summary.'
)


def _allowed(key):
    return key not in PROTECTED_KEYS and not key.startswith(PROTECTED_PREFIXES)


def catalogue(cfg):
    """Text table of the settings Claude may change."""
    from crb import schema
    lines = []
    for key, meta in schema.BY_KEY.items():
        if not _allowed(key):
            continue
        kind = meta['kind']
        if kind in ('int', 'float'):
            allowed = f"{kind} {meta.get('min')}..{meta.get('max')}"
        elif kind == 'choice':
            allowed = 'one of: ' + ', '.join(str(c[0]) for c in (meta.get('choices') or [])) \
                if meta.get('choices') else 'choice'
        else:
            allowed = kind
        current = cfg.get(key, meta.get('default'))
        lines.append(f'{key} | {schema.title(key)} | {meta.get("help", "")} | {allowed} | now: {current}')
    return '\n'.join(lines)


def _coerce(meta, text):
    kind = meta['kind']
    text = str(text).strip()
    if kind == 'bool':
        if text.lower() not in ('true', 'false', 'on', 'off', 'yes', 'no', '1', '0'):
            raise ValueError('not a yes/no value')
        return text.lower() in ('true', 'on', 'yes', '1')
    if kind in ('int', 'float'):
        value = float(text.replace(',', ''))
        if meta.get('min') is not None:
            value = max(meta['min'], value)
        if meta.get('max') is not None:
            value = min(meta['max'], value)
        return int(value) if kind == 'int' else round(value, 2)
    if kind == 'choice' and meta.get('choices'):
        for choice, _label in meta['choices']:
            if str(choice) == text:
                return choice
        raise ValueError('not one of the choices')
    return text


def plan(cfg, goal):
    """Returns (summary, [(key, new value, why)]) or (error text, None)."""
    from crb import schema
    from smart import ai
    goal = (goal or '').strip()
    if not goal:
        return 'Type a goal first.', None
    answer = ai.ask_json(cfg, f'Goal: {goal}\n\nSettings (key | title | meaning | allowed | current):\n'
                         + catalogue(cfg), SCHEMA, system=SYSTEM, effort='medium')
    if answer is None:
        return 'Claude could not be reached. Check the API key on the Smart page and the Logs page.', None
    changes = []
    for item in answer.get('changes', []):
        key = item.get('key')
        meta = schema.BY_KEY.get(key)
        if not meta or not _allowed(key):
            continue
        try:
            value = _coerce(meta, item.get('value'))
        except (TypeError, ValueError):
            continue
        if value != cfg.get(key, meta.get('default')):
            changes.append((key, value, item.get('why', '')))
    return answer.get('summary', ''), changes
