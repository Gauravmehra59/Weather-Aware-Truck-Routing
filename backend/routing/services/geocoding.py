"""Place name -> (lat, lon) using a geocoding API.

Data source: Nominatim (OpenStreetMap), keyless. Its usage policy allows at most one
request per second with an identifying User-Agent, so calls are rate-limited and
results are cached.
"""

import hashlib
from dataclasses import dataclass

import requests
from django.conf import settings
from django.core.cache import cache

from .errors import ServiceError
from .ratelimit import RateLimiter

REQUEST_TIMEOUT_S = 10
CACHE_TTL_S = 24 * 60 * 60

_limiter = RateLimiter(min_interval_s=1.0)


class GeocodingError(ServiceError):
    """The place could not be found or the geocoding service failed."""


@dataclass(frozen=True)
class Place:
    query: str
    label: str
    lat: float
    lon: float

    @property
    def point(self):
        return (self.lat, self.lon)

    def to_dict(self):
        return {'query': self.query, 'label': self.label, 'lat': self.lat, 'lon': self.lon}


def _cache_key(query):
    return 'geocode:' + hashlib.sha1(query.lower().encode()).hexdigest()


def geocode(query, session=None):
    """The best match for a free-text place name, e.g. 'Chicago, IL'."""
    query = ' '.join((query or '').split())
    if not query:
        raise GeocodingError('location is empty')

    key = _cache_key(query)
    place = cache.get(key)
    if place:
        return place

    session = session or requests.Session()
    _limiter.wait()
    try:
        response = session.get(
            settings.NOMINATIM_URL,
            params={'q': query, 'format': 'jsonv2', 'limit': 1},
            headers={'User-Agent': settings.HTTP_USER_AGENT},
            timeout=REQUEST_TIMEOUT_S,
        )
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise GeocodingError(f'geocoding service unavailable: {exc}') from exc

    if response.status_code != 200 or not isinstance(data, list):
        raise GeocodingError(f'geocoding service error: {response.status_code}')
    if not data:
        raise GeocodingError(f'could not find "{query}"')

    best = data[0]
    place = Place(
        query=query,
        label=best.get('display_name', query),
        lat=float(best['lat']),
        lon=float(best['lon']),
    )
    cache.set(key, place, CACHE_TTL_S)
    return place
