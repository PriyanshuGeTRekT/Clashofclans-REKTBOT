# Reconstructed from Pyarmor-decrypted bytecode disassembly (startup.dis.txt).
# ACBot Basic v1.6.7 - emulator discovery / one-time emulator config / adb server control.
import psutil
import subprocess
import time
import os
import re
import json
import shutil
import sys
from pathlib import Path
from utils.runtime_paths import resolve_resource_path, resolve_writable_path

_SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


def _run_subprocess(cmd, **A):
    if _SUBPROCESS_FLAGS:
        A.setdefault('creationflags', _SUBPROCESS_FLAGS)
    # FIX: no timeout here, so a wedged adb server hung the bot at "Starting ADB server" (10 Nov).
    A.setdefault('timeout', 30)
    try:
        return subprocess.run(cmd, **A)
    except subprocess.TimeoutExpired:
        print(f'[STARTUP] {" ".join(str(c) for c in cmd[-2:])} timed out')
        if cmd[-1:] == ['start-server']:
            _kill_adb_processes()
        return subprocess.CompletedProcess(cmd, 1, b'', b'')


def _kill_adb_processes():
    """Last resort for a hung adb server: end the adb.exe processes (they restart on demand)."""
    for proc in psutil.process_iter(['name']):
        if (proc.info.get('name') or '').lower() in ('adb.exe', 'adb'):
            try:
                proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass


BLUESTACKS_CONF = Path('C:\\ProgramData\\BlueStacks_nxt\\bluestacks.conf')
BOT_CONFIG_PATH = resolve_writable_path('bot.config')


def _adb_candidates():
    # Bundled adb first: Tools/adb (Windows release) or Tools/platform-tools (fetched by the launcher on
    # macOS / Linux / Windows), then the PATH (see _resolve_adb_path), then loose copies.
    exe = 'adb.exe' if os.name == 'nt' else 'adb'
    return [
        resolve_resource_path(f'Tools/adb/{exe}'),
        resolve_resource_path(f'Tools/platform-tools/{exe}'),
        resolve_resource_path(f'adb/{exe}'),
        resolve_resource_path(exe),
    ]


def _resolve_adb_path():
    candidates = _adb_candidates()
    for candidate in candidates[:2]:
        if candidate.exists():
            return str(candidate)
    on_path = shutil.which('adb')
    if on_path:
        return on_path
    for candidate in candidates[2:]:
        if candidate.exists():
            return str(candidate)
    return None


def _require_adb_path():
    adb_path = _resolve_adb_path()
    if adb_path:
        return adb_path
    checked = ', '.join(str(c) for c in _adb_candidates())
    raise FileNotFoundError(f'[STARTUP] adb not found. Checked: {checked} and system PATH')


ADB_PATH = _resolve_adb_path()
INSTANCE = 'bst.instance.Pie64'
# Emulator presets. 'exe' is looked for in the install folders found in the Windows uninstall
# registry (any drive / custom folder), then in 'exe_candidates' (default install paths).
# 'uninstall_names' match the uninstall entries' DisplayName. Every preset is driven over plain
# adb; only bluestacks / ldplayer also get the one-time resolution config (see enforce_*).
EMULATOR_CONFIGS = {
    'bluestacks': {
        'display_name': 'BlueStacks',
        'process_names': ['HD-Player.exe', 'BlueStacksServices.exe', 'BlueStacks.exe', 'BlueStacks'],
        'exe': 'HD-Player.exe',
        'uninstall_names': ['BlueStacks'],
        'exe_candidates': [
            'C:\\Program Files\\BlueStacks_nxt\\HD-Player.exe',
            'C:\\Program Files (x86)\\BlueStacks_nxt\\HD-Player.exe',
            '/Applications/BlueStacks.app',                    # BlueStacks Air (macOS)
        ],
        'default_adb_port': '5556',
    },
    'ldplayer': {
        'display_name': 'LDPlayer',
        'process_names': ['dnplayer.exe', 'LdVBoxHeadless.exe'],
        'exe': 'dnplayer.exe',
        'uninstall_names': ['LDPlayer'],
        'exe_candidates': [
            'C:\\LDPlayer\\LDPlayer9\\dnplayer.exe',
            'C:\\LDPlayer\\LDPlayer4.0\\dnplayer.exe',
            'C:\\LDPlayer\\dnplayer.exe',
        ],
        'default_adb_port': '5555',
    },
    'memu': {
        'display_name': 'MEmu',
        'process_names': ['MEmu.exe', 'MEmuHeadless.exe'],
        'exe': 'MEmu.exe',
        'uninstall_names': ['MEmu'],
        'exe_candidates': [
            'C:\\Program Files\\Microvirt\\MEmu\\MEmu.exe',
            'D:\\Program Files\\Microvirt\\MEmu\\MEmu.exe',
        ],
        'default_adb_port': '21503',
    },
    'nox': {
        'display_name': 'Nox',
        'process_names': ['Nox.exe', 'NoxVMHandle.exe'],
        'exe': 'Nox.exe',
        'uninstall_names': ['Nox'],
        'exe_candidates': [
            'C:\\Program Files\\Nox\\bin\\Nox.exe',
            'C:\\Program Files (x86)\\Nox\\bin\\Nox.exe',
        ],
        'default_adb_port': '62001',
    },
    'mumu': {
        'display_name': 'MuMu Player',
        'process_names': ['MuMuPlayer.exe', 'MuMuVMMHeadless.exe', 'MuMuNxDevice.exe', 'MuMuPlayer'],
        'exe': 'MuMuPlayer.exe',
        'uninstall_names': ['MuMu'],
        'exe_candidates': [
            'C:\\Program Files\\Netease\\MuMuPlayer-12.0\\shell\\MuMuPlayer.exe',
            'C:\\Program Files\\Netease\\MuMu Player 12\\shell\\MuMuPlayer.exe',
            '/Applications/MuMuPlayer.app',                    # MuMu Player Pro (macOS)
        ],
        'default_adb_port': '16384',
    },
    'other': {
        'display_name': 'Other',
        'process_names': [],
        'exe': None,
        'uninstall_names': [],
        'exe_candidates': [],
        'default_adb_port': '5555',
    },
}
# Emulators whose resolution / ADB settings the bot writes itself (one-time, see bot.config).
CONFIGURABLE_EMULATORS = ('bluestacks', 'ldplayer') if os.name == 'nt' else ()
SELECTED_EMULATOR = 'bluestacks'


def _default_bot_config():
    return {'emulator_config_state': {key: False for key in EMULATOR_CONFIGS}}


def _load_bot_config():
    defaults = _default_bot_config()
    if not BOT_CONFIG_PATH.exists():
        return defaults
    try:
        data = json.loads(BOT_CONFIG_PATH.read_text(encoding='utf-8'))
    except Exception:
        print('[STARTUP] bot.config is invalid JSON; recreating defaults')
        return defaults
    if not isinstance(data, dict):
        return defaults
    state = data.get('emulator_config_state')
    if not isinstance(state, dict):
        data['emulator_config_state'] = defaults['emulator_config_state'].copy()
        return data
    for key, value in defaults['emulator_config_state'].items():
        state.setdefault(key, value)
    allowed = set(defaults['emulator_config_state'].keys())
    for key in list(state.keys()):
        if key not in allowed:
            state.pop(key, None)
    return data


def _save_bot_config(data):
    BOT_CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding='utf-8')


def _is_emulator_config_applied(emulator_key):
    key = _normalize_emulator_key(emulator_key)
    data = _load_bot_config()
    state = data.get('emulator_config_state', {})
    return bool(state.get(key, False))


def _set_emulator_config_applied(emulator_key, is_applied):
    key = _normalize_emulator_key(emulator_key)
    data = _load_bot_config()
    state = data.setdefault('emulator_config_state', {})
    state[key] = bool(is_applied)
    _save_bot_config(data)


def _normalize_emulator_key(emulator_key):
    key = (emulator_key or SELECTED_EMULATOR or 'bluestacks').strip().lower()
    if key not in EMULATOR_CONFIGS:
        return 'bluestacks'
    return key


def get_selected_emulator():
    return SELECTED_EMULATOR


def set_selected_emulator(emulator_key):
    global SELECTED_EMULATOR
    SELECTED_EMULATOR = _normalize_emulator_key(emulator_key)
    return SELECTED_EMULATOR


def get_default_adb_port(emulator_key=None):
    key = _normalize_emulator_key(emulator_key)
    return EMULATOR_CONFIGS[key]['default_adb_port']


def get_supported_emulators():
    return list(EMULATOR_CONFIGS.keys())


def get_emulator_display_name(emulator_key=None):
    key = _normalize_emulator_key(emulator_key)
    return EMULATOR_CONFIGS[key]['display_name']


def _uninstall_dirs(names):
    """Install folders of programs whose uninstall DisplayName contains one of `names` (Windows)."""
    if os.name != 'nt' or not names:
        return []
    import winreg
    wanted = [n.lower() for n in names]
    dirs = []
    roots = [(winreg.HKEY_LOCAL_MACHINE, 'SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall'),
             (winreg.HKEY_LOCAL_MACHINE, 'SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall'),
             (winreg.HKEY_CURRENT_USER, 'SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall')]
    for hive, path in roots:
        try:
            root = winreg.OpenKey(hive, path)
        except OSError:
            continue
        with root:
            for i in range(winreg.QueryInfoKey(root)[0]):
                try:
                    with winreg.OpenKey(root, winreg.EnumKey(root, i)) as sub:
                        def value(name):
                            try:
                                return str(winreg.QueryValueEx(sub, name)[0])
                            except OSError:
                                return ''
                        display = value('DisplayName').lower()
                        if not any(display.startswith(w) or w in display.split() for w in wanted):
                            continue
                        for raw in (value('InstallLocation'), value('InstallDir'), value('DisplayIcon')):
                            raw = raw.split(',')[0].strip().strip('"')
                            if not raw:
                                continue
                            folder = raw if os.path.isdir(raw) else os.path.dirname(raw)
                            if folder and os.path.isdir(folder) and folder not in dirs:
                                dirs.append(folder)
                except OSError:
                    continue
    return dirs


def _find_in(folder, exe, depth=3):
    """First `exe` under `folder`, at most `depth` levels down."""
    base = folder.rstrip('\\/').count(os.sep)
    for root, subdirs, files in os.walk(folder):
        if exe in files:
            return os.path.join(root, exe)
        if root.count(os.sep) - base >= depth:
            subdirs[:] = []
    return None


_EXE_CACHE = {}


def _resolve_emulator_executable(emulator_key=None):
    # FIX: only fixed default paths were checked, so an emulator on another drive / folder could
    # never be launched or restarted. The uninstall registry gives the real install folder.
    key = _normalize_emulator_key(emulator_key)
    cfg = EMULATOR_CONFIGS[key]
    if key in _EXE_CACHE and _EXE_CACHE[key] and os.path.exists(_EXE_CACHE[key]):
        return _EXE_CACHE[key]
    found = None
    if cfg.get('exe'):
        try:
            for folder in _uninstall_dirs(cfg.get('uninstall_names', [])):
                found = _find_in(folder, cfg['exe'])
                if found:
                    break
        except Exception as exc:
            print(f'[STARTUP] Registry lookup for {cfg["display_name"]} failed: {exc}')
    if not found:
        found = next((p for p in cfg['exe_candidates'] if os.path.exists(p)), None)
    _EXE_CACHE[key] = found
    return found


def is_emulator_running(emulator_key=None):
    key = _normalize_emulator_key(emulator_key)
    targets = {name.lower() for name in EMULATOR_CONFIGS[key]['process_names']}
    for proc in psutil.process_iter(['name']):
        proc_name = (proc.info.get('name') or '').lower()
        if proc_name in targets:
            return True
    return False


def _launch_detached(exe_path):
    """Start the emulator so it is not a child of the bot: it must survive the bot closing."""
    folder = os.path.dirname(exe_path)
    if os.name == 'nt':
        # `start` runs it from a short-lived cmd, so the emulator has no living bot parent.
        subprocess.Popen(['cmd', '/c', 'start', '', exe_path], cwd=folder, close_fds=True,
                         creationflags=_SUBPROCESS_FLAGS | subprocess.CREATE_NEW_PROCESS_GROUP)
    elif sys.platform == 'darwin' and '.app' in exe_path:
        subprocess.Popen(['open', exe_path[:exe_path.index('.app') + 4]])
    else:
        subprocess.Popen([exe_path], cwd=folder, close_fds=True, start_new_session=True)


def launch_emulator(emulator_key=None):
    key = _normalize_emulator_key(emulator_key)
    display_name = get_emulator_display_name(key)
    exe_path = _resolve_emulator_executable(key)
    if not exe_path:
        raise FileNotFoundError(f'{display_name} executable not found')
    print(f'[STARTUP]Launching {display_name}')
    _launch_detached(exe_path)
    wait_for_emulator(key)


def stop_emulator(emulator_key=None, timeout=20):
    key = _normalize_emulator_key(emulator_key)
    targets = {name.lower() for name in EMULATOR_CONFIGS[key]['process_names']}
    procs = []
    for proc in psutil.process_iter(['pid', 'name']):
        proc_name = (proc.info.get('name') or '').lower()
        if proc_name in targets:
            procs.append(proc)
    if not procs:
        return None
    for proc in procs:
        try:
            proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    gone, alive = psutil.wait_procs(procs, timeout=timeout)
    for proc in alive:
        try:
            proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    if alive:
        psutil.wait_procs(alive, timeout=5)
        return None
    return None


def wait_for_emulator(emulator_key=None, timeout=120):
    key = _normalize_emulator_key(emulator_key)
    display_name = get_emulator_display_name(key)
    start = time.time()
    while time.time() - start < timeout:
        if is_emulator_running(key):
            print(f'[STARTUP]Waiting for {display_name} ADB')
            time.sleep(20)
            return True
        time.sleep(2)
    raise RuntimeError(f'{display_name} did not start in time.')


def restart_emulator_for_recovery(emulator_key=None):
    """Close a hung emulator so main() relaunches it. False when the bot can't launch this one."""
    key = _normalize_emulator_key(emulator_key)
    if not _resolve_emulator_executable(key):
        return False
    if is_emulator_running(key):
        print(f'[STARTUP] Closing {get_emulator_display_name(key)} (adb unreachable)')
        stop_emulator(key)
        time.sleep(3)
    launch_emulator(key)
    return True


def start_adb():
    adb_path = _require_adb_path()
    _run_subprocess([adb_path, 'start-server'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def kill_adb_server():
    adb_path = _require_adb_path()
    _run_subprocess([adb_path, 'kill-server'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def enforce_ldplayer_config():
    print('[STARTUP] Applying LDPlayer config (1600x900, 300 DPI, ADB debug enabled)')
    had_errors = False
    roots = [Path('C:\\LDPlayer\\LDPlayer9'), Path('C:\\LDPlayer\\LDPlayer4.0'), Path('C:\\LDPlayer')]
    config_files = []
    for root in roots:
        if not root.exists():
            continue
        config_dirs = [root, root / 'vms' / 'config']
        for config_dir in config_dirs:
            if not config_dir.exists():
                continue
            config_files.extend(sorted(config_dir.glob('leidian[0-9]*.config')))
            config_files.extend(sorted(config_dir.glob('leidan[0-9]*.config')))
    config_files = sorted({p.resolve() for p in config_files})
    if not config_files:
        print('[STARTUP] No LDPlayer config files found, skipping LDPlayer config')
        return False
    for config_path in config_files:
        try:
            data = json.loads(config_path.read_text(encoding='utf-8'))
            data['basicSettings.adbDebug'] = 1
            data['advancedSettings.resolution'] = {'width': 1600, 'height': 900}
            data['advancedSettings.resolutionDpi'] = 300
            config_path.write_text(json.dumps(data, indent=2), encoding='utf-8')
        except (json.JSONDecodeError, IOError, OSError) as exc:
            print(f'[STARTUP] Failed to update {config_path}: {exc}')
            had_errors = True
    if had_errors:
        print('[STARTUP] LDPlayer config step finished with errors')
    else:
        print('[STARTUP] LDPlayer config step finished')
    return not had_errors


def enforce_bluestacks_config():
    if not BLUESTACKS_CONF.exists():
        print('[STARTUP] bluestacks.conf missing, skipping BlueStacks config')
        return False
    A = BLUESTACKS_CONF.read_text()
    # FIX: the instance was hard-coded to Pie64; newer installs use Rvc64 / Tiramisu64 etc. The first
    # installed image is the main instance.
    m = re.search(r'^bst\.installed_images="([^",]+)', A, flags=re.MULTILINE)
    instance = f'bst.instance.{m.group(1)}' if m else INSTANCE
    print(f'[STARTUP] Applying BlueStacks config to {instance} (1600x900, 300 DPI, ADB enabled)')

    def B(key, value):
        # Per-instance key: bst.instance.<image>.<key>="<value>"
        nonlocal A
        full_key = f'{instance}.{key}'
        pattern = f'^{re.escape(full_key)}=".*?"$'
        line = f'{full_key}="{value}"'
        if re.search(pattern, A, flags=re.MULTILINE):
            A = re.sub(pattern, line, A, flags=re.MULTILINE)
        else:
            A += f'\n{line}'

    def C(key, value):
        # Global key: <key>="<value>"
        nonlocal A
        pattern = f'^{re.escape(key)}=".*?"$'
        line = f'{key}="{value}"'
        if re.search(pattern, A, flags=re.MULTILINE):
            A = re.sub(pattern, line, A, flags=re.MULTILINE)
        else:
            A += f'\n{line}'

    C('bst.enable_adb_access', '1')
    B('dpi', '300')
    B('fb_width', '1600')
    B('fb_height', '900')
    B('adb_port', '5556')
    try:
        BLUESTACKS_CONF.write_text(A)
    except OSError as exc:            # e.g. no write access to ProgramData
        print(f'[STARTUP] Could not write bluestacks.conf ({exc}); set 1600x900 in BlueStacks yourself')
        return False
    print('[STARTUP] BlueStacks config step finished')
    return True


def ensure_emulator_config_ready(emulator_key=None):
    key = _normalize_emulator_key(emulator_key)
    display_name = get_emulator_display_name(key)
    if key == 'other':
        return None
    if key not in CONFIGURABLE_EMULATORS:
        # MEmu / Nox / MuMu: nothing to write, just start it when it is installed and not running.
        if not is_emulator_running(key):
            if _resolve_emulator_executable(key):
                launch_emulator(key)
            else:
                print(f'[STARTUP] {display_name} is not running and its install was not found: start it yourself')
        return None
    applied = _is_emulator_config_applied(key)
    if applied:
        if not is_emulator_running(key):
            launch_emulator(key)
        return None
    print(f'[STARTUP] {display_name} config not marked as applied; running one-time config')
    if is_emulator_running(key):
        print(f'[STARTUP] Closing {display_name} before config')
        stop_emulator(key)
    result = enforce_emulator_config(key)
    if result is False:
        print(f'[STARTUP] {display_name} config step could not be completed')
    _set_emulator_config_applied(key, True)
    launch_emulator(key)


def enforce_emulator_config(emulator_key=None):
    key = _normalize_emulator_key(emulator_key)
    if key == 'bluestacks':
        return enforce_bluestacks_config()
    if key == 'ldplayer':
        return enforce_ldplayer_config()
    if key == 'other':
        return True
    return False
