"""Clash Rekt Bot - update engine (Python standard library only).

The app downloads an update package (a zip of the app's own files plus app_manifest.json, built by
tools/build_update.py and attached to every GitHub release), checks it and unpacks it into
.crb/updates/staging-<version>. This module puts it in place. It is used in three ways:

  * imported by the app          versions, manifests and what counts as "the app's files";
  * as its own process           python -I engine.py apply --root <app folder> --wait-pid <app pid>
                                 waits for the app to close, swaps the files, installs new libraries
                                 when requirements.txt changed, opens the new version and checks that
                                 it comes up. If anything fails, the previous version is put back
                                 and opened instead;
  * from runtime/run_bot.py      startup_hook(): first thing at every start, before the app imports
                                 any of its own modules, it finishes an update that was cut off
                                 (power cut, killed updater) or undoes one that never opened.

What an update never touches: settings (runtime/profiles, runtime/bot.config), logs, the downloaded
Python (.crb), adb, farm instances and everything else outside the update scope below. Inside the
scope, a file this computer changed (the bot's self-healing re-learns button pictures, users add or
edit attack scripts) is kept when the new version did not change it; when both changed, the new file
wins and this computer's copy goes into the backup. Every file an update replaces or removes is kept
in .crb/updates/backup/, so "Undo the last update" can put the previous version back.

  engine.py apply       --root DIR [--wait-pid PID]    run what .crb/updates/pending.json asks for
  engine.py resume      --root DIR                     finish a cut-off update (no app start)
  engine.py install-dir --source DIR --root DIR        put a newer app folder over an older one
  engine.py manifest    --root DIR [--version V] [--out FILE]
  engine.py verify      ZIP                            check an update package
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
import zipfile
from pathlib import Path

REPO = 'PriyanshuGeTRekT/Clashofclans-REKTBOT'
MANIFEST = 'app_manifest.json'
PACKAGE_NAME = 'ClashRektBot-{version}-update.zip'

# What an update replaces. Everything else in the app folder belongs to the user.
SCOPE_DIRS = ('source/', 'launcher/', 'runtime/templates/', 'runtime/assets/', 'runtime/CSV/',
              'runtime/Tools/uiautomator2_data/')
SCOPE_FILES = ('VERSION', 'requirements.txt', 'README.md', 'runtime/run_bot.py',
               'Start Clash Rekt Bot.bat', 'Start Clash Rekt Bot.command', 'start-clash-rekt-bot.sh')
SKIP_DIRS = ('__pycache__', '.git', '.crb')
SKIP_FILES = ('.DS_Store', 'Thumbs.db', 'desktop.ini')
SKIP_SUFFIXES = ('.pyc', '.pyo', '.crb-new', '.part')

WAIT_FOR_APP_SECONDS = 90         # the app closes in a few seconds; give up after this
HEALTH_SECONDS = 150              # the new version must open its window within this
LAUNCHED = 10                     # exit code of `apply`: the app was opened by the engine
MAX_PACKAGE_BYTES = 400 * 1024 * 1024
MAX_PACKAGE_FILES = 20000
LAUNCH_ENV = 'CRB_UPDATE_LAUNCHED'

_NO_WINDOW = 0x08000000 if os.name == 'nt' else 0             # CREATE_NO_WINDOW
_DETACHED = (0x00000008 | 0x00000200) if os.name == 'nt' else 0   # DETACHED_PROCESS | NEW_PROCESS_GROUP


class UpdateError(Exception):
    pass


# ====================================================================== versions
def parse_version(text):
    """'v2.1.0' -> comparable tuple. A release sorts after its pre-releases (2.1.0-beta < 2.1.0)."""
    text = str(text or '').strip()
    if text[:1] in ('v', 'V'):
        text = text[1:]
    core, _, pre = text.partition('-')
    nums = []
    for part in core.split('+')[0].split('.'):
        digits = ''.join(ch for ch in part if ch.isdigit())
        nums.append(int(digits) if digits else 0)
    nums = (nums + [0, 0, 0, 0])[:4]
    return tuple(nums) + ((0, pre) if pre else (1, ''))


def is_newer(a, b):
    """True when version a is newer than version b."""
    return parse_version(a) > parse_version(b)


def read_version(root):
    root = Path(root)
    try:
        text = (root / 'VERSION').read_text(encoding='utf-8').strip()
        if text:
            return text
    except OSError:
        pass
    manifest = load_json(root / MANIFEST, None)
    return str(manifest.get('version', '')) if isinstance(manifest, dict) else ''


# ====================================================================== files
def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def in_scope(rel):
    return rel in SCOPE_FILES or rel.startswith(SCOPE_DIRS)


def is_junk(rel):
    parts = rel.split('/')
    return (any(p in SKIP_DIRS for p in parts[:-1]) or parts[-1] in SKIP_FILES
            or parts[-1].endswith(SKIP_SUFFIXES))


def safe_rel(rel):
    """A clean relative path inside the app folder (no '..', no drive, no absolute path)."""
    if not isinstance(rel, str) or not rel or len(rel) > 400:
        return False
    if rel.startswith('/') or '\\' in rel or ':' in rel or '\x00' in rel:
        return False
    return all(p not in ('', '.', '..') for p in rel.split('/'))


def collect_files(tree, use_git=True):
    """The app's files in `tree` (relative POSIX paths): git's view in a checkout, else a walk."""
    tree = Path(tree)
    names = None
    if use_git and (tree / '.git').exists():
        try:
            out = subprocess.run(['git', '-C', str(tree), 'ls-files', '-z', '--cached', '--others',
                                  '--exclude-standard'], capture_output=True, check=True, timeout=120).stdout
            names = [n for n in out.decode('utf-8').split('\0') if n and (tree / n).is_file()]
        except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
            names = None
    if names is None:
        names = []
        for dirpath, dirnames, filenames in os.walk(tree):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            rel_dir = Path(os.path.relpath(dirpath, tree)).as_posix()
            for name in filenames:
                names.append(name if rel_dir == '.' else f'{rel_dir}/{name}')
    return sorted({n for n in names if safe_rel(n) and in_scope(n) and not is_junk(n)})


def _is_exec(path, rel):
    if rel.endswith(('.sh', '.command')):
        return True
    return os.name != 'nt' and bool(os.stat(path).st_mode & 0o111)


def build_manifest(tree, version=None, files=None):
    tree = Path(tree)
    files = collect_files(tree) if files is None else files
    entries = {}
    for rel in files:
        path = tree / rel
        entry = {'sha256': sha256_file(path), 'size': path.stat().st_size}
        if _is_exec(path, rel):
            entry['x'] = True
        entries[rel] = entry
    return {'schema': 1, 'name': 'Clash Rekt Bot', 'version': version or read_version(tree), 'files': entries}


def verify_tree(tree, manifest):
    """Raise UpdateError unless every manifest file is in `tree` with the right content."""
    tree = Path(tree)
    files = manifest.get('files')
    if not isinstance(files, dict) or not files:
        raise UpdateError('the update has no file list')
    for rel, meta in files.items():
        if not (safe_rel(rel) and in_scope(rel)):
            raise UpdateError(f'the update lists a file outside the app: {rel!r}')
        path = tree / rel
        if not path.is_file() or sha256_file(path) != meta.get('sha256'):
            raise UpdateError(f'the update is damaged ({rel})')


def load_json(path, default=None):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.crb-new')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=1)
        f.flush()
        os.fsync(f.fileno())
    _replace(tmp, path)


def _replace(src, dst):
    for attempt in range(12):                 # Windows: a viewer or antivirus may hold a file briefly
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == 11:
                raise
            time.sleep(0.4)


def _copy_in(src, dst, executable=None):
    """Copy src over dst atomically. The new file gets a new time stamp, so Python never runs stale
    byte code for it."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + '.crb-new')
    shutil.copyfile(src, tmp)
    if os.name != 'nt':
        if executable is None:
            shutil.copymode(src, tmp)
        else:
            os.chmod(tmp, 0o755 if executable else 0o644)
    _replace(tmp, dst)


def _read_lines(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return [ln.rstrip('\n') for ln in f if ln.strip()]
    except OSError:
        return []


def _append_line(path, text):
    with open(path, 'a', encoding='utf-8') as f:
        f.write(text + '\n')
        f.flush()
        os.fsync(f.fileno())


# ====================================================================== state
def state_dir(root):
    return Path(root) / '.crb' / 'updates'


def log(root, message):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
    try:
        print(f'[UPDATE] {message}', flush=True)
    except Exception:                                   # pythonw: no console
        pass
    try:
        path = state_dir(root) / 'updater.log'
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > 1_000_000:
            path.replace(path.with_name('updater.old.log'))
        with open(path, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except OSError:
        pass


def bad_versions(root):
    data = load_json(state_dir(root) / 'bad_versions.json', {})
    return data if isinstance(data, dict) else {}


def _mark_bad(root, version, reason):
    data = bad_versions(root)
    data[str(version)] = reason
    save_json(state_dir(root) / 'bad_versions.json', data)


def _result(root, op, from_v, to_v, ok, message):
    save_json(state_dir(root) / 'last_result.json', {'op': op, 'from': from_v, 'to': to_v, 'ok': ok,
                                                    'message': message, 'at': time.time(), 'shown': False})
    log(root, ('OK: ' if ok else 'FAILED: ') + message)


# ---------------------------------------------------------------------- processes
def pid_alive(pid):
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        k32.WaitForSingleObject.restype = wintypes.DWORD
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = k32.OpenProcess(0x00100000 | 0x1000, False, pid)   # SYNCHRONIZE | QUERY_LIMITED_INFO
        if not handle:
            return False
        try:
            return k32.WaitForSingleObject(handle, 0) == 0x102          # WAIT_TIMEOUT: still running
        finally:
            k32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    try:                                   # an ended child nobody collected yet still answers kill(0)
        stat = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)], capture_output=True, text=True,
                              timeout=5).stdout.strip()
        if not stat or stat.startswith('Z'):
            return False
    except (OSError, subprocess.SubprocessError):
        pass
    return True


def wait_for_exit(pid, timeout):
    deadline = time.time() + timeout
    while pid_alive(pid):
        if time.time() > deadline:
            return False
        time.sleep(0.3)
    return True


def _lock_path(root):
    return state_dir(root) / 'lock'


def _lock_owner(root):
    try:
        return int(_lock_path(root).read_text().strip() or 0)
    except (OSError, ValueError):
        return 0


def _acquire_lock(root):
    path = _lock_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(3):
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            owner = _lock_owner(root)
            if owner == os.getpid():
                return True
            if owner and pid_alive(owner):
                return False
            try:
                path.unlink()                  # left behind by an updater that is gone
            except OSError:
                time.sleep(0.2)
    return False


def _release_lock(root):
    if _lock_owner(root) == os.getpid():
        try:
            _lock_path(root).unlink()
        except OSError:
            pass


def _boot_time():
    if os.name == 'nt':
        try:
            import ctypes
            k32 = ctypes.WinDLL('kernel32')
            k32.GetTickCount64.restype = ctypes.c_ulonglong
            return time.time() - k32.GetTickCount64() / 1000.0
        except Exception:                                     # noqa: BLE001
            return 0.0
    return 0.0


def _app_open(health):
    """True when the app that wrote `health` is still running (and is really this app)."""
    if not isinstance(health, dict):
        return False
    try:
        pid = int(health.get('pid') or 0)
    except (TypeError, ValueError):
        return False
    if pid <= 0 or pid == os.getpid() or not pid_alive(pid):
        return False
    if os.name == 'nt':
        return float(health.get('at') or 0) > _boot_time()       # a pid from before a restart is stale
    try:
        cmd = subprocess.run(['ps', '-o', 'command=', '-p', str(pid)], capture_output=True, text=True,
                             timeout=5).stdout
        return 'run_bot.py' in cmd
    except (OSError, subprocess.SubprocessError):
        return True


def _updater_busy(root):
    owner = _lock_owner(root)
    return bool(owner) and owner != os.getpid() and pid_alive(owner)


# ====================================================================== applying files
def apply_files(root, source, new_manifest, old_manifest, backup_files, added_log, on_file=None):
    """Bring the in-scope files of `root` to `new_manifest` (copied from `source`). Safe to run
    again after an interruption: files already in place are skipped, and the backup keeps the very
    first copy of every file it replaced."""
    root, source, backup_files = Path(root), Path(source), Path(backup_files)
    new_files = new_manifest['files']
    old_files = old_manifest.get('files') if isinstance(old_manifest, dict) else None
    added = set(_read_lines(added_log))
    stats = {'replaced': 0, 'added': 0, 'removed': 0, 'unchanged': 0, 'kept': 0, 'overridden': 0}
    for rel in sorted(new_files):
        if not (safe_rel(rel) and in_scope(rel)):
            raise UpdateError(f'refusing to write {rel!r}')
        meta = new_files[rel]
        dst = root / rel
        cur = sha256_file(dst) if dst.is_file() else None
        new = meta['sha256']
        if cur == new:
            stats['unchanged'] += 1
            continue
        old = (old_files.get(rel) or {}).get('sha256') if old_files is not None else None
        if cur is not None and old is not None and old == new:
            stats['kept'] += 1          # the release did not change it, this computer did: keep it
            continue
        if cur is None:
            if rel not in added:
                _append_line(added_log, rel)
                added.add(rel)
            stats['added'] += 1
        else:
            if old is not None and cur != old:
                stats['overridden'] += 1       # both changed: the release wins, this copy is backed up
            _backup(root, rel, backup_files)
            stats['replaced'] += 1
        _copy_in(source / rel, dst, bool(meta.get('x')))
        if on_file:
            on_file(rel)
    if old_files is not None:
        for rel in sorted(set(old_files) - set(new_files)):
            dst = root / rel
            if not (safe_rel(rel) and in_scope(rel)) or not dst.is_file():
                continue
            if sha256_file(dst) != (old_files.get(rel) or {}).get('sha256'):
                stats['kept'] += 1             # changed on this computer: leave it
                continue
            _backup(root, rel, backup_files)
            dst.unlink()
            stats['removed'] += 1
            _prune_empty_dirs(root, dst.parent)
    return stats


def _backup(root, rel, backup_files):
    target = backup_files / rel
    if target.exists():                          # the first copy is the original: keep it
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + '.crb-new')
    shutil.copy2(Path(root) / rel, tmp)
    _replace(tmp, target)


def _prune_empty_dirs(root, folder):
    root = Path(root)
    while folder != root and folder.is_dir():
        rel = folder.relative_to(root).as_posix() + '/'
        if not rel.startswith(SCOPE_DIRS) or rel in SCOPE_DIRS:
            return
        try:
            folder.rmdir()                       # only succeeds when empty
        except OSError:
            return
        folder = folder.parent


def _clear_bytecode(root):
    for top in ('source', 'runtime', 'launcher'):
        base = Path(root) / top
        if not base.is_dir():
            continue
        for dirpath, dirnames, _files in os.walk(base):
            for d in list(dirnames):
                if d == '__pycache__':
                    shutil.rmtree(os.path.join(dirpath, d), ignore_errors=True)
                    dirnames.remove(d)


def restore_backup(root, backup_dir):
    """Put back the version the backup was taken from."""
    root, backup_dir = Path(root), Path(backup_dir)
    info = load_json(backup_dir / 'info.json', None)
    if not isinstance(info, dict):
        raise UpdateError('there is no backup to go back to')
    for rel in _read_lines(backup_dir / 'added.txt'):           # files the update added
        path = root / rel
        if safe_rel(rel) and in_scope(rel) and path.is_file():
            path.unlink()
            _prune_empty_dirs(root, path.parent)
    files = backup_dir / 'files'
    if files.is_dir():
        for path in sorted(files.rglob('*')):
            if path.is_file() and not path.name.endswith('.crb-new'):
                rel = path.relative_to(files).as_posix()
                if safe_rel(rel) and in_scope(rel):
                    _copy_in(path, root / rel)
    if info.get('manifest_missing'):
        try:
            (root / MANIFEST).unlink()
        except OSError:
            pass
    elif (backup_dir / MANIFEST).is_file():
        _copy_in(backup_dir / MANIFEST, root / MANIFEST)
    _clear_bytecode(root)
    return info


# ---------------------------------------------------------------------- libraries
def _venv_python(root):
    crb = Path(root) / '.crb'
    return crb / ('venv/Scripts/python.exe' if os.name == 'nt' else 'venv/bin/python')


def install_requirements(root):
    """Add/upgrade the libraries in requirements.txt in the app's own Python (uv, like the launcher).
    Returns (ok, message). Never wipes the environment: a failure leaves the old libraries usable."""
    root = Path(root)
    crb = root / '.crb'
    uv = crb / 'uv' / ('uv.exe' if os.name == 'nt' else 'uv')
    py = _venv_python(root)
    if not py.exists():
        return False, "the app's Python was not found"
    if not uv.exists():
        return False, 'the Python manager (uv) was not found'
    env = dict(os.environ, UV_PYTHON_INSTALL_DIR=str(crb / 'python'), UV_CACHE_DIR=str(crb / 'cache'))
    cmd = [str(uv), 'pip', 'install', '--python', str(py), '-r', str(root / 'requirements.txt'), '--quiet']
    try:
        run = subprocess.run(cmd, env=env, capture_output=True, timeout=1800, creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if run.returncode != 0:
        text = (run.stderr or run.stdout or b'').decode('utf-8', 'replace').strip()
        return False, text[-600:] or f'uv ended with code {run.returncode}'
    try:
        subprocess.run([str(uv), 'cache', 'clean', '--quiet'], env=env, capture_output=True, timeout=300,
                       creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        pass
    return True, ''


def update_stamp(root, old_sha, new_sha):
    """Keep the launcher's "libraries are installed for this requirements.txt" stamp in step, in the
    launcher's own format (bash: lowercase hash, PowerShell: uppercase), so it does not rebuild."""
    path = Path(root) / '.crb' / 'setup.stamp'
    try:
        raw = path.read_bytes()
    except OSError:
        return False
    cut = raw.find(b'|')
    if cut <= 0:
        return False
    stamp_hash = raw[:cut].decode('ascii', 'replace').strip().lstrip('﻿')
    if stamp_hash.lower() != str(old_sha).lower():
        return False
    new = new_sha.upper() if stamp_hash.isupper() else new_sha.lower()
    path.write_bytes(raw[:cut].replace(stamp_hash.encode('ascii'), new.encode('ascii')) + raw[cut:])
    return True


def _req_sha(root):
    path = Path(root) / 'requirements.txt'
    return sha256_file(path) if path.is_file() else ''


# ---------------------------------------------------------------------- starting the app
def launch_app(root, relaunch, version):
    """Open the app (runtime/run_bot.py) as its own process. Returns the Popen object."""
    root = Path(root)
    python = (relaunch or {}).get('python') or str(_venv_python(root))
    if os.name == 'nt' and python.lower().endswith('python.exe') and Path(python[:-10] + 'pythonw.exe').exists():
        python = python[:-10] + 'pythonw.exe'
    cmd = [python, str(root / 'runtime' / 'run_bot.py')] + [str(a) for a in (relaunch or {}).get('args') or []]
    out = open(state_dir(root) / 'last_start.log', 'wb')
    env = dict(os.environ)
    env[LAUNCH_ENV] = str(version)
    kwargs = dict(cwd=str(root), env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                  close_fds=True)
    if os.name == 'nt':
        kwargs['creationflags'] = _DETACHED
    else:
        kwargs['start_new_session'] = True
    try:
        return subprocess.Popen(cmd, **kwargs)
    finally:
        out.close()


def _start_log_tail(root, lines=6):
    try:
        text = (state_dir(root) / 'last_start.log').read_text(encoding='utf-8', errors='replace')
    except OSError:
        return ''
    keep = [ln for ln in text.splitlines() if ln.strip()]
    return ' | '.join(keep[-lines:])[-500:]


def wait_health(root, version, proc, since, timeout=HEALTH_SECONDS):
    """Wait until the app of `version` reports that its window is up. Returns (ok, why not)."""
    path = state_dir(root) / 'health.json'

    def healthy():
        h = load_json(path, {})
        return isinstance(h, dict) and h.get('version') == version and float(h.get('at') or 0) >= since - 2

    deadline = time.time() + timeout
    while time.time() < deadline:
        if healthy():
            return True, ''
        if proc is not None and proc.poll() is not None:
            time.sleep(1.5)
            if healthy():
                return True, ''
            tail = _start_log_tail(root)
            return False, f'it closed while starting (exit code {proc.returncode})' + (f': {tail}' if tail else '')
        time.sleep(0.5)
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
        except OSError:
            pass
    return False, f'its window did not open within {timeout} seconds'


def app_started(root, version, pid=None):
    """Called by the app once its window is up (see runtime/run_bot.py)."""
    root = Path(root)
    save_json(state_dir(root) / 'health.json', {'version': version, 'pid': pid or os.getpid(), 'at': time.time()})
    journal = load_json(state_dir(root) / 'journal.json', None)
    if not (isinstance(journal, dict) and journal.get('phase') == 'started' and journal.get('to') == version):
        return
    if _updater_busy(root):
        return                                   # the updater that opened this app finishes the job
    if _acquire_lock(root):
        try:
            _finish_ok(root, journal)
        finally:
            _release_lock(root)


def _update_windows_registry(root, version):
    """Show the new version in Windows' Apps list (installer installs only)."""
    if os.name != 'nt':
        return
    try:
        import winreg
        key = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\{609983BA-D322-4D3D-965A-25888F80AD99}_is1'
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as k:
            location, _kind = winreg.QueryValueEx(k, 'InstallLocation')
            here = os.path.normcase(os.path.abspath(str(root)))
            if os.path.normcase(os.path.abspath(str(location).rstrip('\\/'))) == here:
                winreg.SetValueEx(k, 'DisplayVersion', 0, winreg.REG_SZ, str(version))
    except OSError:
        pass


# ====================================================================== operations
def _begin(root, pending, from_dir=None):
    """Turn a request (pending.json) into a journal, the record of an operation in progress."""
    root = Path(root)
    st = state_dir(root)
    current = read_version(root)
    op = pending.get('op')
    if op == 'update':
        staging = Path(from_dir or pending.get('staging') or '')
        if from_dir is None and st.resolve() not in staging.resolve().parents:
            raise UpdateError('the staged update is not in the update folder')
        manifest = load_json(staging / MANIFEST, None)
        if not isinstance(manifest, dict):
            raise UpdateError('the staged update has no manifest')
        to = str(manifest.get('version') or '')
        if pending.get('to') and to != pending['to']:
            raise UpdateError(f'the staged update is {to}, not {pending["to"]}')
        verify_tree(staging, manifest)
        if not pending.get('allow_same') and not is_newer(to, current):
            raise UpdateError(f'version {current} is already installed (the update is {to})')
        backup = st / 'backup'
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)         # one undo step: the newest replaces it
        (backup / 'files').mkdir(parents=True)
        info = {'version': current, 'to': to, 'manifest_missing': not (root / MANIFEST).is_file(),
                'requirements_sha': _req_sha(root), 'created': time.time()}
        if (root / MANIFEST).is_file():
            shutil.copy2(root / MANIFEST, backup / MANIFEST)
        save_json(backup / 'info.json', info)
        journal = {'op': 'update', 'from': current, 'to': to, 'staging': str(staging)}
    elif op == 'rollback':
        info = load_json(st / 'backup' / 'info.json', None)
        if not isinstance(info, dict) or info.get('to') != current:
            raise UpdateError('there is no earlier version to go back to')
        journal = {'op': 'rollback', 'from': current, 'to': info.get('version') or '?'}
    else:
        raise UpdateError(f'unknown request {op!r}')
    journal.update(phase='files', relaunch=pending.get('relaunch'), old_req_sha=_req_sha(root),
                   starts=0, started_at=0, begun=time.time(), finalize=bool(pending.get('finalize')))
    save_json(st / 'journal.json', journal)
    try:
        (st / 'pending.json').unlink()
    except OSError:
        pass
    log(root, f"{'Updating' if journal['op'] == 'update' else 'Going back'} from {journal['from']} "
              f"to {journal['to']}")
    return journal


def _run(root, journal, launch, on_file=None):
    """Carry an operation on from its current phase. Returns LAUNCHED when it opened the app."""
    root = Path(root)
    st = state_dir(root)
    backup = st / 'backup'
    op = journal['op']
    if journal['phase'] == 'files':
        if op == 'update':
            staging = Path(journal['staging'])
            new_manifest = load_json(staging / MANIFEST, None)
            if not isinstance(new_manifest, dict):
                raise UpdateError('the staged update is gone')
            old_manifest = None if load_json(backup / 'info.json', {}).get('manifest_missing') \
                else load_json(backup / MANIFEST, None)
            stats = apply_files(root, staging, new_manifest, old_manifest, backup / 'files',
                                backup / 'added.txt', on_file)
            save_json(root / MANIFEST, new_manifest)
            log(root, 'Files: ' + ', '.join(f'{v} {k}' for k, v in stats.items() if v))
        else:
            restore_backup(root, backup)
        _clear_bytecode(root)
        journal['phase'] = 'deps'
        save_json(st / 'journal.json', journal)
    if journal['phase'] == 'deps':
        new_sha = _req_sha(root)
        if new_sha and new_sha != journal.get('old_req_sha'):
            log(root, 'requirements.txt changed: installing the new libraries')
            ok, why = install_requirements(root)
            if ok:
                update_stamp(root, journal.get('old_req_sha') or '', new_sha)
                journal['deps_installed'] = True
                journal['new_req_sha'] = new_sha
            elif op == 'update':
                return _fail(root, journal, f'the new libraries could not be installed ({why})', launch)
            else:
                log(root, f'Could not reinstall the earlier libraries: {why}')
        _update_windows_registry(root, journal['to'])
        journal['phase'] = 'started'
        save_json(st / 'journal.json', journal)
        if journal.get('finalize'):
            _finish_ok(root, journal)
            return 0
    if journal['phase'] == 'started':
        if not launch:
            return 0                       # the app is about to start in this very process
        journal['starts'] = int(journal.get('starts') or 0) + 1
        journal['started_at'] = time.time()
        save_json(st / 'journal.json', journal)
        log(root, f"Opening Clash Rekt Bot {journal['to']}")
        try:
            proc = launch_app(root, journal.get('relaunch'), journal['to'])
        except OSError as exc:
            return _fail(root, journal, f'it could not be started ({exc})', launch)
        ok, why = wait_health(root, journal['to'], proc, journal['started_at'])
        if ok:
            _finish_ok(root, journal)
            return LAUNCHED
        if op == 'update':
            return _fail(root, journal, why, launch)
        _result(root, op, journal['from'], journal['to'], False, f'Version {journal["to"]} did not open: {why}')
        _cleanup(root, journal)
        return LAUNCHED
    return 0


def _finish_ok(root, journal):
    root = Path(root)
    if journal['op'] == 'update' and journal['from'] == journal['to']:
        _cleanup(root, journal)                  # reinstall of the same version: nothing to announce
        return
    if journal['op'] == 'update':
        message = f"Updated from {journal['from']} to {journal['to']}"
    else:
        _mark_bad(root, journal['from'], 'you went back to the previous version')
        shutil.rmtree(state_dir(root) / 'backup', ignore_errors=True)
        message = f"Went back from {journal['from']} to {journal['to']}"
    _result(root, journal['op'], journal['from'], journal['to'], True, message)
    _cleanup(root, journal)


def _cleanup(root, journal):
    st = state_dir(root)
    for name in ('journal.json', 'pending.json'):
        try:
            (st / name).unlink()
        except OSError:
            pass
    staging = journal.get('staging')
    if staging and st.resolve() in Path(staging).resolve().parents:
        shutil.rmtree(staging, ignore_errors=True)
    shutil.rmtree(st / 'downloads', ignore_errors=True)


def _fail(root, journal, why, launch):
    """The update did not work: put the previous version back (and open it)."""
    root = Path(root)
    st = state_dir(root)
    log(root, f"Update to {journal['to']} failed: {why}. Going back to {journal['from']}")
    restore_ok = True
    try:
        restore_backup(root, st / 'backup')
        if journal.get('deps_installed'):
            ok, msg = install_requirements(root)
            if ok:
                update_stamp(root, journal.get('new_req_sha') or '', _req_sha(root))
            else:
                log(root, f'Could not reinstall the earlier libraries: {msg}')
        shutil.rmtree(st / 'backup', ignore_errors=True)
    except Exception as exc:                               # noqa: BLE001 - keep going: tell the user
        restore_ok = False
        log(root, f'Putting the previous version back failed: {exc}\n{traceback.format_exc()}')
    _mark_bad(root, journal['to'], why)
    message = f"The update to {journal['to']} did not work ({why})."
    message += f" Version {journal['from']} was put back." if restore_ok else \
        ' Putting the previous version back also failed: please reinstall from the Releases page.'
    _result(root, 'update', journal['from'], journal['to'], False, message)
    _cleanup(root, journal)
    if launch and restore_ok:
        try:
            proc = launch_app(root, journal.get('relaunch'), journal['from'])
            ok, why_old = wait_health(root, journal['from'], proc, time.time())
            if not ok:
                log(root, f"Version {journal['from']} did not open either: {why_old}")
            return LAUNCHED
        except OSError as exc:
            log(root, f'Could not open the app: {exc}')
    return 0


# ====================================================================== entry points
def startup_hook(root):
    """Called by runtime/run_bot.py before the app imports anything of its own. Returns
      'go'       open the app;
      'exit'     do not open it (an updater is busy and opens it itself);
      'restart'  files were changed in this process: start again so the right code runs."""
    try:
        return _startup_hook(Path(root))
    except Exception as exc:                                       # noqa: BLE001 - never block a start
        try:
            log(root, f'Checking for a cut-off update failed: {exc}\n{traceback.format_exc()}')
        except Exception:                                          # noqa: BLE001
            pass
        return 'go'


def _startup_hook(root):
    st = state_dir(root)
    journal = load_json(st / 'journal.json', None)
    pending = load_json(st / 'pending.json', None)
    if not isinstance(journal, dict) and not isinstance(pending, dict):
        return 'go'
    if isinstance(journal, dict) and os.environ.get(LAUNCH_ENV) == journal.get('to'):
        return 'go'                                   # opened by the updater: it watches this start
    if _updater_busy(root):
        log(root, 'An update is being installed; Clash Rekt Bot opens by itself when it is done')
        return 'exit'
    health = load_json(st / 'health.json', {}) or {}
    if _app_open(health):
        return 'go'                                   # the app is already open: leave the update alone
    if not _acquire_lock(root):
        return 'exit'
    try:
        if isinstance(journal, dict) and journal.get('phase') == 'started':
            h_ok = health.get('version') == journal.get('to') and \
                float(health.get('at') or 0) >= float(journal.get('started_at') or 0) - 2
            if h_ok:
                _finish_ok(root, journal)
                return 'go'
            if journal['op'] == 'update' and int(journal.get('starts') or 0) >= 1:
                _fail(root, journal, 'its window did not open the last time', launch=False)
                return 'restart'
            journal['starts'] = int(journal.get('starts') or 0) + 1
            journal['started_at'] = time.time()
            save_json(st / 'journal.json', journal)
            return 'go'
        if isinstance(journal, dict):
            log(root, f"Finishing the cut-off {journal['op']} to {journal['to']}")
        else:
            try:
                journal = _begin(root, pending)
            except UpdateError as exc:
                log(root, f'The waiting update cannot be installed: {exc}')
                _result(root, pending.get('op') or 'update', read_version(root), pending.get('to') or '?',
                        False, f'The update could not be installed: {exc}')
                _cleanup(root, {'staging': pending.get('staging')})
                return 'go'
        _run(root, journal, launch=False)
        journal = load_json(st / 'journal.json', None)
        if isinstance(journal, dict) and journal.get('phase') == 'started':
            journal['starts'] = int(journal.get('starts') or 0) + 1
            journal['started_at'] = time.time()
            save_json(st / 'journal.json', journal)
        return 'restart'
    finally:
        _release_lock(root)


def cmd_apply(root, wait_pid=None):
    root = Path(root)
    if not _acquire_lock(root):
        log(root, 'Another update is already running')
        return 2
    try:
        if wait_pid and not wait_for_exit(wait_pid, WAIT_FOR_APP_SECONDS):
            log(root, 'The app did not close: the update will be installed the next time it starts')
            return 3
        st = state_dir(root)
        journal = load_json(st / 'journal.json', None)
        if not isinstance(journal, dict):
            pending = load_json(st / 'pending.json', None)
            if not isinstance(pending, dict):
                log(root, 'Nothing to do')
                return 0
            try:
                journal = _begin(root, pending)
            except UpdateError as exc:
                to = pending.get('to') or '?'
                _result(root, pending.get('op') or 'update', read_version(root), to, False,
                        f'The update could not be installed: {exc}')
                _cleanup(root, {'staging': pending.get('staging')})
                try:
                    launch_app(root, pending.get('relaunch'), read_version(root))
                    return LAUNCHED
                except OSError:
                    return 1
        return _run(root, journal, launch=True)
    except Exception as exc:                                       # noqa: BLE001
        log(root, f'The updater failed: {exc}\n{traceback.format_exc()}')
        journal = load_json(state_dir(root) / 'journal.json', None)
        if isinstance(journal, dict) and journal.get('op') == 'update':
            return _fail(root, journal, f'the updater failed ({exc})', launch=True)
        try:
            launch_app(root, (journal or {}).get('relaunch') if isinstance(journal, dict) else None,
                       read_version(root))
            return LAUNCHED
        except OSError:
            return 1
    finally:
        _release_lock(root)


def cmd_resume(root):
    return {'go': 0, 'restart': 0, 'exit': 2}[startup_hook(Path(root))]


def cmd_install_dir(source, root):
    """Install a newer app folder (macOS .app / Linux .deb payload) over a per-user copy."""
    root = Path(root)
    if not _acquire_lock(root):
        log(root, 'An update is running: try again in a minute')
        return 2
    try:
        old = load_json(state_dir(root) / 'journal.json', None)
        if isinstance(old, dict):                  # finish what was cut off first, then replace it
            try:
                _run(root, old, launch=False)
            except Exception as exc:               # noqa: BLE001
                log(root, f'Could not finish the earlier update ({exc}); installing over it')
            _cleanup(root, old)
        journal = _begin(root, {'op': 'update', 'allow_same': True, 'finalize': True}, from_dir=source)
        return _run(root, journal, launch=False)
    except UpdateError as exc:
        log(root, f'Could not install from {source}: {exc}')
        return 1
    finally:
        _release_lock(root)


def verify_package(zip_path):
    """Raise UpdateError unless `zip_path` is a sound update package. Returns its manifest."""
    with zipfile.ZipFile(zip_path) as z:
        infos = [i for i in z.infolist() if not i.is_dir()]
        if len(infos) > MAX_PACKAGE_FILES or sum(i.file_size for i in infos) > MAX_PACKAGE_BYTES:
            raise UpdateError('the update is too big')
        try:
            manifest = json.loads(z.read(MANIFEST).decode('utf-8'))
        except (KeyError, ValueError):
            raise UpdateError('the update has no manifest')
        files = manifest.get('files') or {}
        names = {i.filename for i in infos} - {MANIFEST}
        if names != set(files):
            raise UpdateError('the update and its file list do not match')
        for info in infos:
            if info.filename == MANIFEST:
                continue
            if not (safe_rel(info.filename) and in_scope(info.filename)):
                raise UpdateError(f'the update has a file outside the app: {info.filename!r}')
            h = hashlib.sha256()
            with z.open(info) as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b''):
                    h.update(chunk)
            if h.hexdigest() != files[info.filename].get('sha256'):
                raise UpdateError(f'the update is damaged ({info.filename})')
        version = str(manifest.get('version') or '')
        inside = z.read('VERSION').decode('utf-8').strip() if 'VERSION' in names else ''
        if not version or inside != version:
            raise UpdateError('the update has no matching VERSION file')
    return manifest


def main(argv):
    import argparse
    parser = argparse.ArgumentParser(prog='engine.py', description='Clash Rekt Bot update engine')
    sub = parser.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('apply')
    p.add_argument('--root', required=True)
    p.add_argument('--wait-pid', type=int, default=0)
    p = sub.add_parser('resume')
    p.add_argument('--root', required=True)
    p = sub.add_parser('install-dir')
    p.add_argument('--source', required=True)
    p.add_argument('--root', required=True)
    p = sub.add_parser('manifest')
    p.add_argument('--root', required=True)
    p.add_argument('--version', default=None)
    p.add_argument('--out', default=None)
    p = sub.add_parser('verify')
    p.add_argument('zip')
    args = parser.parse_args(argv)
    if args.cmd == 'apply':
        return cmd_apply(Path(args.root), args.wait_pid)
    if args.cmd == 'resume':
        return cmd_resume(Path(args.root))
    if args.cmd == 'install-dir':
        return cmd_install_dir(Path(args.source), Path(args.root))
    if args.cmd == 'manifest':
        manifest = build_manifest(Path(args.root), args.version)
        out = Path(args.out) if args.out else Path(args.root) / MANIFEST
        save_json(out, manifest)
        print(f"{len(manifest['files'])} files, version {manifest['version']} -> {out}")
        return 0
    if args.cmd == 'verify':
        try:
            manifest = verify_package(args.zip)
        except (UpdateError, zipfile.BadZipFile) as exc:
            print(f'NOT OK: {exc}')
            return 1
        print(f"OK: version {manifest['version']}, {len(manifest['files'])} files")
        return 0
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
