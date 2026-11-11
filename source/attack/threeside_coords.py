# attack.threeside_coords - Reconstructed from attack.threeside_coords.dis.txt (Pyarmor 015394, Python 3.10).
from attack.geometry import THREE_SIDES


def line_points(p1, p2, count):
    # Evenly spaced points from p1 to p2 INCLUSIVE of both endpoints.
    n = count
    x1, y1 = p1
    x2, y2 = p2
    points = []
    for i in range(n):
        t = i / (n - 1)          # NOTE: ZeroDivisionError when count == 1 (as in original)
        x = int(x1 + (x2 - x1) * t)
        y = int(y1 + (y2 - y1) * t)
        points.append((x, y))
    return points


def interleave_lists(lists):
    src = lists
    result = []
    longest = max(len(lst) for lst in src)
    for i in range(longest):
        for lst in src:
            if i < len(lst):
                result.append(lst[i])
    return result


def generate_perimeter_coords(count=42):
    # Split `count` points evenly across the 3 sides (remainder goes to the
    # first sides), then round-robin interleave so consecutive taps alternate sides.
    total = count
    sides = THREE_SIDES
    per_side = total // len(sides)
    remainder = total % len(sides)
    counts = [per_side] * len(sides)
    for i in range(remainder):
        counts[i] += 1
    per_side_points = [line_points(p1, p2, n) for (p1, p2), n in zip(sides, counts)]
    return interleave_lists(per_side_points)
