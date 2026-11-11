# Reconstructed from Pyarmor-decrypted bytecode disassembly (adb.dis.txt).
# ACBot Basic v1.6.7 - ADB transport: device discovery, screencap, input taps/swipes, app control.
import subprocess
import random
import os
import time
import re
import shutil
import cv2
import numpy as np
from utils.runtime_paths import resolve_resource_path, resolve_writable_path

EMULATOR_HOST = '127.0.0.1'
ADB_PORT = '5556'
EMULATOR_NAME = 'bluestacks'


def set_host(host):
    global EMULATOR_HOST, _CACHED_TARGET
    value = host
    value = (value or '').strip()
    EMULATOR_HOST = value if value else '127.0.0.1'
    _CACHED_TARGET = None


def set_port(port):
    global ADB_PORT, _CACHED_TARGET
    ADB_PORT = port
    _CACHED_TARGET = None


def set_emulator(emulator_name):
    global EMULATOR_NAME, _CACHED_TARGET
    EMULATOR_NAME = (emulator_name or 'bluestacks').strip().lower()
    _CACHED_TARGET = None


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


ADB_PATH = _resolve_adb_path()
_CACHED_ADB_PATH = None
_CACHED_TARGET = None


def _get_cached_adb_path():
    global _CACHED_ADB_PATH
    if _CACHED_ADB_PATH is None:
        _CACHED_ADB_PATH = _require_adb_path()
    return _CACHED_ADB_PATH


def _get_cached_target():
    global _CACHED_TARGET
    if _CACHED_TARGET is None:
        _CACHED_TARGET = get_active_target()
    return _CACHED_TARGET


def _require_adb_path():
    adb_path = _resolve_adb_path()
    if adb_path:
        return adb_path
    checked = ', '.join(str(c) for c in _adb_candidates())
    raise FileNotFoundError(f'[ADB] adb not found. Checked: {checked} and system PATH')


def get_target_addr():
    return f'{EMULATOR_HOST}:{ADB_PORT}'


def get_bluestacks_addr():
    return get_active_target()


DEBUG_TAPS = False
DEBUG_VISION = None
_SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


def get_connected_devices():
    output = adb(['devices'])
    lines = output.splitlines()[1:]
    devices = []
    for line in lines:
        if '\tdevice' in line:
            devices.append(line.split('\t')[0])
    return devices


def _device_matches_port(serial, port):
    serial_str = serial
    port_str = str(port)
    if ':' in serial_str:
        return serial_str.split(':')[-1] == port_str
    if serial_str.startswith('emulator-'):
        try:
            console_port = int(serial_str.split('-')[1])
            # emulator-N console port; adb port is console port + 1
            return str(console_port + 1) == port_str
        except (IndexError, ValueError):
            pass
    return False


def get_device_addr():
    devices = get_connected_devices()
    if not devices:
        raise RuntimeError('No ADB devices found')
    if len(devices) == 1:
        return devices[0]
    for device in devices:
        if _device_matches_port(device, ADB_PORT):
            return device
    for device in devices:
        if device.startswith('127.0.0.1') or device.startswith('localhost') or device.startswith('emulator-'):
            return device
    return devices[0]


def _get_configured_connected_device(devices):
    device_list = devices
    target = get_target_addr()
    for device in device_list:
        if device == target:
            return device
    for device in device_list:
        if _device_matches_port(device, ADB_PORT):
            return device
    return None


ADB_CALL_TIMEOUT = 20


def _run_subprocess(cmd, **A):
    # FIX: taps and screenshots had no timeout, so one hung adb call froze the bot for good.
    if _SUBPROCESS_FLAGS:
        A.setdefault('creationflags', _SUBPROCESS_FLAGS)
    A.setdefault('timeout', ADB_CALL_TIMEOUT)
    return subprocess.run(cmd, **A)


def check_stop():
    """Raise control.BotStopped once the user pressed Stop (see control.BotStopped)."""
    try:
        import control
    except Exception:
        return
    if control.BotControl.stop_requested:
        raise control.BotStopped()


def _input(cmd):
    """Run an input command (tap / swipe) on the target; a timeout is logged, not fatal: the next
    screenshot re-checks the connection."""
    check_stop()
    try:
        _run_subprocess([_require_adb_path(), '-s', get_active_target()] + cmd,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    except subprocess.TimeoutExpired:
        print(f'[ADB] {" ".join(cmd[1:3])} timed out')


def adb(cmd):
    full_cmd = [_require_adb_path()] + cmd
    try:
        result = _run_subprocess(full_cmd, capture_output=True, text=True, encoding='utf-8',
                                 errors='replace', timeout=10)
    except subprocess.TimeoutExpired:
        print(f'[ADB] adb {" ".join(cmd[:2])} timed out')
        return ''
    return (result.stdout or '').strip()


def adb_target(cmd):
    target = get_active_target()
    full_cmd = [_require_adb_path(), '-s', target] + cmd
    try:
        result = _run_subprocess(full_cmd, capture_output=True, text=True, encoding='utf-8',
                                 errors='replace', timeout=20)
    except subprocess.TimeoutExpired:
        print(f'[ADB] {" ".join(cmd[:3])} timed out')
        return ''
    return (result.stdout or '').strip()


def get_active_target():
    # FIX: this ran `adb devices` on every tap, swipe and shell call (several per second). The
    # serial is now resolved once and kept until ensure_connected() / a reconnect changes it.
    global _CACHED_TARGET
    if _CACHED_TARGET:
        return _CACHED_TARGET
    target = get_target_addr()
    try:
        devices = get_connected_devices()
    except Exception:
        return target
    configured = _get_configured_connected_device(devices)
    if configured:
        _CACHED_TARGET = configured
        return configured
    return target


def connect_emulator():
    target = get_active_target()
    if ':' not in target:
        return None
    print(f'[ADB] Connecting to {EMULATOR_NAME} at {target}')
    for attempt in range(3):
        try:
            output = adb(['connect', target])
            if 'connected' in output.lower() or 'already connected' in output.lower():
                print(f'[ADB] Successfully connected to {target}')
                time.sleep(1)
                return None
            print(f'[ADB] Connect attempt {attempt + 1}/3: {output.strip()}')
        except Exception as exc:
            print(f'[ADB] Connect attempt {attempt + 1}/3 failed: {exc}')
        if attempt < 2:
            time.sleep(2)
    time.sleep(1)


def wait_for_device(timeout=10):
    connect_emulator()
    start = time.time()
    last_status_log = 0
    print(f'[ADB] Waiting up to {timeout} s for the emulator at {get_target_addr()}')
    while time.time() - start < timeout:
        if not _bot_running():
            raise RuntimeError('[ADB] Bot stopped while waiting for the emulator')
        try:
            output = adb(['devices'])
        except Exception as exc:
            print(f'[ADB] adb devices error: {exc}')
            time.sleep(1)
            continue
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        device_lines = lines[1:] if len(lines) > 1 else []
        target = get_active_target()
        saw_offline = False
        saw_unauthorized = False
        for line in device_lines:
            parts = line.split('\t')
            if len(parts) != 2:
                continue
            serial, state = parts[0].strip(), parts[1].strip()
            if serial == target and state == 'device':
                print('[ADB] Target device ready')
                return serial
            if serial == target and state == 'offline':
                saw_offline = True
            if serial == target and state == 'unauthorized':
                saw_unauthorized = True
        now = time.time()
        if now - last_status_log > 15:
            left = int(timeout - (now - start))
            if saw_unauthorized:
                print(f'[ADB] Device unauthorized - accept the USB debugging prompt ({left} s left)')
            elif saw_offline:
                print(f'[ADB] Device offline - waiting for it to come back ({left} s left)')
            else:
                print(f'[ADB] Nothing answering at {target} yet ({left} s left)')
            last_status_log = now
        if ':' in target and now - start > 5:
            try:
                adb(['connect', target])     # the emulator may come up while we wait
            except Exception:
                pass
        time.sleep(2)
    # FIX: this used to end with a bare "wait_for_device timeout" after two minutes of
    # "No ready device yet..." spam. Say what is wrong and what the bot can see instead.
    others = [serial for serial, state in _device_states_quiet().items() if state == 'device']
    hint = f' adb can see: {", ".join(others)} - pick that emulator/port in Settings.' if others else \
        ' Start the emulator (and enable ADB in its settings), or check the emulator and port in Settings.'
    print(f'[ADB] No emulator answered at {get_target_addr()} within {timeout} s.{hint}')
    raise RuntimeError(f'No emulator answered at {get_target_addr()} within {timeout} s.{hint}')


def _device_states_quiet():
    try:
        return _read_adb_device_states(_require_adb_path(), timeout=10)
    except Exception:
        return {}


def is_app_running(package_name):
    out = adb_target(['shell', 'pidof', package_name]).strip()
    if out and out.split()[0].isdigit():
        return True
    if 'not found' in out or not out:
        # Android < 7 has no pidof: fall back to ps (and ps -A on newer toybox ps)
        listing = adb_target(['shell', 'ps']) + adb_target(['shell', 'ps', '-A'])
        return any(line.split()[-1] == package_name for line in listing.splitlines() if line.split())
    return False


def is_app_in_foreground(package_name):
    """FIX: main.py's hard-popup restart called this, but it did not exist (AttributeError)."""
    out = adb_target(['shell', 'dumpsys', 'window', 'windows'])
    for line in out.splitlines():
        if 'mCurrentFocus' in line or 'mFocusedApp' in line:
            if package_name in line:
                return True
    return False


def launch_app(package_name):
    print('[ADB] Launching Clash of Clans')
    adb_target(['shell', 'monkey', '-p', package_name, '-c', 'android.intent.category.LAUNCHER', '1'])


def force_stop(package_name):
    print('[ADB] Force stopping Clash of Clans')
    adb_target(['shell', 'am', 'force-stop', package_name])


def _capture(adb_path):
    target = get_active_target()
    try:
        data = _run_subprocess([adb_path, '-s', target, 'exec-out', 'screencap', '-p'],
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15).stdout
        if data:
            return data
        print('[ADB] exec-out failed, using fallback screencap...')
        remote_path = '/sdcard/screen.png'
        _run_subprocess([adb_path, '-s', target, 'shell', 'screencap', '-p', remote_path],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
        return _run_subprocess([adb_path, '-s', target, 'exec-out', 'cat', remote_path],
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15).stdout
    except subprocess.TimeoutExpired:
        print('[ADB] screencap timed out')
        return b''


def screenshot():
    global _CACHED_TARGET
    check_stop()
    ensure_connected()
    adb_path = _require_adb_path()
    data = _capture(adb_path)
    if not data:
        # FIX: an empty capture (emulator hung or dropping) raised and ended the bot. Re-check
        # the connection (reconnect / DeviceLostError) and try once more.
        _CACHED_TARGET = None
        serial = _reconnect(adb_path, get_target_addr(), 'no screenshot')
        if not serial:
            raise DeviceLostError(f'no screenshot from {get_target_addr()} after {RECONNECT_SECONDS} s')
        _CACHED_TARGET = serial
        data = _capture(adb_path)
        if not data:
            # adb still lists the device but it returns nothing: the emulator is frozen (10 Nov:
            # screencap timeouts, then garbage). Treat it as lost so the worker restarts it.
            raise DeviceLostError(f'{get_target_addr()} is connected but returns no screenshots (emulator frozen?)')
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    for _ in range(2):
        if img is not None:
            break
        # FIX: a truncated PNG (seen once in the Oct runs) ended the bot. Capture again.
        print('[ADB] Screenshot could not be decoded, capturing again')
        time.sleep(0.5)
        data = _capture(adb_path)
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR) if data else None
    if img is None:
        raise DeviceLostError(f'{get_target_addr()} keeps returning unreadable screenshots (emulator frozen?)')
    return img


def _read_adb_device_states(adb_path, timeout=10):
    try:
        result = _run_subprocess([adb_path, 'devices'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError('adb devices timed out while ensuring connection') from exc
    states = {}
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    for line in lines[1:]:
        parts = line.split('\t')
        if len(parts) != 2:
            continue
        serial = parts[0].strip()
        state = parts[1].strip().lower()
        if serial:
            states[serial] = state
    return states


def _resolve_ready_serial_for_target(target, states):
    state_map = states
    wanted = target
    if wanted in state_map and state_map[wanted] == 'device':
        return wanted
    for serial, state in state_map.items():
        if state != 'device':
            continue
        if _device_matches_port(serial, ADB_PORT):
            return serial
    return None


class DeviceLostError(RuntimeError):
    """The emulator stayed unreachable over adb after the reconnect attempts."""


RECONNECT_SECONDS = 150


def _bot_running():
    try:
        import control
        return bool(control.BotControl.running)
    except Exception:
        return True


def _emulator_gone():
    """True when the selected emulator's window process has exited (crashed / closed): waiting for
    adb is pointless then. Unknown for "Other" (no process names), so False."""
    try:
        import startup
        key = startup._normalize_emulator_key(EMULATOR_NAME)
        return bool(startup.EMULATOR_CONFIGS[key]['process_names']) and not startup.is_emulator_running(key)
    except Exception:
        return False


def _reconnect(adb_path, target, state):
    """Bring a dropped / offline adb target back: reconnect, then restart the adb server.

    Returns the ready serial, or None after RECONNECT_SECONDS (or when the bot is stopped)."""
    global _CACHED_TARGET
    print(f'[ADB] Lost the connection to {target} ({state}), reconnecting')
    _CACHED_TARGET = None
    start = time.time()
    server_restarted = False
    while time.time() - start < RECONNECT_SECONDS and _bot_running():
        if time.time() - start > 10 and _emulator_gone():
            print('[ADB] The emulator window has closed (crashed?), not waiting any longer')
            return None
        try:
            if ':' in target:
                _run_subprocess([adb_path, 'disconnect', target], stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=10)
                _run_subprocess([adb_path, 'connect', target], stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=10)
            time.sleep(2)
            serial = _resolve_ready_serial_for_target(target, _read_adb_device_states(adb_path, timeout=10))
            if serial:
                print(f'[ADB] Reconnected to {serial} after {int(time.time() - start)} s')
                return serial
            if not server_restarted and time.time() - start > 30:
                print('[ADB] Still not ready, restarting the adb server')
                _run_subprocess([adb_path, 'kill-server'], stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=15)
                _run_subprocess([adb_path, 'start-server'], stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=30)
                server_restarted = True
        except (subprocess.TimeoutExpired, RuntimeError) as exc:
            print(f'[ADB] Reconnect attempt failed: {exc}')
        time.sleep(3)
    return None


def ensure_connected():
    global _CACHED_TARGET
    adb_path = _require_adb_path()
    target = get_active_target()
    last_states = {}
    for attempt in range(3):
        try:
            states = _read_adb_device_states(adb_path, timeout=10)
        except RuntimeError:
            states = {}
        last_states = states
        ready_serial = _resolve_ready_serial_for_target(target, states)
        if ready_serial:
            _CACHED_TARGET = ready_serial
            return None
        target_state = states.get(target)
        if ':' in target:
            try:
                _run_subprocess([adb_path, 'connect', target], stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=10)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(f'adb connect to {target} timed out') from exc
            time.sleep(1)
            continue
        if target_state == 'unauthorized':
            raise RuntimeError(f'adb target {target} is unauthorized (accept USB debugging prompt)')
        if attempt < 2:
            time.sleep(1)
    # FIX: an emulator that drops to "offline" (seen on BlueStacks right after a battle) used to
    # raise here and end the bot. Reconnect first; only give up after RECONNECT_SECONDS.
    state = last_states.get(target, 'missing')
    serial = _reconnect(adb_path, target, state)
    if serial:
        _CACHED_TARGET = serial
        return None
    seen = ', '.join(f'{s}:{st}' for s, st in sorted(last_states.items())) or 'none'
    raise DeviceLostError(f'adb target {target} not ready after {RECONNECT_SECONDS} s of reconnecting '
                          f'(last state={state}, seen: {seen})')


def tap(x, y):
    if DEBUG_TAPS and DEBUG_VISION:
        debug_tap_overlay(DEBUG_VISION, x, y)
    jx = x + random.randint(-5, 5)
    jy = y + random.randint(-2, 2)
    _input(['shell', 'input', 'tap', str(jx), str(jy)])


def tap_small(x, y):
    if DEBUG_TAPS and DEBUG_VISION:
        debug_tap_overlay(DEBUG_VISION, x, y)
    jx = x + random.randint(-2, 2)
    jy = y + random.randint(-2, 2)
    _input(['shell', 'input', 'tap', str(jx), str(jy)])


def tap_raw(x, y):
    if DEBUG_TAPS and DEBUG_VISION:
        debug_tap_overlay(DEBUG_VISION, x, y)
    _input(['shell', 'input', 'tap', str(x), str(y)])


def swipe(x1, y1, x2, y2, duration=300):
    _input(['shell', 'input', 'swipe', str(x1), str(y1), str(x2), str(y2), str(duration)])


def tap_batch_small(coords):
    points = coords
    if not points:
        return None
    adb_path = _get_cached_adb_path()
    target = _get_cached_target()
    commands = []
    for x, y in points:
        jx = x + random.randint(-2, 2)
        jy = y + random.randint(-2, 2)
        commands.append(f'input tap {jx} {jy}')
    shell_cmd = ' ; '.join(commands)
    try:
        _run_subprocess([adb_path, '-s', target, 'shell', shell_cmd],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
    except subprocess.TimeoutExpired:
        print('[ADB] batched taps timed out')


EXPECTED_SIZE = (1600, 900)


def check_screen_size():
    """Warn when the emulator is not 1600x900 landscape: every tap position and template assumes it."""
    out = adb_target(['shell', 'wm', 'size'])
    sizes = re.findall(r'(\d+)x(\d+)', out)
    if not sizes:
        return None
    w, h = (int(v) for v in sizes[-1])              # "Override size" wins over "Physical size"
    if (max(w, h), min(w, h)) != EXPECTED_SIZE:
        print(f'[ADB] WARNING: emulator screen is {w}x{h}; the bot needs 1600x900 (landscape). '
              f'Set the emulator resolution to 1600x900, or taps will land in the wrong places.')
    dpi = screen_density()
    if dpi and dpi != EXPECTED_DPI:
        print(f'[ADB] WARNING: emulator density is {dpi} DPI; the bot was built at {EXPECTED_DPI} DPI '
              f'(the game scales its buttons with DPI). Set {EXPECTED_DPI} DPI in the emulator settings.')
    return w, h


EXPECTED_DPI = 300


def screen_density():
    """The emulator's DPI ("Override density" wins over "Physical density"), or None."""
    found = re.findall(r'density:\s*(\d+)', adb_target(['shell', 'wm', 'density']))
    return int(found[-1]) if found else None


def ensure_ready(timeout=240):        # a cold emulator boot can take 2+ minutes (MEmu, 11 Nov)
    global _CACHED_TARGET
    _CACHED_TARGET = None
    wait_for_device(timeout)
    ensure_connected()
    try:
        check_screen_size()
    except Exception as exc:
        print(f'[ADB] Screen size check failed: {exc}')


def save_treasure_screenshot():
    folder = str(resolve_writable_path('treasureloot'))
    os.makedirs(folder, exist_ok=True)
    files = [name for name in os.listdir(folder) if name.startswith('loot') and name.endswith('.png')]
    numbers = []
    for name in files:
        try:
            numbers.append(int(name.replace('loot', '').replace('.png', '')))
        except ValueError:
            pass
    next_index = max(numbers) + 1 if numbers else 1
    out_path = os.path.join(folder, f'loot{next_index}.png')
    img = screenshot()
    cv2.imwrite(out_path, img)
    print('[TREASURE] Saved loot screenshot')


def debug_tap_overlay(vision, x, y):
    frame = vision.grab()
    cv2.circle(frame, (int(x), int(y)), 18, (0, 0, 255), 3)
    stamp = int(time.time() * 1000)
    cv2.imwrite(f'debug_tap_{stamp}.png', frame)
