# attack.scripted - named strategies backed by bundled CSV scripts (new module, Pro feature).
#
# The Pro strategies (Valkyrie + Quake, Super Minion + Quake, Super Barbarian, BArch / Goblin and
# Thrower) are written as MyBot-format scripts in CSV/Attack and run by attack.csv_script, so they get
# the red line, refused-tap redeploy and troop-bar handling of the CSV engine.
from attack import csv_script

STRATEGY_SCRIPTS = {
    'valkyrie': 'ACBot-Valkyrie Quake',
    'sminion': 'ACBot-SuperMinion Quake',
    'sbarb': 'ACBot-Super Barb',
    'barch': 'ACBot-BArch Goblin',
    'thrower': 'PHMOD-Thrower Smash',
}


class ScriptedStrategy:
    def __init__(self, script_name):
        self.script_name = script_name

    def run_attack(self, adb, vision, active_config=None):
        cfg = dict(active_config or {})
        cfg['CSV_ATTACK_SCRIPT'] = self.script_name
        return csv_script.run_attack(adb, vision, cfg)


def strategy_modules():
    return {key: ScriptedStrategy(name) for key, name in STRATEGY_SCRIPTS.items()}
