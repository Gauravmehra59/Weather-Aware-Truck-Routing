import os
from datetime import datetime, timedelta, timezone

import pytest
import requests

from routing.services import weather
from routing.services.checkpoints import build_checkpoints
from routing.services.weather import (
    WeatherError,
    fetch_forecasts,
    parse_location,
    weather_for_checkpoints,
)

from .fakes import FakeResponse

START = datetime(2026, 10, 30, 8, 0, tzinfo=timezone.utc)
HOUR = 3600


def location_payload(hours=3, start=START, **overrides):
    """Open-Meteo JSON for one location, with calm weather unless overridden."""
    hourly = {
        'time': [int(start.timestamp()) + i * HOUR for i in range(hours)],
        'wind_speed_10m': [5.0] * hours,
        'wind_gusts_10m': [10.0] * hours,
        'rain': [0.0] * hours,
        'showers': [0.0] * hours,
        'snowfall': [0.0] * hours,
    }
    hourly.update(overrides)
    return {'hourly_units': dict(weather.EXPECTED_UNITS), 'hourly': hourly}


class FakeSession:
    """Records requests and answers with calm weather for every location asked."""

    def __init__(self, respond=None):
        self.calls = []
        self.respond = respond

    def get(self, url, params, timeout):
        self.calls.append(params)
        if self.respond:
            return self.respond(params)
        start = datetime.strptime(params['start_hour'], '%Y-%m-%dT%H:%M').replace(
            tzinfo=timezone.utc
        )
        end = datetime.strptime(params['end_hour'], '%Y-%m-%dT%H:%M').replace(
            tzinfo=timezone.utc
        )
        hours = int((end - start).total_seconds() // HOUR) + 1
        count = len(params['latitude'].split(','))
        payloads = [location_payload(hours, start) for _ in range(count)]
        return FakeResponse(payloads[0] if count == 1 else payloads)


class TestParseLocation:
    def test_rain_includes_showers(self):
        forecast = parse_location(location_payload(rain=[0.1, 0, 0], showers=[0.2, 0.3, 0]))
        assert [s.rain_in_hr for s in forecast.samples] == pytest.approx([0.3, 0.3, 0])

    def test_values_and_times(self):
        forecast = parse_location(location_payload(
            wind_speed_10m=[20, 30, 40], wind_gusts_10m=[25, 35, 50], snowfall=[0, 0.5, 1.2]
        ))
        last = forecast.samples[-1]
        assert last.time == START + timedelta(hours=2)
        assert (last.wind_mph, last.gust_mph, last.snow_in_hr) == (40, 50, 1.2)

    def test_nulls_become_zero(self):
        forecast = parse_location(location_payload(snowfall=[None, 0.5, None]))
        assert [s.snow_in_hr for s in forecast.samples] == [0, 0.5, 0]

    def test_wrong_units_are_rejected(self):
        payload = location_payload()
        payload['hourly_units']['wind_speed_10m'] = 'km/h'
        with pytest.raises(WeatherError, match='wind_speed_10m'):
            parse_location(payload)

    def test_missing_variable_is_rejected(self):
        payload = location_payload()
        del payload['hourly']['snowfall']
        with pytest.raises(WeatherError, match='snowfall'):
            parse_location(payload)


class TestForecastAt:
    forecast = parse_location(location_payload(wind_speed_10m=[10, 20, 30]))

    @pytest.mark.parametrize(
        'minutes, wind',
        [(0, 10), (29, 10), (31, 20), (60, 20), (120, 30), (149, 30)],
    )
    def test_picks_nearest_hour(self, minutes, wind):
        assert self.forecast.at(START + timedelta(minutes=minutes)).wind_mph == wind

    def test_other_timezones_are_converted(self):
        ist = timezone(timedelta(hours=5, minutes=30))
        when = datetime(2026, 10, 30, 14, 30, tzinfo=ist)  # 09:00 UTC
        assert self.forecast.at(when).wind_mph == 20

    @pytest.mark.parametrize('minutes', [-31, 151])
    def test_outside_forecast_is_an_error(self, minutes):
        with pytest.raises(WeatherError):
            self.forecast.at(START + timedelta(minutes=minutes))

    def test_naive_datetime_is_rejected(self):
        with pytest.raises(ValueError):
            self.forecast.at(START.replace(tzinfo=None))


class TestFetchForecasts:
    def test_request_parameters(self):
        session = FakeSession()
        fetch_forecasts([(41.881, -87.623), (39.739, -104.99)],
                        START + timedelta(minutes=20), START + timedelta(hours=5, minutes=10),
                        session)
        params = session.calls[0]
        assert params['latitude'] == '41.8810,39.7390'
        assert params['longitude'] == '-87.6230,-104.9900'
        assert params['wind_speed_unit'] == 'mph'
        assert params['precipitation_unit'] == 'inch'
        assert params['start_hour'] == '2026-10-30T08:00'
        assert params['end_hour'] == '2026-10-30T14:00'

    def test_single_location_response(self):
        forecasts = fetch_forecasts([(41.8, -87.6)], START, START, FakeSession())
        assert len(forecasts) == 1

    def test_large_requests_are_batched(self, monkeypatch):
        monkeypatch.setattr(weather, 'MAX_LOCATIONS_PER_REQUEST', 10)
        session = FakeSession()
        points = [(40 + i / 100, -100.0) for i in range(25)]
        forecasts = fetch_forecasts(points, START, START + timedelta(hours=2), session)
        assert len(forecasts) == 25
        assert [len(c['latitude'].split(',')) for c in session.calls] == [10, 10, 5]

    def test_api_error_reason_is_shown(self):
        session = FakeSession(lambda params: FakeResponse(
            {'error': True, 'reason': "Parameter 'start_hour' is out of allowed range"}, 400
        ))
        with pytest.raises(WeatherError, match='out of allowed range'):
            fetch_forecasts([(41.8, -87.6)], START, START, session)

    def test_network_failure_is_wrapped(self):
        def fail(params):
            raise requests.ConnectionError('no internet')

        with pytest.raises(WeatherError, match='unavailable'):
            fetch_forecasts([(41.8, -87.6)], START, START, FakeSession(fail))

    def test_invalid_json_is_wrapped(self):
        session = FakeSession(lambda params: FakeResponse(ValueError('bad json')))
        with pytest.raises(WeatherError, match='unavailable'):
            fetch_forecasts([(41.8, -87.6)], START, START, session)

    def test_wrong_number_of_locations_is_rejected(self):
        session = FakeSession(lambda params: FakeResponse([location_payload()] * 3))
        with pytest.raises(WeatherError, match='asked for 2'):
            fetch_forecasts([(41.8, -87.6), (39.7, -105.0)], START, START, session)

    def test_end_before_start_is_rejected(self):
        with pytest.raises(ValueError):
            fetch_forecasts([(41.8, -87.6)], START, START - timedelta(hours=1), FakeSession())


class TestWeatherForCheckpoints:
    def test_each_checkpoint_gets_weather_at_its_eta(self):
        # 100 miles north in 4 hours -> checkpoints at 0, 1, 2, 3, 4 hours.
        coords = [(40.0, -100.0), (41.4474, -100.0)]
        checkpoints = build_checkpoints(coords, [0, 4 * HOUR], START, interval_miles=25)

        def respond(params):
            # Wind = hours after START, so we can tell which hour each checkpoint got.
            count = len(params['latitude'].split(','))
            payload = location_payload(5, wind_speed_10m=[0, 1, 2, 3, 4])
            return FakeResponse([payload] * count)

        samples = weather_for_checkpoints(checkpoints, FakeSession(respond))
        assert [s.wind_mph for s in samples] == [0, 1, 2, 3, 4]

    def test_no_checkpoints_makes_no_request(self):
        session = FakeSession()
        assert weather_for_checkpoints([], session) == []
        assert session.calls == []


@pytest.mark.skipif(not os.environ.get('RUN_LIVE_TESTS'), reason='hits the real API; run `make test-live`')
def test_live_open_meteo():
    now = datetime.now(timezone.utc)
    forecasts = fetch_forecasts([(41.88, -87.63), (39.74, -104.99)], now, now + timedelta(hours=3))
    assert len(forecasts) == 2
    assert forecasts[0].at(now + timedelta(hours=1)).wind_mph >= 0
