"""Classify weather + load into a risk level (Low / Moderate / High / Severe / No Travel).

Boundary convention (the brief's ranges overlap, e.g. rain 0.10–0.25 and 0.25–0.50):
each range includes its lower bound, so a value exactly on a boundary goes to the
higher level (rain 0.25 -> High). The one exception is the top of the Severe band for
rain/snow, because the brief defines No Travel as strictly greater (rain >1.00, snow >3.0).
"""

from dataclasses import dataclass
from enum import IntEnum


class RiskLevel(IntEnum):
    LOW = 0
    MODERATE = 1
    HIGH = 2
    SEVERE = 3
    NO_TRAVEL = 4

    @property
    def label(self):
        return self.name.replace('_', ' ').title()


# Upper limits (exclusive) for Low, Moderate, High, Severe. Anything at or above the
# last limit is No Travel.
WIND_LIMITS_MPH = (25, 35, 45, 55)

# Upper limits for Low, Moderate, High (exclusive) and Severe (inclusive). Anything
# above the last limit is No Travel.
RAIN_LIMITS_IN_HR = (0.10, 0.25, 0.50, 1.00)
SNOW_LIMITS_IN_HR = (0.5, 1.0, 2.0, 3.0)

# Load rules: heavy trucks are more exposed to strong wind.
NO_TRAVEL_WIND_LOAD_LB = 30_000  # 45–54 mph + load above this -> No Travel
SEVERE_WIND_LOAD_LB = 40_000  # 35–44 mph + load above this -> Severe


def _check_non_negative(name, value):
    if value < 0:
        raise ValueError(f'{name} cannot be negative, got {value}')


def classify_wind(wind_mph, load_lb=0):
    """Wind risk, including the load-weight rules."""
    _check_non_negative('wind_mph', wind_mph)
    _check_non_negative('load_lb', load_lb)

    level = RiskLevel.NO_TRAVEL
    for candidate, limit in zip(RiskLevel, WIND_LIMITS_MPH):
        if wind_mph < limit:
            level = candidate
            break

    if level == RiskLevel.SEVERE and load_lb > NO_TRAVEL_WIND_LOAD_LB:
        return RiskLevel.NO_TRAVEL
    if level == RiskLevel.HIGH and load_lb > SEVERE_WIND_LOAD_LB:
        return RiskLevel.SEVERE
    return level


def _classify_precipitation(rate, limits):
    low, moderate, high, severe = limits
    if rate < low:
        return RiskLevel.LOW
    if rate < moderate:
        return RiskLevel.MODERATE
    if rate < high:
        return RiskLevel.HIGH
    if rate <= severe:
        return RiskLevel.SEVERE
    return RiskLevel.NO_TRAVEL


def classify_rain(rain_in_hr):
    _check_non_negative('rain_in_hr', rain_in_hr)
    return _classify_precipitation(rain_in_hr, RAIN_LIMITS_IN_HR)


def classify_snow(snow_in_hr):
    _check_non_negative('snow_in_hr', snow_in_hr)
    return _classify_precipitation(snow_in_hr, SNOW_LIMITS_IN_HR)


@dataclass(frozen=True)
class CheckpointRisk:
    level: RiskLevel
    wind: RiskLevel
    rain: RiskLevel
    snow: RiskLevel

    @property
    def drivers(self):
        """Which conditions caused the overall level (empty when Low)."""
        if self.level == RiskLevel.LOW:
            return []
        factors = {'wind': self.wind, 'rain': self.rain, 'snow': self.snow}
        return [name for name, level in factors.items() if level == self.level]

    def to_dict(self):
        return {
            'level': self.level.label,
            'score': int(self.level),
            'wind': self.wind.label,
            'rain': self.rain.label,
            'snow': self.snow.label,
            'drivers': self.drivers,
        }


def assess_checkpoint(wind_mph, rain_in_hr, snow_in_hr, load_lb):
    """Overall checkpoint risk = the worst of wind (with load rules), rain and snow."""
    wind = classify_wind(wind_mph, load_lb)
    rain = classify_rain(rain_in_hr)
    snow = classify_snow(snow_in_hr)
    return CheckpointRisk(level=max(wind, rain, snow), wind=wind, rain=rain, snow=snow)
