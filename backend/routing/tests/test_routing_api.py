import os

import pytest
import requests

from routing.services import routing_api
from routing.services.checkpoints import haversine_miles
from routing.services.routing_api import (
    METERS_PER_MILE,
    Route,
    RoutingError,
    detour_point,
    fetch_routes,
    overlap,
    parse_route,
)

from .fakes import FakeResponse, FakeSession

CHICAGO = (41.88, -87.63)
DENVER = (39.74, -104.99)


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(routing_api._limiter, 'min_interval_s', 0)


def line(start, end, points=50):
    """Evenly spaced (lat, lon) points from start to end."""
    (lat1, lon1), (lat2, lon2) = start, end
    return [
        (lat1 + (lat2 - lat1) * i / (points - 1), lon1 + (lon2 - lon1) * i / (points - 1))
        for i in range(points)
    ]


def osrm_route(coords, duration_s, legs=1):
    """OSRM-shaped route JSON for (lat, lon) coords with equal per-edge durations."""
    edges = len(coords) - 1
    per_edge = duration_s / edges
    split = [edges // legs + (1 if i < edges % legs else 0) for i in range(legs)]
    distance_m = sum(haversine_miles(a, b) for a, b in zip(coords, coords[1:])) * METERS_PER_MILE
    return {
        'geometry': {'type': 'LineString', 'coordinates': [[lon, lat] for lat, lon in coords]},
        'duration': duration_s,
        'distance': distance_m,
        'legs': [{'annotation': {'duration': [per_edge] * n}} for n in split],
    }


def ok(*routes):
    return FakeResponse({'code': 'Ok', 'routes': list(routes)})


def via_count(call):
    """Number of waypoints in an OSRM request URL."""
    return call['url'].rsplit('/', 1)[1].count(';') + 1


class TestParseRoute:
    def test_flips_geojson_to_lat_lon(self):
        route = parse_route(osrm_route([(41.0, -87.0), (40.0, -90.0)], 600))
        assert route.coords == ((41.0, -87.0), (40.0, -90.0))

    def test_distance_in_miles(self):
        raw = osrm_route([(41.0, -87.0), (40.0, -90.0)], 600)
        raw['distance'] = 16093.44
        assert parse_route(raw).distance_miles == pytest.approx(10)

    def test_uses_per_edge_durations(self):
        raw = osrm_route([(0, 0), (0.1, 0), (0.2, 0)], 300)
        raw['legs'][0]['annotation']['duration'] = [100, 200]
        assert parse_route(raw).cum_seconds == pytest.approx((0, 100, 300))

    def test_edge_durations_are_scaled_to_route_total(self):
        raw = osrm_route([(0, 0), (0.1, 0), (0.2, 0)], 330)
        raw['legs'][0]['annotation']['duration'] = [100, 200]
        assert parse_route(raw).cum_seconds == pytest.approx((0, 110, 330))

    def test_joins_legs_of_a_route_through_a_waypoint(self):
        coords = line((0, 0), (1, 0), points=11)
        route = parse_route(osrm_route(coords, 1000, legs=2))
        assert len(route.cum_seconds) == 11
        assert route.cum_seconds[-1] == pytest.approx(1000)

    def test_falls_back_to_distance_when_annotations_missing(self):
        raw = osrm_route([(0, 0), (0.1, 0), (0.3, 0)], 300)
        del raw['legs']
        assert parse_route(raw).cum_seconds == pytest.approx((0, 100, 300))


class TestDetourPoint:
    def test_left_of_eastward_trip_is_north(self):
        lat, lon = detour_point((40, -100), (40, -90), 0.2)
        assert lat > 40
        assert lon == pytest.approx(-95)

    def test_right_of_eastward_trip_is_south(self):
        lat, _ = detour_point((40, -100), (40, -90), -0.2)
        assert lat < 40

    def test_offset_is_fraction_of_trip_length(self):
        origin, destination = CHICAGO, DENVER
        mid = ((origin[0] + destination[0]) / 2, (origin[1] + destination[1]) / 2)
        via = detour_point(origin, destination, 0.15)
        assert haversine_miles(mid, via) == pytest.approx(
            0.15 * haversine_miles(origin, destination), rel=0.02
        )


class TestOverlap:
    def test_same_road_is_full_overlap(self):
        a = parse_route(osrm_route(line(CHICAGO, DENVER), 3600))
        assert overlap(a, a) == 1

    def test_far_apart_roads_do_not_overlap(self):
        a = parse_route(osrm_route(line((40, -100), (40, -90)), 3600))
        b = parse_route(osrm_route(line((35, -100), (35, -90)), 3600))
        assert overlap(a, b) == 0

    def test_route_sharing_half_its_road(self):
        shared = line((40, -100), (40, -95), 25)
        a = parse_route(osrm_route(shared + line((40, -95), (40, -90), 25), 3600))
        b = parse_route(osrm_route(shared + line((38, -95), (38, -90), 25), 3600))
        assert overlap(b, a) == pytest.approx(0.5, abs=0.1)


class TestFetchRoutes:
    fast = osrm_route(line(CHICAGO, DENVER), 16 * 3600)
    north = osrm_route(line(CHICAGO, (43.5, -96)) + line((43.5, -96), DENVER), 18 * 3600)
    south = osrm_route(line(CHICAGO, (38, -96)) + line((38, -96), DENVER), 19 * 3600)

    def test_three_routes_from_osrm_need_no_detours(self):
        session = FakeSession(lambda url, params: ok(self.south, self.fast, self.north))
        routes = fetch_routes(CHICAGO, DENVER, session)
        assert len(session.calls) == 1
        assert session.calls[0]['params']['alternatives'] == 2
        assert [r.duration_s / 3600 for r in routes] == [16, 18, 19]
        assert all(r.detour_via is None for r in routes)

    def test_request_url_and_user_agent(self, settings):
        settings.OSRM_URL = 'https://osrm.test'
        settings.HTTP_USER_AGENT = 'test-agent/1.0'
        session = FakeSession(lambda url, params: ok(self.fast, self.north, self.south))
        fetch_routes(CHICAGO, DENVER, session)
        call = session.calls[0]
        assert call['url'] == 'https://osrm.test/route/v1/driving/-87.630000,41.880000;-104.990000,39.740000'
        assert call['headers'] == {'User-Agent': 'test-agent/1.0'}
        assert call['params']['annotations'] == 'duration'

    def test_missing_alternatives_are_filled_with_detours(self):
        detours = iter([self.north, self.south])

        def respond(url, params):
            return ok(self.fast) if params['alternatives'] == 2 else ok(next(detours))

        session = FakeSession(respond)
        routes = fetch_routes(CHICAGO, DENVER, session)
        assert len(routes) == 3
        assert [via_count(c) for c in session.calls] == [2, 3, 3]
        assert routes[0].detour_via is None
        assert routes[1].detour_via is not None and routes[2].detour_via is not None

    def test_detour_that_repeats_an_existing_road_is_rejected(self):
        detours = iter([self.fast, self.north, self.south])

        def respond(url, params):
            return ok(self.fast) if params['alternatives'] == 2 else ok(next(detours))

        routes = fetch_routes(CHICAGO, DENVER, FakeSession(respond))
        assert [r.duration_s / 3600 for r in routes] == [16, 18, 19]

    def test_detour_that_is_too_slow_is_rejected(self):
        slow = osrm_route(line(CHICAGO, (46, -96)) + line((46, -96), DENVER), 30 * 3600)
        detours = iter([slow, self.north, self.south])

        def respond(url, params):
            return ok(self.fast) if params['alternatives'] == 2 else ok(next(detours))

        routes = fetch_routes(CHICAGO, DENVER, FakeSession(respond))
        assert [r.duration_s / 3600 for r in routes] == [16, 18, 19]

    def test_unroutable_detour_is_skipped(self):
        answers = iter([
            ok(self.fast),
            FakeResponse({'code': 'NoRoute', 'message': 'Impossible route'}, 400),
            ok(self.north),
            ok(self.south),
        ])
        routes = fetch_routes(CHICAGO, DENVER, FakeSession(lambda url, params: next(answers)))
        assert len(routes) == 3

    def test_returns_fewer_routes_when_no_detour_is_good_enough(self):
        session = FakeSession(lambda url, params: ok(self.fast))
        routes = fetch_routes(CHICAGO, DENVER, session)
        assert len(routes) == 1
        assert len(session.calls) == 1 + len(routing_api.DETOUR_OFFSETS)

    def test_no_route_between_points(self):
        session = FakeSession(lambda url, params: FakeResponse(
            {'code': 'NoRoute', 'message': 'Impossible route between points'}, 400
        ))
        with pytest.raises(RoutingError, match='Impossible route between points'):
            fetch_routes(CHICAGO, (30.0, -30.0), session)

    def test_network_failure(self):
        def fail(url, params):
            raise requests.ConnectionError('down')

        with pytest.raises(RoutingError, match='unavailable'):
            fetch_routes(CHICAGO, DENVER, FakeSession(fail))


def test_route_is_hashable_value_object():
    route = parse_route(osrm_route(line(CHICAGO, DENVER), 3600))
    assert isinstance(route, Route)
    assert hash(route) == hash(parse_route(osrm_route(line(CHICAGO, DENVER), 3600)))


@pytest.mark.skipif(not os.environ.get('RUN_LIVE_TESTS'), reason='hits the real API; run `make test-live`')
def test_live_osrm():
    routes = fetch_routes(CHICAGO, DENVER)
    assert 1 <= len(routes) <= 3
    assert all(900 < r.distance_miles < 1400 for r in routes)
    assert routes == sorted(routes, key=lambda r: r.duration_s)
