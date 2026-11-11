# crb/devices.py - find running Android emulators/devices over adb (any emulator, any OS).
#
# Lists what `adb devices` already knows, then tries `adb connect` on the usual local ports of the
# common emulators (first and second instance), so emulators that do not register themselves with
# adb are found too.
import subprocess

# port -> (preset key, label)
KNOWN_PORTS = {
    5555: ('ldplayer', 'LDPlayer / BlueStacks / generic'), 5557: ('ldplayer', 'LDPlayer #2'),
    5556: ('bluestacks', 'BlueStacks'), 5565: ('bluestacks', 'BlueStacks #2'), 5575: ('bluestacks', 'BlueStacks #3'),
    21503: ('memu', 'MEmu'), 21513: ('memu', 'MEmu #2'), 21523: ('memu', 'MEmu #3'),
    62001: ('nox', 'Nox'), 62025: ('nox', 'Nox #2'),
    16384: ('mumu', 'MuMu Player 12'), 16416: ('mumu', 'MuMu Player 12 #2'), 7555: ('mumu', 'MuMu Player 6'),
}
_FLAGS = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0


def _run(args, timeout=8):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, creationflags=_FLAGS)
        return r.stdout or ''
    except Exception:
        return ''


def _devices(adb_path):
    out = {}
    for line in _run([adb_path, 'devices']).splitlines()[1:]:
        parts = line.split('\t')
        if len(parts) == 2 and parts[0].strip():
            out[parts[0].strip()] = parts[1].strip()
    return out


def preset_for(serial):
    """(preset key or None, host or None, port string or None) for an adb serial."""
    serial = serial.strip()
    if serial.startswith('emulator-'):
        try:
            port = int(serial.split('-')[1]) + 1          # console port + 1 = adb port
        except ValueError:
            return None, None, None
        key = KNOWN_PORTS.get(port, ('other', ''))[0]
        return key, '127.0.0.1', str(port)
    if ':' in serial:
        host, port = serial.rsplit(':', 1)
        if port.isdigit():
            key = KNOWN_PORTS.get(int(port), ('other', ''))[0]
            return key, host, port
    return 'other', None, None                         # USB device: serial only


def scan(adb_path):
    """[(serial, description)] of every device that answers (state 'device')."""
    for port in KNOWN_PORTS:
        _run([adb_path, 'connect', f'127.0.0.1:{port}'], timeout=3)
    found = []
    for serial, state in _devices(adb_path).items():
        key, _host, port = preset_for(serial)
        label = KNOWN_PORTS.get(int(port), (key, 'emulator'))[1] if port and port.isdigit() else 'USB device'
        if state != 'device':
            label += f' ({state})'
        found.append((serial, label))
    # forget the probes that did not answer
    for serial, state in _devices(adb_path).items():
        if state == 'offline' and ':' in serial:
            _run([adb_path, 'disconnect', serial], timeout=3)
    return [f for f in found if '(offline)' not in f[1]]
