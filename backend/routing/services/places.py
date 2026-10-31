"""Place suggestions while the user types (autocomplete).

Data source: Photon (https://photon.komoot.io), built for search-as-you-type on
OpenStreetMap data. Nominatim, used for one-off geocoding, forbids autocomplete in its
usage policy, so suggestions use a different service.

Photon's public server asks for fair use: the frontend debounces keystrokes, and
results are cached here so repeated prefixes don't hit the API again.
"""

import hashlib

import requests
from django.conf import settings
from django.core.cache import cache

from .errors import ServiceError
from .ratelimit import RateLimiter

MIN_QUERY_LENGTH = 3
MAX_SUGGESTIONS = 6
REQUEST_TIMEOUT_S = 5
CACHE_TTL_S = 24 * 60 * 60
# Nudge ranking toward the continental US at country scale (zoom 4). Photon's default
# zoom is street-level, which pulled in cemeteries and schools near the bias point.
BIAS_POINT = (39.5, -98.35)
BIAS_ZOOM = 4
# Places, addresses and streets; leaves out POIs ("other": schools, cemeteries, ...).
LAYERS = ('city', 'district', 'locality', 'county', 'house', 'street')
# Shown first (other countries still appear after them): the app works in mph and lb.
PREFERRED_COUNTRIES = {'US', 'CA', 'MX'}

_limiter = RateLimiter(min_interval_s=0.2)
_session = None


def _get_session():
    global _session
    if not isinstance(requests.Session, type):
        return requests.Session()
    if _session is None:
        _session = requests.Session()
    return _session


class PlaceSearchError(ServiceError):
    """The suggestion service failed."""


def _label(props):
    """'Chicago, Illinois, US' or '1600 Pennsylvania Avenue NW, Washington, DC, US'."""
    street = ' '.join(filter(None, [props.get('housenumber'), props.get('street')]))
    name = props.get('name')
    parts = [name, street if street != name else None, props.get('city'), props.get('state'),
             props.get('countrycode')]
    seen, label = set(), []
    for part in parts:
        if part and part not in seen:
            seen.add(part)
            label.append(part)
    return ', '.join(label)


def parse_suggestions(data):
    """Photon GeoJSON -> [{'label', 'lat', 'lon'}], North America first, no duplicate labels."""
    features = sorted(
        data.get('features', []),
        # Stable sort: keeps Photon's relevance order within each group.
        key=lambda f: f.get('properties', {}).get('countrycode') not in PREFERRED_COUNTRIES,
    )
    suggestions, labels = [], set()
    for feature in features:
        lon, lat = feature['geometry']['coordinates']
        label = _label(feature.get('properties', {}))
        if label and label not in labels:
            labels.add(label)
            suggestions.append({'label': label, 'lat': lat, 'lon': lon})
    return suggestions[:MAX_SUGGESTIONS]


def suggest(query, session=None):
    """Up to MAX_SUGGESTIONS places matching the start of `query`."""
    query = ' '.join((query or '').split())
    if len(query) < MIN_QUERY_LENGTH:
        return []

    key = 'places:' + hashlib.sha1(query.lower().encode()).hexdigest()
    cached = cache.get(key)
    if cached is not None:
        return cached

    session = session or _get_session()
    _limiter.wait()
    try:
        response = session.get(
            settings.PHOTON_URL,
            # Ask for extra results: duplicates are dropped after formatting labels.
            params={'q': query, 'limit': MAX_SUGGESTIONS + 4, 'lang': 'en',
                    'lat': BIAS_POINT[0], 'lon': BIAS_POINT[1], 'zoom': BIAS_ZOOM,
                    'layer': LAYERS},
            headers={'User-Agent': settings.HTTP_USER_AGENT},
            timeout=REQUEST_TIMEOUT_S,
        )
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise PlaceSearchError(f'place search unavailable: {exc}') from exc

    if response.status_code != 200 or not isinstance(data, dict):
        raise PlaceSearchError(f'place search error: {response.status_code}')

    suggestions = parse_suggestions(data)
    cache.set(key, suggestions, CACHE_TTL_S)
    return suggestions
