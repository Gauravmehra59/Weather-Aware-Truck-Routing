import os

import pytest
import requests
from django.core.cache import cache

from routing.services import geocoding
from routing.services.geocoding import GeocodingError, geocode

from .fakes import FakeResponse, FakeSession

CHICAGO = [{'lat': '41.8755616', 'lon': '-87.6244212', 'display_name': 'Chicago, Illinois, United States'}]


@pytest.fixture(autouse=True)
def fresh_cache_and_no_waiting(monkeypatch):
    cache.clear()
    monkeypatch.setattr(geocoding._limiter, 'min_interval_s', 0)


def answer(data, status=200):
    return FakeSession(lambda url, params: FakeResponse(data, status))


def test_returns_best_match():
    place = geocode('Chicago, IL', answer(CHICAGO))
    assert place.point == (41.8755616, -87.6244212)
    assert place.label == 'Chicago, Illinois, United States'
    assert place.to_dict()['query'] == 'Chicago, IL'


def test_sends_query_and_user_agent(settings):
    settings.HTTP_USER_AGENT = 'test-agent/1.0'
    session = answer(CHICAGO)
    geocode('  Chicago,   IL ', session)
    call = session.calls[0]
    assert call['params'] == {'q': 'Chicago, IL', 'format': 'jsonv2', 'limit': 1}
    assert call['headers'] == {'User-Agent': 'test-agent/1.0'}


def test_results_are_cached_case_insensitively():
    session = answer(CHICAGO)
    first = geocode('Chicago, IL', session)
    second = geocode('chicago, il', session)
    assert first == second
    assert len(session.calls) == 1


@pytest.mark.parametrize('query', ['', '   ', None])
def test_empty_query_is_rejected(query):
    with pytest.raises(GeocodingError, match='empty'):
        geocode(query, answer(CHICAGO))


def test_unknown_place():
    with pytest.raises(GeocodingError, match='could not find "Xyzzyville"'):
        geocode('Xyzzyville', answer([]))


def test_http_error():
    with pytest.raises(GeocodingError, match='503'):
        geocode('Chicago', answer({'error': 'busy'}, status=503))


def test_network_failure():
    def fail(url, params):
        raise requests.Timeout('slow')

    with pytest.raises(GeocodingError, match='unavailable'):
        geocode('Chicago', FakeSession(fail))


def test_failures_are_not_cached():
    with pytest.raises(GeocodingError):
        geocode('Chicago', answer([]))
    assert geocode('Chicago', answer(CHICAGO)).lat == pytest.approx(41.8755616)


@pytest.mark.skipif(not os.environ.get('RUN_LIVE_TESTS'), reason='hits the real API; run `make test-live`')
def test_live_nominatim():
    place = geocode('Denver, CO')
    assert place.lat == pytest.approx(39.74, abs=0.1)
    assert place.lon == pytest.approx(-104.99, abs=0.1)
