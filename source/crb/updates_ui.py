# crb/updates_ui.py - "a new version is out" inside the app.
#
#   * a popup with the release notes and Update now / Later / Skip this version;
#   * a button under the version number in the sidebar while an update is waiting;
#   * the Updates card on the Appearance & Help page: look for updates, install them by themselves,
#     Check now, What's new, Go back to the previous version.
# The work itself is in updates/client.py (GitHub, download, checks) and updates/engine.py (installing
# after the app has closed, and putting the old version back if the new one does not start).
import threading
import time

from PySide6.QtCore import QObject, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel, QMessageBox, QProgressDialog,
                               QPushButton, QTextBrowser, QVBoxLayout)

from crb.widgets import Card, SettingRow, ToggleSwitch
from updates import client

FIRST_CHECK_MS = 8_000                 # after the app has opened
EVERY_MS = 6 * 3600 * 1000            # then every 6 hours
COUNTDOWN_SECONDS = 20                # "Install updates by themselves": the notice before installing
SHOWN = ('available', 'notify-only', 'needs-installer', 'git')


class UpdateController(QObject):
    checked = Signal(object)
    progress = Signal(object)
    staged = Signal(object)

    def __init__(self, window):
        super().__init__(window)
        self.w = window
        self.enabled = client.supported()
        self.info = None
        self.status = None
        self.staging = None
        self.staging_version = None
        self.busy = False
        self.checking = False
        self.quiet = False
        self.after_stop = None
        self.bot_was_running = False
        self.shown_for = None
        self.dialog = None
        self.progress_dialog = None
        self.cancel = threading.Event()
        self.version_label = self.card_status = self.undo_btn = self.notes_btn = None
        self.check_switch = self.auto_switch = None
        self.checked.connect(self._on_checked)
        self.progress.connect(self._on_progress)
        self.staged.connect(self._on_staged)
        self.timer = QTimer(self)
        self.timer.setInterval(EVERY_MS)
        self.timer.timeout.connect(lambda: self.check(manual=False))

    # ================================================================== start / check
    def start(self):
        badge = getattr(self.w, 'update_badge', None)
        if badge is not None:
            badge.clicked.connect(self.show_dialog)
        if not self.enabled:
            return
        # The updater writes its result once this window has reported a good start (1.5 s after it
        # opens), so look a little later, twice.
        QTimer.singleShot(4000, self._take_result)
        QTimer.singleShot(15000, self._take_result)
        if client.load_prefs().get('check', True):
            QTimer.singleShot(FIRST_CHECK_MS, lambda: self.check(manual=False))
            self.timer.start()
        self.refresh()

    def check(self, manual=False):
        if not self.enabled or self.checking:
            return
        self.checking = True
        self._say('Looking for a new version…')

        def work():
            try:
                result = ('ok', client.check())
            except client.UpdateError as exc:
                result = ('error', str(exc))
            except Exception as exc:                          # noqa: BLE001 - shown to the user
                result = ('error', f'{exc.__class__.__name__}: {exc}')
            self.checked.emit((result, manual))
        threading.Thread(target=work, name='crb-update-check', daemon=True).start()

    def _on_checked(self, payload):
        (kind, data), manual = payload
        self.checking = False
        client.save_prefs(last_check=time.time())
        if kind == 'error':
            self._say(f'Could not look for a new version: {data}')
            if manual:
                QMessageBox.warning(self.w, 'Updates', f'Could not look for a new version.\n\n{data}')
            return
        self.info = data
        prefs = client.load_prefs()
        self.status = client.evaluate(data, manual=manual, prefs=prefs)
        version, current = data['version'], client.current_version()
        self.refresh()
        if self.status == 'current':
            self._say(f'You have the newest version ({current}).')
            if manual:
                QMessageBox.information(self.w, 'Updates', f'You have the newest version, {current}.')
            return
        if self.status == 'skipped':
            self._say(f'Version {version} is out (you chose to skip it).')
            return
        if self.status == 'bad':
            self._say(f'Version {version} is out, but it did not start on this computer: Check now offers it again.')
            return
        self._say(f'Version {version} is out.')
        if self.status == 'available' and prefs.get('auto') and not manual:
            self._auto_install()
        elif manual or self.shown_for != version:
            self.show_dialog()

    # ================================================================== the popup
    def show_dialog(self):
        info, status = self.info, self.status
        if not info or status not in SHOWN:
            return
        self.shown_for = info['version']
        if self.dialog is not None:
            self.dialog.close()
        v, cur = info['version'], client.current_version()
        d = QDialog(self.w)
        d.setObjectName('UpdateDialog')
        d.setWindowTitle('Update available')
        d.setWindowModality(Qt.WindowModal)
        d.setMinimumWidth(560)
        lay = QVBoxLayout(d)
        lay.setSpacing(10)
        title = QLabel(f'Clash Rekt Bot {v} is out')
        title.setObjectName('CardTitle')
        lay.addWidget(title)
        if status == 'available':
            text = (f'You have {cur}. Update now closes the app, installs {v} and opens it again, usually in '
                    f'under a minute. Settings, accounts, logs and your own attack scripts are kept, and if {v} '
                    f'does not start, {cur} comes back by itself.')
            if self.w.worker.isRunning():
                text += ' The bot is running: it is stopped first and started again after the update.'
        elif status == 'notify-only':
            text = (f'You have {cur}. This release cannot be installed from inside the app: download the '
                    'installer for your system from the release page.')
        elif status == 'needs-installer':
            text = (f'You have {cur}, which is too old to update itself to {v}. Install {v} once with the '
                    'installer from the release page; after that, updates install from inside the app.')
        else:
            text = f'You have {cur}. This copy is a git checkout: update it with "git pull".'
        sub = QLabel(text)
        sub.setObjectName('Help')
        sub.setWordWrap(True)
        lay.addWidget(sub)
        notes = QTextBrowser()
        notes.setObjectName('UpdateNotes')
        notes.setOpenExternalLinks(True)
        notes.setMarkdown(info.get('notes') or '_No release notes._')
        notes.setMinimumHeight(200)
        lay.addWidget(notes, 1)
        row = QHBoxLayout()
        row.addStretch(1)

        def button(text, name, slot, primary=False):
            b = QPushButton(text)
            b.setObjectName('Primary' if primary else '')
            b.setProperty('role', name)
            b.setAccessibleName(text)
            b.clicked.connect(slot)
            row.addWidget(b)
            return b

        def later():
            d.reject()

        def skip():
            client.save_prefs(skip=v)
            self.status = 'skipped'
            self.refresh()
            self._say(f'Version {v} skipped: it is not offered again by itself.')
            d.reject()

        if status == 'available':
            button('Skip this version', 'skip', skip)
            button('Later', 'later', later)
            now = button('Update now', 'now', lambda: (d.accept(), self.update_now()), primary=True)
            now.setDefault(True)
        else:
            if status != 'git':
                button('Skip this version', 'skip', skip)
            button('Later', 'later', later)
            button('Open the release page', 'download',
                   lambda: (QDesktopServices.openUrl(QUrl(info['page'])), d.accept()), primary=True)
        lay.addLayout(row)
        self.dialog = d
        d.open()

    # ================================================================== installing
    def update_now(self):
        if self.busy or self.status != 'available' or not self.info:
            return
        if self.w.worker.isRunning():
            answer = QMessageBox.question(
                self.w, 'Update', 'The bot is running. Stop it, install the update, and start it again '
                'afterwards?', QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if answer != QMessageBox.Yes:
                return
            self.bot_was_running = True
            self.after_stop = self._download_then_install
            self._say('Stopping the bot for the update…')
            self.w.stop_bot()
            return
        self.bot_was_running = False
        self._download_then_install()

    def bot_stopped(self):
        """Called by the window whenever the bot has stopped."""
        if self.after_stop and not self.w.worker.isRunning():
            fn, self.after_stop = self.after_stop, None
            QTimer.singleShot(500, fn)

    def _download_then_install(self, quiet=False):
        if self.busy or not self.info:
            return
        info = self.info
        if self.staging is not None and self.staging_version == info['version'] and self.staging.exists():
            return self._offer_countdown() if quiet else self._install()
        self.busy = True
        self.quiet = quiet
        self.cancel = threading.Event()
        if not quiet:
            dlg = QProgressDialog('Downloading the update…', 'Cancel', 0, 1000, self.w)
            dlg.setObjectName('UpdateProgress')
            dlg.setWindowTitle('Updating Clash Rekt Bot')
            dlg.setWindowModality(Qt.WindowModal)
            dlg.setMinimumDuration(0)
            dlg.setAutoClose(False)
            dlg.setAutoReset(False)
            dlg.canceled.connect(self.cancel.set)
            dlg.show()
            self.progress_dialog = dlg
        self._say(f'Downloading version {info["version"]}…')

        def work():
            try:
                path = client.download(info, progress=lambda done, total: self.progress.emit((done, total)),
                                       cancel=self.cancel)
                self.progress.emit(('checking', 0))
                self.staged.emit(('ok', client.stage(path, info)))
            except client.UpdateCancelled:
                self.staged.emit(('cancelled', None))
            except Exception as exc:                          # noqa: BLE001 - shown to the user
                self.staged.emit(('error', str(exc)))
        threading.Thread(target=work, name='crb-update-download', daemon=True).start()

    def _on_progress(self, payload):
        dlg = self.progress_dialog
        if dlg is None:
            return
        done, total = payload
        if done == 'checking':
            dlg.setLabelText('Checking the update…')
            dlg.setValue(1000)
            return
        if total:
            dlg.setValue(min(999, int(done * 1000 / total)))
            dlg.setLabelText(f'Downloading the update… {done / 1e6:.1f} of {total / 1e6:.1f} MB')
        else:
            dlg.setLabelText(f'Downloading the update… {done / 1e6:.1f} MB')

    def _on_staged(self, payload):
        kind, data = payload
        self.busy = False
        dlg, self.progress_dialog = self.progress_dialog, None
        if dlg is not None:
            dlg.close()
        if kind == 'cancelled':
            self._say('Update cancelled.')
            return
        if kind == 'error':
            self._say(f'The update could not be downloaded: {data}')
            if not self.quiet:
                QMessageBox.warning(self.w, 'Update', f'The update could not be downloaded.\n\n{data}\n\n'
                                    'Try again later, or download the installer from the release page.')
            return
        self.staging, self.staging_version = data, self.info['version']
        self.refresh()
        if self.quiet:
            self._offer_countdown()
        else:
            self._install()

    def _install(self):
        if self.w.worker.isRunning():
            self.after_stop = self._install
            return
        version = self.staging_version
        try:
            client.request_update(self.staging, version, self.bot_was_running)
        except client.UpdateError as exc:
            QMessageBox.warning(self.w, 'Update', f'The update could not be started.\n\n{exc}')
            return
        self._say(f'Installing version {version}: the app closes and opens again by itself.')
        self._closing_note(f'Installing Clash Rekt Bot {version}…')

    def _closing_note(self, text):
        box = QMessageBox(self.w)
        box.setObjectName('UpdateClosing')
        box.setWindowTitle('Updating')
        box.setIcon(QMessageBox.Information)
        box.setText(text)
        box.setInformativeText('The app closes now and opens again by itself in a moment.')
        box.setStandardButtons(QMessageBox.NoButton)
        box.open()
        self.closing_box = box
        QTimer.singleShot(1500, self._quit)

    def _quit(self):
        # QApplication.quit() asks every window to close first, and a message box without buttons
        # refuses: hide it, close the window, then end the event loop outright.
        box = getattr(self, 'closing_box', None)
        if box is not None:
            box.hide()
            box.deleteLater()
        self.w.updating = True
        self.w.close()
        QApplication.exit(0)

    # ------------------------------------------------------------------ installing by themselves
    def _auto_install(self):
        if self.busy:
            return
        self._say(f'Version {self.info["version"]} is out: downloading it in the background…')
        self._download_then_install(quiet=True)

    def _offer_countdown(self):
        if self.w.worker.isRunning():
            self.after_stop = self._offer_countdown
            self._say(f'Version {self.staging_version} is ready: it installs when the bot stops.')
            self.refresh()
            return
        v = self.staging_version
        box = QMessageBox(self.w)
        box.setObjectName('UpdateCountdown')
        box.setWindowTitle('Update ready')
        box.setIcon(QMessageBox.Information)
        now_btn = box.addButton('Install now', QMessageBox.AcceptRole)
        box.addButton('Not now', QMessageBox.RejectRole)
        state = {'left': COUNTDOWN_SECONDS, 'choice': None}

        def tick():
            box.setText(f'Clash Rekt Bot {v} is ready.')
            box.setInformativeText(f'It installs in {state["left"]} s: the app closes and opens again by itself. '
                                   'Settings, accounts and logs are kept.')
            if state['left'] <= 0:
                state['choice'] = 'now'
                timer.stop()
                box.close()
            state['left'] -= 1

        def clicked(btn):
            state['choice'] = 'now' if btn is now_btn else 'later'

        def finished(_code):
            timer.stop()
            if state['choice'] == 'now':
                self.bot_was_running = False
                self._install()
            else:
                self.after_stop = self._offer_countdown
                self._say(f'Version {v} is ready: it is offered again when the bot stops or the app starts.')

        timer = QTimer(box)
        timer.timeout.connect(tick)
        box.buttonClicked.connect(clicked)
        box.finished.connect(finished)
        tick()
        timer.start(1000)
        box.open()

    # ================================================================== going back
    def undo(self):
        previous = client.undo_available()
        if not previous:
            return
        answer = QMessageBox.question(self.w, 'Go back to the previous version',
                                      f'Go back to version {previous}? The app closes and opens again by '
                                      'itself. Settings and logs are kept.', QMessageBox.Yes | QMessageBox.No,
                                      QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        running = self.w.worker.isRunning()

        def go():
            try:
                client.request_undo(running)
            except client.UpdateError as exc:
                QMessageBox.warning(self.w, 'Go back', f'Could not go back.\n\n{exc}')
                return
            self._closing_note(f'Going back to Clash Rekt Bot {previous}…')

        if running:
            self.after_stop = go
            self.w.stop_bot()
        else:
            go()

    # ================================================================== after an update
    def _take_result(self):
        result = client.take_last_result()
        if result:
            self._show_result(result)

    def _show_result(self, result):
        box = QMessageBox(self.w)
        box.setObjectName('UpdateResult')
        if result.get('ok'):
            box.setIcon(QMessageBox.Information)
            box.setWindowTitle('Updated')
            if result.get('op') == 'rollback':
                box.setText(f"Clash Rekt Bot is back on version {result.get('to')}.")
            else:
                box.setText(f"Clash Rekt Bot was updated to version {result.get('to')}.")
                page = f"https://github.com/{client.engine.REPO}/releases/tag/v{result.get('to')}"
                notes = box.addButton("What's new", QMessageBox.HelpRole)
                notes.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(page)))
            box.addButton(QMessageBox.Ok)
            self._say(result.get('message') or '')
        else:
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle('Update did not work')
            box.setText(result.get('message') or 'The update did not work.')
            box.setInformativeText('Details are in .crb/updates/updater.log in the app folder.')
            box.addButton(QMessageBox.Ok)
            self._say(result.get('message') or '')
        box.open()

    # ================================================================== the Updates card
    def build_card(self, scheme):
        card = Card('Updates', 'New versions come from the Releases page on GitHub.', 'download', scheme)
        self.version_label = QLabel('')
        self.version_label.setObjectName('Help')
        self.version_label.setWordWrap(True)
        card.add(self.version_label)
        prefs = client.load_prefs()
        self.check_switch = ToggleSwitch(scheme)
        self.check_switch.setChecked(bool(prefs.get('check', True)))
        self.check_switch.toggled.connect(self._set_check)
        card.add(SettingRow('Look for new versions', 'When the app starts and every 6 hours. Only the release '
                            'information is downloaded from GitHub; nothing about you is sent.',
                            self.check_switch))
        card.add_divider()
        self.auto_switch = ToggleSwitch(scheme)
        self.auto_switch.setChecked(bool(prefs.get('auto', False)))
        self.auto_switch.toggled.connect(lambda on: client.save_prefs(auto=bool(on)))
        card.add(SettingRow('Install updates by themselves', 'Downloads a new version in the background and '
                            f'installs it after a {COUNTDOWN_SECONDS}-second notice. Never while the bot is '
                            'running: then it waits until the bot stops.', self.auto_switch))
        card.add_divider()
        row = QHBoxLayout()
        check_btn = QPushButton('  Check now')
        check_btn.clicked.connect(lambda: self.check(manual=True))
        row.addWidget(check_btn)
        self.notes_btn = QPushButton("  What's new")
        self.notes_btn.clicked.connect(self._open_page)
        row.addWidget(self.notes_btn)
        self.undo_btn = QPushButton('')
        self.undo_btn.clicked.connect(self.undo)
        row.addWidget(self.undo_btn)
        row.addStretch(1)
        card.body.addLayout(row)
        self.card_status = QLabel('')
        self.card_status.setObjectName('Help')
        self.card_status.setWordWrap(True)
        self.card_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        card.add(self.card_status)
        if not self.enabled:
            for w in (self.check_switch, self.auto_switch, check_btn, self.notes_btn, self.undo_btn):
                w.setEnabled(False)
            self.card_status.setText('This is an extra bot started by the main app: the main app handles updates.')
        self.refresh()
        return card

    def _set_check(self, on):
        client.save_prefs(check=bool(on))
        if on:
            self.timer.start()
            self.check(manual=False)
        else:
            self.timer.stop()
            self._say('Not looking for new versions.')

    def _open_page(self):
        page = (self.info or {}).get('page') or client.RELEASES_PAGE
        QDesktopServices.openUrl(QUrl(page))

    def refresh(self):
        current = client.current_version()
        if self.version_label is not None:
            text = f'This is version {current}.'
            if client.is_git_checkout():
                text += ' This copy is a git checkout: update it with "git pull".'
            self.version_label.setText(text)
        badge = getattr(self.w, 'update_badge', None)
        version = (self.info or {}).get('version', '')
        if badge is not None:
            show = self.status in SHOWN
            ready = self.staging is not None and self.staging_version == version
            badge.setText(f'  Update ready: {version}' if ready else f'  Update to {version}')
            badge.setToolTip(f'Clash Rekt Bot {version} is out: click for details')
            badge.setVisible(bool(show))
        if self.undo_btn is not None:
            previous = client.undo_available()
            self.undo_btn.setText(f'  Go back to {previous}')
            self.undo_btn.setVisible(bool(previous))

    def _say(self, text):
        if text:
            print(f'[UPDATE] {text}')
        if self.card_status is not None and self.enabled:
            self.card_status.setText(f'{time.strftime("%H:%M")}  {text}' if text else '')
