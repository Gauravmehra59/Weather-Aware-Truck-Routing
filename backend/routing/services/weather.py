"""Hourly forecast (wind mph, rain in/hr, snow in/hr) for a point at a given time.

Data source: Open-Meteo (https://open-meteo.com), free and keyless.

Choices:
- Units are requested from the API (wind_speed_unit=mph, precipitation_unit=inch) and
  checked against `hourly_units` in the response, so a silent unit change fails loudly.
- Rain = Open-Meteo `rain` + `showers`. `rain` alone excludes convective showers
  (thunderstorms), which are exactly the heavy-rain cases we care about.
- Wind risk uses sustained 10 m wind speed. Gusts are returned for display only.
- Precipitation values are totals for the preceding hour, i.e. already per hour.
- A time is matched to the nearest forecast hour.
- Missing (null) values are treated as 0.
- Locations are batched, up to MAX_LOCATIONS_PER_REQUEST per HTTP call.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests

from .errors import ServiceError

OPEN_METEO_URL = 'https://api.open-meteo.com/v1/forecast'

EXPECTED_UNITS = {
    'wind_speed_10m': 'mp/h',
    'wind_gusts_10m': 'mp/h',
    'rain': 'inch',
    'showers': 'inch',
    'snowfall': 'inch',
}

MAX_LOCATIONS_PER_REQUEST = 100
REQUEST_TIMEOUT_S = 15
HOUR = timedelta(hours=1)


class WeatherError(ServiceError):
    """The forecast could not be fetched or understood."""


@dataclass(frozen=True)
class WeatherSample:
    time: datetime  # UTC, on the hour
    wind_mph: float
    gust_mph: float
    rain_in_hr: float
    snow_in_hr: float

    def to_dict(self):
        return {
            'time': self.time.isoformat(),
            'wind_mph': round(self.wind_mph, 1),
            'gust_mph': round(self.gust_mph, 1),
            'rain_in_hr': round(self.rain_in_hr, 3),
            'snow_in_hr': round(self.snow_in_hr, 3),
        }


@dataclass(frozen=True)
class HourlyForecast:
    samples: tuple  # WeatherSample, one per consecutive hour

    def at(self, when):
        """The forecast hour closest to `when` (a timezone-aware datetime)."""
        if when.tzinfo is None or when.utcoffset() is None:
            raise ValueError('when must be timezone-aware')
        if not self.samples:
            raise WeatherError('forecast has no hours')

        start = self.samples[0].time
        index = round((when - start) / HOUR)
        if not 0 <= index < len(self.samples):
            raise WeatherError(f'no forecast for {when.isoformat()}')
        return self.samples[index]


def _floor_hour(dt):
    return dt.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def _ceil_hour(dt):
    floored = _floor_hour(dt)
    return floored if floored == dt else floored + HOUR


def _values(hourly, name, length):
    values = hourly.get(name)
    if values is None or len(values) != length:
        raise WeatherError(f'forecast is missing hourly {name}')
    return [0.0 if v is None else float(v) for v in values]


def parse_location(payload):
    """Turn one location's Open-Meteo JSON into an HourlyForecast."""
    units = payload.get('hourly_units', {})
    for name, expected in EXPECTED_UNITS.items():
        if units.get(name) != expected:
            raise WeatherError(f'expected {name} in {expected}, got {units.get(name)!r}')

    hourly = payload.get('hourly', {})
    times = hourly.get('time') or []
    n = len(times)
    wind = _values(hourly, 'wind_speed_10m', n)
    gust = _values(hourly, 'wind_gusts_10m', n)
    rain = _values(hourly, 'rain', n)
    showers = _values(hourly, 'showers', n)
    snow = _values(hourly, 'snowfall', n)

    return HourlyForecast(tuple(
        WeatherSample(
            time=datetime.fromtimestamp(times[i], tz=timezone.utc),
            wind_mph=wind[i],
            gust_mph=gust[i],
            rain_in_hr=rain[i] + showers[i],
            snow_in_hr=snow[i],
        )
        for i in range(n)
    ))


def _request(session, points, start, end):
    params = {
        'latitude': ','.join(f'{lat:.4f}' for lat, _ in points),
        'longitude': ','.join(f'{lon:.4f}' for _, lon in points),
        'hourly': ','.join(EXPECTED_UNITS),
        'wind_speed_unit': 'mph',
        'precipitation_unit': 'inch',
        'timezone': 'GMT',
        'timeformat': 'unixtime',
        'start_hour': f'{start:%Y-%m-%dT%H:%M}',
        'end_hour': f'{end:%Y-%m-%dT%H:%M}',
    }
    try:
        response = session.get(OPEN_METEO_URL, params=params, timeout=REQUEST_TIMEOUT_S)
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise WeatherError(f'weather service unavailable: {exc}') from exc

    if response.status_code != 200 or (isinstance(data, dict) and data.get('error')):
        reason = data.get('reason') if isinstance(data, dict) else None
        raise WeatherError(f'weather service error: {reason or response.status_code}')

    # One location -> a single object, several -> a list in request order.
    locations = data if isinstance(data, list) else [data]
    if len(locations) != len(points):
        raise WeatherError(f'asked for {len(points)} locations, got {len(locations)}')
    return [parse_location(location) for location in locations]


def fetch_forecasts(points, start, end, session=None):
    """Hourly forecasts from `start` to `end` (inclusive) for each (lat, lon) point."""
    if end < start:
        raise ValueError('end must not be before start')
    session = session or requests.Session()
    start, end = _floor_hour(start), _ceil_hour(end)

    forecasts = []
    for i in range(0, len(points), MAX_LOCATIONS_PER_REQUEST):
        chunk = points[i:i + MAX_LOCATIONS_PER_REQUEST]
        forecasts.extend(_request(session, chunk, start, end))
    return forecasts


def weather_for_checkpoints(checkpoints, session=None):
    """The forecast at each checkpoint for the hour the truck gets there."""
    if not checkpoints:
        return []
    etas = [cp.eta for cp in checkpoints]
    forecasts = fetch_forecasts(
        [(cp.lat, cp.lon) for cp in checkpoints], min(etas), max(etas), session
    )
    return [forecast.at(cp.eta) for forecast, cp in zip(forecasts, checkpoints)]
