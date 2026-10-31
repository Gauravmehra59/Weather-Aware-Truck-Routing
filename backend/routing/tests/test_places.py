import os

import pytest
import requests
from django.core.cache import cache
from django.test import Client

from routing.services import places
from routing.services.places import PlaceSearchError, parse_suggestions, suggest

from .fakes import FakeResponse, FakeSession


def feature(lon, lat, **props):
    return {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [lon, lat]}, 'properties': props}


CHICAGO = feature(-87.62, 41.88, name='Chicago', state='Illinois', countrycode='US', type='city')
CHICAGO_HEIGHTS = feature(-87.64, 41.51, name='Chicago Heights', state='Illinois', countrycode='US')
WHITE_HOUSE = feature(-77.04, 38.90, name='White House', housenumber='1600',
                      street='Pennsylvania Avenue Northwest', city='Washington',
                      state='District of Columbia', countrycode='US')
BARE_ADDRESS = feature(-80.13, 25.79, housenumber='1600', street='Pennsylvania Avenue',
                       city='Miami Beach', state='Florida', countrycode='US')


@pytest.fixture(autouse=True)
def fresh_cache_and_no_waiting(monkeypatch):
    cache.clear()
    monkeypatch.setattr(places._limiter, 'min_interval_s', 0)


def answer(*features, status=200):
    return FakeSession(lambda url, params: FakeResponse(
        {'type': 'FeatureCollection', 'features': list(features)}, status
    ))


class TestParseSuggestions:
    def test_city(self):
        assert parse_suggestions({'features': [CHICAGO]}) == [
            {'label': 'Chicago, Illinois, US', 'lat': 41.88, 'lon': -87.62}
        ]

    def test_named_address(self):
        label = parse_suggestions({'features': [WHITE_HOUSE]})[0]['label']
        assert label == 'White House, 1600 Pennsylvania Avenue Northwest, Washington, District of Columbia, US'

    def test_unnamed_address(self):
        label = parse_suggestions({'features': [BARE_ADDRESS]})[0]['label']
        assert label == '1600 Pennsylvania Avenue, Miami Beach, Florida, US'

    def test_city_named_like_its_state_is_not_repeated(self):
        ny = feature(-74.0, 40.7, name='New York', city='New York', state='New York', countrycode='US')
        assert parse_suggestions({'features': [ny]})[0]['label'] == 'New York, US'

    def test_duplicate_labels_are_dropped(self):
        assert len(parse_suggestions({'features': [CHICAGO, CHICAGO, CHICAGO_HEIGHTS]})) == 2

    def test_capped_at_max_suggestions(self):
        many = [feature(-90, 40 + i / 10, name=f'Town {i}', countrycode='US') for i in range(20)]
        assert len(parse_suggestions({'features': many})) == places.MAX_SUGGESTIONS

    def test_north_america_first_keeping_relevance_order(self):
        springs_za = feature(28.4, -26.25, name='Springs', state='Gauteng', countrycode='ZA')
        spring_tx = feature(-95.4, 30.08, name='Spring', state='Texas', countrycode='US')
        springe_de = feature(9.55, 52.2, name='Springe', state='Lower Saxony', countrycode='DE')
        springfield = feature(-89.65, 39.8, name='Springfield', state='Illinois', countrycode='US')
        labels = [s['label'] for s in parse_suggestions(
            {'features': [spring_tx, springs_za, springe_de, springfield]}
        )]
        assert labels == [
            'Spring, Texas, US', 'Springfield, Illinois, US',
            'Springs, Gauteng, ZA', 'Springe, Lower Saxony, DE',
        ]

    def test_empty(self):
        assert parse_suggestions({'features': []}) == []


class TestSuggest:
    @pytest.mark.parametrize('query', ['', '  ', 'ch', None])
    def test_short_queries_make_no_request(self, query):
        session = answer(CHICAGO)
        assert suggest(query, session) == []
        assert session.calls == []

    def test_request_params_and_user_agent(self, settings):
        settings.PHOTON_URL = 'https://photon.test/api/'
        settings.HTTP_USER_AGENT = 'test-agent/1.0'
        session = answer(CHICAGO)
        suggest('  chica  ', session)
        call = session.calls[0]
        assert call['url'] == 'https://photon.test/api/'
        assert call['params']['q'] == 'chica'
        assert (call['params']['lat'], call['params']['lon']) == places.BIAS_POINT
        assert call['params']['zoom'] == places.BIAS_ZOOM
        assert 'house' in call['params']['layer'] and 'other' not in call['params']['layer']
        assert call['headers'] == {'User-Agent': 'test-agent/1.0'}

    def test_results_are_cached(self):
        session = answer(CHICAGO)
        assert suggest('Chica', session) == suggest('chica', session)
        assert len(session.calls) == 1

    def test_empty_results_are_cached_too(self):
        session = answer()
        suggest('xyzzy', session)
        suggest('xyzzy', session)
        assert len(session.calls) == 1

    def test_http_error(self):
        with pytest.raises(PlaceSearchError, match='503'):
            suggest('chica', answer(status=503))

    def test_network_failure(self):
        def fail(url, params):
            raise requests.Timeout('slow')

        with pytest.raises(PlaceSearchError, match='unavailable'):
            suggest('chica', FakeSession(fail))


class TestPlacesEndpoint:
    def test_returns_suggestions(self, monkeypatch):
        monkeypatch.setattr(places.requests, 'Session', lambda: answer(CHICAGO))
        response = Client().get('/api/places/', {'q': 'chica'})
        assert response.status_code == 200
        assert response.json()[0]['label'] == 'Chicago, Illinois, US'

    def test_missing_query(self):
        assert Client().get('/api/places/').status_code == 400

    def test_upstream_failure_is_502(self, monkeypatch):
        monkeypatch.setattr(places.requests, 'Session', lambda: answer(status=500))
        response = Client().get('/api/places/', {'q': 'chica'})
        assert response.status_code == 502


@pytest.mark.skipif(not os.environ.get('RUN_LIVE_TESTS'), reason='hits the real API; run `make test-live`')
def test_live_photon():
    results = suggest('chica')
    assert results[0]['label'].startswith('Chicago')
    labels = [s['label'] for s in suggest('springfield')]
    assert all(label.endswith(', US') for label in labels)
