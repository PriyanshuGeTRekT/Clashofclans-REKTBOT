"""Installer check used by the build workflow: import the whole bot from an installed copy and open the
Clash Rekt Bot window off-screen, saving a screenshot of the Dashboard.

  <installed python> tools/ci_smoke.py <installed app dir> <screenshot.png>
"""
import importlib
import os
import sys

target, shot = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
os.environ['APP_LAUNCH_DIR'] = os.path.join(target, 'runtime')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path[:0] = [os.path.join(target, 'source'), os.path.join(target, 'source', 'ui')]
os.chdir(os.path.join(target, 'runtime'))

MODULES = ['adb', 'startup', 'vision', 'main', 'farming', 'zoomnorm', 'ui2_zoom', 'builder_base', 'collect',
           'upgrades', 'ranked', 'war', 'attack.lootmax', 'attack.edragon', 'attack.dragon', 'attack.csv_script',
           'crb.theme', 'crb.window', 'crb.app', 'ui.bot_worker', 'profiles.profile_manager']
for name in MODULES:
    importlib.import_module(name)
print(f'imported {len(MODULES)} modules')

import adb  # noqa: E402
print('adb found at', adb._resolve_adb_path())

import crb.app  # noqa: E402
app = crb.app.create_app()
from crb.window import MainWindow  # noqa: E402
w = MainWindow()
w.resize(1280, 840)
w.show()
for _ in range(20):
    app.processEvents()
w.go('dashboard')
app.processEvents()
w.grab().save(shot)
sys.__stdout__.write(f'window OK, screenshot {shot}\n')
sys.__stdout__.flush()
os._exit(0)
