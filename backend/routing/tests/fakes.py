"""Stand-ins for requests.Session so tests never touch the network."""


class FakeResponse:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code

    def json(self):
        if isinstance(self._data, Exception):
            raise self._data
        return self._data


class FakeSession:
    """Records every GET and answers with `respond(url, params)`."""

    def __init__(self, respond):
        self.respond = respond
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({'url': url, 'params': params, 'headers': headers})
        return self.respond(url, params)
