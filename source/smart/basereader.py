# smart/basereader.py - pick the entry side from the enemy base itself (no AI).
#
# The dragon strategies start from one of three fixed outer edges and normally take the edge whose
# MIDPOINT is nearest the Town Hall. That ignores the shape of the base: a base pushed into one
# corner, or with a deep empty margin on one side, has a much shorter real flight from another edge.
# With "Shortest real path" the bot uses its red-line detector (attack/redline.py: where troops can
# actually be dropped) and takes the edge whose deploy line comes closest to the Town Hall.
from attack import redline
from attack.geometry import FOUR_SIDES, THREE_SIDES

# THREE_SIDES[i] is the same edge as FOUR_SIDES[j] (drawn in the other direction)
THREE_TO_FOUR = {0: 3, 1: 2, 2: 1}
SAMPLES = 24


def side_distances(frame, th_pos):
    """{three-side index: px from the Town Hall to the nearest deploy point on that edge} or None."""
    depths = redline.detect(frame)
    if not depths:
        return None
    out = {}
    for three, four in THREE_TO_FOUR.items():
        if four not in depths:
            continue
        best = None
        for i in range(SAMPLES + 1):
            x, y = redline.point_on_line(four, depths[four], i / SAMPLES)
            d = ((x - th_pos[0]) ** 2 + (y - th_pos[1]) ** 2) ** 0.5
            best = d if best is None else min(best, d)
        out[three] = best
    return out or None


def entry_point(cfg, vision, th_pos):
    """A point that makes the strategy choose the edge with the shortest real path, or None."""
    distances = side_distances(vision.grab(), th_pos)
    if not distances:
        return None
    best = min(distances, key=distances.get)
    (x1, y1), (x2, y2) = THREE_SIDES[best]
    names = {0: 'bottom right', 1: 'top right', 2: 'top left'}
    print(f"[SMART] Entry side: {names[best]} "
          f"({', '.join(f'{names[k]} {int(v)} px' for k, v in sorted(distances.items()))})")
    return (x1 + x2) // 2, (y1 + y2) // 2
