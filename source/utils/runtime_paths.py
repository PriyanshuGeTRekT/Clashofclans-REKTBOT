# Reconstructed from Pyarmor-decrypted bytecode (utils.runtime_paths, Python 3.10).
from pathlib import Path
import sys, os


def is_frozen():
    return bool(getattr(sys, 'frozen', False))


def bundle_root():
    if is_frozen() and hasattr(sys, '_MEIPASS'):
        return Path(getattr(sys, '_MEIPASS'))
    return Path(__file__).resolve().parent.parent


def app_root():
    launch_dir = os.environ.get('APP_LAUNCH_DIR')
    if launch_dir:
        return Path(launch_dir).resolve()
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resolve_resource_path(relative_path):
    path = Path(relative_path)
    if path.is_absolute():
        return path
    candidate = app_root() / path
    if candidate.exists():
        return candidate
    return bundle_root() / path


def resolve_writable_path(relative_path):
    path = Path(relative_path)
    if path.is_absolute():
        return path
    return app_root() / path


def resolve_external_resource_path(relative_path):
    path = Path(relative_path)
    if path.is_absolute():
        return path
    return app_root() / path


def ensure_runtime_dirs():
    for name in ('logs', 'profiles', 'treasureloot'):
        resolve_writable_path(name).mkdir(parents=True, exist_ok=True)


_STALE_TEMPDIR_MIN_AGE_SECONDS = 600


def _running_exe_paths():
    import psutil
    paths = []
    for proc in psutil.process_iter(['exe']):
        exe = proc.info.get('exe')
        if exe:
            paths.append(os.path.normcase(exe))
    return paths


def _remove_stale_tempdirs(folders):
    import shutil
    import time
    running = _running_exe_paths()
    now = time.time()
    for folder in folders:
        try:
            if now - folder.stat().st_mtime < _STALE_TEMPDIR_MIN_AGE_SECONDS:
                continue
            prefix = os.path.normcase(str(folder)) + os.sep
            # Skip dirs that still host a running executable
            if any(p.startswith(prefix) for p in running):
                continue
            shutil.rmtree(folder, ignore_errors=True)
        except Exception:
            continue


def cleanup_stale_onefile_tempdirs():
    try:
        import re
        import threading
        this_dir = Path(__file__).resolve().parent.parent
        # Only acts when running from an onefile extraction under ...\AutoClashBasicTemp\<n>_<n>\
        if this_dir.parent.name != 'AutoClashBasicTemp':
            return None
        pattern = re.compile('^\\d+_\\d+$')
        stale = [d for d in this_dir.parent.iterdir()
                 if d.name != this_dir.name and d.is_dir() and pattern.match(d.name)]
        if stale:
            threading.Thread(target=_remove_stale_tempdirs, args=(stale,),
                             name='stale-tempdir-cleanup', daemon=True).start()
    except Exception:
        pass
