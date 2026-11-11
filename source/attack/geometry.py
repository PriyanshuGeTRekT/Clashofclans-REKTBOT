# attack.geometry - Reconstructed from attack.geometry.dis.txt (Pyarmor 015394, Python 3.10).
# Screen-space deploy edges of the (zoomed-out) enemy village diamond.
# Each side is ((x1, y1), (x2, y2)).

FOUR_SIDES = [
    ((385, 624), (160, 456)),
    ((163, 414), (690, 24)),
    ((913, 17), (1399, 381)),
    ((1415, 466), (1112, 711)),
]

FOUR_SIDES_REVERSED = [
    ((1123, 711), (1451, 460)),
    ((1444, 398), (949, 26)),
    ((658, 22), (167, 392)),
    ((168, 465), (476, 701)),
]

# The 3-side set is the first three edges of FOUR_SIDES_REVERSED
# (bottom-right, top-right, top-left; bottom-left edge excluded).
THREE_SIDES = [FOUR_SIDES_REVERSED[0], FOUR_SIDES_REVERSED[1], FOUR_SIDES_REVERSED[2]]
