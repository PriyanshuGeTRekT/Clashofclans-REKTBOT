# crb/schema.py - how the settings catalogue is laid out in the Clash Rekt Bot UI.
#
# Pages -> cards -> setting keys. Titles here are short, plain-language versions; the catalogue's
# help text is shown under each title. Keys, kinds, ranges and scopes come from settings_catalog.
from crb.settings_catalog import SETTINGS, STRATEGY_HELP, STRATEGY_CHOICES

BY_KEY = {s['key']: s for s in SETTINGS}

# Friendlier titles (the catalogue keeps the old UI wording).
TITLES = {
    'LOOTMAX_ENABLED': '50% Loot Maxxing',
    'SELECTED_ATTACK_STRATEGY': 'Attack strategy',
    'CSV_ATTACK_SCRIPT': 'Attack script',
    'CSV_USE_REDLINE': 'Drop troops on the detected red line',
    'SELECTED_ARMY_SLOT': 'Army to use',
    'ATTACK_MIN_GOLD': 'Minimum gold',
    'ATTACK_MIN_ELIXIR': 'Minimum elixir',
    'ATTACK_MIN_DARK': 'Minimum dark elixir',
    'XP_FARMING': 'XP farming: attack every base',
    'HERO_TAP_DELAY_ENABLED': 'Custom hero ability delay',
    'HERO_TAP_DELAY_SECONDS': 'Hero ability delay (seconds)',
    'AIR_TROOP_WIDTH_ENABLED': 'Custom air troop spread',
    'AIR_TROOP_WIDTH': 'Air troop spread (pixels)',
    'END_BATTLE_ENABLED': 'End battles early',
    'END_BATTLE_STARS': 'End at this many stars',
    'END_BATTLE_DAMAGE': 'End at this damage %',
    'END_BATTLE_NO_CHANGE_SECONDS': 'End when nothing changes for (s)',
    'RANKED_ATTACKS_ENABLED': 'Attack in Ranked tournaments',
    'RANKED_MAX_PER_DAY': 'Ranked attacks per day',
    'RANKED_AUTO_SIGNUP': 'Sign up for tournaments automatically',
    'WAR_ATTACKS_ENABLED': 'Attack in Clan War / CWL',
    'WAR_MAX_ATTACKS': 'War attacks per war',
    'WAR_ATTACK_STRATEGY': 'War strategy',
    'WAR_CSV_SCRIPT': 'War script',
    'COLLECT_RESOURCES': 'Collect resources',
    'COLLECT_LOOT_CART': 'Collect the loot cart too',
    'CLAIM_EVENT_REWARDS': 'Claim free event rewards',
    'REMOVE_OBSTACLES': 'Remove obstacles',
    'AUTO_UPGRADE_BUILDINGS': 'Upgrade buildings and heroes',
    'AUTO_UPGRADE_KEEP_BUILDERS': 'Keep builders free',
    'AUTO_UPGRADE_LAB': 'Laboratory research',
    'AUTO_UPGRADE_PETS': 'Pet House upgrades',
    'AUTO_UPGRADE_EQUIPMENT': 'Hero equipment upgrades',
    'UPGRADE_WALLS': 'Upgrade walls',
    'HELPER_HUT_ENABLED': 'Use the Helper Hut',
    'HELPER_APPRENTICE': 'Builder Apprentice',
    'HELPER_LAB_ASSISTANT': 'Lab Assistant',
    'SUPER_TROOP_ENABLED': 'Keep Super Troops boosted',
    'SUPER_TROOPS': 'Super Troops to boost (max 2)',
    'SUPER_TROOP_USE_POTION': 'Use Super Potions first',
    'BB_ATTACKS_ENABLED': 'Builder Base battles',
    'BB_ATTACKS_PER_VISIT': 'Battles per visit',
    'BB_INTERVAL_MINUTES': 'Visit every (minutes)',
    'BB_ONLY': 'Builder Base ONLY mode',
    'BB_AUTO_UPGRADE': 'Upgrade Builder Base buildings',
    'BB_AUTO_LAB': 'Star Laboratory research',
    'REQUEST_DONATIONS': 'Request troops from the clan',
    'DONATE_ENABLED': 'Donate to clan requests',
    'DONATE_TROOPS': 'What to donate',
    'CLAN_GAMES': 'Play Clan Games',
    'CG_TROOP_CHALLENGES': 'Prefer Super Troop challenges',
    'CAPITAL_RAIDS_ENABLED': 'Clan Capital raids',
    'CAPITAL_MAX_RAIDS': 'Raid attacks per visit',
    'SCHED_ACTIVE_HOURS_ENABLED': 'Only play during set hours',
    'SCHED_START_HOUR': 'Start hour (0-23)',
    'SCHED_END_HOUR': 'End hour (0-23)',
    'SCHED_BREAKS_ENABLED': 'Take random breaks',
    'SCHED_BREAK_EVERY_MIN': 'Play at least (minutes)',
    'SCHED_BREAK_EVERY_MAX': 'Play at most (minutes)',
    'SCHED_BREAK_LENGTH_MIN': 'Shortest break (minutes)',
    'SCHED_BREAK_LENGTH_MAX': 'Longest break (minutes)',
    'END_CONDITIONS_ENABLED': 'Stop automatically',
    'END_AFTER_ATTACKS': 'After this many attacks',
    'END_AFTER_HOURS': 'After this many hours',
    'END_AFTER_GOLD': 'After gaining this much gold',
    'END_AFTER_ELIXIR': 'After gaining this much elixir',
    'END_AFTER_DARK': 'After gaining this much dark elixir',
    'MULTI_VILLAGE_ENABLED': 'Switch between accounts',
    'START_PROFILE': 'Start with account',
    'VILLAGE_COUNT': 'Number of accounts',
    'VILLAGE_SWITCH_MINUTES': 'Switch every (minutes)',
    'SWITCH_ON_LOOT_FULL': 'Switch when storages are full',
    'SWITCH_ON_BUILDERS_BUSY': 'Switch when all builders are busy',
}

# key -> (title, card hint, icon, [keys])
PAGES = [
    ('attack', 'Attack', 'Choose how the bot attacks and which bases are worth it.', [
        ('50% Loot Maxxing', 'Fast 1-star loot attacks: 50% gives the star, the star gives the loot bonus, '
         'and the battle ends after ~15 s. Replay army: 11 Electro Dragons; Queen, King, Warden, Minion Prince '
         '(+ pets); 11 Earthquake, 2 Freeze, 1 Totem. Other armies work too.', 'star',
         ['LOOTMAX_ENABLED', 'LOOTMAX_ARMY_SLOT', 'LOOTMAX_TARGET_DAMAGE', 'LOOTMAX_USE_ABILITIES',
          'LOOTMAX_HUMANIZE']),
        ('Strategy', 'Pick the attack plan that matches your army.', 'attack',
         ['SELECTED_ATTACK_STRATEGY', 'CSV_ATTACK_SCRIPT', 'CSV_USE_REDLINE', 'SELECTED_ARMY_SLOT']),
        ('Which bases to attack', 'Bases with less loot than this are skipped (Next).', 'gold',
         ['ATTACK_MIN_GOLD', 'ATTACK_MIN_ELIXIR', 'ATTACK_MIN_DARK', 'XP_FARMING']),
        ('End battles early', 'Leave a battle once it has done enough, to save time.', 'clock',
         ['END_BATTLE_ENABLED', 'END_BATTLE_STARS', 'END_BATTLE_DAMAGE', 'END_BATTLE_NO_CHANGE_SECONDS']),
        ('Fine tuning', 'Advanced: only change these if attacks need adjusting.', 'settings',
         ['HERO_TAP_DELAY_ENABLED', 'HERO_TAP_DELAY_SECONDS', 'AIR_TROOP_WIDTH_ENABLED', 'AIR_TROOP_WIDTH']),
        ('Ranked tournaments', 'Uses tournament attacks (no loot). Sign-up stays off unless you turn it on.', 'star',
         ['RANKED_ATTACKS_ENABLED', 'RANKED_MAX_PER_DAY', 'RANKED_AUTO_SIGNUP']),
        ('Clan War and CWL', 'Uses your real war attacks on the recommended target. Off unless you turn it on.', 'clan',
         ['WAR_ATTACKS_ENABLED', 'WAR_MAX_ATTACKS', 'WAR_ATTACK_STRATEGY', 'WAR_CSV_SCRIPT']),
    ]),
    ('village', 'Village', 'Chores the bot does in your home village between attacks.', [
        ('Resources', '', 'gold',
         ['COLLECT_RESOURCES', 'COLLECT_LOOT_CART', 'CLAIM_EVENT_REWARDS', 'REMOVE_OBSTACLES']),
        ('Upgrades', 'These spend your resources: each one is off until you turn it on.', 'builder',
         ['AUTO_UPGRADE_BUILDINGS', 'AUTO_UPGRADE_KEEP_BUILDERS', 'AUTO_UPGRADE_LAB', 'AUTO_UPGRADE_PETS',
          'AUTO_UPGRADE_EQUIPMENT', 'UPGRADE_WALLS']),
        ('Helper Hut', '', 'accounts', ['HELPER_HUT_ENABLED', 'HELPER_APPRENTICE', 'HELPER_LAB_ASSISTANT']),
        ('Super Troops', '', 'star', ['SUPER_TROOP_ENABLED', 'SUPER_TROOPS', 'SUPER_TROOP_USE_POTION']),
    ]),
    ('builder', 'Builder Base', 'Builder Base battles and upgrades.', [
        ('Battles', '', 'attack', ['BB_ATTACKS_ENABLED', 'BB_ATTACKS_PER_VISIT', 'BB_INTERVAL_MINUTES', 'BB_ONLY']),
        ('Upgrades', 'Spend Builder Base resources on visits.', 'builder', ['BB_AUTO_UPGRADE', 'BB_AUTO_LAB']),
    ]),
    ('clan', 'Clan & Events', 'Donations, Clan Games and the Clan Capital.', [
        ('Donations', '', 'clan', ['REQUEST_DONATIONS', 'DONATE_ENABLED', 'DONATE_TROOPS']),
        ('Clan Games', '', 'star', ['CLAN_GAMES', 'CG_TROOP_CHALLENGES']),
        ('Clan Capital', '', 'village', ['CAPITAL_RAIDS_ENABLED', 'CAPITAL_MAX_RAIDS']),
    ]),
    ('schedule', 'Schedule', 'When the bot plays, rests and stops.', [
        ('Play hours', 'Outside these hours the game is closed.', 'clock',
         ['SCHED_ACTIVE_HOURS_ENABLED', 'SCHED_START_HOUR', 'SCHED_END_HOUR']),
        ('Breaks', 'Random breaks, like putting the phone down.', 'pause',
         ['SCHED_BREAKS_ENABLED', 'SCHED_BREAK_EVERY_MIN', 'SCHED_BREAK_EVERY_MAX',
          'SCHED_BREAK_LENGTH_MIN', 'SCHED_BREAK_LENGTH_MAX']),
        ('Stop automatically', '0 means "no limit".', 'stop',
         ['END_CONDITIONS_ENABLED', 'END_AFTER_ATTACKS', 'END_AFTER_HOURS', 'END_AFTER_GOLD',
          'END_AFTER_ELIXIR', 'END_AFTER_DARK']),
    ]),
]

ACCOUNT_KEYS = ['MULTI_VILLAGE_ENABLED', 'START_PROFILE', 'VILLAGE_COUNT', 'VILLAGE_SWITCH_MINUTES',
                'SWITCH_ON_LOOT_FULL', 'SWITCH_ON_BUILDERS_BUSY']

# Quick switches shown on the dashboard.
QUICK_KEYS = ['LOOTMAX_ENABLED', 'COLLECT_RESOURCES', 'CLAIM_EVENT_REWARDS', 'BB_ATTACKS_ENABLED', 'DONATE_ENABLED',
              'END_BATTLE_ENABLED', 'XP_FARMING', 'SCHED_BREAKS_ENABLED', 'END_CONDITIONS_ENABLED']

# Settings that are global (not per account). SWITCH_ON_BUILDERS_BUSY is global in practice (Q3).
GLOBAL_KEYS = {s['key'] for s in SETTINGS if s['scope'] == 'global'} | {'SWITCH_ON_BUILDERS_BUSY'}


def title(key):
    return TITLES.get(key, BY_KEY[key]['label'])


def help_text(key):
    return BY_KEY[key]['help']


def depends_ok(dep, cfg):
    """Evaluate a catalogue depends_on against a config dict."""
    if dep is None:
        return True
    if isinstance(dep, dict):
        return any(depends_ok(d, cfg) for d in dep.get('any', []))
    if isinstance(dep, list):
        return all(depends_ok(d, cfg) for d in dep)
    if isinstance(dep, tuple):
        k, v = dep
        cur = cfg.get(k, BY_KEY[k]['default'] if k in BY_KEY else None)
        return cur == v
    return bool(cfg.get(dep, BY_KEY[dep]['default'] if dep in BY_KEY else False))


def depends_text(dep):
    if dep is None:
        return ''
    if isinstance(dep, dict):
        return ' or '.join(depends_text(d) for d in dep.get('any', []))
    if isinstance(dep, list):
        return ', '.join(depends_text(d) for d in dep)
    if isinstance(dep, tuple):
        k, v = dep
        if k == 'SELECTED_ATTACK_STRATEGY' or k == 'WAR_ATTACK_STRATEGY':
            label = dict(STRATEGY_CHOICES).get(v, v)
            return f'"{title(k)}" = {label}'
        return f'"{title(k)}" {"on" if v else "off"}' if isinstance(v, bool) else f'"{title(k)}" = {v}'
    return f'"{title(dep)}" on'


__all__ = ['PAGES', 'BY_KEY', 'ACCOUNT_KEYS', 'QUICK_KEYS', 'GLOBAL_KEYS', 'STRATEGY_HELP', 'title',
           'help_text', 'depends_ok', 'depends_text']
