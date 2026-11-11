# Reconstructed from Pyarmor-decrypted bytecode (ui.bot_worker, Python 3.10).
# Qt worker thread that runs main.main() with stdout/stderr tee'd into a
# per-session log file under <writable>/logs/.
import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from PySide6.QtCore import QThread, Signal
import control
import main
from stats import Stats
import time
from datetime import datetime, timedelta
import threading
import re
from utils.runtime_paths import resolve_writable_path

BASE_STDOUT = sys.__stdout__ if hasattr(sys, '__stdout__') and sys.__stdout__ else sys.stdout
BASE_STDERR = sys.__stderr__ if hasattr(sys, '__stderr__') and sys.__stderr__ else sys.stderr


class TeeStream:
    def __init__(A, *B):
        A.streams = B
        A._lock = threading.Lock()

    def write(A, data):
        # timeout: a lock left held by a killed thread must not block every later print()
        got = A._lock.acquire(timeout=1.0)
        try:
            for s in A.streams:
                try:
                    s.write(data)
                except Exception:
                    pass
        finally:
            if got:
                A._lock.release()

    def flush(A):
        got = A._lock.acquire(timeout=1.0)
        try:
            for s in A.streams:
                try:
                    s.flush()
                except Exception:
                    pass
        finally:
            if got:
                A._lock.release()

    @property
    def encoding(self):
        for s in self.streams:
            if hasattr(s, 'encoding'):
                return s.encoding
        return 'utf-8'


class BotWorker(QThread):
    status = Signal(str)
    config_changed = Signal(dict)
    prompt_continue = Signal(str, str)

    def __init__(A):
        super().__init__()
        A.stats = None
        A.log_path = None
        A.ui_stdout = sys.stdout
        A.ui_stderr = sys.stderr

    def _prune_old_logs(I, keep_days=7):
        days = keep_days
        logs_dir = resolve_writable_path('logs')
        logs_dir.mkdir(parents=True, exist_ok=True)
        cutoff = (datetime.now() - timedelta(days=days - 1)).date()
        pattern = re.compile('^log-(\\d{4}-\\d{2}-\\d{2})_\\d{2}-\\d{2}\\.txt$')
        removed = 0
        for path in logs_dir.glob('log-*.txt'):
            m = pattern.match(path.name)
            if not m:
                continue
            try:
                file_date = datetime.strptime(m.group(1), '%Y-%m-%d').date()
            except ValueError:
                continue
            if file_date < cutoff:
                try:
                    path.unlink()
                    removed += 1
                except Exception:
                    pass
        if removed:
            print(f'[LOG] Pruned {removed} old log file(s) (retention: {days} days)')

    def run(A):
        control.BotControl.running = True
        control.BotControl.paused = False
        control.BotControl.stop_requested = False
        main.profile_loot_status = {}
        A.status.emit('Running')
        A.stats = Stats()
        A._prune_old_logs(keep_days=7)
        stamp = datetime.now().strftime('%Y-%m-%d_%H-%M')
        log_file = resolve_writable_path(f'logs/log-{stamp}.txt')
        A.log_path = str(log_file)
        out = A.ui_stdout or BASE_STDOUT
        err = A.ui_stderr or BASE_STDERR
        fh = None
        try:
            sys.stdout = out
            sys.stderr = err
            fh = open(A.log_path, 'a', encoding='utf-8', buffering=1)
            sys.stdout = TeeStream(out, fh)
            sys.stderr = TeeStream(err, fh)
            print(f'[LOG] Session log started: {A.log_path}')
            A._run_main_with_device_recovery()
            print('[LOG] Session log ended')
        except control.BotStopped:
            print('[BOT] Stopped')
        finally:
            control.BotControl.stop_requested = False
            main.stop_error_popup_watchdog_for_cleanup()
            sys.stdout = out
            sys.stderr = err
            if fh:
                fh.close()
            main.profile_loot_status = {}
            A.status.emit('Stopped')

    def _run_main_with_device_recovery(A):
        # FIX: a lost emulator connection ended the session. Now the emulator is restarted (when the
        # bot knows how to launch it) and main() starts over, at most 3 times per 30 minutes.
        import adb
        import startup
        recoveries = []
        while True:
            try:
                main.main(A.stats)
                return
            except adb.DeviceLostError as exc:
                if not control.BotControl.running:
                    return
                now = time.time()
                recoveries = [t for t in recoveries if now - t < 1800] + [now]
                if len(recoveries) > 3:
                    print(f'[WATCHDOG] Emulator lost 4 times in 30 minutes, stopping: {exc}')
                    raise
                print(f'[WATCHDOG] {exc}')
                main.stop_error_popup_watchdog_for_cleanup()
                emulator = startup.get_selected_emulator()
                if startup.restart_emulator_for_recovery(emulator):
                    print(f'[WATCHDOG] Restarted {startup.get_emulator_display_name(emulator)}, resuming the bot')
                else:
                    print('[WATCHDOG] Waiting for the emulator to come back, resuming the bot')
                time.sleep(5)
                if not control.BotControl.running:
                    return
            except Exception as exc:
                # Any other error used to end the session silently in the GUI. Log the full
                # traceback and start main() over (it re-checks the device and the game), at most 5
                # times per 30 minutes so a bug that repeats still stops the bot.
                if not control.BotControl.running:
                    return
                import traceback
                now = time.time()
                crashes = [t for t in getattr(A, '_crashes', []) if now - t < 1800] + [now]
                A._crashes = crashes
                print(f'[WATCHDOG] Unexpected error: {exc.__class__.__name__}: {exc}')
                print(traceback.format_exc().rstrip())
                if len(crashes) > 5:
                    print('[WATCHDOG] 6 errors in 30 minutes, stopping the bot')
                    raise
                print('[WATCHDOG] Restarting the bot flow in 15 s')
                main.stop_error_popup_watchdog_for_cleanup()
                time.sleep(15)
                if not control.BotControl.running:
                    return

    def pause(A):
        control.BotControl.paused = True
        if A.stats and not A.stats._paused:
            A.stats._paused = True
            A.stats._pause_started = time.time()
        A.status.emit('Paused')

    def resume(A):
        control.BotControl.paused = False
        if A.stats and A.stats._paused:
            A.stats._total_paused_time += time.time() - A.stats._pause_started
            A.stats._paused = False
        A.status.emit('Running')

    def stop(A):
        control.BotControl.running = False
        control.BotControl.paused = False
        control.BotControl.stop_requested = True     # next screenshot/tap raises BotStopped
        main.profile_loot_status = {}
        main.stop_error_popup_watchdog_for_cleanup()
        if A.stats and not A.stats._paused:
            A.stats._paused = True
            A.stats._pause_started = time.time()
        # FIX: terminate() killed the main() thread mid-flight and left its helper threads (the
        # error-popup watchdog, uiautomator2's adb reader) alive at interpreter exit -> "Windows
        # fatal exception: access violation" when the window was closed. Let the loop stop on
        # BotControl.running first; terminate only as a last resort.
        # The bot now unwinds within a second or two (control.BotStopped). terminate() is only a last
        # resort: killing a thread that holds the GIL or the log lock can hang the whole app (11 Nov).
        if A.isRunning():
            A.wait(30000)
        if A.isRunning():
            print('[BOT] Bot thread did not stop in 30 s, forcing it')
            A.terminate()
            A.wait(2000)
        vision = getattr(main, 'GLOBAL_VISION', None)
        t = getattr(vision, '_error_popup_thread', None) if vision else None
        if t is not None and t.is_alive():
            t.join(timeout=2.0)
        sys.stdout = A.ui_stdout or BASE_STDOUT
        sys.stderr = A.ui_stderr or BASE_STDERR
        A.status.emit('Stopped')
