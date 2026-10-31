import pytest

from routing.services.recommend import (
    Segment,
    decisive_reason,
    rank_routes,
    recommend,
    summarize_route,
)
from routing.services.risk import RiskLevel

L, M, H, S, NT = (
    RiskLevel.LOW,
    RiskLevel.MODERATE,
    RiskLevel.HIGH,
    RiskLevel.SEVERE,
    RiskLevel.NO_TRAVEL,
)

HOUR = 3600


def route(route_id, *levels, miles=25, duration_s=10 * HOUR):
    """Build a route summary with one equal-length segment per risk level."""
    return summarize_route(route_id, duration_s, [Segment(miles, level) for level in levels])


class TestSummarizeRoute:
    def test_totals_miles_per_level(self):
        summary = summarize_route(
            'A', HOUR, [Segment(25, L), Segment(25, S), Segment(25, H), Segment(10, S)]
        )
        assert summary.distance_miles == 85
        assert summary.severe_miles == 35
        assert summary.high_miles == 25
        assert summary.no_travel_miles == 0
        assert summary.travel_advised

    def test_avg_risk_is_weighted_by_distance(self):
        # 90 Low miles (0) + 10 Severe miles (3) -> 30 / 100
        summary = summarize_route('A', HOUR, [Segment(90, L), Segment(10, S)])
        assert summary.avg_risk == pytest.approx(0.3)

    def test_no_travel_miles_mark_route_as_not_advised(self):
        summary = route('A', L, NT)
        assert summary.no_travel_miles == 25
        assert not summary.travel_advised

    def test_empty_route_is_rejected(self):
        with pytest.raises(ValueError):
            summarize_route('A', HOUR, [])

    def test_negative_miles_are_rejected(self):
        with pytest.raises(ValueError):
            summarize_route('A', HOUR, [Segment(-5, L)])


class TestRankRoutes:
    def test_fewest_severe_miles_wins_over_shorter_time(self):
        risky_fast = route('fast', S, S, L, duration_s=5 * HOUR)
        safe_slow = route('slow', S, L, L, duration_s=9 * HOUR)
        assert rank_routes([risky_fast, safe_slow])[0].route_id == 'slow'

    def test_high_miles_break_severe_tie(self):
        a = route('A', S, H, H)
        b = route('B', S, H, L)
        assert rank_routes([a, b])[0].route_id == 'B'

    def test_avg_risk_breaks_high_tie(self):
        a = route('A', H, M, M)
        b = route('B', H, M, L)
        assert rank_routes([a, b])[0].route_id == 'B'

    def test_small_avg_risk_difference_still_counts(self):
        # avg risk 0.31 vs 0.34: both round to 0.3, but A is still safer
        a = summarize_route('A', 9 * HOUR, [Segment(69, L), Segment(31, M)])
        b = summarize_route('B', 8 * HOUR, [Segment(66, L), Segment(34, M)])
        assert rank_routes([a, b])[0].route_id == 'A'

    def test_duration_breaks_risk_tie(self):
        a = route('A', L, M, duration_s=8 * HOUR)
        b = route('B', M, L, duration_s=7 * HOUR)
        assert rank_routes([a, b])[0].route_id == 'B'

    def test_no_travel_ranks_below_any_amount_of_severe(self):
        blocked = route('blocked', NT, L, L, L)
        severe = route('severe', S, S, S, S)
        assert rank_routes([blocked, severe])[0].route_id == 'severe'

    def test_float_noise_does_not_break_ties(self):
        a = summarize_route('A', 9 * HOUR, [Segment(0.1 + 0.2, S)])
        b = summarize_route('B', 8 * HOUR, [Segment(0.3, S)])
        assert rank_routes([a, b])[0].route_id == 'B'

    def test_full_tie_keeps_input_order(self):
        a, b = route('A', L, M), route('B', L, M)
        assert [r.route_id for r in rank_routes([a, b])] == ['A', 'B']
        assert [r.route_id for r in rank_routes([b, a])] == ['B', 'A']

    def test_empty_list_is_rejected(self):
        with pytest.raises(ValueError):
            rank_routes([])


@pytest.mark.parametrize(
    'best, runner_up, reason',
    [
        (route('A', L), route('B', NT), 'fewest No Travel miles'),
        (route('A', L), route('B', S), 'fewest Severe miles'),
        (route('A', L), route('B', H), 'fewest High miles'),
        (route('A', L), route('B', M), 'lowest average risk'),
        (route('A', L, duration_s=HOUR), route('B', L, duration_s=2 * HOUR), 'shortest travel time'),
        (route('A', L), route('B', L), 'tied on all criteria'),
    ],
)
def test_decisive_reason(best, runner_up, reason):
    assert decisive_reason(best, runner_up) == reason


class TestRecommend:
    def test_picks_safest_of_three_and_explains_why(self):
        result = recommend([
            route('fastest', S, H, L, duration_s=6 * HOUR),
            route('safest', L, H, L, duration_s=8 * HOUR),
            route('middle', L, H, H, duration_s=7 * HOUR),
        ])
        assert result['recommended_route_id'] == 'safest'
        assert result['reason'] == 'fewest High miles'
        assert result['travel_advised'] is True
        assert [r['route_id'] for r in result['ranking']] == ['safest', 'middle', 'fastest']

    def test_warns_when_every_route_has_no_travel(self):
        result = recommend([route('A', NT, L), route('B', NT, NT)])
        assert result['recommended_route_id'] == 'A'
        assert result['travel_advised'] is False

    def test_single_route(self):
        result = recommend([route('only', L)])
        assert result['recommended_route_id'] == 'only'
        assert result['reason'] == 'only route available'

    def test_ranking_is_json_ready(self):
        result = recommend([route('A', S, L, miles=12.345, duration_s=3725.6)])
        assert result['ranking'][0] == {
            'route_id': 'A',
            'distance_miles': 24.7,
            'duration_s': 3726,
            'no_travel_miles': 0,
            'severe_miles': 12.3,
            'high_miles': 0,
            'avg_risk': 1.5,
            'travel_advised': True,
        }
