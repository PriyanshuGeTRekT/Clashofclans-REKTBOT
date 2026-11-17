"""App side of updates: ask GitHub for the newest release, download its update package, check it,
and hand it to the update engine (updates/engine.py), which installs it once the app has closed.

Where the release information comes from (first one that answers):
  1. https://github.com/<repo>/releases/latest/download/latest.json - written by tools/build_update.py
     and attached to every release by the "Build installers" workflow (no GitHub API rate limit);
  2. the GitHub API's latest release - for a release made without latest.json. Its update package
     (ClashRektBot-<version>-update.zip) is used when attached; otherwise the user only gets the
     "new version" notice with a link to the installers.
Only public release information is downloaded; nothing about the user or the computer is sent.
For testing, CRB_UPDATE_URL (a latest.json address) and CRB_UPDATE_API override the sources.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from urllib.parse import urlparse

from updates import engine

ROOT = Path(__file__).resolve().parents[2]
LATEST_JSON = f'https://github.com/{engine.REPO}/releases/latest/download/latest.json'
LATEST_API = f'https://api.github.com/repos/{engine.REPO}/releases/latest'
RELEASES_PAGE = f'https://github.com/{engine.REPO}/releases/latest'
GITHUB_HOSTS = ('github.com', 'api.github.com', 'codeload.github.com')
LOOPBACK = ('127.0.0.1', 'localhost', '::1')
DEFAULT_PREFS = {'check': True, 'auto': False, 'skip': '', 'last_check': 0.0}
KEEP_PIDS = set()            # crb.app.cleanup_children() must not end the updater


class UpdateError(Exception):
    pass


class UpdateCancelled(UpdateError):
    pass


def current_version():
    return engine.read_version(ROOT) or '0.0.0'


def is_git_checkout():
    return (ROOT / '.git').exists()


def supported():
    """Updates are handled by the main app only (not by farm instances started from it)."""
    return not os.environ.get('CRB_INSTANCE_DIR')


def state():
    return engine.state_dir(ROOT)


# ------------------------------------------------------------------ preferences (bot.config "updates")
def _config_path():
    from utils.runtime_paths import resolve_writable_path
    return Path(resolve_writable_path('bot.config'))


def load_prefs():
    try:
        data = json.loads(_config_path().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        data = {}
    prefs = dict(DEFAULT_PREFS)
    if isinstance(data, dict) and isinstance(data.get('updates'), dict):
        prefs.update(data['updates'])
    return prefs


def save_prefs(**changes):
    path = _config_path()
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    prefs = data.get('updates') if isinstance(data.get('updates'), dict) else {}
    prefs.update(changes)
    data['updates'] = prefs
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding='utf-8')
    return prefs


# ------------------------------------------------------------------ network
def _override_hosts():
    hosts = set()
    for var in ('CRB_UPDATE_URL', 'CRB_UPDATE_API'):
        if os.environ.get(var):
            hosts.add(urlparse(os.environ[var]).hostname)
    return hosts


def _allowed(url):
    u = urlparse(url)
    host = (u.hostname or '').lower()
    if u.scheme == 'https' and (host in GITHUB_HOSTS or host.endswith('.githubusercontent.com')):
        return True
    if host in _override_hosts():
        return u.scheme == 'https' or host in LOOPBACK
    return False


def _get(url, timeout, stream=False, accept=None):
    import requests
    if not _allowed(url):
        raise UpdateError(f'not downloading from {urlparse(url).hostname}: only GitHub is allowed')
    headers = {'User-Agent': f'ClashRektBot/{current_version()} (+https://github.com/{engine.REPO})'}
    if accept:
        headers['Accept'] = accept
    try:
        response = requests.get(url, timeout=timeout, stream=stream, headers=headers)
    except requests.RequestException as exc:
        raise UpdateError(f'could not reach GitHub ({exc.__class__.__name__}): is the internet connected?')
    for hop in list(response.history) + [response]:
        if not _allowed(hop.url):
            response.close()
            raise UpdateError(f'GitHub sent the download to {urlparse(hop.url).hostname}: refused')
    return response


def _clean_info(version, tag, notes, page, package, min_version, source):
    version = str(version or '').strip().lstrip('vV')
    if not version or engine.parse_version(version)[:3] == (0, 0, 0):
        raise UpdateError('the release has no version number')
    if package is not None:
        sha = str(package.get('sha256') or '').lower()
        url = str(package.get('url') or '')
        if len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha) or not url:
            package = None
        else:
            package = {'name': str(package.get('name') or engine.PACKAGE_NAME.format(version=version)),
                       'url': url, 'sha256': sha, 'size': int(package.get('size') or 0)}
    return {'version': version, 'tag': str(tag or f'v{version}'), 'notes': str(notes or ''),
            'page': str(page or RELEASES_PAGE), 'package': package, 'min_version': str(min_version or ''),
            'source': source}


def _from_latest_json(data):
    if not isinstance(data, dict) or int(data.get('schema') or 0) != 1:
        raise ValueError('not a latest.json')
    return _clean_info(data.get('version'), data.get('tag'), data.get('notes'), data.get('page'),
                       data.get('package') if isinstance(data.get('package'), dict) else None,
                       data.get('min_version'), 'latest.json')


def _from_api(timeout):
    url = os.environ.get('CRB_UPDATE_API') or LATEST_API
    response = _get(url, timeout, accept='application/vnd.github+json')
    if response.status_code == 404:
        raise UpdateError('no release has been published yet')
    if response.status_code in (403, 429):
        raise UpdateError('GitHub is limiting requests from this connection: try again in an hour')
    if response.status_code != 200:
        raise UpdateError(f'GitHub answered with error {response.status_code}')
    try:
        data = response.json()
        tag = data['tag_name']
    except (ValueError, KeyError, TypeError):
        raise UpdateError('GitHub sent something unexpected')
    version = str(tag).lstrip('vV')
    assets = [a for a in data.get('assets') or [] if isinstance(a, dict)]
    want = engine.PACKAGE_NAME.format(version=version)
    asset = next((a for a in assets if a.get('name') == want), None)
    package = None
    if asset:
        digest = str(asset.get('digest') or '')
        sha = digest.split(':', 1)[1] if digest.startswith('sha256:') else ''
        if not sha:
            side = next((a for a in assets if a.get('name') == want + '.sha256'), None)
            if side:
                text = _get(side['browser_download_url'], timeout).text
                sha = (text.split() or [''])[0]
        package = {'name': want, 'url': asset.get('browser_download_url'), 'sha256': sha,
                   'size': asset.get('size')}
    return _clean_info(version, tag, data.get('body'), data.get('html_url'), package, '', 'api')


def check(timeout=20):
    """The newest release: {'version', 'tag', 'notes', 'page', 'package' or None, 'min_version'}."""
    url = os.environ.get('CRB_UPDATE_URL') or LATEST_JSON
    response = _get(url, timeout)
    if response.status_code == 200:
        try:
            return _from_latest_json(response.json())
        except (ValueError, TypeError, UpdateError):
            pass                                   # a broken latest.json: ask the API instead
    elif response.status_code != 404:
        raise UpdateError(f'GitHub answered with error {response.status_code}')
    return _from_api(timeout)


def evaluate(info, manual=False, prefs=None):
    """What to do with `info`:
      current          this version is the newest
      skipped / bad    newer, but the user skipped it / it failed to start here (not shown by itself)
      needs-installer  too big a step: install it with the installer
      notify-only      the release has no update package: show the notice and the download link
      git              this copy is a git checkout: update it with git
      available        can be installed from inside the app"""
    prefs = prefs or load_prefs()
    if not engine.is_newer(info['version'], current_version()):
        return 'current'
    if not manual:
        if info['version'] in engine.bad_versions(ROOT):
            return 'bad'
        if prefs.get('skip') == info['version']:
            return 'skipped'
    if info.get('min_version') and engine.is_newer(info['min_version'], current_version()):
        return 'needs-installer'
    if not info.get('package'):
        return 'notify-only'
    if is_git_checkout():
        return 'git'
    return 'available'


# ------------------------------------------------------------------ download, check, unpack
def download(info, progress=None, cancel=None):
    """Download the update package (resuming nothing: it is small). Returns its path."""
    pkg = info['package']
    folder = state() / 'downloads'
    folder.mkdir(parents=True, exist_ok=True)
    final = folder / pkg['name']
    if final.is_file() and engine.sha256_file(final) == pkg['sha256']:
        return final                              # already here and complete
    part = folder / (pkg['name'] + '.part')
    digest = hashlib.sha256()
    done = 0
    response = _get(pkg['url'], (10, 60), stream=True)
    try:
        if response.status_code != 200:
            raise UpdateError(f'the download failed (error {response.status_code})')
        total = int(response.headers.get('Content-Length') or pkg.get('size') or 0)
        if total > engine.MAX_PACKAGE_BYTES:
            raise UpdateError('the update is unexpectedly big: not downloading it')
        with open(part, 'wb') as f:
            for chunk in response.iter_content(256 * 1024):
                if cancel is not None and cancel.is_set():
                    raise UpdateCancelled('cancelled')
                f.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if done > engine.MAX_PACKAGE_BYTES:
                    raise UpdateError('the update is unexpectedly big: stopped')
                if progress:
                    progress(done, total)
    except BaseException:
        response.close()
        try:
            part.unlink()
        except OSError:
            pass
        raise
    response.close()
    if pkg.get('size') and done != pkg['size']:
        part.unlink()
        raise UpdateError('the download is incomplete: try again')
    if digest.hexdigest() != pkg['sha256']:
        part.unlink()
        raise UpdateError('the download is damaged (its checksum does not match): try again')
    os.replace(part, final)
    return final


def stage(zip_path, info):
    """Check the package and unpack it into .crb/updates/staging-<version>. Returns that folder."""
    version = info['version']
    try:
        manifest = engine.verify_package(zip_path)
    except (engine.UpdateError, zipfile.BadZipFile, OSError) as exc:
        raise UpdateError(f'the update package is not usable: {exc}')
    if manifest.get('version') != version:
        raise UpdateError(f"the package is version {manifest.get('version')}, not {version}")
    staging = state() / f'staging-{version}'
    if staging.exists():
        shutil.rmtree(staging)
    with zipfile.ZipFile(zip_path) as z:
        for item in z.infolist():
            if item.is_dir():
                continue
            name = item.filename
            if name != engine.MANIFEST and not (engine.safe_rel(name) and engine.in_scope(name)):
                raise UpdateError(f'the package has a file outside the app: {name!r}')
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(item) as src, open(target, 'wb') as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
    engine.verify_tree(staging, manifest)
    return staging


# ------------------------------------------------------------------ handing over to the engine
def _relaunch(bot_was_running):
    try:
        args = [str(a) for a in json.loads(os.environ.get('CRB_LAUNCH_ARGS') or '[]')]
    except ValueError:
        args = []
    args = [a for a in args if a != '--autostart']
    if bot_was_running:
        args.append('--autostart')                 # the bot was stopped for the update: carry on after it
    return {'python': sys.executable, 'args': args}


def _spawn_engine():
    st = state()
    st.mkdir(parents=True, exist_ok=True)
    runner = st / 'engine.py'                      # run a copy: the original is about to be replaced
    shutil.copyfile(ROOT / 'source' / 'updates' / 'engine.py', runner)
    cmd = [sys.executable, '-I', str(runner), 'apply', '--root', str(ROOT), '--wait-pid', str(os.getpid())]
    kwargs = dict(cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                  stderr=subprocess.DEVNULL, close_fds=True)
    if os.name == 'nt':
        kwargs['creationflags'] = engine._DETACHED
    else:
        kwargs['start_new_session'] = True
    proc = subprocess.Popen(cmd, **kwargs)
    KEEP_PIDS.add(proc.pid)
    return proc.pid


def request_update(staging, version, bot_was_running=False):
    """Ask the engine to install the staged update after this app has closed. Close the app next."""
    engine.save_json(state() / 'pending.json', {'op': 'update', 'to': version, 'staging': str(staging),
                                                'relaunch': _relaunch(bot_was_running),
                                                'requested': time.time()})
    try:
        return _spawn_engine()
    except OSError as exc:
        try:
            (state() / 'pending.json').unlink()
        except OSError:
            pass
        raise UpdateError(f'the updater could not be started ({exc})')


def undo_available():
    """The version "Undo the last update" goes back to, or ''."""
    info = engine.load_json(state() / 'backup' / 'info.json', None)
    if isinstance(info, dict) and info.get('to') == current_version() and info.get('version'):
        return str(info['version'])
    return ''


def request_undo(bot_was_running=False):
    engine.save_json(state() / 'pending.json', {'op': 'rollback', 'relaunch': _relaunch(bot_was_running),
                                                'requested': time.time()})
    try:
        return _spawn_engine()
    except OSError as exc:
        try:
            (state() / 'pending.json').unlink()
        except OSError:
            pass
        raise UpdateError(f'the updater could not be started ({exc})')


def take_last_result():
    """What the last update did (once): {'op', 'from', 'to', 'ok', 'message'} or None."""
    path = state() / 'last_result.json'
    data = engine.load_json(path, None)
    if not isinstance(data, dict) or data.get('shown'):
        return None
    data['shown'] = True
    engine.save_json(path, data)
    return data


def report_started():
    """The app's window is up: tells a waiting updater that the new version works."""
    if supported():
        engine.app_started(ROOT, current_version(), os.getpid())
