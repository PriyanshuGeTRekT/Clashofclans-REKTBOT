# ACBot Basic v1.6.7 - vision: OpenCV template matching, digit recognition, screen-state detection.
# Reconstructed from Pyarmor-decrypted bytecode (vision, Python 3.10).
#
# Notes on naming:
#   * The original source was passed through a minifier before Pyarmor: the `self` parameter of
#     each method (and some nested helpers / closure cells) carry single-letter names (A, B, C, ...).
#     Those argument/function names are real and are preserved verbatim.
#   * Local variables were obfuscated by Pyarmor (_var_var_N) and have been renamed by usage.
#   * No OCR engine (Tesseract etc.) is used anywhere: all digits are read by matching binarised
#     glyph crops against PNG digit templates (templates/digits/ui, templates/digits/battle).
import time
import cv2
import adb
import numpy as np
import os
from pathlib import Path
import fixed_points as fp
import defaults
from utils.runtime_paths import resolve_resource_path, app_root, bundle_root
from fixed_points import crop

VISION_DEBUG = False
ATTACK_DEBUG = False
ARMY_DEBUG = False
THZONE_DEBUG = False


class Vision:

    # ------------------------------------------------------------------ template loading

    @staticmethod
    def _imread_unicode_safe(path, mode):
        data = np.fromfile(str(path), dtype=np.uint8)
        if data.size == 0:
            return None
        return cv2.imdecode(data, mode)

    def _template_path(D, sub_path=''):
        sub = sub_path
        base = Path(defaults.TEMPLATES_DIR)
        if base.is_absolute():
            return base / sub if sub else base
        rel = base / sub if sub else base
        return resolve_resource_path(str(rel))

    def _template_scan_roots(E):
        """Template roots: [<bundle>/templates, <app>/templates] (external app folder overrides/extends)."""
        base = Path(defaults.TEMPLATES_DIR)
        if base.is_absolute():
            return [base]
        roots = []
        bundle_dir = bundle_root() / base
        app_dir = app_root() / base
        if bundle_dir.exists():
            roots.append(bundle_dir)
        if app_dir.exists() and app_dir != bundle_dir:
            roots.append(app_dir)
        if not roots:
            roots.append(resolve_resource_path(str(base)))
        return roots

    def load_digit_templates(A):
        A.DIGIT_UI = {}
        A.DIGIT_BATTLE = {}
        for folder, target in ((A._template_path('digits/ui'), A.DIGIT_UI),
                               (A._template_path('digits/battle'), A.DIGIT_BATTLE)):
            for png in Path(folder).glob('*.png'):
                digit = png.stem[0]          # first char of file name is the digit label
                img = A._imread_unicode_safe(png, cv2.IMREAD_GRAYSCALE)
                if img is None:
                    continue
                _, img = cv2.threshold(img, 180, 255, cv2.THRESH_BINARY)
                target.setdefault(digit, []).append(img)
        if VISION_DEBUG:
            print('[VISION] UI digits:', {k: len(v) for k, v in A.DIGIT_UI.items()})
            print('[VISION] Battle digits:', {k: len(v) for k, v in A.DIGIT_BATTLE.items()})

    def load_all_templates(C, root=None):
        templates = {}
        roots = [Path(root)] if root is not None else C._template_scan_roots()
        for root_dir in roots:
            for p in Path(root_dir).rglob('*.png'):
                if any(part in str(p) for part in ('digits', 'tabs', 'townhall', 'walls', 'cc_requests')):
                    continue
                key = p.stem.lower()
                tpl = C.load_template(str(p), cv2.IMREAD_GRAYSCALE)
                if tpl is None:
                    print('Failed to load:', p)
                    continue
                templates[key] = tpl     # later roots (app dir) override earlier (bundle) by stem
        if VISION_DEBUG:
            print(f'[VISION] Loaded {len(templates)} templates')
        return templates

    def _load_template_group(B, subdir, mode=cv2.IMREAD_COLOR):
        group = {}
        for root_dir in B._template_scan_roots():
            folder = root_dir / subdir
            if not (folder.exists() and folder.is_dir()):
                continue
            for p in folder.glob('*.png'):
                key = p.stem.lower()
                group[key] = B.load_template(str(p), mode)
        return group

    def __init__(A):
        A.last_th_pos = None
        A.DIGIT_UI = {}
        A.DIGIT_BATTLE = {}
        A.load_digit_templates()
        A.templates = A.load_all_templates()
        A.tab_templates = A._load_template_group('tabs', cv2.IMREAD_COLOR)
        A.th_templates = A._load_template_group('townhall', cv2.IMREAD_COLOR)
        A.wall_level_templates = A._load_template_group('walls', cv2.IMREAD_COLOR)
        A.cc_request_templates = A._load_template_group('cc_requests', cv2.IMREAD_COLOR)
        A.cg_templates = {}
        A.cg_ui_templates = {}
        A.cg_super_templates = {}
        A.army_edit_templates = A._load_template_group('army_edit', cv2.IMREAD_COLOR)
        for root_dir in A._template_scan_roots():
            cg_dir = root_dir / 'clangames'
            if not (cg_dir.exists() and cg_dir.is_dir()):
                continue
            for p in cg_dir.glob('*.png'):
                key = p.stem.lower()
                tpl = A.load_template(str(p), cv2.IMREAD_COLOR)
                if key.startswith('cgsuper_'):
                    A.cg_super_templates[key] = tpl
                elif key.startswith('cg_') or key.startswith('cgarmy_') or key.startswith('cgspell_'):
                    A.cg_templates[key] = tpl
                elif key.startswith('ui_'):
                    A.cg_ui_templates[key] = tpl
        if VISION_DEBUG:
            print(f'[VISION] Clan Games loaded{len(A.cg_templates)} challenges, '
                  f'{len(A.cg_ui_templates)} ui, {len(A.cg_super_templates)} super')
        A.TH_ALLOWED_POLY = np.array(fp.TH_ZONE_POLY, dtype=np.int32)
        A.tab_matches = {}
        A.tab_scores = {}
        A.use_smallest_troop_bar_size = False
        A._tab_scale_locked = False

    def apply_runtime_config(A, config):
        pass

    # ------------------------------------------------------------------ troop bar (attack tabs)

    def _detect_tabs_for_scale(Z, roi, search_region, tab_scale):
        region = search_region
        scale = tab_scale
        found = {}
        matches = {}
        scores = {}
        for name, tpl in Z.tab_templates.items():
            img = tpl['img']
            w = int(tpl['w'])
            h = int(tpl['h'])
            if scale != 1.0:
                scaled = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                if scaled is None or scaled.size == 0:
                    continue
                img = scaled
                h, w = img.shape[:2]
            if name.startswith('hero_'):
                thr = 0.8
            elif name.startswith('spell_'):
                thr = 0.8
            elif name.startswith('troop_'):
                thr = 0.9
            elif name.startswith('siege_'):
                thr = 0.7
            else:
                thr = 0.75
            res = cv2.matchTemplate(roi, img, cv2.TM_CCOEFF_NORMED)
            if name.startswith('spell_'):
                # Spells may occupy up to two slots: collect up to 2 separated peaks.
                _, max_val, _, _ = cv2.minMaxLoc(res)
                if max_val < thr:
                    continue
                multi_thr = max(0.88, max_val - 0.05)
                ys, xs = np.where(res >= multi_thr)
                candidates = []
                for x, y in zip(xs, ys):
                    score = float(res[y, x])
                    cx = x + w // 2                      # NB: x not offset by region[0] (as in original)
                    cy = region[1] + y + h // 2
                    candidates.append((score, cx, cy))
                candidates.sort(key=lambda item: item[0], reverse=True)
                min_dist = int(max(w, h) * 0.6)
                picked = []
                for score, cx, cy in candidates:
                    if any(abs(cx - px) < min_dist and abs(cy - py) < min_dist for _, px, py in picked):
                        continue
                    picked.append((score, cx, cy))
                    if len(picked) >= 2:
                        break
                if picked:
                    found[name] = (picked[0][1], picked[0][2])
                    matches[name] = [(px, py) for _, px, py in picked]
                    scores[name] = float(picked[0][0])
                    if ATTACK_DEBUG:
                        print(f'[VISION] Tab {name} found x{len(picked)} (best={picked[0][0]:.2f})')
                continue
            method = cv2.TM_CCORR_NORMED if name.startswith('siege_') else cv2.TM_CCOEFF_NORMED
            result = cv2.matchTemplate(roi, img, method) if name.startswith('siege_') else res
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            if max_val >= thr:
                cx = max_loc[0] + w // 2
                cy = region[1] + max_loc[1] + h // 2
                found[name] = (cx, cy)
                matches[name] = [(cx, cy)]
                scores[name] = float(max_val)
                if ATTACK_DEBUG:
                    print(f'[VISION] Tab {name} found ({max_val:.2f})')
        return found, matches, scores

    def detect_tabs(A):
        screen = A.grab()
        _h, _w, _c = screen.shape
        region = fp.TROOP_BAR_REGION
        roi = crop(screen, region)
        if ATTACK_DEBUG:
            cv2.imwrite('DEBUG_TABS_ROI.png', roi)
        if not A._tab_scale_locked:
            # First call: try 100% and 80% template scale, lock whichever detects more (or scores higher).
            found_100, matches_100, scores_100 = A._detect_tabs_for_scale(roi, region, 1.0)
            found_80, matches_80, scores_80 = A._detect_tabs_for_scale(roi, region, 0.8)
            n_100 = len(found_100)
            n_80 = len(found_80)
            sum_100 = float(sum(scores_100.values())) if scores_100 else 0.0
            sum_80 = float(sum(scores_80.values())) if scores_80 else 0.0
            use_small = n_80 > n_100 or (n_80 == n_100 and sum_80 > sum_100)
            A.use_smallest_troop_bar_size = use_small
            A._tab_scale_locked = True
            label = '80%' if use_small else '100%'
            print(f'[VISION] Troop bar scale : {label}')
            if use_small:
                A.tab_matches = matches_80
                A.tab_scores = scores_80
                return found_80
            A.tab_matches = matches_100
            A.tab_scores = scores_100
            return found_100
        scale = 0.8 if A.use_smallest_troop_bar_size else 1.0
        found, matches, scores = A._detect_tabs_for_scale(roi, region, scale)
        A.tab_matches = matches
        A.tab_scores = scores
        return found

    # ------------------------------------------------------------------ capture / generic matching

    def grab(A):
        return adb.screenshot()

    def grab_full(A):
        return adb.screenshot()

    def load_template(B, path, mode=cv2.IMREAD_GRAYSCALE):
        img = B._imread_unicode_safe(path, mode)
        if img is None:
            raise RuntimeError(f'Could not load {path}')
        h, w = img.shape[:2]
        return {'img': img, 'w': w, 'h': h}

    def match_any_template(E, roi_gray, template_keys, threshold=0.9):
        for key in template_keys:
            tpl = E.templates.get(key)
            if not tpl:
                continue
            res = cv2.matchTemplate(roi_gray, tpl['img'], cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(res)
            if VISION_DEBUG:
                print(f'[VISION] {key} match score: {max_val:.3f}')
            if max_val >= threshold:
                return True, key
        return False, None

    def match_template_region(E, region, template_key, threshold=0.85):
        box = region
        key = template_key
        x1, y1, x2, y2 = box
        screen = E.grab()
        roi = screen[y1:y2, x1:x2]
        if roi.size == 0:
            return None
        tpl = E.templates.get(key)
        if not tpl:
            tpl = E.cc_request_templates.get(key)
        if not tpl:
            return None
        tpl_img = tpl['img']
        if roi.shape[0] < tpl_img.shape[0] or roi.shape[1] < tpl_img.shape[1]:
            if VISION_DEBUG:
                print(f'[VISION] {key} larger than region {box}, skipping')
            return None
        if len(tpl_img.shape) == 3 and len(roi.shape) == 3:
            roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            tpl_gray = cv2.cvtColor(tpl_img, cv2.COLOR_BGR2GRAY)
            res = cv2.matchTemplate(roi_gray, tpl_gray, cv2.TM_CCOEFF_NORMED)
        elif len(tpl_img.shape) == 2 and len(roi.shape) == 3:
            roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            res = cv2.matchTemplate(roi_gray, tpl_img, cv2.TM_CCOEFF_NORMED)
        else:
            res = cv2.matchTemplate(roi, tpl_img, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if VISION_DEBUG:
            print(f'[VISION] {key} region score: {max_val:.3f}')
        if max_val < threshold:
            return None
        cx = x1 + max_loc[0] + tpl['w'] // 2
        cy = y1 + max_loc[1] + tpl['h'] // 2
        return cx, cy

    def match_template_region_multiscale(D, region, template_key, threshold=0.85, scales=None):
        key = template_key
        scale_list = scales
        if scale_list is None:
            scale_list = [round(i * 0.1, 1) for i in range(5, 11)]   # 0.5 .. 1.0
        x1, y1, x2, y2 = region
        screen = D.grab()
        roi = screen[y1:y2, x1:x2]
        if roi.size == 0:
            return None
        tpl = D.templates.get(key)
        if not tpl:
            tpl = D.cc_request_templates.get(key)
        if not tpl:
            return None
        tpl_img = tpl['img']
        if len(tpl_img.shape) == 3:
            tpl_gray = cv2.cvtColor(tpl_img, cv2.COLOR_BGR2GRAY)
        else:
            tpl_gray = tpl_img
        roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if len(roi.shape) == 3 else roi
        roi_h, roi_w = roi_gray.shape[:2]
        best_val = -1
        best_loc = None
        best_w = 0
        best_h = 0
        for s in scale_list:
            th, tw = tpl_gray.shape[:2]
            sw = max(1, int(tw * s))
            sh = max(1, int(th * s))
            if sh > roi_h or sw > roi_w:
                continue
            scaled = cv2.resize(tpl_gray, (sw, sh), interpolation=cv2.INTER_AREA)
            res = cv2.matchTemplate(roi_gray, scaled, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            if max_val > best_val:
                best_val = max_val
                best_loc = max_loc
                best_w = sw
                best_h = sh
        if best_val < threshold or best_loc is None:
            return None
        cx = x1 + best_loc[0] + best_w // 2
        cy = y1 + best_loc[1] + best_h // 2
        return cx, cy

    def find_all_templates(B, key, threshold=0.85):
        if key not in B.templates:
            return []
        screen = B.grab()
        gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        tpl_img = B.templates[key]['img']
        h, w = tpl_img.shape[:2]
        res = cv2.matchTemplate(gray, tpl_img, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(res >= threshold)
        points = list(zip(xs, ys))
        results = []
        for x, y in points:
            cx = x + w // 2
            cy = y + h // 2
            duplicate = False
            for ex, ey, ew, eh in results:
                ecx = ex + ew // 2
                ecy = ey + eh // 2
                if abs(cx - ecx) < w * 0.6 and abs(cy - ecy) < h * 0.6:
                    duplicate = True
                    break
            if not duplicate:
                results.append((x, y, w, h))
        results.sort(key=lambda b: b[1])
        return results

    # ------------------------------------------------------------------ army / home screen

    def find_army_bars(D):
        screen = D.grab()
        _h, _w, _c = screen.shape
        region = (665, 127, 1268, 894)
        roi = crop(screen, region)
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        tpl_img = D.templates['army_bar']['img']
        th = D.templates['army_bar']['h']
        tw = D.templates['army_bar']['w']
        res = cv2.matchTemplate(gray, tpl_img, cv2.TM_CCOEFF_NORMED)
        thr = 0.9
        hits = []
        for y in range(res.shape[0]):
            for x in range(res.shape[1]):
                score = res[y, x]
                if score >= thr:
                    cx = region[0] + x + tw // 2
                    cy = region[1] + y + th // 2
                    hits.append((cx, cy, score))
        hits.sort(key=lambda m: m[1])
        slots = []
        min_gap = th
        for x, y, score in hits:
            if not slots or abs(y - slots[-1][1]) > min_gap:
                slots.append((x, y))
        if ARMY_DEBUG:
            for i, (x, y) in enumerate(slots):
                print(f'[VISION] Slot {i} at y={y}')
                cv2.circle(screen, (x, y), 8, (0, 255, 0), -1)
            cv2.imwrite('debug_army_bars_clicks.png', screen)
            print(f'[VISION] Found {len(slots)} army bars')
        return slots

    def find_army_button(C):
        screen = C.grab()
        _h, _w, _c = screen.shape
        region = fp.HOME_BUTTONS_LEFT_REGION
        roi = crop(screen, region)
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        tpl = C.templates['army_button']
        res = cv2.matchTemplate(gray, tpl['img'], cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if ARMY_DEBUG:
            print(f'[VISION] Army button match score: {max_val:.3f}')
        if max_val >= 0.9:
            cx = region[0] + max_loc[0] + tpl['w'] // 2
            cy = region[1] + max_loc[1] + tpl['h'] // 2
            return cx, cy
        return None

    def find_army_dropdown(C):
        screen = C.grab()
        h, w, _c = screen.shape
        region = (int(w * 0.25), 0, int(w * 0.75), int(h * 0.5))
        roi = crop(screen, region)
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        tpl = C.templates['army_dropdown']
        res = cv2.matchTemplate(gray, tpl['img'], cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if ARMY_DEBUG:
            print(f'[VISION] Army dropdown match score: {max_val:.3f}')
        if max_val >= 0.9:
            cx = region[0] + max_loc[0] + tpl['w'] // 2
            cy = region[1] + max_loc[1] + tpl['h'] // 2
            return cx, cy
        return None

    def is_home_village(A):
        screen = A.grab()
        h, w, _c = screen.shape
        region = (int(w * 0.5), int(h * 0.5), w, h)       # bottom-right quadrant
        roi = crop(screen, region)
        if VISION_DEBUG:
            cv2.imwrite('debug_home_roi.png', roi)
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        matched, key = A.match_any_template(gray, template_keys=['magic_items'], threshold=0.9)
        if matched:
            if VISION_DEBUG:
                print(f'[VISION] HOME VILLAGE DETECTED via {key} ✅')
            return True
        if VISION_DEBUG:
            print('[VISION] NOT home village ❌')
        return False

    def is_in_battle(A):
        screen = A.grab()
        h, w, _c = screen.shape
        x1, y1, x2, y2 = (6, 502, 217, 749)
        region = (max(0, min(x1, w - 1)), max(0, min(y1, h - 1)),
                  max(1, min(x2, w)), max(1, min(y2, h)))
        roi = crop(screen, region)
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        matched, key = A.match_any_template(
            gray, template_keys=['end_battle', 'end_battle0.8', 'surrender_battle'], threshold=0.9)
        if ATTACK_DEBUG and matched:
            print(f'[VISION] Battle detected via {key}')
        return matched

    def is_battle_end(E):
        screen = E.grab()
        h, w, _c = screen.shape
        region = (int(w * 0.35), int(h * 0.6), int(w * 0.65), h)
        roi = crop(screen, region)
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        if ATTACK_DEBUG:
            cv2.imwrite('debug_battle_end_roi.png', roi)
        debug_img = screen.copy()
        for key in ('return_home', 'claim_reward', 'card_claim'):
            tpl = E.templates[key]
            res = cv2.matchTemplate(gray, tpl['img'], cv2.TM_CCOEFF_NORMED)
            _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(res)
            if ATTACK_DEBUG:
                print(f'[VISION] {key} score: {max_val:.3f}')
                bx = region[0] + max_loc[0]
                by = region[1] + max_loc[1]
                th, tw = tpl['img'].shape[:2]
                cv2.rectangle(debug_img, (bx, by), (bx + tw, by + th), (0, 0, 255), 2)
            if max_val >= 0.85:
                if ATTACK_DEBUG:
                    cv2.imwrite(f'debug_battle_end_{key}_MATCH.png', debug_img)
                return True
        if ATTACK_DEBUG:
            cv2.imwrite('debug_battle_end_NO_MATCH.png', debug_img)
        return False

    def find_okay_button(B):
        screen = B.grab()
        gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        tpl = B.templates['okay_button']
        res = cv2.matchTemplate(gray, tpl['img'], cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if ARMY_DEBUG:
            print(f'[VISION] CC button score: {max_val:.3f}')
        if max_val >= 0.9:
            cx = max_loc[0] + tpl['w'] // 2
            cy = max_loc[1] + tpl['h'] // 2
            return cx, cy
        return None

    def find_wall_upgrade(O, full_screen=False):
        screen = O.grab()
        gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        x1, y1, x2, y2 = fp.UPGRADE_LIST_REGION
        roi = gray[y1:y2, x1:x2]
        tpl = O.templates['wall_upgrade']
        res = cv2.matchTemplate(roi, tpl['img'], cv2.TM_CCOEFF_NORMED)
        thr = 0.9
        mask = (res >= thr).astype(np.uint8)
        num, labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
        candidates = []
        for i in range(1, num):
            left = stats[i, cv2.CC_STAT_LEFT]
            top = stats[i, cv2.CC_STAT_TOP]
            cw = stats[i, cv2.CC_STAT_WIDTH]
            ch = stats[i, cv2.CC_STAT_HEIGHT]
            if cw <= 0 or ch <= 0:
                continue
            patch = res[top:top + ch, left:left + cw].copy()
            lbl = labels[top:top + ch, left:left + cw]
            patch[lbl != i] = -1.0
            _, peak, _, peak_loc = cv2.minMaxLoc(patch)
            if peak < thr:
                continue
            px = left + peak_loc[0]
            py = top + peak_loc[1]
            candidates.append((px, py, float(peak)))
        if VISION_DEBUG:
            print(f'[VISION] wall_upgrade candidate groups: {len(candidates)}')
        if candidates:
            left, top, score = max(candidates, key=lambda item: item[1])   # lowest on screen
            cx = x1 + left + tpl['w'] // 2
            cy = y1 + top + tpl['h'] // 2
            if VISION_DEBUG:
                dbg = screen.copy()
                tl = (x1 + left, y1 + top)
                br = (x1 + left + tpl['w'], y1 + top + tpl['h'])
                cv2.rectangle(dbg, tl, br, (0, 0, 255), 2)
                cv2.circle(dbg, (cx, cy), 5, (0, 255, 0), -1)
                cv2.putText(dbg, f'score={score:.3f}', (tl[0], max(20, tl[1] - 8)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA)
                cv2.imwrite('debug_wall_upgrade_match.png', dbg)
                print(f'[VISION] wall_upgrade selected box={tl}->{br} center=({cx},{cy}) score={score:.3f}')
            return cx, cy
        return None

    # ------------------------------------------------------------------ town hall

    def find_townhall(B):
        screen = B.grab()
        best_score = 0
        best_pos = None
        best_name = None
        for name, tpl in B.th_templates.items():
            res = cv2.matchTemplate(screen, tpl['img'], cv2.TM_CCOEFF_NORMED)   # colour (BGR) match
            while True:
                _, score, _, loc = cv2.minMaxLoc(res)
                if score < 0.4:
                    break
                cx = loc[0] + tpl['w'] // 2
                cy = loc[1] + tpl['h'] // 2
                # suppress this peak in the result map, then look for the next one
                cv2.rectangle(res, loc, (loc[0] + tpl['w'], loc[1] + tpl['h']), 0, -1)
                if not B.th_inside_allowed_area(cx, cy):
                    continue
                if score > best_score:
                    best_score = score
                    best_pos = (cx, cy)
                    best_name = name
        if best_pos:
            B.last_th_pos = best_pos
            print(f'[ATTACK] TH accepted: {best_name}')
            if THZONE_DEBUG:
                print(f'[ATTACK DEBUG] TH accepted: {best_name} {best_pos} score={best_score:.3f}')
                B.debug_draw_th_grid(screen, best_pos)
            return best_pos
        print('[VISION]TH not detected')
        return None

    def get_townhall_pos(A, fallback=(791, 429)):
        pos = A.find_townhall()
        if pos:
            return pos
        if A.last_th_pos:
            return A.last_th_pos
        return fallback

    def detect_wall_level(C):
        screen = C.grab()
        roi = crop(screen, fp.WALL_LEVEL_CHECK_REGION)
        best_key = None
        best_score = 0
        for key, tpl in C.wall_level_templates.items():
            res = cv2.matchTemplate(roi, tpl['img'], cv2.TM_CCOEFF_NORMED)
            _, score, _, _ = cv2.minMaxLoc(res)
            if score > best_score:
                best_score = score
                best_key = key
        if VISION_DEBUG:
            print('Wall level match:', best_key, best_score)
        if best_key and best_score > 0.7:
            return int(best_key.replace('lvl', ''))
        return None

    # ------------------------------------------------------------------ loot / digit reading

    def read_loot(I):
        """Home-village gold/elixir counters (top-right) via white-glyph segmentation + digit templates."""
        screen = I.grab()
        gold_region = fp.HOME_GOLD_REGION
        elixir_region = fp.HOME_ELIXIR_REGION

        def A(region):
            x1, y1, x2, y2 = region
            roi = screen[y1:y2, x1:x2]
            hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
            lower = np.array([0, 0, 200])
            upper = np.array([180, 60, 255])
            mask = cv2.inRange(hsv, lower, upper)
            mask = cv2.resize(mask, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_LINEAR)
            _, mask = cv2.threshold(mask, 180, 255, cv2.THRESH_BINARY)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            boxes = []
            for c in contours:
                x, y, w, h = cv2.boundingRect(c)
                if h > 12 and w > 4:
                    boxes.append((x, y, w, h))
            boxes.sort(key=lambda b: b[0])
            text = ''
            for x, y, w, h in boxes:
                glyph = mask[y:y + h, x:x + w]
                glyph = cv2.copyMakeBorder(glyph, 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=0)
                digit = I.match_digit(glyph)
                text += digit
            return int(text) if text else 0

        gold = A(gold_region)
        elixir = A(elixir_region)
        if VISION_DEBUG:
            print(f'[VISION] LootGold:{gold} Elixir:{elixir}')
        return gold, elixir

    def _enemy_loot_regions(D, screen):
        """Enemy available-loot regions, shifted by the offset of the 'available_loot' anchor template."""
        base = (fp.ENEMY_GOLD_REGION, fp.ENEMY_ELIXIR_REGION, fp.ENEMY_DARK_REGION)
        anchor = D.templates.get('available_loot')
        if not anchor:
            return base
        hit = D.match_template(screen, 'available_loot', fp.ENEMY_LOOT_ANCHOR_THRESHOLD,
                               region=fp.ENEMY_LOOT_ANCHOR_SEARCH_REGION)
        if not hit:
            return base
        ref_x, ref_y = fp.ENEMY_LOOT_ANCHOR_TOP_LEFT
        dx = int(hit[0] - anchor['w'] // 2) - ref_x
        dy = int(hit[1] - anchor['h'] // 2) - ref_y
        return tuple((x1 + dx, y1 + dy, x2 + dx, y2 + dy) for x1, y1, x2, y2 in base)

    def detect_loot(F):
        """Enemy base available loot (gold, elixir, dark) during scouting."""
        screen = F.grab()
        gold_r, elixir_r, dark_r = F._enemy_loot_regions(screen)
        gold_img = crop(screen, gold_r)
        elixir_img = crop(screen, elixir_r)
        dark_img = crop(screen, dark_r)

        def B(crop):
            hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
            lower = np.array([0, 0, 200])
            upper = np.array([180, 60, 255])
            mask = cv2.inRange(hsv, lower, upper)
            mask = cv2.resize(mask, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_LINEAR)
            _, mask = cv2.threshold(mask, 180, 255, cv2.THRESH_BINARY)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            boxes = []
            for c in contours:
                x, y, w, h = cv2.boundingRect(c)
                if h > 12 and w > 4:
                    boxes.append((x, y, w, h))
            boxes.sort(key=lambda b: b[0])
            text = ''
            for x, y, w, h in boxes:
                glyph = mask[y:y + h, x:x + w]
                glyph = cv2.copyMakeBorder(glyph, 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=0)
                text += F.match_digit(glyph)
            return int(text) if text else 0

        gold = B(gold_img)
        elixir = B(elixir_img)
        dark = B(dark_img)
        if ATTACK_DEBUG:
            print(f'[VISION] Enemy LootG:{gold} E:{elixir} D:{dark}')
        return gold, elixir, dark

    def stable_loot_read(E):
        loot = E.detect_loot()
        if not loot:
            return None
        gold, elixir, dark = loot
        if not (0 <= gold <= 15000000):
            gold = 0
        if not (0 <= elixir <= 15000000):
            elixir = 0
        if not (0 <= dark <= 1000000):
            dark = 0
        return gold, elixir, dark

    # Storage-bar colour samples (BGR) used to measure how full each resource bar is.
    _LOOT_BAR_COLORS = {
        'gold': [np.array([13, 192, 231], dtype=np.int16), np.array([101, 217, 242], dtype=np.int16)],
        'elixir': [np.array([192, 39, 192], dtype=np.int16), np.array([217, 118, 217], dtype=np.int16)],
        'dark': [np.array([51, 13, 39], dtype=np.int16), np.array([126, 101, 118], dtype=np.int16)],
    }
    _LOOT_BAR_TOLERANCE = 16

    def get_loot_bar_fill_ratios(A, screen=None):
        img = screen
        if img is None:
            img = A.grab()
        regions = {'gold': fp.LOOT_BAR_GOLD_REGION,
                   'elixir': fp.LOOT_BAR_ELIXIR_REGION,
                   'dark': fp.LOOT_BAR_DARK_REGION}
        ratios = {}
        for name, region in regions.items():
            x1, y1, x2, y2 = region
            best = 0.0
            for dy in range(-3, 4):                     # tolerate +-3px vertical misalignment
                strip = img[max(0, y1 + dy):y2 + dy, x1:x2].astype(np.int16)
                if strip.size == 0:
                    continue
                mask = np.zeros(strip.shape[:2], dtype=bool)
                for color in A._LOOT_BAR_COLORS[name]:
                    mask |= np.all(np.abs(strip - color) <= A._LOOT_BAR_TOLERANCE, axis=2)
                best = max(best, float(mask.any(axis=0).mean()))   # fraction of columns that are bar-coloured
            ratios[name] = best
        return ratios

    _LOOT_BAR_THRESHOLD = 1.0

    def is_loot_full(A):
        ratios = A.get_loot_bar_fill_ratios()
        return {k: v >= A._LOOT_BAR_THRESHOLD for k, v in ratios.items()}

    def read_builders_free(I, screen=None):
        """Read the 'free/total' builder counter; returns the number left of the slash glyph."""
        img = screen
        if img is None:
            img = I.grab()
        x1, y1, x2, y2 = fp.HOME_BUILDER_COUNT_REGION
        roi = img[y1:y2, x1:x2]
        if roi.size == 0:
            return None
        mask = cv2.inRange(cv2.cvtColor(roi, cv2.COLOR_BGR2HSV), np.array([0, 0, 220]), np.array([180, 30, 255]))
        contours, _hier = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes = []
        for c in contours:
            x, y, w, h = cv2.boundingRect(c)
            if 6 < h <= 30 and w > 2:
                boxes.append((x, y, w, h, float((mask[y:y + h, x:x + w] > 0).mean())))
        boxes.sort(key=lambda b: b[0])
        if len(boxes) < 3:
            return None
        slash_idx = min(range(len(boxes)), key=lambda i: boxes[i][4])   # lowest fill ratio = '/' glyph
        text = ''
        for idx, (x, y, w, h, _fill) in enumerate(boxes):
            if idx >= slash_idx:
                break
            glyph = cv2.copyMakeBorder(mask[y:y + h, x:x + w], 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=0)
            text += I.match_digit_battle(glyph) or ''
        return int(text) if text else None

    def find_treasure_hunt(B):
        screen = B.grab()
        gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        tpl = B.templates['treasure_hunt']
        res = cv2.matchTemplate(gray, tpl['img'], cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if VISION_DEBUG:
            print(f'[VISION] Treasure hunt score: {max_val:.3f}')
        if max_val >= 0.85:
            return max_loc[0] + tpl['w'] // 2, max_loc[1] + tpl['h'] // 2
        return None

    def find_treasure_chest(B):
        screen = B.grab()
        gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        tpl = B.templates['treasure_chest']
        res = cv2.matchTemplate(gray, tpl['img'], cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if VISION_DEBUG:
            print(f'[VISION] Treasure chest score: {max_val:.3f}')
        if max_val >= 0.85:
            return max_loc[0] + tpl['w'] // 2, max_loc[1] + tpl['h'] // 2
        return None

    def read_battle_end_loot(M, debug=False):
        """Battle-end screen loot: sum of 'top' and 'bottom' rows per resource."""
        screen = M.grab()
        gold_top = crop(screen, fp.BATTLE_GOLD_TOP_REGION)
        elixir_top = crop(screen, fp.BATTLE_ELIXIR_TOP_REGION)
        dark_top = crop(screen, fp.BATTLE_DARK_TOP_REGION)
        gold_bot = crop(screen, fp.BATTLE_GOLD_BOTTOM_REGION)
        elixir_bot = crop(screen, fp.BATTLE_ELIXIR_BOTTOM_REGION)
        dark_bot = crop(screen, fp.BATTLE_DARK_BOTTOM_REGION)

        def B(img, name):
            label = name
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            _, mask = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            boxes = []
            for c in contours:
                x, y, w, h = cv2.boundingRect(c)
                if h > 8 and w > 4:
                    boxes.append((x, y, w, h))
            boxes.sort(key=lambda b: b[0])
            text = ''
            if ATTACK_DEBUG:
                vis = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
            for i, (x, y, w, h) in enumerate(boxes):
                glyph = mask[y:y + h, x:x + w]
                glyph = cv2.copyMakeBorder(glyph, 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=0)
                digit = M.match_digit_battle(glyph)
                text += digit
                if ATTACK_DEBUG:
                    cv2.rectangle(vis, (x, y), (x + w, y + h), (0, 255, 0), 1)
                    cv2.putText(vis, digit, (x, y - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)
                    cv2.imwrite(f'debug_digit_{label}_{i}.png', glyph)
                    print(f"[DIGIT {label}] box={(x, y, w, h)}'{digit}'")
            if ATTACK_DEBUG:
                ts = int(time.time() * 1000)
                cv2.imwrite(f'debug_battle_mask_{label}_{ts}.png', mask)
                cv2.imwrite(f'debug_battle_boxes_{label}_{ts}.png', vis)
                cv2.imwrite(f'debug_battle_crop_{label}_{ts}.png', img)
                print(f'[BATTLE DIGITS {label}]', text)
            return int(text) if text else 0

        g_top = B(gold_top, 'gold_top')
        g_bot = B(gold_bot, 'gold_bot')
        e_top = B(elixir_top, 'elixir_top')
        e_bot = B(elixir_bot, 'elixir_bot')
        d_top = B(dark_top, 'dark_top')
        d_bot = B(dark_bot, 'dark_bot')
        gold = g_top + g_bot
        elixir = e_top + e_bot
        dark = d_top + d_bot
        if ATTACK_DEBUG:
            print('[BATTLE LOOT DEBUG]')
            print(f'   GOLD   top={g_top}   bot={g_bot}   total={gold}')
            print(f'   ELIXIR top={e_top} bot={e_bot} total={elixir}')
            print(f'   DARK   top={d_top}   bot={d_bot}   total={dark}')
        return gold, elixir, dark

    def detect_battle_end_stars(G, debug=False):
        """Count lit stars: mean grey brightness > 150 in a 40x40 patch around each star point."""
        screen = G.grab()
        points = fp.BATTLE_STAR_POINTS
        stars = 0
        for x, y in points:
            patch = screen[y - 20:y + 20, x - 20:x + 20]
            if patch.size == 0:
                continue
            gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
            brightness = float(np.mean(gray))
            if ATTACK_DEBUG:
                print('[STAR DEBUG] brightness:', brightness)
                cv2.imwrite(f'debug_star_{x}_{y}.png', gray)
            if brightness > 150:
                stars += 1
        return stars

    def match_template(E, screen, template_key, threshold=0.85, region=None):
        box = region
        img = screen
        key = template_key
        tpl = E.templates.get(key)
        if not tpl:
            tpl = E.cc_request_templates.get(key)
        if not tpl:
            return None
        if box is not None:
            x1, y1, x2, y2 = box
            roi = img[y1:y2, x1:x2]
            offset = (x1, y1)
        else:
            roi = img
            offset = (0, 0)
        roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        if len(tpl['img'].shape) == 3:
            tpl_gray = cv2.cvtColor(tpl['img'], cv2.COLOR_BGR2GRAY)
        else:
            tpl_gray = tpl['img']
        ih, iw = roi_gray.shape[:2]
        th, tw = tpl_gray.shape[:2]
        if ih < th or iw < tw:
            if VISION_DEBUG:
                print(f'[VISION] {key} skipped: image {iw}x{ih} smaller than template {tw}x{th}')
            return None
        res = cv2.matchTemplate(roi_gray, tpl_gray, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if max_val < threshold:
            return None
        cx = max_loc[0] + tpl['w'] // 2 + offset[0]
        cy = max_loc[1] + tpl['h'] // 2 + offset[1]
        if VISION_DEBUG:
            print(f'[VISION] {key} match {max_val:.2f} at {(cx, cy)}')
        return cx, cy

    def collect_collectors(B, region=None, threshold=0.85):
        box = region
        screen = B.grab()
        if screen is None:
            return {}
        if box is None:
            box = fp.COLLECTOR_SEARCH_REGION
        found = {}
        for key in ('gold_collector',):
            pos = B.match_template(screen, key, threshold=threshold, region=box)
            if pos:
                found[key] = pos
        return found

    def read_troop_count(I, tab_pos, screen=None, debug=False):
        """Read the 'xN' count above a troop-bar tab (box geometry depends on locked bar scale)."""
        img = screen
        if img is None:
            img = I.grab()
        tab_x, tab_y = tab_pos
        if I.use_smallest_troop_bar_size:
            x_off = fp.TROOP_COUNT_X_OFFSET_SMALL
            y_off = fp.TROOP_COUNT_Y_OFFSET_SMALL
            box_w = fp.TROOP_COUNT_BOX_WIDTH_SMALL
            box_h = fp.TROOP_COUNT_BOX_HEIGHT_SMALL
        else:
            x_off = fp.TROOP_COUNT_X_OFFSET
            y_off = fp.TROOP_COUNT_Y_OFFSET
            box_w = fp.TROOP_COUNT_BOX_WIDTH
            box_h = fp.TROOP_COUNT_BOX_HEIGHT
        cx = tab_x + x_off
        x1 = int(cx - box_w // 2)
        x2 = int(cx + box_w // 2)
        y2 = int(tab_y - y_off)
        y1 = int(y2 - box_h)
        x1 = max(x1, 0)
        y1 = max(y1, 0)
        x2 = min(x2, img.shape[1])
        y2 = min(y2, img.shape[0])
        roi = img[y1:y2, x1:x2]
        if roi.size == 0:
            return None
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        lower = np.array([0, 0, 200])
        upper = np.array([180, 60, 255])
        mask = cv2.inRange(hsv, lower, upper)
        mask = cv2.resize(mask, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_LINEAR)
        _, mask = cv2.threshold(mask, 180, 255, cv2.THRESH_BINARY)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes = []
        for c in contours:
            x, y, w, h = cv2.boundingRect(c)
            if h > 12 and w > 4:
                boxes.append((x, y, w, h))
        boxes.sort(key=lambda b: b[0])
        text = ''
        for x, y, w, h in boxes:
            glyph = mask[y:y + h, x:x + w]
            glyph = cv2.copyMakeBorder(glyph, 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=0)
            digit = I.match_digit(glyph)
            text += digit
        if ATTACK_DEBUG:
            print('[TROOP DIGITS]', text)
            ts = int(time.time() * 1000)
            cv2.imwrite(f'debug_troop_digits_{ts}.png', mask)
        return int(text) if text else None

    def match_digit_battle(E, roi):
        glyph = roi
        glyph = cv2.resize(glyph, (30, 40), interpolation=cv2.INTER_LINEAR)
        best_digit = None
        best_score = 0
        for digit, samples in E.DIGIT_BATTLE.items():
            for sample in samples:
                tpl = cv2.resize(sample, glyph.shape[::-1], interpolation=cv2.INTER_LINEAR)
                res = cv2.matchTemplate(glyph, tpl, cv2.TM_CCOEFF_NORMED)
                score = res.max()
                if score > best_score:
                    best_score = score
                    best_digit = digit
        if best_score > 0.85:
            return best_digit
        return ''

    def match_digit(F, roi):
        glyph = roi
        glyph = cv2.resize(glyph, (30, 40), interpolation=cv2.INTER_LINEAR)
        best_digit = None
        best_score = 0
        for digit, samples in F.DIGIT_UI.items():
            for sample in samples:
                if sample.shape[0] < 35:            # skip undersized digit samples
                    continue
                tpl = cv2.resize(sample, glyph.shape[::-1], interpolation=cv2.INTER_LINEAR)
                res = cv2.matchTemplate(glyph, tpl, cv2.TM_CCOEFF_NORMED)
                score = res.max()
                if score > best_score:
                    best_score = score
                    best_digit = digit
        if best_score > 0.55:
            return best_digit
        return ''

    # ------------------------------------------------------------------ clan castle / misc

    def find_request_available(D, debug=False):
        screen = D.grab()
        gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        for key in ('cc_cake', 'request_available'):
            tpl = D.templates.get(key)
            if not tpl:
                continue
            res = cv2.matchTemplate(gray, tpl['img'], cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            if max_val < 0.85:
                continue
            x, y = max_loc
            th, tw = tpl['img'].shape[:2]
            patch = screen[y:y + th, x:x + tw]
            if patch.size == 0:
                continue
            if key != 'cc_cake':
                # Greyed-out (disabled) request button has ~no saturation.
                hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
                sat = hsv[:, :, 1]
                mean_sat = float(sat.mean())
                if mean_sat < 10:
                    continue
            return x + tw // 2, y + th // 2
        return None

    def find_cg_request_available(D, debug=False):
        screen = D.grab()
        gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        tpl = D.templates.get('request_available')
        if not tpl:
            return None
        res = cv2.matchTemplate(gray, tpl['img'], cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if max_val < 0.85:
            return None
        x, y = max_loc
        th, tw = tpl['img'].shape[:2]
        patch = screen[y:y + th, x:x + tw]
        if patch.size == 0:
            return None
        hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
        sat = hsv[:, :, 1]
        mean_sat = float(sat.mean())
        if mean_sat < 10:
            return None
        return x + tw // 2, y + th // 2

    def th_inside_allowed_area(A, x, y):
        return cv2.pointPolygonTest(A.TH_ALLOWED_POLY, (x, y), False) >= 0

    def debug_draw_th_grid(C, screen, th_pos=None):
        pos = th_pos
        img = screen.copy()
        cv2.polylines(img, [C.TH_ALLOWED_POLY], isClosed=True, color=(0, 255, 0), thickness=3)
        if pos:
            cv2.circle(img, pos, 10, (0, 0, 255), -1)
            cv2.putText(img, 'TH', (pos[0] + 10, pos[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        if THZONE_DEBUG:
            ts = int(time.time() * 1000)
            cv2.imwrite(f'debug_th_grid_{ts}.png', img)

    def is_cost_red(D, region):
        """True when >5% of the region's pixels are red (cost text shown red = not affordable)."""
        roi = D.capture_region(region)
        if roi is None or roi.size == 0:
            return False
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        lower1 = np.array([0, 80, 150])
        upper1 = np.array([10, 255, 255])
        lower2 = np.array([170, 80, 150])
        upper2 = np.array([180, 255, 255])
        mask1 = cv2.inRange(hsv, lower1, upper1)
        mask2 = cv2.inRange(hsv, lower2, upper2)
        mask = cv2.bitwise_or(mask1, mask2)
        red_ratio = np.sum(mask > 0) / mask.size
        return red_ratio > 0.05

    def capture_region(F, region):
        x1, y1, x2, y2 = region
        screen = F.grab()
        x1 = max(0, x1)
        y1 = max(0, y1)
        x2 = min(screen.shape[1], x2)
        y2 = min(screen.shape[0], y2)
        return screen[y1:y2, x1:x2]

    def find_error_dialog(D):
        """Scan templates/errors/error_*.png; return (name, pos) preferring the matching *_button.png."""
        errors_dir = D._template_path('errors')
        if not os.path.exists(errors_dir):
            return None
        screen = D.grab()
        gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)

        def E(image_path, threshold=0.85):
            tpl = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
            if tpl is None:
                return None
            res = cv2.matchTemplate(gray, tpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            if max_val < threshold:
                return None
            th, tw = tpl.shape[:2]
            return max_loc[0] + tw // 2, max_loc[1] + th // 2

        for fname in os.listdir(errors_dir):
            if not (fname.startswith('error_') and fname.endswith('.png')):
                continue
            if fname.endswith('_button.png'):
                continue
            name = fname.replace('.png', '')
            button_name = f'{name}_button.png'
            dialog_path = os.path.join(errors_dir, fname)
            button_path = os.path.join(errors_dir, button_name)
            dialog_pos = E(dialog_path, 0.85)
            if not dialog_pos:
                continue
            if os.path.exists(button_path):
                button_pos = E(button_path, 0.85)
                if button_pos:
                    return name, button_pos
            return name, dialog_pos
        return None

    def find_upgrade_buttons(E, threshold=0.85):
        screen = E.grab()
        gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        keys = ['wall_chain']
        points = []
        for key in keys:
            tpl = E.templates.get(key)
            if tpl is None:
                print(f'[VISION]Missing template: {key}')
                continue
            tpl_img = tpl['img'] if isinstance(tpl, dict) else tpl
            th, tw = tpl_img.shape[:2]
            res = cv2.matchTemplate(gray, tpl_img, cv2.TM_CCOEFF_NORMED)
            ys, xs = np.where(res >= threshold)
            for x, y in zip(xs, ys):
                cx = x + tw // 2
                cy = y + th // 2
                points.append((cx, cy))
        unique = []
        for cx, cy in points:
            if any(abs(cx - ux) < 25 and abs(cy - uy) < 25 for ux, uy in unique):
                continue
            unique.append((cx, cy))
        unique.sort(key=lambda p: p[0])
        return unique

    def match_two_templates(H, screen, key, threshold=0.85):
        gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        tpl = H.templates.get(key)
        if tpl is None:
            return []
        if isinstance(tpl, dict):
            tpl = tpl['img']
        th, tw = tpl.shape[:2]
        res = cv2.matchTemplate(gray, tpl, cv2.TM_CCOEFF_NORMED)
        loc = np.where(res >= threshold)
        points = []
        for pt in zip(*loc[::-1]):
            points.append((pt[0] + tw // 2, pt[1] + th // 2))
        filtered = []
        for x, y in points:
            keep = True
            for fx, fy in filtered:
                if abs(x - fx) < 40 and abs(y - fy) < 40:
                    keep = False
                    break
            if keep:
                filtered.append((x, y))
        return filtered

    def debug_match_score(B, img, key):
        name = key
        if name not in B.templates:
            print(f'[VISION] Template not loaded: {name}')
            return None
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        tpl_img = B.templates[name]['img']
        res = cv2.matchTemplate(gray, tpl_img, cv2.TM_CCOEFF_NORMED)
        _min_val, max_val, _min_loc, _max_loc = cv2.minMaxLoc(res)
        print(f'[VISION DEBUG] {name} score: {max_val:.4f}')
        return max_val

    # ------------------------------------------------------------------ clan games

    def match_clangames(O, region, templates, threshold=0.85):
        tpl_map = templates
        thr = threshold
        x1, y1, x2, y2 = region
        screen = O.grab()
        roi = screen[y1:y2, x1:x2]
        if roi.size == 0:
            return None, None, 0
        best_score = 0
        best_name = None
        best_loc = None
        best_size = None
        if VISION_DEBUG:
            print(f'[CLAN GAMES DEBUG] Searching {len(tpl_map)} templates with threshold {thr}')
        for name, tpl in tpl_map.items():
            th, tw = tpl['img'].shape[:2]
            if th >= roi.shape[0] or tw >= roi.shape[1]:
                continue
            res = cv2.matchTemplate(roi, tpl['img'], cv2.TM_CCOEFF_NORMED)   # colour (BGR) match
            _, score, _, loc = cv2.minMaxLoc(res)
            if VISION_DEBUG:
                print(f'[CLAN GAMES DEBUG]   {name}: {score:.3f}' + (' ✓' if score >= thr else ''))
            if score > best_score:
                best_score = score
                best_name = name
                best_loc = loc
                best_size = (tw, th)
        if best_score < thr or best_loc is None:
            if VISION_DEBUG:
                print(f'[CLAN GAMES DEBUG] No match above threshold. Best: {best_name} at {best_score:.3f}')
            return None, None, best_score
        cx = x1 + best_loc[0] + best_size[0] // 2
        cy = y1 + best_loc[1] + best_size[1] // 2
        if VISION_DEBUG:
            print(f'[CLAN GAMES] BEST: {best_name} score={best_score:.3f}')
        return best_name, (cx, cy), best_score

    def find_clan_games_start_scaled(E, debug=False):
        dbg = debug
        if dbg:
            print('[CLAN GAMES] Builder swipe down')
        adb.swipe(*fp.BUILDER_SWIPE_UP)
        time.sleep(1.0)
        # FIX: the original only tried scales <= 1.0 and returned the first hit >= 0.75. On MEmu the
        # zoomed-out village renders the Clan Games building ~5-10% larger (clangames_start1 scores
        # 0.75 at 1.0x but 0.92 at 1.05x), so detection flipped between found / "Unable to start".
        # Search slightly larger scales too and keep the best match over all templates and scales.
        scales = [1.0, 1.05, 1.1, 0.95, 0.9, 0.85]
        screen = E.grab()
        gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        best = None  # (score, cx, cy, key, scale)
        for key in ('clangames_start3', 'clangames_start1', 'clangames_start2'):
            tpl = E.templates.get(key)
            if not tpl:
                print(f'[CLAN GAMES] Template {key} missing')
                continue
            for s in scales:
                if dbg:
                    print(f'[CLAN GAMES] Searching {key} at scale {s}')
                scaled = cv2.resize(tpl['img'], None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
                th, tw = scaled.shape[:2]
                if th >= gray.shape[0] or tw >= gray.shape[1]:
                    continue
                res = cv2.matchTemplate(gray, scaled, cv2.TM_CCOEFF_NORMED)
                _, score, _, loc = cv2.minMaxLoc(res)
                if dbg:
                    print(f'[CLAN GAMES] {key} scale {s} score {score:.3f}')
                if score >= 0.75 and (best is None or score > best[0]):
                    best = (score, loc[0] + tw // 2, loc[1] + th // 2, key, s)
        if best:
            if dbg:
                print(f'[CLAN GAMES] Found start button via {best[3]} at scale {best[4]} ({best[0]:.3f})')
            return best[1], best[2]
        if dbg:
            print('[CLAN GAMES] Start button not found')
        return None
