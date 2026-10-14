
import requests

from api_reliability import collector


def test_collect_once_success():
    """A successful HTTP response should produce valid measurements."""
    session = requests.Session()
    response = requests.Response()
    response.status_code = 200
    response._content = b'{"message": "success"}'

    # Replace the real HTTP request with a simulated response.
    session.get = lambda *args, **kwargs: response

    result = collector.collect_once(session, repo="psf/requests")

    assert result["repository"] == "psf/requests"
    assert result["http_status"] == 200
    assert result["success"] is True
    assert result["response_size_bytes"] == len(response.content)
    assert result["response_time_ms"] >= 0
    assert result["error"] is None
    assert result["timestamp"] is not None

    session.close()


def test_collect_once_http_error():
    """An HTTP error should be recorded as an unsuccessful request."""
    session = requests.Session()
    response = requests.Response()
    response.status_code = 404
    response._content = b'{"message": "Not Found"}'

    session.get = lambda *args, **kwargs: response

    result = collector.collect_once(session, repo="invalid/repository")

    assert result["http_status"] == 404
    assert result["success"] is False
    assert result["error"] == "HTTP 404"
    assert result["response_size_bytes"] == len(response.content)

    session.close()


def test_collect_once_timeout():
    """A timeout should be recorded rather than crashing the collector."""
    session = requests.Session()

    def raise_timeout(*args, **kwargs):
        raise requests.Timeout("Request timed out")

    session.get = raise_timeout

    result = collector.collect_once(session)

    assert result["http_status"] is None
    assert result["response_size_bytes"] is None
    assert result["success"] is False
    assert "Timeout" in result["error"]

    session.close()


def test_collect_once_connection_error():
    """A connection failure should be recorded as an unsuccessful request."""
    session = requests.Session()

    def raise_connection_error(*args, **kwargs):
        raise requests.ConnectionError("Connection failed")

    session.get = raise_connection_error

    result = collector.collect_once(session)

    assert result["http_status"] is None
    assert result["success"] is False
    assert "ConnectionError" in result["error"]

    session.close()


def test_monitor_makes_requested_number_of_requests(monkeypatch):
    """The monitor should stop after max_requests observations."""
    observations = []

    def fake_collect_once(session, repo, timeout):
        result = {
            "repository": repo,
            "success": True,
            "response_time_ms": 5.0,
        }
        observations.append(result)
        return result

    class FakeSession:
        """A session substitute that doesn't make network requests."""

        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(collector, "collect_once", fake_collect_once)
    monkeypatch.setattr(
        collector.requests,
        "Session",
        lambda: FakeSession(),
    )
    monkeypatch.setattr(collector.time, "sleep", lambda seconds: None)

    results = collector.monitor(
        repo="psf/requests",
        interval=1,
        max_requests=3,
    )

    assert len(results) == 3
    assert len(observations) == 3
    assert all(result["success"] for result in results)


def test_monitor_rejects_invalid_interval():
    """The monitor should reject zero or negative polling intervals."""
    import pytest

    with pytest.raises(ValueError, match="interval"):
        collector.monitor(interval=0)

    with pytest.raises(ValueError, match="interval"):
        collector.monitor(interval=-1)
