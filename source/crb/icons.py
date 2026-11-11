# crb/icons.py - the Clash Rekt Bot icon set: 24x24 line icons drawn for this app, tinted at runtime.
from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_STROKE = 'fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"'

PATHS = {
    'dashboard': '<rect x="3" y="3" width="8" height="10" rx="2"/><rect x="13" y="3" width="8" height="6" rx="2"/>'
                 '<rect x="13" y="11" width="8" height="10" rx="2"/><rect x="3" y="15" width="8" height="6" rx="2"/>',
    'attack': '<path d="M14.5 3.5 20.5 3.5 20.5 9.5 9 21 3 15Z"/><path d="M7 13l4 4"/><path d="M3 21l3-3"/>',
    'village': '<path d="M3 21V9l3-2 3 2v3h6V9l3-2 3 2v12Z"/><path d="M10 21v-4a2 2 0 0 1 4 0v4"/>'
               '<path d="M6 7V4M18 7V4"/>',
    'builder': '<path d="M14 6l4 4"/><path d="M15 3l6 6-3 3-6-6Z"/><path d="M12 9 3 18l3 3 9-9"/>',
    'clan': '<path d="M12 3 20 6v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6Z"/><path d="m9 12 2 2 4-4"/>',
    'schedule': '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    'accounts': '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.6-3.6 3.4-5.5 6.5-5.5s5.9 1.9 6.5 5.5"/>'
                '<path d="M16 4.5a3.5 3.5 0 0 1 0 7"/><path d="M18 14.8c2 .6 3.2 2.4 3.5 5.2"/>',
    'emulator': '<rect x="6" y="2.5" width="12" height="19" rx="2.5"/><path d="M10.5 18.5h3"/>',
    'logs': '<path d="M8 6h12M8 12h12M8 18h12"/><circle cx="4" cy="6" r="1"/><circle cx="4" cy="12" r="1"/><circle cx="4" cy="18" r="1"/>',
    'settings': '<circle cx="12" cy="12" r="3"/><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1'
                'M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1"/>',
    'play': '<path d="M7 4.5v15l12-7.5Z"/>',
    'pause': '<path d="M8 5v14M16 5v14"/>',
    'stop': '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    'wizard': '<path d="M15 4V2M15 10V8M11 6H9M21 6h-2M17.8 3.2l1.4-1.4M17.8 8.8l1.4 1.4M12.2 3.2 10.8 1.8"/>'
              '<path d="M3 21 14 10l-1-1L2 20Z"/>',
    'refresh': '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>',
    'folder': '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/>',
    'check': '<path d="m5 12 5 5 9-10"/>',
    'warn': '<path d="M12 3 2 20h20Z"/><path d="M12 10v4M12 17v.5"/>',
    'up': '<path d="m6 15 6-6 6 6"/>',
    'down': '<path d="m6 9 6 6 6-6"/>',
    'edit': '<path d="M4 20h4L19 9l-4-4L4 16Z"/><path d="m13 7 4 4"/>',
    'trash': '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
    'download': '<path d="M12 3v12M7 10l5 5 5-5"/><path d="M4 21h16"/>',
    'link': '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
    'info': '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/>',
    'star': '<path d="m12 3 2.7 5.6 6.1.8-4.5 4.2 1.1 6-5.4-2.9-5.4 2.9 1.1-6L3.2 9.4l6.1-.8Z"/>',
    'gold': '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4"/>',
    'elixir': '<path d="M12 3c3 4 6 7.5 6 11a6 6 0 0 1-12 0c0-3.5 3-7 6-11Z"/>',
    'dark': '<path d="M12 3c3 4 6 7.5 6 11a6 6 0 0 1-12 0c0-3.5 3-7 6-11Z"/><path d="M9 15a3 3 0 0 0 3 3"/>',
    'clock': '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    'wall': '<rect x="3" y="5" width="18" height="14" rx="1"/><path d="M3 12h18M9 5v7M15 12v7"/>',
    'zoom': '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4M8 11h6M11 8v6"/>',
}


def svg(name, color):
    body = PATHS.get(name, PATHS['info'])
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><g {_STROKE.format(c=color)}>'
            f'{body}</g></svg>')


def pixmap(name, color, size=20, ratio=2.0):
    renderer = QSvgRenderer(QByteArray(svg(name, color).encode()))
    px = int(size * ratio)
    img = QImage(px, px, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    renderer.render(p)
    p.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(ratio)
    return pm


def icon(name, color, size=20):
    return QIcon(pixmap(name, color, size))


def logo_pixmap(path, size):
    renderer = QSvgRenderer(path)
    ratio = 2.0
    img = QImage(int(size * ratio), int(size * ratio), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    renderer.render(p)
    p.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(ratio)
    return pm


def write_app_icons(svg_path, out_dir):
    """Render the logo to icon.png and a multi-size icon.ico (used by shortcuts and the window)."""
    import os
    os.makedirs(out_dir, exist_ok=True)
    renderer = QSvgRenderer(svg_path)
    images = []
    for s in (16, 24, 32, 48, 64, 128, 256):
        img = QImage(s, s, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        renderer.render(p)
        p.end()
        images.append(img)
    images[-1].save(os.path.join(out_dir, 'crb_icon.png'))
    _write_ico(images, os.path.join(out_dir, 'crb_icon.ico'))
    return os.path.join(out_dir, 'crb_icon.ico')


def _write_ico(images, path):
    """Multi-resolution .ico with PNG-compressed entries (no imageformats plugin needed)."""
    import struct
    from PySide6.QtCore import QBuffer, QIODevice
    blobs = []
    for img in images:
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        img.save(buf, 'PNG')
        blobs.append((img.width(), bytes(buf.data())))
    header = struct.pack('<HHH', 0, 1, len(blobs))
    offset = 6 + 16 * len(blobs)
    entries = b''
    data = b''
    for w, blob in blobs:
        entries += struct.pack('<BBBBHHII', w if w < 256 else 0, w if w < 256 else 0, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
        data += blob
    with open(path, 'wb') as fh:
        fh.write(header + entries + data)


__all__ = ['icon', 'pixmap', 'logo_pixmap', 'write_app_icons', 'QSize']
