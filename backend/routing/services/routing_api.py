"""Fetch up to 3 alternative routes (geometry, distance, duration) from a routing API.

Data source: OSRM (keyless public server by default, see settings.OSRM_URL).

Why OSRM: openrouteservice's public API only returns alternative routes for trips up to
100 km, while truck trips are usually far longer. OSRM returns alternatives at any
distance, plus a duration for every edge of the route.

Getting to 3 routes: OSRM often returns only 1–2 alternatives. When that happens we ask
for extra routes through a detour waypoint placed to the left or right of the trip's
midpoint, and keep a candidate only if it
  - is not much slower than the fastest route (MAX_DETOUR_RATIO), and
  - is not mostly the same road as a route we already have (MAX_OVERLAP).
If no candidate passes, fewer than 3 routes are returned rather than a bad one.

Limitation: the public OSRM server uses a car profile, so durations are for a car, not
a loaded truck.
"""

import math
from dataclasses import dataclass, replace

import requests
from django.conf import settings
from django.core.cache import cache

from .checkpoints import cumulative_seconds_from_edges, cumulative_seconds_from_total
from .errors import ServiceError
from .ratelimit import RateLimiter

METERS_PER_MILE = 1609.344
REQUEST_TIMEOUT_S = 20

ROUTE_COUNT = 3
MAX_DETOUR_RATIO = 1.6  # a detour may take at most 1.6x the fastest route's time
MAX_OVERLAP = 0.85  # share of a candidate's road already covered by another route
# Detour waypoint offsets from the trip midpoint (or along-axis fraction), as a fraction
# of the straight-line trip length. Ordered by highest yield of distinct alternative routes.
DETOUR_OFFSETS = (
    0.45,
    (0.67, -0.25),
    0.3,
    -0.3,
    0.15,
    -0.15,
    -0.45,
    (0.33, 0.25),
)
OVERLAP_CELL_DEG = 0.05  # ~3.5 miles; grid size used to compare routes
CACHE_TTL_S = 24 * 60 * 60

# 50 ms polite rate limit avoids unnecessary artificial sleep on multi-detour searches.
_limiter = RateLimiter(min_interval_s=0.05)
_session = None


def _get_session():
    global _session
    if not isinstance(requests.Session, type):
        return requests.Session()
    if _session is None:
        _session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=10)
        _session.mount('https://', adapter)
        _session.mount('http://', adapter)
    return _session


def _cache_key(origin, destination):
    return f'osrm_routes_{origin[0]:.4f}_{origin[1]:.4f}_{destination[0]:.4f}_{destination[1]:.4f}'


class RoutingError(ServiceError):
    """No route could be found or the routing service failed."""


@dataclass(frozen=True)
class Route:
    coords: tuple  # (lat, lon) per vertex
    cum_seconds: tuple  # time from origin to each vertex
    distance_miles: float
    duration_s: float
    detour_via: tuple | None = None  # (lat, lon) waypoint, if this is a generated detour


def parse_route(osrm_route):
    """Turn one OSRM route into a Route with (lat, lon) coords and per-vertex times."""
    coords = tuple((lat, lon) for lon, lat in osrm_route['geometry']['coordinates'])
    duration = float(osrm_route['duration'])
    edges = [
        d for leg in osrm_route.get('legs', [])
        for d in leg.get('annotation', {}).get('duration', [])
    ]

    if len(edges) == len(coords) - 1 and sum(edges) > 0:
        # Per-edge times sum to slightly less than the route total (turn penalties
        # etc.), so scale them to match the total OSRM reports.
        scale = duration / sum(edges)
        cum_seconds = cumulative_seconds_from_edges(e * scale for e in edges)
    else:
        cum_seconds = cumulative_seconds_from_total(coords, duration)

    return Route(
        coords=coords,
        cum_seconds=tuple(cum_seconds),
        distance_miles=float(osrm_route['distance']) / METERS_PER_MILE,
        duration_s=duration,
    )


def _request(session, points, alternatives=0):
    """Raw OSRM routes through the given (lat, lon) points, in order."""
    path = ';'.join(f'{lon:.6f},{lat:.6f}' for lat, lon in points)
    params = {
        'overview': 'full',
        'geometries': 'geojson',
        'annotations': 'duration',
        'alternatives': alternatives or 'false',
    }
    _limiter.wait()
    try:
        response = session.get(
            f'{settings.OSRM_URL}/route/v1/driving/{path}',
            params=params,
            headers={'User-Agent': settings.HTTP_USER_AGENT},
            timeout=REQUEST_TIMEOUT_S,
        )
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise RoutingError(f'routing service unavailable: {exc}') from exc

    if not isinstance(data, dict) or data.get('code') != 'Ok' or not data.get('routes'):
        message = data.get('message') if isinstance(data, dict) else None
        raise RoutingError(f'no route found: {message or response.status_code}')
    return data['routes']


def detour_point(origin, destination, offset, along=0.5):
    """A point beside the trip, `offset` fraction away from the route axis at fraction `along`."""
    if isinstance(offset, (tuple, list)):
        along, offset = offset
    (lat1, lon1), (lat2, lon2) = origin, destination
    p_lat = lat1 + (lat2 - lat1) * along
    p_lon = lon1 + (lon2 - lon1) * along
    # Work in a locally flat frame where one unit is one degree of latitude.
    cos_lat = math.cos(math.radians(p_lat))
    dx, dy = (lon2 - lon1) * cos_lat, lat2 - lat1
    # (-dy, dx) is (dx, dy) rotated 90° counter-clockwise, i.e. to the left.
    via_lat = p_lat + offset * dx
    via_lon = p_lon - offset * dy / cos_lat
    return (via_lat, via_lon)


def _cells(coords, dilate=False):
    cells = {(math.floor(lat / OVERLAP_CELL_DEG), math.floor(lon / OVERLAP_CELL_DEG))
             for lat, lon in coords}
    if dilate:
        cells = {(r + dr, c + dc) for r, c in cells for dr in (-1, 0, 1) for dc in (-1, 0, 1)}
    return cells


def overlap(candidate, existing):
    """Share of `candidate`'s road (0..1) that runs alongside `existing`."""
    candidate_cells = _cells(candidate.coords)
    if not candidate_cells:
        return 1.0
    # Dilate the existing route by one cell so roads straddling a cell edge still match.
    return len(candidate_cells & _cells(existing.coords, dilate=True)) / len(candidate_cells)


def fetch_routes(origin, destination, session=None):
    """Up to ROUTE_COUNT distinct routes between two (lat, lon) points, fastest first."""
    use_cache = session is None
    if use_cache:
        key = _cache_key(origin, destination)
        cached = cache.get(key)
        if cached is not None:
            return cached

    s = session or _get_session()
    routes = [
        parse_route(r)
        for r in _request(s, [origin, destination], alternatives=ROUTE_COUNT - 1)
    ][:ROUTE_COUNT]
    fastest = min(r.duration_s for r in routes)

    for offset in DETOUR_OFFSETS:
        if len(routes) >= ROUTE_COUNT:
            break
        via = detour_point(origin, destination, offset)
        try:
            raw = _request(s, [origin, via, destination])
        except RoutingError:
            continue
        candidate = replace(parse_route(raw[0]), detour_via=via)
        if candidate.duration_s > MAX_DETOUR_RATIO * fastest:
            continue
        if any(overlap(candidate, route) > MAX_OVERLAP for route in routes):
            continue
        routes.append(candidate)

    sorted_routes = sorted(routes, key=lambda r: r.duration_s)
    if use_cache and sorted_routes:
        cache.set(key, sorted_routes, CACHE_TTL_S)
    return sorted_routes
