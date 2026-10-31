import math

import pytest

from routing.services.geometry import _offset, simplify


def test_short_lines_are_unchanged():
    assert simplify([], 0.1) == []
    assert simplify([(0, 0)], 0.1) == [(0, 0)]
    assert simplify([(0, 0), (1, 1)], 0.1) == [(0, 0), (1, 1)]


def test_straight_line_keeps_only_ends():
    line = [(0, i / 10) for i in range(101)]
    assert simplify(line, 0.001) == [(0, 0), (0, 10)]


def test_corner_is_kept():
    path = [(0, 0), (0, 1), (0, 2), (1, 2), (2, 2)]
    assert simplify(path, 0.01) == [(0, 0), (0, 2), (2, 2)]


def test_wiggles_within_tolerance_are_dropped():
    path = [(0, 0), (0.0001, 1), (-0.0001, 2), (0, 3)]
    assert simplify(path, 0.001) == [(0, 0), (0, 3)]


def test_wiggles_beyond_tolerance_are_kept():
    path = [(0, 0), (0.01, 1), (0, 2)]
    assert simplify(path, 0.001) == path


def test_every_dropped_point_stays_within_tolerance():
    path = [(math.sin(i / 20) * 0.5, i / 100) for i in range(2000)]
    kept = simplify(path, 0.001)
    assert len(kept) < len(path) / 2
    # Each original point lies within tolerance of the simplified line.
    j = 0
    for point in path:
        while point[1] > kept[j + 1][1]:
            j += 1
        assert _offset(point, kept[j], kept[j + 1]) <= 0.001 + 1e-12


def test_loop_back_to_start():
    path = [(0, 0), (0, 1), (1, 1), (1, 0), (0, 0)]
    assert simplify(path, 0.01) == path


def test_long_route_does_not_hit_recursion_limit():
    # A zig-zag where every point matters splits ~1500 levels deep, past Python's
    # default recursion limit of 1000.
    path = [(i % 2 * 0.01, i * 0.001) for i in range(1_500)]
    assert len(simplify(path, 0.001)) == pytest.approx(1_500, rel=0.01)
