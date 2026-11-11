# Reconstructed from Pyarmor-decrypted bytecode (stats, Python 3.10).
import time


class Stats:
    def __init__(A):
        A.start_time = time.time()
        A._paused = False
        A._pause_started = 0
        A._total_paused_time = 0
        A.total_attacks = 0
        A.gold_gained = 0
        A.elixir_gained = 0
        A.dark_gained = 0
        A.stars_0 = 0
        A.stars_1 = 0
        A.stars_2 = 0
        A.stars_3 = 0
        A.walls_upgraded = 0
        A.troops_donated = 0
        A.spells_donated = 0
        A._last_hourly_update = 0
        A._cached_gold_hr = 0
        A._cached_elixir_hr = 0
        A._cached_dark_hr = 0

    @property
    def elapsed_seconds(self):
        s = self
        if s._paused:
            return int(s._pause_started - s.start_time - s._total_paused_time)
        return int(time.time() - s.start_time - s._total_paused_time)

    def elapsed_hhmmss(B):
        secs = B.elapsed_seconds
        h = secs // 3600
        m = secs % 3600 // 60
        s = secs % 60
        return f'{h:02}:{m:02}:{s:02}'

    def record_stars(A, stars):
        n = stars
        if n == 0:
            A.stars_0 += 1
        elif n == 1:
            A.stars_1 += 1
        elif n == 2:
            A.stars_2 += 1
        elif n == 3:
            A.stars_3 += 1

    def update_hourly_rates(A):
        now = time.time()
        if now - A._last_hourly_update < 60:
            return
        hours = max(A.elapsed_seconds / 3600, 0.01)
        A._cached_gold_hr = int(A.gold_gained / hours)
        A._cached_elixir_hr = int(A.elixir_gained / hours)
        A._cached_dark_hr = int(A.dark_gained / hours)
        A._last_hourly_update = now

    def pause_timer(A):
        if not A._paused:
            A._paused = True
            A._pause_started = time.time()

    def resume_timer(A):
        if A._paused:
            A._total_paused_time += time.time() - A._pause_started
            A._paused = False

    def reset_timer(A):
        A.start_time = time.time()
        A._paused = False
        A._pause_started = 0
        A._total_paused_time = 0
