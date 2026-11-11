# Reconstructed from Pyarmor-decrypted bytecode (error_popup_watcher, Python 3.10).
# Separate process that template-matches error popups in a screen region and
# reports the button position back to the bot through a 1-slot queue.
import queue
import multiprocessing as mp
from pathlib import Path
import time
import cv2
import numpy as np
import defaults
from utils.runtime_paths import resolve_resource_path

# (popup template key, button template key, is_hard)
ERROR_POPUPS = [
    ('error_rating', 'error_rating_button', False),
    ('error_client', 'error_client_button', True),
    ('error_connection', 'error_connection_button', True),
    ('error_device', 'error_device_button', True),
    ('error_inactivity', 'error_inactivity_button', True),
]
POPUP_MATCH_THRESHOLD = 0.8
BUTTON_MATCH_THRESHOLD = 0.8


def _imread_unicode_safe(path, mode):
    data = np.fromfile(str(path), dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, mode)


def _template_file_path(key):
    templates_dir = Path(defaults.TEMPLATES_DIR)
    rel = templates_dir / 'errors' / f'{key}.png'
    return Path(resolve_resource_path(str(rel)))


def _load_templates():
    templates = {}
    for popup_key, button_key, is_hard in ERROR_POPUPS:
        popup_path = _template_file_path(popup_key)
        button_path = _template_file_path(button_key)
        popup_img = _imread_unicode_safe(popup_path, cv2.IMREAD_GRAYSCALE)
        button_img = _imread_unicode_safe(button_path, cv2.IMREAD_GRAYSCALE)
        if popup_img is None or button_img is None:
            continue
        templates[popup_key] = {
            'popup': popup_img,
            'button': button_img,
            'is_hard': is_hard,
            'button_key': button_key,
        }
    return templates


def _match_center(gray_img, tmpl, threshold):
    img = gray_img
    template = tmpl
    if img is None or template is None:
        return None
    img_h, img_w = img.shape[:2]
    t_h, t_w = template.shape[:2]
    if img_h < t_h or img_w < t_w:
        return None
    res = cv2.matchTemplate(img, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    if max_val < threshold:
        return None
    h, w = template.shape[:2]
    return (max_loc[0] + w // 2, max_loc[1] + h // 2)


def _put_latest(q, payload):
    """Put into a maxsize=1 queue, dropping the stale item if full."""
    item = payload
    try:
        q.put_nowait(item)
        return
    except queue.Full:
        pass
    try:
        q.get_nowait()
    except queue.Empty:
        pass
    try:
        q.put_nowait(item)
    except queue.Full:
        pass


def _watcher_main(frame_queue, detection_queue, stop_event, region):
    templates = _load_templates()
    rx1, ry1, rx2, ry2 = region
    last_error_log = 0.0
    while not stop_event.is_set():
        try:
            try:
                payload = frame_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if payload is None:
                continue
            if isinstance(payload, np.ndarray):
                frame = payload
            else:
                buf = np.frombuffer(payload, dtype=np.uint8)
                frame = cv2.imdecode(buf, cv2.IMREAD_COLOR)
            if frame is None:
                continue
            h, w = frame.shape[:2]
            x1 = max(0, min(rx1, w))
            x2 = max(0, min(rx2, w))
            y1 = max(0, min(ry1, h))
            y2 = max(0, min(ry2, h))
            if x2 <= x1 or y2 <= y1:
                continue
            crop = frame[y1:y2, x1:x2]
            if crop.size == 0:
                continue
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            for popup_key, button_key, is_hard in ERROR_POPUPS:
                tpl = templates.get(popup_key)
                if not tpl:
                    continue
                popup_hit = _match_center(gray, tpl['popup'], POPUP_MATCH_THRESHOLD)
                if not popup_hit:
                    continue
                button_hit = _match_center(gray, tpl['button'], BUTTON_MATCH_THRESHOLD)
                if not button_hit:
                    continue
                detection = {
                    'popup_key': popup_key,
                    'button_key': button_key,
                    'is_hard': is_hard,
                    'button_pos': (button_hit[0] + x1, button_hit[1] + y1),
                }
                _put_latest(detection_queue, detection)
                break
        except Exception as e:
            now = time.time()
            if now - last_error_log >= 2.0:
                print(f'[WATCHDOG] watcher frame processing error: {e}')
                last_error_log = now


class ErrorPopupWatcher:
    def __init__(A, region):
        A.region = region
        A._frame_queue = mp.Queue(maxsize=1)
        A._detection_queue = mp.Queue(maxsize=1)
        A._stop_event = mp.Event()
        A._proc = None

    def start(A):
        if A._proc is not None and A._proc.is_alive():
            return
        A._frame_queue = mp.Queue(maxsize=1)
        A._detection_queue = mp.Queue(maxsize=1)
        A._stop_event = mp.Event()
        A._proc = mp.Process(
            target=_watcher_main,
            args=(A._frame_queue, A._detection_queue, A._stop_event, A.region),
            daemon=True,
        )
        A._proc.start()

    def is_alive(A):
        return A._proc is not None and A._proc.is_alive()

    def stop(A):
        if A._proc is None:
            return
        A._stop_event.set()
        try:
            A._frame_queue.put_nowait(None)
        except Exception:
            pass
        A._proc.join(timeout=1.0)
        if A._proc.is_alive():
            A._proc.terminate()
            A._proc.join(timeout=1.0)
        A._proc = None
        # FIX: each mp.Queue keeps a feeder thread; left running, it was torn down during interpreter
        # shutdown and crashed Python on window close ("Windows fatal exception: access violation",
        # exit code 5). Close the queues and do not wait to flush data the dead child never reads.
        for q in (A._frame_queue, A._detection_queue):
            try:
                q.cancel_join_thread()
                q.close()
            except Exception:
                pass

    def submit_frame(A, frame):
        f = frame
        if A._proc is None or f is None:
            return
        snapshot = np.ascontiguousarray(f).copy()
        _put_latest(A._frame_queue, snapshot)

    def poll_detection(B):
        latest = None
        # Drain the queue, keep the newest detection.
        while True:
            try:
                latest = B._detection_queue.get_nowait()
            except queue.Empty:
                break
        return latest
