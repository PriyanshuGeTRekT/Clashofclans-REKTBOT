# smart/events.py - session replay: a timeline of what the bot did, with thumbnails.
#
# Each bot session gets logs/replay/<stamp>/ with events.jsonl, small JPEG thumbnails and an
# index.html that is rebuilt after every event. Each event also carries the session-log lines
# written since the previous event ("what the bot was thinking").
import html
import json
import os
import time
from pathlib import Path

from utils.runtime_paths import resolve_writable_path

_state = {'dir': None, 'log_offset': 0, 'log_path': None, 'count': 0}
THUMB_SIZE = (480, 270)
MAX_LOG_LINES = 40


def start_session():
    _state.update(dir=None, log_offset=0, log_path=None, count=0)


def _dir():
    if _state['dir'] is None:
        d = Path(resolve_writable_path('logs')) / 'replay' / time.strftime('%Y-%m-%d_%H-%M-%S')
        d.mkdir(parents=True, exist_ok=True)
        _state['dir'] = d
    return _state['dir']


def _log_lines():
    """Session-log lines written since the last event."""
    try:
        from control import BotControl
        path = getattr(BotControl.worker, 'log_path', None)
        if not path or not os.path.exists(path):
            return []
        if path != _state['log_path']:
            _state.update(log_path=path, log_offset=0)
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            f.seek(_state['log_offset'])
            text = f.read()
            _state['log_offset'] = f.tell()
        return [ln for ln in text.splitlines() if ln.strip()][-MAX_LOG_LINES:]
    except Exception:
        return []


def record(kind, frame=None, **data):
    d = _dir()
    _state['count'] += 1
    event = {'n': _state['count'], 'time': time.strftime('%H:%M:%S'), 'kind': kind, **data}
    if frame is not None:
        try:
            import cv2
            name = f"{_state['count']:04d}_{kind}.jpg"
            cv2.imwrite(str(d / name), cv2.resize(frame, THUMB_SIZE), [cv2.IMWRITE_JPEG_QUALITY, 80])
            event['thumb'] = name
        except Exception:
            pass
    event['log'] = _log_lines()
    with open(d / 'events.jsonl', 'a', encoding='utf-8') as f:
        f.write(json.dumps(event) + '\n')
    build_html(d)
    return event


def load(d):
    path = Path(d) / 'events.jsonl'
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding='utf-8').splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _fmt(n):
    try:
        return f'{int(n):,}'
    except (TypeError, ValueError):
        return '?'


def build_html(d):
    d = Path(d)
    events = load(d)
    rows = []
    for e in events:
        if e['kind'] == 'attack':
            title = (f"Attack - {e.get('stars', '?')} star(s) with {html.escape(str(e.get('strategy') or '?'))}")
            detail = (f"Loot: {_fmt(e.get('gold'))} gold, {_fmt(e.get('elixir'))} elixir, "
                      f"{_fmt(e.get('dark'))} dark. Base offered {_fmt(e.get('offer_gold'))} / "
                      f"{_fmt(e.get('offer_elixir'))} / {_fmt(e.get('offer_dark'))}"
                      f"{', ' + html.escape(str(e['th'])) if e.get('th') else ''}.")
        else:
            title = html.escape(e['kind'].replace('_', ' ').capitalize())
            detail = html.escape(str(e.get('note', '')))
        thumb = f'<img src="{html.escape(e["thumb"])}" alt="">' if e.get('thumb') else ''
        log = html.escape('\n'.join(e.get('log') or []))
        rows.append(f'<article><div class="t">{e["time"]}</div>{thumb}<div class="b"><h2>{title}</h2>'
                    f'<p>{detail}</p><details><summary>What the bot was doing</summary><pre>{log}</pre>'
                    f'</details></div></article>')
    attacks = [e for e in events if e['kind'] == 'attack']
    total = lambda k: sum(int(e.get(k) or 0) for e in attacks)   # noqa: E731
    summary = (f'{len(attacks)} attack(s) - {_fmt(total("gold"))} gold, {_fmt(total("elixir"))} elixir, '
               f'{_fmt(total("dark"))} dark')
    page = f'''<!doctype html><html><head><meta charset="utf-8"><title>Clash Rekt Bot - session replay</title>
<style>body{{font:15px/1.5 system-ui,sans-serif;background:#0d1024;color:#e8eaf6;margin:0;padding:24px}}
h1{{font-size:22px;margin:0 0 4px}}.s{{color:#9aa0c3;margin-bottom:20px}}
article{{display:flex;gap:16px;background:#151a36;border:1px solid #262c55;border-radius:12px;padding:14px;margin-bottom:12px}}
.t{{width:70px;color:#9aa0c3;flex:none}}img{{width:240px;height:135px;border-radius:8px;flex:none}}
.b{{min-width:0;flex:1}}h2{{font-size:16px;margin:0 0 4px}}p{{margin:0 0 6px;color:#c5c9e8}}
pre{{white-space:pre-wrap;background:#0d1024;padding:10px;border-radius:8px;font-size:12px;color:#aab}}
summary{{cursor:pointer;color:#ffb938}}</style></head><body>
<h1>Session replay - {html.escape(d.name)}</h1><div class="s">{summary}</div>{''.join(rows)}</body></html>'''
    (d / 'index.html').write_text(page, encoding='utf-8')
    return d / 'index.html'


def latest_html():
    """Newest replay page on disk, or None."""
    root = Path(resolve_writable_path('logs')) / 'replay'
    if not root.exists():
        return None
    pages = sorted(root.glob('*/index.html'))
    return pages[-1] if pages else None
