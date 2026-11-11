"""Launch the reconstructed ACBot GUI from source, with diagnostics.

The original Nuitka build exposed every module at top level (e.g. `main_window`,
`bot_worker`) as well as under `ui.`, so both `source/` and `source/ui/` go on
sys.path. This folder is the app root: templates/, assets/, Tools/, profiles/,
logs/ and bot.config live here.

Diagnostics (written to logs/diagnostics-<stamp>.log, never into the source):
  * full tracebacks for exceptions escaping the bot thread, other threads and the
    main thread (the bot's own session log only keeps a one-line message);
  * Qt warnings/criticals;
  * native crashes via faulthandler (logs/faults-<stamp>.log);
  * bot start/stop transitions.

Options:
  --autostart            press Start once the window is up
  --auto-restart N       after an unexpected stop, press Start again (at most N
                         times per 30 minutes, 30 s after the stop); 0 disables
"""
import argparse
import datetime
import faulthandler
import os
import sys
import threading
import time
import traceback
from pathlib import Path

RUNTIME = Path(__file__).resolve().parent
SOURCE = RUNTIME.parent / "source"

os.environ["APP_LAUNCH_DIR"] = str(RUNTIME)
os.environ.setdefault("UIAUTOMATOR2_DATA", str(RUNTIME / "Tools" / "uiautomator2_data"))
sys.path[:0] = [str(SOURCE), str(SOURCE / "ui")]
os.chdir(RUNTIME)

LOGS = RUNTIME / "logs"
STAMP = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
DIAG_PATH = LOGS / f"diagnostics-{STAMP}.log"
_diag_lock = threading.Lock()
_diag = None  # opened in main(); multiprocessing children re-import this file and must not log


def _open_diagnostics():
    global _diag
    LOGS.mkdir(exist_ok=True)
    _diag = open(DIAG_PATH, "a", encoding="utf-8", buffering=1)
    faults = open(LOGS / f"faults-{STAMP}.log", "a", encoding="utf-8")
    faulthandler.enable(faults, all_threads=True)


def diag(kind, text):
    if _diag is None:
        return
    line = f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} [{kind}] {text}"
    with _diag_lock:
        _diag.write(line.rstrip("\n") + "\n")


def _excepthook(exc_type, exc, tb):
    diag("UNCAUGHT", "".join(traceback.format_exception(exc_type, exc, tb)))
    sys.__excepthook__(exc_type, exc, tb)


def _thread_excepthook(args):
    name = args.thread.name if args.thread else "?"
    diag("THREAD", f"thread={name}\n" + "".join(
        traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))


sys.excepthook = _excepthook
threading.excepthook = _thread_excepthook


def _install_worker_hooks():
    """Wrap BotWorker.run so an escaping exception keeps its traceback."""
    import bot_worker  # top-level alias used by main_window

    for mod in {bot_worker, sys.modules.get("ui.bot_worker")} - {None}:
        cls = mod.BotWorker
        if getattr(cls, "_diag_wrapped", False):
            continue
        original_run = cls.run

        def run(self, _original=original_run):
            diag("BOT", "worker started")
            try:
                _original(self)
                diag("BOT", "worker returned normally")
            except BaseException:
                diag("BOT-CRASH", traceback.format_exc())
                print("[DIAG] Bot thread crashed; full traceback in " + DIAG_PATH.name)
                raise

        cls.run = run
        cls._diag_wrapped = True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--autostart", action="store_true")
    parser.add_argument("--auto-restart", type=int, default=0)
    parser.add_argument("--classic", action="store_true", help="open the old ACBot window instead")
    opts = parser.parse_args()
    sys.argv = sys.argv[:1]  # keep Qt from seeing our flags
    _open_diagnostics()

    from PySide6.QtCore import QTimer, qInstallMessageHandler, QtMsgType

    def qt_handler(mode, context, message):
        if mode in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
            diag("QT", f"{mode.name}: {message}")

    qInstallMessageHandler(qt_handler)
    _install_worker_hooks()

    diag("LAUNCH", f"python={sys.version.split()[0]} autostart={opts.autostart} "
                   f"auto_restart={opts.auto_restart} classic={opts.classic} pid={os.getpid()}")

    if not opts.classic:
        _run_crb(opts)
        return

    import main_window
    from ui import gui

    # MainWindow is created inside gui.run(); hook its __init__ to reach the instance.
    state = {"user_stop": False, "restarts": []}
    original_init = main_window.MainWindow.__init__

    def init(self, *a, **kw):
        original_init(self, *a, **kw)
        original_stop = self.stop_bot

        def stop_bot(*sa, **skw):
            state["user_stop"] = True
            diag("BOT", "stop requested from GUI")
            return original_stop(*sa, **skw)

        self.stop_bot = stop_bot
        try:  # re-point the Stop button at the wrapper
            self.stop_btn.clicked.disconnect()
            self.stop_btn.clicked.connect(stop_bot)
        except Exception as e:
            diag("WARN", f"could not rewire Stop button: {e}")

        def on_status(status):
            diag("STATUS", status)

        def on_finished():
            # Fires on normal return, crash (run() raised, so no 'Stopped' status) and terminate().
            diag("BOT", "worker thread finished")
            if not opts.auto_restart:
                return
            if state["user_stop"]:
                state["user_stop"] = False
                return
            now = time.time()
            state["restarts"] = [t for t in state["restarts"] if now - t < 1800]
            if len(state["restarts"]) >= opts.auto_restart:
                diag("BOT", "auto-restart limit reached; leaving bot stopped")
                print("[DIAG] Auto-restart limit reached; bot left stopped")
                return
            state["restarts"].append(now)
            diag("BOT", f"unexpected stop; auto-restart {len(state['restarts'])}/{opts.auto_restart} in 30 s")
            print("[DIAG] Unexpected stop; restarting in 30 s")
            QTimer.singleShot(30000, self.start_bot)

        self.worker.status.connect(on_status)
        self.worker.finished.connect(on_finished)
        if opts.autostart:
            diag("BOT", "autostart in 3 s")
            QTimer.singleShot(3000, self.start_bot)

    main_window.MainWindow.__init__ = init

    # Qt dispatches closeEvent as a virtual, so patch it on the class.
    original_close = main_window.MainWindow.closeEvent

    def close_event(self, event):
        state["user_stop"] = True
        diag("BOT", "window closing")
        return original_close(self, event)

    main_window.MainWindow.closeEvent = close_event
    gui.MainWindow = main_window.MainWindow
    gui.run()


def _run_crb(opts):
    """Clash Rekt Bot window (crb package) with the same diagnostics / autostart / auto-restart."""
    from PySide6.QtCore import QTimer
    import crb.app

    state = {"restarts": []}

    def hook(win):
        win.worker.status.connect(lambda s: diag("STATUS", s))

        def on_finished():
            diag("BOT", "worker thread finished")
            if not opts.auto_restart or getattr(win, "user_stop", False):
                return
            now = time.time()
            state["restarts"] = [t for t in state["restarts"] if now - t < 1800]
            if len(state["restarts"]) >= opts.auto_restart:
                diag("BOT", "auto-restart limit reached; leaving bot stopped")
                print("[DIAG] Auto-restart limit reached; bot left stopped")
                return
            state["restarts"].append(now)
            diag("BOT", f"unexpected stop; auto-restart {len(state['restarts'])}/{opts.auto_restart} in 30 s")
            print("[DIAG] Unexpected stop; restarting in 30 s")
            QTimer.singleShot(30000, win.start_bot)

        win.worker.finished.connect(on_finished)
        if opts.autostart:
            diag("BOT", "autostart in 3 s")
            QTimer.singleShot(3000, win.start_bot)

    crb.app.run(hook)


if __name__ == "__main__":
    main()
