# clangames.py -- reconstructed from Pyarmor-decrypted CPython 3.10 bytecode
# (ACBot Basic v1.6.7). Pyarmor enter/exit/assert wrappers stripped; local
# variable names were obfuscated (_var_var_N) and have been renamed by usage.
# Lines marked "# RECON:" are reconstruction judgement calls.
import time
import cv2
import re
import fixed_points as fp
from adb import swipe, tap
from actions import click_point
import os
from pathlib import Path
import defaults
from utils.runtime_paths import resolve_resource_path, resolve_writable_path

CG_DEBUG = False
CG_EDIT_VISUAL_DEBUG = False
CG_EDIT_VISUAL_DEBUG_DIR = 'logs/cg_edit_debug'
CG_EDIT_SCROLL_SETTLE_SECONDS = 0.9
CG_EDIT_POST_REMOVE_SETTLE_SECONDS = 0.6
CG_EDIT_EXTRA_REMOVALS = 6
# FIX: the attack strategies never deploy Clan Castle troops, so a requested super troop is never
# used and a cgsuper_* challenge can only end by timing out, blocking every other challenge. After
# this many attack cycles on the same one it is trashed and skipped for the rest of the session.
CG_SUPER_MAX_CYCLES = 6


class ClanGames:
    # Challenges that the army "edit" logic will NOT apply for a given army
    # (i.e. the current army already satisfies them).
    CG_EDIT_EXEMPTED_CHALLENGES = {
        'edragon': ['cgarmy_edragon', 'cgarmy_balloon', 'cgspell_1_freeze', 'cgspell_2_rage'],
        'dragon': ['cgarmy_balloon', 'cgspell_1_freeze', 'cgspell_2_rage'],
        'valkyrie': ['cgarmy_valkyrie'],
        'thrower': ['cgarmy_thrower', 'cgarmy_healer', 'cgspell_1_totem'],
    }

    def _map_cgsuper_to_request_key(self, name):
        tpl = name
        if not tpl or not tpl.startswith('cgsuper_'):
            return None
        suffix = tpl[len('cgsuper_'):]
        return f'army_super_{suffix}'

    def _templates_root(self):
        root = Path(defaults.TEMPLATES_DIR)
        if not root.is_absolute():
            root = resolve_writable_path(str(root))
        return root

    def __init__(self, vision, active_config=None):
        self.vision = vision
        self.active_config = active_config or {}
        self.cached_cg_super = None
        self.cg_super_selected = False
        self.cached_cg_edit_challenge = None
        self.cg_army_temp_active = False
        self.cg_army_restore_pending = False
        self.cg_finished_for_session = False
        self.cg_edit_challenge_unavailable = False
        self._cg_filter_signature = None
        self._cg_filtered_templates = None
        self._cg_filtered_super_templates = None
        # FIX (slot 8): what a challenge edit changed, so the "Current Army" can be put back.
        self._edit_log = None          # {template_key: units removed} while an edit is running
        self.slot8_restore = None      # {'removed': {...}, 'added': key|None, 'is_spell': bool}
        # FIX (stalled super challenges): cycles seen on the active cgsuper_* and the ones given up on
        self._super_cycles = 0
        self._session_skipped = set()

    # ------------------------------------------------------------------ FIX: slot-8 army restore
    # With SELECTED_ARMY_SLOT == 8 ("Current Army") there is no saved recipe to re-select, so the
    # original never undid challenge edits and the army drifted (fewer base troops, extra challenge
    # troops) on every troop/spell challenge. Edits are now recorded and reversed in place.
    ROW_TILE_SCALE = 0.80                      # army-row tiles are 0.8x the picker templates
    ROW_MINUS_OFFSET = (37, -36)               # minus button relative to an army-row tile centre
    TROOP_ROW_REGION = (690, 230, 1570, 370)   # army row with the troop picker open
    SPELL_ROW_REGION = (690, 345, 1570, 485)   # army row with the spell picker open

    def _is_current_army_slot(self, cfg=None):
        cfg = cfg if cfg is not None else self.active_config
        return int(cfg.get('SELECTED_ARMY_SLOT', 0) or 0) == 8

    def _row_template(self, key):
        entry = self.vision.templates.get(key)
        if not entry:
            return None
        img = entry['img']
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        return cv2.resize(gray, None, fx=self.ROW_TILE_SCALE, fy=self.ROW_TILE_SCALE,
                          interpolation=cv2.INTER_AREA)

    def _identify_row_tile(self, minus_point):
        """Template key of the troop/spell whose army-row minus button is at minus_point."""
        prefix = 'edit_armyspell_' if minus_point in (fp.EDIT_ARMY_SPELL_REMOVE1,
                                                      fp.EDIT_ARMY_SPELL_REMOVE2) else 'edit_army_'
        cx = minus_point[0] - self.ROW_MINUS_OFFSET[0]
        cy = minus_point[1] - self.ROW_MINUS_OFFSET[1]
        screen = self.vision.grab()
        x1, y1 = max(0, cx - 75), max(0, cy - 75)
        crop = cv2.cvtColor(screen[y1:cy + 75, x1:cx + 75], cv2.COLOR_BGR2GRAY)
        best_key, best_score = None, 0.0
        for key in self.vision.templates:
            if not key.startswith(prefix) or (prefix == 'edit_army_' and key.startswith('edit_armyspell_')):
                continue
            tpl = self._row_template(key)
            if tpl is None or tpl.shape[0] > crop.shape[0] or tpl.shape[1] > crop.shape[1]:
                continue
            _, score, _, _ = cv2.minMaxLoc(cv2.matchTemplate(crop, tpl, cv2.TM_CCOEFF_NORMED))
            if score > best_score:
                best_key, best_score = key, score
        return best_key if best_score >= 0.8 else None

    def _record_removal(self, minus_point):
        if self._edit_log is None:
            return
        key = self._identify_row_tile(minus_point)
        if key:
            self._edit_log[key] = self._edit_log.get(key, 0) + 1
        else:
            print('[CLAN GAME]Could not identify removed unit; restore will be incomplete')
            self._edit_log['?'] = self._edit_log.get('?', 0) + 1

    def _find_row_tile(self, key, region):
        tpl = self._row_template(key)
        if tpl is None:
            return None
        x1, y1, x2, y2 = region
        roi = cv2.cvtColor(self.vision.grab()[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
        _, score, _, loc = cv2.minMaxLoc(cv2.matchTemplate(roi, tpl, cv2.TM_CCOEFF_NORMED))
        if score < 0.8:
            return None
        return (x1 + loc[0] + tpl.shape[1] // 2, y1 + loc[1] + tpl.shape[0] // 2)

    def _rewind_picker(self):
        for _ in range(4):
            swipe(*fp.EDIT_ARMY_TROOP_SWIPE_BACK)
            time.sleep(0.35)
        time.sleep(0.5)

    def _finish_edit_record(self, added_key, is_spell, cfg):
        log, self._edit_log = self._edit_log, None
        if not self._is_current_army_slot(cfg):
            return
        removed = {k: v for k, v in (log or {}).items() if k != '?'}
        if removed or added_key:
            self.slot8_restore = {'removed': removed, 'added': added_key, 'is_spell': is_spell}

    def restore_slot8_edit(self):
        """Reverse the last challenge edit on the open My Army screen. Returns True when complete."""
        rec = self.slot8_restore
        if not rec:
            return True
        is_spell = rec['is_spell']
        print('[CLAN GAME]Restoring current army after challenge edit')
        tap(*(fp.EDIT_ARMY_SPELL if is_spell else fp.EDIT_ARMY_TROOP))
        time.sleep(0.8)
        ok = True
        if rec['added']:
            pos = self._find_row_tile(rec['added'], self.SPELL_ROW_REGION if is_spell else self.TROOP_ROW_REGION)
            if pos:
                tap(pos[0] + self.ROW_MINUS_OFFSET[0], pos[1] + self.ROW_MINUS_OFFSET[1])
                time.sleep(0.5)
            else:
                print(f"[CLAN GAME]Restore: {self._clean_template_name(rec['added'])} not in army (already gone)")
        for key, count in rec['removed'].items():
            self._rewind_picker()
            found_pos, _meta = self._search_edit_picker(key, 0.8)
            if not found_pos:
                print(f'[CLAN GAME]Restore: {self._clean_template_name(key)} not found in picker')
                ok = False
                continue
            for _ in range(count):
                tap(*found_pos)
                time.sleep(0.3)
        tap(*fp.EDIT_ARMY_DONE)
        time.sleep(0.5)
        self.slot8_restore = None
        print('[CLAN GAME]Current army restored' if ok else '[CLAN GAME]Current army only partially restored')
        return ok

    def _normalize_cg_challenge_key(self, key):
        if not key:
            return ''
        norm = str(key).strip().lower()
        if norm.startswith('cg_'):
            return re.sub('\\d+$', '', norm)
        return norm

    def _get_disabled_cg_challenges(self):
        disabled = self.active_config.get('CG_DISABLED_CHALLENGES', [])
        if isinstance(disabled, str):
            disabled = [item.strip() for item in disabled.split(',') if item.strip()]
        if not isinstance(disabled, (list, tuple, set)):
            return set()
        keys = {self._normalize_cg_challenge_key(item) for item in disabled if str(item).strip()}
        keys |= self._session_skipped
        keys.discard('')
        return keys

    def _get_filtered_challenge_templates(self):
        disabled = self._get_disabled_cg_challenges()
        signature = tuple(sorted(disabled))
        if signature == self._cg_filter_signature:
            return (self._cg_filtered_templates, self._cg_filtered_super_templates)
        self._cg_filter_signature = signature
        self._cg_filtered_templates = {
            name: tpl for name, tpl in self.vision.cg_templates.items()
            if self._normalize_cg_challenge_key(name) not in disabled
        }
        self._cg_filtered_super_templates = {
            name: tpl for name, tpl in self.vision.cg_super_templates.items()
            if self._normalize_cg_challenge_key(name) not in disabled
        }
        return (self._cg_filtered_templates, self._cg_filtered_super_templates)

    def _clean_template_name(self, name):
        tpl = name
        if not tpl:
            return tpl
        if tpl.startswith('army_'):
            return tpl[5:]
        if tpl.startswith('cgsuper_'):
            return tpl.replace('cg', '', 1)
        if tpl.startswith('cghero_'):
            return tpl[7:]
        if tpl.startswith('cg_'):
            return tpl[3:]
        if tpl.startswith('cgarmy_'):
            return tpl[7:]
        if tpl.startswith('cgspell_'):
            parts = tpl.split('_', 2)
            if len(parts) >= 3:
                return parts[2]
        return tpl

    def _describe_cg_challenge(self, name):
        tpl = name
        if not tpl:
            return None
        cleaned = self._clean_template_name(tpl)
        pretty = cleaned.replace('_', ' ').strip().title()
        if tpl.startswith('cgarmy_'):
            return f'[CLAN GAME]Troop challenge: {pretty}'
        if tpl.startswith('cgspell_'):
            return f'[CLAN GAME]Spell challenge: {pretty}'
        if tpl.startswith('cghero_'):
            return f'[CLAN GAME]Hero challenge: {pretty}'
        if tpl.startswith('cgsuper_'):
            return f'[CLAN GAME]Super troop request: {pretty}'
        if tpl.startswith('cg_'):
            return f'[CLAN GAME]Challenge: {pretty}'
        return f'[CLAN GAME]Challenge: {pretty}'

    def run(self):
        if self.cg_finished_for_session:
            return None
        start_pos = self.vision.find_clan_games_start_scaled()
        if not start_pos:
            print('[CLAN GAME]Unable to start')
            return None
        tap(*start_pos)
        time.sleep(3)
        if self._find_ui('ui_cooldown'):
            print('[CLAN GAME]Cooldown active')
            self._close()
            return None
        if self._busy():
            print('[CLAN GAME]Challenge in progress')
            if self.cg_edit_challenge_unavailable:
                print('[CLAN GAME]Trashing unavailable challenge')
                self.cg_edit_challenge_unavailable = False
                self._trash_active_challenge()
                self._close()
                return None
            # Identify the currently-active challenge (threshold 0.5)
            name, start_pos, score = self.vision.match_clangames(
                fp.CLAN_GAMES_ACTIVE_REGION, self.vision.cg_super_templates, 0.5)
            if CG_DEBUG:
                print(f'[CLAN GAMES]Active super scan -> name={name} score={score:.3f}')
            if name and name.startswith('cgsuper_'):
                print(self._describe_cg_challenge(name))
                request_key = self._map_cgsuper_to_request_key(name)
                if request_key != self.cached_cg_super:
                    self.cg_super_selected = False
                    self._super_cycles = 0
                    if CG_DEBUG:
                        print(f'[CLAN GAMES]Super challenge changed from {self.cached_cg_super} to {request_key}, will trash and select')
                else:
                    self.cg_super_selected = True
                self._super_cycles += 1
                if self._super_cycles > CG_SUPER_MAX_CYCLES:
                    print(f'[CLAN GAME]Super troop challenge {self._clean_template_name(name)} stalled '
                          f'after {CG_SUPER_MAX_CYCLES} attacks (Clan Castle troops are not deployed), trashing')
                    self._session_skipped.add(self._normalize_cg_challenge_key(name))
                    self._super_cycles = 0
                    self.cached_cg_super = None
                    self.cg_super_selected = False
                    self._trash_active_challenge()
                    self._close()
                    return None
                self.cached_cg_super = request_key
                self.cached_cg_edit_challenge = None
                if CG_DEBUG:
                    print(f'[CLAN GAMES]Cached super challenge from active challenge: {self.cached_cg_super}')
            else:
                reg_name, reg_pos, reg_score = self.vision.match_clangames(
                    fp.CLAN_GAMES_ACTIVE_REGION, self.vision.cg_templates, 0.5)
                if CG_DEBUG:
                    print(f'[CLAN GAMES]Active regular scan -> name={reg_name} score={reg_score:.3f}')
                if reg_name and (reg_name.startswith('cgarmy_') or reg_name.startswith('cgspell_')):
                    print(self._describe_cg_challenge(reg_name))
                    if reg_name != self.cached_cg_edit_challenge and CG_DEBUG:
                        print(f'[CLAN GAMES]Active edit challenge changed from {self.cached_cg_edit_challenge} to {reg_name}')
                    self.cached_cg_edit_challenge = reg_name
                    self.cached_cg_super = None
                    self.cg_super_selected = False
                    if CG_DEBUG:
                        print(f'[CLAN GAMES]Cached edit challenge from active challenge: {self.cached_cg_edit_challenge}')
                elif CG_DEBUG and reg_name:
                    print('[CLAN GAMES]Active challenge found but not cacheable (expected cgarmy_* or cgspell_*)')
                elif CG_DEBUG:
                    print('[CLAN GAMES]Active challenge not matched at threshold (no cache update)')
            self._close()
            return None
        failed_btn = self._failed()
        if failed_btn:
            print('[CLAN GAME]Challenge failed')
            tap(*failed_btn)
            time.sleep(1)
            trash_btn = self._find_ui('ui_trash')
            if trash_btn:
                print('[CLAN GAME]Removing failed challenge')
                tap(*trash_btn)
                time.sleep(1)
                self._safety_retrash_active_challenge_once()
        if self._is_cg_finished():
            self.cg_finished_for_session = True
            print('[CLAN GAME]ClanGames finished, skipping')
            self._close()
            return None
        challenges = self._find_challenges()
        if not challenges:
            print('[CLAN GAME]No challenges found, scanning')
            swipe(*fp.CLAN_GAMES_SWIPE)
            time.sleep(0.8)
            challenges = self._find_challenges()
        if challenges:
            name, start_pos, score = challenges[0]
            if name.startswith('cgsuper_'):
                self.cached_cg_super = self._map_cgsuper_to_request_key(name)
                self.cg_super_selected = False
                self.cached_cg_edit_challenge = None
            elif name.startswith('cgarmy_') or name.startswith('cgspell_'):
                self.cached_cg_edit_challenge = name
                self.cached_cg_super = None
                self.cg_super_selected = False
            else:
                self.cached_cg_super = None
                self.cg_super_selected = False
                self.cached_cg_edit_challenge = None
            print(f'[CLAN GAME]Starting {self._clean_template_name(name)}')
            tap(*start_pos)
            time.sleep(0.5)
            start_btn = self._find_ui('ui_start')
            if start_btn:
                tap(*start_btn)
                time.sleep(0.5)
            self._close()
            return None
        print('[CLAN GAME]No suitable challenges, trashing challenge')
        challenge_btn = self._find_ui('ui_challenge')
        if challenge_btn:
            tap(*challenge_btn)
            time.sleep(0.5)
            start_btn = self._find_ui('ui_start')
            if start_btn:
                tap(*start_btn)
                time.sleep(2)
            trash_btn = self._find_ui('ui_trash')
            if trash_btn:
                print('[CLAN GAME]Trashing challenge')
                tap(*trash_btn)
                time.sleep(0.5)
                okay_btn = self._find_ui('ui_okay')
                if okay_btn:
                    tap(*okay_btn)
                    time.sleep(0.5)
                self._safety_retrash_active_challenge_once()
        self._close()
        return None

    def _trash_active_challenge(self):
        # Open the active challenge and trash it (the original's "unavailable challenge" sequence).
        # FIX: the original tapped 'ui_challenge' (the silver medal icon), which only appears on
        # challenges that have NOT been started, so it opened another tile and never found Trash.
        # The active challenge always sits in CLAN_GAMES_ACTIVE_REGION; tap that tile instead.
        # The panel and the "Trash Challenge?" dialog animate in: a tap during the animation is
        # ignored, and the tile still reads as busy for ~0.5 s after Okay, so wait for each step
        # before the original's one-shot retry (which otherwise dismissed the dialog it opened).
        x1, y1, x2, y2 = fp.CLAN_GAMES_ACTIVE_REGION
        challenge_btn = ((x1 + x2) // 2, (y1 + y2) // 2)
        if challenge_btn:
            tap(*challenge_btn)
            time.sleep(1.0)
            trash_btn = self._find_ui('ui_trash')
            if trash_btn:
                tap(*trash_btn)
                time.sleep(1.0)
                okay_btn = self._find_ui('ui_okay')
                if okay_btn:
                    tap(*okay_btn)
                    time.sleep(1.5)
                if self._busy():
                    print('[CLAN GAME]Trash did not take, retrying once')
                    self._safety_retrash_active_challenge_once()
                else:
                    print('[CLAN GAME]Challenge trashed')
            else:
                print('[CLAN GAME]Trash button not found on the active challenge')

    def _busy(self):
        # A challenge is "in progress" if the colour-test pixel area is yellow/orange.
        import numpy
        img = self.vision.grab()
        x, y = fp.CLAN_GAMES_COLOR_TEST
        x0, y0 = max(0, x - 5), max(0, y - 5)
        x1, y1 = min(img.shape[1], x + 5), min(img.shape[0], y + 5)
        roi = img[y0:y1, x0:x1]
        if roi.size == 0:
            return False
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        lower = numpy.array([20, 150, 200])
        upper = numpy.array([28, 220, 255])
        mask = cv2.inRange(hsv, lower, upper)
        ratio = numpy.sum(mask > 0) / mask.size
        return ratio > 0.05

    def _failed(self):
        # A failed challenge shows red at the colour-test point; returns its position.
        import numpy
        img = self.vision.grab()
        x, y = fp.CLAN_GAMES_COLOR_TEST
        x0, y0 = max(0, x - 5), max(0, y - 5)
        x1, y1 = min(img.shape[1], x + 5), min(img.shape[0], y + 5)
        roi = img[y0:y1, x0:x1]
        if roi.size == 0:
            return None
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        lower_red1 = numpy.array([0, 180, 200])
        upper_red1 = numpy.array([5, 255, 255])
        lower_red2 = numpy.array([175, 180, 200])
        upper_red2 = numpy.array([180, 255, 255])
        mask1 = cv2.inRange(hsv, lower_red1, upper_red1)
        mask2 = cv2.inRange(hsv, lower_red2, upper_red2)
        mask = cv2.bitwise_or(mask1, mask2)
        ratio = numpy.sum(mask > 0) / mask.size
        if ratio > 0.05:
            return (x, y)
        return None

    def _close(self):
        tap(*fp.CLAN_GAMES_CLOSE)
        time.sleep(0.5)

    def _safety_retrash_active_challenge_once(self):
        if not self._busy() and not self._failed():
            return None
        if self._busy():
            # FIX: an active challenge has no medal icon; open it from its fixed tile (see above).
            x1, y1, x2, y2 = fp.CLAN_GAMES_ACTIVE_REGION
            challenge_btn = ((x1 + x2) // 2, (y1 + y2) // 2)
        else:
            challenge_btn = self._find_ui('ui_challenge')
        if not challenge_btn:
            return None
        tap(*challenge_btn)
        time.sleep(1.0)  # FIX: was 0.4; taps during the panel/dialog animation are ignored
        trash_btn = self._find_ui('ui_trash')
        if not trash_btn:
            return None
        tap(*trash_btn)
        time.sleep(1.0)
        okay_btn = self._find_ui('ui_okay')
        if okay_btn:
            tap(*okay_btn)
            time.sleep(1.0)
            return None
        return None

    def _find_ui(self, key):
        pos = self.vision.match_template_region(fp.CLAN_GAMES_REGION, key, 0.8)
        if pos and CG_DEBUG:
            print(f'[CLAN DEBUG] {key} matched at {pos}')
        return pos

    def _is_cg_finished(self):
        pos = self.vision.match_template_region(fp.CLAN_GAMES_FINISHED_REGION, 'cg_finished', 0.85)
        return bool(pos)

    def _find_challenges(self):
        templates, super_templates = self._get_filtered_challenge_templates()
        if CG_DEBUG:
            print(f"[CLAN GAME] CG_TROOP_CHALLENGES = {self.active_config.get('CG_TROOP_CHALLENGES', False)}")
            print(f'[CLAN GAME] active_config keys: {list(self.active_config.keys())}')
        if self.active_config.get('CG_TROOP_CHALLENGES', False):
            # Super-troop ("cgsuper_*") challenges are preferred (threshold 0.85)
            if CG_DEBUG:
                print(f'[CLAN GAME] Looking for cgsuper in {len(super_templates)} templates')
            name, pos, score = self.vision.match_clangames(fp.CLAN_GAMES_REGION, super_templates, 0.85)
            if CG_DEBUG:
                shown = self._clean_template_name(name) if name else name
                print(f'[CLAN GAME] cgsuper search result: {shown} ({score:.3f})')
            if not name:
                if CG_DEBUG:
                    print(f'[CLAN GAME] No army found, trying regular challenges in {len(templates)} templates')
                name, pos, score = self.vision.match_clangames(fp.CLAN_GAMES_REGION, templates, 0.94)
                if CG_DEBUG:
                    shown = self._clean_template_name(name) if name else name
                    print(f'[CLAN GAME] Regular challenge result: {shown} ({score:.3f})')
        else:
            name, pos, score = self.vision.match_clangames(fp.CLAN_GAMES_REGION, templates, 0.94)
        if not name:
            return []
        return [(name, pos, score)]

    def auto_collect_templates(self):
        out_dir = self._templates_root() / 'clangames' / 'auto'
        os.makedirs(out_dir, exist_ok=True)
        img = self.vision.grab()
        x1, y1, x2, y2 = fp.CLAN_GAMES_REGION
        crop = img[y1:y2, x1:x2]
        if crop.size == 0:
            return None
        ts = int(time.time() * 1000)
        path = os.path.join(out_dir, f'clangames_{ts}.png')
        ok, buf = cv2.imencode('.png', crop)
        if ok:
            with open(path, 'wb') as f:
                f.write(buf.tobytes())
        if CG_DEBUG:
            print(f'[CLAN AUTO] Saved region{path}')
            return None
        return None

    def _handle_cg_troops(self):
        # Clan Castle request for the super troop demanded by an active
        # "cgsuper_*" clan-games challenge.
        if not self.cached_cg_super or not self.cg_super_selected:
            # Clear the existing request, then edit the request to pick the super troop
            tap(*fp.CC_TRASH)
            time.sleep(0.5)
            okay_btn = self.vision.find_okay_button()
            if okay_btn:
                tap(*okay_btn)
                time.sleep(0.5)
            request_btn = self.vision.find_cg_request_available()
            if not request_btn:
                print('[CLAN GAME]Request button not found, will retry')
                self.cg_super_selected = False
                return None
            tap(*request_btn)
            time.sleep(0.5)
            tap(*fp.CC_EDIT)
            time.sleep(0.5)
            target = self.cached_cg_super
            if not target:
                print('[CLAN GAME]No troop target set')
                return None
            troop_name = target.removeprefix('army_')
            print(f'[CLAN GAME]Setting up request: {troop_name}')
            selected = False
            for _page in range(6):
                pos = self.vision.match_template_region(fp.CC_REQUEST_REGION, target, 0.8)
                if pos:
                    # Tap the troop repeatedly (up to 20x) until its icon greys out
                    # (mean HSV saturation < 40 => slot full / no more capacity)
                    for _tap in range(20):
                        tap(*pos)
                        time.sleep(0.05)
                        img = self.vision.grab()
                        rx1, ry1, rx2, ry2 = fp.CC_REQUEST_REGION
                        px, py = pos
                        cx1 = max(rx1, px - 15)
                        cy1 = max(ry1, py - 15)
                        cx2 = min(rx2, px + 15)
                        cy2 = min(ry2, py + 15)
                        crop = img[cy1:cy2, cx1:cx2]
                        if crop.size > 0:
                            hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
                            sat = hsv[:, :, 1]
                            mean_sat = float(sat.mean())
                            if mean_sat < 40:
                                break
                    time.sleep(0.1)
                    tap(*fp.CC_CONFIRM)
                    time.sleep(0.1)
                    selected = True
                    break
                swipe(*fp.CC_SWIPE)
                time.sleep(2)
            if not selected:
                print('[CLAN GAME]Troop not found, retrying')
                swipe(*fp.CC_SWIPE_BACK)
                time.sleep(2)
                for _page in range(6):
                    pos = self.vision.match_template_region(fp.CC_REQUEST_REGION, target, 0.8)
                    if pos:
                        print(f'[CLAN GAME]Selecting {troop_name}')
                        for _tap in range(20):
                            tap(*pos)
                            time.sleep(0.05)
                            img = self.vision.grab()
                            rx1, ry1, rx2, ry2 = fp.CC_REQUEST_REGION
                            px, py = pos
                            cx1 = max(rx1, px - 15)
                            cy1 = max(ry1, py - 15)
                            cx2 = min(rx2, px + 15)
                            cy2 = min(ry2, py + 15)
                            crop = img[cy1:cy2, cx1:cx2]
                            if crop.size > 0:
                                hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
                                sat = hsv[:, :, 1]
                                mean_sat = float(sat.mean())
                                if mean_sat < 40:
                                    break
                        time.sleep(0.1)
                        tap(*fp.CC_CONFIRM)
                        time.sleep(0.1)
                        selected = True
                        break
                    swipe(*fp.CC_SWIPE)
                    time.sleep(2)
            if not selected:
                print('[CLAN GAME]Unable to select troop, skipping')
                return None
            self.cg_super_selected = True
            tap(*fp.HOME_SEND_TROOP_REQUEST)
            time.sleep(0.2)
            request_btn = self.vision.find_request_available()
            if request_btn:
                tap(*request_btn)
                time.sleep(0.1)
                tap(*fp.HOME_SEND_TROOP_REQUEST)
                time.sleep(0.2)
        else:
            # Super troop already configured in the request: just send it
            request_btn = self.vision.find_request_available()
            if request_btn:
                tap(*request_btn)
                time.sleep(0.1)
                tap(*fp.HOME_SEND_TROOP_REQUEST)
                time.sleep(0.2)
            else:
                print('[CLAN GAME]Request button not found')
                return None
        sent_name = self._clean_template_name(self.cached_cg_super or '')
        print(f'[CLAN GAME]Troop request sent: {sent_name}')
        return None

    def _get_edit_template(self, template_key):
        key = template_key
        if not key:
            return None
        for source in (getattr(self.vision, 'army_edit_templates', {}),
                       getattr(self.vision, 'templates', {}),
                       getattr(self.vision, 'cc_request_templates', {})):
            tpl = source.get(key)
            if tpl:
                return tpl
        return None

    def _find_best_edit_match(self, screen, region, template_key):
        img = screen
        if img is None:
            img = self.vision.grab()
        x1, y1, x2, y2 = region
        roi = img[y1:y2, x1:x2]
        if roi.size == 0:
            return None
        tpl_entry = self._get_edit_template(template_key)
        if not tpl_entry:
            return None
        tpl_img = tpl_entry['img']
        if len(tpl_img.shape) == 3 and len(roi.shape) == 3:
            roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            tpl_gray = cv2.cvtColor(tpl_img, cv2.COLOR_BGR2GRAY)
        elif len(tpl_img.shape) == 2 and len(roi.shape) == 3:
            roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            tpl_gray = tpl_img
        else:
            roi_gray = roi
            tpl_gray = tpl_img
        rh, rw = roi_gray.shape[:2]
        th, tw = tpl_gray.shape[:2]
        if rh < th or rw < tw:
            return None
        result = cv2.matchTemplate(roi_gray, tpl_gray, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        left = x1 + max_loc[0]
        top = y1 + max_loc[1]
        right = left + tw
        bottom = top + th
        center = (left + tw // 2, top + th // 2)
        return {'score': float(max_val), 'top_left': (left, top),
                'bottom_right': (right, bottom), 'center': center}

    def _match_edit_region_with_reason(self, region, template_key, threshold, screen=None):
        key = template_key
        img = screen
        x1, y1, x2, y2 = region
        if img is None:
            img = self.vision.grab()
        roi = img[y1:y2, x1:x2]
        if roi.size == 0:
            return {'accepted': False, 'pos': None, 'score': None, 'reason': 'roi_empty', 'source': None}
        source = 'templates'
        tpl_entry = self.vision.templates.get(key)
        if not tpl_entry:
            source = 'cc_request_templates'
            tpl_entry = self.vision.cc_request_templates.get(key)
        if not tpl_entry:
            return {'accepted': False, 'pos': None, 'score': None,
                    'reason': 'template_missing_in_matcher_pool', 'source': None}
        tpl_img = tpl_entry['img']
        if len(tpl_img.shape) == 3 and len(roi.shape) == 3:
            roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            tpl_gray = cv2.cvtColor(tpl_img, cv2.COLOR_BGR2GRAY)
        elif len(tpl_img.shape) == 2 and len(roi.shape) == 3:
            roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            tpl_gray = tpl_img
        else:
            roi_gray = roi
            tpl_gray = tpl_img
        rh, rw = roi_gray.shape[:2]
        th, tw = tpl_gray.shape[:2]
        if rh < th or rw < tw:
            return {'accepted': False, 'pos': None, 'score': None,
                    'reason': 'roi_smaller_than_template', 'source': source}
        result = cv2.matchTemplate(roi_gray, tpl_gray, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        score = float(max_val)
        if score < threshold:
            return {'accepted': False, 'pos': None, 'score': score,
                    'reason': 'score_below_threshold', 'source': source}
        cx = x1 + max_loc[0] + tpl_entry['w'] // 2
        cy = y1 + max_loc[1] + tpl_entry['h'] // 2
        return {'accepted': True, 'pos': (cx, cy), 'score': score, 'reason': 'accepted', 'source': source}

    def _save_edit_check_debug_snapshot(self, pass_name, template_key, region, threshold,
                                        screen, accepted_pos, match_meta=None):
        # Only active when CG_EDIT_VISUAL_DEBUG is True (it is False in this build).
        if not CG_EDIT_VISUAL_DEBUG:
            return None
        img = screen
        if img is None:
            img = self.vision.grab()
        best = self._find_best_edit_match(img, region, template_key)
        canvas = img.copy()
        x1, y1, x2, y2 = region
        cv2.rectangle(canvas, (x1, y1), (x2, y2), (255, 180, 0), 2)
        if best:
            cv2.rectangle(canvas, best['top_left'], best['bottom_right'], (0, 165, 255), 2)
            cv2.circle(canvas, best['center'], 6, (0, 165, 255), -1)
        if accepted_pos:
            cv2.circle(canvas, accepted_pos, 8, (0, 255, 0), 2)
        best_score = f"{best['score']:.3f}" if best else 'n/a'
        accepted_txt = 'yes' if accepted_pos else 'no'
        matcher_score = None
        matcher_reason = 'unknown'
        matcher_source = 'unknown'
        if match_meta:
            matcher_score = match_meta.get('score')
            matcher_reason = match_meta.get('reason', 'unknown')
            matcher_source = match_meta.get('source', 'unknown')
        lines = [
            f'pass={pass_name}',
            f'template={template_key}',
            f'threshold={threshold:.2f}',
            f'best_score={best_score}',
            f'accepted={accepted_txt}',
            f"matcher_score={('n/a' if matcher_score is None else f'{matcher_score:.3f}')}",
            f'matcher_source={matcher_source}',
            f'matcher_reason={matcher_reason}',
        ]
        y = 30
        for line in lines:
            cv2.putText(canvas, line, (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
            y += 28
        os.makedirs(resolve_writable_path(CG_EDIT_VISUAL_DEBUG_DIR), exist_ok=True)
        ts = int(time.time() * 1000)
        safe_key = re.sub('[^a-zA-Z0-9_-]', '_', str(template_key or 'unknown'))
        filename = f'cg_edit_{ts}_{pass_name}_{safe_key}.png'
        path = os.path.join(resolve_writable_path(CG_EDIT_VISUAL_DEBUG_DIR), filename)
        ok, buf = cv2.imencode('.png', canvas)
        if ok:
            with open(path, 'wb') as f:
                f.write(buf.tobytes())
            if CG_DEBUG:
                print(f'[CLAN GAME]Saved edit debug snapshot: {path}')
                return None
            return None
        return None

    def _edit_slot_filled(self, point):
        img = self.vision.grab()
        x, y = point
        crop = img[max(0, y - 12):y + 12, max(0, x - 12):x + 12]
        if crop.size == 0:
            return False
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        return float(hsv[:, :, 2].mean()) > 100 or float(crop.std()) > 30

    def _tap_remove(self, point, times):
        pt = point
        for _ in range(times):
            if not self._edit_slot_filled(pt):
                return None
            self._record_removal(pt)  # FIX: slot-8 restore bookkeeping
            tap(*pt)
            time.sleep(0.15)
        return None

    @staticmethod
    def _edit_tile_unlocked(screen, pos):
        # Looks for bright, unsaturated (white) text under the tile => unlocked.
        import numpy
        x, y = pos
        crop = screen[y + 38:y + 66, max(0, x - 28):x + 28]
        if crop.size == 0:
            return True
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        mask = (hsv[:, :, 2] > 225) & (hsv[:, :, 1] < 50)
        return float(numpy.mean(mask)) > 0.02

    def _current_profile(self):
        import main
        profiles = getattr(main, 'active_profiles', None) or []
        idx = getattr(main, 'current_profile_index', -1)
        if self.active_config.get('MULTI_VILLAGE_ENABLED', False):
            if 0 <= idx < len(profiles):
                return profiles[idx]
            return None
        return None

    def _disable_challenge(self, challenge_key):
        # Persistently add a challenge (and, for spells, every cgspell_<n>_<spell>
        # variant) to CG_DISABLED_CHALLENGES in the profile config.
        key = challenge_key
        if key.startswith('cgspell_'):
            spell = key.split('_', 2)[-1]
            keys = {k for k in self.vision.cg_templates if re.fullmatch(f'cgspell_\\d+_{re.escape(spell)}', k)}
        else:
            keys = set()
        keys.add(key)
        from profiles.config_manager import ConfigManager
        profile = self._current_profile()
        manager = ConfigManager()
        config = manager.load(profile)
        disabled = config.get('CG_DISABLED_CHALLENGES', [])
        if isinstance(disabled, str):
            disabled = [item.strip() for item in disabled.split(',') if item.strip()]
        merged = sorted(set(disabled) | keys)
        config['CG_DISABLED_CHALLENGES'] = merged
        manager.save(config, profile)
        self.active_config['CG_DISABLED_CHALLENGES'] = merged
        self._cg_filter_signature = None
        print(f"[CLAN GAME]Disabled {', '.join((self._clean_template_name(k) for k in sorted(keys)))} challenges for {profile or 'this village'}")

    def _apply_spell_removals(self, strategy_name, spell_count):
        strategy = strategy_name
        count = spell_count
        if count <= 0:
            return True
        if strategy in ('edragon', 'dragon'):
            if count >= 3:
                self._tap_remove(fp.EDIT_ARMY_SPELL_REMOVE1, 1)
                self._tap_remove(fp.EDIT_ARMY_SPELL_REMOVE2, 1)
                return True
            self._tap_remove(fp.EDIT_ARMY_SPELL_REMOVE1, count)
            return True
        if strategy in ('valkyrie', 'sminion', 'sbarb', 'thrower'):
            self._tap_remove(fp.EDIT_ARMY_SPELL_REMOVE1, count)
            return True
        return False

    def reset_army_slot(self, adb, active_config):
        adb_dev = adb
        try:
            print('[CLAN GAME]Resetting army to base configuration')
            slot = active_config.get('SELECTED_ARMY_SLOT', 0)
            # FIX: the original opened the "Saved Recipes" dropdown first and returned for slot 8 with
            # it still open; the next tap (troop row) then hit a recipe ("Use Army Recipe?" dialog)
            # and the CG troop search failed. Slot 8 = current army, so never open the dropdown.
            if int(slot or 0) == 8:
                print('[CLAN GAME]Current Army selected, skipping saved slot reset')
                return True
            dropdown = self.vision.find_army_dropdown()
            if dropdown:
                click_point(adb_dev, dropdown)
                time.sleep(0.3)
            bars = self.vision.find_army_bars()
            if not bars:
                print('[CLAN GAME]Army bars not found for reset')
                if dropdown:  # FIX: don't leave the dropdown open over the army screen
                    click_point(adb_dev, dropdown)
                    time.sleep(0.3)
                return False
            if slot < len(bars):
                click_point(adb_dev, bars[slot])
                time.sleep(0.5)
            okay1 = self.vision.find_okay_button()
            if okay1:
                click_point(adb_dev, okay1)
                time.sleep(0.5)
            okay2 = self.vision.find_okay_button()
            if okay2:
                click_point(adb_dev, okay2)
                time.sleep(0.5)
            return True
        except Exception as e:
            print(f'[CLAN GAME]Error resetting army: {e}')
            return False

    def has_pending_non_exempt_edit(self, active_config):
        challenge = self.cached_cg_edit_challenge
        if not challenge:
            return False
        if not challenge.startswith('cgarmy_') and not challenge.startswith('cgspell_'):
            return False
        strategy = str(active_config.get('SELECTED_ATTACK_STRATEGY', '')).strip().lower()
        return challenge not in self.CG_EDIT_EXEMPTED_CHALLENGES.get(strategy, [])

    def _search_edit_picker(self, template_key, match_threshold):
        # Scroll through the army-edit picker looking for the template; stops when
        # the picker stops moving (mean abs frame diff < 2.0) or the template matches.
        threshold = match_threshold
        key = template_key
        found_pos = None
        last_meta = None
        import numpy
        x1, y1, x2, y2 = fp.EDIT_ARMY_REGION
        prev_screen = None
        for step in range(int(fp.EDIT_ARMY_SEARCH_MAX_SWIPES) + 1):
            if step:
                swipe(*fp.EDIT_ARMY_TROOP_STEP_SWIPE)
                time.sleep(CG_EDIT_SCROLL_SETTLE_SECONDS)
            screen = self.vision.grab()
            if prev_screen is not None:
                diff = numpy.abs(screen[y1:y2, x1:x2].astype(numpy.int16)
                                 - prev_screen[y1:y2, x1:x2].astype(numpy.int16)).mean()
                if diff < 2.0:
                    break
            prev_screen = screen
            meta = self._match_edit_region_with_reason(fp.EDIT_ARMY_REGION, key, threshold, screen=screen)
            found_pos = meta['pos'] if meta['accepted'] else None
            last_meta = meta
            self._save_edit_check_debug_snapshot(
                f'check_{step + 1}' + ('_swipe' if step else '_start'),
                key, fp.EDIT_ARMY_REGION, threshold, screen, found_pos, match_meta=meta)
            if found_pos:
                break
        return (found_pos, last_meta)

    def apply_cg_edit_if_needed(self, adb, active_config):
        # Temporarily edits the army (Army -> Edit) so that it contains the troop or
        # spell demanded by the active "cgarmy_*" / "cgspell_<n>_<name>" challenge.
        cfg = active_config
        challenge = self.cached_cg_edit_challenge
        if not challenge:
            return False
        is_troop = challenge.startswith('cgarmy_')
        is_spell = challenge.startswith('cgspell_')
        if not is_troop and not is_spell:
            return False
        strategy = str(cfg.get('SELECTED_ATTACK_STRATEGY', '')).strip().lower()
        if challenge in self.CG_EDIT_EXEMPTED_CHALLENGES.get(strategy, []):
            if CG_DEBUG:
                pretty = self._clean_template_name(challenge)
                print(f'[CLAN GAME]Skipping {pretty} edit - {strategy} already uses it')
            return False
        if self.cg_army_temp_active:
            return True
        if not self.reset_army_slot(adb, cfg):
            print('[CLAN GAME]Failed to reset army before edit')
            return False
        time.sleep(0.5)
        # Number of troop units to remove from the strategy's army to free space
        troop_removals = {'edragon': 1, 'dragon': 2, 'valkyrie': 4, 'sminion': 3, 'sbarb': 6, 'thrower': 2}.get(strategy)
        if troop_removals is None:
            print('[CLAN GAME]Challenge skipped — unsupported')
            return False
        picker_key = None
        removed_any = False
        self._edit_log = {}  # FIX: record removals for the slot-8 restore
        if is_troop:
            tap(*fp.EDIT_ARMY_TROOP)
            time.sleep(0.4)
            self._tap_remove(fp.EDIT_ARMY_TROOP_REMOVE1, troop_removals)
            time.sleep(CG_EDIT_POST_REMOVE_SETTLE_SECONDS)
            removed_any = True
            picker_key = challenge.replace('cgarmy_', 'edit_army_', 1)
        else:
            parts = challenge.split('_', 2)
            spell_count = 0
            spell_name = ''
            if len(parts) >= 3:
                try:
                    spell_count = int(parts[1])
                except ValueError:
                    spell_count = 0
                spell_name = parts[2].strip()
            if spell_count <= 0 or not spell_name:
                pretty = self._clean_template_name(challenge)  # RECON: computed but unused
                print('[CLAN GAME]Invalid challenge format, skipping')
                return False
            tap(*fp.EDIT_ARMY_SPELL)
            time.sleep(0.4)
            if not self._apply_spell_removals(strategy, spell_count):
                print('[CLAN GAME]Challenge skipped — unsupported')
                return False
            removed_any = spell_count > 0
            picker_key = f'edit_armyspell_{spell_name}'
        found_pos = None
        meta = None
        threshold = 0.8
        found_pos, meta = self._search_edit_picker(picker_key, threshold)
        if not found_pos:
            if meta:
                score = meta.get('score')
                score_txt = 'n/a' if score is None else f'{score:.3f}'
                print(f"[CLAN GAME]Troop not found in editor, skipping (reason={meta.get('reason')} source={meta.get('source')} score={score_txt} threshold={threshold:.2f})")
            else:
                print('[CLAN GAME]Troop not found in editor, skipping')
            if removed_any:
                self.cg_army_restore_pending = True
                self.cached_cg_edit_challenge = None
            self._finish_edit_record(None, is_spell, cfg)  # FIX: undo the removals later
            tap(*fp.EDIT_ARMY_DONE)
            time.sleep(0.3)
            return False
        import numpy
        screen = self.vision.grab()
        px, py = found_pos
        x1 = max(0, px - 10)
        y1 = max(0, py - 10)
        x2 = min(screen.shape[1], px + 10)
        y2 = min(screen.shape[0], py + 10)
        tile = screen[y1:y2, x1:x2]
        if tile.size > 0:
            hsv = cv2.cvtColor(tile, cv2.COLOR_BGR2HSV)
            # Low saturation => greyed-out tile (no housing space or locked)
            sat = float(hsv[:, :, 1].mean())
            kind = 'Spell' if is_spell else 'Troop'
            pretty = self._clean_template_name(challenge).replace('_', ' ').title()
            if sat < 8 and self._edit_tile_unlocked(screen, found_pos):
                # Unlocked but greyed out: remove extra units to make room
                remove_pt = fp.EDIT_ARMY_SPELL_REMOVE1 if is_spell else fp.EDIT_ARMY_TROOP_REMOVE1
                for _ in range(CG_EDIT_EXTRA_REMOVALS):
                    if not self._edit_slot_filled(remove_pt):
                        break
                    self._record_removal(remove_pt)  # FIX: slot-8 restore bookkeeping
                    tap(*remove_pt)
                    time.sleep(0.3)
                    removed_any = True
                    screen = self.vision.grab()
                    tile2 = screen[y1:y2, x1:x2]
                    sat = float(cv2.cvtColor(tile2, cv2.COLOR_BGR2HSV)[:, :, 1].mean())
                    if sat >= 8:
                        print(f'[CLAN GAME]Removed extra units to fit {pretty}')
                        break
            if sat < 8:
                if self._edit_tile_unlocked(screen, found_pos):
                    print(f"[CLAN GAME]{kind} {pretty} still doesn't fit after removing more units")
                else:
                    print(f'[CLAN GAME]{kind} {pretty} not unlocked')
                    self._disable_challenge(challenge)
                self.cg_edit_challenge_unavailable = True
                if removed_any:
                    self.cg_army_restore_pending = True
                    self.cached_cg_edit_challenge = None
                self._finish_edit_record(None, is_spell, cfg)  # FIX: undo the removals later
                tap(*fp.EDIT_ARMY_DONE)
                time.sleep(0.3)
                return False
        tap(*found_pos)
        time.sleep(0.15)
        self._finish_edit_record(picker_key, is_spell, cfg)  # FIX: undo after the challenge attack
        tap(*fp.EDIT_ARMY_DONE)
        time.sleep(0.4)
        self.cg_army_temp_active = True
        print('[CLAN GAME]Army adjusted for challenge')
        return True

    def mark_cg_army_attack_completed(self):
        if self.cg_army_temp_active:
            self.cg_army_temp_active = False
            self.cg_army_restore_pending = True
            self.cached_cg_edit_challenge = None
            print('[CLAN GAME]Army Challenge completed')
            return None
        return None

    def consume_cg_army_restore_pending(self):
        if not self.cg_army_restore_pending:
            return False
        self.cg_army_restore_pending = False
        return True
