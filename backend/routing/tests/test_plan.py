"""The /api/plan/ endpoint and the planner pipeline, with external services faked."""

from datetime import datetime, timedelta, timezone

import pytest
from django.test import Client
from django.utils import timezone as dj_timezone

from routing.services import planner
from routing.services.geocoding import GeocodingError, Place
from routing.services.routing_api import Route
from routing.services.weather import WeatherError, WeatherSample

HOUR = 3600


def straight_route(lat, miles_per_degree=69.09, degrees=1.0, hours=2.0, points=200):
    """A route due east along `lat` with evenly spaced points."""
    coords = tuple((lat, -100 + degrees * i / (points - 1)) for i in range(points))
    cum = tuple(hours * HOUR * i / (points - 1) for i in range(points))
    return Route(coords=coords, cum_seconds=cum, distance_miles=0, duration_s=hours * HOUR)


FAST = straight_route(40.0, hours=2.0)
SLOW = straight_route(41.0, hours=3.0)


@pytest.fixture
def fake_services(monkeypatch):
    """Fake geocoding, routing and weather. Weather per route is set via `storms`."""
    storms = {}  # latitude -> wind mph on that route

    def fake_geocode(query):
        return Place(query=query, label=f'{query}, USA', lat=40.0, lon=-100.0)

    def fake_weather(checkpoints):
        return [
            WeatherSample(
                time=cp.eta, wind_mph=storms.get(round(cp.lat), 5.0),
                gust_mph=10.0, rain_in_hr=0.0, snow_in_hr=0.0,
            )
            for cp in checkpoints
        ]

    monkeypatch.setattr(planner, 'geocode', fake_geocode)
    monkeypatch.setattr(planner, 'fetch_routes', lambda o, d: [FAST, SLOW])
    monkeypatch.setattr(planner, 'weather_for_checkpoints', fake_weather)
    return storms


def departure_in(hours):
    return (dj_timezone.now() + timedelta(hours=hours)).replace(microsecond=0)


def post(payload):
    return Client().post('/api/plan/', payload, content_type='application/json')


def valid_payload(**overrides):
    payload = {
        'origin': 'Chicago, IL',
        'destination': 'Denver, CO',
        'departure': departure_in(2).isoformat(),
        'load_lb': 35_000,
        'interval_miles': 25,
    }
    payload.update(overrides)
    return payload


class TestPlanner:
    DEPARTURE = datetime(2026, 10, 30, 8, 0, tzinfo=timezone.utc)

    def test_calm_weather_recommends_fastest(self, fake_services):
        result = planner.plan_trip('Chicago', 'Denver', self.DEPARTURE, 35_000, 25)
        assert result['recommended_route_id'] == 'A'
        assert result['reason'] == 'shortest travel time'
        assert [r['id'] for r in result['routes']] == ['A', 'B']

    def test_storm_on_fast_route_recommends_slower_one(self, fake_services):
        fake_services[40] = 50  # Severe wind on route A (lat 40)
        result = planner.plan_trip('Chicago', 'Denver', self.DEPARTURE, 20_000, 25)
        assert result['recommended_route_id'] == 'B'
        assert result['reason'] == 'fewest Severe miles'
        assert [r['id'] for r in result['routes']] == ['B', 'A']

    def test_load_rule_changes_outcome(self, fake_services):
        fake_services[40] = 50
        fake_services[41] = 50  # both routes Severe for a light truck
        light = planner.plan_trip('Chicago', 'Denver', self.DEPARTURE, 20_000, 25)
        heavy = planner.plan_trip('Chicago', 'Denver', self.DEPARTURE, 35_000, 25)
        assert light['travel_advised'] is True
        assert heavy['travel_advised'] is False

    def test_checkpoint_payload(self, fake_services):
        result = planner.plan_trip('Chicago', 'Denver', self.DEPARTURE, 35_000, 25)
        route = result['routes'][0]
        cp = route['checkpoints'][1]
        assert cp['mile'] == 25.0
        assert cp['weather']['wind_mph'] == 5.0
        assert cp['risk']['level'] == 'Low'
        assert datetime.fromisoformat(cp['eta']) > self.DEPARTURE

    def test_route_payload(self, fake_services):
        result = planner.plan_trip('Chicago', 'Denver', self.DEPARTURE, 35_000, 25)
        route = result['routes'][0]
        assert route['duration_s'] == 2 * HOUR
        assert route['is_detour'] is False
        assert route['distance_miles'] == pytest.approx(52.9, abs=0.2)
        # A straight line simplifies to just its two ends.
        assert route['geometry'] == [[40.0, -100.0], [40.0, -99.0]]

    def test_picked_suggestion_skips_geocoding(self, fake_services, monkeypatch):
        def must_not_geocode(query):
            raise AssertionError('geocode should not be called')

        routed = []
        monkeypatch.setattr(planner, 'geocode', must_not_geocode)
        monkeypatch.setattr(planner, 'fetch_routes', lambda o, d: routed.append((o, d)) or [FAST])
        result = planner.plan_trip(
            'Springfield, Missouri, US', 'Tulsa, Oklahoma, US', self.DEPARTURE, 35_000, 25,
            origin_point=(37.21, -93.29), destination_point=(36.15, -95.99),
        )
        assert routed == [((37.21, -93.29), (36.15, -95.99))]
        assert result['origin']['label'] == 'Springfield, Missouri, US'

    def test_point_for_one_end_only(self, fake_services):
        result = planner.plan_trip('Chicago', 'Denver', self.DEPARTURE, 35_000, 25,
                                   origin_point=(41.88, -87.62))
        assert result['origin']['lat'] == 41.88
        assert result['destination']['label'] == 'Denver, USA'  # geocoded

    def test_echoes_inputs(self, fake_services):
        result = planner.plan_trip('Chicago', 'Denver', self.DEPARTURE, 35_000, 10)
        assert result['origin']['label'] == 'Chicago, USA'
        assert result['departure'] == '2026-10-30T08:00:00+00:00'
        assert result['interval_miles'] == 10
        assert len(result['routes'][0]['checkpoints']) == 7  # 0,10,...,50 + 52.9


class TestPlanEndpoint:
    def test_success(self, fake_services):
        response = post(valid_payload())
        assert response.status_code == 200
        assert response.json()['recommended_route_id'] == 'A'

    def test_interval_defaults_to_25(self, fake_services):
        payload = valid_payload()
        del payload['interval_miles']
        assert post(payload).json()['interval_miles'] == 25

    def test_departure_offset_is_respected(self, fake_services):
        ist = timezone(timedelta(hours=5, minutes=30))
        local = departure_in(3).astimezone(ist)
        result = post(valid_payload(departure=local.isoformat())).json()
        assert datetime.fromisoformat(result['departure']) == local

    @pytest.mark.parametrize(
        'overrides, field',
        [
            ({'interval_miles': 15}, 'interval_miles'),
            ({'load_lb': -1}, 'load_lb'),
            ({'load_lb': 500_000}, 'load_lb'),
            ({'origin': ''}, 'origin'),
            ({'departure': 'tomorrow'}, 'departure'),
            ({'departure': departure_in(-3).isoformat()}, 'departure'),
            ({'departure': departure_in(24 * 20).isoformat()}, 'departure'),
            ({'destination': ' chicago, il '}, 'non_field_errors'),
        ],
    )
    def test_invalid_input(self, fake_services, overrides, field):
        response = post(valid_payload(**overrides))
        assert response.status_code == 400
        assert field in response.json()

    def test_missing_fields(self):
        response = post({})
        assert response.status_code == 400
        assert set(response.json()) == {'origin', 'destination', 'departure', 'load_lb'}

    def test_accepts_points(self, fake_services):
        response = post(valid_payload(origin_point=[41.88, -87.62], destination_point=[39.74, -104.99]))
        assert response.status_code == 200
        assert response.json()['origin']['lat'] == 41.88

    @pytest.mark.parametrize('point', [[41.88], [41.88, -87.62, 1], [95, 0], 'chicago'])
    def test_invalid_points(self, point):
        response = post(valid_payload(origin_point=point))
        assert response.status_code == 400
        assert 'origin_point' in response.json()

    def test_service_error_message_reaches_user(self, fake_services, monkeypatch):
        def not_found(query):
            raise GeocodingError(f'could not find "{query}"')

        monkeypatch.setattr(planner, 'geocode', not_found)
        response = post(valid_payload(origin='Xyzzyville'))
        assert response.status_code == 422
        assert response.json() == {'detail': 'could not find "Xyzzyville"'}

    def test_weather_failure(self, fake_services, monkeypatch):
        def down(checkpoints):
            raise WeatherError('weather service unavailable: timeout')

        monkeypatch.setattr(planner, 'weather_for_checkpoints', down)
        response = post(valid_payload())
        assert response.status_code == 422
        assert 'unavailable' in response.json()['detail']

    def test_get_is_not_allowed(self):
        assert Client().get('/api/plan/').status_code == 405
