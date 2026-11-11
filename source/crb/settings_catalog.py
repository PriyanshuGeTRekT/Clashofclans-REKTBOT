# crb/settings_catalog.py -- every user-facing setting (key, kind, default, range, scope, help) and
# every non-setting UI function of the bot, inventoried from the old ACBot GUI (ui/main_window.py).
# Contract with the bot backend: key names, scopes and quirks below must stay exact.
#
# Sources read: ui/main_window.py, ui/bot_worker.py, ui/gui.py, control.py, defaults.py,
# profiles/config_manager.py, profiles/profile_manager.py, startup.py, adb.py, main.py, farming.py,
# scheduler.py, stats.py, attack/*.py, war.py, ranked.py, builder_base.py, upgrades.py, donate.py,
# supertroop.py, helperhut.py, collect.py, rewards.py, obstacles.py, capital.py, battle_end.py,
# clangames.py, walls.py.
#
# ======================================================================================== QUIRKS
# PERSISTENCE MODEL
#  Q1  ConfigManager (profiles/config_manager.py). Global file = <writable>/profiles/config.json;
#      per-profile file = <writable>/profiles/<name>/config.json.
#      load(None) -> global dict.  load(name) -> global.copy() updated with the profile dict (MERGED).
#      save(cfg, None) -> writes the whole dict to the global file.
#      save(cfg, name) -> pops GLOBAL_KEYS from cfg *in place*, writes the rest to the profile file.
#      GLOBAL_KEYS = MULTI_VILLAGE_ENABLED, VILLAGE_SWITCH_MINUTES, SWITCH_ON_LOOT_FULL, VILLAGE_COUNT,
#      START_PROFILE, EMULATOR_SELECTION, EMULATOR_IP, EMULATOR_PORT.  Everything else is
#      "profile scope": saved to the active profile (MainWindow.current_profile) when one is
#      loaded, otherwise to the global file. The global file therefore doubles as (a) the
#      single-village config and (b) the TEMPLATE for new profiles: a profile config is created
#      as a copy of the current global config.json minus GLOBAL_KEYS.
#  Q2  Only keys defined in defaults.py are auto-filled (PROFILE_KEYS = UPPER_CASE names of
#      defaults.py minus GLOBAL_KEYS). Every Pro / War / BB / CSV key (and SWITCH_ON_BUILDERS_BUSY)
#      is NOT in defaults.py: it is absent from fresh configs and readers fall back to the
#      hard-coded default in the UI/backend `.get(key, default)` (listed in 'default' below).
#      ConfigManager.load also rewrites any None value to False.
#  Q3  SWITCH_ON_BUILDERS_BUSY is saved to the GLOBAL file by update_multi but is NOT in
#      GLOBAL_KEYS, so it is copied into every profile created afterwards and that (stale) profile
#      copy overrides the global value in the merged runtime config after a profile switch.
#      A new UI should treat it as global and ideally also write/strip it from profile files.
#  Q4  PROFILE_MATCH_THRESHOLD is edited per *named* profile from the pencil popup (not the active
#      profile); saved as round(value, 2). defaults.py says 0.92 (auto-filled), UI/backend fallback 0.9.
#  Q5  The bot reads config only when main.main() starts and at each profile switch
#      (ConfigManager().load(...) merged into main.active_config). Settings pages are disabled
#      while running (set_controls_enabled(False)), so edits apply on the next Start/switch.
#  Q6  Emulator/IP/port are NOT read from config by the bot: main.main() uses
#      startup.get_selected_emulator() and the adb module's globals. The UI must push them live:
#      startup.set_selected_emulator(key); adb.set_emulator(key); adb.set_host(ip or '127.0.0.1');
#      adb.set_port(port) -- on every change AND once at startup after restoring from config.
# TRANSFORMS / CLAMPS / FORCED VALUES
#  Q7  CLAN_CAPITAL is written False on every update_general() ("forced off"); nothing reads it.
#  Q8  SELECTED_ARMY_SLOT stores the combo INDEX 0..8 ('Slot 1'..'Slot 8' = 0..7, 'Current Army' = 8).
#      defaults.py default is 1, i.e. the UI shows "Slot 2" on a fresh config (UI fallback is 0).
#      Loader clamps to 0..8. farming taps bars[slot]; 8 == CURRENT_ARMY_SLOT_INDEX = no switch.
#  Q9  SELECTED_ATTACK_STRATEGY / WAR_ATTACK_STRATEGY store internal keys ('edragon', 'csv', ...),
#      the combos show display names (strategy_map / _WAR_STRATEGIES). LOCKED_STRATEGIES is an
#      empty set (paywall removed); if it were non-empty a locked choice is forced to edragon.
#      An unknown key at runtime falls back to 'edragon'.
#  Q10 AIR_TROOP_WIDTH: spinbox range 50..600 step 50, but the loader AND the backend
#      (attacklogic.set_attack_runtime_settings) clamp to 50..500. HERO_TAP_DELAY_SECONDS clamped 1..15.
#      HERO_TAP_DELAY_SECONDS is the real delay in seconds (backend calls wait(sec*2) because wait halves).
#  Q11 VILLAGE_COUNT saved as min(100, value) (FREE_MAX_VILLAGES=100; ProfileManager.MAX_PROFILES=100).
#      defaults.py default 5; UI loader fallback 10.  VILLAGE_SWITCH_MINUTES default 10 (defaults.py),
#      backend fallback 30.
#  Q12 CSV_ATTACK_SCRIPT / WAR_CSV_SCRIPT are saved only when the combo text is non-empty (never
#      cleared). Values are .csv basenames WITHOUT extension from <APP_LAUNCH_DIR or cwd>/CSV/Attack.
#      Unset CSV_ATTACK_SCRIPT -> csv_script.DEFAULT_SCRIPT 'PHMOD-DragLoon'. Unset WAR_CSV_SCRIPT ->
#      war uses CSV_ATTACK_SCRIPT.
#  Q13 CSV_USE_REDLINE (default True) is only enabled in the UI for strategy 'csv', but the backend
#      also applies it to the bundled scripted strategies (valkyrie, sminion, sbarb, barch, thrower
#      run through attack.csv_script.run_attack with the same cfg).
#  Q14 Pro 'text' fields are saved stripped, on editingFinished only (not per keystroke). The UI
#      shows label.split(',')[0] as the row label and the full label as placeholder.
#  Q15 Pro 'int' fields with max >= 1,000,000 show thousands separators (setGroupSeparatorShown).
#      All QSpinBoxes use the en_US locale.
#  Q16 EMULATOR_PORT is a STRING. A non-digit port text is neither applied nor saved. Choosing an
#      emulator overwrites the port with that emulator's default (except during the startup restore).
#      Empty IP saves as '127.0.0.1'.
#  Q17 SWITCH_ON_LOOT_FULL disables the VILLAGE_SWITCH_MINUTES spinbox (UI), but with
#      SWITCH_ON_BUILDERS_BUSY the minutes are the MINIMUM play time before switching. Precedence in
#      farming: SWITCH_ON_LOOT_FULL > SWITCH_ON_BUILDERS_BUSY > timer. With SWITCH_ON_LOOT_FULL the bot
#      STOPS once every enabled profile has been seen full.
#  Q18 CG_TROOP_CHALLENGES is force-unchecked and disabled whenever CLAN_GAMES is unchecked.
#  Q19 Unticking MULTI_VILLAGE_ENABLED resets current_profile to None and reloads the GLOBAL config
#      into every widget (update_multi).
#  Q20 SCHED_* min/max pairs are swapped automatically if min > max (scheduler._range). Start==End
#      hour means "always active"; End < Start wraps past midnight.
#  Q21 END_AFTER_HOURS is measured from scheduler module import (= app launch), NOT from Start;
#      the other END_AFTER_* use the per-Start Stats object.
#  Q22 apply_config_to_gui() does NOT refresh VILLAGE_COUNT / VILLAGE_SWITCH_MINUTES /
#      SWITCH_ON_LOOT_FULL / SWITCH_ON_BUILDERS_BUSY / START_PROFILE widgets (only read at build
#      time; START_PROFILE via refresh_profile_list). It also leaves multi_enabled unblocked, so it
#      can recurse into update_multi. handle_config_update applies config WITHOUT block_gui_signals,
#      so it re-saves the GUI values into the (new) current profile.
#  Q23 When the bot stops by itself (end condition, loot-full stop, crash limit) the worker emits
#      'Stopped' but handle_worker_status does NOT re-enable the controls; only stop_bot() does.
#  Q24 After the profile-edit popup closes the old UI sets status 'Deleted all profiles' (copy/paste
#      bug in the original). main.profile_loot_status is only ever reset, so the ' 🔋' suffix in the
#      profile list never appears.
#  Q25 Keys present in configs but NOT exposed by the old UI (keep them untouched):
#      WALL_MIN_GOLD, WALL_MIN_ELIXIR (defaults.py, unused), TEMPLATES_DIR (read from defaults module,
#      not config), CLAN_CAPITAL (forced False), RANKED_ATTACK_STRATEGY (ranked.py, falls back to
#      SELECTED_ATTACK_STRATEGY), HELPER_HUT_POS ([x, y], helperhut.py), CG_DISABLED_CHALLENGES
#      (list written by clangames.py into the profile config).
# ==============================================================================================

STRATEGY_CHOICES = [  # (config value, old UI label) -- MainWindow.strategy_map, combo order
    ('edragon', 'Electric Dragon/Loon'),
    ('dragon', 'Dragon/Loon'),
    ('valkyrie', 'Valkyrie + Quake'),
    ('sminion', 'Super Minion + Quake'),
    ('sbarb', 'Super Barbarian'),
    ('barch', 'BArch / Goblin'),
    ('thrower', 'Thrower Smash'),
    ('csv', 'Custom Script (CSV)'),
]
# Backend dispatch: farming.ATTACK_STRATEGY_MODULES = {'edragon','dragon','csv'} + attack.scripted
# STRATEGY_SCRIPTS: valkyrie->'ACBot-Valkyrie Quake', sminion->'ACBot-SuperMinion Quake',
# sbarb->'ACBot-Super Barb', barch->'ACBot-BArch Goblin', thrower->'PHMOD-Thrower Smash'.

WAR_STRATEGY_CHOICES = [  # MainWindow._WAR_STRATEGIES
    ('edragon', 'Electric Dragon/Loon'),
    ('dragon', 'Dragon/Loon'),
    ('csv', 'Custom Script (CSV)'),
]

ARMY_SLOT_CHOICES = [(i, f'Slot {i + 1}') for i in range(8)] + [(8, 'Current Army')]

EMULATOR_CHOICES = [  # (key, display name, default ADB port) -- startup.EMULATOR_CONFIGS order
    ('bluestacks', 'BlueStacks', '5556'),
    ('ldplayer', 'LDPlayer', '5555'),
    ('memu', 'MEmu', '21503'),
    ('nox', 'Nox', '62001'),
    ('mumu', 'MuMu Player', '16384'),
    ('other', 'Other', '5555'),
]

# Read-only "Army Composition Suggestion" text shown under the strategy combo (strategy_help).
STRATEGY_HELP = {
    'edragon': '• Any # Electro Dragons\n• Any # Balloons\n• Up to 5 Rage +  4 Freeze\n• Funnel with up to 4 heroes\n• Any siege machine (preferably Stone Slammer)\n• CC: Any troop with 1 Rage + 1 Freeze',
    'dragon': '• Any # Dragons\n• Any # Balloons\n• Up to 5 Rage +  4 Freeze\n• Funnel with up to 4 heroes\n• Any siege machine (preferably Stone Slammer)\n• CC: Any troop with 1 Rage + 1 Freeze',
    'valkyrie': '• Any # Valkyries\n• 11x Earthquake\n• Funnel with up to 4 heroes\n• Any siege machine (preferably Wall Wrecker or Log Launcher)\n• CC: Super Valkyrie & Super Yeti with Totem Spells(Will drop on th)',
    'sminion': '• Any #Super Minions\n• 11x Earthquake\n• Funnel with up to 4 heroes\n• Any siege machine (preferably Wall Wrecker or Log Launcher)\n• CC: Super Valkyrie & Super Yeti with Totem Spells(Will drop on th)',
    'sbarb': '• Super Barbarians (any count)\n• Wall Breakers optional\n• 2+ Rage\n• Heroes and any siege\n• Script: CSV\\Attack\\ACBot-Super Barb.csv',
    'barch': '• Barbarians, Archers and/or Goblins (normal or super)\n• No spells needed\n• Spreads all around the base to farm outside collectors\n• Script: CSV\\Attack\\ACBot-BArch Goblin.csv',
    'thrower': '• Throwers with the army in the script NOTE lines\n• Script: CSV\\Attack\\PHMOD-Thrower Smash.csv',
    'csv': '• Runs a MyBot/PHMOD-format attack script from CSV\\Attack\n• Train the army listed in the script (TRAIN lines / NOTE header)\n• Troops missing from your bar are skipped\n• Add your own scripts by dropping .csv files into CSV\\Attack',
}

CSV_SCRIPTS_SOURCE = "attack.csv_script.list_scripts()  # sorted .csv basenames (no ext) in <APP_LAUNCH_DIR or cwd>/CSV/Attack"
PROFILE_NAMES_SOURCE = "ProfileManager(None).list_profiles() filtered by active_profiles.json enabled flag (MainWindow.refresh_start_profile_dropdown)"


def _s(key, label, kind, default, scope, old_section, help, depends_on=None, *, min=None, max=None,
       step=None, choices=None, choices_source=None, widget=None, saved_by=None, notes=None):
    """One setting. depends_on: None | 'KEY' (must be truthy) | ('KEY', value) (must equal value)
    | a list of those (all must hold) | {'any': [...]} (any must hold)."""
    return {'key': key, 'label': label, 'kind': kind, 'default': default, 'min': min, 'max': max,
            'step': step, 'choices': choices, 'choices_source': choices_source, 'scope': scope,
            'old_section': old_section, 'help': help, 'depends_on': depends_on,
            'old_widget': widget, 'saved_by': saved_by, 'notes': notes}


P, G = 'profile', 'global'
CSV_ON = ('SELECTED_ATTACK_STRATEGY', 'csv')
BB_VISITS = {'any': ['BB_ATTACKS_ENABLED', 'BB_ONLY']}

SETTINGS = [
    # ------------------------------------------------------------------ General page
    _s('UPGRADE_WALLS', 'Upgrade Walls', 'bool', False, P, 'General: Wall Upgrades',
       'Each home-village cycle spends spare gold/elixir upgrading walls (walls.upgrade_walls); skipped for 1 h once no wall is left to upgrade.',
       widget='upgrade_walls', saved_by='update_general'),
    _s('ATTACK_MIN_GOLD', 'Min Gold', 'int', 0, P, 'General: Attack Filter',
       'Only attack a searched base whose gold is at least this much (ignored by XP farming).',
       min=0, max=50_000_000, step=200_000, widget='attack_gold', saved_by='update_general',
       notes='group separators shown'),
    _s('ATTACK_MIN_ELIXIR', 'Min Elixir', 'int', 0, P, 'General: Attack Filter',
       'Only attack a searched base whose elixir is at least this much (ignored by XP farming).',
       min=0, max=50_000_000, step=200_000, widget='attack_elixir', saved_by='update_general'),
    _s('ATTACK_MIN_DARK', 'Min Dark', 'int', 0, P, 'General: Attack Filter',
       'Only attack a searched base whose dark elixir is at least this much (ignored by XP farming).',
       min=0, max=50_000, step=500, widget='attack_dark', saved_by='update_general'),
    _s('REQUEST_DONATIONS', 'Request Donations', 'bool', False, P, 'General: Donations',
       'Before each search, taps the Clan Castle request button when available and sends the request.',
       widget='request_donations', saved_by='update_donations'),
    _s('CLAN_GAMES', 'Enable Clan Games', 'bool', False, P, 'General: Clan Games',
       'Each home cycle opens Clan Games, picks/handles challenges (army edits, CG troop requests).',
       widget='clan_games_enable', saved_by='update_general'),
    _s('CG_TROOP_CHALLENGES', 'Enable Super Troop Challenges', 'bool', False, P, 'General: Clan Games',
       'Prefer super-troop (cgsuper_*) Clan Games challenges, falling back to regular ones.',
       depends_on='CLAN_GAMES', widget='cg_troop_challenges', saved_by='update_general',
       notes='force-unchecked + disabled when CLAN_GAMES is off (Q18)'),

    # ------------------------------------------------------------------ Attack Army page
    _s('HERO_TAP_DELAY_ENABLED', 'Hero Re-Tap Delay', 'bool', False, P, 'Attack Army: Attack Settings',
       'Use a custom delay before re-tapping heroes to fire their ability (instead of the built-in delay).',
       widget='hero_tap_delay_enabled', saved_by='update_attack_army'),
    _s('HERO_TAP_DELAY_SECONDS', 'Hero Re-Tap Delay (seconds)', 'int', 1, P, 'Attack Army: Attack Settings',
       'Seconds to wait before the hero ability re-tap.', depends_on='HERO_TAP_DELAY_ENABLED',
       min=1, max=15, step=1, widget='hero_tap_delay_seconds', saved_by='update_attack_army',
       notes='clamped 1..15 on load and in backend'),
    _s('AIR_TROOP_WIDTH_ENABLED', 'Air Troop Spread', 'bool', False, P, 'Attack Army: Attack Settings',
       'Override the width (px) of the line along which air troops are dropped.',
       widget='air_troop_width_enabled', saved_by='update_attack_army'),
    _s('AIR_TROOP_WIDTH', 'Air Troop Spread (px)', 'int', 300, P, 'Attack Army: Attack Settings',
       'Drop-line width in screen pixels used for air troops.', depends_on='AIR_TROOP_WIDTH_ENABLED',
       min=50, max=500, step=50, widget='air_troop_width', saved_by='update_attack_army',
       notes='old spinbox max was 600 but loader and backend clamp to 500 (Q10)'),
    _s('SELECTED_ATTACK_STRATEGY', 'Attack Strategy', 'choice', 'edragon', P, 'Attack Army: Attack Army tab',
       'Strategy used for multiplayer attacks (also the fallback for war/ranked).',
       choices=STRATEGY_CHOICES, widget='strategy', saved_by='update_attack_army',
       notes='stores internal key, combo shows display name (Q9)'),
    _s('CSV_ATTACK_SCRIPT', 'Attack Script (Custom Script strategy)', 'choice', None, P, 'Attack Army: Attack Army tab',
       'CSV attack script (basename in CSV/Attack) run by the Custom Script strategy; unset = PHMOD-DragLoon.',
       depends_on=CSV_ON, choices_source=CSV_SCRIPTS_SOURCE, widget='csv_script', saved_by='update_attack_army',
       notes='saved only when non-empty (Q12)'),
    _s('CSV_USE_REDLINE', 'Drop on the detected red line (off: outer map edges)', 'bool', True, P, 'Attack Army: Attack Army tab',
       'Detects the dashed deploy border while scouting and starts every script vector there (MyBot style); off = outer map edges.',
       depends_on=CSV_ON, widget='csv_redline', saved_by='update_attack_army',
       notes='backend also applies it to the bundled scripted strategies (Q13)'),
    _s('SELECTED_ARMY_SLOT', 'Army Slot', 'choice', 1, P, 'Attack Army: Attack Army tab',
       'Saved army (quick-train) slot selected before attacking; Current Army = keep whatever is trained.',
       choices=ARMY_SLOT_CHOICES, widget='army_slot', saved_by='update_attack_army',
       notes='stores combo index 0..8; defaults.py 1 == "Slot 2" (Q8)'),

    # ------------------------------------------------------------------ 50% Loot Maxxing (attack/lootmax.py)
    _s('LOOTMAX_ENABLED', '50% Loot Maxxing strategy', 'bool', False, P, 'Attack: 50% Loot Maxxing',
       'Every attack: dragons round three sides, heroes on the fourth, all Earthquakes on the Town Hall, then End Battle once 1 star and the target damage are reached (~15 s per attack, star bonus included). Overrides the attack strategy above.',
       notes='army: Electro Dragons (or Dragons) + heroes + Earthquakes'),
    _s('LOOTMAX_ARMY_SLOT', 'Army slot for this strategy', 'choice', 8, P, 'Attack: 50% Loot Maxxing',
       'Save the replay army in an in-game army slot (11 Electro Dragons, Queen, King, Warden, Minion Prince + pets, 11 Earthquake, 2 Freeze, 1 Totem) and pick that slot: the bot trains it before attacking. "Current Army" = use whatever is trained (other troops work too).',
       depends_on='LOOTMAX_ENABLED', choices=ARMY_SLOT_CHOICES),
    _s('LOOTMAX_TARGET_DAMAGE', 'End at about this damage %', 'int', 50, P, 'Attack: 50% Loot Maxxing',
       'The battle is ended once this damage (plus a random 0-6 %) and 1 star are reached.',
       depends_on='LOOTMAX_ENABLED', min=50, max=90, step=1),
    _s('LOOTMAX_USE_ABILITIES', 'Use hero abilities', 'bool', True, P, 'Attack: 50% Loot Maxxing',
       'Fire each hero ability a few seconds after the Earthquakes, in a random order.',
       depends_on='LOOTMAX_ENABLED'),
    _s('LOOTMAX_HUMANIZE', 'Vary every attack (human-like)', 'bool', True, P, 'Attack: 50% Loot Maxxing',
       'Randomises tap spots, spacing, sweep direction, hero sides and order, every pause and the exit point, so no two attacks look the same.',
       depends_on='LOOTMAX_ENABLED'),

    # ------------------------------------------------------------------ Pro Features page (hand-built boxes)
    _s('WAR_ATTACKS_ENABLED', 'Attack in Clan War and CWL (uses real war attacks)', 'bool', False, P, 'Pro Features: Clan War / CWL',
       'On war Battle Day, attacks the game\'s "Recommended target" using real war attacks.',
       widget='war_enable', saved_by='update_pro_features'),
    _s('WAR_MAX_ATTACKS', 'Attacks per war', 'int', 2, P, 'Pro Features: Clan War / CWL',
       'Maximum war attacks the bot spends per war.', depends_on='WAR_ATTACKS_ENABLED',
       min=1, max=2, step=1, widget='war_max', saved_by='update_pro_features'),
    _s('WAR_ATTACK_STRATEGY', 'War strategy', 'choice', 'edragon', P, 'Pro Features: Clan War / CWL',
       'Strategy used for war attacks (falls back to SELECTED_ATTACK_STRATEGY if unset).',
       depends_on='WAR_ATTACKS_ENABLED', choices=WAR_STRATEGY_CHOICES, widget='war_strategy',
       saved_by='update_pro_features'),
    _s('WAR_CSV_SCRIPT', 'War script', 'choice', None, P, 'Pro Features: Clan War / CWL',
       'CSV script for war attacks when the war strategy is Custom Script; unset = CSV_ATTACK_SCRIPT.',
       depends_on=['WAR_ATTACKS_ENABLED', ('WAR_ATTACK_STRATEGY', 'csv')], choices_source=CSV_SCRIPTS_SOURCE,
       widget='war_script', saved_by='update_pro_features', notes='saved only when non-empty (Q12)'),
    _s('BB_ATTACKS_ENABLED', 'Builder Base battles (both stages, Battle Machine ability, Star Bonus)', 'bool', False, P, 'Pro Features: Builder Base',
       'Periodically sails to the Builder Base, fights battles, then returns home.',
       widget='bb_enable', saved_by='update_pro_features'),
    _s('BB_ATTACKS_PER_VISIT', 'Battles per visit', 'int', 3, P, 'Pro Features: Builder Base',
       'Builder Base battles per visit (also per loop in BB-only mode).', depends_on=BB_VISITS,
       min=1, max=20, step=1, widget='bb_attacks', saved_by='update_pro_features'),
    _s('BB_INTERVAL_MINUTES', 'Visit every (minutes)', 'int', 60, P, 'Pro Features: Builder Base',
       'Minutes between Builder Base visits.', depends_on='BB_ATTACKS_ENABLED',
       min=10, max=720, step=10, widget='bb_interval', saved_by='update_pro_features'),
    _s('BB_ONLY', 'Builder Base battles ONLY (no home village attacks, stays on the Builder Base)', 'bool', False, P, 'Pro Features: Builder Base',
       'Skips the home village entirely: stays on the Builder Base battling back to back (scheduler/end conditions still apply).',
       widget='bb_only', saved_by='update_pro_features', notes='works without BB_ATTACKS_ENABLED'),
    _s('RANKED_AUTO_SIGNUP', 'Sign up for Ranked Battle tournaments automatically', 'bool', False, P, 'Pro Features: Ranked Battles',
       'When the Battle menu shows "Sign Up!/Join Tournament" on the Ranked card, signs up (once per session).',
       widget='ranked_signup', saved_by='update_pro_features'),

    # ------------------------------------------------------------------ PRO_SETTING_GROUPS (generic)
    # Village
    _s('COLLECT_RESOURCES', 'Collect full collectors, gem box and gem mine every 10 minutes', 'bool', False, P, 'Pro: Village',
       'Every 10 min on the home village taps full collectors, gem box and gem mine (also collects on BB visits).',
       widget="pro_widgets['COLLECT_RESOURCES']", saved_by='update_pro_features'),
    _s('COLLECT_LOOT_CART', 'Also collect the loot cart', 'bool', True, P, 'Pro: Village',
       'During resource collection also opens and collects the loot cart.', depends_on='COLLECT_RESOURCES',
       widget="pro_widgets['COLLECT_LOOT_CART']", saved_by='update_pro_features'),
    _s('CLAIM_EVENT_REWARDS', 'Claim free event rewards (Events window, every 3 hours)', 'bool', False, P, 'Pro: Village',
       'Every 3 h opens the Events window and claims free rewards.',
       widget="pro_widgets['CLAIM_EVENT_REWARDS']", saved_by='update_pro_features'),
    _s('REMOVE_OBSTACLES', 'Remove obstacles (templates in templates/obstacles, needs a free builder)', 'bool', False, P, 'Pro: Village',
       'Every 30 min finds obstacles (templates/obstacles) and removes them with a free builder.',
       widget="pro_widgets['REMOVE_OBSTACLES']", saved_by='update_pro_features'),
    # Auto Upgrades
    _s('AUTO_UPGRADE_BUILDINGS', 'Buildings and heroes (free builders)', 'bool', False, P, 'Pro: Auto Upgrades (first affordable upgrade in the game Build menu list)',
       'Every 30 min starts the first affordable building/hero upgrade(s) in the Build menu with free builders (max 3 per run).',
       widget="pro_widgets['AUTO_UPGRADE_BUILDINGS']", saved_by='update_pro_features'),
    _s('AUTO_UPGRADE_KEEP_BUILDERS', 'Keep this many builders free (e.g. for walls)', 'int', 0, P, 'Pro: Auto Upgrades (first affordable upgrade in the game Build menu list)',
       'Builders reserved (not used) by building auto-upgrades.', depends_on='AUTO_UPGRADE_BUILDINGS',
       min=0, max=6, step=1, widget="pro_widgets['AUTO_UPGRADE_KEEP_BUILDERS']", saved_by='update_pro_features'),
    _s('AUTO_UPGRADE_LAB', 'Laboratory research (troops, spells, sieges)', 'bool', False, P, 'Pro: Auto Upgrades (first affordable upgrade in the game Build menu list)',
       'Every 30 min starts the first affordable Laboratory research.',
       widget="pro_widgets['AUTO_UPGRADE_LAB']", saved_by='update_pro_features'),
    _s('AUTO_UPGRADE_PETS', 'Pet House', 'bool', False, P, 'Pro: Auto Upgrades (first affordable upgrade in the game Build menu list)',
       'Every 30 min starts the first affordable Pet House upgrade.',
       widget="pro_widgets['AUTO_UPGRADE_PETS']", saved_by='update_pro_features'),
    _s('AUTO_UPGRADE_EQUIPMENT', 'Hero equipment (Blacksmith, spends ores)', 'bool', False, P, 'Pro: Auto Upgrades (first affordable upgrade in the game Build menu list)',
       'Every 30 min upgrades one affordable hero equipment at the Blacksmith (spends ores).',
       widget="pro_widgets['AUTO_UPGRADE_EQUIPMENT']", saved_by='update_pro_features'),
    _s('BB_AUTO_UPGRADE', 'Builder Base buildings, Battle Machine/Copter and walls (on BB visits)', 'bool', False, P, 'Pro: Auto Upgrades (first affordable upgrade in the game Build menu list)',
       'On Builder Base visits starts affordable BB building/hero/wall upgrades.', depends_on=BB_VISITS,
       widget="pro_widgets['BB_AUTO_UPGRADE']", saved_by='update_pro_features'),
    _s('BB_AUTO_LAB', 'Builder Base Star Laboratory (on BB visits)', 'bool', False, P, 'Pro: Auto Upgrades (first affordable upgrade in the game Build menu list)',
       'On Builder Base visits starts an affordable Star Laboratory upgrade.', depends_on=BB_VISITS,
       widget="pro_widgets['BB_AUTO_LAB']", saved_by='update_pro_features'),
    # Ranked Battles
    _s('RANKED_ATTACKS_ENABLED', 'Attack in Ranked Battle tournaments (uses the tournament attacks, no loot)', 'bool', False, P, 'Pro: Ranked Battles',
       'When a ranked tournament is running and attacks remain, attacks via the Ranked card (strategy = RANKED_ATTACK_STRATEGY or SELECTED_ATTACK_STRATEGY).',
       widget="pro_widgets['RANKED_ATTACKS_ENABLED']", saved_by='update_pro_features'),
    _s('RANKED_MAX_PER_DAY', 'Ranked attacks per day at most', 'int', 14, P, 'Pro: Ranked Battles',
       'Daily cap on ranked attacks made by the bot (counter resets at local midnight).',
       depends_on='RANKED_ATTACKS_ENABLED', min=1, max=14, step=1,
       widget="pro_widgets['RANKED_MAX_PER_DAY']", saved_by='update_pro_features'),
    # Clan Donations
    _s('DONATE_ENABLED', 'Donate to clan requests (checked every 5 minutes)', 'bool', False, P, 'Pro: Clan Donations',
       'Every 5 min opens clan chat and fills requests with the troops/spells listed in DONATE_TROOPS.',
       widget="pro_widgets['DONATE_ENABLED']", saved_by='update_pro_features',
       notes='no effect while DONATE_TROOPS is empty'),
    _s('DONATE_TROOPS', 'What to donate, e.g. troop_edragon:1, troop_balloon:5, spell_rage:1', 'text', '', P, 'Pro: Clan Donations',
       "Comma list of 'tab_key:count' (count defaults to 1, min 1) to donate per request.",
       depends_on='DONATE_ENABLED', widget="pro_widgets['DONATE_TROOPS']", saved_by='update_pro_features',
       notes="row label shown as 'What to donate', full text as placeholder (Q14)"),
    # Clan Capital
    _s('CAPITAL_RAIDS_ENABLED', 'Use Clan Capital raid attacks during raid weekends (checked every 4 h)', 'bool', False, P, 'Pro: Clan Capital',
       'Every 4 h checks for a raid weekend and uses Clan Capital raid attacks.',
       widget="pro_widgets['CAPITAL_RAIDS_ENABLED']", saved_by='update_pro_features'),
    _s('CAPITAL_MAX_RAIDS', 'Raid attacks per visit', 'int', 6, P, 'Pro: Clan Capital',
       'Maximum raid attacks attempted per capital visit.', depends_on='CAPITAL_RAIDS_ENABLED',
       min=1, max=6, step=1, widget="pro_widgets['CAPITAL_MAX_RAIDS']", saved_by='update_pro_features'),
    # Schedule
    _s('SCHED_ACTIVE_HOURS_ENABLED', 'Only play between the hours below (CoC is closed outside them)', 'bool', False, P, 'Pro: Schedule',
       'Outside START..END hours closes Clash of Clans and idles until the start hour.',
       widget="pro_widgets['SCHED_ACTIVE_HOURS_ENABLED']", saved_by='update_pro_features'),
    _s('SCHED_START_HOUR', 'Start hour (0-23)', 'int', 8, P, 'Pro: Schedule',
       'Local hour at which play starts.', depends_on='SCHED_ACTIVE_HOURS_ENABLED', min=0, max=23, step=1,
       widget="pro_widgets['SCHED_START_HOUR']", saved_by='update_pro_features', notes='start==end means always (Q20)'),
    _s('SCHED_END_HOUR', 'End hour (0-23, may be past midnight)', 'int', 23, P, 'Pro: Schedule',
       'Local hour at which play stops (exclusive); may be earlier than start to wrap midnight.',
       depends_on='SCHED_ACTIVE_HOURS_ENABLED', min=0, max=23, step=1,
       widget="pro_widgets['SCHED_END_HOUR']", saved_by='update_pro_features'),
    _s('SCHED_BREAKS_ENABLED', 'Take random breaks (closes CoC, like putting the phone away)', 'bool', False, P, 'Pro: Schedule',
       'After a random play period closes CoC for a random break length, then relaunches.',
       widget="pro_widgets['SCHED_BREAKS_ENABLED']", saved_by='update_pro_features'),
    _s('SCHED_BREAK_EVERY_MIN', 'Break every ... minutes, from', 'int', 40, P, 'Pro: Schedule',
       'Lower bound (minutes) of random play time between breaks.', depends_on='SCHED_BREAKS_ENABLED',
       min=10, max=600, step=5, widget="pro_widgets['SCHED_BREAK_EVERY_MIN']", saved_by='update_pro_features'),
    _s('SCHED_BREAK_EVERY_MAX', '... to', 'int', 90, P, 'Pro: Schedule',
       'Upper bound (minutes) of random play time between breaks.', depends_on='SCHED_BREAKS_ENABLED',
       min=10, max=600, step=5, widget="pro_widgets['SCHED_BREAK_EVERY_MAX']", saved_by='update_pro_features'),
    _s('SCHED_BREAK_LENGTH_MIN', 'Break length in minutes, from', 'int', 5, P, 'Pro: Schedule',
       'Lower bound (minutes) of a break.', depends_on='SCHED_BREAKS_ENABLED',
       min=1, max=240, step=1, widget="pro_widgets['SCHED_BREAK_LENGTH_MIN']", saved_by='update_pro_features'),
    _s('SCHED_BREAK_LENGTH_MAX', '... to', 'int', 15, P, 'Pro: Schedule',
       'Upper bound (minutes) of a break.', depends_on='SCHED_BREAKS_ENABLED',
       min=1, max=240, step=1, widget="pro_widgets['SCHED_BREAK_LENGTH_MAX']", saved_by='update_pro_features'),
    # End Conditions
    _s('END_CONDITIONS_ENABLED', 'Stop the bot when one of these targets is reached', 'bool', False, P, 'Pro: End Conditions (0 = off)',
       'Stops the bot (END_CONDITION) as soon as any non-zero target below is reached.',
       widget="pro_widgets['END_CONDITIONS_ENABLED']", saved_by='update_pro_features'),
    _s('END_AFTER_ATTACKS', 'After this many attacks', 'int', 0, P, 'Pro: End Conditions (0 = off)',
       'Stop after this many attacks this session (0 = off; BB-only battles count).', depends_on='END_CONDITIONS_ENABLED',
       min=0, max=10_000, step=10, widget="pro_widgets['END_AFTER_ATTACKS']", saved_by='update_pro_features'),
    _s('END_AFTER_HOURS', 'After this many hours', 'int', 0, P, 'Pro: End Conditions (0 = off)',
       'Stop after this many hours (0 = off).', depends_on='END_CONDITIONS_ENABLED',
       min=0, max=168, step=1, widget="pro_widgets['END_AFTER_HOURS']", saved_by='update_pro_features',
       notes='counted from app launch, not from Start (Q21)'),
    _s('END_AFTER_GOLD', 'After gaining this much gold', 'int', 0, P, 'Pro: End Conditions (0 = off)',
       'Stop once gold gained this session reaches this (0 = off).', depends_on='END_CONDITIONS_ENABLED',
       min=0, max=2_000_000_000, step=1_000_000, widget="pro_widgets['END_AFTER_GOLD']", saved_by='update_pro_features'),
    _s('END_AFTER_ELIXIR', 'After gaining this much elixir', 'int', 0, P, 'Pro: End Conditions (0 = off)',
       'Stop once elixir gained this session reaches this (0 = off).', depends_on='END_CONDITIONS_ENABLED',
       min=0, max=2_000_000_000, step=1_000_000, widget="pro_widgets['END_AFTER_ELIXIR']", saved_by='update_pro_features'),
    _s('END_AFTER_DARK', 'After gaining this much dark elixir', 'int', 0, P, 'Pro: End Conditions (0 = off)',
       'Stop once dark elixir gained this session reaches this (0 = off).', depends_on='END_CONDITIONS_ENABLED',
       min=0, max=100_000_000, step=10_000, widget="pro_widgets['END_AFTER_DARK']", saved_by='update_pro_features'),
    # Helper Hut
    _s('HELPER_HUT_ENABLED', 'Assign the Builder Apprentice and Lab Assistant to the longest upgrade (every 2-4 h)', 'bool', False, P, 'Pro: Helper Hut',
       'Every random 2-4 h opens the Helper Hut and assigns the enabled helpers to the longest running upgrade.',
       widget="pro_widgets['HELPER_HUT_ENABLED']", saved_by='update_pro_features'),
    _s('HELPER_APPRENTICE', 'Builder Apprentice', 'bool', True, P, 'Pro: Helper Hut',
       'Assign the Builder Apprentice.', depends_on='HELPER_HUT_ENABLED',
       widget="pro_widgets['HELPER_APPRENTICE']", saved_by='update_pro_features'),
    _s('HELPER_LAB_ASSISTANT', 'Lab Assistant', 'bool', True, P, 'Pro: Helper Hut',
       'Assign the Lab Assistant.', depends_on='HELPER_HUT_ENABLED',
       widget="pro_widgets['HELPER_LAB_ASSISTANT']", saved_by='update_pro_features'),
    # Super Troops
    _s('SUPER_TROOP_ENABLED', 'Keep Super Troops boosted (checked every 6 hours)', 'bool', False, P, 'Pro: Super Troops',
       'Every 6 h opens the Super Troop barrel and boosts the listed troops that are not active.',
       widget="pro_widgets['SUPER_TROOP_ENABLED']", saved_by='update_pro_features',
       notes='no effect while SUPER_TROOPS is empty'),
    _s('SUPER_TROOPS', 'Troops to boost (max 2), e.g. sneaky_goblin, super_wall_breaker', 'text', '', P, 'Pro: Super Troops',
       'Comma list of super troop names (lower-cased, spaces -> underscores), at most 2 used.',
       depends_on='SUPER_TROOP_ENABLED', widget="pro_widgets['SUPER_TROOPS']", saved_by='update_pro_features',
       notes="row label shown as 'Troops to boost (max 2)' (Q14)"),
    _s('SUPER_TROOP_USE_POTION', 'Use a Super Potion instead of dark elixir when available', 'bool', False, P, 'Pro: Super Troops',
       'Boost with a Super Potion when one is available instead of paying dark elixir.',
       depends_on='SUPER_TROOP_ENABLED', widget="pro_widgets['SUPER_TROOP_USE_POTION']", saved_by='update_pro_features'),
    # XP Farming
    _s('XP_FARMING', 'Attack every base regardless of loot (experience farming; combine with End Battle Early)', 'bool', False, P, 'Pro: XP Farming',
       'Attacks the first base found, bypassing the Min Gold/Elixir/Dark filter.',
       widget="pro_widgets['XP_FARMING']", saved_by='update_pro_features'),
    # End Battle Early
    _s('END_BATTLE_ENABLED', 'End battles early once all troops are deployed', 'bool', False, P, 'Pro: End Battle Early (0 = off)',
       'After deployment, checks every 2 s and taps End Battle/Surrender when a non-zero condition below is met.',
       widget="pro_widgets['END_BATTLE_ENABLED']", saved_by='update_pro_features'),
    _s('END_BATTLE_STARS', 'When this many stars are reached', 'int', 0, P, 'Pro: End Battle Early (0 = off)',
       'End the battle once this many stars are earned (0 = off).', depends_on='END_BATTLE_ENABLED',
       min=0, max=3, step=1, widget="pro_widgets['END_BATTLE_STARS']", saved_by='update_pro_features'),
    _s('END_BATTLE_DAMAGE', 'When damage reaches this percent', 'int', 0, P, 'Pro: End Battle Early (0 = off)',
       'End the battle once destruction reaches this percent (0 = off).', depends_on='END_BATTLE_ENABLED',
       min=0, max=100, step=5, widget="pro_widgets['END_BATTLE_DAMAGE']", saved_by='update_pro_features'),
    _s('END_BATTLE_NO_CHANGE_SECONDS', 'When damage and loot stop changing for this many seconds', 'int', 0, P, 'Pro: End Battle Early (0 = off)',
       'End the battle when damage and loot have not changed for this many seconds (0 = off).',
       depends_on='END_BATTLE_ENABLED', min=0, max=180, step=5,
       widget="pro_widgets['END_BATTLE_NO_CHANGE_SECONDS']", saved_by='update_pro_features'),

    # ------------------------------------------------------------------ Multi Village page (GLOBAL)
    _s('MULTI_VILLAGE_ENABLED', 'Enable Multi Village', 'bool', False, G, 'Multi Village: Multi Village',
       'Rotates between calibrated CoC accounts (profiles); at Start calibrates profiles if needed, then loads each profile config on switch.',
       widget='multi_enabled', saved_by='update_multi',
       notes='unticking resets current_profile to GLOBAL and reloads GUI (Q19); mode label MULTI VILLAGE/GLOBAL MODE'),
    _s('START_PROFILE', 'Start Profile', 'choice', '', G, 'Multi Village: Village Settings',
       'Enabled profile the bot switches to first at Start.', depends_on='MULTI_VILLAGE_ENABLED',
       choices_source=PROFILE_NAMES_SOURCE, widget='start_profile', saved_by='update_multi',
       notes="saved as the combo text ('' when no enabled profile); rename_profile updates it"),
    _s('VILLAGE_COUNT', 'Village Count', 'int', 5, G, 'Multi Village: Village Settings',
       'Number of accounts to calibrate; at Start, re-calibrates when larger than the calibrated profile count.',
       depends_on='MULTI_VILLAGE_ENABLED', min=1, max=100, step=1, widget='village_count', saved_by='update_multi',
       notes='saved as min(100, value); UI fallback 10 (Q11)'),
    _s('VILLAGE_SWITCH_MINUTES', 'Switch Every (min)', 'int', 10, G, 'Multi Village: Village Settings',
       'Minutes on a village before switching to the next enabled profile (minimum play time with Switch when Builders Busy).',
       depends_on=['MULTI_VILLAGE_ENABLED', ('SWITCH_ON_LOOT_FULL', False)], min=1, max=1440, step=1,
       widget='switch_minutes', saved_by='update_multi', notes='disabled in UI while SWITCH_ON_LOOT_FULL (Q17); backend fallback 30'),
    _s('SWITCH_ON_LOOT_FULL', 'Switch on Loot Full', 'bool', False, G, 'Multi Village: Village Settings',
       'Switch village only when all storages are full; the bot STOPS when every enabled profile has been full.',
       depends_on='MULTI_VILLAGE_ENABLED', widget='switch_on_loot_full', saved_by='update_multi (via _on_switch_on_loot_full_changed)',
       notes="tooltip: 'Bot will STOP when all profiles have full loot'"),
    _s('SWITCH_ON_BUILDERS_BUSY', 'Switch when Builders Busy', 'bool', False, G, 'Multi Village: Village Settings',
       'Switch village once every builder is working and Switch Every minutes have passed.',
       depends_on=['MULTI_VILLAGE_ENABLED', ('SWITCH_ON_LOOT_FULL', False)], widget='switch_on_builders_busy',
       saved_by='update_multi', notes='saved to GLOBAL file but not in GLOBAL_KEYS -> leaks into profiles (Q3)'),

    # ------------------------------------------------------------------ per-profile popup (pencil icon)
    _s('PROFILE_MATCH_THRESHOLD', 'Match Threshold', 'float', 0.92, P, 'Multi Village: Profiles list -> pencil popup "Profile Settings"',
       'Template-match score needed to find this account\'s card on the Supercell ID profile screen when switching.',
       min=0.5, max=1.0, step=0.01, widget='QDoubleSpinBox in _open_profile_match_threshold_popup',
       saved_by='_open_profile_match_threshold_popup (save to the clicked profile, not current_profile)',
       notes='2 decimals; rounded to 2 on save; UI fallback 0.9 (Q4)'),

    # ------------------------------------------------------------------ Settings drawer (GLOBAL)
    _s('EMULATOR_SELECTION', 'Emulator', 'choice', 'bluestacks', G, 'Settings drawer (nav panel bottom)',
       'Emulator preset: drives launch/restart/process detection and the default ADB port.',
       choices=[(k, d) for k, d, _p in EMULATOR_CHOICES], widget='emulator_select',
       saved_by='_save_emulator_global_settings (via _on_emulator_changed)',
       notes='must also call startup.set_selected_emulator + adb.set_emulator (Q6); changing it resets EMULATOR_PORT to the preset default (Q16)'),
    _s('EMULATOR_IP', 'Emulator IP', 'text', '127.0.0.1', G, 'Settings drawer (nav panel bottom)',
       'Host part of the ADB target (host:port).', widget='emulator_ip_input',
       saved_by='_save_emulator_global_settings (via _on_emulator_ip_changed)',
       notes="empty -> '127.0.0.1'; must call adb.set_host (Q6)"),
    _s('EMULATOR_PORT', 'ADB Port', 'text', '5556', G, 'Settings drawer (nav panel bottom)',
       'Port part of the ADB target; digits only.', widget='adb_port_input',
       saved_by='_save_emulator_global_settings (via _on_adb_port_changed)',
       notes='stored as a string; non-digit text ignored; must call adb.set_port (Q6, Q16)'),
]

# Keys that live in config files but have no control in the old UI (do not drop them on save).
BACKEND_ONLY_KEYS = [
    {'key': 'CLAN_CAPITAL', 'default': False, 'note': 'written False by update_general; unused'},
    {'key': 'WALL_MIN_GOLD', 'default': 3_000_000, 'note': 'defaults.py, auto-filled, unused'},
    {'key': 'WALL_MIN_ELIXIR', 'default': 3_000_000, 'note': 'defaults.py, auto-filled, unused'},
    {'key': 'TEMPLATES_DIR', 'default': 'templates', 'note': 'auto-filled, but code reads defaults.TEMPLATES_DIR'},
    {'key': 'RANKED_ATTACK_STRATEGY', 'default': None, 'note': 'ranked.py strategy override, falls back to SELECTED_ATTACK_STRATEGY'},
    {'key': 'HELPER_HUT_POS', 'default': None, 'note': '[x, y] Helper Hut tap position override (helperhut.py)'},
    {'key': 'CG_DISABLED_CHALLENGES', 'default': [], 'note': 'list maintained by clangames.py in the profile config'},
]


def _u(name, kind, what, implemented_by, how_to_call):
    return {'name': name, 'kind': kind, 'what': what, 'implemented_by': implemented_by,
            'how_to_call': how_to_call}


NON_SETTING_UI = [
    # ------------------------------------------------------------------ app / window
    _u('App bootstrap', 'lifecycle',
       'Sets Windows AppUserModelID, QApplication name "ACBot Basic", icon, creates runtime dirs, cleans stale onefile temp dirs, shows MainWindow; on exit terminates child processes except emulator processes, then os._exit.',
       'ui/gui.py run(), bootstrap_external_ui2_data(), get_app_icon()',
       "Keep gui.bootstrap_external_ui2_data() before importing; call utils.runtime_paths.ensure_runtime_dirs(), cleanup_stale_onefile_tempdirs(); on exit reuse the psutil child cleanup that keeps startup.EMULATOR_CONFIGS[*]['process_names'] alive."),
    _u('Window title', 'live display',
       "'ACBot Basic v1.6.7 | <Emulator display>:<port>' refreshed every 1 s.",
       'MainWindow._update_window_title, title_timer (1000 ms)',
       'from utils.update_checker import APP_NAME, APP_VERSION; title = f"{APP_NAME} v{APP_VERSION}" + f" | {emulator_display}:{port}"'),
    _u('Window geometry persistence', 'persistence',
       "Saves x/y/width/height to <writable>/bot.config['window_state'] (debounced 250 ms on move/resize, and on close); restores on launch if >=700x500 and on a visible screen. Old window is fixed 1000x650.",
       'MainWindow._load_bot_config/_save_bot_config/_restore_window_state_from_bot_config/_save_window_state_to_bot_config/_schedule_window_state_save, resizeEvent, moveEvent',
       "Read/merge JSON at utils.runtime_paths.resolve_writable_path('bot.config'); keep other top-level keys (startup.py stores 'emulator_config_state' in the same file)."),
    _u('Close window', 'lifecycle', 'Stops a running worker (BotWorker.stop) and saves window state.',
       'MainWindow.closeEvent', 'if worker.isRunning(): worker.stop(); then save window state.'),
    _u('Fonts/theme', 'appearance', 'Loads Bangers (titles), Inter Regular/Bold (UI) from assets/, dark QSS, bg.png background.',
       'MainWindow.__init__ (QFontDatabase.addApplicationFont, setStyleSheet)', "utils.runtime_paths.resolve_resource_path('assets/<file>')"),
    _u('Enter / Return shortcut', 'shortcut',
       'Sets BotControl.enter_pressed = True (consumed by BotControl.wait_for_enter, the console fallback for prompts).',
       'MainWindow.handle_enter, enter_shortcut, enter_shortcut2', 'control.BotControl.enter_pressed = True'),

    # ------------------------------------------------------------------ navigation
    _u('Page navigation', 'navigation',
       "Six checkable nav buttons: 'General', 'Attack Army', 'Pro Features', 'Multi Village', 'Statistics', 'Log'.",
       'MainWindow.switch_page(name), self.buttons, self.pages, self.stack', 'UI-only; no backend call.'),
    _u('Settings drawer toggle', 'navigation',
       "'Settings ▸/▾' button at the bottom of the nav panel slides a 196 px drawer with Emulator / Emulator IP / ADB Port.",
       'MainWindow._toggle_settings_drawer, _position_settings_drawer, settings_drawer_anim', 'UI-only.'),

    # ------------------------------------------------------------------ bot control (bottom bar)
    _u('Start button', 'button',
       'Starts the BotWorker QThread (or resumes it if already running); disables all settings pages except Log/Statistics, the profile list, emulator/IP/port inputs, Delete All Profiles; unlocks Pause/Stop.',
       'MainWindow.start_bot, start_btn (#StartBtn)',
       'if not worker.isRunning(): worker.start()  else: worker.resume(); then lock settings (set_controls_enabled(False)). Worker must exist with control.BotControl.worker = worker.'),
    _u('Pause / Resume button', 'button',
       "Toggles pause: text 'I I' when running, '▶' when paused. Ignored while locked (bot not started).",
       'MainWindow.pause_bot via guard_button(pause_btn, ...), pause_btn (#PauseBtn), property locked',
       'if control.BotControl.paused: worker.resume() else: worker.pause()   (worker.pause/resume also pause the Stats runtime clock and emit status)'),
    _u('Stop button', 'button',
       "Stops the bot (blocks the GUI up to ~7 s while the thread winds down), re-enables controls, resets the profile timer, refreshes the profile list, status 'Stopped'. Ignored while locked.",
       'MainWindow.stop_bot via guard_button(stop_btn, ...), stop_btn (#StopBtn)',
       'worker.stop()  # sets BotControl.running=False, waits 6 s, terminate() as last resort; then unlock settings (set_controls_enabled(True)). Better: run stop off the GUI thread or wait on worker.finished.'),
    _u('Lock settings while running', 'behaviour',
       "Disables every page except 'Log' and 'Statistics' while the bot runs.",
       'MainWindow.set_controls_enabled(enabled)', 'UI-only; pair with start_bot/stop_bot (and ideally with the worker emitting Stopped, see Q23).'),
    _u('Status label', 'live display',
       "Bottom-bar text: 'Idle' / 'Running' / 'Paused' / 'Stopped' from the worker, plus transient 'Loaded <p> config', 'Cleared active profile' (reset to 'Idle' after 3 s).",
       'MainWindow.status, handle_worker_status(status)', 'worker.status.connect(handler)  # str'),
    _u('Mode label', 'live display', "'MULTI VILLAGE' when MULTI_VILLAGE_ENABLED is ticked, else 'GLOBAL MODE'.",
       'MainWindow.mode_label, update_mode_label', 'Derive from the MULTI_VILLAGE_ENABLED widget/config.'),
    _u('License label', 'live display', "Static 'License: Pro (local build)'.",
       'MainWindow.key_status_label, update_key_status_label', 'Static text; no licensing backend exists.'),

    # ------------------------------------------------------------------ BotWorker signals
    _u('BotWorker.status signal', 'signal',
       "Emits 'Running' (start/resume), 'Paused', 'Stopped' (stop or thread end). Old UI shows it in the status label AND appends it to the log.",
       'ui/bot_worker.BotWorker.status = Signal(str) -> MainWindow.handle_worker_status, MainWindow.append_log',
       "worker.status.connect(on_status); on 'Stopped' reset profile timer to '--:--' and refresh the profile list."),
    _u('BotWorker.config_changed signal', 'signal',
       "Payload {'cfg': merged_config_dict, 'profile': name_or_None}; emitted by the bot at calibration end and every profile switch (and by deselect_active_profile). UI sets current_profile, refreshes the profile list, applies cfg to all widgets, sets the active-profile label ('GLOBAL' when None).",
       'BotWorker.config_changed = Signal(dict); control.BotControl.emit_config(cfg, profile) -> MainWindow.handle_config_update(payload)',
       "worker.config_changed.connect(on_config); never save back in response (old UI did, see Q22)."),
    _u('BotWorker.prompt_continue signal / continue popup', 'signal + popup',
       "Bot blocks in BotControl.wait_for_continue(title, msg) until the user confirms. Title 'Profile Calibration' -> modal 260x210 dialog with message, 'Show/Hide calibration help' link revealing assets/profile_guide.png, and a 'Continue' button; any other title -> information QMessageBox whose OK button reads 'Continue'. Closing the dialog in any way continues.",
       'BotWorker.prompt_continue = Signal(str, str) -> MainWindow.show_continue_popup(title, message)',
       'worker.prompt_continue.connect(show_popup); after the dialog closes ALWAYS call control.BotControl.continue_clicked().'),
    _u('BotWorker lifecycle details', 'backend',
       "run(): BotControl.running=True, paused=False, resets main.profile_loot_status, creates stats.Stats(), prunes logs older than 7 days, tees stdout/stderr to <writable>/logs/log-YYYY-MM-DD_HH-MM.txt, runs main.main(stats) with auto-recovery (emulator restart up to 3x/30 min on adb.DeviceLostError; restart flow up to 5x/30 min on other errors), emits 'Stopped' at the end.",
       'ui/bot_worker.BotWorker (QThread): start(), pause(), resume(), stop(), attributes stats, log_path, ui_stdout, ui_stderr',
       'worker = BotWorker(); control.BotControl.worker = worker  # construct AFTER sys.stdout is redirected to the log sink, because the worker captures sys.stdout in __init__.'),

    # ------------------------------------------------------------------ log
    _u('Log view', 'live display',
       "Read-only Consolas 12 no-wrap text view; every print() in the process (GUI + bot) arrives as '[HH:MM:SS] text' and is shown as 'HH:MM:SS | TAG        | message' where TAG is a leading '[TAG]' (else 'LOG'); auto-scrolls to bottom.",
       'MainWindow.log_view, LogRedirect (text_written Signal(str)), MainWindow.append_log(text)',
       'sink = LogRedirect(); sink.text_written.connect(append_log); sys.stdout = sink  # before creating BotWorker. Also connect worker.status to append_log to log state changes.'),
    _u('Session log file', 'backend', 'Every session is also written to <writable>/logs/log-YYYY-MM-DD_HH-MM.txt (7-day retention).',
       'BotWorker.run, BotWorker._prune_old_logs(keep_days=7), BotWorker.log_path',
       "worker.log_path holds the current file; resolve_writable_path('logs') is the folder (useful for an 'Open logs' button)."),

    # ------------------------------------------------------------------ statistics (refreshed every 1 s from main.GLOBAL_STATS)
    _u('Statistics refresh', 'timer', 'Every 1 s copies main.GLOBAL_STATS (a stats.Stats set by main.main once the game is ready) into the labels below; nothing shown until it exists.',
       'MainWindow.refresh_statistics, stats_timer (1000 ms)', "stats = getattr(main, 'GLOBAL_STATS', None)  # or worker.stats"),
    _u('Stat: Runtime', 'statistic', "Session runtime excluding paused time, 'HH:MM:SS'.", 'stats_runtime <- Stats.elapsed_hhmmss()', 'stats.elapsed_hhmmss()  (raw: stats.elapsed_seconds)'),
    _u('Stat: Total Attacks', 'statistic', 'Attacks this session (includes BB-only battles).', 'stats_attacks <- Stats.total_attacks', 'str(stats.total_attacks)'),
    _u('Stat: Gold gained', 'statistic', 'Gold gained this session, thousands-separated.', 'stats_gold <- Stats.gold_gained', "f'{stats.gold_gained:,}'"),
    _u('Stat: Gold per hour', 'statistic', "Gold/hour (cached, recomputed at most once a minute after battles), shown as 'N / hr'.", 'stats_gold_hr <- Stats._cached_gold_hr', "f'{stats._cached_gold_hr:,} / hr'"),
    _u('Stat: Elixir gained', 'statistic', 'Elixir gained this session.', 'stats_elixir <- Stats.elixir_gained', "f'{stats.elixir_gained:,}'"),
    _u('Stat: Elixir per hour', 'statistic', 'Elixir/hour (cached).', 'stats_elixir_hr <- Stats._cached_elixir_hr', "f'{stats._cached_elixir_hr:,} / hr'"),
    _u('Stat: Dark elixir gained', 'statistic', 'Dark elixir gained this session.', 'stats_dark <- Stats.dark_gained', "f'{stats.dark_gained:,}'"),
    _u('Stat: Dark elixir per hour', 'statistic', 'Dark elixir/hour (cached).', 'stats_dark_hr <- Stats._cached_dark_hr', "f'{stats._cached_dark_hr:,} / hr'"),
    _u('Stat: 0-star attacks', 'statistic', 'Count of 0-star attacks (icon 0star.png).', 'stats_0 <- Stats.stars_0', 'str(stats.stars_0)'),
    _u('Stat: 1-star attacks', 'statistic', 'Count of 1-star attacks.', 'stats_1 <- Stats.stars_1', 'str(stats.stars_1)'),
    _u('Stat: 2-star attacks', 'statistic', 'Count of 2-star attacks.', 'stats_2 <- Stats.stars_2', 'str(stats.stars_2)'),
    _u('Stat: 3-star attacks', 'statistic', 'Count of 3-star attacks.', 'stats_3 <- Stats.stars_3', 'str(stats.stars_3)'),
    _u('Stat: Walls upgraded', 'statistic', 'Wall segments upgraded this session (icon wallsupgraded.png).', 'stats_walls <- Stats.walls_upgraded', 'str(stats.walls_upgraded)'),
    _u('Stat (unused by old UI): troops/spells donated', 'statistic', 'Stats has troops_donated and spells_donated counters the old UI never displayed.',
       'Stats.troops_donated, Stats.spells_donated', 'stats.troops_donated, stats.spells_donated'),

    # ------------------------------------------------------------------ attack army helpers
    _u('Army composition suggestion', 'live display', 'Read-only text under the strategy combo describing the army for the selected strategy (STRATEGY_HELP above).',
       'MainWindow.strategy_info, MainWindow.strategy_help', 'Look up STRATEGY_HELP[strategy_key] on strategy change.'),
    _u('CSV script list', 'data source', 'Populates the Custom Script and War script combos once at build time.',
       'attack.csv_script.list_scripts() in MainWindow.__init__', 'from attack.csv_script import list_scripts, scripts_dir; list_scripts()  # consider a Refresh button; scripts_dir() gives the folder'),
    _u('CSV/war script enablement', 'behaviour', 'CSV script + red line widgets are enabled only when strategy == csv; war script only when war strategy == csv.',
       'lambdas on strategy.currentIndexChanged; _load_pro_features/update_pro_features (war_script.setEnabled)', 'UI-only (see depends_on in SETTINGS).'),
    _u('Locked strategy paywall (vestigial)', 'behaviour', 'LOCKED_STRATEGIES is empty; helpers grey out locked combo items with tooltip "Available in paid edition".',
       'LOCKED_STRATEGIES, MainWindow._apply_locked_strategy_items, _set_combo_item_enabled', 'Not needed in a new UI.'),

    # ------------------------------------------------------------------ multi village / profiles
    _u('Profile list', 'list',
       "Shows '<n>. <name>' rows for ProfileManager.list_profiles() (order = key order of profiles/active_profiles.json). Checkbox = profile enabled for rotation; drag-and-drop reorders; styles: active profile gold bold 14pt, enabled white, disabled grey. Enabled only while MULTI_VILLAGE_ENABLED; disabled while running.",
       'MainWindow.profile_list (QListWidget + ProfileListDelegate), refresh_profile_list, refresh_profile_styles',
       "from profiles.profile_manager import ProfileManager; ProfileManager(None).list_profiles(); enabled flags from json.load(open(resolve_writable_path('profiles/active_profiles.json')))['profiles']"),
    _u('Enable/disable or reorder profile', 'profile action',
       "Toggling a checkbox or dragging a row rewrites profiles/active_profiles.json as {'profiles': {name: bool, ...}} in list order, then refreshes the Start Profile dropdown and styles.",
       'MainWindow.save_profile_order (connected to itemChanged and model().rowsMoved)',
       "json.dump({'profiles': {name: enabled for name in ordered_names}}, open(resolve_writable_path('profiles/active_profiles.json'), 'w'), indent=2)  # order matters: bot rotates in this order (ProfileManager.get_enabled_profiles)"),
    _u('Load profile config', 'profile action',
       "Double-click a row or click its gear icon (⚙): current_profile = name, all widgets show ConfigManager.load(name) (merged), active label = name, Deselect enabled, status 'Loaded <name> config'. Subsequent edits save into that profile.",
       'MainWindow.load_profile(name); eventFilter (gear rect from ProfileListDelegate.tool_rects)',
       'cfg = ConfigManager().load(name); apply to widgets with signals blocked; remember current_profile = name'),
    _u('Edit profile popup (rename + match threshold)', 'popup',
       "Pencil icon (✏️) opens frameless 'Profile Settings' popup: Profile Name line edit + Match Threshold (0.50-1.00) + Cancel/Save. Save renames (sanitized: lower-case, [a-z0-9 ] only, spaces->_) via ProfileManager.rename_profile (moves folder, updates order.txt, active_profiles.json, START_PROFILE) and writes PROFILE_MATCH_THRESHOLD to that profile.",
       'MainWindow._open_profile_match_threshold_popup(profile_name, global_pos); eventFilter',
       "ok, msg, new_name = ProfileManager(None).rename_profile(old, new)  # (bool, str, str); show msg on failure. Then c = ConfigManager().load(new_name); c['PROFILE_MATCH_THRESHOLD'] = round(v, 2); ConfigManager().save(c, new_name)"),
    _u('Profile list tooltips / click-empty', 'behaviour',
       "Tooltips: list 'Double-Click to load profile Config', pencil 'Click to edit profile name and match threshold', gear 'Click to edit profile'. Clicking empty space clears selection.",
       'MainWindow.eventFilter', 'UI-only.'),
    _u('Active profile display', 'live display', "Shows the profile currently loaded in the editor/bot ('None' initially, 'GLOBAL' after deselect or when the bot runs global).",
       'MainWindow.active_profile_label', 'Updated by load_profile, deselect_active_profile, handle_config_update.'),
    _u('Profile switch countdown', 'live display',
       "Every 1 s while running in multi-village with a switch done: 'MM:SS' remaining until switch (green; yellow < 30 s; red at 0); 'LOOT' (purple) when SWITCH_ON_LOOT_FULL; '--:--' otherwise.",
       'MainWindow.profile_timer_label, refresh_profile_timer, profile_refresh_timer (1000 ms)',
       "control.BotControl.running, main.active_config, main.active_profiles, main.last_profile_switch (epoch s); remaining = VILLAGE_SWITCH_MINUTES*60 - (time.time() - main.last_profile_switch). Old UI used the spinbox value; prefer main.active_config['VILLAGE_SWITCH_MINUTES']."),
    _u('Deselect Active Profile button', 'profile action',
       "current_profile = None, widgets show GLOBAL config, active label 'GLOBAL', button disabled, emits config_changed(cfg, None), status 'Cleared active profile'.",
       'MainWindow.deselect_active_profile, deselect_btn', 'cfg = ConfigManager().load(); apply to widgets; (old UI also called control.BotControl.emit_config(cfg, None))'),
    _u('Delete All Profiles button', 'profile action (destructive)',
       "After a Yes/No warning, deletes every sub-folder of <writable>/profiles (all profile configs + profile.png) and profiles/active_profiles.json + order.txt; keeps profiles/config.json (global). Then clears the list and deselects. Disabled while running.",
       'MainWindow.delete_all_profiles, delete_profiles_btn',
       "Confirm first; shutil.rmtree each dir in resolve_writable_path('profiles'); os.remove active_profiles.json and order.txt."),
    _u('Start Profile dropdown population', 'data source', 'Lists only enabled (checked) profiles; selects START_PROFILE if present.',
       'MainWindow.refresh_start_profile_dropdown, refresh_profile_list', 'Rebuild from the enabled profile list whenever it changes; signals blocked while rebuilding.'),
    _u('Profile calibration (bot side)', 'backend',
       'At Start with MULTI_VILLAGE_ENABLED, if active_profiles.json is missing or VILLAGE_COUNT > calibrated count, the bot opens the Supercell ID screen, prompts "Profile Calibration" via prompt_continue, OCRs and saves profile cards (profiles/<name>/profile.png + config.json), writes order.txt/active_profiles.json, then emits config_changed.',
       'profiles.profile_manager.ProfileManager.calibrate_profiles(village_count) called from main.main',
       'No direct UI call; to re-calibrate: raise VILLAGE_COUNT or Delete All Profiles, then Start.'),
    _u('Multi-village panel enablement', 'behaviour', 'Village Settings, Active Profile and Profiles boxes are enabled only while Enable Multi Village is ticked.',
       'MainWindow.update_multi_ui', 'UI-only.'),

    # ------------------------------------------------------------------ emulator runtime
    _u('Emulator settings live-apply', 'behaviour',
       'On change: emulator -> startup.set_selected_emulator(key), adb.set_emulator(key), port reset to preset default; IP -> adb.set_host(ip or 127.0.0.1); port (digits only) -> adb.set_port(port). Each saves EMULATOR_* to GLOBAL config. Disabled while running.',
       'MainWindow._on_emulator_changed(display_name, apply_default_port=True), _on_emulator_ip_changed, _on_adb_port_changed, _save_emulator_global_settings',
       "import startup, adb; startup.set_selected_emulator(key); adb.set_emulator(key); adb.set_host(ip); adb.set_port(port); c = ConfigManager().load(); c.update(EMULATOR_SELECTION=key, EMULATOR_IP=ip, EMULATOR_PORT=port); ConfigManager().save(c)"),
    _u('Emulator settings restore at launch', 'behaviour',
       'Reads EMULATOR_SELECTION/IP/PORT from GLOBAL config, selects the emulator WITHOUT resetting the port, pushes all three into startup/adb, then re-saves.',
       'MainWindow.__init__ (after bottom bar)', 'Same calls as live-apply, executed once at startup (Q6).'),
    _u('Emulator choices source', 'data source', 'Combo items = display names of startup.get_supported_emulators().',
       'MainWindow.emulator_display_to_key', '{startup.get_emulator_display_name(k): k for k in startup.get_supported_emulators()}; startup.get_default_adb_port(k)'),

    # ------------------------------------------------------------------ config <-> GUI plumbing
    _u('Config -> widgets loader', 'plumbing', 'Applies a (merged) config dict to every settings widget, with clamps (army slot 0..8, hero delay 1..15, air width 50..500).',
       'MainWindow.apply_config_to_gui(cfg), _load_pro_features(cfg), block_gui_signals(block)', 'Call with widget signals blocked to avoid write-back (see Q22).'),
    _u('Widgets -> config savers', 'plumbing',
       'Each change re-reads its whole group and saves: update_general / update_donations / update_attack_army / update_pro_features -> ConfigManager.save(cfg, current_profile); update_multi and _save_emulator_global_settings -> ConfigManager.save(cfg) (GLOBAL).',
       'MainWindow.update_general, update_donations, update_attack_army, update_pro_features, update_multi, _save_emulator_global_settings',
       'cm = ConfigManager(); cfg = cm.load(current_profile); cfg[KEY] = value; cm.save(cfg, current_profile)  # profile scope;  cfg = cm.load(); ...; cm.save(cfg)  # global scope'),
]


if __name__ == '__main__':
    from collections import Counter
    keys = [s['key'] for s in SETTINGS]
    assert len(keys) == len(set(keys)), 'duplicate keys'
    print('SETTINGS:', len(SETTINGS), dict(Counter(s['scope'] for s in SETTINGS)))
    print('by section:', dict(Counter(s['old_section'].split(':')[0] for s in SETTINGS)))
    print('BACKEND_ONLY_KEYS:', len(BACKEND_ONLY_KEYS))
    print('NON_SETTING_UI:', len(NON_SETTING_UI), dict(Counter(u['kind'] for u in NON_SETTING_UI)))
