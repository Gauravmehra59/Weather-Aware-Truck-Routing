from datetime import datetime, timedelta, timezone

import pytest

from routing.services.checkpoints import (
    build_checkpoints,
    cumulative_miles,
    cumulative_seconds_from_edges,
    cumulative_seconds_from_total,
    haversine_miles,
)

DEPARTURE = datetime(2026, 10, 30, 8, 0, tzinfo=timezone.utc)
HOUR = 3600

# One degree of latitude along a meridian.
MILES_PER_DEGREE = haversine_miles((0, 0), (1, 0))


def north(miles):
    """A point `miles` due north of (0, 0)."""
    return (miles / MILES_PER_DEGREE, 0.0)


class TestDistances:
    def test_one_degree_of_latitude(self):
        assert MILES_PER_DEGREE == pytest.approx(69.09, abs=0.01)

    def test_new_york_to_los_angeles(self):
        nyc, la = (40.7128, -74.0060), (34.0522, -118.2437)
        assert haversine_miles(nyc, la) == pytest.approx(2445, rel=0.01)

    def test_cumulative_miles(self):
        assert cumulative_miles([north(0), north(10), north(30)]) == pytest.approx([0, 10, 30])


class TestCumulativeSeconds:
    def test_from_total_is_proportional_to_distance(self):
        coords = [north(0), north(25), north(100)]
        assert cumulative_seconds_from_total(coords, 4 * HOUR) == pytest.approx(
            [0, HOUR, 4 * HOUR]
        )

    def test_from_total_with_zero_length_route(self):
        assert cumulative_seconds_from_total([north(0), north(0)], HOUR) == [0, 0]

    def test_from_edges(self):
        assert cumulative_seconds_from_edges([60, 120, 30]) == [0, 60, 180, 210]


class TestPlacement:
    def test_checkpoints_every_interval_plus_destination(self):
        coords = [north(0), north(60)]
        cps = build_checkpoints(coords, [0, 2 * HOUR], DEPARTURE, interval_miles=25)
        assert [cp.mile for cp in cps] == pytest.approx([0, 25, 50, 60])
        assert [cp.index for cp in cps] == [0, 1, 2, 3]

    def test_positions_are_interpolated_along_the_route(self):
        coords = [north(0), north(60)]
        cps = build_checkpoints(coords, [0, 2 * HOUR], DEPARTURE, interval_miles=25)
        for cp in cps:
            assert haversine_miles((0, 0), (cp.lat, cp.lon)) == pytest.approx(cp.mile)
            assert cp.lon == 0

    def test_checkpoint_on_a_later_edge(self):
        # Route goes north 20 miles, then east. The 25-mile checkpoint is 5 miles east.
        corner = north(20)
        east = (corner[0], 20 / haversine_miles(corner, (corner[0], corner[1] + 1)))
        cps = build_checkpoints([north(0), corner, east], [0, HOUR, 2 * HOUR], DEPARTURE, 25)
        assert cps[1].lat == pytest.approx(corner[0])
        assert haversine_miles(corner, (cps[1].lat, cps[1].lon)) == pytest.approx(5, abs=0.01)

    def test_exact_multiple_does_not_duplicate_destination(self):
        cps = build_checkpoints([north(0), north(50)], [0, HOUR], DEPARTURE, 25)
        assert [cp.mile for cp in cps] == pytest.approx([0, 25, 50])

    def test_destination_just_past_a_checkpoint_is_merged(self):
        cps = build_checkpoints([north(0), north(50.4)], [0, HOUR], DEPARTURE, 25)
        assert [cp.mile for cp in cps] == pytest.approx([0, 25, 50.4])
        assert sum(cp.covered_miles for cp in cps) == pytest.approx(50.4)

    def test_destination_a_mile_or_more_past_gets_its_own_checkpoint(self):
        cps = build_checkpoints([north(0), north(51)], [0, HOUR], DEPARTURE, 25)
        assert [cp.mile for cp in cps] == pytest.approx([0, 25, 50, 51])

    def test_very_short_route_keeps_origin_and_destination(self):
        cps = build_checkpoints([north(0), north(0.5)], [0, 60], DEPARTURE, 10)
        assert [cp.mile for cp in cps] == pytest.approx([0, 0.5])

    def test_route_shorter_than_interval(self):
        cps = build_checkpoints([north(0), north(8)], [0, 600], DEPARTURE, 10)
        assert [cp.mile for cp in cps] == pytest.approx([0, 8])

    def test_zero_length_edges_are_skipped(self):
        coords = [north(0), north(10), north(10), north(30)]
        cps = build_checkpoints(coords, [0, 600, 600, 1800], DEPARTURE, 10)
        assert [cp.mile for cp in cps] == pytest.approx([0, 10, 20, 30])
        assert [cp.elapsed_s for cp in cps] == pytest.approx([0, 600, 1200, 1800])


class TestEta:
    def test_eta_with_constant_speed(self):
        coords = [north(0), north(100)]
        cps = build_checkpoints(coords, [0, 4 * HOUR], DEPARTURE, 25)
        assert [cp.eta for cp in cps] == [DEPARTURE + timedelta(hours=h) for h in range(5)]

    def test_eta_uses_per_edge_speed(self):
        # First 50 miles take 1 hour (highway), the next 50 take 3 hours (city).
        coords = [north(0), north(50), north(100)]
        cps = build_checkpoints(coords, [0, HOUR, 4 * HOUR], DEPARTURE, 25)
        assert [cp.elapsed_s / HOUR for cp in cps] == pytest.approx([0, 0.5, 1, 2.5, 4])

    def test_eta_keeps_departure_timezone(self):
        ist = timezone(timedelta(hours=5, minutes=30))
        departure = datetime(2026, 10, 30, 8, 0, tzinfo=ist)
        cps = build_checkpoints([north(0), north(10)], [0, HOUR], departure, 10)
        assert cps[-1].eta == datetime(2026, 10, 30, 9, 0, tzinfo=ist)


class TestCoveredMiles:
    def test_each_checkpoint_covers_its_nearest_miles(self):
        cps = build_checkpoints([north(0), north(60)], [0, HOUR], DEPARTURE, 25)
        # gaps: 25, 25, 10
        assert [cp.covered_miles for cp in cps] == pytest.approx([12.5, 25, 17.5, 5])

    def test_covered_miles_add_up_to_route_length(self):
        coords = [north(0), north(37), north(143.7)]
        cps = build_checkpoints(coords, [0, HOUR, 3 * HOUR], DEPARTURE, 10)
        assert sum(cp.covered_miles for cp in cps) == pytest.approx(143.7)

    def test_zero_length_route_has_single_checkpoint(self):
        cps = build_checkpoints([north(0), north(0)], [0, 0], DEPARTURE, 10)
        assert len(cps) == 1
        assert cps[0].covered_miles == 0


def test_to_dict():
    cps = build_checkpoints([north(0), north(30)], [0, HOUR], DEPARTURE, 25)
    assert cps[1].to_dict() == {
        'index': 1,
        'lat': round(north(25)[0], 5),
        'lon': 0.0,
        'mile': 25.0,
        'elapsed_s': 3000,
        'eta': '2026-10-30T08:50:00+00:00',
        'covered_miles': 15.0,
    }


@pytest.mark.parametrize(
    'coords, cum_seconds, departure, interval',
    [
        ([north(0)], [0], DEPARTURE, 10),
        ([north(0), north(10)], [0], DEPARTURE, 10),
        ([north(0), north(10), north(20)], [0, 600, 300], DEPARTURE, 10),
        ([north(0), north(10)], [0, 600], DEPARTURE, 0),
        ([north(0), north(10)], [0, 600], DEPARTURE.replace(tzinfo=None), 10),
    ],
    ids=['one-point', 'length-mismatch', 'time-goes-backwards', 'zero-interval', 'naive-datetime'],
)
def test_invalid_input_is_rejected(coords, cum_seconds, departure, interval):
    with pytest.raises(ValueError):
        build_checkpoints(coords, cum_seconds, departure, interval)
