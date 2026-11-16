# smart/remote.py - control the bot from your phone with a Telegram bot; messages to Discord.
#
# Setup (Smart page): create a bot with @BotFather, paste its token, send the bot any message, and
# it replies with your chat id to paste into the app. Only that chat is obeyed.
#
#   /status      what the bot is doing and this session's loot
#   /screenshot  the emulator screen right now
#   /start /pause /resume /stop
#   /backoff 20  "I'm playing" - leave the village alone for 20 minutes, then carry on
#   /summary     results per strategy and Town Hall from the attack log
# Optional: a message after every attack, and a summary once a day at a set hour.
#
# Discord: paste a channel webhook address (Channel settings > Integrations > Webhooks) to get the
# attack messages there. A webhook can only receive messages, so the commands stay in Telegram.
import threading
import time

import requests

from smart import service

API = 'https://api.telegram.org/bot{token}/{method}'
HELP = ('/status - what the bot is doing\n/screenshot - the emulator screen\n/start /pause /resume /stop\n'
        '/backoff 20 - leave the village alone for 20 minutes\n/summary - results so far')
_thread = {'obj': None}


def _log(msg):
    print(f'[REMOTE] {msg}')


class TelegramRemote(threading.Thread):
    def __init__(self, token, chat_id):
        super().__init__(name='crb-telegram', daemon=True)
        self.token = token.strip()
        self.chat_id = str(chat_id or '').strip()
        self.offset = None
        self.stop_event = threading.Event()
        self.summary_day = time.strftime('%Y-%m-%d')

    # ------------------------------------------------------------ Telegram API
    def call(self, method, timeout=35, **params):
        files = params.pop('files', None)
        r = requests.post(API.format(token=self.token, method=method), data=params, files=files,
                          timeout=timeout)
        data = r.json()
        if not data.get('ok'):
            raise RuntimeError(data.get('description', f'HTTP {r.status_code}'))
        return data['result']

    def send(self, text, chat_id=None):
        try:
            self.call('sendMessage', chat_id=chat_id or self.chat_id, text=text[:4000])
        except Exception as e:
            _log(f'could not send a message: {e}')

    def send_photo(self, png, caption=''):
        try:
            self.call('sendPhoto', chat_id=self.chat_id, caption=caption,
                      files={'photo': ('screen.png', png, 'image/png')})
        except Exception as e:
            _log(f'could not send the screenshot: {e}')

    # ------------------------------------------------------------ commands
    def handle(self, chat_id, text):
        if not self.chat_id:
            self.send(f'Your chat id is {chat_id}. Paste it into Clash Rekt Bot (Smart > Phone remote), '
                      'then send /status.', chat_id)
            return
        if str(chat_id) != self.chat_id:
            return                                      # somebody else: ignore silently
        parts = text.strip().split()
        cmd = parts[0].lower().split('@')[0] if parts else ''
        if cmd in ('/start', '/stop', '/pause', '/resume'):
            ok = service.do(cmd[1:])
            time.sleep(1.5)
            self.send(service.status_text() if ok else 'That did not work.')
        elif cmd == '/status':
            self.send(service.status_text())
        elif cmd == '/screenshot':
            png = service.screenshot_png()
            self.send_photo(png, service.status_text().splitlines()[0]) if png else \
                self.send('No screenshot: is the emulator running?')
        elif cmd == '/backoff':
            try:
                minutes = float(parts[1]) if len(parts) > 1 else 20
            except ValueError:
                minutes = 20
            minutes = service.back_off(minutes)
            self.send(f'Leaving the village alone for {minutes:g} minute(s).' if minutes
                      else 'Back-off cancelled.')
        elif cmd == '/summary':
            from smart import learn, ledger
            self.send(service.status_text() + '\n\n' + learn.summary_text() + '\n\n' + ledger.summary_text())
        else:
            self.send(HELP)

    def maybe_daily_summary(self):
        cfg = service.cfg()
        if not cfg.get('SMART_TELEGRAM_DAILY_SUMMARY') or not self.chat_id:
            return
        today = time.strftime('%Y-%m-%d')
        if today != self.summary_day and time.localtime().tm_hour >= int(cfg.get('SMART_TELEGRAM_SUMMARY_HOUR', 22)):
            self.summary_day = today
            from smart import learn
            self.send('Daily summary\n' + service.status_text() + '\n\n' + learn.summary_text())

    def run(self):
        _log('Telegram remote started')
        while not self.stop_event.is_set():
            try:
                params = {'timeout': 25}
                if self.offset is not None:
                    params['offset'] = self.offset
                for update in self.call('getUpdates', **params):
                    self.offset = update['update_id'] + 1
                    msg = update.get('message') or {}
                    if msg.get('text') and msg.get('chat', {}).get('id') is not None:
                        self.handle(msg['chat']['id'], msg['text'])
                self.maybe_daily_summary()
            except Exception as e:
                _log(f'Telegram is not answering ({e}), trying again in 30 s')
                self.stop_event.wait(30)
        _log('Telegram remote stopped')


def restart(cfg):
    """(Re)start the remote to match the settings. Called by the window."""
    old = _thread['obj']
    if old is not None:
        old.stop_event.set()
        _thread['obj'] = None
    token = str(cfg.get('SMART_TELEGRAM_TOKEN', '') or '').strip()
    if cfg.get('SMART_TELEGRAM_ENABLED') and token:
        _thread['obj'] = TelegramRemote(token, cfg.get('SMART_TELEGRAM_CHAT_ID', ''))
        _thread['obj'].start()
    return _thread['obj']


def notify(text):
    t = _thread['obj']
    if t is not None and t.chat_id:
        threading.Thread(target=t.send, args=(text,), daemon=True).start()


DISCORD_PREFIXES = ('https://discord.com/api/webhooks/', 'https://discordapp.com/api/webhooks/')


def discord_send(cfg, text):
    """Post `text` to the Discord webhook from the settings. True when Discord accepted it."""
    url = str((cfg or {}).get('SMART_DISCORD_WEBHOOK', '') or '').strip()
    if not url.startswith(DISCORD_PREFIXES):
        if url:
            _log('The Discord address is not a webhook address (https://discord.com/api/webhooks/...)')
        return False
    try:
        r = requests.post(url, json={'content': text[:1900]}, timeout=15)
        if r.status_code >= 300:
            _log(f'Discord refused the message (HTTP {r.status_code})')
            return False
        return True
    except Exception as e:
        _log(f'could not reach Discord: {e}')
        return False


def notify_attack(cfg, entry):
    text = (f"Attack done: {entry['stars']} star(s), {entry['gold']:,} gold, {entry['elixir']:,} elixir, "
            f"{entry['dark']:,} dark ({entry.get('strategy') or '?'}).")
    if (cfg or {}).get('SMART_TELEGRAM_NOTIFY_ATTACKS'):
        notify(text)
    if (cfg or {}).get('SMART_DISCORD_NOTIFY_ATTACKS'):
        threading.Thread(target=discord_send, args=(cfg, text), daemon=True).start()
