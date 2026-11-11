# crb/theme.py - Clash Rekt Bot brand: colour schemes, fonts, the application style sheet.
#
# Three schemes: "Rekt Night" (default dark), "Rekt Day" (light) and "High Contrast" (accessibility:
# pure black/white, thick focus rings). Text size is a user setting (90-160%). Every interactive
# widget gets a visible keyboard focus ring; colour is never the only signal (status also has text).
import os

from PySide6.QtGui import QFont, QFontDatabase, QColor, QPalette

APP_NAME = 'Clash Rekt Bot'
APP_SHORT = 'CRB'
APP_VERSION = '2.0.0'

SCHEMES = {
    'night': {
        'name': 'Rekt Night',
        'bg': '#0B0E1A', 'surface': '#131830', 'surface2': '#1B2142', 'surface3': '#252C55',
        'border': '#2C3463', 'text': '#ECEFFA', 'muted': '#A3ABCF', 'faint': '#6E77A3',
        'primary': '#FF3B5C', 'primary_hover': '#FF6079', 'primary_text': '#FFFFFF',
        'gold': '#FFB938', 'success': '#22D39A', 'warning': '#FFB938', 'danger': '#FF3B5C',
        'info': '#4CC2FF', 'focus': '#FFD166', 'track_off': '#3A4273', 'knob': '#FFFFFF',
        'log_bg': '#080A14',
    },
    'day': {
        'name': 'Rekt Day',
        'bg': '#F3F5FB', 'surface': '#FFFFFF', 'surface2': '#EEF1F9', 'surface3': '#E1E6F3',
        'border': '#CDD3E6', 'text': '#141831', 'muted': '#4C5478', 'faint': '#7A82A6',
        'primary': '#D81E45', 'primary_hover': '#EE3158', 'primary_text': '#FFFFFF',
        'gold': '#B97800', 'success': '#0E9F6E', 'warning': '#B97800', 'danger': '#D81E45',
        'info': '#0B79C2', 'focus': '#1F5BFF', 'track_off': '#B9C0D8', 'knob': '#FFFFFF',
        'log_bg': '#FFFFFF',
    },
    'contrast': {
        'name': 'High Contrast',
        'bg': '#000000', 'surface': '#000000', 'surface2': '#0A0A0A', 'surface3': '#1A1A1A',
        'border': '#FFFFFF', 'text': '#FFFFFF', 'muted': '#FFFFFF', 'faint': '#D0D0D0',
        'primary': '#FFE500', 'primary_hover': '#FFF27A', 'primary_text': '#000000',
        'gold': '#FFE500', 'success': '#3DFF8B', 'warning': '#FFE500', 'danger': '#FF5C5C',
        'info': '#5CD6FF', 'focus': '#00E5FF', 'track_off': '#5A5A5A', 'knob': '#FFFFFF',
        'log_bg': '#000000',
    },
}

_FONTS = {'display': 'Bangers', 'ui': 'Inter'}


def load_fonts(assets_dir):
    """Register the bundled fonts (Bangers for the wordmark/titles, Inter for the UI)."""
    for name in ('Bangers-Regular.ttf', 'Inter-Regular.ttf', 'Inter-Bold.ttf'):
        path = os.path.join(assets_dir, name)
        if os.path.exists(path):
            fid = QFontDatabase.addApplicationFont(path)
            fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
            if fams and name.startswith('Bangers'):
                _FONTS['display'] = fams[0]
            elif fams and name.startswith('Inter'):
                _FONTS['ui'] = fams[0]


def display_family():
    return _FONTS['display']


def ui_family():
    return _FONTS['ui']


def mono_family():
    """A monospace font that exists on this machine, else the UI font. A missing family made Qt fall
    back to the first app font (Bangers), which turned the log into comic lettering (11 Nov)."""
    available = set(QFontDatabase.families())
    for fam in ('Consolas', 'Menlo', 'SF Mono', 'DejaVu Sans Mono', 'Liberation Mono', 'Courier New'):
        if fam in available:
            return f"'{fam}'"
    return f"'{ui_family()}'"


def colors(scheme):
    return SCHEMES.get(scheme, SCHEMES['night'])


def apply_palette(app, scheme):
    c = colors(scheme)
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(c['bg']))
    pal.setColor(QPalette.WindowText, QColor(c['text']))
    pal.setColor(QPalette.Base, QColor(c['surface2']))
    pal.setColor(QPalette.AlternateBase, QColor(c['surface3']))
    pal.setColor(QPalette.Text, QColor(c['text']))
    pal.setColor(QPalette.Button, QColor(c['surface2']))
    pal.setColor(QPalette.ButtonText, QColor(c['text']))
    pal.setColor(QPalette.Highlight, QColor(c['primary']))
    pal.setColor(QPalette.HighlightedText, QColor(c['primary_text']))
    pal.setColor(QPalette.ToolTipBase, QColor(c['surface3']))
    pal.setColor(QPalette.ToolTipText, QColor(c['text']))
    pal.setColor(QPalette.PlaceholderText, QColor(c['faint']))
    app.setPalette(pal)


def base_font(scale=1.0):
    f = QFont(ui_family())
    f.setPointSizeF(10.5 * scale)
    return f


def stylesheet(scheme, scale=1.0):
    c = colors(scheme)
    focus_w = 3 if scheme == 'contrast' else 2
    pt = lambda v: f'{v * scale:.1f}pt'          # noqa: E731
    return f"""
* {{ font-family: '{ui_family()}'; color: {c['text']}; }}
QMainWindow, QWidget#Root {{ background: {c['bg']}; }}
QWidget#Sidebar {{ background: {c['surface']}; border-right: 1px solid {c['border']}; }}
QWidget#Content, QScrollArea, QScrollArea > QWidget > QWidget#Page {{ background: {c['bg']}; border: none; }}
QLabel {{ background: transparent; }}
QLabel#Wordmark {{ font-family: '{display_family()}'; font-size: {pt(25)}; letter-spacing: 1px; }}
QLabel#PageTitle {{ font-family: '{display_family()}'; font-size: {pt(26)}; letter-spacing: 1px; }}
QLabel#PageSubtitle {{ color: {c['muted']}; font-size: {pt(10.5)}; }}
QLabel#CardTitle {{ font-size: {pt(12.5)}; font-weight: 700; }}
QLabel#CardHint, QLabel#Help {{ color: {c['muted']}; font-size: {pt(9.5)}; }}
QLabel#RowTitle {{ font-size: {pt(10.5)}; font-weight: 600; }}
QLabel#StatValue {{ font-size: {pt(18)}; font-weight: 700; }}
QLabel#StatLabel {{ color: {c['muted']}; font-size: {pt(9)}; text-transform: uppercase; letter-spacing: 1px; }}
QLabel#Dim {{ color: {c['faint']}; }}
QFrame#Card {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 14px; }}
QFrame#Tile {{ background: {c['surface2']}; border: 1px solid {c['border']}; border-radius: 12px; }}
QFrame#Divider {{ background: {c['border']}; max-height: 1px; min-height: 1px; border: none; }}

QPushButton {{
    background: {c['surface2']}; border: 1px solid {c['border']}; border-radius: 10px;
    padding: 8px 16px; font-size: {pt(10.5)}; font-weight: 600; min-height: 22px;
}}
QPushButton:hover {{ background: {c['surface3']}; }}
QPushButton:pressed {{ background: {c['border']}; }}
QPushButton:disabled {{ color: {c['faint']}; background: {c['surface']}; }}
QPushButton:focus {{ border: {focus_w}px solid {c['focus']}; }}
QPushButton#Primary {{ background: {c['primary']}; color: {c['primary_text']}; border: 1px solid {c['primary']}; }}
QPushButton#Primary:hover {{ background: {c['primary_hover']}; }}
QPushButton#Primary:disabled {{ background: {c['surface3']}; color: {c['faint']}; border-color: {c['border']}; }}
QPushButton#Big {{ font-size: {pt(14)}; font-weight: 800; padding: 14px 18px; border-radius: 14px; }}
QPushButton#Danger {{ color: {c['danger']}; border-color: {c['danger']}; }}
QPushButton#Ghost {{ background: transparent; border: 1px solid transparent; }}
QPushButton#Ghost:hover {{ background: {c['surface2']}; }}

QPushButton#Nav {{
    text-align: left; padding: 10px 14px; border-radius: 10px; border: 1px solid transparent;
    background: transparent; font-size: {pt(11)}; font-weight: 600; color: {c['muted']};
}}
QPushButton#Nav:hover {{ background: {c['surface2']}; color: {c['text']}; }}
QPushButton#Nav:checked {{ background: {c['surface3']}; color: {c['text']}; border-left: 4px solid {c['primary']}; }}
QPushButton#Nav:focus {{ border: {focus_w}px solid {c['focus']}; }}

QPushButton#Segment {{ border-radius: 9px; padding: 7px 12px; background: {c['surface2']}; color: {c['muted']}; }}
QPushButton#Segment:checked {{ background: {c['primary']}; color: {c['primary_text']}; border-color: {c['primary']}; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit {{
    background: {c['surface2']}; border: 1px solid {c['border']}; border-radius: 9px;
    padding: 6px 10px; font-size: {pt(10.5)}; selection-background-color: {c['primary']};
    selection-color: {c['primary_text']}; min-height: 22px;
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{
    border: {focus_w}px solid {c['focus']};
}}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{ color: {c['faint']}; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox QAbstractItemView {{
    background: {c['surface2']}; border: 1px solid {c['border']}; selection-background-color: {c['primary']};
    selection-color: {c['primary_text']}; padding: 4px; outline: none;
}}
QPlainTextEdit#Log {{ background: {c['log_bg']}; font-family: {mono_family()}; font-size: {pt(9.5)}; }}
QListWidget {{ background: {c['surface2']}; border: 1px solid {c['border']}; border-radius: 10px; padding: 4px; outline: none; }}
QListWidget::item {{ padding: 8px; border-radius: 8px; }}
QListWidget::item:selected {{ background: {c['surface3']}; color: {c['text']}; }}
QListWidget:focus {{ border: {focus_w}px solid {c['focus']}; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 2px solid {c['border']}; background: {c['surface2']}; }}
QCheckBox::indicator:checked {{ background: {c['primary']}; border-color: {c['primary']}; }}
QCheckBox:focus {{ color: {c['focus']}; }}
QSlider::groove:horizontal {{ height: 6px; background: {c['track_off']}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {c['primary']}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {c['knob']}; width: 18px; height: 18px; margin: -7px 0; border-radius: 9px; border: 2px solid {c['primary']}; }}
QSlider:focus {{ border: none; }}
QSlider::handle:horizontal:focus {{ border: {focus_w + 1}px solid {c['focus']}; }}
QProgressBar {{ background: {c['surface2']}; border: 1px solid {c['border']}; border-radius: 8px; text-align: center; height: 16px; }}
QProgressBar::chunk {{ background: {c['primary']}; border-radius: 7px; }}
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {c['surface3']}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {c['border']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {c['surface3']}; border-radius: 5px; min-width: 30px; }}
QToolTip {{ background: {c['surface3']}; color: {c['text']}; border: 1px solid {c['border']}; padding: 6px 8px; border-radius: 6px; }}
QMessageBox, QDialog {{ background: {c['surface']}; }}
QTabBar::tab {{ background: transparent; padding: 8px 14px; color: {c['muted']}; border-bottom: 3px solid transparent; }}
QTabBar::tab:selected {{ color: {c['text']}; border-bottom: 3px solid {c['primary']}; }}
"""
