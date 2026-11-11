# attack.fourside_coords - Reconstructed from attack.fourside_coords.dis.txt (Pyarmor 015394, Python 3.10).
import math
from attack.geometry import FOUR_SIDES_REVERSED


def line_points(p1, p2, count):
    # Evenly spaced points strictly BETWEEN p1 and p2 (endpoints excluded):
    # t = (i + 1) / (count + 1).
    n = count
    x1, y1 = p1
    x2, y2 = p2
    points = []
    for i in range(n):
        t = (i + 1) / (n + 1)
        x = int(x1 + (x2 - x1) * t)
        y = int(y1 + (y2 - y1) * t)
        points.append((x, y))
    return points


def interleave_lists(lists):
    # Defined but not used by generate_perimeter_coords in this module.
    src = lists
    result = []
    longest = max(len(lst) for lst in src)
    for i in range(longest):
        for lst in src:
            if i < len(lst):
                result.append(lst[i])
    return result


def generate_perimeter_coords(count):
    # Distribute `count` points over the 4 sides proportionally to side length,
    # then hand leftover points (from int() truncation) round-robin.
    # Sides are emitted one after another (NOT interleaved).
    total_count = count
    sides = FOUR_SIDES_REVERSED
    lengths = []
    for start, end in sides:
        lengths.append(math.hypot(end[0] - start[0], end[1] - start[1]))
    total_length = sum(lengths)
    raw = [length / total_length * total_count for length in lengths]
    counts = [int(v) for v in raw]
    leftover = total_count - sum(counts)
    for i in range(leftover):
        counts[i % len(counts)] += 1
    coords = []
    for (start, end), n in zip(sides, counts):
        if n <= 0:
            continue
        pts = line_points(start, end, n)
        coords.extend(pts)
    return coords
