# Reconstructed from Pyarmor-decrypted bytecode (utils.update_checker, Python 3.10).
# Only the app name/version for the classic window's title remain. Updates are in source/updates/.
from pathlib import Path

APP_NAME = 'Clash Rekt Bot (classic window)'
try:
    APP_VERSION = (Path(__file__).resolve().parents[2] / 'VERSION').read_text(encoding='utf-8').strip() or '?'
except OSError:
    APP_VERSION = '?'


def build_window_title():
    return f'{APP_NAME} v{APP_VERSION}'
