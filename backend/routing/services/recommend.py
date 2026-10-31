"""Rank routes: fewest Severe miles, fewest High miles, lowest avg risk, shortest time.

Assumptions beyond the brief:
- No Travel miles are compared first. No Travel is worse than Severe, so a route with
  any No Travel miles must never beat one without them just because it has fewer
  Severe miles.
- Each segment is a stretch of road with one risk level (checkpoints.py decides how
  many miles each checkpoint covers). Average risk is weighted by segment length, so a
  short final segment doesn't count as much as a full one.
- Miles are compared rounded to 0.1 mile so floating-point noise doesn't break ties.
"""

from dataclasses import dataclass

from .risk import RiskLevel

MILES_PRECISION = 1  # decimal places used when comparing miles

CRITERIA = (
    ('no_travel_miles', 'fewest No Travel miles'),
    ('severe_miles', 'fewest Severe miles'),
    ('high_miles', 'fewest High miles'),
    ('avg_risk', 'lowest average risk'),
    ('duration_s', 'shortest travel time'),
)


@dataclass(frozen=True)
class Segment:
    miles: float
    risk: RiskLevel


@dataclass(frozen=True)
class RouteSummary:
    route_id: str
    distance_miles: float
    duration_s: float
    no_travel_miles: float
    severe_miles: float
    high_miles: float
    avg_risk: float

    @property
    def travel_advised(self):
        return self.no_travel_miles == 0

    def sort_key(self):
        return (
            round(self.no_travel_miles, MILES_PRECISION),
            round(self.severe_miles, MILES_PRECISION),
            round(self.high_miles, MILES_PRECISION),
            round(self.avg_risk, 6),
            self.duration_s,
        )

    def to_dict(self):
        return {
            'route_id': self.route_id,
            'distance_miles': round(self.distance_miles, 1),
            'duration_s': round(self.duration_s),
            'no_travel_miles': round(self.no_travel_miles, 1),
            'severe_miles': round(self.severe_miles, 1),
            'high_miles': round(self.high_miles, 1),
            'avg_risk': round(self.avg_risk, 2),
            'travel_advised': self.travel_advised,
        }


def summarize_route(route_id, duration_s, segments):
    """Total up miles per risk level for one route."""
    segments = list(segments)
    if not segments:
        raise ValueError(f'route {route_id} has no segments')
    if any(s.miles < 0 for s in segments):
        raise ValueError(f'route {route_id} has a segment with negative miles')

    miles_at = {level: 0.0 for level in RiskLevel}
    for segment in segments:
        miles_at[segment.risk] += segment.miles

    distance = sum(miles_at.values())
    weighted = sum(int(level) * miles for level, miles in miles_at.items())
    return RouteSummary(
        route_id=route_id,
        distance_miles=distance,
        duration_s=duration_s,
        no_travel_miles=miles_at[RiskLevel.NO_TRAVEL],
        severe_miles=miles_at[RiskLevel.SEVERE],
        high_miles=miles_at[RiskLevel.HIGH],
        avg_risk=weighted / distance if distance else 0.0,
    )


def rank_routes(summaries):
    """Best route first. Ties on every criterion keep the routing API's order."""
    if not summaries:
        raise ValueError('no routes to rank')
    return sorted(summaries, key=RouteSummary.sort_key)


def decisive_reason(best, runner_up):
    """The first criterion where best beat runner_up, e.g. 'fewest Severe miles'."""
    for (_, reason), best_value, other_value in zip(
        CRITERIA, best.sort_key(), runner_up.sort_key()
    ):
        if best_value != other_value:
            return reason
    return 'tied on all criteria'


def recommend(summaries):
    """Rank routes and explain why the top one was chosen."""
    ranked = rank_routes(summaries)
    best = ranked[0]
    reason = decisive_reason(best, ranked[1]) if len(ranked) > 1 else 'only route available'
    return {
        'recommended_route_id': best.route_id,
        'reason': reason,
        'travel_advised': best.travel_advised,
        'ranking': [summary.to_dict() for summary in ranked],
    }
