# ui/main_window.py -- ACBot Basic v1.6.7 PySide6 main window.
# Reconstructed from Pyarmor-decrypted CPython 3.10 bytecode (decrypted/ui.main_window.dis.txt).
# The original source was minified (self was renamed A/B/C/...); obfuscated locals (_var_var_N)
# have been renamed by usage. Pyarmor enter/exit wrappers removed. Large string constants
# (QSS stylesheets, strategy help) were copied verbatim from the constant pool.
import os
import re
import shutil
import sys
import time
import json
from PySide6.QtWidgets import (QLineEdit, QApplication, QDialog, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                               QFrame, QPushButton, QStackedWidget, QLabel, QGroupBox, QGridLayout, QComboBox,
                               QSpinBox, QDoubleSpinBox, QTextEdit, QListWidget, QListWidgetItem, QCheckBox,
                               QAbstractItemView, QMessageBox, QTabWidget, QStyledItemDelegate, QToolTip,
                               QScrollArea)
from PySide6.QtCore import QObject, Signal, Qt, QTimer, QEvent, QSize, QLocale, QRect, QUrl
from PySide6.QtGui import (QDesktopServices, QIcon, QFontDatabase, QFont, QShortcut, QKeySequence, QPixmap, QColor,
                           QPalette)
from PySide6.QtCore import QPropertyAnimation, QEasingCurve
from bot_worker import BotWorker
import main
import control
import adb
import startup

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from profiles.config_manager import ConfigManager
from utils.runtime_paths import resolve_resource_path, resolve_writable_path
import datetime

UI_DEBUG = False
FREE_MAX_VILLAGES = 100                                         # Pro: up to 100 villages (Basic capped this at 5)
LOCKED_STRATEGIES = set()                                       # Pro: every strategy unlocked (Basic locked Valkyrie / Super Minion)

# Pro Features page: declarative settings (config key, label, kind, default, min, max, step).
# Each group becomes a QGroupBox; values load/save generically (_load_pro_features / update_pro_features).
PRO_SETTING_GROUPS = [
    ('Village', [
        ('COLLECT_RESOURCES', 'Collect full collectors, gem box and gem mine every 10 minutes', 'bool', False),
        ('COLLECT_LOOT_CART', 'Also collect the loot cart', 'bool', True),
        ('CLAIM_EVENT_REWARDS', 'Claim free event rewards (Events window, every 3 hours)', 'bool', False),
        ('REMOVE_OBSTACLES', 'Remove obstacles (templates in templates/obstacles, needs a free builder)', 'bool', False),
    ]),
    ('Auto Upgrades (first affordable upgrade in the game Build menu list)', [
        ('AUTO_UPGRADE_BUILDINGS', 'Buildings and heroes (free builders)', 'bool', False),
        ('AUTO_UPGRADE_KEEP_BUILDERS', 'Keep this many builders free (e.g. for walls)', 'int', 0, 0, 6, 1),
        ('AUTO_UPGRADE_LAB', 'Laboratory research (troops, spells, sieges)', 'bool', False),
        ('AUTO_UPGRADE_PETS', 'Pet House', 'bool', False),
        ('AUTO_UPGRADE_EQUIPMENT', 'Hero equipment (Blacksmith, spends ores)', 'bool', False),
        ('BB_AUTO_UPGRADE', 'Builder Base buildings, Battle Machine/Copter and walls (on BB visits)', 'bool', False),
        ('BB_AUTO_LAB', 'Builder Base Star Laboratory (on BB visits)', 'bool', False),
    ]),
    ('Ranked Battles', [
        ('RANKED_ATTACKS_ENABLED', 'Attack in Ranked Battle tournaments (uses the tournament attacks, no loot)', 'bool', False),
        ('RANKED_MAX_PER_DAY', 'Ranked attacks per day at most', 'int', 14, 1, 14, 1),
    ]),
    ('Clan Donations', [
        ('DONATE_ENABLED', 'Donate to clan requests (checked every 5 minutes)', 'bool', False),
        ('DONATE_TROOPS', 'What to donate, e.g. troop_edragon:1, troop_balloon:5, spell_rage:1', 'text', ''),
    ]),
    ('Clan Capital', [
        ('CAPITAL_RAIDS_ENABLED', 'Use Clan Capital raid attacks during raid weekends (checked every 4 h)', 'bool', False),
        ('CAPITAL_MAX_RAIDS', 'Raid attacks per visit', 'int', 6, 1, 6, 1),
    ]),
    ('Schedule', [
        ('SCHED_ACTIVE_HOURS_ENABLED', 'Only play between the hours below (CoC is closed outside them)', 'bool', False),
        ('SCHED_START_HOUR', 'Start hour (0-23)', 'int', 8, 0, 23, 1),
        ('SCHED_END_HOUR', 'End hour (0-23, may be past midnight)', 'int', 23, 0, 23, 1),
        ('SCHED_BREAKS_ENABLED', 'Take random breaks (closes CoC, like putting the phone away)', 'bool', False),
        ('SCHED_BREAK_EVERY_MIN', 'Break every ... minutes, from', 'int', 40, 10, 600, 5),
        ('SCHED_BREAK_EVERY_MAX', '... to', 'int', 90, 10, 600, 5),
        ('SCHED_BREAK_LENGTH_MIN', 'Break length in minutes, from', 'int', 5, 1, 240, 1),
        ('SCHED_BREAK_LENGTH_MAX', '... to', 'int', 15, 1, 240, 1),
    ]),
    ('End Conditions (0 = off)', [
        ('END_CONDITIONS_ENABLED', 'Stop the bot when one of these targets is reached', 'bool', False),
        ('END_AFTER_ATTACKS', 'After this many attacks', 'int', 0, 0, 10000, 10),
        ('END_AFTER_HOURS', 'After this many hours', 'int', 0, 0, 168, 1),
        ('END_AFTER_GOLD', 'After gaining this much gold', 'int', 0, 0, 2000000000, 1000000),
        ('END_AFTER_ELIXIR', 'After gaining this much elixir', 'int', 0, 0, 2000000000, 1000000),
        ('END_AFTER_DARK', 'After gaining this much dark elixir', 'int', 0, 0, 100000000, 10000),
    ]),
    ('Helper Hut', [
        ('HELPER_HUT_ENABLED', 'Assign the Builder Apprentice and Lab Assistant to the longest upgrade (every 2-4 h)', 'bool', False),
        ('HELPER_APPRENTICE', 'Builder Apprentice', 'bool', True),
        ('HELPER_LAB_ASSISTANT', 'Lab Assistant', 'bool', True),
    ]),
    ('Super Troops', [
        ('SUPER_TROOP_ENABLED', 'Keep Super Troops boosted (checked every 6 hours)', 'bool', False),
        ('SUPER_TROOPS', 'Troops to boost (max 2), e.g. sneaky_goblin, super_wall_breaker', 'text', ''),
        ('SUPER_TROOP_USE_POTION', 'Use a Super Potion instead of dark elixir when available', 'bool', False),
    ]),
    ('XP Farming', [
        ('XP_FARMING', 'Attack every base regardless of loot (experience farming; combine with End Battle Early)', 'bool', False),
    ]),
    ('End Battle Early (0 = off)', [
        ('END_BATTLE_ENABLED', 'End battles early once all troops are deployed', 'bool', False),
        ('END_BATTLE_STARS', 'When this many stars are reached', 'int', 0, 0, 3, 1),
        ('END_BATTLE_DAMAGE', 'When damage reaches this percent', 'int', 0, 0, 100, 5),
        ('END_BATTLE_NO_CHANGE_SECONDS', 'When damage and loot stop changing for this many seconds', 'int', 0, 0, 180, 5),
    ]),
]


class LogRedirect(QObject):
    text_written = Signal(str)

    def write(self, text):
        if text.strip():
            ts = datetime.datetime.now().strftime('%H:%M:%S')
            line = f'[{ts}] {text.strip()}'
            self.text_written.emit(line)

    def flush(self):
        pass


class ProfileListDelegate(QStyledItemDelegate):
    EDIT_TOOL_TEXT = '✏️'
    LOAD_TOOL_TEXT = '⚙'
    TOOL_WIDTH = 24
    TOOL_SPACING = 4

    @classmethod
    def tool_rects(cls, rect):
        r = rect
        load_rect = QRect(r.right() - cls.TOOL_WIDTH - 8, r.top(), cls.TOOL_WIDTH, r.height())
        edit_rect = QRect(load_rect.left() - cls.TOOL_WIDTH - cls.TOOL_SPACING, r.top(), cls.TOOL_WIDTH, r.height())
        return edit_rect, load_rect

    def paint(self, painter, option, index):
        opt = option
        p = painter
        super().paint(p, opt, index)
        p.save()
        try:
            edit_rect, load_rect = self.tool_rects(opt.rect)
            color = opt.palette.color(QPalette.Text)
            p.setPen(color)
            p.drawText(edit_rect, Qt.AlignCenter, self.EDIT_TOOL_TEXT)
            p.drawText(load_rect, Qt.AlignCenter, self.LOAD_TOOL_TEXT)
        finally:
            p.restore()


class MainWindow(QMainWindow):

    # ------------------------------------------------------------------ bot.config (window state)
    def _bot_config_path(self):
        return resolve_writable_path('bot.config')

    def _load_bot_config(self):
        path = self._bot_config_path()
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_bot_config(self, data):
        path = self._bot_config_path()
        path.write_text(json.dumps(data, indent=2), encoding='utf-8')

    def _restore_window_state_from_bot_config(self):
        state = self._load_bot_config().get('window_state')
        if not isinstance(state, dict):
            return
        try:
            x = int(state.get('x', self.x()))
            y = int(state.get('y', self.y()))
            w = int(state.get('width', self.width()))
            h = int(state.get('height', self.height()))
        except (TypeError, ValueError):
            return
        if w < 700 or h < 500:
            return
        rect = QRect(x, y, w, h)
        for screen in QApplication.screens():
            if screen.availableGeometry().intersects(rect):
                self.setGeometry(rect)
                return

    def _save_window_state_to_bot_config(self):
        if not getattr(self, '_window_state_ready', False):
            return
        geo = self.geometry()
        data = self._load_bot_config()
        data['window_state'] = {'x': int(geo.x()), 'y': int(geo.y()),
                                'width': int(geo.width()), 'height': int(geo.height())}
        try:
            self._save_bot_config(data)
        except Exception:
            pass

    def _schedule_window_state_save(self):
        if not getattr(self, '_window_state_ready', False):
            return
        self._window_state_save_timer.start(250)

    def _update_window_title(self):
        from utils.update_checker import APP_NAME, APP_VERSION
        base = f'{APP_NAME} v{APP_VERSION}'
        parts = []
        emulator = self.emulator_select.currentText().strip() if hasattr(self, 'emulator_select') else ''
        port = (self.adb_port_input.text() or '').strip() if hasattr(self, 'adb_port_input') else ''
        if emulator and port:
            parts.append(f'{emulator}:{port}')
        elif emulator:
            parts.append(emulator)
        self.setWindowTitle(base + (' | ' + ' | '.join(parts) if parts else ''))

    # ------------------------------------------------------------------ emulator / ADB settings (GLOBAL config)
    def _save_emulator_global_settings(self):
        if not getattr(self, '_emulator_settings_ready', False):
            return
        cfg = self.config_mgr.load()
        key = self.emulator_display_to_key.get(self.emulator_select.currentText(), 'bluestacks')
        cfg['EMULATOR_SELECTION'] = key
        cfg['EMULATOR_IP'] = (self.emulator_ip_input.text() or '127.0.0.1').strip()
        cfg['EMULATOR_PORT'] = (self.adb_port_input.text() or startup.get_default_adb_port(key)).strip()
        self.config_mgr.save(cfg)

    def _on_emulator_ip_changed(self, value):
        ip = (value or '').strip()
        adb.set_host(ip if ip else '127.0.0.1')
        self._save_emulator_global_settings()

    def _on_adb_port_changed(self, value):
        port = value
        if port.isdigit():
            self.adb_port = port
            adb.set_port(port)
            self._save_emulator_global_settings()
        self._update_window_title()

    def _on_emulator_changed(self, display_name, apply_default_port=True):
        key = self.emulator_display_to_key.get(display_name, 'bluestacks')
        startup.set_selected_emulator(key)
        adb.set_emulator(key)
        if apply_default_port:
            port = startup.get_default_adb_port(key)
            self.adb_port_input.setText(port)
        self._save_emulator_global_settings()
        self._update_window_title()

    def _toggle_settings_drawer(self):
        self.settings_drawer_expanded = not self.settings_drawer_expanded
        self.settings_toggle_btn.setText('Settings ▾' if self.settings_drawer_expanded else 'Settings ▸')
        self._position_settings_drawer()
        full_h = self.settings_drawer.height()
        target_h = 196 if self.settings_drawer_expanded else 0
        x = self.settings_drawer.x()
        w = self.settings_drawer.width()
        bottom = self.settings_toggle_btn.y() - 6
        start_rect = QRect(x, bottom - full_h, w, full_h)
        end_rect = QRect(x, bottom - target_h, w, target_h)
        self.settings_drawer.show()
        self.settings_drawer.raise_()
        self.settings_drawer_anim.stop()
        self.settings_drawer_anim.setStartValue(start_rect)
        self.settings_drawer_anim.setEndValue(end_rect)
        self.settings_drawer_anim.start()

    def _position_settings_drawer(self):
        if not hasattr(self, 'settings_drawer') or not hasattr(self, 'settings_toggle_btn'):
            return
        w = max(160, self.nav.width() - 16)
        h = self.settings_drawer.height()
        x = 8
        bottom = self.settings_toggle_btn.y() - 6
        y = bottom - h
        self.settings_drawer.setGeometry(x, y, w, h)

    # ------------------------------------------------------------------ assets / paywall helpers
    def _asset_path(self, name):
        return str(resolve_resource_path(f'assets/{name}'))

    def _asset_url(self, name):
        return self._asset_path(name).replace('\\', '/')

    def _set_combo_item_enabled(self, combo, item_text, enabled):
        idx = combo.findText(item_text)
        if idx < 0:
            return
        item = combo.model().item(idx)
        if not item:
            return
        item.setEnabled(enabled)
        if enabled:
            item.setForeground(QColor('#E6E6E6'))
            item.setData(None, Qt.ToolTipRole)
        else:
            item.setForeground(QColor('#6A6E7A'))
            item.setData('Available in paid edition', Qt.ToolTipRole)

    def _apply_locked_strategy_items(self, combo):
        for name in LOCKED_STRATEGIES:
            self._set_combo_item_enabled(combo, name, False)

    # ------------------------------------------------------------------ construction
    def __init__(self):
        super().__init__()
        self._window_state_ready = False
        self._window_state_save_timer = QTimer(self)
        self._window_state_save_timer.setSingleShot(True)
        self._window_state_save_timer.timeout.connect(self._save_window_state_to_bot_config)
        self.config_mgr = ConfigManager()
        self.current_profile = None
        self.enter_shortcut = QShortcut(QKeySequence(Qt.Key_Return), self)
        self.enter_shortcut.activated.connect(self.handle_enter)
        self.enter_shortcut2 = QShortcut(QKeySequence(Qt.Key_Enter), self)
        self.enter_shortcut2.activated.connect(self.handle_enter)
        self.setWindowIcon(QIcon(self._asset_path('icon.png')))
        self.strategy_map = {'Electric Dragon/Loon': 'edragon', 'Dragon/Loon': 'dragon',
                             'Valkyrie + Quake': 'valkyrie', 'Super Minion + Quake': 'sminion',
                             'Super Barbarian': 'sbarb', 'BArch / Goblin': 'barch', 'Thrower Smash': 'thrower',
                             'Custom Script (CSV)': 'csv'}
        self.strategy_help = {
            'Electric Dragon/Loon':
                '• Any # Electro Dragons\n• Any # Balloons\n• Up to 5 Rage +  4 Freeze\n• Funnel with up to 4 heroes\n• Any siege machine (preferably Stone Slammer)\n• CC: Any troop with 1 Rage + 1 Freeze',
            'Dragon/Loon':
                '• Any # Dragons\n• Any # Balloons\n• Up to 5 Rage +  4 Freeze\n• Funnel with up to 4 heroes\n• Any siege machine (preferably Stone Slammer)\n• CC: Any troop with 1 Rage + 1 Freeze',
            'Valkyrie + Quake':
                '• Any # Valkyries\n• 11x Earthquake\n• Funnel with up to 4 heroes\n• Any siege machine (preferably Wall Wrecker or Log Launcher)\n• CC: Super Valkyrie & Super Yeti with Totem Spells(Will drop on th)',
            'Super Minion + Quake':
                '• Any #Super Minions\n• 11x Earthquake\n• Funnel with up to 4 heroes\n• Any siege machine (preferably Wall Wrecker or Log Launcher)\n• CC: Super Valkyrie & Super Yeti with Totem Spells(Will drop on th)',
            'Super Barbarian':
                '• Super Barbarians (any count)\n• Wall Breakers optional\n• 2+ Rage\n• Heroes and any siege\n• Script: CSV\\Attack\\ACBot-Super Barb.csv',
            'BArch / Goblin':
                '• Barbarians, Archers and/or Goblins (normal or super)\n• No spells needed\n• Spreads all around the base to farm outside collectors\n• Script: CSV\\Attack\\ACBot-BArch Goblin.csv',
            'Thrower Smash':
                '• Throwers with the army in the script NOTE lines\n• Script: CSV\\Attack\\PHMOD-Thrower Smash.csv',
            'Custom Script (CSV)':
                '• Runs a MyBot/PHMOD-format attack script from CSV\\Attack\n• Train the army listed in the script (TRAIN lines / NOTE header)\n• Troops missing from your bar are skipped\n• Add your own scripts by dropping .csv files into CSV\\Attack',
        }

        bangers_path = self._asset_path('Bangers-Regular.ttf')
        inter_path = self._asset_path('Inter-Regular.ttf')
        inter_bold_path = self._asset_path('Inter-Bold.ttf')
        bangers_id = QFontDatabase.addApplicationFont(bangers_path)
        inter_id = QFontDatabase.addApplicationFont(inter_path)
        inter_bold_id = QFontDatabase.addApplicationFont(inter_bold_path)
        if bangers_id != -1:
            self.font_title = QFontDatabase.applicationFontFamilies(bangers_id)[0]
        else:
            print('❌ Failed to load Bangers')
            self.font_title = 'Arial'
        if inter_id != -1:
            self.font_ui = QFontDatabase.applicationFontFamilies(inter_id)[0]
        else:
            print('❌ Failed to load Inter')
            self.font_ui = 'Arial'
        if inter_bold_id != -1:
            self.font_ui_bold = QFontDatabase.applicationFontFamilies(inter_bold_id)[0]
        else:
            print('❌ Failed to load Inter Bold')
            self.font_ui_bold = self.font_ui
        QApplication.instance().setFont(QFont(self.font_ui, 11))
        self._update_window_title()
        self.setFixedSize(1000, 650)
        self.setStyleSheet('''
QMainWindow {
        background-image: url("%s");
    background-position: center;
    background-repeat: no-repeat;
    background-color: #14161A;
        border-top: 2px solid #3B82F6;
}

QMainWindow::title {
        background-color: #171A21;
        color: #F4D37A;
}
                
QFrame {
    background-color: rgba(28, 31, 38, 235);
}

#NavPanel {
        background-color: #1D212A;
        border-right: 1px solid #2A2F3B;
}

#BottomBar {
        background-color: #171A21;
        border-top: 1px solid #2A2F3B;
}

/* ---------------- Buttons ---------------- */

QPushButton {
    background-color: #242834;
    color: #E6E6E6;
        border: 1px solid #181B24;
        border-radius: 8px;

    padding: 10px 12px;
    margin: 4px 6px;

    text-align: left;
    font-family: "%s";
    font-size: 18px;
}

QPushButton:hover {
        background-color: #2D3240;
        border: 1px solid #222737;
}

QPushButton:pressed {
        background-color: #1F2330;
        border: 1px solid #141824;
}
                           
QListWidget {
    background-color: rgba(28, 31, 38, 10);
        color: #E6E6E6;
    border: none;
}

QListWidget::item {
        border-radius: 6px;
        padding: 6px 8px;
}

QListWidget::item:hover {
        background-color: rgba(70, 80, 102, 0.45);
}

QListWidget::item:selected {
        background-color: transparent;
        border: none;
}

QListWidget::item:selected:active {
        background-color: transparent;
        border: none;
}

QListWidget#ProfileListWidget::indicator {
        width: 16px;
        height: 16px;
        border-radius: 3px;
}

QListWidget#ProfileListWidget::indicator:unchecked {
        border: 2px solid #EF4444;
        background: rgba(239, 68, 68, 0.15);
}

QListWidget#ProfileListWidget::indicator:checked {
        border: 2px solid #22C55E;
        background: rgba(34, 197, 94, 0.22);
}

QListWidget#ProfileListWidget::indicator:unchecked:hover {
        border: 2px solid #F87171;
        background: rgba(248, 113, 113, 0.2);
}

QListWidget#ProfileListWidget::indicator:checked:hover {
        border: 2px solid #4ADE80;
        background: rgba(74, 222, 128, 0.28);
}

/* Sidebar buttons ONLY */
QFrame QPushButton:hover {
    background-color: #2F3546;
}

QPushButton:checked {
    background-color: #3B82F6;
        border: 1px solid #2B62BD;
    color: white;
}

/* ---------------- Tabs ---------------- */

QTabWidget::pane {
        background: transparent;
        border: none;
        margin-top: 0px;
        top: -10px;
}

QTabWidget > QWidget {
        background: transparent;
        border: none;
}

QTabBar {
        background: transparent;
}

QTabBar::tab {
        background-color: rgba(36, 40, 52, 200);
        color: #C9CCD6;
        border-left: 1px solid #3A4253;
        border-top: 1px solid #3A4253;
        border-right: 1px solid #3A4253;
        border-bottom: none;
        border-top-left-radius: 8px;
        border-top-right-radius: 8px;
        border-bottom-left-radius: 0px;
        border-bottom-right-radius: 0px;
        padding: 6px 12px;
        margin-right: 6px;
        font-family: "%s";
        font-size: 14px;
        font-weight: bold;
}

QTabBar::tab:selected {
        background-color: #3B82F6;
        border-left: 1px solid #60A5FA;
        border-top: 1px solid #60A5FA;
        border-right: 1px solid #60A5FA;
        color: white;
}

QTabBar::tab:hover:!selected {
        background-color: #2F3546;
}

/* ---------------- Text ---------------- */

QLabel {
    color: #C9CCD6;
    background: transparent;
}

QCheckBox {
    color: #C9CCD6;
}

QTextEdit {
    color: #C9CCD6;
    background-color: rgba(28, 31, 38, 10);
}

QLineEdit,
QComboBox,
QSpinBox {
    color: #E6E6E6;
        background-color: #1B1F2A;
        border: 1px solid #2A2F3B;
        border-radius: 6px;
}

QLineEdit:hover,
QSpinBox:hover {
        border: 1px solid #3A4253;
}

QLineEdit:focus,
QSpinBox:focus {
        border: 1px solid #60A5FA;
}

QComboBox {
        padding-left: 8px;
        padding-right: 26px;
}

QComboBox::drop-down {
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 18px;
        margin-right: 2px;
        border: none;
        background: transparent;
}

QComboBox::down-arrow {
        image: url("%s");
        width: 12px;
        height: 8px;
}

QComboBox QAbstractItemView {
    color: #E6E6E6;
    background-color: #1B1F2A;
    selection-background-color: #3B82F6;
    selection-color: #FFFFFF;
}

QSpinBox {
        padding-right: 24px;
}

QSpinBox::up-button,
QSpinBox::down-button {
        subcontrol-origin: padding;
        width: 14px;
        margin-right: 2px;
        background: transparent;
        border: none;
}

QSpinBox::up-button:hover,
QSpinBox::down-button:hover {
        background: rgba(96, 165, 250, 0.16);
}

QSpinBox::up-button:pressed,
QSpinBox::down-button:pressed {
        background: rgba(96, 165, 250, 0.28);
}

QSpinBox::up-button {
        subcontrol-position: top right;
}

QSpinBox::down-button {
        subcontrol-position: bottom right;
}

QSpinBox::up-arrow,
QSpinBox::down-arrow {
        width: 12px;
        height: 8px;
}

QSpinBox::up-arrow {
        image: url("%s");
}

QSpinBox::down-arrow {
        image: url("%s");
}

QScrollBar:vertical {
        background: #171A21;
        width: 10px;
        margin: 2px;
        border-radius: 5px;
}

QScrollBar::handle:vertical {
        background: rgba(220, 225, 235, 0.55);
        min-height: 24px;
        border-radius: 5px;
}

QScrollBar::handle:vertical:hover {
        background: rgba(220, 225, 235, 0.78);
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
        background: transparent;
        height: 0px;
}

QScrollBar:horizontal {
        background: #171A21;
        height: 10px;
        margin: 2px;
        border-radius: 5px;
}

QScrollBar::handle:horizontal {
        background: rgba(220, 225, 235, 0.55);
        min-width: 24px;
        border-radius: 5px;
}

QScrollBar::handle:horizontal:hover {
        background: rgba(220, 225, 235, 0.78);
}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {
        background: transparent;
        width: 0px;
}

/* Disabled */

QLineEdit:disabled,
QComboBox:disabled,
QSpinBox:disabled,
QCheckBox:disabled,
QTextEdit:disabled {
    color: #6A6E7A;
    background-color: #16181D;
}

/* Minimum widget height */

QSpinBox,
QComboBox,
QCheckBox {
    min-height: 26px;
}

/* ---------------- Group Boxes ---------------- */

QGroupBox {
    color: #F4D37A;
    font-family: "%s";
    font-weight: bold;
    font-size: 16px;

    border: 1px solid #151819;
    border-radius: 6px;

    margin-top: 10px;
    padding-top: 12px;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
}

#AttackArmyPageGroup {
        border-top-left-radius: 0px;
        border-top-right-radius: 0px;
        border-bottom-left-radius: 6px;
        border-bottom-right-radius: 6px;
}
                           
/* -------- Bottom Control Buttons -------- */

#StartBtn {
    background-color: #22C55E;
    color: white;
    text-align: center;
    font-size: 26px;
    font-weight: bold;
    border-radius: 6px;
}

#PauseBtn {
    background-color: #FACC15;
    color: white;
    text-align: center;
    font-size: 24px;
    font-weight: bold;
    border-radius: 6px;
}

#StopBtn {
    background-color: #EF4444;
    color: white;
    text-align: center;
    font-size: 26px;
    font-weight: bold;
    border-radius: 6px;
}
QPushButton[locked="true"] {
    opacity: 0.5;
}

#SettingsToggleBtn {
        font-size: 14px;
        font-weight: bold;
        text-align: left;
        padding: 8px 10px;
        margin: 6px;
}

#SettingsDrawer {
        background-color: #171A21;
        border: 2px solid #2F3546;
        border-radius: 8px;
        padding: 0px;
        margin: 0px;
}

#SettingsDrawer QLabel {
        padding-left: 0px;
        margin-left: 0px;
}

#SettingsDrawer QComboBox,
#SettingsDrawer QLineEdit {
        padding-left: 0px;
        margin-left: 0px;
}
                           
#StartBtn,
#PauseBtn,
#StopBtn {
        border-radius: 10px;
        border: 1px solid rgba(0, 0, 0, 0.35);
    padding: 0px;
}

/* Hover polish */

#StartBtn:hover { background-color: #16A34A; }
#PauseBtn:hover { background-color: #EAB308; }
#StopBtn:hover { background-color: #DC2626; }
#StartBtn:pressed { background-color: #15803D; }
#PauseBtn:pressed { background-color: #CA8A04; }
#StopBtn:pressed  { background-color: #B91C1C; }

#DeselectProfileBtn:hover { background-color: #3A414D; }
#DeselectProfileBtn:pressed { background-color: #2F3540; }

#DeleteProfilesBtn {
        background-color: #7F1D1D;
        color: #FEE2E2;
}
#DeleteProfilesBtn:hover { background-color: #991B1B; }
#DeleteProfilesBtn:pressed { background-color: #B91C1C; }

/* Tooltips */
QToolTip {
    background-color: #2E3440;
    color: #ECEFF4;
    border: 1px solid #4C566A;
    padding: 4px;
    border-radius: 4px;
}
                
''' % (
            self._asset_url('bg.png'), self.font_title, self.font_ui_bold, self._asset_url('arrow_down.svg'),
            self._asset_url('arrow_up.svg'), self._asset_url('arrow_down.svg'), self.font_ui_bold))

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        body_layout = QHBoxLayout()
        body_layout.setSpacing(0)
        body_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addLayout(body_layout, 1)

        self.nav = QFrame()
        self.nav.setObjectName('NavPanel')
        self.nav.setFixedWidth(220)
        nav_layout = QVBoxLayout(self.nav)
        nav_layout.setSpacing(0)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        self.buttons = []
        self.pages = {}
        page_names = ['General', 'Attack Army', 'Pro Features', 'Multi Village', 'Statistics', 'Log']
        self.stack = QStackedWidget()

        for name in page_names:
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _, n=name: self.switch_page(n))
            nav_layout.addWidget(btn)
            self.buttons.append(btn)

            if name == 'General':
                page = QWidget()
                layout = QVBoxLayout(page)
                layout.setContentsMargins(20, 20, 20, 20)
                layout.setSpacing(12)
                walls_box = QGroupBox('Wall Upgrades')
                walls_grid = QGridLayout(walls_box)
                self.upgrade_walls = QCheckBox('Upgrade Walls')
                walls_grid.addWidget(self.upgrade_walls, 0, 0)
                filter_box = QGroupBox('Attack Filter')
                filter_grid = QGridLayout(filter_box)
                self.attack_gold = QSpinBox()
                self.attack_elixir = QSpinBox()
                self.attack_dark = QSpinBox()
                for spin in (self.attack_gold, self.attack_elixir):
                    spin.setRange(0, 50000000)
                    spin.setSingleStep(200000)
                    spin.setGroupSeparatorShown(True)
                self.attack_dark.setRange(0, 50000)
                self.attack_dark.setSingleStep(500)
                self.attack_dark.setGroupSeparatorShown(True)
                filter_grid.addWidget(QLabel('Min Gold'), 0, 0)
                filter_grid.addWidget(self.attack_gold, 0, 1)
                filter_grid.addWidget(QLabel('Min Elixir'), 1, 0)
                filter_grid.addWidget(self.attack_elixir, 1, 1)
                filter_grid.addWidget(QLabel('Min Dark'), 2, 0)
                filter_grid.addWidget(self.attack_dark, 2, 1)
                donations_box = QGroupBox('Donations')
                donations_layout = QVBoxLayout(donations_box)
                donations_layout.setSpacing(10)
                self.request_donations = QCheckBox('Request Donations')
                donations_layout.addWidget(self.request_donations)
                cg_box = QGroupBox('Clan Games')
                cg_layout = QVBoxLayout(cg_box)
                self.clan_games_enable = QCheckBox('Enable Clan Games')
                cg_layout.addWidget(self.clan_games_enable)
                cg_sub = QHBoxLayout()
                cg_sub.setContentsMargins(20, 0, 0, 0)
                self.cg_troop_challenges = QCheckBox('Enable Super Troop Challenges')
                cg_sub.addWidget(self.cg_troop_challenges)
                cg_layout.addLayout(cg_sub)
                layout.addWidget(walls_box)
                layout.addWidget(filter_box)
                layout.addWidget(donations_box)
                layout.addWidget(cg_box)
                layout.addStretch()

                cfg = self.config_mgr.load(self.current_profile)
                self.upgrade_walls.setChecked(cfg.get('UPGRADE_WALLS', False))
                self.attack_gold.setValue(cfg.get('ATTACK_MIN_GOLD', 0))
                self.attack_elixir.setValue(cfg.get('ATTACK_MIN_ELIXIR', 0))
                self.attack_dark.setValue(cfg.get('ATTACK_MIN_DARK', 0))
                self.request_donations.setChecked(cfg.get('REQUEST_DONATIONS', False))
                self.clan_games_enable.setChecked(cfg.get('CLAN_GAMES', False))
                self.cg_troop_challenges.setChecked(cfg.get('CG_TROOP_CHALLENGES', False))
                self._sync_clan_games_options()
                self.upgrade_walls.stateChanged.connect(self.update_general)
                self.attack_gold.valueChanged.connect(self.update_general)
                self.attack_elixir.valueChanged.connect(self.update_general)
                self.attack_dark.valueChanged.connect(self.update_general)
                self.request_donations.stateChanged.connect(self.update_donations)
                self.clan_games_enable.stateChanged.connect(self._sync_clan_games_options)
                self.clan_games_enable.stateChanged.connect(self.update_general)
                self.cg_troop_challenges.stateChanged.connect(self.update_general)

            elif name == 'Attack Army':
                page = QWidget()
                layout = QVBoxLayout(page)
                layout.setContentsMargins(20, 20, 20, 20)
                layout.setSpacing(12)
                tabs = QTabWidget()
                army_tab = QWidget()
                army_tab_layout = QVBoxLayout(army_tab)
                army_tab_layout.setContentsMargins(0, 0, 0, 0)
                army_tab_layout.setSpacing(12)
                tabs.addTab(army_tab, 'Attack Army')
                layout.addWidget(tabs)
                atk_box = QGroupBox('Attack Settings')
                atk_grid = QGridLayout(atk_box)
                atk_grid.setHorizontalSpacing(10)
                atk_grid.setVerticalSpacing(8)
                self.hero_tap_delay_enabled = QCheckBox('Hero Re-Tap Delay')
                atk_grid.addWidget(self.hero_tap_delay_enabled, 0, 0)
                self.hero_tap_delay_seconds = QSpinBox()
                self.hero_tap_delay_seconds.setRange(1, 15)
                atk_grid.addWidget(self.hero_tap_delay_seconds, 0, 1)
                self.air_troop_width_enabled = QCheckBox('Air Troop Spread')
                atk_grid.addWidget(self.air_troop_width_enabled, 1, 0)
                self.air_troop_width = QSpinBox()
                self.air_troop_width.setRange(50, 600)
                self.air_troop_width.setSingleStep(50)
                atk_grid.addWidget(self.air_troop_width, 1, 1)
                layout.addWidget(atk_box)

                cfg = self.config_mgr.load(self.current_profile)
                self.hero_tap_delay_enabled.setChecked(cfg.get('HERO_TAP_DELAY_ENABLED', False))
                hero_delay = int(cfg.get('HERO_TAP_DELAY_SECONDS', 1) or 1)
                hero_delay = max(1, min(15, hero_delay))
                self.hero_tap_delay_seconds.setValue(hero_delay)
                self.hero_tap_delay_seconds.setEnabled(self.hero_tap_delay_enabled.isChecked())
                self.air_troop_width_enabled.setChecked(cfg.get('AIR_TROOP_WIDTH_ENABLED', False))
                air_width = int(cfg.get('AIR_TROOP_WIDTH', 300) or 300)
                air_width = max(50, min(500, air_width))   # NB: spinbox allows up to 600, loader clamps to 500
                self.air_troop_width.setValue(air_width)
                self.air_troop_width.setEnabled(self.air_troop_width_enabled.isChecked())
                self.hero_tap_delay_enabled.stateChanged.connect(
                    lambda: (self.hero_tap_delay_seconds.setEnabled(self.hero_tap_delay_enabled.isChecked()),
                             self.update_attack_army()))
                self.hero_tap_delay_seconds.valueChanged.connect(self.update_attack_army)
                self.air_troop_width_enabled.stateChanged.connect(
                    lambda: (self.air_troop_width.setEnabled(self.air_troop_width_enabled.isChecked()),
                             self.update_attack_army()))
                self.air_troop_width.valueChanged.connect(self.update_attack_army)

                army_group = QGroupBox('')
                army_group.setObjectName('AttackArmyPageGroup')
                army_layout = QVBoxLayout(army_group)
                army_layout.setSpacing(12)
                army_layout.addWidget(QLabel('Attack Strategy'))
                self.strategy = QComboBox()
                army_layout.addWidget(self.strategy)
                self.strategy.addItems(self.strategy_map.keys())
                self._apply_locked_strategy_items(self.strategy)
                self.strategy.setToolTip('Strategy used for multiplayer attacks')
                army_layout.addWidget(QLabel('Attack Script (Custom Script strategy)'))
                self.csv_script = QComboBox()
                from attack.csv_script import list_scripts
                self.csv_script.addItems(list_scripts())
                self.csv_script.setEnabled(self.strategy_map.get(self.strategy.currentText()) == 'csv')
                army_layout.addWidget(self.csv_script)
                self.csv_redline = QCheckBox('Drop on the detected red line (off: outer map edges)')
                self.csv_redline.setChecked(True)
                self.csv_redline.setToolTip('Finds the dashed deploy border around the enemy base while scouting '
                                            'and starts every script vector there, as MyBot does.')
                self.csv_redline.setEnabled(self.csv_script.isEnabled())
                army_layout.addWidget(self.csv_redline)
                army_layout.addWidget(QLabel('Army Slot'))
                self.army_slot = QComboBox()
                self.army_slot.addItems([f'Slot {i}' for i in range(1, 9)])
                self.army_slot.addItem('Current Army')
                army_layout.addWidget(self.army_slot)
                army_layout.addWidget(QLabel('Army Composition Suggestion'))
                self.strategy_info = QTextEdit()
                self.strategy_info.setReadOnly(True)
                self.strategy_info.setMinimumHeight(130)
                self.strategy_info.setMaximumHeight(130)
                army_layout.addWidget(self.strategy_info)
                army_layout.addStretch()
                army_tab_layout.addWidget(army_group)
                army_tab_layout.addStretch()
                self.strategy_info.setText(self.strategy_help.get(self.strategy.currentText(), ''))
                self.army_slot.currentIndexChanged.connect(self.update_attack_army)
                self.strategy.currentIndexChanged.connect(self.update_attack_army)
                self.strategy.currentIndexChanged.connect(
                    lambda: self.strategy_info.setText(self.strategy_help.get(self.strategy.currentText(), '')))
                self.strategy.currentIndexChanged.connect(
                    lambda: self.csv_script.setEnabled(self.strategy_map.get(self.strategy.currentText()) == 'csv'))
                self.strategy.currentIndexChanged.connect(
                    lambda: self.csv_redline.setEnabled(self.strategy_map.get(self.strategy.currentText()) == 'csv'))
                self.csv_script.currentIndexChanged.connect(self.update_attack_army)
                self.csv_redline.stateChanged.connect(self.update_attack_army)

            elif name == 'Pro Features':
                # New: war / Builder Base / ranked options (modules war.py, builder_base.py, ranked.py).
                content = QWidget()
                layout = QVBoxLayout(content)
                layout.setContentsMargins(20, 20, 20, 20)
                layout.setSpacing(12)
                from attack.csv_script import list_scripts
                war_box = QGroupBox('Clan War / CWL')
                war_grid = QGridLayout(war_box)
                self.war_enable = QCheckBox('Attack in Clan War and CWL (uses real war attacks)')
                war_grid.addWidget(self.war_enable, 0, 0, 1, 2)
                war_grid.addWidget(QLabel('Attacks per war'), 1, 0)
                self.war_max = QSpinBox()
                self.war_max.setRange(1, 2)
                war_grid.addWidget(self.war_max, 1, 1)
                war_grid.addWidget(QLabel('War strategy'), 2, 0)
                self.war_strategy = QComboBox()
                self.war_strategy.addItems(['Electric Dragon/Loon', 'Dragon/Loon', 'Custom Script (CSV)'])
                war_grid.addWidget(self.war_strategy, 2, 1)
                war_grid.addWidget(QLabel('War script'), 3, 0)
                self.war_script = QComboBox()
                self.war_script.addItems(list_scripts())
                war_grid.addWidget(self.war_script, 3, 1)
                bb_box = QGroupBox('Builder Base')
                bb_grid = QGridLayout(bb_box)
                self.bb_enable = QCheckBox('Builder Base battles (both stages, Battle Machine ability, Star Bonus)')
                bb_grid.addWidget(self.bb_enable, 0, 0, 1, 2)
                self.bb_only = QCheckBox('Builder Base battles ONLY (no home village attacks, stays on the Builder Base)')
                bb_grid.addWidget(self.bb_only, 3, 0, 1, 2)
                bb_grid.addWidget(QLabel('Battles per visit'), 1, 0)
                self.bb_attacks = QSpinBox()
                self.bb_attacks.setRange(1, 20)
                bb_grid.addWidget(self.bb_attacks, 1, 1)
                bb_grid.addWidget(QLabel('Visit every (minutes)'), 2, 0)
                self.bb_interval = QSpinBox()
                self.bb_interval.setRange(10, 720)
                self.bb_interval.setSingleStep(10)
                bb_grid.addWidget(self.bb_interval, 2, 1)
                ranked_box = QGroupBox('Ranked Battles')
                ranked_layout = QVBoxLayout(ranked_box)
                self.ranked_signup = QCheckBox('Sign up for Ranked Battle tournaments automatically')
                ranked_layout.addWidget(self.ranked_signup)
                layout.addWidget(war_box)
                layout.addWidget(bb_box)
                layout.addWidget(ranked_box)
                self.pro_widgets = {}
                for title, specs in PRO_SETTING_GROUPS:
                    layout.addWidget(self._build_spec_group(title, specs))
                layout.addStretch()
                page = QScrollArea()
                page.setWidgetResizable(True)
                page.setFrameShape(QFrame.NoFrame)
                page.setWidget(content)
                self._load_pro_features(self.config_mgr.load(self.current_profile))
                for w in (self.war_enable, self.bb_enable, self.ranked_signup, self.bb_only):
                    w.stateChanged.connect(self.update_pro_features)
                for w in (self.war_max, self.bb_attacks, self.bb_interval):
                    w.valueChanged.connect(self.update_pro_features)
                for w in (self.war_strategy, self.war_script):
                    w.currentIndexChanged.connect(self.update_pro_features)

            elif name == 'Multi Village':
                page = QWidget()
                outer = QHBoxLayout(page)
                outer.setContentsMargins(20, 20, 20, 20)
                outer.setSpacing(12)
                left_col = QVBoxLayout()
                left_col.setSpacing(12)
                self.multi_box = QGroupBox('Multi Village')
                multi_layout = QVBoxLayout(self.multi_box)
                self.multi_enabled = QCheckBox('Enable Multi Village')
                multi_layout.addWidget(self.multi_enabled)
                self.settings_box = QGroupBox('Village Settings')
                vs_grid = QGridLayout(self.settings_box)
                vs_grid.addWidget(QLabel('Start Profile'), 0, 0)
                self.start_profile = QComboBox()
                vs_grid.addWidget(self.start_profile, 0, 1)
                vs_grid.addWidget(QLabel('Village Count'), 1, 0)
                self.village_count = QSpinBox()
                self.village_count.setRange(1, FREE_MAX_VILLAGES)          # Pro cap (100)
                vs_grid.addWidget(self.village_count, 1, 1)
                vs_grid.addWidget(QLabel('Switch Every (min)'), 2, 0)
                self.switch_minutes = QSpinBox()
                self.switch_minutes.setRange(1, 1440)
                vs_grid.addWidget(self.switch_minutes, 2, 1)
                vs_grid.addWidget(QLabel('Switch on Loot Full'), 3, 0)
                self.switch_on_loot_full = QCheckBox()
                self.switch_on_loot_full.setToolTip('Bot will STOP when all profiles have full loot')
                vs_grid.addWidget(self.switch_on_loot_full, 3, 1)
                vs_grid.addWidget(QLabel('Switch when Builders Busy'), 4, 0)
                self.switch_on_builders_busy = QCheckBox()
                self.switch_on_builders_busy.setToolTip(
                    'Move on once every builder of the village is working (after Switch Every minutes)')
                self.switch_on_builders_busy.setChecked(bool(self.config_mgr.load().get('SWITCH_ON_BUILDERS_BUSY', False)))
                self.switch_on_builders_busy.stateChanged.connect(self.update_multi)
                vs_grid.addWidget(self.switch_on_builders_busy, 4, 1)
                self.active_box = QGroupBox('Active Profile')
                active_layout = QVBoxLayout(self.active_box)
                self.active_profile_label = QLabel('None')
                self.active_profile_label.setAlignment(Qt.AlignCenter)
                self.active_profile_label.setFont(QFont(self.font_ui_bold, 12))
                self.profile_timer_label = QLabel('--:--')
                self.profile_timer_label.setAlignment(Qt.AlignCenter)
                self.profile_timer_label.setFont(QFont(self.font_ui_bold, 14))
                self.profile_timer_label.setStyleSheet('color: #22C55E;')
                self.profile_timer_label.setToolTip('<span style="color:#E6E6E6;">Time until switch:</span>')
                active_layout.addWidget(self.active_profile_label)
                active_layout.addWidget(self.profile_timer_label)
                left_col.addWidget(self.multi_box)
                left_col.addWidget(self.settings_box)
                left_col.addWidget(self.active_box)
                self.deselect_btn = QPushButton('Deselect Active Profile')
                self.deselect_btn.setObjectName('DeselectProfileBtn')
                self.deselect_btn.setStyleSheet('QPushButton#DeselectProfileBtn:hover { background-color: #3A414D; }'
                                                'QPushButton#DeselectProfileBtn:pressed { background-color: #2F3540; }')
                self.deselect_btn.setToolTip('Clear active profile and load GLOBAL config')
                self.deselect_btn.setEnabled(False)
                left_col.addWidget(self.deselect_btn)
                self.deselect_btn.clicked.connect(self.deselect_active_profile)
                self.delete_profiles_btn = QPushButton('Delete All Profiles')
                self.delete_profiles_btn.setObjectName('DeleteProfilesBtn')
                self.delete_profiles_btn.setToolTip('Delete all profile folders and active config')
                left_col.addWidget(self.delete_profiles_btn)
                self.delete_profiles_btn.clicked.connect(self.delete_all_profiles)
                left_col.addStretch()
                self.right_box = QGroupBox('Profiles')
                right_layout = QVBoxLayout(self.right_box)
                self.profile_list = QListWidget()
                self.profile_list.setObjectName('ProfileListWidget')
                self.profile_list.setItemDelegate(ProfileListDelegate(self.profile_list))
                self.profile_list.setEditTriggers(QAbstractItemView.NoEditTriggers)
                self.profile_list.setDragDropMode(QAbstractItemView.InternalMove)
                self.profile_list.setDefaultDropAction(Qt.MoveAction)
                self.profile_list.setSelectionMode(QAbstractItemView.SingleSelection)
                self.profile_list.setSelectionBehavior(QAbstractItemView.SelectItems)
                self.profile_list.setToolTip('Double-Click to load profile Config')
                self.profile_list.installEventFilter(self)
                self.profile_list.viewport().installEventFilter(self)
                right_layout.addWidget(self.profile_list)
                outer.addLayout(left_col, 1)
                outer.addWidget(self.right_box, 1)
                self.settings_box.setEnabled(self.multi_enabled.isChecked())
                self.active_box.setEnabled(self.multi_enabled.isChecked())
                self.right_box.setEnabled(self.multi_enabled.isChecked())

                self.multi_enabled.blockSignals(True)
                self.village_count.blockSignals(True)
                self.switch_minutes.blockSignals(True)
                self.switch_on_loot_full.blockSignals(True)
                self.start_profile.blockSignals(True)
                cfg = self.config_mgr.load()
                self.multi_enabled.setChecked(cfg.get('MULTI_VILLAGE_ENABLED', False))
                self.village_count.setValue(cfg.get('VILLAGE_COUNT', 10))   # clamped by setRange(1, 100)
                self.switch_minutes.setValue(cfg.get('VILLAGE_SWITCH_MINUTES', 10))
                self.switch_on_loot_full.setChecked(cfg.get('SWITCH_ON_LOOT_FULL', False))
                self.switch_minutes.setEnabled(not self.switch_on_loot_full.isChecked())
                self.multi_enabled.blockSignals(False)
                self.village_count.blockSignals(False)
                self.switch_minutes.blockSignals(False)
                self.switch_on_loot_full.blockSignals(False)
                self.start_profile.blockSignals(False)
                self.refresh_profile_list()
                self.profile_list.model().rowsMoved.connect(self.save_profile_order)
                self.profile_list.itemChanged.connect(self.save_profile_order)
                self.profile_list.setSpacing(2)
                self.profile_list.itemDoubleClicked.connect(lambda item: self.load_profile(item.data(Qt.UserRole)))
                self.multi_enabled.stateChanged.connect(lambda: (self.update_multi(), self.update_multi_ui()))
                self.village_count.valueChanged.connect(self.update_multi)
                self.switch_minutes.valueChanged.connect(self.update_multi)
                self.switch_on_loot_full.stateChanged.connect(self._on_switch_on_loot_full_changed)
                self.start_profile.currentIndexChanged.connect(self.update_multi)

            elif name == 'Statistics':
                # RECON: condensed 4 group boxes of icon+value QLabel grid setups (layout positions abbreviated)
                page = QWidget()
                layout = QVBoxLayout(page)
                layout.setContentsMargins(20, 20, 20, 20)
                layout.setSpacing(18)
                session_box = QGroupBox('Session')
                session_grid = QGridLayout(session_box)
                session_grid.setVerticalSpacing(14)
                self.stats_runtime = QLabel('00:00:00')
                self.stats_attacks = QLabel('0')
                session_grid.addWidget(QLabel('Runtime:'), 0, 0)
                session_grid.addWidget(self.stats_runtime, 0, 1)
                session_grid.addWidget(QLabel('Total Attacks:'), 1, 0)
                session_grid.addWidget(self.stats_attacks, 1, 1)

                loot_box = QGroupBox('Loot Gained')
                loot_grid = QGridLayout(loot_box)
                loot_grid.setVerticalSpacing(14)
                self.stats_gold = QLabel('0')
                self.stats_gold_hr = QLabel('0 / hr')
                self.stats_elixir = QLabel('0')
                self.stats_elixir_hr = QLabel('0 / hr')
                self.stats_dark = QLabel('0')
                self.stats_dark_hr = QLabel('0 / hr')
                for row, (icon_name, tip, value_lbl, hr_lbl) in enumerate((
                        ('gold.png', 'Gold Gained', self.stats_gold, self.stats_gold_hr),
                        ('elixir.png', 'Elixir Gained', self.stats_elixir, self.stats_elixir_hr),
                        ('dark.png', 'Dark Elixir Gained', self.stats_dark, self.stats_dark_hr))):
                    icon = QLabel()
                    icon.setPixmap(QPixmap(self._asset_path(icon_name)).scaled(32, 32, Qt.KeepAspectRatio,
                                                                               Qt.SmoothTransformation))
                    icon.setToolTip(tip)
                    loot_grid.addWidget(icon, row, 0)
                    loot_grid.addWidget(value_lbl, row, 1)
                    loot_grid.addWidget(hr_lbl, row, 2)

                stars_box = QGroupBox('Stars')
                stars_grid = QGridLayout(stars_box)
                stars_grid.setVerticalSpacing(14)
                self.stats_0 = QLabel('0')
                self.stats_1 = QLabel('0')
                self.stats_2 = QLabel('0')
                self.stats_3 = QLabel('0')
                for lbl in (self.stats_0, self.stats_1, self.stats_2, self.stats_3):
                    lbl.setAlignment(Qt.AlignVCenter)
                for row, (icon_name, tip, value_lbl) in enumerate((
                        ('0star.png', '0 Star Attacks', self.stats_0), ('1star.png', '1 Star Attacks', self.stats_1),
                        ('2star.png', '2 Star Attacks', self.stats_2), ('3star.png', '3 Star Attacks', self.stats_3))):
                    icon = QLabel()
                    icon.setPixmap(QPixmap(self._asset_path(icon_name)).scaledToHeight(32, Qt.SmoothTransformation))
                    icon.setToolTip(tip)
                    stars_grid.addWidget(icon, row, 0)
                    stars_grid.addWidget(value_lbl, row, 1)

                misc_box = QGroupBox('Misc. Stats')
                misc_grid = QGridLayout(misc_box)
                misc_grid.setVerticalSpacing(14)
                misc_grid.setAlignment(Qt.AlignTop)
                walls_icon = QLabel()
                walls_icon.setPixmap(QPixmap(self._asset_path('wallsupgraded.png')).scaledToHeight(
                    32, Qt.SmoothTransformation))
                walls_icon.setToolTip('Walls Upgraded')
                self.stats_walls = QLabel('0')
                self.stats_walls.setAlignment(Qt.AlignCenter)
                misc_grid.addWidget(walls_icon, 0, 0)
                misc_grid.addWidget(self.stats_walls, 0, 1)
                layout.addWidget(session_box)
                layout.addWidget(loot_box)
                bottom_row = QHBoxLayout()
                bottom_row.addWidget(stars_box)
                bottom_row.addWidget(misc_box)
                layout.addLayout(bottom_row)
                layout.addStretch()

            elif name == 'Log':
                page = QWidget()
                layout = QVBoxLayout(page)
                layout.setContentsMargins(20, 20, 20, 20)
                layout.setSpacing(12)
                log_box = QGroupBox('Bot Log')
                log_layout = QVBoxLayout(log_box)
                self.log_view = QTextEdit()
                self.log_view.setReadOnly(True)
                self.log_view.setFont(QFont('Consolas', 12))
                self.log_view.setLineWrapMode(QTextEdit.NoWrap)
                self.log_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
                self.stdout = LogRedirect()
                self.stdout.text_written.connect(self.append_log)
                sys.stdout = self.stdout                         # all print() output is routed to the Log tab
                log_layout.addWidget(self.log_view)
                layout.addWidget(log_box, 1)
                layout.addStretch()

            else:
                page = QLabel(name)
                page.setAlignment(Qt.AlignCenter)

            self.stack.addWidget(page)
            self.pages[name] = page

        # ---- Settings drawer (emulator / IP / ADB port), lives inside the nav panel
        self.emulator_display_to_key = {startup.get_emulator_display_name(k): k for k in startup.get_supported_emulators()}
        self.settings_toggle_btn = QPushButton('Settings ▸')
        self.settings_toggle_btn.setObjectName('SettingsToggleBtn')
        self.settings_drawer = QFrame(self.nav)
        self.settings_drawer.setObjectName('SettingsDrawer')
        self.settings_drawer.setGeometry(8, 0, self.nav.width() - 16, 0)
        self.settings_drawer.hide()
        drawer_grid = QGridLayout(self.settings_drawer)
        drawer_grid.setContentsMargins(8, 8, 4, 8)
        drawer_grid.setHorizontalSpacing(0)
        drawer_grid.setVerticalSpacing(6)
        drawer_grid.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        emu_label = QLabel('Emulator')
        emu_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        drawer_grid.addWidget(emu_label, 0, 0, 1, 1, Qt.AlignLeft)
        self.emulator_select = QComboBox()
        self.emulator_select.addItems(list(self.emulator_display_to_key))
        self.emulator_select.setMinimumWidth(170)
        drawer_grid.addWidget(self.emulator_select, 1, 0, 1, 1, Qt.AlignLeft)
        ip_label = QLabel('Emulator IP')
        ip_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        drawer_grid.addWidget(ip_label, 2, 0, 1, 1, Qt.AlignLeft)
        self.emulator_ip_input = QLineEdit()
        self.emulator_ip_input.setText('127.0.0.1')
        self.emulator_ip_input.setFixedWidth(130)
        drawer_grid.addWidget(self.emulator_ip_input, 3, 0, 1, 1, Qt.AlignLeft)
        port_label = QLabel('ADB Port')
        port_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        drawer_grid.addWidget(port_label, 4, 0, 1, 1, Qt.AlignLeft)
        self.adb_port = startup.get_default_adb_port('bluestacks')
        self.adb_port_input = QLineEdit()
        self.adb_port_input.setText(self.adb_port)
        self.adb_port_input.setFixedWidth(70)
        drawer_grid.addWidget(self.adb_port_input, 5, 0, 1, 1, Qt.AlignLeft)
        self._emulator_settings_ready = False
        self.emulator_select.currentTextChanged.connect(self._on_emulator_changed)
        self.emulator_ip_input.textChanged.connect(self._on_emulator_ip_changed)
        self.adb_port_input.textChanged.connect(self._on_adb_port_changed)
        self.settings_toggle_btn.clicked.connect(self._toggle_settings_drawer)
        self.settings_drawer_expanded = False
        self.settings_drawer_anim = QPropertyAnimation(self.settings_drawer, b'geometry', self)
        self.settings_drawer_anim.setDuration(180)
        self.settings_drawer_anim.setEasingCurve(QEasingCurve.OutCubic)

        def AE():
            if not self.settings_drawer_expanded:
                self.settings_drawer.hide()
            self._position_settings_drawer()

        on_drawer_anim_finished = AE
        self.settings_drawer_anim.finished.connect(on_drawer_anim_finished)
        nav_layout.addStretch()
        nav_layout.addWidget(self.settings_toggle_btn)
        self._position_settings_drawer()
        body_layout.addWidget(self.nav)
        body_layout.addWidget(self.stack, 1)

        # ---- Bottom bar: Start / Pause / Stop, license label, status, mode
        bottom_bar = QFrame()
        bottom_bar.setObjectName('BottomBar')
        bottom_bar.setFixedHeight(60)
        bottom_layout = QHBoxLayout(bottom_bar)
        bottom_layout.setContentsMargins(12, 6, 12, 6)
        self.start_btn = QPushButton('Start')
        self.pause_btn = QPushButton('I I')
        self.stop_btn = QPushButton('Stop')
        bottom_layout.addWidget(self.start_btn)
        bottom_layout.addWidget(self.pause_btn)
        bottom_layout.addWidget(self.stop_btn)
        self.key_status_label = QLabel('License: Free')
        self.key_status_label.setStyleSheet('color:#C9CCD6; padding-left:10px;')
        bottom_layout.addWidget(self.key_status_label)
        self.start_btn.setMinimumWidth(140)
        self.pause_btn.setMinimumWidth(60)
        self.stop_btn.setMinimumWidth(140)
        self.start_btn.setFixedHeight(44)
        self.pause_btn.setFixedHeight(44)
        self.stop_btn.setFixedHeight(44)
        self.start_btn.setObjectName('StartBtn')
        self.pause_btn.setObjectName('PauseBtn')
        self.stop_btn.setObjectName('StopBtn')
        bottom_layout.addStretch()
        self.status = QLabel('Idle')
        bottom_layout.addWidget(self.status)
        self.mode_label = QLabel('GLOBAL MODE')
        self.mode_label.setStyleSheet('color:#F4D37A; padding-left:12px;')
        bottom_layout.addWidget(self.mode_label)

        # ---- Bot worker thread + signal wiring
        self.worker = BotWorker()
        control.BotControl.worker = self.worker
        self.worker.status.connect(self.handle_worker_status)
        self.worker.status.connect(self.append_log)
        self.worker.config_changed.connect(self.handle_config_update)
        self.worker.prompt_continue.connect(self.show_continue_popup)
        self.stats_timer = QTimer(self)
        self.stats_timer.timeout.connect(self.refresh_statistics)
        self.stats_timer.start(1000)
        self.title_timer = QTimer(self)
        self.title_timer.timeout.connect(self._update_window_title)
        self.title_timer.start(1000)
        self.profile_refresh_timer = QTimer(self)
        self.profile_refresh_timer.timeout.connect(self.refresh_profile_timer)
        self.profile_refresh_timer.start(1000)
        self.start_btn.clicked.connect(self.start_bot)
        self.pause_btn.clicked.connect(lambda: self.guard_button(self.pause_btn, self.pause_bot))
        self.stop_btn.clicked.connect(lambda: self.guard_button(self.stop_btn, self.stop_bot))

        # ---- Restore emulator settings from GLOBAL config
        global_cfg = self.config_mgr.load()
        emulator_key = str(global_cfg.get('EMULATOR_SELECTION', startup.get_selected_emulator()) or 'bluestacks').strip().lower()
        emulator_ip = str(global_cfg.get('EMULATOR_IP', '127.0.0.1') or '127.0.0.1').strip()
        emulator_port = str(global_cfg.get('EMULATOR_PORT', startup.get_default_adb_port(emulator_key))
                            or startup.get_default_adb_port(emulator_key)).strip()
        for display, key in self.emulator_display_to_key.items():
            if key == emulator_key:
                self.emulator_select.blockSignals(True)
                self.emulator_select.setCurrentText(display)
                self.emulator_select.blockSignals(False)
                break
        self._on_emulator_changed(self.emulator_select.currentText(), apply_default_port=False)
        self.emulator_ip_input.blockSignals(True)
        self.emulator_ip_input.setText(emulator_ip)
        self.emulator_ip_input.blockSignals(False)
        adb.set_host(emulator_ip if emulator_ip else '127.0.0.1')
        self.adb_port_input.blockSignals(True)
        self.adb_port_input.setText(emulator_port)
        self.adb_port_input.blockSignals(False)
        if emulator_port.isdigit():
            self.adb_port = emulator_port
            adb.set_port(emulator_port)
        self._emulator_settings_ready = True
        self._save_emulator_global_settings()
        self.pause_btn.setProperty('locked', True)
        self.stop_btn.setProperty('locked', True)
        root_layout.addWidget(bottom_bar)

        # ---- Initial config load (GLOBAL)
        self.current_profile = None
        cfg = self.config_mgr.load()
        print('[INIT] Loaded GLOBAL config')
        self.block_gui_signals(True)
        locale = QLocale(QLocale.Language.English, QLocale.Country.UnitedStates)
        for spin in self.findChildren(QSpinBox):
            spin.setLocale(locale)
        self.apply_config_to_gui(cfg)
        self.block_gui_signals(False)
        self.update_mode_label()
        self.update_key_status_label()
        self.buttons[0].setChecked(True)
        self.stack.setCurrentWidget(self.pages[page_names[0]])
        self._restore_window_state_from_bot_config()
        self._window_state_ready = True
        QTimer.singleShot(0, self._position_settings_drawer)

    # ------------------------------------------------------------------ navigation / window events
    def switch_page(self, name):
        for btn in self.buttons:
            btn.setChecked(False)
        for btn in self.buttons:
            if btn.text() == name:
                btn.setChecked(True)
                break
        self.stack.setCurrentWidget(self.pages[name])

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_settings_drawer()
        self._schedule_window_state_save()

    def moveEvent(self, event):
        super().moveEvent(event)
        self._schedule_window_state_save()

    def update_key_status_label(self):
        # Basic edition: license label is hard-coded; no key validation in this module.
        self.key_status_label.setText('License: Pro (local build)')
        self.key_status_label.setStyleSheet('color:#C9CCD6; padding-left:10px;')

    # ------------------------------------------------------------------ settings -> config (per-profile or GLOBAL)
    def update_general(self):
        profile = self.current_profile
        cfg = self.config_mgr.load(profile)
        cfg['UPGRADE_WALLS'] = self.upgrade_walls.isChecked()
        cfg['ATTACK_MIN_GOLD'] = self.attack_gold.value()
        cfg['ATTACK_MIN_ELIXIR'] = self.attack_elixir.value()
        cfg['ATTACK_MIN_DARK'] = self.attack_dark.value()
        cfg['CLAN_GAMES'] = self.clan_games_enable.isChecked()
        cfg['CG_TROOP_CHALLENGES'] = self.cg_troop_challenges.isChecked()
        cfg['CLAN_CAPITAL'] = False                     # always forced off in Basic
        self.config_mgr.save(cfg, profile)

    def _sync_clan_games_options(self, _state=None):
        enabled = self.clan_games_enable.isChecked()
        self.cg_troop_challenges.setEnabled(enabled)
        if not enabled and self.cg_troop_challenges.isChecked():
            self.cg_troop_challenges.setChecked(False)

    def refresh_profile_styles(self):
        active = self.active_profile_label.text()
        for i in range(self.profile_list.count()):
            item = self.profile_list.item(i)
            name = item.data(Qt.UserRole)
            font = item.font()
            if name == active:
                item.setForeground(QColor('#F4D37A'))
                font = item.font()
                font.setBold(True)
                font.setPointSize(14)
            elif item.checkState() == Qt.Checked:
                item.setForeground(QColor('#E6E6E6'))
                font = item.font()
                font.setBold(False)
                font.setPointSize(12)
            else:
                item.setForeground(QColor('#6A6E7A'))
                font = item.font()
                font.setBold(False)
                font.setPointSize(12)
            item.setFont(font)

    def update_donations(self):
        profile = self.current_profile
        cfg = self.config_mgr.load(profile)
        cfg['REQUEST_DONATIONS'] = self.request_donations.isChecked()
        self.config_mgr.save(cfg, profile)

    _WAR_STRATEGIES = {'Electric Dragon/Loon': 'edragon', 'Dragon/Loon': 'dragon', 'Custom Script (CSV)': 'csv'}

    def _build_spec_group(self, title, specs):
        box = QGroupBox(title)
        grid = QGridLayout(box)
        for row, spec in enumerate(specs):
            key, label, kind = spec[0], spec[1], spec[2]
            if kind == 'bool':
                w = QCheckBox(label)
                w.stateChanged.connect(self.update_pro_features)
                grid.addWidget(w, row, 0, 1, 2)
            elif kind == 'text':
                w = QLineEdit()
                w.setPlaceholderText(label)
                w.editingFinished.connect(self.update_pro_features)
                grid.addWidget(QLabel(label.split(',')[0]), row, 0)
                grid.addWidget(w, row, 1)
            else:
                lo, hi, step = spec[4], spec[5], spec[6]
                w = QSpinBox()
                w.setRange(lo, hi)
                w.setSingleStep(step)
                if hi >= 1000000:
                    w.setGroupSeparatorShown(True)
                w.valueChanged.connect(self.update_pro_features)
                grid.addWidget(QLabel(label), row, 0)
                grid.addWidget(w, row, 1)
            self.pro_widgets[key] = (w, kind, spec[3])
        return box

    def _load_pro_features(self, c):
        for key, (w, kind, default) in getattr(self, 'pro_widgets', {}).items():
            w.blockSignals(True)          # a change signal here would save a half-loaded config
            if kind == 'bool':
                w.setChecked(bool(c.get(key, default)))
            elif kind == 'text':
                w.setText(str(c.get(key, default) or ''))
            else:
                w.setValue(int(c.get(key, default) or 0))
            w.blockSignals(False)
        self.war_enable.setChecked(bool(c.get('WAR_ATTACKS_ENABLED', False)))
        self.war_max.setValue(int(c.get('WAR_MAX_ATTACKS', 2) or 2))
        for display, key in self._WAR_STRATEGIES.items():
            if key == c.get('WAR_ATTACK_STRATEGY', 'edragon'):
                self.war_strategy.setCurrentText(display)
        if c.get('WAR_CSV_SCRIPT'):
            self.war_script.setCurrentText(c['WAR_CSV_SCRIPT'])
        self.war_script.setEnabled(self._WAR_STRATEGIES.get(self.war_strategy.currentText()) == 'csv')
        self.bb_enable.setChecked(bool(c.get('BB_ATTACKS_ENABLED', False)))
        self.bb_attacks.setValue(int(c.get('BB_ATTACKS_PER_VISIT', 3) or 3))
        self.bb_interval.setValue(int(c.get('BB_INTERVAL_MINUTES', 60) or 60))
        self.ranked_signup.setChecked(bool(c.get('RANKED_AUTO_SIGNUP', False)))
        self.bb_only.setChecked(bool(c.get('BB_ONLY', False)))

    def update_pro_features(self):
        profile = self.current_profile
        cfg = self.config_mgr.load(profile)
        cfg['WAR_ATTACKS_ENABLED'] = self.war_enable.isChecked()
        cfg['WAR_MAX_ATTACKS'] = self.war_max.value()
        cfg['WAR_ATTACK_STRATEGY'] = self._WAR_STRATEGIES[self.war_strategy.currentText()]
        if self.war_script.currentText():
            cfg['WAR_CSV_SCRIPT'] = self.war_script.currentText()
        self.war_script.setEnabled(cfg['WAR_ATTACK_STRATEGY'] == 'csv')
        cfg['BB_ATTACKS_ENABLED'] = self.bb_enable.isChecked()
        cfg['BB_ATTACKS_PER_VISIT'] = self.bb_attacks.value()
        cfg['BB_INTERVAL_MINUTES'] = self.bb_interval.value()
        cfg['RANKED_AUTO_SIGNUP'] = self.ranked_signup.isChecked()
        cfg['BB_ONLY'] = self.bb_only.isChecked()
        for key, (w, kind, _default) in getattr(self, 'pro_widgets', {}).items():
            cfg[key] = (w.isChecked() if kind == 'bool' else
                        w.text().strip() if kind == 'text' else w.value())
        self.config_mgr.save(cfg, profile)

    def update_attack_army(self):
        profile = self.current_profile
        cfg = self.config_mgr.load(profile)
        cfg['SELECTED_ARMY_SLOT'] = self.army_slot.currentIndex()
        strategy_name = self.strategy.currentText()
        if strategy_name in LOCKED_STRATEGIES:          # paywall: force back to a free strategy
            strategy_name = 'Electric Dragon/Loon'
            self.strategy.setCurrentText(strategy_name)
        cfg['SELECTED_ATTACK_STRATEGY'] = self.strategy_map[strategy_name]
        if self.csv_script.currentText():
            cfg['CSV_ATTACK_SCRIPT'] = self.csv_script.currentText()
        cfg['CSV_USE_REDLINE'] = self.csv_redline.isChecked()
        cfg['HERO_TAP_DELAY_ENABLED'] = self.hero_tap_delay_enabled.isChecked()
        cfg['HERO_TAP_DELAY_SECONDS'] = self.hero_tap_delay_seconds.value()
        cfg['AIR_TROOP_WIDTH_ENABLED'] = self.air_troop_width_enabled.isChecked()
        cfg['AIR_TROOP_WIDTH'] = self.air_troop_width.value()
        self.config_mgr.save(cfg, profile)

    def _on_switch_on_loot_full_changed(self):
        self.switch_minutes.setEnabled(not self.switch_on_loot_full.isChecked())
        self.update_multi()

    def update_multi(self):
        cfg = self.config_mgr.load()                   # multi-village settings always go to GLOBAL config
        cfg['MULTI_VILLAGE_ENABLED'] = self.multi_enabled.isChecked()
        cfg['VILLAGE_COUNT'] = min(FREE_MAX_VILLAGES, self.village_count.value())   # Pro cap (100)
        cfg['VILLAGE_SWITCH_MINUTES'] = self.switch_minutes.value()
        cfg['SWITCH_ON_LOOT_FULL'] = self.switch_on_loot_full.isChecked()
        if hasattr(self, 'switch_on_builders_busy'):
            cfg['SWITCH_ON_BUILDERS_BUSY'] = self.switch_on_builders_busy.isChecked()
        cfg['START_PROFILE'] = self.start_profile.currentText()
        self.config_mgr.save(cfg)
        if not self.multi_enabled.isChecked():
            self.current_profile = None
            cfg = self.config_mgr.load(None)
            self.apply_config_to_gui(cfg)
            try:
                self.deselect_btn.setEnabled(False)
            except Exception:
                pass
        self.update_mode_label()

    # ------------------------------------------------------------------ profiles
    def load_profile(self, name):
        profile = name
        if UI_DEBUG:
            print(f'[UI] Double clicked profile: {profile}')
            print(f'[UI] Previous current_profile: {self.current_profile}')
        self.current_profile = profile
        cfg = self.config_mgr.load(profile)
        self.block_gui_signals(True)
        self.apply_config_to_gui(cfg)
        self.status.setText(f'Loaded {profile} config')
        QTimer.singleShot(3000, lambda: self.status.setText('Idle'))
        self.active_profile_label.setText(profile)
        self.refresh_profile_styles()
        self.block_gui_signals(False)
        try:
            self.deselect_btn.setEnabled(True)
        except Exception:
            pass
        try:
            for i in range(self.profile_list.count()):
                item = self.profile_list.item(i)
                if item and item.data(Qt.UserRole) == profile:
                    self.profile_list.setCurrentItem(item)
                    self.profile_list.scrollToItem(item)
                    break
        except Exception:
            pass

    def deselect_active_profile(self):
        self.current_profile = None
        cfg = self.config_mgr.load()
        self.block_gui_signals(True)
        self.apply_config_to_gui(cfg)
        self.block_gui_signals(False)
        self.active_profile_label.setText('GLOBAL')
        try:
            self.deselect_btn.setEnabled(False)
        except Exception:
            pass
        self.refresh_profile_styles()
        self.profile_list.clearSelection()
        try:
            control.BotControl.emit_config(cfg, None)
        except Exception:
            pass
        self.status.setText('Cleared active profile')
        QTimer.singleShot(3000, lambda: self.status.setText('Idle'))

    def delete_all_profiles(self):
        # FILE DELETION: user-confirmed. Removes every sub-directory of <writable>/profiles and the
        # files profiles/active_profiles.json and profiles/order.txt.
        reply = QMessageBox.warning(self, 'Delete All Profiles',
                                    'This will delete all profile folders and the active config. Continue?',
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        profiles_dir = str(resolve_writable_path('profiles'))
        if os.path.isdir(profiles_dir):
            for entry in os.listdir(profiles_dir):
                full = os.path.join(profiles_dir, entry)
                if os.path.isdir(full):
                    shutil.rmtree(full, ignore_errors=True)
            for fname in ('active_profiles.json', 'order.txt'):
                fpath = os.path.join(profiles_dir, fname)
                if os.path.exists(fpath):
                    try:
                        os.remove(fpath)
                    except OSError:
                        pass
        self.profile_list.clear()
        self.start_profile.blockSignals(True)
        self.start_profile.clear()
        self.start_profile.blockSignals(False)
        self.current_profile = None
        self.deselect_active_profile()
        self.refresh_profile_styles()
        self.refresh_start_profile_dropdown()

    def _open_profile_match_threshold_popup(self, profile_name, global_pos=None):
        pos = global_pos
        if not profile_name:
            return
        cfg = self.config_mgr.load(profile_name)
        dialog = QDialog(self, Qt.Tool | Qt.FramelessWindowHint)
        dialog.setObjectName('ProfileThresholdPopup')
        arrow_up = self._asset_url('arrow_up.svg')
        arrow_down = self._asset_url('arrow_down.svg')
        dialog.setStyleSheet(f'QDialog#ProfileThresholdPopup {{ background-color: #171A21; border: 2px solid #2F3546; border-radius: 8px; }}QLabel {{ color: #E2E8F0; background: transparent; }}QDoubleSpinBox {{ color: #E6E6E6; background-color: #1B1F2A; border: 1px solid #2A2F3B; border-radius: 6px; padding: 4px 4px 4px 8px; }}QDoubleSpinBox::up-button {{ width: 18px; subcontrol-origin: border; subcontrol-position: top right; border-left: 1px solid #2A2F3B; }}QDoubleSpinBox::up-arrow {{ width: 10px; height: 10px; image: url({arrow_up}); }}QDoubleSpinBox::down-button {{ width: 18px; subcontrol-origin: border; subcontrol-position: bottom right; border-left: 1px solid #2A2F3B; }}QDoubleSpinBox::down-arrow {{ width: 10px; height: 10px; image: url({arrow_down}); }}QPushButton {{ background-color: #242834; color: #E6E6E6; border: 1px solid #181B24; border-radius: 6px; padding: 6px 12px; }}QPushButton:hover {{ background-color: #2D3240; }}')
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)
        title = QLabel('Profile Settings')
        title.setFont(QFont(self.font_ui_bold, 10))
        layout.addWidget(title)
        name_label = QLabel('Profile Name')
        layout.addWidget(name_label)
        name_edit = QLineEdit(dialog)
        name_edit.setText(profile_name)
        layout.addWidget(name_edit)
        thr_label = QLabel('Match Threshold')
        layout.addWidget(thr_label)
        spin = QDoubleSpinBox(dialog)
        spin.setDecimals(2)
        spin.setRange(0.5, 1.0)
        spin.setSingleStep(0.01)
        spin.setValue(float(cfg.get('PROFILE_MATCH_THRESHOLD', 0.9) or 0.9))
        layout.addWidget(spin)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton('Cancel')
        save_btn = QPushButton('Save')
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)
        cancel_btn.clicked.connect(dialog.reject)

        def Q():
            target = profile_name
            new_name = (name_edit.text() or '').strip()
            if new_name and new_name != profile_name:
                from profiles.profile_manager import ProfileManager
                pm = ProfileManager(None)
                ok, msg, renamed = pm.rename_profile(profile_name, new_name)
                if not ok:
                    QMessageBox.warning(self, 'Rename Failed', msg)
                    return
                target = renamed
                if self.current_profile == profile_name:
                    self.current_profile = target
                if self.active_profile_label.text() == profile_name:
                    self.active_profile_label.setText(target)
                self.refresh_profile_list()
                self.refresh_profile_styles()
            pcfg = self.config_mgr.load(target)
            pcfg['PROFILE_MATCH_THRESHOLD'] = round(spin.value(), 2)
            self.config_mgr.save(pcfg, target)
            self._update_window_title()
            dialog.accept()

        on_save = Q
        save_btn.clicked.connect(on_save)
        spin.setFocusPolicy(Qt.StrongFocus)
        dialog.adjustSize()
        if pos is not None:
            dialog.move(pos.x() - dialog.width() + 12, pos.y() + 8)
        name_edit.setFocus()
        name_edit.selectAll()
        dialog.exec()
        # RECON: verbatim -- the original sets this (apparently copy-pasted) status text after the popup closes.
        self.status.setText('Deleted all profiles')
        QTimer.singleShot(3000, lambda: self.status.setText('Idle'))

    def save_profile_order(self):
        import json
        path = str(resolve_writable_path('profiles/active_profiles.json'))
        data = {'profiles': {}}
        for i in range(self.profile_list.count()):
            item = self.profile_list.item(i)
            data['profiles'][item.data(Qt.UserRole)] = item.checkState() == Qt.Checked
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
        self.refresh_start_profile_dropdown()
        self.refresh_profile_styles()

    def refresh_profile_list(self):
        from profiles.profile_manager import ProfileManager
        import json
        cfg = self.config_mgr.load()
        pm = ProfileManager(None)
        profiles = pm.list_profiles()
        active_path = str(resolve_writable_path('profiles/active_profiles.json'))
        enabled_map = {}
        if os.path.exists(active_path):
            with open(active_path, 'r') as f:
                enabled_map = json.load(f).get('profiles', {})
        loot_status = getattr(main, 'profile_loot_status', {})
        self.profile_list.blockSignals(True)
        self.start_profile.blockSignals(True)
        self.profile_list.clear()
        self.start_profile.clear()
        for idx, pname in enumerate(profiles, start=1):
            loot_full = loot_status.get(pname, False)
            suffix = ' 🔋' if loot_full else ''
            item = QListWidgetItem(f'{idx}. {pname}{suffix}')
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable | Qt.ItemIsDragEnabled)
            item.setCheckState(Qt.Checked if enabled_map.get(pname, True) else Qt.Unchecked)
            item.setData(Qt.UserRole, pname)
            item.setSizeHint(QSize(0, 36))
            self.profile_list.addItem(item)
            if item.checkState() == Qt.Checked:
                self.start_profile.addItem(pname)
        start = cfg.get('START_PROFILE')
        if start in profiles:
            self.start_profile.setCurrentText(start)
        self.profile_list.blockSignals(False)
        self.start_profile.blockSignals(False)
        try:
            current = self.current_profile
        except Exception:
            current = None
        if current:
            for i in range(self.profile_list.count()):
                item = self.profile_list.item(i)
                if item and item.data(Qt.UserRole) == current:
                    self.profile_list.setCurrentItem(item)
                    break
        self.refresh_profile_styles()
        self.refresh_start_profile_dropdown()

    def refresh_start_profile_dropdown(self):
        cfg = self.config_mgr.load()
        self.start_profile.blockSignals(True)
        self.start_profile.clear()
        enabled = []
        for i in range(self.profile_list.count()):
            item = self.profile_list.item(i)
            if item.checkState() == Qt.Checked:
                enabled.append(item.data(Qt.UserRole))
                self.start_profile.addItem(item.data(Qt.UserRole))
        start = cfg.get('START_PROFILE')
        if start in enabled:
            self.start_profile.setCurrentText(start)
        self.start_profile.blockSignals(False)

    # ------------------------------------------------------------------ config -> GUI
    def apply_config_to_gui(self, cfg):
        c = cfg
        self.request_donations.setChecked(c.get('REQUEST_DONATIONS', False))
        self.multi_enabled.setChecked(c.get('MULTI_VILLAGE_ENABLED', False))
        self.upgrade_walls.setChecked(c.get('UPGRADE_WALLS', False))
        self.attack_gold.setValue(c.get('ATTACK_MIN_GOLD', 0))
        self.attack_elixir.setValue(c.get('ATTACK_MIN_ELIXIR', 0))
        self.attack_dark.setValue(c.get('ATTACK_MIN_DARK', 0))
        try:
            self.clan_games_enable.setChecked(c.get('CLAN_GAMES', False))
        except Exception:
            pass
        try:
            self.cg_troop_challenges.setChecked(c.get('CG_TROOP_CHALLENGES', False))
            self._sync_clan_games_options()
        except Exception:
            pass
        slot = int(c.get('SELECTED_ARMY_SLOT', 0) or 0)
        slot = max(0, min(8, slot))
        self.army_slot.setCurrentIndex(slot)
        self.hero_tap_delay_enabled.setChecked(c.get('HERO_TAP_DELAY_ENABLED', False))
        hero_delay = int(c.get('HERO_TAP_DELAY_SECONDS', 1) or 1)
        hero_delay = max(1, min(15, hero_delay))
        self.hero_tap_delay_seconds.setValue(hero_delay)
        self.hero_tap_delay_seconds.setEnabled(self.hero_tap_delay_enabled.isChecked())
        self.air_troop_width_enabled.setChecked(c.get('AIR_TROOP_WIDTH_ENABLED', False))
        air_width = int(c.get('AIR_TROOP_WIDTH', 300) or 300)
        air_width = max(50, min(500, air_width))
        self.air_troop_width.setValue(air_width)
        self.air_troop_width.setEnabled(self.air_troop_width_enabled.isChecked())
        for display, key in self.strategy_map.items():
            if key == c.get('SELECTED_ATTACK_STRATEGY'):
                self.strategy.setCurrentText(display)
                break
        if self.strategy.currentText() in LOCKED_STRATEGIES:   # paywall: locked strategy in config -> free default
            self.strategy.setCurrentText('Electric Dragon/Loon')
        self.strategy_info.setText(self.strategy_help.get(self.strategy.currentText(), ''))
        if c.get('CSV_ATTACK_SCRIPT'):
            self.csv_script.setCurrentText(c['CSV_ATTACK_SCRIPT'])
        self.csv_script.setEnabled(self.strategy_map.get(self.strategy.currentText()) == 'csv')
        self.csv_redline.setChecked(bool(c.get('CSV_USE_REDLINE', True)))
        self.csv_redline.setEnabled(self.csv_script.isEnabled())
        self._load_pro_features(c)
        self.update_multi_ui()

    def update_mode_label(self):
        if self.multi_enabled.isChecked():
            self.mode_label.setText('MULTI VILLAGE')
        else:
            self.mode_label.setText('GLOBAL MODE')

    def update_multi_ui(self):
        enabled = self.multi_enabled.isChecked()
        self.settings_box.setEnabled(enabled)
        self.active_box.setEnabled(enabled)
        self.right_box.setEnabled(enabled)
        if enabled:
            self.switch_minutes.setEnabled(not self.switch_on_loot_full.isChecked())

    def refresh_statistics(self):
        stats = getattr(main, 'GLOBAL_STATS', None)
        if not stats:
            return
        self.stats_runtime.setText(stats.elapsed_hhmmss())
        self.stats_attacks.setText(str(stats.total_attacks))
        self.stats_gold.setText(f'{stats.gold_gained:,}')
        self.stats_gold_hr.setText(f'{stats._cached_gold_hr:,} / hr')
        self.stats_elixir.setText(f'{stats.elixir_gained:,}')
        self.stats_elixir_hr.setText(f'{stats._cached_elixir_hr:,} / hr')
        self.stats_dark.setText(f'{stats.dark_gained:,}')
        self.stats_dark_hr.setText(f'{stats._cached_dark_hr:,} / hr')
        self.stats_0.setText(str(stats.stars_0))
        self.stats_1.setText(str(stats.stars_1))
        self.stats_2.setText(str(stats.stars_2))
        self.stats_3.setText(str(stats.stars_3))
        self.stats_walls.setText(str(stats.walls_upgraded))

    def append_log(self, text):
        line = text.strip()
        if not line:
            return
        ts = datetime.datetime.now().strftime('%H:%M:%S')
        tag = 'LOG'
        msg = line
        m = re.match('^\\[(\\d{2}:\\d{2}:\\d{2})\\]\\s*(.*)$', msg)
        if m:
            ts = m.group(1)
            msg = m.group(2).strip()
        m2 = re.match('^\\[([^\\]]+)\\]\\s*(.*)$', msg)
        if m2:
            tag = m2.group(1).strip()
            msg = m2.group(2).strip()
        formatted = f'{ts:<8} | {tag:<10} | {msg}'
        self.log_view.append(formatted)
        self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())

    # ------------------------------------------------------------------ start / pause / stop
    def start_bot(self):
        if not self.worker.isRunning():
            self.worker.start()                 # BotWorker is a QThread (see ui/bot_worker)
        else:
            self.worker.resume()
        self.set_controls_enabled(False)
        self.profile_list.setEnabled(False)
        self.start_btn.setEnabled(False)
        self.adb_port_input.setEnabled(False)
        self.emulator_ip_input.setEnabled(False)
        self.emulator_select.setEnabled(False)
        self.delete_profiles_btn.setEnabled(False)
        self.pause_btn.setProperty('locked', False)
        self.stop_btn.setProperty('locked', False)
        self.pause_btn.style().polish(self.pause_btn)
        self.stop_btn.style().polish(self.stop_btn)

    def pause_bot(self):
        if control.BotControl.paused:
            self.worker.resume()
            self.pause_btn.setText('I I')
            self.delete_profiles_btn.setEnabled(False)
        else:
            self.worker.pause()
            self.pause_btn.setText('▶')
            self.delete_profiles_btn.setEnabled(False)

    def stop_bot(self):
        self.worker.stop()
        self.set_controls_enabled(True)
        self.profile_list.setEnabled(True)
        self.start_btn.setEnabled(True)
        self.adb_port_input.setEnabled(True)
        self.emulator_ip_input.setEnabled(True)
        self.emulator_select.setEnabled(True)
        self.delete_profiles_btn.setEnabled(True)
        self.pause_btn.setProperty('locked', True)
        self.stop_btn.setProperty('locked', True)
        self.pause_btn.style().polish(self.pause_btn)
        self.stop_btn.style().polish(self.stop_btn)
        self.profile_timer_label.setText('--:--')
        self.refresh_profile_list()
        self.status.setText('Stopped')

    def handle_worker_status(self, status):
        s = status
        self.status.setText(s)
        if s == 'Stopped':
            self.profile_timer_label.setText('--:--')
            self.profile_timer_label.setStyleSheet('color: #22C55E;')
            self.refresh_profile_list()

    def guard_button(self, button, func):
        if button.property('locked'):
            return
        func()

    # ------------------------------------------------------------------ popups
    def show_continue_popup(self, title, message):
        msg = message
        t = title
        if t == 'Profile Calibration':
            dialog = QDialog(self)
            dialog.setWindowTitle(t)
            dialog.setModal(True)
            dialog.setFixedWidth(260)
            dialog.setFixedHeight(210)
            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(18, 18, 18, 18)
            layout.setSpacing(12)
            msg_label = QLabel(msg)
            msg_label.setWordWrap(True)
            layout.addWidget(msg_label)
            help_link = QLabel('<a href="#">Show calibration help</a>')
            help_link.setTextFormat(Qt.RichText)
            help_link.setTextInteractionFlags(Qt.TextBrowserInteraction)
            help_link.setOpenExternalLinks(False)
            layout.addWidget(help_link)
            help_panel = QWidget(dialog)
            help_panel.setVisible(False)
            help_layout = QVBoxLayout(help_panel)
            help_layout.setContentsMargins(0, 0, 0, 0)
            help_layout.setSpacing(10)
            help_text = QLabel('When calibrating, ensure the full profile card is visible as highlighted below.')
            help_text.setWordWrap(True)
            help_layout.addWidget(help_text)
            guide = QLabel()
            guide.setAlignment(Qt.AlignCenter)
            pix = QPixmap(self._asset_path('profile_guide.png'))
            if not pix.isNull():
                guide.setPixmap(pix.scaledToWidth(210, Qt.SmoothTransformation))
            else:
                guide.setText('Profile guide image could not be loaded.')
            help_layout.addWidget(guide)
            layout.addWidget(help_panel)
            continue_btn = QPushButton('Continue')
            continue_btn.setStyleSheet('text-align: center;')
            continue_btn.clicked.connect(dialog.accept)
            layout.addWidget(continue_btn)

            def P(_link=None):
                show = not help_panel.isVisible()
                help_panel.setVisible(show)
                help_link.setText('<a href="#">Hide calibration help</a>' if show
                                  else '<a href="#">Show calibration help</a>')
                if show:
                    dialog.setFixedHeight(max(210, dialog.sizeHint().height()))
                else:
                    dialog.setFixedHeight(210)

            toggle_help = P
            help_link.linkActivated.connect(toggle_help)
            dialog.exec()
            control.BotControl.continue_clicked()
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle(t)
        box.setText(msg)
        box.setStandardButtons(QMessageBox.Ok)
        ok_btn = box.button(QMessageBox.Ok)
        if ok_btn:
            ok_btn.setText('Continue')
        box.exec()
        control.BotControl.continue_clicked()

    def handle_enter(self):
        control.BotControl.enter_pressed = True

    def handle_config_update(self, payload):
        p = payload
        cfg = p.get('cfg')
        profile = p.get('profile')
        if not cfg:
            return
        self.current_profile = profile
        self.refresh_profile_list()
        self.apply_config_to_gui(cfg)
        if profile:
            self.active_profile_label.setText(profile)
        else:
            self.active_profile_label.setText('GLOBAL')
        self.refresh_profile_styles()

    def refresh_profile_timer(self):
        try:
            if not control.BotControl.running:
                self.profile_timer_label.setText('--:--')
                self.profile_timer_label.setStyleSheet('color: #22C55E;')
                return
            if main.active_config.get('MULTI_VILLAGE_ENABLED', False) and main.active_profiles and main.last_profile_switch:
                if main.active_config.get('SWITCH_ON_LOOT_FULL', False):
                    self.profile_timer_label.setText('LOOT')
                    self.profile_timer_label.setStyleSheet('color: #A78BFA;')
                    return
                now = time.time()
                elapsed = int(now - main.last_profile_switch)
                minutes = int(self.switch_minutes.value())
                total = minutes * 60
                remaining = max(0, total - elapsed)
                mm = remaining // 60
                ss = remaining % 60
                self.profile_timer_label.setText(f'{mm:02d}:{ss:02d}')
                if remaining < 30 and remaining > 0:
                    self.profile_timer_label.setStyleSheet('color: #FACC15;')
                elif remaining == 0:
                    self.profile_timer_label.setStyleSheet('color: #EF4444;')
                else:
                    self.profile_timer_label.setStyleSheet('color: #22C55E;')
            else:
                self.profile_timer_label.setText('--:--')
                self.profile_timer_label.setStyleSheet('color: #22C55E;')
        except Exception:
            self.profile_timer_label.setText('--:--')

    def eventFilter(self, obj, event):
        ev = event
        try:
            lst = getattr(self, 'profile_list', None)
            if lst is None:
                return False
            if obj in (lst, lst.viewport()):
                if ev.type() == QEvent.ToolTip:
                    pos = ev.pos()
                    item = lst.itemAt(pos)
                    if item:
                        rect = lst.visualItemRect(item)
                        edit_rect, load_rect = ProfileListDelegate.tool_rects(rect)
                        if edit_rect.contains(pos):
                            QToolTip.showText(ev.globalPos(), 'Click to edit profile name and match threshold', lst)
                            return True
                        if load_rect.contains(pos):
                            QToolTip.showText(ev.globalPos(), 'Click to edit profile', lst)
                            return True
                    QToolTip.hideText()
                    return False
                elif ev.type() == QEvent.MouseButtonRelease:
                    pos = ev.position().toPoint()
                    item = lst.itemAt(pos)
                    if item:
                        rect = lst.visualItemRect(item)
                        edit_rect, load_rect = ProfileListDelegate.tool_rects(rect)
                        if edit_rect.contains(pos):
                            name = item.data(Qt.UserRole)
                            if name:
                                self._open_profile_match_threshold_popup(name, ev.globalPosition().toPoint())
                                return True
                        if load_rect.contains(pos):
                            name = item.data(Qt.UserRole)
                            if name:
                                self.load_profile(name)
                                return True
                    if not item:
                        lst.clearSelection()
                    return False
        except RuntimeError:
            return False
        return False

    def mousePressEvent(self, event):
        super().mousePressEvent(event)

    def set_controls_enabled(self, enabled):
        for name, page in self.pages.items():
            if name in ('Log', 'Statistics'):
                page.setEnabled(True)
                continue
            page.setEnabled(enabled)

    def block_gui_signals(self, block):
        widgets = [self.upgrade_walls, self.attack_gold, self.attack_elixir, self.attack_dark, self.army_slot,
                   self.strategy, getattr(self, 'csv_script', None), getattr(self, 'csv_redline', None),
                   getattr(self, 'hero_tap_delay_enabled', None),
                   getattr(self, 'hero_tap_delay_seconds', None), getattr(self, 'air_troop_width_enabled', None),
                   getattr(self, 'air_troop_width', None), self.request_donations,
                   getattr(self, 'clan_games_enable', None), getattr(self, 'cg_troop_challenges', None),
                   getattr(self, 'war_enable', None), getattr(self, 'war_max', None),
                   getattr(self, 'war_strategy', None), getattr(self, 'war_script', None),
                   getattr(self, 'bb_enable', None), getattr(self, 'bb_attacks', None),
                   getattr(self, 'bb_interval', None), getattr(self, 'ranked_signup', None),
                   getattr(self, 'bb_only', None)]
        widgets += [w for w, _kind, _default in getattr(self, 'pro_widgets', {}).values()]
        for w in widgets:
            if w:
                w.blockSignals(block)

    def closeEvent(self, event):
        try:
            if self.worker and self.worker.isRunning():
                self.worker.stop()
        except Exception:
            pass
        self._save_window_state_to_bot_config()
        super().closeEvent(event)
