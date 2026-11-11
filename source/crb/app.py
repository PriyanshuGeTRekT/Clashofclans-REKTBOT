# crb/app.py - start the Clash Rekt Bot GUI.
import os
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from crb import icons, theme

ASSETS = os.path.join(os.path.dirname(__file__), 'assets')


def _app_icon():
    """Window/taskbar icon rendered from the logo (cached as runtime/assets/crb_icon.*)."""
    from utils.runtime_paths import resolve_resource_path
    out_dir = str(resolve_resource_path('assets'))
    ico = os.path.join(out_dir, 'crb_icon.ico')
    png = os.path.join(out_dir, 'crb_icon.png')
    logo = os.path.join(ASSETS, 'logo.svg')
    try:
        if not os.path.exists(png) or os.path.getmtime(png) < os.path.getmtime(logo):
            icons.write_app_icons(logo, out_dir)
    except Exception as exc:
        print(f'[CRB] could not write the app icon: {exc}')
    return QIcon(ico if os.name == 'nt' and os.path.exists(ico) else png)


def _set_app_id():
    if os.name == 'nt':
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('ClashRektBot.App')
        except Exception:
            pass


def create_app():
    _set_app_id()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(theme.APP_NAME)
    app.setApplicationDisplayName(theme.APP_NAME)
    from utils.runtime_paths import ensure_runtime_dirs, resolve_resource_path
    ensure_runtime_dirs()
    theme.load_fonts(str(resolve_resource_path('assets')))
    app.setWindowIcon(_app_icon())
    return app


def cleanup_children():
    """End helper processes the bot started (adb readers, popup watcher) but never the emulator."""
    try:
        import psutil
        import startup
        keep = {n.lower() for cfg in startup.EMULATOR_CONFIGS.values() for n in cfg['process_names']}

        def is_emulator(p):
            try:
                return (p.name() or '').lower() in keep
            except Exception:
                return False
        kids = [c for c in psutil.Process(os.getpid()).children(recursive=True) if not is_emulator(c)]
        for c in kids:
            try:
                c.terminate()
            except Exception:
                pass
        psutil.wait_procs(kids, timeout=3)
    except Exception:
        pass


def run(window_hook=None):
    app = create_app()
    from crb.window import MainWindow
    window = MainWindow()
    if window_hook:
        window_hook(window)
    window.show()
    code = app.exec()
    cleanup_children()
    # uiautomator2's reader thread sits in a native read until its adb child (just ended above) closes;
    # give it a moment, and keep faulthandler from logging the process teardown itself (an access
    # violation reported while os._exit unloads modules under a blocked thread, 11 Nov). All state is
    # saved by now.
    import time
    time.sleep(0.5)
    try:
        import faulthandler
        faulthandler.disable()
    except Exception:
        pass
    os._exit(code)
