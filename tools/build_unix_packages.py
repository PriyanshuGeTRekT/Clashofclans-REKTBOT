"""Build the macOS app bundle and the Linux package trees from a release tree (stdlib only).

  python3 tools/build_unix_packages.py mac   <release tree> <out dir> <version>
  python3 tools/build_unix_packages.py linux <release tree> <out dir> <version>

mac   -> <out>/Clash Rekt Bot.app  (the .dmg is made from it with hdiutil on macOS: see
         .github/workflows/build-installers.yml)
linux -> <out>/deb/...              (dpkg-deb --build turns it into the .deb)

Both carry the app as a read-only payload; launcher/user_install.sh copies it into the user's folder
on first start (settings, logs and the downloaded Python live there) and starts it.
"""
import os
import shutil
import stat
import sys
from pathlib import Path

APP = 'Clash Rekt Bot'
BUNDLE_ID = 'io.github.priyanshugetrekt.clashrektbot'
WINDOWS_ONLY = ('runtime/Tools/adb', 'runtime/Tools/tesseract', 'Start Clash Rekt Bot.bat')


def _payload(tree, dest, version):
    def ignore(dirpath, names):
        rel = Path(dirpath).relative_to(tree).as_posix()
        return [n for n in names if (f'{rel}/{n}' if rel != '.' else n) in WINDOWS_ONLY
                or n in ('__pycache__', '.git', '.crb')]
    shutil.copytree(tree, dest, ignore=ignore)
    (dest / 'VERSION').write_text(version + '\n', encoding='utf-8')


def _exe(path, text):
    path.write_text(text, encoding='utf-8', newline='\n')
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def build_mac(tree, out, version):
    app = out / f'{APP}.app'
    if app.exists():
        shutil.rmtree(app)
    contents = app / 'Contents'
    (contents / 'MacOS').mkdir(parents=True)
    (contents / 'Resources').mkdir()
    _payload(tree, contents / 'Resources' / 'app', version)
    (contents / 'Info.plist').write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>{APP}</string>
  <key>CFBundleDisplayName</key><string>{APP}</string>
  <key>CFBundleIdentifier</key><string>{BUNDLE_ID}</string>
  <key>CFBundleVersion</key><string>{version}</string>
  <key>CFBundleShortVersionString</key><string>{version}</string>
  <key>CFBundleExecutable</key><string>ClashRektBot</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
""", encoding='utf-8')
    _exe(contents / 'MacOS' / 'ClashRektBot', f"""#!/bin/bash
# Clash Rekt Bot.app: copy the app into ~/Library/Application Support on first start, then run it.
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PAYLOAD="$APP_DIR/Resources/app"
TARGET="$HOME/Library/Application Support/{APP}"
if [ "$1" = "--no-launch" ]; then          # set up only (used by the build checks)
  exec bash "$PAYLOAD/launcher/user_install.sh" "$PAYLOAD" "$TARGET" --no-launch
fi
if [ ! -x "$TARGET/.crb/venv/bin/python" ] || [ "$(cat "$TARGET/VERSION" 2>/dev/null)" != "$(cat "$PAYLOAD/VERSION")" ]; then
  # first start or an update: show the one-time setup in Terminal
  SETUP="$TMPDIR/clash-rekt-bot-setup.command"
  printf '#!/bin/bash\\nbash "%s/launcher/user_install.sh" "%s" "%s"\\n' "$PAYLOAD" "$PAYLOAD" "$TARGET" > "$SETUP"
  chmod +x "$SETUP"
  open -a Terminal "$SETUP"
else
  exec bash "$TARGET/launcher/bootstrap.sh"
fi
""")
    return app


def build_linux(tree, out, version):
    root = out / 'deb'
    if root.exists():
        shutil.rmtree(root)
    opt = root / 'opt' / 'clash-rekt-bot'
    _payload(tree, opt, version)
    (root / 'DEBIAN').mkdir(parents=True)
    (root / 'DEBIAN' / 'control').write_text(f"""Package: clash-rekt-bot
Version: {version}
Section: games
Priority: optional
Architecture: all
Depends: bash, curl, unzip, rsync
Recommends: tesseract-ocr, libxcb-cursor0, libxkbcommon-x11-0, libegl1
Maintainer: PriyanshuGeTRekT <PriyanshuGeTRekT@users.noreply.github.com>
Description: Clash Rekt Bot - the only Clash of Clans bot you will ever need
 Farms, upgrades and plays Clash of Clans on any Android emulator, with a
 one-click app. The first start downloads Python and its libraries into
 ~/.local/share/clash-rekt-bot.
""", encoding='utf-8')
    bindir = root / 'usr' / 'bin'
    bindir.mkdir(parents=True)
    _exe(bindir / 'clash-rekt-bot', """#!/bin/bash
# Clash Rekt Bot: copy the app into ~/.local/share on first start, then run it.
exec bash /opt/clash-rekt-bot/launcher/user_install.sh /opt/clash-rekt-bot \\
  "${XDG_DATA_HOME:-$HOME/.local/share}/clash-rekt-bot" "$@"
""")
    apps = root / 'usr' / 'share' / 'applications'
    apps.mkdir(parents=True)
    (apps / 'clash-rekt-bot.desktop').write_text("""[Desktop Entry]
Type=Application
Name=Clash Rekt Bot
Comment=The only Clash of Clans bot you will ever need
Exec=clash-rekt-bot
Icon=clash-rekt-bot
Terminal=true
Categories=Game;Utility;
""", encoding='utf-8')
    icons = root / 'usr' / 'share' / 'icons' / 'hicolor' / '256x256' / 'apps'
    icons.mkdir(parents=True)
    shutil.copy2(tree / 'runtime' / 'assets' / 'crb_icon.png', icons / 'clash-rekt-bot.png')
    for path in root.rglob('*'):                      # dpkg wants 0755 dirs and no group/world write
        path.chmod(0o755 if path.is_dir() or os.access(path, os.X_OK) else 0o644)
    return root


if __name__ == '__main__':
    kind, tree, out, version = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
    out.mkdir(parents=True, exist_ok=True)
    print((build_mac if kind == 'mac' else build_linux)(tree, out, version))
