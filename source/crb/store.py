# crb/store.py - reads and writes bot settings exactly the way the backend expects.
#
# ConfigManager keeps one global config.json (also the template for new accounts) and one config per
# account profile. Global keys always go to the global file; everything else goes to the account being
# edited (or the global file when no account is selected). Emulator settings are also pushed into the
# adb/startup modules right away, because the bot reads them from there, not from the config (Q6).
# UI-only preferences (theme, text size, window) live in bot.config under "crb_ui".
import json

from profiles.config_manager import ConfigManager
from utils.runtime_paths import resolve_writable_path

from crb import schema


class SettingsStore:
    def __init__(self):
        self.cm = ConfigManager()
        self.profile = None              # account being edited (None = global / single account)

    # ---------------------------------------------------------------- bot settings
    def load(self):
        return self.cm.load(self.profile)

    def get(self, key, cfg=None):
        cfg = cfg if cfg is not None else self.load()
        if key in cfg and cfg[key] is not None:
            return cfg[key]
        meta = schema.BY_KEY.get(key)
        return meta['default'] if meta else None

    def set(self, key, value):
        meta = schema.BY_KEY.get(key, {})
        value = self._coerce(meta, value)
        if key in schema.GLOBAL_KEYS:
            cfg = self.cm.load()
            cfg[key] = value
            self.cm.save(cfg)
        else:
            cfg = self.cm.load(self.profile)
            cfg[key] = value
            self.cm.save(cfg, self.profile)
        if key.startswith('EMULATOR_'):
            self.apply_emulator()
        return value

    @staticmethod
    def _coerce(meta, value):
        kind = meta.get('kind')
        if kind == 'int' and value is not None:
            value = int(value)
            if meta.get('min') is not None:
                value = max(meta['min'], value)
            if meta.get('max') is not None:
                value = min(meta['max'], value)
        elif kind == 'float' and value is not None:
            value = round(float(value), 2)
        elif kind == 'bool':
            value = bool(value)
        return value

    # ---------------------------------------------------------------- emulator (Q6, Q16)
    def apply_emulator(self):
        import adb
        import startup
        cfg = self.cm.load()
        key = str(cfg.get('EMULATOR_SELECTION') or 'bluestacks').strip().lower()
        if key not in startup.get_supported_emulators():
            key = 'bluestacks'
        ip = str(cfg.get('EMULATOR_IP') or '127.0.0.1').strip() or '127.0.0.1'
        port = str(cfg.get('EMULATOR_PORT') or startup.get_default_adb_port(key)).strip()
        startup.set_selected_emulator(key)
        adb.set_emulator(key)
        adb.set_host(ip)
        if port.isdigit():
            adb.set_port(port)
        return key, ip, port

    def set_emulator(self, key, reset_port=True):
        import startup
        cfg = self.cm.load()
        cfg['EMULATOR_SELECTION'] = key
        if reset_port:
            cfg['EMULATOR_PORT'] = startup.get_default_adb_port(key)
        self.cm.save(cfg)
        return self.apply_emulator()

    # ---------------------------------------------------------------- UI preferences (bot.config)
    @staticmethod
    def _bot_config_path():
        return resolve_writable_path('bot.config')

    def ui_prefs(self):
        try:
            data = json.loads(self._bot_config_path().read_text(encoding='utf-8'))
        except Exception:
            data = {}
        prefs = data.get('crb_ui') if isinstance(data, dict) else None
        out = {'scheme': 'night', 'text_scale': 1.0, 'reduce_motion': False, 'window': None,
               'last_page': 'dashboard'}
        if isinstance(prefs, dict):
            out.update(prefs)
        return out

    def save_ui_prefs(self, **changes):
        path = self._bot_config_path()
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
        prefs = data.get('crb_ui') if isinstance(data.get('crb_ui'), dict) else {}
        prefs.update(changes)
        data['crb_ui'] = prefs                # other keys (emulator_config_state, ...) are kept
        path.write_text(json.dumps(data, indent=2), encoding='utf-8')
