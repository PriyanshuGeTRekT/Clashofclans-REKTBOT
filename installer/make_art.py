"""Render the installer's wizard images (BMP) from the logo, in the Rekt Night colours."""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "source"))
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QImage, QLinearGradient, QPainter
from PySide6.QtSvg import QSvgRenderer

app = QGuiApplication([])
fid = QFontDatabase.addApplicationFont(os.path.join(ROOT, "runtime", "assets", "Bangers-Regular.ttf"))
display = QFontDatabase.applicationFontFamilies(fid)[0]
logo = QSvgRenderer(os.path.join(ROOT, "source", "crb", "assets", "logo.svg"))


def big(w, h, path):
    img = QImage(w, h, QImage.Format_RGB32)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    g = QLinearGradient(0, 0, 0, h)
    g.setColorAt(0, QColor("#1B2142"))
    g.setColorAt(1, QColor("#0B0E1A"))
    p.fillRect(0, 0, w, h, g)
    s = w * 0.72
    logo.render(p, QRectF((w - s) / 2, h * 0.12, s, s))
    f = QFont(display)
    f.setPixelSize(int(w * 0.2))
    p.setFont(f)
    y = h * 0.12 + s + w * 0.08
    for text, color in (("CLASH", "#ECEFFA"), ("REKT", "#FF3B5C"), ("BOT", "#FFB938")):
        p.setPen(QColor(color))
        p.drawText(QRectF(0, y, w, w * 0.24), Qt.AlignHCenter | Qt.AlignTop, text)
        y += w * 0.21
    p.end()
    img.save(path, "BMP")


def small(n, path):
    img = QImage(n, n, QImage.Format_RGB32)
    img.fill(QColor("#FFFFFF"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    logo.render(p, QRectF(n * 0.04, n * 0.04, n * 0.92, n * 0.92))
    p.end()
    img.save(path, "BMP")


big(164, 314, os.path.join(HERE, "wizard_100.bmp"))
big(328, 628, os.path.join(HERE, "wizard_200.bmp"))
small(58, os.path.join(HERE, "wizard_small_100.bmp"))
small(116, os.path.join(HERE, "wizard_small_200.bmp"))
print("art ok")
