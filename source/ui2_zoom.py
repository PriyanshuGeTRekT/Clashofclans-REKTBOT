# ACBot Basic v1.6.7 - ui2_zoom: uiautomator2-based gestures (multi-touch pinch zoom-out, swipe, drag).
# Reconstructed from Pyarmor-decrypted bytecode (ui2_zoom, Python 3.10).
#
# Local variable names were obfuscated (_var_var_N) and have been renamed; function, argument,
# attribute and global names are original.  Nested function `B` keeps its (minified) name.
import time
import sys
import os
import contextlib
import importlib.util
from pathlib import Path
import adb

# RECON: these three were stored with STORE_GLOBAL at module level (module-scope `global` decl).
_EXTERNAL_UI2_DIR = None
u2 = None
RPCUnknownError = Exception  # placeholder until uiautomator2.exceptions.RPCUnknownError is imported
UI2_DEBUG = False


def _ui2_log(message):
    if UI2_DEBUG:
        print(f'[UI2] {message}')


def _setup_external_ui2_if_frozen():
    """Locate an external 'Tools/uiautomator2_data' folder (bundled uiautomator2 package + assets)."""
    global _EXTERNAL_UI2_DIR
    candidates = []
    launch_dir = os.environ.get('APP_LAUNCH_DIR')
    if launch_dir:
        candidates.append(Path(launch_dir) / 'Tools' / 'uiautomator2_data')
    candidates.append(Path(sys.argv[0]).resolve().parent / 'Tools' / 'uiautomator2_data')
    candidates.append(Path.cwd() / 'Tools' / 'uiautomator2_data')
    if getattr(sys, 'frozen', False):
        candidates.append(Path(sys.executable).parent / 'Tools' / 'uiautomator2_data')
    _ui2_log('External data lookup candidates:')
    for idx, cand in enumerate(candidates, start=1):
        _ui2_log(f'  {idx}. {cand}')
    for cand in candidates:
        if cand.exists() and cand.is_dir():
            _EXTERNAL_UI2_DIR = cand
            os.environ['UIAUTOMATOR2_DATA'] = str(cand)
            _ui2_log(f'Using external data folder: {cand}')
            break
    if _EXTERNAL_UI2_DIR is None:
        _ui2_log('No external uiautomator2_data folder found; using package resources')
    return _EXTERNAL_UI2_DIR


def _patch_uiautomator2_resource_lookup():
    """Redirect uiautomator2's with_package_resource() to files in the external folder when present."""
    if _EXTERNAL_UI2_DIR is None:
        return
    try:
        import uiautomator2.utils as ui2_utils
        import uiautomator2.core as ui2_core
    except Exception as e:
        _ui2_log(f'Could not patch resource lookup: {e}')
        return
    original = ui2_utils.with_package_resource

    @contextlib.contextmanager
    def B(filename):
        name = filename
        external = _EXTERNAL_UI2_DIR / name
        if external.exists():
            yield external
            return
        with original(name) as res:
            yield res

    ui2_utils.with_package_resource = B
    ui2_core.with_package_resource = B
    _ui2_log('Patched resource lookup for external assets')


def _import_external_uiautomator2():
    """Load the uiautomator2 package from <_EXTERNAL_UI2_DIR>/__init__.py, replacing any cached copy."""
    global u2, RPCUnknownError
    if _EXTERNAL_UI2_DIR is None:
        return False
    init_py = _EXTERNAL_UI2_DIR / '__init__.py'
    if not init_py.exists():
        _ui2_log(f'External package missing: {init_py}')
        return False
    try:
        for mod_name in list(sys.modules.keys()):
            if mod_name == 'uiautomator2' or mod_name.startswith('uiautomator2.'):
                del sys.modules[mod_name]
        spec = importlib.util.spec_from_file_location(
            'uiautomator2', str(init_py),
            submodule_search_locations=[str(_EXTERNAL_UI2_DIR)])
        if spec is None or spec.loader is None:
            _ui2_log('Failed to build module spec for external uiautomator2')
            return False
        module = importlib.util.module_from_spec(spec)
        sys.modules['uiautomator2'] = module
        spec.loader.exec_module(module)
        u2 = module
        from uiautomator2.exceptions import RPCUnknownError as _rpc_err
        RPCUnknownError = _rpc_err
        _ui2_log(f'Loaded external package from: {_EXTERNAL_UI2_DIR}')
        return True
    except Exception as e:
        _ui2_log(f'External package import failed: {e}')
        return False


def _ensure_uiautomator2_ready():
    global u2, RPCUnknownError
    if u2 is not None:
        return True
    _setup_external_ui2_if_frozen()
    if _import_external_uiautomator2():
        _patch_uiautomator2_resource_lookup()
        return True
    try:
        import uiautomator2 as ui2_mod
        from uiautomator2.exceptions import RPCUnknownError as _rpc_err
    except Exception as e:
        _ui2_log(f'Import failed: {e}')
        return False
    u2 = ui2_mod
    RPCUnknownError = _rpc_err
    _patch_uiautomator2_resource_lookup()
    return True


def _get_device():
    if not _ensure_uiautomator2_ready():
        return None
    try:
        addr = adb.get_bluestacks_addr()
        return u2.connect(addr)
    except Exception as e:
        print('[ZOOM] Device connection failed:', e)
        return None


def _retry_gesture(gesture_func, retries=5, backoff=0.35, device=None):
    """Run gesture_func up to `retries` times with exponential backoff (x1.4).

    On RPCUnknownError mentioning INJECT_EVENTS / SecurityException / performMultiPointerGesture,
    sends a harmless 'input tap 5 5' via the device shell before retrying.
    """
    dev = device
    delay = backoff
    for _attempt in range(retries):
        try:
            gesture_func()
            return True
        except RPCUnknownError as e:
            msg = str(e)
            if ('INJECT_EVENTS' in msg or 'SecurityException' in msg
                    or 'performMultiPointerGesture' in msg) and dev is not None:
                try:
                    dev.shell('input tap 5 5')
                except Exception:
                    pass
            time.sleep(delay)
            delay *= 1.4
        except Exception:
            time.sleep(delay)
            delay *= 1.4
    return False


def swipe_ui2(x1, y1, x2, y2, duration=0.3):
    dur = duration
    d = _get_device()
    if d is None:
        print('[SWIPE] Device connection failed')
        return False
    print(f'[SWIPE] Swiping ({x1},{y1}) -> ({x2},{y2}) duration={dur}s')
    try:
        ok = _retry_gesture(lambda: d.swipe(x1, y1, x2, y2, duration=dur), device=d)
        if ok:
            print('[SWIPE] OK Swipe successful')
            return True
        print('[SWIPE] FAIL Swipe failed after retries')
        return False
    except Exception as e:
        print(f'[SWIPE] FAIL Swipe failed: {e}')
        return False


def drag_ui2(x1, y1, x2, y2, duration=0.8):
    d = _get_device()
    if d is None:
        print('[DRAG] Device connection failed')
        return False
    try:
        ok = _retry_gesture(lambda: d.drag(x1, y1, x2, y2, duration=duration), device=d)
        if ok:
            return True
        return False
    except Exception as e:
        print(f'[DRAG] FAIL Drag failed: {e}')
        return False


def _stage(d, timeout=5.0):
    """The game's GL view. Right after a launch the uiautomator hierarchy sometimes does not list it
    ('stage not found', 10/11 Nov); the app's root content view covers the same screen area."""
    stage = d(resourceId='com.supercell.clashofclans:id/stage')
    if stage.wait(exists=True, timeout=timeout):
        return stage
    root = d(resourceId='android:id/content')
    if root.wait(exists=True, timeout=1.0):
        print('[ZOOM_MULTI] stage not found, using the app root view')
        return root
    return None


def zoom_out_multi(offset_px=400, steps=20, debug=False):
    """Two-finger pinch-in (zoom out) on the Clash of Clans GL surface.

    Finger 1 stays at the stage centre; finger 2 starts `offset_px` to the right
    (clamped 8px inside the stage bounds) and moves to the centre.
    """
    n_steps = steps
    d = _get_device()
    if d is None:
        print('[ZOOM_MULTI] Device connection failed')
        return False
    try:
        # FIX: the original checked `stage.exists` once; right after a battle -> home transition the
        # view hierarchy is still rebuilding, so wait briefly for the GL stage view instead of giving up.
        t0 = time.time()
        stage = _stage(d)
        if stage is None:
            print('[ZOOM_MULTI] stage not found after 5s')
            return False
        waited = time.time() - t0
        if waited > 0.5:
            print(f'[ZOOM_MULTI] stage appeared after {waited:.1f}s')
        info = stage.info or {}
        bounds = info.get('bounds') or {}
        left = int(bounds.get('left', 0))
        right = int(bounds.get('right', 1600))
        top = int(bounds.get('top', 0))
        bottom = int(bounds.get('bottom', 900))
        cx = (left + right) // 2
        cy = (top + bottom) // 2
        sx2 = min(right - 8, max(left + 8, cx + int(offset_px)))
        sy2 = cy
        if debug:
            print(f'[ZOOM_MULTI] center=({cx},{cy}) start2=({sx2},{sy2}) steps={n_steps}')
        # UiObject.gesture(start1, start2, end1, end2, steps)
        ok = _retry_gesture(
            lambda: stage.gesture((cx, cy), (sx2, sy2), (cx, cy), (cx, cy), steps=int(n_steps)),
            device=d)
        if ok:
            time.sleep(0.35)
            return True
    except Exception as e:
        print(f'[ZOOM_MULTI] FAIL: {e}')
    return False


def zoom_out(debug=False):
    try:
        import zoomnorm
        zoomnorm.reset_world_scale()     # a plain zoom-out is not a normalised home view
    except Exception:
        pass
    return zoom_out_multi(debug=debug)


# Pinch response of the game (11 Nov, MEmu): non-linear with a dead zone (10 px did nothing,
# 90 px gave x1.8, 110 px x2.3), so zoomnorm calibrates one spread length per scenery.


def _pinch(spread_from, spread_to, debug=False):
    d = _get_device()
    if d is None:
        print('[ZOOM_MULTI] Device connection failed')
        return False
    try:
        stage = _stage(d)
        if stage is None:
            print('[ZOOM_MULTI] stage not found after 5s')
            return False
        b = (stage.info or {}).get('bounds') or {}
        cx = (int(b.get('left', 0)) + int(b.get('right', 1600))) // 2
        cy = (int(b.get('top', 0)) + int(b.get('bottom', 900))) // 2
        a, z = int(spread_from), int(spread_to)
        if debug:
            print(f'[ZOOM_MULTI] pinch {a}px -> {z}px')
        ok = _retry_gesture(
            lambda: stage.gesture((cx - a, cy), (cx + a, cy), (cx - z, cy), (cx + z, cy), steps=20),
            device=d)
        if ok:
            time.sleep(0.5)
            return True
    except Exception as e:
        print(f'[ZOOM_MULTI] pinch FAIL: {e}')
    return False


def zoom_out_home(vision, debug=False):
    """Zoom out, then zoom back in to the reference scale when the home scenery zooms out further
    than the classic one (zoomnorm.py). Use at the home village only."""
    ok = zoom_out_multi(debug=debug)
    try:
        import zoomnorm
        if zoomnorm.enabled() and vision is not None:
            zoomnorm.normalize(vision, zoom_out_full=lambda: zoom_out_multi(debug=debug),
                               spread=lambda px: _pinch(60, 60 + px, debug), label='home: ')
    except Exception as e:
        print(f'[ZOOM] scale check failed: {e.__class__.__name__}: {e}')
    return ok
