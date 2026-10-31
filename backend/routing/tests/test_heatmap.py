import os
from datetime import datetime, timedelta, timezone

import pytest
from django.test import Client
from django.utils import timezone as dj_timezone

from routing.services import heatmap
from routing.services.heatmap import (
    HOURS,
    _mercator_y,
    build_heatmap,
    corridor_grid,
)
from routing.services.weather import HourlyForecast, WeatherError, WeatherSample

DEPARTURE = datetime(2026, 10, 30, 8, 25, tzinfo=timezone.utc)
CHICAGO_DENVER = [(41.88, -87.63), (41.26, -95.94), (39.74, -104.99)]


def calm_forecast(start, hours, wind=5.0):
    return HourlyForecast(tuple(
        WeatherSample(time=start + timedelta(hours=h), wind_mph=wind(h) if callable(wind) else wind,
                      gust_mph=10.0, rain_in_hr=0.0, snow_in_hr=0.0)
        for h in range(hours)
    ))


class TestCorridorGrid:
    def test_respects_point_budget(self):
        grid = corridor_grid([CHICAGO_DENVER], max_points=250)
        assert 0 < len(grid.cells) <= 250

    def test_uses_finest_cells_that_fit(self):
        coarse = corridor_grid([CHICAGO_DENVER], max_points=100)
        fine = corridor_grid([CHICAGO_DENVER], max_points=400)
        assert fine.cell_deg < coarse.cell_deg

    def test_short_trip_gets_fine_cells(self):
        grid = corridor_grid([[(32.78, -96.80), (29.76, -95.37)]])
        assert grid.cell_deg == heatmap.CELL_SIZES_DEG[0]

    def test_every_route_point_is_inside_a_corridor_cell(self):
        grid = corridor_grid([CHICAGO_DENVER])
        cells = set(grid.cells)
        for lat, lon in heatmap._densify(CHICAGO_DENVER, grid.cell_deg / 2):
            row = int((grid.top_y - _mercator_y(lat)) // grid.cell_y)
            col = int((lon - grid.west) // grid.cell_deg)
            assert (row, col) in cells

    def test_corridor_hugs_the_route(self):
        grid = corridor_grid([CHICAGO_DENVER])
        # A thin corridor covers far fewer cells than the whole bounding box.
        assert len(grid.cells) < grid.rows * grid.cols / 2

    def test_cells_lie_within_bounds(self):
        grid = corridor_grid([CHICAGO_DENVER])
        (south, west), (north, east) = grid.bounds
        assert all(0 <= r < grid.rows and 0 <= c < grid.cols for r, c in grid.cells)
        for r, c in grid.cells:
            lat, lon = grid.center(r, c)
            assert south < lat < north and west < lon < east

    def test_rows_are_even_in_mercator(self):
        grid = corridor_grid([CHICAGO_DENVER])
        ys = [_mercator_y(grid.center(r, 0)[0]) for r in range(grid.rows)]
        gaps = [a - b for a, b in zip(ys, ys[1:])]
        assert max(gaps) == pytest.approx(min(gaps))

    def test_multiple_paths_share_one_grid(self):
        north = [(43.0, -100.0), (43.0, -95.0)]
        south = [(38.0, -100.0), (38.0, -95.0)]
        both = corridor_grid([north, south])
        assert len(both.cells) > len(corridor_grid([north]).cells)

    def test_empty_paths_are_rejected(self):
        with pytest.raises(ValueError):
            corridor_grid([[]])


class TestBuildHeatmap:
    @pytest.fixture
    def fake_forecasts(self, monkeypatch):
        calls = []

        def fake(points, start, end, session=None):
            calls.append((points, start, end))
            # Wind rises 1 mph per hour so we can check hour alignment.
            return [calm_forecast(start, HOURS + 1, wind=lambda h: float(h)) for _ in points]

        monkeypatch.setattr(heatmap, 'fetch_forecasts', fake)
        return calls

    def test_one_forecast_request_for_all_cells_and_hours(self, fake_forecasts):
        result = build_heatmap([CHICAGO_DENVER], DEPARTURE, 35_000)
        (points, start, end), = fake_forecasts
        assert len(points) == len(result['cells'])
        assert start == datetime(2026, 10, 30, 8, 0, tzinfo=timezone.utc)
        assert end == start + timedelta(hours=HOURS)

    def test_shape(self, fake_forecasts):
        result = build_heatmap([CHICAGO_DENVER], DEPARTURE, 35_000)
        n = len(result['cells'])
        for key in ('wind_mph', 'rain_in_hr', 'snow_in_hr', 'risk'):
            assert len(result[key]) == n
            assert all(len(series) == HOURS + 1 for series in result[key])
        assert result['start'] == '2026-10-30T08:00:00+00:00'
        assert result['hours'] == HOURS

    def test_values_follow_the_hour(self, fake_forecasts):
        result = build_heatmap([CHICAGO_DENVER], DEPARTURE, 0)
        assert result['wind_mph'][0][:3] == [0.0, 1.0, 2.0]
        # Wind passes 25 mph (Moderate) at hour 25 and 55 mph (No Travel) never: max 48.
        assert result['risk'][0][24] == 0
        assert result['risk'][0][25] == 1
        assert result['risk'][0][45] == 3

    def test_risk_uses_load_rules(self, fake_forecasts):
        light = build_heatmap([CHICAGO_DENVER], DEPARTURE, 20_000)
        heavy = build_heatmap([CHICAGO_DENVER], DEPARTURE, 35_000)
        assert light['risk'][0][45] == 3  # 45 mph -> Severe
        assert heavy['risk'][0][45] == 4  # 45 mph + >30,000 lb -> No Travel


class TestHeatmapEndpoint:
    def payload(self, **overrides):
        payload = {
            'departure': (dj_timezone.now() + timedelta(hours=2)).isoformat(),
            'load_lb': 35_000,
            'paths': [[list(p) for p in CHICAGO_DENVER]],
        }
        payload.update(overrides)
        return payload

    def post(self, payload):
        return Client().post('/api/heatmap/', payload, content_type='application/json')

    def test_success(self, monkeypatch):
        monkeypatch.setattr(
            heatmap, 'fetch_forecasts',
            lambda points, start, end, session=None: [calm_forecast(start, HOURS + 1) for _ in points],
        )
        response = self.post(self.payload())
        assert response.status_code == 200
        assert len(response.json()['risk']) == len(response.json()['cells'])

    @pytest.mark.parametrize(
        'overrides, field',
        [
            ({'paths': []}, 'paths'),
            ({'paths': [[[41.0, -87.0]]]}, 'paths'),
            ({'paths': [[[41.0, -87.0, 3.0], [40.0, -90.0]]]}, 'paths'),
            ({'paths': [[[95.0, -87.0], [40.0, -90.0]]]}, 'paths'),
            ({'paths': [[[41.0, -87.0], [40.0, -90.0]]] * 4}, 'paths'),
            ({'load_lb': -1}, 'load_lb'),
            ({'departure': '2020-01-01T00:00:00Z'}, 'departure'),
        ],
    )
    def test_invalid_input(self, overrides, field):
        response = self.post(self.payload(**overrides))
        assert response.status_code == 400
        assert field in response.json()

    def test_weather_failure(self, monkeypatch):
        def down(points, start, end, session=None):
            raise WeatherError('weather service unavailable: timeout')

        monkeypatch.setattr(heatmap, 'fetch_forecasts', down)
        response = self.post(self.payload())
        assert response.status_code == 422


@pytest.mark.skipif(not os.environ.get('RUN_LIVE_TESTS'), reason='hits the real API; run `make test-live`')
def test_live_heatmap():
    departure = dj_timezone.now() + timedelta(hours=1)
    result = build_heatmap([CHICAGO_DENVER], departure, 35_000)
    assert len(result['cells']) <= heatmap.MAX_POINTS
    assert all(len(series) == HOURS + 1 for series in result['risk'])
