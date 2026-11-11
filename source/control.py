# Reconstructed from Pyarmor-decrypted bytecode (control, Python 3.10).
import threading
import time


class BotStopped(BaseException):
    """Raised from the bot thread's next screenshot/tap once Stop was pressed, so the bot unwinds in
    a second instead of finishing its attack (a BaseException: generic `except Exception` handlers
    must not swallow it). Replaces killing the thread, which can deadlock Python."""


class BotControl:
    running = True
    paused = False
    stop_requested = False
    enter_pressed = False
    continue_event = threading.Event()
    worker = None  # set to the Qt BotWorker by ui.bot_worker

    @classmethod
    def emit_config(A, cfg, profile=None):
        if A.worker:
            A.worker.config_changed.emit({'cfg': cfg, 'profile': profile})

    @staticmethod
    def wait_for_enter():
        BotControl.enter_pressed = False
        while not BotControl.enter_pressed and BotControl.running:
            time.sleep(0.1)

    @classmethod
    def wait_for_continue(A, title, message):
        msg = message
        ttl = title
        A.continue_event.clear()
        if A.worker and hasattr(A.worker, 'prompt_continue'):
            A.worker.prompt_continue.emit(ttl, msg)
        else:
            print(f'[{ttl}] {msg}')
            A.wait_for_enter()
            return
        while A.running and not A.continue_event.wait(0.1):
            pass

    @classmethod
    def continue_clicked(A):
        A.continue_event.set()
