# ui/gui.py -- GUI entry point; reconstructed from Pyarmor-decrypted CPython 3.10 bytecode
# (decrypted/ui.gui.dis.txt). Local names were obfuscated and are renamed.
import os
import sys
import ctypes


def bootstrap_external_ui2_data():
    # When frozen, point uiautomator2 at <exe dir>/Tools/uiautomator2_data if present.
    if not getattr(sys, 'frozen', False):
        return
    exe_dir = os.path.dirname(sys.executable)
    ui2_data = os.path.join(exe_dir, 'Tools', 'uiautomator2_data')
    if not os.path.isdir(ui2_data):
        return
    os.environ['UIAUTOMATOR2_DATA'] = ui2_data
    os.environ.setdefault('APP_LAUNCH_DIR', exe_dir)


bootstrap_external_ui2_data()
os.environ.setdefault('APP_LAUNCH_DIR', os.getcwd())

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from main_window import MainWindow

if getattr(sys, 'frozen', False):
    base_dir = os.path.dirname(sys.executable)
else:
    base_dir = os.path.dirname(os.path.dirname(__file__))
sys.path.append(base_dir)

from utils.runtime_paths import ensure_runtime_dirs, resolve_resource_path, cleanup_stale_onefile_tempdirs


def get_app_icon():
    if os.name == 'nt':
        ico = resolve_resource_path('assets/icon.ico')
        if ico.exists():
            return QIcon(str(ico))
    png = resolve_resource_path('assets/icon.png')
    if png.exists():
        return QIcon(str(png))
    if getattr(sys, 'frozen', False):
        return QIcon(str(sys.executable))
    return QIcon()


def set_windows_app_user_model_id():
    if os.name != 'nt':
        return
    if getattr(sys, 'frozen', False):
        return
    app_id = 'MysticTech.AutoClashBasic'
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        pass


def run():
    set_windows_app_user_model_id()
    app = QApplication(sys.argv)
    app.setApplicationName('ACBot Basic')
    app.setWindowIcon(get_app_icon())
    ensure_runtime_dirs()
    cleanup_stale_onefile_tempdirs()
    window = MainWindow()
    window.show()
    exit_code = app.exec()
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    # On exit: terminate every child process of this process (recursive), wait up to 3 s,
    # then hard-exit with the Qt exit code.
    try:
        import psutil
        # FIX: an emulator the bot launched is a child process too, so closing the bot window also
        # killed MEmu / BlueStacks (MEmu VM log: powered off the moment the bot exited). Leave
        # emulator processes alone; the launcher also detaches them now (startup.launch_emulator).
        try:
            import startup
            keep = {n.lower() for cfg in startup.EMULATOR_CONFIGS.values() for n in cfg['process_names']}
        except Exception:
            keep = set()
        def _is_emulator(proc):
            try:
                return (proc.name() or '').lower() in keep
            except Exception:
                return False
        children = [c for c in psutil.Process(os.getpid()).children(recursive=True) if not _is_emulator(c)]
        for child in children:
            try:
                child.terminate()
            except Exception:
                pass
        psutil.wait_procs(children, timeout=3)
    except Exception:
        pass
    os._exit(exit_code)


if __name__ == '__main__':
    run()
