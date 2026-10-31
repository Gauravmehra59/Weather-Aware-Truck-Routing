"""Shrink route geometry for the map without changing its shape.

Routing APIs return ~10 points per mile, far more than a map line needs, and sending
them all would make every response hundreds of KB. Ramer–Douglas–Peucker keeps only the
points needed to stay within `tolerance_deg` of the original line.
"""


def _offset(point, start, end):
    """Distance from `point` to the line through `start` and `end`, in degrees."""
    (y, x), (y1, x1), (y2, x2) = point, start, end
    dx, dy = x2 - x1, y2 - y1
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
    # Project onto the segment, clamped so points past either end measure to that end.
    t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / length_sq))
    return ((x - x1 - t * dx) ** 2 + (y - y1 - t * dy) ** 2) ** 0.5


def simplify(coords, tolerance_deg):
    """Ramer–Douglas–Peucker over (lat, lon) points. Always keeps the first and last."""
    coords = list(coords)
    if len(coords) < 3:
        return coords

    keep = [False] * len(coords)
    keep[0] = keep[-1] = True
    # Iterative rather than recursive: long routes would hit Python's recursion limit.
    stack = [(0, len(coords) - 1)]
    while stack:
        first, last = stack.pop()
        worst, worst_index = 0.0, None
        for i in range(first + 1, last):
            d = _offset(coords[i], coords[first], coords[last])
            if d > worst:
                worst, worst_index = d, i
        if worst_index is not None and worst > tolerance_deg:
            keep[worst_index] = True
            stack.append((first, worst_index))
            stack.append((worst_index, last))

    return [point for point, kept in zip(coords, keep) if kept]
