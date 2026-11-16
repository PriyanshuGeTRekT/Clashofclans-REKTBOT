# smart/farm.py - one bot per emulator instance.
#
# The bot talks to one emulator at a time. A farm starts one extra copy of the bot per emulator
# instance, each with its own settings, logs and (optionally) its own web dashboard. Instances are
# listed on the Smart page as "name=port", for example:  second=5565, third=5575
# Each copy keeps its files in runtime/instances/<name>/ and shares the templates and tools.
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SHARED = ('templates', 'assets', 'Tools', 'CSV')
_procs = {}


def _log(msg):
    print(f'[FARM] {msg}')


def parse(spec):
    """'a=5565, b=5575' -> [('a', '5565'), ('b', '5575')]. Bad entries are dropped."""
    out = []
    for part in re.split(r'[,\n;]+', spec or ''):
        m = re.fullmatch(r'\s*([A-Za-z0-9_-]{1,24})\s*=\s*(\d{2,5})\s*', part)
        if m:
            out.append((m.group(1), m.group(2)))
    return out


def runtime_root():
    """The main runtime folder (the one that holds templates/ and run_bot.py)."""
    return Path(os.environ.get('CRB_MAIN_RUNTIME') or Path(__file__).resolve().parents[2] / 'runtime')


def prepare(name, port, base_cfg=None):
    """Create runtime/instances/<name>/ and point its settings at 127.0.0.1:<port>."""
    root = runtime_root()
    inst = root / 'instances' / name
    (inst / 'profiles').mkdir(parents=True, exist_ok=True)
    (inst / 'logs').mkdir(exist_ok=True)
    for shared in SHARED:
        link, target = inst / shared, root / shared
        if target.exists() and not link.exists():
            try:
                os.symlink(target, link, target_is_directory=True)
            except OSError:
                import shutil
                shutil.copytree(target, link)            # no symlink rights (Windows): copy once
    cfg_path = inst / 'profiles' / 'config.json'
    try:
        cfg = json.loads(cfg_path.read_text(encoding='utf-8'))
    except Exception:
        cfg = dict(base_cfg or {})
        for secret in ('SMART_TELEGRAM_ENABLED', 'SMART_WEB_ENABLED', 'SMART_FARM_INSTANCES'):
            cfg.pop(secret, None)                        # one remote / one farm list: the main bot's
    cfg.update(EMULATOR_SELECTION='other', EMULATOR_IP='127.0.0.1', EMULATOR_PORT=str(port),
               MULTI_VILLAGE_ENABLED=False)
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding='utf-8')
    return inst


def launch(spec, base_cfg=None, headless=False, autostart=True):
    """Start one bot per listed instance. Returns [(name, port, pid or error text)]."""
    root = runtime_root()
    results = []
    for index, (name, port) in enumerate(parse(spec)):
        old = _procs.get(name)
        if old is not None and old.poll() is None:
            results.append((name, port, f'already running (pid {old.pid})'))
            continue
        inst = prepare(name, port, base_cfg)
        env = dict(os.environ, CRB_INSTANCE_DIR=str(inst), CRB_MAIN_RUNTIME=str(root))
        cmd = [sys.executable, str(root / 'run_bot.py')]
        if autostart:
            cmd.append('--autostart')
        if headless:
            cmd += ['--headless', '--web-port', str(8766 + index)]
        try:
            proc = subprocess.Popen(cmd, env=env, cwd=str(root), stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError as e:
            results.append((name, port, f'could not start: {e}'))
            continue
        _procs[name] = proc
        _log(f'{name} started on port {port} (pid {proc.pid})'
             + (f', dashboard http://127.0.0.1:{8766 + index}/' if headless else ''))
        results.append((name, port, proc.pid))
    return results


def stop_all():
    for name, proc in list(_procs.items()):
        if proc.poll() is None:
            proc.terminate()
            _log(f'{name} stopped')
        _procs.pop(name, None)
