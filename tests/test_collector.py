import requests
import pytest

from api_reliability import collector


class FakeResponse:
    def __init__(self, status_code=200, content=b'{"ok": true}'):
        self.status_code = status_code
        self.content = content


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response = response or FakeResponse()
        self.error = error
        self.headers = {}
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return self.response


@pytest.mark.parametrize(
    ("endpoint", "url"),
    [
        ("github", "https://api.github.com/repos/psf/requests"),
        ("jsonplaceholder", "https://jsonplaceholder.typicode.com/posts/1"),
        ("open-meteo", "https://api.open-meteo.com/v1/forecast"),
    ],
)
def test_collect_endpoint_success(endpoint, url):
    session = FakeSession()
    result = collector.collect_endpoint(session, endpoint)
    assert result["endpoint"].startswith(endpoint + ":")
    assert result["http_status"] == 200
    assert result["success"] is True
    assert result["response_size_bytes"] == len(session.response.content)
    assert result["response_time_ms"] >= 0
    assert result["error"] is None
    assert session.calls[0][0] == url
    assert session.calls[0][1]["timeout"] == 10.0


def test_open_meteo_sends_location_parameters():
    session = FakeSession()
    collector.collect_open_meteo(session, latitude=35.6762, longitude=139.6503)
    params = session.calls[0][1]["params"]
    assert params["latitude"] == 35.6762
    assert params["longitude"] == 139.6503
    assert params["current"] == "temperature_2m,wind_speed_10m"


def test_http_error_is_recorded_as_failure():
    result = collector.collect_jsonplaceholder(
        FakeSession(response=FakeResponse(status_code=503))
    )
    assert result["http_status"] == 503
    assert result["success"] is False
    assert result["error"] == "HTTP 503"


def test_timeout_is_recorded_as_failure():
    result = collector.collect_open_meteo(
        FakeSession(error=requests.Timeout("timed out"))
    )
    assert result["http_status"] is None
    assert result["response_size_bytes"] is None
    assert result["success"] is False
    assert "Timeout" in result["error"]


def test_unknown_endpoint_raises_value_error():
    with pytest.raises(ValueError, match="Unknown endpoint"):
        collector.collect_endpoint(FakeSession(), "unknown")
