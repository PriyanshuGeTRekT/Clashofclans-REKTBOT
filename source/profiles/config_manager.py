# Reconstructed from Pyarmor-decrypted bytecode (profiles.config_manager, Python 3.10).
import json, os
from json import JSONDecodeError
import sys

if os.path.dirname(os.path.dirname(os.path.abspath(__file__))) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import defaults
from utils.runtime_paths import resolve_writable_path

# <app_root>/profiles  (global config: profiles/config.json; per-profile: profiles/<name>/config.json)
BASE_DIR = str(resolve_writable_path('profiles'))
GLOBAL_KEYS = [
    'MULTI_VILLAGE_ENABLED', 'VILLAGE_SWITCH_MINUTES', 'SWITCH_ON_LOOT_FULL', 'VILLAGE_COUNT',
    'START_PROFILE', 'EMULATOR_SELECTION', 'EMULATOR_IP', 'EMULATOR_PORT',
]
# Every UPPER_CASE public name in defaults.py that is not a global key
PROFILE_KEYS = [k for k in dir(defaults) if k.isupper() and not k.startswith('_') and k not in GLOBAL_KEYS]
DEBUG = False


def _safe_load_json(path, fallback=None):
    fb = fallback
    if fb is None:
        fb = {}
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            return json.load(f)
    except (JSONDecodeError, OSError, ValueError):
        return fb.copy() if isinstance(fb, dict) else fb


def _global_defaults():
    cfg = {}
    for key in GLOBAL_KEYS:
        cfg[key] = getattr(defaults, key, False)
    for key in PROFILE_KEYS:
        cfg[key] = getattr(defaults, key, False)
    return cfg


def _profile_defaults():
    # Profile defaults are seeded from the current global config.json (minus global-only keys)
    path = os.path.join(BASE_DIR, 'config.json')
    if os.path.exists(path):
        cfg = _safe_load_json(path, {})
    else:
        cfg = {}
    for key in GLOBAL_KEYS:
        cfg.pop(key, None)
    return cfg


class ConfigManager:
    def _ensure_global_defaults(self, cfg):
        data = cfg
        changed = False
        for key in GLOBAL_KEYS:
            if key not in data:
                data[key] = getattr(defaults, key, False)
                changed = True
        for key in PROFILE_KEYS:
            if key not in data:
                data[key] = getattr(defaults, key, False)
                changed = True
        return changed

    def _ensure_profile_defaults(self, cfg):
        data = cfg
        changed = False
        for key in GLOBAL_KEYS:
            if key in data:
                data.pop(key, None)
                changed = True
        for key in PROFILE_KEYS:
            if key not in data:
                data[key] = getattr(defaults, key, False)
                changed = True
        return changed

    def _global_path(self):
        os.makedirs(BASE_DIR, exist_ok=True)
        return os.path.join(BASE_DIR, 'config.json')

    def _profile_path(self, profile):
        folder = os.path.join(BASE_DIR, profile)
        os.makedirs(folder, exist_ok=True)
        return os.path.join(folder, 'config.json')

    def load(self, profile=None):
        name = profile
        global_path = self._global_path()
        if not os.path.exists(global_path):
            global_cfg = _global_defaults()
            self.save(global_cfg, None)
        else:
            global_cfg = _safe_load_json(global_path, _global_defaults())
            if not isinstance(global_cfg, dict):
                global_cfg = _global_defaults()
                self.save(global_cfg, None)
        if self._ensure_global_defaults(global_cfg):
            self.save(global_cfg, None)
        for key in global_cfg:
            if global_cfg[key] is None:
                global_cfg[key] = False
        if not name:
            if DEBUG:
                print(f'[CFG] Loading GLOBAL config{global_path}')
            return global_cfg
        profile_path = self._profile_path(name)
        if not os.path.exists(profile_path):
            profile_cfg = _profile_defaults()
            self.save(profile_cfg, name)
        else:
            profile_cfg = _safe_load_json(profile_path, _profile_defaults())
            if not isinstance(profile_cfg, dict):
                profile_cfg = _profile_defaults()
                self.save(profile_cfg, name)
        if self._ensure_profile_defaults(profile_cfg):
            self.save(profile_cfg, name)
        for key in profile_cfg:
            if profile_cfg[key] is None:
                profile_cfg[key] = False
        merged = global_cfg.copy()
        merged.update(profile_cfg)
        if DEBUG:
            print(f'[CFG] Loading PROFILE config: {name}{profile_path}')
        return merged

    def save(self, cfg, profile=None):
        name = profile
        if name:
            for key in GLOBAL_KEYS:
                cfg.pop(key, None)
        if name:
            path = self._profile_path(name)
            if DEBUG:
                print(f'[CFG] Saving PROFILE config: {name}{path}')
        else:
            path = self._global_path()
            if DEBUG:
                print(f'[CFG] Saving GLOBAL config{path}')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=2)

    def ensure_profile_config(self, profile):
        name = profile
        path = self._profile_path(name)
        if not os.path.exists(path):
            self.save(_profile_defaults(), name)
            return None
