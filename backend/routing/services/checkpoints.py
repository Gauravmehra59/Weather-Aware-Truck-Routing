"""Sample points every N miles along a route and compute each point's ETA.

Conventions:
- Coordinates are (lat, lon) tuples. GeoJSON from routing APIs is [lon, lat], so
  routing_api.py flips them before calling this module.
- Checkpoints are placed at the origin, every `interval_miles`, and at the destination.
- Each checkpoint "covers" the miles closest to it: half the gap to the previous
  checkpoint plus half the gap to the next one. Covered miles add up to the route
  length, and the origin and destination weather both count.
- Positions and times are interpolated linearly between route vertices. Routing APIs
  return dense geometry, so a straight line between two vertices is accurate enough.
"""

import math
from dataclasses import dataclass
from datetime import timedelta
from itertools import accumulate, pairwise

EARTH_RADIUS_MILES = 3958.8

ALLOWED_INTERVALS_MILES = (10, 25, 50)

# A destination closer than this to the last interval checkpoint is merged into it,
# so a 100.3-mile route doesn't get near-duplicate checkpoints at 100 and 100.3.
MIN_GAP_MILES = 1.0


def haversine_miles(a, b):
    """Great-circle distance between two (lat, lon) points."""
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(h))


def cumulative_miles(coords):
    """Distance from the origin to each vertex."""
    return [0.0, *accumulate(haversine_miles(a, b) for a, b in pairwise(coords))]


def cumulative_seconds_from_total(coords, total_duration_s):
    """Spread the total duration over the route by distance (constant average speed)."""
    miles = cumulative_miles(coords)
    total_miles = miles[-1]
    if total_miles == 0:
        return [0.0] * len(coords)
    return [total_duration_s * m / total_miles for m in miles]


def cumulative_seconds_from_edges(edge_durations_s):
    """Turn per-edge durations (one per pair of vertices) into time at each vertex."""
    return [0.0, *accumulate(edge_durations_s)]


@dataclass(frozen=True)
class Checkpoint:
    index: int
    lat: float
    lon: float
    mile: float
    elapsed_s: float
    eta: object  # timezone-aware datetime
    covered_miles: float

    def to_dict(self):
        return {
            'index': self.index,
            'lat': round(self.lat, 5),
            'lon': round(self.lon, 5),
            'mile': round(self.mile, 1),
            'elapsed_s': round(self.elapsed_s),
            'eta': self.eta.isoformat(timespec='seconds'),
            'covered_miles': round(self.covered_miles, 2),
        }


def _validate(coords, cum_seconds, departure, interval_miles):
    if len(coords) < 2:
        raise ValueError('a route needs at least 2 coordinates')
    if len(cum_seconds) != len(coords):
        raise ValueError('cum_seconds must have one entry per coordinate')
    if any(later < earlier for earlier, later in pairwise(cum_seconds)):
        raise ValueError('cum_seconds must never decrease')
    if interval_miles <= 0:
        raise ValueError('interval_miles must be positive')
    if departure.tzinfo is None or departure.utcoffset() is None:
        raise ValueError('departure must be timezone-aware')


def _marks(total_miles, interval_miles):
    """Distances from origin where checkpoints go: 0, N, 2N, ..., destination."""
    count = int(total_miles // interval_miles)
    marks = [i * interval_miles for i in range(count + 1)]
    if len(marks) > 1 and total_miles - marks[-1] < MIN_GAP_MILES:
        marks[-1] = total_miles
    elif total_miles > marks[-1]:
        marks.append(total_miles)
    return marks


def _covered_miles(marks):
    gaps = [b - a for a, b in pairwise(marks)]
    if not gaps:
        return [0.0]
    before = [0.0, *gaps]
    after = [*gaps, 0.0]
    return [(b + a) / 2 for b, a in zip(before, after)]


def build_checkpoints(coords, cum_seconds, departure, interval_miles):
    """Place checkpoints every `interval_miles` and work out when the truck reaches each."""
    _validate(coords, cum_seconds, departure, interval_miles)

    cum_miles = cumulative_miles(coords)
    marks = _marks(cum_miles[-1], interval_miles)
    covered = _covered_miles(marks)

    checkpoints = []
    edge = 0
    last_edge = len(coords) - 2
    for index, (mark, covered_mi) in enumerate(zip(marks, covered)):
        while edge < last_edge and cum_miles[edge + 1] < mark:
            edge += 1

        edge_miles = cum_miles[edge + 1] - cum_miles[edge]
        t = (mark - cum_miles[edge]) / edge_miles if edge_miles else 0.0
        t = min(max(t, 0.0), 1.0)

        (lat1, lon1), (lat2, lon2) = coords[edge], coords[edge + 1]
        elapsed = cum_seconds[edge] + t * (cum_seconds[edge + 1] - cum_seconds[edge])
        checkpoints.append(Checkpoint(
            index=index,
            lat=lat1 + t * (lat2 - lat1),
            lon=lon1 + t * (lon2 - lon1),
            mile=mark,
            elapsed_s=elapsed,
            eta=departure + timedelta(seconds=elapsed),
            covered_miles=covered_mi,
        ))
    return checkpoints
