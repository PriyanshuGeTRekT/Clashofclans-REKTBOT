# crb/window.py - the Clash Rekt Bot main window.
#
# Sidebar (logo, pages, Start/Pause/Stop, status) + pages: Dashboard, Attack, Village, Builder Base,
# Clan & Events, Schedule (all built from crb.schema), Accounts, Emulator, Logs, Appearance & Help.
# The bot itself is the existing ui.bot_worker.BotWorker; this window only drives it.
import datetime
import json
import os
import re
import sys
import threading

from PySide6.QtCore import QObject, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit,
                               QPushButton, QScrollArea, QSlider, QStackedWidget, QVBoxLayout, QWidget)

import control
from utils.runtime_paths import resolve_resource_path, resolve_writable_path

from crb import icons, schema, theme
from crb.store import SettingsStore
from crb.widgets import (Card, Choice, Segmented, SettingRow, StatTile, StatusPill, Stepper, TextField,
                         ToggleSwitch, set_reduce_motion)

LOGO_PATH = os.path.join(os.path.dirname(__file__), 'assets', 'logo.svg')

NAV = [
    ('dashboard', 'Dashboard', 'dashboard'),
    ('attack', 'Attack', 'attack'),
    ('village', 'Village', 'village'),
    ('builder', 'Builder Base', 'builder'),
    ('clan', 'Clan & Events', 'clan'),
    ('schedule', 'Schedule', 'schedule'),
    ('accounts', 'Accounts', 'accounts'),
    ('emulator', 'Emulator', 'emulator'),
    ('logs', 'Logs', 'logs'),
    ('appearance', 'Appearance & Help', 'settings'),
]
SETTING_PAGES = {'attack', 'village', 'builder', 'clan', 'schedule', 'accounts', 'emulator'}
_TAG = re.compile(r'^\s*\[([A-Z0-9_ ]+)\]\s?')


class LogSink(QObject):
    """sys.stdout replacement: every print() of the GUI and the bot arrives here, line by line."""
    line = Signal(str)

    def __init__(self, passthrough=None):
        super().__init__()
        self._buf = ''
        self._lock = threading.Lock()
        self._passthrough = passthrough

    def write(self, text):
        if self._passthrough:
            try:
                self._passthrough.write(text)
            except Exception:
                pass
        got = self._lock.acquire(timeout=1.0)        # never block forever on a lock (see BotWorker.stop)
        try:
            self._buf += text
            *lines, self._buf = self._buf.split('\n')
        finally:
            if got:
                self._lock.release()
        for ln in lines:
            if ln.strip():
                self.line.emit(f'{datetime.datetime.now():%H:%M:%S}  {ln.rstrip()}')

    def flush(self):
        pass

    @property
    def encoding(self):
        return 'utf-8'


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.store = SettingsStore()
        self.prefs = self.store.ui_prefs()
        self.scheme = self.prefs.get('scheme', 'night')
        self.scale = float(self.prefs.get('text_scale', 1.0))
        set_reduce_motion(self.prefs.get('reduce_motion', False))
        self.rows = {}                    # key -> SettingRow
        self.running = False
        self.paused = False
        self._loading = False
        self._stopping = False
        self.user_stop = False

        self.setWindowTitle(theme.APP_NAME)
        self.setMinimumSize(1000, 660)
        self._restore_geometry()

        # Log sink BEFORE the worker: BotWorker captures sys.stdout when it is created.
        self.sink = LogSink(passthrough=sys.__stdout__ if sys.__stdout__ else None)
        sys.stdout = self.sink
        sys.stderr = self.sink
        self.sink.line.connect(self._on_log_line)

        from ui.bot_worker import BotWorker
        self.worker = BotWorker()
        control.BotControl.worker = self.worker
        self.worker.status.connect(self._on_status)
        self.worker.config_changed.connect(self._on_config_changed)
        self.worker.prompt_continue.connect(self._on_prompt_continue)
        self.worker.finished.connect(lambda: self._on_status('Stopped'))

        self._build()
        self.apply_theme()
        self.store.apply_emulator()
        self.reload_values()
        self.go(self.prefs.get('last_page', 'dashboard') if self.prefs.get('last_page') in dict(
            (k, 1) for k, _t, _i in NAV) else 'dashboard')

        self._set_running(False)
        self.side_status.set_state('Idle')
        self.btn_start.setFocus()
        self.stats_timer = QTimer(self)
        self.stats_timer.timeout.connect(self._refresh_stats)
        self.stats_timer.start(1000)
        self._shortcuts()
        print(f'[CRB] {theme.APP_NAME} {theme.APP_VERSION} ready')

    # ================================================================== layout
    def _build(self):
        root = QWidget()
        root.setObjectName('Root')
        self.setCentralWidget(root)
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._build_sidebar())

        right = QWidget()
        right.setObjectName('Content')
        rl = QVBoxLayout(right)
        rl.setContentsMargins(28, 20, 28, 16)
        rl.setSpacing(10)
        head = QHBoxLayout()
        tl = QVBoxLayout()
        tl.setSpacing(0)
        self.page_title = QLabel()
        self.page_title.setObjectName('PageTitle')
        self.page_sub = QLabel()
        self.page_sub.setObjectName('PageSubtitle')
        self.page_sub.setWordWrap(True)
        tl.addWidget(self.page_title)
        tl.addWidget(self.page_sub)
        head.addLayout(tl, 1)
        self.editing_label = QLabel()
        self.editing_label.setObjectName('Help')
        head.addWidget(self.editing_label, 0, Qt.AlignRight | Qt.AlignTop)
        rl.addLayout(head)
        self.lock_banner = QLabel('The bot is running: settings are locked. Stop the bot to change them.')
        self.lock_banner.setObjectName('Help')
        self.lock_banner.setVisible(False)
        rl.addWidget(self.lock_banner)

        self.stack = QStackedWidget()
        rl.addWidget(self.stack, 1)
        lay.addWidget(right, 1)

        self.pages = {}
        builders = {'dashboard': self._page_dashboard, 'accounts': self._page_accounts,
                    'emulator': self._page_emulator, 'logs': self._page_logs,
                    'appearance': self._page_appearance}
        for key, label, _icon in NAV:
            if key in builders:
                page, sub = builders[key]()
            else:
                page, sub = self._page_settings(key)
            self.pages[key] = (self.stack.addWidget(page), label, sub, page)

    def _scroll(self, inner):
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        inner.setObjectName('Page')
        area.setWidget(inner)
        return area

    def _build_sidebar(self):
        side = QWidget()
        side.setObjectName('Sidebar')
        self.sidebar = side
        lay = QVBoxLayout(side)
        lay.setContentsMargins(16, 18, 16, 16)
        lay.setSpacing(4)
        brand = QHBoxLayout()
        self.logo = QLabel()
        self.logo.setPixmap(icons.logo_pixmap(LOGO_PATH, 52))
        self.logo.setAccessibleName('Clash Rekt Bot logo')
        brand.addWidget(self.logo)
        self.wordmark = QLabel()
        self.wordmark.setObjectName('Wordmark')
        self.wordmark.setAccessibleName(theme.APP_NAME)
        brand.addWidget(self.wordmark, 1)
        lay.addLayout(brand)
        ver = QLabel(f'v{theme.APP_VERSION}')
        ver.setObjectName('Dim')
        lay.addWidget(ver)
        lay.addSpacing(10)

        self.nav_buttons = {}
        for i, (key, label, icon_name) in enumerate(NAV):
            b = QPushButton(f'  {label}'.replace('&', '&&'))     # '&' would become a mnemonic
            b.setObjectName('Nav')
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(f'{label}  (Ctrl+{(i + 1) % 10})')
            b.setAccessibleName(f'{label} page')
            b.clicked.connect(lambda _c=False, k=key: self.go(k))
            b._icon_name = icon_name
            self.nav_buttons[key] = b
            lay.addWidget(b)
        lay.addStretch(1)

        self.side_status = StatusPill(self.scheme)
        lay.addWidget(self.side_status, 0, Qt.AlignLeft)
        self.target_label = QLabel()
        self.target_label.setObjectName('Help')
        self.target_label.setWordWrap(True)
        lay.addWidget(self.target_label)
        lay.addSpacing(6)
        self.btn_start = QPushButton('  Start bot')
        self.btn_start.setObjectName('Primary')
        self.btn_start.setProperty('class', 'Big')
        self.btn_start.setMinimumHeight(48)
        self.btn_start.setToolTip('Start the bot (F5)')
        self.btn_start.clicked.connect(self.start_bot)
        lay.addWidget(self.btn_start)
        row = QHBoxLayout()
        self.btn_pause = QPushButton('  Pause')
        self.btn_pause.setToolTip('Pause / resume (F6)')
        self.btn_pause.clicked.connect(self.toggle_pause)
        self.btn_stop = QPushButton('  Stop')
        self.btn_stop.setObjectName('Danger')
        self.btn_stop.setToolTip('Stop the bot (F7)')
        self.btn_stop.clicked.connect(self.stop_bot)
        row.addWidget(self.btn_pause)
        row.addWidget(self.btn_stop)
        lay.addLayout(row)
        return side

    # ================================================================== pages
    def _page_dashboard(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 8, 8)
        lay.setSpacing(14)

        hero = Card(scheme=self.scheme)
        hl = QHBoxLayout()
        txt = QVBoxLayout()
        self.hero_status = QLabel('Ready when you are.')
        self.hero_status.setObjectName('CardTitle')
        self.hero_detail = QLabel('Press Start: the bot opens the emulator and Clash of Clans by itself.')
        self.hero_detail.setObjectName('Help')
        self.hero_detail.setWordWrap(True)
        txt.addWidget(self.hero_status)
        txt.addWidget(self.hero_detail)
        hl.addLayout(txt, 1)
        self.hero_start = QPushButton('  START')
        self.hero_start.setObjectName('Primary')
        self.hero_start.setMinimumSize(190, 56)
        self.hero_start.clicked.connect(self._hero_clicked)
        self.hero_start.setAccessibleName('Start or stop the bot')
        hl.addWidget(self.hero_start)
        hero.body.addLayout(hl)
        lay.addWidget(hero)

        grid = QGridLayout()
        grid.setSpacing(12)
        c = theme.colors(self.scheme)
        self.tiles = {
            'runtime': StatTile('Runtime', 'clock', c['info']),
            'attacks': StatTile('Attacks', 'attack', c['primary']),
            'gold': StatTile('Gold', 'gold', c['gold']),
            'elixir': StatTile('Elixir', 'elixir', '#D85CFF'),
            'dark': StatTile('Dark elixir', 'dark', c['muted']),
            'walls': StatTile('Walls upgraded', 'wall', c['success']),
        }
        for i, t in enumerate(self.tiles.values()):
            grid.addWidget(t, i // 3, i % 3)
        lay.addLayout(grid)

        stars = Card('Stars per attack', 'How the attacks this session went.', 'star', self.scheme)
        sl = QHBoxLayout()
        self.star_tiles = []
        for n in range(4):
            t = StatTile(f'{n} star{"s" if n != 1 else ""}', 'star', c['gold'] if n else c['faint'])
            self.star_tiles.append(t)
            sl.addWidget(t)
        stars.body.addLayout(sl)
        lay.addWidget(stars)

        quick = Card('Quick switches', 'The most used options. Everything else is on the other pages.',
                     'settings', self.scheme)
        qg = QGridLayout()
        qg.setHorizontalSpacing(24)
        for i, key in enumerate(schema.QUICK_KEYS):
            sw = ToggleSwitch(self.scheme)
            row = SettingRow(schema.title(key), '', sw)
            row.help.setVisible(False)
            sw.setToolTip(schema.help_text(key))
            sw.setAccessibleDescription(schema.help_text(key))
            sw.toggled.connect(lambda v, k=key: self._changed(k, v))
            self.rows.setdefault(f'quick:{key}', row)
            qg.addWidget(row, i // 2, i % 2)
        quick.body.addLayout(qg)
        lay.addWidget(quick)

        recent = Card('Recent activity', '', 'logs', self.scheme)
        self.mini_log = QPlainTextEdit()
        self.mini_log.setObjectName('Log')
        self.mini_log.setReadOnly(True)
        self.mini_log.setMaximumBlockCount(14)
        self.mini_log.setFixedHeight(190)
        self.mini_log.setAccessibleName('Recent activity log')
        recent.add(self.mini_log)
        lay.addWidget(recent)
        lay.addStretch(1)
        return self._scroll(page), 'Start the bot and watch how it is doing.'

    def _page_settings(self, page_key):
        spec = next(p for p in schema.PAGES if p[0] == page_key)
        _k, _title, sub, cards = spec
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 8, 8)
        lay.setSpacing(14)
        for card_title, hint, icon_name, keys in cards:
            card = Card(card_title, hint, icon_name, self.scheme)
            for i, key in enumerate(keys):
                if i:
                    card.add_divider()
                card.add(self._make_row(key))
                if key == 'SELECTED_ATTACK_STRATEGY':
                    self.strategy_info = QLabel()
                    self.strategy_info.setObjectName('Help')
                    self.strategy_info.setWordWrap(True)
                    self.strategy_info.setAccessibleName('Army suggestion for the selected strategy')
                    card.add(self.strategy_info)
            lay.addWidget(card)
        lay.addStretch(1)
        return self._scroll(page), sub

    def _make_row(self, key):
        meta = schema.BY_KEY[key]
        kind = meta['kind']
        if kind == 'bool':
            ctl = ToggleSwitch(self.scheme)
            ctl.toggled.connect(lambda v, k=key: self._changed(k, v))
        elif kind in ('int', 'float'):
            ctl = Stepper(kind, meta['min'] or 0, meta['max'] or 999_999, meta['step'] or 1)
            ctl.valueChanged.connect(lambda v, k=key: self._changed(k, v))
        elif kind == 'choice':
            choices = self._choices(key)
            if len(choices) <= 3 and key not in ('CSV_ATTACK_SCRIPT', 'WAR_CSV_SCRIPT', 'START_PROFILE'):
                ctl = Segmented(choices)
            else:
                ctl = Choice(choices)
            ctl.valueChanged.connect(lambda v, k=key: self._changed(k, v))
        else:
            ctl = TextField(meta['label'])
            ctl.valueChanged.connect(lambda v, k=key: self._changed(k, v))
        row = SettingRow(schema.title(key), schema.help_text(key), ctl)
        self.rows[key] = row
        return row

    def _choices(self, key):
        meta = schema.BY_KEY[key]
        if meta.get('choices'):
            return list(meta['choices'])
        if key in ('CSV_ATTACK_SCRIPT', 'WAR_CSV_SCRIPT'):
            try:
                from attack.csv_script import list_scripts
                return [(s, s) for s in list_scripts()]
            except Exception:
                return []
        if key == 'START_PROFILE':
            return [('', '(first enabled account)')] + [(n, n) for n in self._enabled_profiles()]
        return []

    def _page_accounts(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 8, 8)
        lay.setSpacing(14)
        card = Card('Multiple accounts', 'Rotate between several Clash of Clans accounts (Supercell ID). '
                    'At the first Start the bot learns your accounts from the switch-account screen.',
                    'accounts', self.scheme)
        for i, key in enumerate(schema.ACCOUNT_KEYS):
            if i:
                card.add_divider()
            card.add(self._make_row(key))
        lay.addWidget(card)

        plist = Card('Your accounts', 'Ticked accounts are played, in this order. Select one and press '
                     '"Edit its settings" to give it its own settings; otherwise all accounts share the main settings.',
                     'accounts', self.scheme)
        self.profile_list = QListWidget()
        self.profile_list.setMinimumHeight(220)
        self.profile_list.setAccessibleName('Accounts list')
        self.profile_list.itemChanged.connect(lambda _i: self._save_profile_order())
        plist.add(self.profile_list)
        btns = QHBoxLayout()
        self.btn_up = QPushButton('Move up')
        self.btn_down = QPushButton('Move down')
        self.btn_edit_profile = QPushButton('Edit its settings')
        self.btn_rename = QPushButton('Rename / match')
        self.btn_global = QPushButton('Back to main settings')
        self.btn_delete_profiles = QPushButton('Forget all accounts')
        self.btn_delete_profiles.setObjectName('Danger')
        self.btn_up.clicked.connect(lambda: self._move_profile(-1))
        self.btn_down.clicked.connect(lambda: self._move_profile(1))
        self.btn_edit_profile.clicked.connect(self._edit_selected_profile)
        self.btn_rename.clicked.connect(self._rename_selected_profile)
        self.btn_global.clicked.connect(lambda: self._set_editing(None))
        self.btn_delete_profiles.clicked.connect(self._delete_all_profiles)
        for b in (self.btn_up, self.btn_down, self.btn_edit_profile, self.btn_rename, self.btn_global):
            btns.addWidget(b)
        btns.addStretch(1)
        btns.addWidget(self.btn_delete_profiles)
        plist.body.addLayout(btns)
        lay.addWidget(plist)
        lay.addStretch(1)
        return self._scroll(page), 'Play several accounts one after another.'

    def _page_emulator(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 8, 8)
        lay.setSpacing(14)
        card = Card('Your emulator', 'Any Android emulator with ADB works. The bot needs a 1600 x 900 '
                    '(landscape) screen; see the README for setup steps per emulator.', 'emulator', self.scheme)
        import startup
        self.emu_choice = Segmented([(k, startup.get_emulator_display_name(k))
                                     for k in startup.get_supported_emulators()])
        self.emu_choice.valueChanged.connect(self._emulator_picked)
        card.add(SettingRow('Emulator', 'Pick yours. "Other" works for any emulator: just enter its ADB port.',
                            self.emu_choice))
        card.add_divider()
        self.emu_ip = TextField('127.0.0.1')
        self.emu_ip.setMinimumWidth(160)
        self.emu_ip.valueChanged.connect(lambda v: self._changed('EMULATOR_IP', v or '127.0.0.1'))
        card.add(SettingRow('ADB address', 'Usually 127.0.0.1 (this computer).', self.emu_ip))
        card.add_divider()
        self.emu_port = TextField('5555')
        self.emu_port.setMinimumWidth(160)
        self.emu_port.valueChanged.connect(self._port_entered)
        card.add(SettingRow('ADB port', 'Filled in for you when you pick an emulator; change it for a '
                            'second instance or an emulator listed as "Other".', self.emu_port))
        lay.addWidget(card)

        tools = Card('Check the connection', 'Find running emulators and test that the bot can see the game.',
                     'link', self.scheme)
        tb = QHBoxLayout()
        self.btn_detect = QPushButton('  Find running emulators')
        self.btn_detect.clicked.connect(self._detect_devices)
        self.btn_test = QPushButton('  Test connection')
        self.btn_test.setObjectName('Primary')
        self.btn_test.clicked.connect(self._test_connection)
        tb.addWidget(self.btn_detect)
        tb.addWidget(self.btn_test)
        tb.addStretch(1)
        tools.body.addLayout(tb)
        self.device_list = QListWidget()
        self.device_list.setMaximumHeight(130)
        self.device_list.setAccessibleName('Emulators found')
        self.device_list.itemDoubleClicked.connect(self._device_chosen)
        tools.add(self.device_list)
        self.emu_result = QLabel('Not tested yet.')
        self.emu_result.setObjectName('Help')
        self.emu_result.setWordWrap(True)
        tools.add(self.emu_result)
        lay.addWidget(tools)

        zoom = Card('Scenery zoom', 'Some sceneries zoom out further than others. The bot measures your '
                    'village and zooms to the right level by itself; the result per scenery is remembered.',
                    'zoom', self.scheme)
        zr = QHBoxLayout()
        self.zoom_info = QLabel()
        self.zoom_info.setObjectName('Help')
        self.zoom_info.setWordWrap(True)
        zr.addWidget(self.zoom_info, 1)
        reset = QPushButton('Forget zoom calibration')
        reset.clicked.connect(self._reset_zoom)
        zr.addWidget(reset)
        zoom.body.addLayout(zr)
        lay.addWidget(zoom)
        lay.addStretch(1)
        self._refresh_zoom_info()
        return self._scroll(page), 'Connect the bot to your Android emulator.'

    def _page_logs(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.log_filter = Choice([('all', 'Everything'), ('important', 'Important only'),
                                  ('attacks', 'Attacks and results'), ('errors', 'Problems only')])
        self.log_filter.setMinimumWidth(200)
        self.log_filter.setAccessibleName('Log filter')
        self.log_filter.valueChanged.connect(lambda _v: self._rebuild_log())
        self.log_search = QLineEdit()
        self.log_search.setPlaceholderText('Search the log…')
        self.log_search.setAccessibleName('Search the log')
        self.log_search.textChanged.connect(lambda _t: self._rebuild_log())
        copy = QPushButton('Copy')
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.log_view.toPlainText()))
        folder = QPushButton('  Open log folder')
        folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(resolve_writable_path('logs')))))
        bar.addWidget(self.log_filter)
        bar.addWidget(self.log_search, 1)
        bar.addWidget(copy)
        bar.addWidget(folder)
        lay.addLayout(bar)
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName('Log')
        self.log_view.setReadOnly(True)
        self.log_view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.log_view.setAccessibleName('Bot log')
        lay.addWidget(self.log_view, 1)
        self._log_lines = []
        return page, 'Everything the bot does, live. A copy of each session is saved in the log folder.'

    def _page_appearance(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 8, 8)
        lay.setSpacing(14)
        card = Card('Look and feel', '', 'settings', self.scheme)
        self.scheme_choice = Segmented([(k, v['name']) for k, v in theme.SCHEMES.items()])
        self.scheme_choice.setValue(self.scheme)
        self.scheme_choice.valueChanged.connect(self._set_scheme)
        card.add(SettingRow('Colour scheme', 'High Contrast uses pure black and white with thick focus outlines.',
                            self.scheme_choice))
        card.add_divider()
        self.scale_slider = QSlider(Qt.Horizontal)
        self.scale_slider.setRange(90, 160)
        self.scale_slider.setSingleStep(10)
        self.scale_slider.setPageStep(10)
        self.scale_slider.setValue(int(self.scale * 100))
        self.scale_slider.setMinimumWidth(220)
        self.scale_slider.sliderReleased.connect(lambda: self._set_scale(self.scale_slider.value() / 100))
        self.scale_slider.valueChanged.connect(
            lambda v: self.scale_slider.isSliderDown() or self._set_scale(v / 100))
        card.add(SettingRow('Text size', 'Also Ctrl + / Ctrl − anywhere in the app.', self.scale_slider))
        card.add_divider()
        self.motion_switch = ToggleSwitch(self.scheme)
        self.motion_switch.setChecked(bool(self.prefs.get('reduce_motion', False)))
        self.motion_switch.toggled.connect(self._set_reduce_motion)
        card.add(SettingRow('Reduce motion', 'Switches flip instantly instead of sliding.', self.motion_switch))
        lay.addWidget(card)

        keys = Card('Keyboard', 'Everything works without a mouse: Tab moves between controls, Space or Enter '
                    'flips a switch or presses a button.', 'info', self.scheme)
        lines = ['F5  Start', 'F6  Pause / resume', 'F7  Stop', 'Ctrl+1 … Ctrl+0  Go to a page',
                 'Ctrl + / Ctrl −  Bigger / smaller text']
        for ln in lines:
            l = QLabel(ln)
            l.setObjectName('Help')
            keys.add(l)
        lay.addWidget(keys)

        about = Card(theme.APP_NAME, f'Version {theme.APP_VERSION}. Setup guides and troubleshooting are in the '
                     'README next to this app.', 'info', self.scheme)
        ab = QHBoxLayout()
        readme = QPushButton('  Open README')
        readme.clicked.connect(self._open_readme)
        ab.addWidget(readme)
        ab.addStretch(1)
        about.body.addLayout(ab)
        lay.addWidget(about)
        lay.addStretch(1)
        return self._scroll(page), 'Make the app comfortable to use.'

    # ================================================================== navigation / theme
    def go(self, key):
        idx, label, sub, _w = self.pages[key]
        self.stack.setCurrentIndex(idx)
        self.page_title.setText(label.upper())
        self.page_sub.setText(sub)
        for k, b in self.nav_buttons.items():
            b.setChecked(k == key)
        if key == 'accounts':
            self._refresh_profiles()
        if key == 'emulator':
            self._refresh_zoom_info()
        self._current_page = key
        self.store.save_ui_prefs(last_page=key)

    def apply_theme(self):
        app = QApplication.instance()
        theme.apply_palette(app, self.scheme)
        app.setFont(theme.base_font(self.scale))
        app.setStyleSheet(theme.stylesheet(self.scheme, self.scale))
        self.sidebar.setFixedWidth(int(250 * max(1.0, self.scale)))     # room for bigger text
        c = theme.colors(self.scheme)
        self.wordmark.setText(f'<span style="color:{c["text"]}">CLASH</span> '
                              f'<span style="color:{c["primary"]}">REKT</span><br>'
                              f'<span style="color:{c["gold"]}; font-size:70%">BOT</span>')
        for b in self.nav_buttons.values():
            b.setIcon(icons.icon(b._icon_name, c['muted'], 20))
        self.btn_start.setIcon(icons.icon('play', c['primary_text'], 18))
        self.hero_start.setIcon(icons.icon('play' if not self.running else 'stop', c['primary_text'], 20))
        self.btn_pause.setIcon(icons.icon('pause' if not self.paused else 'play', c['text'], 16))
        self.btn_stop.setIcon(icons.icon('stop', c['danger'], 16))
        self.btn_detect.setIcon(icons.icon('refresh', c['text'], 16))
        self.btn_test.setIcon(icons.icon('link', c['primary_text'], 16))
        for w in self.findChildren(ToggleSwitch):
            w.set_scheme(self.scheme)
        self.side_status.set_scheme(self.scheme)
        self.hero_start.setStyleSheet(f'QPushButton {{ font-size: {14 * self.scale:.0f}pt; font-weight: 800;'
                                      f' border-radius: 14px; }}')

    def _set_scheme(self, scheme):
        self.scheme = scheme
        self.store.save_ui_prefs(scheme=scheme)
        self.apply_theme()

    def _set_scale(self, scale):
        scale = max(0.9, min(1.6, round(scale, 1)))
        if abs(scale - self.scale) < 0.01:
            return
        self.scale = scale
        self.store.save_ui_prefs(text_scale=scale)
        self.scale_slider.blockSignals(True)
        self.scale_slider.setValue(int(scale * 100))
        self.scale_slider.blockSignals(False)
        self.apply_theme()

    def _set_reduce_motion(self, on):
        set_reduce_motion(on)
        self.store.save_ui_prefs(reduce_motion=bool(on))

    def _shortcuts(self):
        for i, (key, _l, _i) in enumerate(NAV):
            QShortcut(QKeySequence(f'Ctrl+{(i + 1) % 10}'), self, activated=lambda k=key: self.go(k))
        QShortcut(QKeySequence('F5'), self, activated=self.start_bot)
        QShortcut(QKeySequence('F6'), self, activated=self.toggle_pause)
        QShortcut(QKeySequence('F7'), self, activated=self.stop_bot)
        for seq in ('Ctrl++', 'Ctrl+='):
            QShortcut(QKeySequence(seq), self, activated=lambda: self._set_scale(self.scale + 0.1))
        QShortcut(QKeySequence('Ctrl+-'), self, activated=lambda: self._set_scale(self.scale - 0.1))
        QShortcut(QKeySequence(Qt.Key_Return), self, activated=self._enter_pressed)

    def _enter_pressed(self):
        control.BotControl.enter_pressed = True     # console-style prompts (BotControl.wait_for_enter)

    # ================================================================== values
    def reload_values(self):
        """Show the current config in every control (signals blocked: no write-back, Q22)."""
        self._loading = True
        try:
            cfg = self.store.load()
            for key, row in self.rows.items():
                real = key.split(':', 1)[1] if key.startswith('quick:') else key
                if real not in schema.BY_KEY:
                    continue
                ctl = row.control
                ctl.blockSignals(True)
                if isinstance(ctl, Choice) and real in ('CSV_ATTACK_SCRIPT', 'WAR_CSV_SCRIPT', 'START_PROFILE'):
                    ctl.set_choices(self._choices(real))
                val = self.store.get(real, cfg)
                if real == 'START_PROFILE' and val is None:
                    val = ''
                try:
                    if isinstance(ctl, ToggleSwitch):
                        ctl.setChecked(bool(val))
                    elif val is not None:
                        ctl.setValue(val)
                finally:
                    ctl.blockSignals(False)
            gcfg = self.store.cm.load()
            import startup
            emu = str(gcfg.get('EMULATOR_SELECTION') or 'bluestacks').lower()
            self.emu_choice.blockSignals(True)
            self.emu_choice.setValue(emu)
            self.emu_choice.blockSignals(False)
            self.emu_ip.setValue(gcfg.get('EMULATOR_IP') or '127.0.0.1')
            self.emu_port.setValue(gcfg.get('EMULATOR_PORT') or startup.get_default_adb_port(emu))
        finally:
            self._loading = False
        self._refresh_dependencies(cfg)
        self._refresh_strategy_info(cfg)
        self._refresh_target_label()
        self._refresh_editing_label()

    def _changed(self, key, value):
        if self._loading:
            return
        stored = self.store.set(key, value)
        # keep the quick switch and the page switch for the same key in sync
        for rk in (key, f'quick:{key}'):
            row = self.rows.get(rk)
            if row is not None and isinstance(row.control, ToggleSwitch) and row.control.isChecked() != bool(stored):
                row.control.blockSignals(True)
                row.control.setChecked(bool(stored))
                row.control.blockSignals(False)
        cfg = self.store.load()
        self._refresh_dependencies(cfg)
        if key == 'SELECTED_ATTACK_STRATEGY':
            self._refresh_strategy_info(cfg)
        if key == 'MULTI_VILLAGE_ENABLED' and not value:
            self._set_editing(None)                        # Q19
        if key.startswith('EMULATOR_'):
            self._refresh_target_label()

    def _refresh_dependencies(self, cfg=None):
        cfg = cfg if cfg is not None else self.store.load()
        for key, row in self.rows.items():
            real = key.split(':', 1)[1] if key.startswith('quick:') else key
            meta = schema.BY_KEY.get(real)
            if not meta:
                continue
            dep = meta.get('depends_on')
            ok = schema.depends_ok(dep, cfg)
            row.set_available(ok and not self.running, schema.depends_text(dep) if not ok else '')

    def _refresh_strategy_info(self, cfg=None):
        if not hasattr(self, 'strategy_info'):
            return
        cfg = cfg if cfg is not None else self.store.load()
        strat = self.store.get('SELECTED_ATTACK_STRATEGY', cfg)
        text = schema.STRATEGY_HELP.get(strat, '')
        self.strategy_info.setText('Suggested army:\n' + text if text else '')

    def _refresh_target_label(self):
        import startup
        cfg = self.store.cm.load()
        key = str(cfg.get('EMULATOR_SELECTION') or 'bluestacks').lower()
        name = startup.get_emulator_display_name(key) if key in startup.get_supported_emulators() else key
        self.target_label.setText(f'{name} · {cfg.get("EMULATOR_IP") or "127.0.0.1"}:{cfg.get("EMULATOR_PORT")}')

    def _refresh_editing_label(self):
        p = self.store.profile
        self.editing_label.setText(f'Editing settings of account: {p}' if p else
                                   ('Editing the main settings' if self.store.get('MULTI_VILLAGE_ENABLED') else ''))

    # ================================================================== bot control
    def _hero_clicked(self):
        if self.running:
            self.stop_bot()
        else:
            self.start_bot()

    def start_bot(self):
        if self._stopping:
            return
        if self.worker.isRunning():
            if self.paused:
                self.toggle_pause()
            return
        self.store.apply_emulator()
        self.user_stop = False
        self.worker.start()
        self._set_running(True)

    def toggle_pause(self):
        if not self.worker.isRunning():
            return
        if control.BotControl.paused:
            self.worker.resume()
        else:
            self.worker.pause()

    def stop_bot(self):
        if not self.worker.isRunning() or self._stopping:
            return
        self._stopping = True
        self.user_stop = True                 # run_bot.py's auto-restart respects a manual stop
        self.side_status.set_state('Stopping')
        self.btn_stop.setEnabled(False)
        self.btn_pause.setEnabled(False)
        self.hero_start.setEnabled(False)
        # BotWorker.stop() waits up to ~7 s for the bot loop: keep the window responsive meanwhile
        threading.Thread(target=self.worker.stop, name='crb-stop', daemon=True).start()

    def _set_running(self, on):
        self.running = on
        if not on:
            self.paused = False
            self._stopping = False
        self.btn_start.setEnabled(not on)
        self.btn_pause.setEnabled(on)
        self.btn_stop.setEnabled(on)
        self.hero_start.setEnabled(True)
        c = theme.colors(self.scheme)
        self.hero_start.setText('  STOP' if on else '  START')
        self.hero_start.setIcon(icons.icon('stop' if on else 'play', c['primary_text'], 20))
        self.lock_banner.setVisible(on)
        for key in ('emulator', 'accounts'):
            self.pages[key][3].setEnabled(not on)
        self.btn_detect.setEnabled(not on)
        self._refresh_dependencies()
        self.side_status.set_state('Running' if on else 'Stopped')
        self.hero_status.setText('The bot is playing.' if on else 'Ready when you are.')
        self.hero_detail.setText('Settings are locked while it runs. Stop it to change them.' if on else
                                 'Press Start: the bot opens the emulator and Clash of Clans by itself.')

    def _on_status(self, status):
        if status == 'Running':
            if not self.running:
                self._set_running(True)
            self.paused = False
            self.side_status.set_state('Running')
            self.btn_pause.setText('  Pause')
        elif status == 'Paused':
            self.paused = True
            self.side_status.set_state('Paused')
            self.btn_pause.setText('  Resume')
        elif status == 'Stopped':
            # FIX (Q23): the old UI never unlocked when the bot stopped by itself
            if not self.worker.isRunning():
                self._set_running(False)
        c = theme.colors(self.scheme)
        self.btn_pause.setIcon(icons.icon('play' if self.paused else 'pause', c['text'], 16))

    def _on_config_changed(self, payload):
        # The bot switched account (or finished calibration): show that account's settings, never save back.
        self.store.profile = payload.get('profile')
        self.reload_values()
        self._refresh_profiles()

    def _on_prompt_continue(self, title, message):
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setIcon(QMessageBox.Information)
        box.setText(message)
        if title == 'Profile Calibration':
            guide = resolve_resource_path('assets/profile_guide.png')
            if guide.exists():
                box.setInformativeText('Open the in-game Settings → Supercell ID "switch account" screen, '
                                       'then press Continue.')
        box.addButton('Continue', QMessageBox.AcceptRole)
        box.exec()
        control.BotControl.continue_clicked()

    # ================================================================== stats / log
    def _refresh_stats(self):
        import main
        stats = getattr(main, 'GLOBAL_STATS', None) or getattr(self.worker, 'stats', None)
        if not stats:
            return
        try:
            t = self.tiles
            t['runtime'].set(stats.elapsed_hhmmss())
            t['attacks'].set(f'{stats.total_attacks:,}')
            t['gold'].set(f'{stats.gold_gained:,}', f'{getattr(stats, "_cached_gold_hr", 0):,} / hour')
            t['elixir'].set(f'{stats.elixir_gained:,}', f'{getattr(stats, "_cached_elixir_hr", 0):,} / hour')
            t['dark'].set(f'{stats.dark_gained:,}', f'{getattr(stats, "_cached_dark_hr", 0):,} / hour')
            t['walls'].set(f'{getattr(stats, "walls_upgraded", 0):,}')
            for n, tile in enumerate(self.star_tiles):
                tile.set(str(getattr(stats, f'stars_{n}', 0)))
        except Exception:
            pass

    def _on_log_line(self, line):
        self._log_lines.append(line)
        if len(self._log_lines) > 20000:
            del self._log_lines[:5000]
        if self._log_visible(line):
            self.log_view.appendPlainText(line)
        if self._is_important(line):
            self.mini_log.appendPlainText(line)
        if 'Traceback' in line or 'Unexpected error' in line:
            self.side_status.set_state('Error') if not self.running else None

    @staticmethod
    def _is_important(line):
        return any(k in line for k in ('[BATTLE] Result', 'ATTACK START', '[COLLECT]', '[UPGRADE]', '[BB]',
                                       'Lost the connection', 'Reconnected', '[WATCHDOG]', '[STARTUP]App ready',
                                       '[HELPER]', '[DONATE]', '[CAPITAL]', '[RANKED]', '[ZOOM] home',
                                       '[SCHEDULE]', 'End condition', 'No emulator answered', '[CRB]',
                                       '[LOOTMAX]', '[END BATTLE]'))

    def _log_visible(self, line):
        f = self.log_filter.value() if hasattr(self, 'log_filter') else 'all'
        q = self.log_search.text().strip().lower() if hasattr(self, 'log_search') else ''
        if q and q not in line.lower():
            return False
        if f == 'important':
            return self._is_important(line)
        if f == 'attacks':
            return any(k in line for k in ('[BATTLE]', 'ATTACK', '[SEARCH]Loot good', 'High loot', 'TROOPS:'))
        if f == 'errors':
            return any(k in line.lower() for k in ('error', 'fail', 'lost', 'timed out', 'traceback',
                                                   'warning', 'stuck', 'could not', 'not found'))
        return True

    def _rebuild_log(self):
        self.log_view.setPlainText('\n'.join(ln for ln in self._log_lines if self._log_visible(ln)))
        self.log_view.moveCursor(QTextCursor.End)

    # ================================================================== accounts
    def _profiles_data(self):
        path = resolve_writable_path('profiles/active_profiles.json')
        try:
            return json.loads(path.read_text(encoding='utf-8')).get('profiles', {})
        except Exception:
            return {}

    def _enabled_profiles(self):
        return [n for n, on in self._profiles_data().items() if on]

    def _refresh_profiles(self):
        if not hasattr(self, 'profile_list'):
            return
        self.profile_list.blockSignals(True)
        self.profile_list.clear()
        for name, on in self._profiles_data().items():
            it = QListWidgetItem(name)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if on else Qt.Unchecked)
            if name == self.store.profile:
                it.setText(f'{name}   (editing)')
            it.setData(Qt.UserRole, name)
            self.profile_list.addItem(it)
        self.profile_list.blockSignals(False)
        empty = self.profile_list.count() == 0
        for b in (self.btn_up, self.btn_down, self.btn_edit_profile, self.btn_rename, self.btn_delete_profiles):
            b.setEnabled(not empty)
        self.btn_global.setEnabled(self.store.profile is not None)
        if empty:
            it = QListWidgetItem('No accounts yet: turn on "Switch between accounts" and press Start.')
            it.setFlags(Qt.NoItemFlags)
            self.profile_list.addItem(it)

    def _save_profile_order(self):
        order = {}
        for i in range(self.profile_list.count()):
            it = self.profile_list.item(i)
            name = it.data(Qt.UserRole)
            if name:
                order[name] = it.checkState() == Qt.Checked
        path = resolve_writable_path('profiles/active_profiles.json')
        path.write_text(json.dumps({'profiles': order}, indent=2), encoding='utf-8')
        row = self.rows.get('START_PROFILE')
        if row:
            row.control.set_choices(self._choices('START_PROFILE'))

    def _move_profile(self, delta):
        i = self.profile_list.currentRow()
        j = i + delta
        if i < 0 or not (0 <= j < self.profile_list.count()):
            return
        self.profile_list.blockSignals(True)
        it = self.profile_list.takeItem(i)
        self.profile_list.insertItem(j, it)
        self.profile_list.setCurrentRow(j)
        self.profile_list.blockSignals(False)
        self._save_profile_order()

    def _selected_profile(self):
        it = self.profile_list.currentItem()
        return it.data(Qt.UserRole) if it else None

    def _edit_selected_profile(self):
        name = self._selected_profile()
        if name:
            self._set_editing(name)

    def _set_editing(self, name):
        self.store.profile = name
        self.reload_values()
        self._refresh_profiles()
        print(f'[CRB] Editing settings of account {name}' if name else '[CRB] Editing the main settings')

    def _rename_selected_profile(self):
        name = self._selected_profile()
        if not name:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f'Account: {name}')
        form = QFormLayout(dlg)
        new_name = QLineEdit(name)
        new_name.setAccessibleName('Account name')
        thr = QDoubleSpinBox()
        thr.setRange(0.5, 1.0)
        thr.setSingleStep(0.01)
        thr.setDecimals(2)
        thr.setValue(float(self.store.cm.load(name).get('PROFILE_MATCH_THRESHOLD', 0.92) or 0.92))
        thr.setAccessibleName('Match threshold')
        form.addRow('Name', new_name)
        form.addRow('Match threshold', thr)
        hint = QLabel('How closely the account card must match when switching (0.92 is a good default).')
        hint.setObjectName('Help')
        hint.setWordWrap(True)
        form.addRow(hint)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if dlg.exec() != QDialog.Accepted:
            return
        target = name
        wanted = new_name.text().strip()
        if wanted and wanted != name:
            from profiles.profile_manager import ProfileManager
            ok, msg, renamed = ProfileManager(None).rename_profile(name, wanted)
            if not ok:
                QMessageBox.warning(self, 'Rename', msg)
                return
            target = renamed
            if self.store.profile == name:
                self.store.profile = renamed
        c = self.store.cm.load(target)
        c['PROFILE_MATCH_THRESHOLD'] = round(thr.value(), 2)
        self.store.cm.save(c, target)
        self._refresh_profiles()
        self.reload_values()

    def _delete_all_profiles(self):
        if QMessageBox.warning(self, 'Forget all accounts',
                               'This deletes every learned account and its own settings. Your main settings '
                               'stay. The accounts are learned again at the next Start.\n\nContinue?',
                               QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        import shutil
        base = resolve_writable_path('profiles')
        for entry in os.listdir(base):
            p = os.path.join(base, entry)
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
        for f in ('active_profiles.json', 'order.txt'):
            try:
                os.remove(os.path.join(base, f))
            except OSError:
                pass
        self._set_editing(None)

    # ================================================================== emulator page
    def _emulator_picked(self, key):
        if self._loading:
            return
        _k, _ip, port = self.store.set_emulator(key, reset_port=True)
        self.emu_port.setValue(port)
        self._refresh_target_label()

    def _port_entered(self, value):
        if value.isdigit():
            self._changed('EMULATOR_PORT', value)
        elif value:
            self.emu_result.setText('The port must be a number, e.g. 5555.')

    def _run_in_thread(self, fn, done):
        """Run fn() off the GUI thread; done(result) runs on the GUI thread."""
        holder = {}

        def work():
            try:
                holder['r'] = fn()
            except Exception as exc:
                holder['r'] = exc
        th = threading.Thread(target=work, daemon=True)
        th.start()
        timer = QTimer(self)

        def poll():
            if not th.is_alive():
                timer.stop()
                done(holder.get('r'))
        timer.timeout.connect(poll)
        timer.start(150)

    def _detect_devices(self):
        self.device_list.clear()
        self.emu_result.setText('Looking for running emulators…')
        self.btn_detect.setEnabled(False)

        def find():
            import adb
            import startup
            from crb import devices
            startup.start_adb()
            return devices.scan(adb._require_adb_path())

        def done(result):
            self.btn_detect.setEnabled(not self.running)
            if isinstance(result, Exception):
                self.emu_result.setText(f'Could not run adb: {result}')
                return
            if not result:
                self.emu_result.setText('No running emulator found. Start your emulator (with ADB enabled) and try again.')
                return
            for serial, guess in result:
                it = QListWidgetItem(f'{serial}    {guess}')
                it.setData(Qt.UserRole, serial)
                self.device_list.addItem(it)
            self.emu_result.setText('Double-click an entry to use it.')
        self._run_in_thread(find, done)

    def _device_chosen(self, item):
        serial = item.data(Qt.UserRole) or ''
        from crb import devices
        key, host, port = devices.preset_for(serial)
        if key:
            self.store.set_emulator(key, reset_port=False)
        if host:
            self._changed('EMULATOR_IP', host)
        if port:
            self._changed('EMULATOR_PORT', port)
        self.reload_values()
        self.emu_result.setText(f'Using {serial}. Press "Test connection" to check it.')

    def _test_connection(self):
        self.emu_result.setText('Testing… (this can take a few seconds)')
        self.btn_test.setEnabled(False)
        self.store.apply_emulator()

        def test():
            import adb
            import startup
            startup.start_adb()
            adb.connect_emulator()
            states = adb._device_states_quiet()
            target = adb.get_target_addr()
            serial = adb._resolve_ready_serial_for_target(target, states)
            if not serial:
                return f'✗ Nothing answering at {target}. Seen by adb: ' + (
                    ', '.join(f'{s} ({st})' for s, st in states.items()) or 'nothing') + \
                    '. Is the emulator running with ADB enabled, and is the port right?'
            adb._CACHED_TARGET = serial
            size = adb.check_screen_size()
            running = adb.is_app_running('com.supercell.clashofclans')
            installed = 'package:com.supercell.clashofclans' in adb.adb_target(
                ['shell', 'pm', 'list', 'packages', 'com.supercell.clashofclans'])
            parts = [f'✓ Connected to {serial}.']
            if size:
                w, h = size
                ok = (max(w, h), min(w, h)) == adb.EXPECTED_SIZE
                parts.append(f'Screen {w} x {h}: ' + ('✓ correct.' if ok else '✗ set the emulator to 1600 x 900 (see README).'))
            dpi = adb.screen_density()
            if dpi:
                parts.append(f'Density {dpi} DPI: ' + ('✓ correct.' if dpi == adb.EXPECTED_DPI else
                                                      f'✗ set {adb.EXPECTED_DPI} DPI (see README).'))
            parts.append('Clash of Clans: ' + ('✓ installed' + (' and running.' if running else '.')
                                               if installed else '✗ not installed (see README).'))
            return ' '.join(parts)

        def done(result):
            self.btn_test.setEnabled(True)
            self.emu_result.setText(str(result))
            print(f'[CRB] Connection test: {result}')
        self._run_in_thread(test, done)

    def _refresh_zoom_info(self):
        path = resolve_writable_path('logs/zoom_calibration.json')
        try:
            cal = json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            cal = {}
        sceneries = [k for k in cal if k[0].isdigit() or k.startswith('probe-')]
        if sceneries:
            self.zoom_info.setText(f'Calibrated for {len(sceneries)} scenery zoom level(s). It recalibrates by '
                                   'itself when you change scenery.')
        else:
            self.zoom_info.setText('Not calibrated yet: happens automatically the first time it is needed (~1 min).')

    def _reset_zoom(self):
        try:
            os.remove(resolve_writable_path('logs/zoom_calibration.json'))
        except OSError:
            pass
        self._refresh_zoom_info()

    def _open_readme(self):
        for cand in (resolve_resource_path('../README.md'), resolve_resource_path('README.md')):
            if os.path.exists(cand):
                QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(cand)))
                return

    # ================================================================== window state
    def _restore_geometry(self):
        w = self.prefs.get('window')
        screen = QApplication.primaryScreen().availableGeometry()
        if isinstance(w, dict) and w.get('width', 0) >= 1000 and w.get('height', 0) >= 660:
            from PySide6.QtCore import QRect
            r = QRect(w.get('x', 0), w.get('y', 0), w['width'], w['height'])
            if screen.intersects(r):
                self.setGeometry(r)
                return
        self.resize(min(1240, screen.width() - 40), min(820, screen.height() - 60))

    def closeEvent(self, event):
        g = self.geometry()
        self.store.save_ui_prefs(window={'x': g.x(), 'y': g.y(), 'width': g.width(), 'height': g.height()})
        self.user_stop = True
        if self.worker.isRunning():
            # Stop first (the bot unwinds in a second or two), then close: never block the window.
            event.ignore()
            if not getattr(self, '_close_pending', False):
                self._close_pending = True
                self.hero_status.setText('Stopping the bot, then closing…')
                self.worker.finished.connect(self.close)
                self.stop_bot()
            return
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__
        super().closeEvent(event)
