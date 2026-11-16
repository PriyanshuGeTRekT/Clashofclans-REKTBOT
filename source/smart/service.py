# smart/service.py - what the remote controls (Telegram, web dashboard) are allowed to do.
#
# The window registers a Controller; remote.py and webdash.py only ever talk to this object, so
# they have exactly the same powers as the buttons in the app: start, pause, resume, stop, look.
import time


class Controller:
    """Filled in by the window (crb/window.py). Every callable is safe to call from any thread."""
    start = stop = pause = resume = None      # callables() -> None
    get_cfg = None                            # callable() -> settings dict
    is_running = None                         # callable() -> bool


controller = Controller()


def cfg():
    try:
        return controller.get_cfg() if controller.get_cfg else {}
    except Exception:
        return {}


def status():
    """Plain dict describing the bot right now."""
    from control import BotControl
    out = {'running': bool(controller.is_running and controller.is_running()),
           'paused': bool(BotControl.paused), 'backing_off_seconds': 0}
    if BotControl.hold_until:
        out['backing_off_seconds'] = max(0, int(BotControl.hold_until - time.time()))
    try:
        import main
        stats = getattr(main, 'GLOBAL_STATS', None) or getattr(BotControl.worker, 'stats', None)
    except Exception:
        stats = None
    if stats is not None:
        out.update(attacks=stats.total_attacks, gold=stats.gold_gained, elixir=stats.elixir_gained,
                   dark=stats.dark_gained, elapsed=stats.elapsed_hhmmss(),
                   stars=[stats.stars_0, stats.stars_1, stats.stars_2, stats.stars_3])
    return out


def status_text():
    s = status()
    state = 'stopped'
    if s['running']:
        state = 'paused' if s['paused'] else 'running'
        if s['backing_off_seconds']:
            state = f"backing off for {s['backing_off_seconds'] // 60 + 1} more minute(s)"
    lines = [f'Bot is {state}.']
    if 'attacks' in s:
        lines.append(f"This session: {s['attacks']} attack(s) in {s['elapsed']}, "
                     f"{s['gold']:,} gold, {s['elixir']:,} elixir, {s['dark']:,} dark.")
    return '\n'.join(lines)


def screenshot_png():
    """PNG bytes of the emulator screen, or None."""
    try:
        import cv2
        import adb
        frame = adb.screenshot()
        if frame is None:
            return None
        ok, buf = cv2.imencode('.png', frame)
        return buf.tobytes() if ok else None
    except Exception:
        return None


def log_tail(lines=60):
    try:
        from control import BotControl
        path = getattr(BotControl.worker, 'log_path', None)
        if not path:
            return ''
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return ''.join(f.readlines()[-lines:])
    except Exception:
        return ''


def back_off(minutes):
    """Leave the village alone for `minutes` (the bot keeps its place and carries on afterwards)."""
    from control import BotControl
    minutes = max(0.0, min(float(minutes), 24 * 60))
    BotControl.hold_until = time.time() + minutes * 60 if minutes else 0.0
    return minutes


def do(action):
    fn = getattr(controller, action, None)
    if action not in ('start', 'stop', 'pause', 'resume') or not callable(fn):
        return False
    fn()
    return True
