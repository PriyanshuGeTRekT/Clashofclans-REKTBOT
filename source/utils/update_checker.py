# Reconstructed from Pyarmor-decrypted bytecode (utils.update_checker, Python 3.10).
# Only the app name/version for the window title remain: the remote update check (a GitHub
# manifest fetched at launch and hourly, plus the "Update Available" dialog) has been removed.
APP_NAME = 'ACBot Basic'
APP_VERSION = '1.6.7'


def build_window_title():
    return f'{APP_NAME} v{APP_VERSION}'
