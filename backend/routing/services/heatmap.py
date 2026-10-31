"""Weather heatmap along the trip corridor, hourly for 0–48 hours after departure.

The corridor is a grid of cells around the routes. Cell size grows until the corridor
fits in MAX_POINTS cells, so one batched forecast request covers every cell.

Rows are evenly spaced in Web Mercator y (not latitude), the projection web maps use.
That way the frontend can draw the grid as one stretched image and every cell lands
exactly where it belongs on the map.
"""

import math
from dataclasses import dataclass
from datetime import timedelta

from .risk import assess_checkpoint
from .weather import fetch_forecasts

HOURS = 48
MAX_POINTS = 250
# Candidate cell sizes in degrees of longitude, finest first.
CELL_SIZES_DEG = (0.1, 0.15, 0.2, 0.25, 0.35, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0)


def _mercator_y(lat):
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def _mercator_lat(y):
    return math.degrees(2 * math.atan(math.exp(y)) - math.pi / 2)


@dataclass(frozen=True)
class Grid:
    west: float
    top_y: float  # Mercator y of the north edge
    cell_deg: float
    rows: int
    cols: int
    cells: tuple  # (row, col) pairs in the corridor, row 0 = north

    @property
    def cell_y(self):
        # Square cells in Mercator: a degree of longitude is radians(1) of x.
        return math.radians(self.cell_deg)

    @property
    def bounds(self):
        """[[south, west], [north, east]] of the whole grid."""
        north = _mercator_lat(self.top_y)
        south = _mercator_lat(self.top_y - self.rows * self.cell_y)
        return [[south, self.west], [north, self.west + self.cols * self.cell_deg]]

    def center(self, row, col):
        lat = _mercator_lat(self.top_y - (row + 0.5) * self.cell_y)
        return (lat, self.west + (col + 0.5) * self.cell_deg)


def _densify(path, max_step_deg):
    """Points along `path` no more than `max_step_deg` apart."""
    for (lat1, lon1), (lat2, lon2) in zip(path, path[1:]):
        steps = max(1, math.ceil(max(abs(lat2 - lat1), abs(lon2 - lon1)) / max_step_deg))
        for i in range(steps):
            t = i / steps
            yield (lat1 + t * (lat2 - lat1), lon1 + t * (lon2 - lon1))
    yield path[-1]


def _grid_for(paths, cell_deg):
    points = [p for path in paths for p in _densify(path, cell_deg / 2)]
    cell_y = math.radians(cell_deg)
    # One cell of padding on every side, for the corridor's dilation below.
    west = min(lon for _, lon in points) - cell_deg
    east = max(lon for _, lon in points) + cell_deg
    top_y = max(_mercator_y(lat) for lat, _ in points) + cell_y
    bottom_y = min(_mercator_y(lat) for lat, _ in points) - cell_y
    rows = math.ceil((top_y - bottom_y) / cell_y)
    cols = math.ceil((east - west) / cell_deg)

    on_route = {
        (int((top_y - _mercator_y(lat)) // cell_y), int((lon - west) // cell_deg))
        for lat, lon in points
    }
    # Widen the corridor by one cell on each side of the route.
    cells = {
        (r + dr, c + dc)
        for r, c in on_route for dr in (-1, 0, 1) for dc in (-1, 0, 1)
        if 0 <= r + dr < rows and 0 <= c + dc < cols
    }
    return Grid(west, top_y, cell_deg, rows, cols, tuple(sorted(cells)))


def corridor_grid(paths, max_points=MAX_POINTS):
    """The finest grid whose corridor around `paths` has at most `max_points` cells."""
    paths = [path for path in paths if path]
    if not paths:
        raise ValueError('at least one path is required')
    for cell_deg in CELL_SIZES_DEG:
        grid = _grid_for(paths, cell_deg)
        if len(grid.cells) <= max_points:
            return grid
    return grid  # coarsest available; only reachable for continent-spanning trips


def build_heatmap(paths, departure, load_lb, session=None):
    """Hourly wind, rain, snow and risk for every corridor cell, as JSON-ready data."""
    grid = corridor_grid(paths)
    start = departure.replace(minute=0, second=0, microsecond=0)
    times = [start + timedelta(hours=h) for h in range(HOURS + 1)]
    centers = [grid.center(r, c) for r, c in grid.cells]
    forecasts = fetch_forecasts(centers, times[0], times[-1], session)

    wind, rain, snow, risk = [], [], [], []
    for forecast in forecasts:
        samples = [forecast.at(t) for t in times]
        wind.append([round(s.wind_mph, 1) for s in samples])
        rain.append([round(s.rain_in_hr, 3) for s in samples])
        snow.append([round(s.snow_in_hr, 3) for s in samples])
        risk.append([
            int(assess_checkpoint(s.wind_mph, s.rain_in_hr, s.snow_in_hr, load_lb).level)
            for s in samples
        ])

    return {
        'start': start.isoformat(),
        'hours': HOURS,
        'bounds': grid.bounds,
        'rows': grid.rows,
        'cols': grid.cols,
        'cell_deg': grid.cell_deg,
        'cells': [list(cell) for cell in grid.cells],
        'wind_mph': wind,
        'rain_in_hr': rain,
        'snow_in_hr': snow,
        'risk': risk,
    }
