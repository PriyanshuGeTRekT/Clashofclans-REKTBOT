# smart/webdash.py - the bot as a web page (and headless mode).
#
# A tiny built-in web server showing the bot's status, the emulator screen and the log, with
# Start / Pause / Resume / Stop / Back off buttons. By default it only answers on this computer
# (127.0.0.1). Opening it to the home network needs a password, which every request must carry.
# `run_bot.py --headless` starts the bot with no window and this page as its only face.
import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from smart import service

_server = {'obj': None, 'password': ''}

PAGE = '''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Clash Rekt Bot</title><style>
body{font:15px/1.5 system-ui,sans-serif;background:#0d1024;color:#e8eaf6;margin:0;padding:20px;max-width:980px;margin:auto}
h1{font-size:22px}button{font:inherit;padding:10px 16px;margin:0 6px 8px 0;border-radius:10px;border:1px solid #2c3364;background:#1b2142;color:#fff;cursor:pointer}
button.p{background:#ff3b5c;border-color:#ff3b5c}#status{white-space:pre-line;background:#151a36;padding:14px;border-radius:12px;margin:12px 0}
img{width:100%;border-radius:12px;border:1px solid #262c55}pre{background:#151a36;padding:14px;border-radius:12px;white-space:pre-wrap;font-size:12px;max-height:340px;overflow:auto}
</style></head><body><h1>Clash Rekt Bot</h1>
<div><button class="p" onclick="act('start')">Start</button><button onclick="act('pause')">Pause</button>
<button onclick="act('resume')">Resume</button><button onclick="act('stop')">Stop</button>
<button onclick="backoff()">Back off 20 min</button></div>
<div id="status">Loading...</div><img id="shot" alt="Emulator screen"><h2>Log</h2><pre id="log"></pre>
<script>
const T=new URLSearchParams(location.search).get('t')||'';const q=p=>p+(T?'?t='+encodeURIComponent(T):'');
async function refresh(){try{const s=await (await fetch(q('/api/status'))).json();
document.getElementById('status').textContent=s.text;
document.getElementById('log').textContent=await (await fetch(q('/api/log'))).text();
document.getElementById('shot').src=q('/api/screenshot.png')+(T?'&':'?')+'_='+Date.now();}catch(e){}}
async function act(a){await fetch(q('/api/'+a),{method:'POST'});setTimeout(refresh,1500)}
async function backoff(){await fetch(q('/api/backoff')+(T?'&':'?')+'minutes=20',{method:'POST'});setTimeout(refresh,500)}
refresh();setInterval(refresh,5000);
</script></body></html>'''


class Handler(BaseHTTPRequestHandler):
    server_version = 'ClashRektBot'

    def log_message(self, *args):                    # keep the bot log clean
        pass

    def _allowed(self, query):
        password = _server['password']
        if not password:
            return True
        given = (query.get('t') or [''])[0]
        return hmac.compare_digest(given.encode(), password.encode())

    def _send(self, code, body, ctype='text/plain; charset=utf-8'):
        if isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _route(self, method):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if not self._allowed(query):
            return self._send(403, 'Password needed: add ?t=<password> to the address.')
        path = url.path
        if method == 'GET' and path == '/':
            return self._send(200, PAGE, 'text/html; charset=utf-8')
        if method == 'GET' and path == '/api/status':
            return self._send(200, json.dumps({**service.status(), 'text': service.status_text()}),
                              'application/json')
        if method == 'GET' and path == '/api/log':
            return self._send(200, service.log_tail(80))
        if method == 'GET' and path == '/api/screenshot.png':
            png = service.screenshot_png()
            return self._send(200, png, 'image/png') if png else self._send(503, 'No screenshot')
        if method == 'POST' and path in ('/api/start', '/api/stop', '/api/pause', '/api/resume'):
            return self._send(200 if service.do(path.rsplit('/', 1)[1]) else 409, 'ok')
        if method == 'POST' and path == '/api/backoff':
            try:
                minutes = float((query.get('minutes') or ['20'])[0])
            except ValueError:
                minutes = 20
            return self._send(200, f'{service.back_off(minutes):g}')
        return self._send(404, 'Not found')

    def do_GET(self):
        self._route('GET')

    def do_POST(self):
        self._route('POST')


def stop():
    srv = _server['obj']
    if srv is not None:
        _server['obj'] = None
        threading.Thread(target=srv.shutdown, daemon=True).start()


def restart(cfg, force=False):
    """(Re)start the page to match the settings. Returns its address or None."""
    stop()
    if not (force or cfg.get('SMART_WEB_ENABLED')):
        return None
    import os
    port = int(os.environ.get('CRB_WEB_PORT') or cfg.get('SMART_WEB_PORT', 8765) or 8765)
    password = str(cfg.get('SMART_WEB_PASSWORD', '') or '').strip()
    lan = bool(cfg.get('SMART_WEB_LAN'))
    if lan and not password:
        print('[WEB] Not opened to the network: set a password first. Serving this computer only.')
        lan = False
    _server['password'] = password
    host = '0.0.0.0' if lan else '127.0.0.1'
    try:
        srv = ThreadingHTTPServer((host, port), Handler)
    except OSError as e:
        print(f'[WEB] Could not start the web page on port {port}: {e}')
        return None
    srv.daemon_threads = True
    _server['obj'] = srv
    threading.Thread(target=srv.serve_forever, name='crb-web', daemon=True).start()
    address = f'http://127.0.0.1:{port}/' + (f'?t={password}' if password else '')
    print(f'[WEB] Dashboard at http://127.0.0.1:{port}/' + (' (also on your network)' if lan else ''))
    return address
