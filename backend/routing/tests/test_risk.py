import pytest

from routing.services.risk import (
    RiskLevel,
    assess_checkpoint,
    classify_rain,
    classify_snow,
    classify_wind,
)

L, M, H, S, NT = (
    RiskLevel.LOW,
    RiskLevel.MODERATE,
    RiskLevel.HIGH,
    RiskLevel.SEVERE,
    RiskLevel.NO_TRAVEL,
)


@pytest.mark.parametrize(
    'mph, expected',
    [
        (0, L), (24.9, L),
        (25, M), (34, M), (34.9, M),
        (35, H), (44, H),
        (45, S), (54, S), (54.9, S),
        (55, NT), (80, NT),
    ],
)
def test_wind_thresholds_without_load(mph, expected):
    assert classify_wind(mph) == expected


@pytest.mark.parametrize(
    'rate, expected',
    [
        (0, L), (0.09, L),
        (0.10, M), (0.24, M),
        (0.25, H), (0.49, H),
        (0.50, S), (1.00, S),
        (1.01, NT), (2.5, NT),
    ],
)
def test_rain_thresholds(rate, expected):
    assert classify_rain(rate) == expected


@pytest.mark.parametrize(
    'rate, expected',
    [
        (0, L), (0.49, L),
        (0.5, M), (0.99, M),
        (1.0, H), (1.99, H),
        (2.0, S), (3.0, S),
        (3.01, NT), (6, NT),
    ],
)
def test_snow_thresholds(rate, expected):
    assert classify_snow(rate) == expected


class TestLoadRules:
    def test_55_mph_is_no_travel_for_any_load(self):
        assert classify_wind(55, load_lb=0) == NT
        assert classify_wind(60, load_lb=10_000) == NT

    @pytest.mark.parametrize('mph', [45, 50, 54])
    def test_severe_wind_with_heavy_load_is_no_travel(self, mph):
        assert classify_wind(mph, load_lb=30_001) == NT

    def test_severe_wind_at_exactly_30000_lb_stays_severe(self):
        assert classify_wind(50, load_lb=30_000) == S

    @pytest.mark.parametrize('mph', [35, 40, 44])
    def test_high_wind_with_very_heavy_load_is_severe(self, mph):
        assert classify_wind(mph, load_lb=40_001) == S

    def test_high_wind_at_exactly_40000_lb_stays_high(self):
        assert classify_wind(40, load_lb=40_000) == H

    def test_high_wind_between_30000_and_40000_lb_stays_high(self):
        assert classify_wind(40, load_lb=35_000) == H

    def test_load_does_not_affect_low_or_moderate_wind(self):
        assert classify_wind(20, load_lb=80_000) == L
        assert classify_wind(30, load_lb=80_000) == M


class TestAssessCheckpoint:
    def test_calm_weather_is_low_with_no_drivers(self):
        risk = assess_checkpoint(wind_mph=5, rain_in_hr=0, snow_in_hr=0, load_lb=40_000)
        assert risk.level == L
        assert risk.drivers == []

    def test_overall_is_worst_condition(self):
        risk = assess_checkpoint(wind_mph=30, rain_in_hr=0.3, snow_in_hr=0, load_lb=10_000)
        assert (risk.wind, risk.rain, risk.snow) == (M, H, L)
        assert risk.level == H
        assert risk.drivers == ['rain']

    def test_load_rule_raises_overall_level(self):
        light = assess_checkpoint(wind_mph=48, rain_in_hr=0, snow_in_hr=0, load_lb=20_000)
        heavy = assess_checkpoint(wind_mph=48, rain_in_hr=0, snow_in_hr=0, load_lb=35_000)
        assert light.level == S
        assert heavy.level == NT

    def test_multiple_drivers_at_same_level(self):
        risk = assess_checkpoint(wind_mph=50, rain_in_hr=0, snow_in_hr=2.5, load_lb=0)
        assert risk.level == S
        assert risk.drivers == ['wind', 'snow']

    def test_to_dict(self):
        risk = assess_checkpoint(wind_mph=50, rain_in_hr=0.1, snow_in_hr=0, load_lb=35_000)
        assert risk.to_dict() == {
            'level': 'No Travel',
            'score': 4,
            'wind': 'No Travel',
            'rain': 'Moderate',
            'snow': 'Low',
            'drivers': ['wind'],
        }


@pytest.mark.parametrize(
    'kwargs',
    [
        {'wind_mph': -1, 'rain_in_hr': 0, 'snow_in_hr': 0, 'load_lb': 0},
        {'wind_mph': 0, 'rain_in_hr': -0.1, 'snow_in_hr': 0, 'load_lb': 0},
        {'wind_mph': 0, 'rain_in_hr': 0, 'snow_in_hr': -1, 'load_lb': 0},
        {'wind_mph': 0, 'rain_in_hr': 0, 'snow_in_hr': 0, 'load_lb': -5},
    ],
)
def test_negative_values_are_rejected(kwargs):
    with pytest.raises(ValueError):
        assess_checkpoint(**kwargs)
