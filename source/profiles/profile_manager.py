# Reconstructed from Pyarmor-decrypted bytecode (profiles.profile_manager, Python 3.10).
import os, cv2, pytesseract, re
import fixed_points as fp
import adb
from adb import tap
import time, json, math, control
from pathlib import Path
from profiles.config_manager import ConfigManager
import numpy as np
from utils.runtime_paths import resolve_writable_path, resolve_external_resource_path

PROFILE_DEBUG = False
PROFILE_CALIBRATION_DUPLICATE_THRESHOLD = 0.98

# Tesseract OCR discovery (used to read Supercell ID profile names)
if os.name == 'nt':
    portable_tesseract = resolve_external_resource_path('Tools/tesseract/tesseract.exe')
    portable_tessdata = resolve_external_resource_path('Tools/tesseract/tessdata')
    if portable_tesseract.exists():
        pytesseract.pytesseract.tesseract_cmd = str(portable_tesseract)
        if portable_tessdata.exists():
            os.environ['TESSDATA_PREFIX'] = str(portable_tessdata)
    if not portable_tesseract.exists():
        possible_paths = [
            'C:\\Program Files\\Tesseract-OCR\\tesseract.exe',
            'C:\\Program Files (x86)\\Tesseract-OCR\\tesseract.exe',
            'C:\\Tesseract-OCR\\tesseract.exe',
        ]
        for path in possible_paths:
            if os.path.exists(path):
                pytesseract.pytesseract.tesseract_cmd = path
                break
else:
    # macOS / Linux: Homebrew / package-manager install (apps started from Finder lack the shell PATH)
    import shutil as _shutil
    for path in (_shutil.which('tesseract'), '/opt/homebrew/bin/tesseract', '/usr/local/bin/tesseract',
                 '/usr/bin/tesseract'):
        if path and os.path.exists(path):
            pytesseract.pytesseract.tesseract_cmd = path
            break

# Loaded at import time (creates profiles/config.json if missing)
cfg = ConfigManager().load()
village_count = cfg.get('VILLAGE_COUNT', 10)
PROFILE_DIR = str(resolve_writable_path('profiles'))
ORDER_FILE = os.path.join(PROFILE_DIR, 'order.txt')
ACTIVE_PROFILES_PATH = os.path.join(PROFILE_DIR, 'active_profiles.json')
PROFILE_EXPAND_RIGHT = 440
MAX_PROFILES = 100
Y_OFFSET = 11
SCROLL_UP = (1133, 187, 1152, 773)
SCROLL_DOWN = (1152, 773, 1133, 187)


def sanitize_name(text):
    s = text
    s = s.lower().strip()
    s = re.sub('[^a-z0-9 ]', '', s)
    s = re.sub('\\s+', '_', s)
    return s or 'unknown'


def _load_active_profiles_data():
    empty = {'profiles': {}}
    if not os.path.exists(ACTIVE_PROFILES_PATH):
        return empty
    try:
        with open(ACTIVE_PROFILES_PATH, 'r', encoding='utf-8-sig') as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return empty
    if not isinstance(data, dict):
        return empty
    if not isinstance(data.get('profiles'), dict):
        data['profiles'] = {}
    return data


class ProfileManager:
    def __init__(self, vision):
        self.vision = vision
        os.makedirs(PROFILE_DIR, exist_ok=True)

    def _decode_profile_image(self, path):
        try:
            raw = Path(path).read_bytes()
            return cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_GRAYSCALE)
        except Exception:
            return None

    def _profile_crop_to_gray(self, crop):
        img = crop
        if img is None or getattr(img, 'size', 0) == 0:
            return None
        if len(img.shape) == 2:
            return img
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    def _profile_visual_similarity(self, candidate_crop, reference_crop):
        cand = self._profile_crop_to_gray(candidate_crop)
        ref = self._profile_crop_to_gray(reference_crop)
        if cand is None or ref is None:
            return 0.0
        h, w = ref.shape[:2]
        if h <= 0 or w <= 0:
            return 0.0
        if cand.shape[:2] != ref.shape[:2]:
            cand = cv2.resize(cand, (w, h), interpolation=cv2.INTER_AREA)
        result = cv2.matchTemplate(cand, ref, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(result)
        return float(max_val)

    def _find_duplicate_profile_by_image(self, candidate_crop, known_profile_images,
                                         threshold=PROFILE_CALIBRATION_DUPLICATE_THRESHOLD):
        best_name = None
        best_score = 0.0
        for name, image in known_profile_images.items():
            score = self._profile_visual_similarity(candidate_crop, image)
            if score > best_score:
                best_name = name
                best_score = score
        if best_name is not None and best_score >= float(threshold):
            return (best_name, best_score)
        return (None, best_score)

    def _make_unique_profile_name(self, base_name, seen_names):
        seen = seen_names
        base = base_name or 'unknown'
        if base not in seen:
            return base
        idx = 2
        while f'{base}_{idx}' in seen:
            idx += 1
        return f'{base}_{idx}'

    def _make_unknown_profile_name(self, seen_names):
        idx = 1
        while True:
            name = f'unknown{idx}'
            if name not in seen_names:
                return name
            idx += 1

    def _fallback_profile_name_region(self, card):
        img = card
        if img is None or getattr(img, 'size', 0) == 0:
            return img
        bottom = min(50, img.shape[0])
        left = min(150, max(img.shape[1] // 4, 105))
        right = max(left + 80, img.shape[1] - 20)
        return img[:bottom, left:right].copy()

    def rename_profile(self, old_name, new_name):
        old_name = str(old_name or '').strip()
        new_raw = str(new_name or '').strip()
        if not old_name:
            return (False, 'Missing source profile name', old_name)
        if not new_raw:
            return (False, 'Profile name cannot be empty', old_name)
        new_name = sanitize_name(new_raw)
        if not new_name:
            return (False, 'Profile name is invalid', old_name)
        if new_name == old_name:
            return (True, 'No rename needed', old_name)
        old_dir = os.path.join(PROFILE_DIR, old_name)
        new_dir = os.path.join(PROFILE_DIR, new_name)
        if not os.path.isdir(old_dir):
            return (False, f"Profile '{old_name}' does not exist", old_name)
        if os.path.exists(new_dir):
            return (False, f"Profile '{new_name}' already exists", old_name)
        try:
            os.rename(old_dir, new_dir)
        except OSError as e:
            return (False, f'Failed to rename folder: {e}', old_name)
        try:
            if os.path.exists(ORDER_FILE):
                with open(ORDER_FILE, 'r', encoding='utf-8') as f:
                    order = [line.strip() for line in f if line.strip()]
                order = [new_name if n == old_name else n for n in order]
                with open(ORDER_FILE, 'w', encoding='utf-8') as f:
                    for n in order:
                        f.write(n + '\n')
        except OSError:
            pass
        data = _load_active_profiles_data()
        profiles = data.get('profiles', {})
        if old_name in profiles:
            profiles[new_name] = profiles.pop(old_name)
        else:
            profiles[new_name] = True
        try:
            with open(ACTIVE_PROFILES_PATH, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        except OSError as e:
            return (False, f'Renamed folder but failed to update active profiles: {e}', old_name)
        try:
            cm = ConfigManager()
            global_cfg = cm.load()
            if str(global_cfg.get('START_PROFILE', '') or '').strip() == old_name:
                global_cfg['START_PROFILE'] = new_name
                cm.save(global_cfg)
        except Exception:
            pass
        return (True, 'Profile renamed', new_name)

    def profiles_initialized(self):
        return os.path.exists(ACTIVE_PROFILES_PATH)

    def get_calibrated_profile_count(self):
        return len(self.list_profiles())

    def list_profiles(self):
        if not os.path.exists(ACTIVE_PROFILES_PATH):
            return []
        data = _load_active_profiles_data()
        profiles = data.get('profiles', {})
        result = []
        for name, _enabled in profiles.items():
            folder = os.path.join(PROFILE_DIR, name)
            if os.path.isdir(folder):
                result.append(name)
            else:
                print(f'[PROFILES] Missing folder for {name}')
        return result

    def calibrate_profiles(self, village_count):
        # Pro: up to MAX_PROFILES villages (the Basic build capped this at 5)
        target = max(0, min(int(village_count), MAX_PROFILES))
        existing = self.list_profiles()[:MAX_PROFILES]
        previous_flags = {}
        if os.path.exists(ACTIVE_PROFILES_PATH):
            with open(ACTIVE_PROFILES_PATH, 'r') as f:
                data = json.load(f)
            previous_flags = data.get('profiles', {})
        tap(*fp.HOME_OPEN_SETTINGS)
        time.sleep(1.2)
        tap(*fp.HOME_SETTINGS_TAB)
        time.sleep(0.8)
        tap(*fp.HOME_OPEN_PROFILES)
        time.sleep(2.0)
        print('\n=== PROFILE CALIBRATION MODE ===')
        print('Open Supercell profile screen.')
        print(f'[PROFILES] Scanning up to {target} profiles')
        if existing:
            remaining = max(0, target - len(existing))
            print(f'{len(existing)} existing profiles found. Capture {remaining} new profile(s).')
            print('Align uncaptured profiles on screen, then click Continue...')
        else:
            print('Align FIRST profiles on screen, then click Continue...')
        control.BotControl.wait_for_continue('Profile Calibration', 'Align profiles on screen, then click Continue.')
        captured = len(existing)
        seen_names = set(existing)
        known_images = {}
        for name in existing:
            img_path = os.path.join(PROFILE_DIR, name, 'profile.png')
            img = self._decode_profile_image(img_path)
            if img is not None:
                known_images[name] = img
        ordered = list(existing)
        # Pro: scroll the account list automatically between passes; ask the user only when two
        # scrolled passes in a row add nothing (end of the list, or the screen needs aligning).
        max_attempts = 3 + target // 2
        attempts = 0
        empty_scrolls = 0
        while captured < target and attempts < max_attempts:
            attempts += 1
            frame = self.vision.grab()
            boxes = self.vision.find_all_templates('profile_box')
            if not boxes:
                print('[PROFILES] No profile boxes detected!')
                if attempts < max_attempts:
                    print('Adjust screen and click Continue...')
                    control.BotControl.wait_for_continue(
                        'Profile Calibration',
                        'No profile boxes detected. Adjust the profile screen, then click Continue.')
                continue
            boxes = sorted(boxes, key=lambda b: b[1])
            new_this_pass = 0
            for (x, y, w, h) in boxes:
                if captured >= target:
                    break
                x1 = x
                y1 = y + Y_OFFSET
                x2 = x + w + PROFILE_EXPAND_RIGHT
                y2 = y + h + Y_OFFSET
                card = frame[y1:y2, x1:x2]
                if not self.is_valid_profile_card(card):
                    continue
                name_region = self.extract_profile_name_region(card)
                is_unknown = False
                if name_region is None:
                    crop = self._fallback_profile_name_region(card)
                    if crop is None or getattr(crop, 'size', 0) == 0:
                        continue
                    name = self._make_unknown_profile_name(seen_names)
                    is_unknown = True
                else:
                    crop = name_region.copy()
                    big = cv2.resize(name_region, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
                    gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
                    text = pytesseract.image_to_string(gray, config='--psm 7')
                    name = sanitize_name(text)
                    if name == 'unknown':
                        name = self._make_unknown_profile_name(seen_names)
                        is_unknown = True
                dup_name, _dup_score = self._find_duplicate_profile_by_image(crop, known_images)
                if dup_name:
                    continue
                if not is_unknown:
                    name = self._make_unique_profile_name(name, seen_names)
                seen_names.add(name)
                new_this_pass += 1
                folder = os.path.join(PROFILE_DIR, name)
                os.makedirs(folder, exist_ok=True)
                png_path = os.path.join(folder, 'profile.png')
                ok, buf = cv2.imencode('.png', crop)
                if ok:
                    with open(png_path, 'wb') as f:
                        f.write(buf.tobytes())
                    known_images[name] = self._profile_crop_to_gray(crop)
                else:
                    print(f'[PROFILES] Warning: failed to encode profile image for {name}')
                ordered.append(name)
                print(f'[PROFILE] Saved {name}')
                captured += 1
            if captured < target and (new_this_pass > 0 or empty_scrolls < 2):
                empty_scrolls = 0 if new_this_pass else empty_scrolls + 1
                adb.swipe(*SCROLL_DOWN, 600)       # next page of accounts
                time.sleep(1.2)
                continue
            empty_scrolls = 0
            if captured < target and new_this_pass == 0 and attempts < max_attempts:
                print(f'\nCaptured {captured}/{target}')
                print('No new cards found. Re-align the visible list and click Continue...')
                control.BotControl.wait_for_continue(
                    'Profile Calibration',
                    f'Captured {captured}/{target}. Re-align visible profiles and click Continue.')
        if captured < target:
            print(f'[PROFILES] Scan ended after {max_attempts} attempts. Found {captured}/{target}.')
        with open(ORDER_FILE, 'w') as f:
            for name in ordered:
                f.write(name + '\n')
        data = {'profiles': {name: previous_flags.get(name, True) for name in ordered}}
        with open(ACTIVE_PROFILES_PATH, 'w') as f:
            json.dump(data, f, indent=2)
        from profiles.config_manager import ConfigManager
        cm = ConfigManager()
        for name in ordered:
            cm.load(name)  # creates profiles/<name>/config.json seeded from global config
        print('\n✅ Profile calibration complete.\n')
        print('[PROFILES]active_profiles.json written')

    def find_profile_on_screen(self, profile_path, threshold=0.95):
        thr = threshold
        frame = self.vision.grab()
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        template = cv2.imread(profile_path, cv2.IMREAD_GRAYSCALE)
        if template is None:
            return None
        th, tw = template.shape[:2]
        result = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if PROFILE_DEBUG:
            print(f'[PROFILES] Best match: {max_val:.4f} (threshold: {thr})')
        if max_val < thr:
            return None
        cx = max_loc[0] + tw // 2
        cy = max_loc[1] + th // 2
        return (cx, cy)

    def switch_to_profile(self, name, retries=2):
        profile_png = os.path.join(PROFILE_DIR, name, 'profile.png')
        profile_cfg = ConfigManager().load(name)
        threshold = profile_cfg.get('PROFILE_MATCH_THRESHOLD', 0.9)
        profile_count = max(1, len(self.list_profiles()))
        scroll_steps = max(1, math.ceil(profile_count / 5 * 2))
        cycles = 2  # RECON: hard-coded 2; the `retries` argument is not used
        for _cycle in range(cycles):
            tap(*fp.HOME_OPEN_SETTINGS)
            time.sleep(1.2)
            tap(*fp.HOME_SETTINGS_TAB)
            time.sleep(0.8)
            tap(*fp.HOME_OPEN_PROFILES)
            deadline = time.time() + 15.0
            on_profile_screen = False
            while time.time() < deadline:
                frame = self.vision.grab()
                if frame is not None and frame.size > 0:
                    h, w = frame.shape[:2]
                    region = (0, 0, w // 2, h)
                    on_profile_screen = self.vision.match_template_region(region, 'profile_screen', 0.8)
                    if on_profile_screen:
                        break
                time.sleep(0.25)
            if not on_profile_screen:
                print('[PROFILES] not on profile screen running recovery')
                return False
            for _step in range(scroll_steps):
                pos = self.find_profile_on_screen(profile_png, threshold=threshold)
                if pos:
                    print('[PROFILES]Profile found, tapping')
                    tap(*pos)
                    time.sleep(3.0)
                    for _ in range(10):
                        if self.vision.is_home_village():
                            print('[PROFILES]Profile loaded OK')
                            return True
                        time.sleep(0.5)
                    print('[PROFILES]Home not detected after tap')
                    break
                adb.swipe(*SCROLL_DOWN, 600)
                time.sleep(1.0)
            print('[PROFILES]Not found, returning to top')
            for _ in range(scroll_steps):
                adb.swipe(*SCROLL_UP, 600)
                time.sleep(1)
            time.sleep(1.0)
        print('\n[PROFILES] ❌ Profile not located after full cycles')
        return False

    def get_enabled_profiles(self):
        if not os.path.exists(ACTIVE_PROFILES_PATH):
            return []
        data = _load_active_profiles_data()
        profiles = data.get('profiles', {})
        enabled = []
        for name, is_enabled in profiles.items():
            if not is_enabled:
                continue
            folder = os.path.join(PROFILE_DIR, name)
            if os.path.isdir(folder):
                enabled.append(name)
        return enabled

    def is_valid_profile_card(self, card):
        return card is not None and getattr(card, 'size', 0) > 0

    def _build_primary_name_mask(self, gray):
        _, mask = cv2.threshold(gray, 110, 255, cv2.THRESH_BINARY_INV)
        kernel = np.ones((2, 2), np.uint8)
        return cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

    def _find_text_line_groups(self, mask):
        row_sums = np.sum(mask, axis=1)
        if row_sums.max() == 0:
            return []
        rows = np.where(row_sums > row_sums.max() * 0.2)[0]
        if len(rows) == 0:
            return []
        return np.split(rows, np.where(np.diff(rows) > 3)[0] + 1)

    def _score_name_line(self, gray, mask, rows, card_height):
        top = int(rows[0])
        bottom = int(rows[-1]) + 1
        line_mask = mask[top:bottom, :]
        if line_mask.size == 0:
            return -1
        line_gray = gray[top:bottom, :]
        ink = line_mask > 0
        if not np.any(ink):
            return -1
        darkness = 255.0 - float(np.mean(line_gray[ink]))
        density = float(np.mean(ink))
        height = bottom - top
        rel_top = top / max(float(card_height), 1.0)
        top_bonus = max(0.0, 0.65 - rel_top)
        height_score = min(height / 22.0, 1.0)
        return darkness * 0.03 + density * 8.0 + top_bonus * 2.5 + height_score

    def _remove_left_edge_artifacts(self, mask):
        m = mask
        if m.size == 0:
            return m
        n_labels, labels, stats, _centroids = cv2.connectedComponentsWithStats(m, 8)
        if n_labels <= 1:
            return m
        cleaned = m.copy()
        left_limit = max(10, m.shape[1] // 18)
        for i in range(1, n_labels):
            left = stats[i, cv2.CC_STAT_LEFT]
            width = stats[i, cv2.CC_STAT_WIDTH]
            area = stats[i, cv2.CC_STAT_AREA]
            if left > left_limit:
                continue
            if area >= 300 and width >= m.shape[1] * 0.12:
                continue
            cleaned[labels == i] = 0
        return cleaned

    def extract_profile_name_region(self, card):
        img = card
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        band_h = min(50, img.shape[0])
        left = min(150, max(img.shape[1] // 4, 105))
        right = max(left + 80, img.shape[1] - 20)
        band = gray[:band_h, left:right]
        mask = self._build_primary_name_mask(band)
        groups = self._find_text_line_groups(mask)
        if not groups:
            return None
        candidates = []
        max_start = max(int(band_h * 0.58), 1)
        for rows in groups:
            if len(rows) == 0:
                continue
            if rows[0] >= max_start:
                continue
            score = self._score_name_line(band, mask, rows, band_h)
            if score <= 0:
                continue
            candidates.append((score, rows))
        if not candidates:
            return None
        candidates.sort(key=lambda item: (int(item[1][0]), -item[0]))
        best_rows = candidates[0][1]
        first = best_rows[0]
        last = best_rows[-1]
        y1 = max(first - 8, 0)
        y2 = min(last + 4, band_h)
        if y2 - y1 < 22:
            y2 = min(y1 + 26, band_h)
        strip = img[y1:y2, left:right]
        strip_gray = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY)
        strip_mask = self._remove_left_edge_artifacts(self._build_primary_name_mask(strip_gray))
        col_sums = np.sum(strip_mask, axis=0)
        col_thresh = max(col_sums.max() * 0.22, 1) if col_sums.size else 1
        cols = np.where(col_sums >= col_thresh)[0]
        if len(cols) > 0:
            x1 = max(left + int(cols[0]) - 8, 0)
            x2 = min(left + int(cols[-1]) + 8, img.shape[1])
        else:
            x1 = left
            x2 = right
        region = img[y1:y2, x1:x2]
        return region
