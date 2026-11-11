# attack.redline - deploy boundary ("red line") of the enemy village (new module, not in Basic).
#
# MyBot/PHMOD find the red line with a closed image DLL (imgloc). Here it is found in the scouting
# frame directly: while scouting, Clash of Clans draws the deploy border as a thin dashed line that
# is redder and darker than the ground around it. Rays are marched from the outer deploy edges
# (attack.geometry.FOUR_SIDES) towards the village along the edge normal and stop at
#   1. the first border pixel lying on open ground (the red line itself), or
#   2. one tile before the first building/wall (a ray that slipped through a gap in the dashes).
# The ground colour is sampled per frame (sceneries differ). Decorations and obstacles can stop a
# ray early, which only moves that point a little outwards (still deployable). The result is a depth
# (px from the outer edge) for DEPTH_SAMPLES positions along every edge.
import cv2
import numpy as np

from attack.geometry import FOUR_SIDES

DEPTH_SAMPLES = 48
TILE_PX = 17                  # one tile measured across, at the zoomed-out battle view
BORDER_DA, BORDER_DL = 6, -4  # border pixels: Lab a above / L below the local median by this much
BUILDING_RUN_PX = 24          # this much non-ground in a row is a building or a wall
ISO_ANGLE_DEG = 36.6          # tile edges on screen (from the FOUR_SIDES slopes)
LINE_KERNEL_PX = 31
LINE_MIN_FILL = 0.4           # share of a 31 px iso-direction segment that must be border pixels
MIN_BORDER_EXTENT_PX = 60     # connected border pieces shorter than this are texture
ENTER_GROUND_PX = 24          # border hits count only after this much continuous ground (map rim)
STEP_PX = 3
MAX_DEPTH_FRACTION = 0.7      # never march further than this share of the edge-to-centre distance
SMOOTH_HALF = 4               # rays on each side used to smooth one ray
SMOOTH_PERCENTILE = 25
EDGE_MARGIN_PX = 10           # stay this far outside the detected border
UI_REGIONS = [                # (x1, y1, x2, y2) battle UI drawn over the map
    (0, 0, 380, 250),         # player name + available loot
    (680, 0, 920, 95),        # "Battle starts in" timer
    (1230, 0, 1600, 210),     # own resources
    (0, 630, 230, 720),       # End Battle
    (1320, 570, 1600, 720),   # Next
    (0, 725, 1600, 900),      # troop bar
]
# The ground colour differs per scenery (grass, sand, snow, dusk), so it is sampled per frame in a
# band just inside the outer deploy edges, where there is mostly open ground; a pixel is ground when
# its Lab colour is close to that sample.
BAND_FROM_PX, BAND_TO_PX = 10, 60
TOL_L, TOL_A, TOL_B = 28, 10, 12      # minimum tolerances (Lab, 0-255 scale)
TOL_MAX = (42, 15, 18)                # caps: a busy band (decorations) must not accept buildings
TOL_SPREAD = 2.5                      # x the band's median absolute deviation

_CENTER = (
    sum(p[0] for edge in FOUR_SIDES for p in edge) / 8.0,
    sum(p[1] for edge in FOUR_SIDES for p in edge) / 8.0,
)


def _band_mask(shape):
    mask = np.zeros(shape[:2], np.uint8)
    for p1, p2 in FOUR_SIDES:
        (nx, ny), _dist = _inward_normal(p1, p2)
        poly = np.array([
            [p1[0] + nx * BAND_FROM_PX, p1[1] + ny * BAND_FROM_PX],
            [p2[0] + nx * BAND_FROM_PX, p2[1] + ny * BAND_FROM_PX],
            [p2[0] + nx * BAND_TO_PX, p2[1] + ny * BAND_TO_PX],
            [p1[0] + nx * BAND_TO_PX, p1[1] + ny * BAND_TO_PX],
        ], np.int32)
        cv2.fillPoly(mask, [poly], 255)
    for x1, y1, x2, y2 in UI_REGIONS:
        mask[y1:y2, x1:x2] = 0
    return mask


def ground_reference(frame):
    """(median Lab, tolerance Lab) of the ground in the band inside the outer edges."""
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB).astype(np.int16)
    px = lab[_band_mask(frame.shape) > 0]
    med = np.median(px, axis=0)
    mad = np.median(np.abs(px - med), axis=0)
    tol = np.minimum(np.maximum(np.array([TOL_L, TOL_A, TOL_B]), TOL_SPREAD * mad), np.array(TOL_MAX))
    return med, tol


def grass_mask(frame):
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB).astype(np.int16)
    med, tol = ground_reference(frame)
    diff = np.abs(lab - med.astype(np.int16))
    mask = np.all(diff <= tol.astype(np.int16), axis=2).astype(np.uint8) * 255
    # Remove tile-texture speckles before deciding what is "only ground".
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    for x1, y1, x2, y2 in UI_REGIONS:
        mask[y1:y2, x1:x2] = 0
    return mask


def border_mask(frame, ground):
    """Pixels of the dashed deploy border: redder and darker than their 9x9 neighbourhood and next
    to open ground."""
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    L, a, _b = cv2.split(lab)
    da = a.astype(np.int16) - cv2.medianBlur(a, 9).astype(np.int16)
    dl = L.astype(np.int16) - cv2.medianBlur(L, 9).astype(np.int16)
    relative = (da > BORDER_DA) & (dl < BORDER_DL)
    # Dark sceneries draw the border as a saturated red line (HSV H<=8 or >=172, S>=110).
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    h, sat, val = cv2.split(hsv)
    absolute = ((h <= 8) | (h >= 172)) & (sat >= 110) & (val >= 70) & (val <= 230)
    mask = (relative | absolute).astype(np.uint8) * 255
    for x1, y1, x2, y2 in UI_REGIONS:
        mask[y1:y2, x1:x2] = 0
    # The border follows the tile grid: keep only pixels on dashes that run along one of the two
    # isometric directions (grass texture and decoration outlines do not line up like that).
    unit = cv2.dilate(mask, np.ones((3, 3), np.uint8)).astype(np.float32) / 255.0
    keep = np.zeros(mask.shape, bool)
    for kernel in _LINE_KERNELS:
        keep |= cv2.filter2D(unit, -1, kernel) >= LINE_MIN_FILL
    mask[~keep] = 0
    mask = cv2.dilate(mask, np.ones((3, 3), np.uint8))
    # The border is one long connected outline; texture at the map rim leaves short pieces.
    n, labels, stats, _c = cv2.connectedComponentsWithStats(mask, connectivity=8)
    small = np.max(stats[:, [cv2.CC_STAT_WIDTH, cv2.CC_STAT_HEIGHT]], axis=1) < MIN_BORDER_EXTENT_PX
    small[0] = False
    mask[small[labels]] = 0
    return mask


def _line_kernel(slope_sign):
    k = np.zeros((LINE_KERNEL_PX, LINE_KERNEL_PX), np.float32)
    c = LINE_KERNEL_PX // 2
    dx, dy = np.cos(np.radians(ISO_ANGLE_DEG)) * c, np.sin(np.radians(ISO_ANGLE_DEG)) * c * slope_sign
    cv2.line(k, (int(round(c - dx)), int(round(c - dy))), (int(round(c + dx)), int(round(c + dy))), 1.0, 1)
    return k / k.sum()


_LINE_KERNELS = []


def _inward_normal(p1, p2):
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    length = (dx * dx + dy * dy) ** 0.5 or 1.0
    nx, ny = -dy / length, dx / length
    mx, my = (p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0
    if (_CENTER[0] - mx) * nx + (_CENTER[1] - my) * ny < 0:
        nx, ny = -nx, -ny
    dist = abs((_CENTER[0] - mx) * nx + (_CENTER[1] - my) * ny)
    return (nx, ny), dist


def edge_depths(ground, border, edge):
    """Depth (px) of the deploy border for DEPTH_SAMPLES points along `edge` (p1 -> p2)."""
    (p1, p2) = edge
    (nx, ny), dist = _inward_normal(p1, p2)
    h, w = ground.shape[:2]
    max_depth = dist * MAX_DEPTH_FRACTION
    depths = []
    for i in range(DEPTH_SAMPLES):
        t = (i + 0.5) / DEPTH_SAMPLES
        bx = p1[0] + (p2[0] - p1[0]) * t
        by = p1[1] + (p2[1] - p1[1]) * t
        depth = 0.0
        ground_run = 0.0      # continuous open ground just crossed
        entered = False       # crossed ENTER_GROUND_PX of open ground (past the map rim)
        run_start = None
        d = 0.0
        while d <= max_depth:
            x, y = int(round(bx + nx * d)), int(round(by + ny * d))
            if not (0 <= x < w and 0 <= y < h):
                break
            if ground[y, x]:
                ground_run += STEP_PX
                run_start = None
                if ground_run >= ENTER_GROUND_PX:
                    entered = True
                if entered:
                    depth = d
            else:
                ground_run = 0.0
            if border[y, x] and d >= ENTER_GROUND_PX:
                depth = d - EDGE_MARGIN_PX                # on the red line
                break
            if not ground[y, x]:
                if entered:
                    if run_start is None:
                        run_start = d
                    elif d - run_start >= BUILDING_RUN_PX:
                        depth = run_start - TILE_PX       # building: stay a tile away from it
                        break
            d += STEP_PX
        depths.append(max(0.0, depth))
    # Single rays are noisy: some slip between buildings (too deep, risky), others stop at a
    # decoration (too shallow, harmless). Take a low percentile over neighbouring rays, which
    # favours the outer side, then a short moving average.
    arr = np.array(depths)
    low = np.array([np.percentile(arr[max(0, i - SMOOTH_HALF):i + SMOOTH_HALF + 1], SMOOTH_PERCENTILE)
                    for i in range(len(arr))])
    out = np.convolve(np.pad(low, 1, mode='edge'), np.ones(3) / 3.0, mode='valid')
    return [float(v) for v in out]


def detect(frame):
    """{edge_index: [depth, ...]} for the four FOUR_SIDES edges, or None without a frame."""
    if frame is None:
        return None
    ground = grass_mask(frame)
    border = border_mask(frame, ground)
    return {i: edge_depths(ground, border, edge) for i, edge in enumerate(FOUR_SIDES)}


def depth_at(depths, t):
    """Linear interpolation of an edge's depth samples at edge parameter t (0..1, p1 -> p2)."""
    n = len(depths)
    pos = min(max(t * n - 0.5, 0.0), n - 1.0)
    i = int(pos)
    j = min(i + 1, n - 1)
    f = pos - i
    return depths[i] * (1 - f) + depths[j] * f


def point_on_line(edge_index, depths, t):
    """Screen point on the red line for edge parameter t."""
    p1, p2 = FOUR_SIDES[edge_index]
    (nx, ny), _dist = _inward_normal(p1, p2)
    d = depth_at(depths, t)
    return (p1[0] + (p2[0] - p1[0]) * t + nx * d, p1[1] + (p2[1] - p1[1]) * t + ny * d)


def shift_point(edge_index, depths, point):
    """Move a point on outer edge `edge_index` inward onto the red line."""
    p1, p2 = FOUR_SIDES[edge_index]
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    length2 = float(dx * dx + dy * dy) or 1.0
    t = ((point[0] - p1[0]) * dx + (point[1] - p1[1]) * dy) / length2
    (nx, ny), _dist = _inward_normal(p1, p2)
    d = depth_at(depths, min(max(t, 0.0), 1.0))
    return point[0] + nx * d, point[1] + ny * d


_LINE_KERNELS[:] = [_line_kernel(1), _line_kernel(-1)]
