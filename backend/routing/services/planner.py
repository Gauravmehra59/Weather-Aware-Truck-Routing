"""Plan a trip end to end: geocode -> routes -> checkpoints -> weather -> risk -> recommend."""

from string import ascii_uppercase

from .checkpoints import build_checkpoints
from .geocoding import Place, geocode
from .geometry import simplify
from .recommend import Segment, recommend, summarize_route
from .risk import assess_checkpoint
from .routing_api import fetch_routes
from .weather import weather_for_checkpoints

# ~50 m. Plenty for a map line, and cuts a 1000-mile route from ~10k points to ~1–2k.
MAP_TOLERANCE_DEG = 0.0005


def _route_payload(route_id, route, checkpoints, samples, risks, summary):
    return {
        'id': route_id,
        **summary.to_dict(),
        'is_detour': route.detour_via is not None,
        'geometry': [[round(lat, 5), round(lon, 5)] for lat, lon in simplify(route.coords, MAP_TOLERANCE_DEG)],
        'checkpoints': [
            {**cp.to_dict(), 'weather': sample.to_dict(), 'risk': risk.to_dict()}
            for cp, sample, risk in zip(checkpoints, samples, risks)
        ],
    }


def _place(text, point):
    """The picked suggestion's exact point when there is one, else geocode the text."""
    if point:
        return Place(query=text, label=text, lat=point[0], lon=point[1])
    return geocode(text)


def plan_trip(origin, destination, departure, load_lb, interval_miles,
              origin_point=None, destination_point=None):
    """Everything the UI needs for one trip, as JSON-ready data.

    Raises ServiceError (with a user-facing message) when geocoding, routing or the
    weather forecast fails.
    """
    origin_place = _place(origin, origin_point)
    destination_place = _place(destination, destination_point)
    routes = fetch_routes(origin_place.point, destination_place.point)
    route_ids = list(ascii_uppercase[:len(routes)])  # fastest route is A

    checkpoints_per_route = [
        build_checkpoints(route.coords, route.cum_seconds, departure, interval_miles)
        for route in routes
    ]

    # One batched weather lookup for every checkpoint on every route.
    all_checkpoints = [cp for cps in checkpoints_per_route for cp in cps]
    all_samples = iter(weather_for_checkpoints(all_checkpoints))
    samples_per_route = [[next(all_samples) for _ in cps] for cps in checkpoints_per_route]

    payloads, summaries = {}, []
    for route_id, route, cps, samples in zip(route_ids, routes, checkpoints_per_route, samples_per_route):
        risks = [
            assess_checkpoint(s.wind_mph, s.rain_in_hr, s.snow_in_hr, load_lb) for s in samples
        ]
        summary = summarize_route(
            route_id, route.duration_s, [Segment(cp.covered_miles, r.level) for cp, r in zip(cps, risks)]
        )
        summaries.append(summary)
        payloads[route_id] = _route_payload(route_id, route, cps, samples, risks, summary)

    recommendation = recommend(summaries)
    return {
        'origin': origin_place.to_dict(),
        'destination': destination_place.to_dict(),
        'departure': departure.isoformat(),
        'load_lb': load_lb,
        'interval_miles': interval_miles,
        'recommended_route_id': recommendation['recommended_route_id'],
        'reason': recommendation['reason'],
        'travel_advised': recommendation['travel_advised'],
        # Best route first, matching the recommendation ranking.
        'routes': [payloads[r['route_id']] for r in recommendation['ranking']],
    }
