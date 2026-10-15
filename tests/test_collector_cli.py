import sys

from api_reliability import collector


def test_cli_coordinates_are_passed_to_monitor(monkeypatch):
    """Latitude and longitude CLI arguments should reach monitor()."""
    captured = {}

    def fake_monitor(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(collector, "monitor", fake_monitor)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "collector",
            "--endpoints",
            "open-meteo",
            "--latitude",
            "35.6762",
            "--longitude",
            "139.6503",
            "--max-requests",
            "1",
        ],
    )

    collector.main()

    assert captured["endpoints"] == ["open-meteo"]
    assert captured["latitude"] == 35.6762
    assert captured["longitude"] == 139.6503
    assert captured["max_requests"] == 1


def test_monitor_passes_coordinates_to_open_meteo(monkeypatch):
    """monitor() should forward the configured coordinates to the collector."""
    captured = {}

    class FakeSession:
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

    def fake_collect_open_meteo(session, latitude, longitude, timeout):
        captured["latitude"] = latitude
        captured["longitude"] = longitude
        captured["timeout"] = timeout
        return {
            "timestamp": "2026-10-15T00:00:00+00:00",
            "endpoint": f"open-meteo:current-weather:{latitude},{longitude}",
            "response_time_ms": 1.0,
            "http_status": 200,
            "response_size_bytes": 10,
            "success": True,
            "error": None,
        }

    monkeypatch.setattr(collector.requests, "Session", FakeSession)
    monkeypatch.setattr(collector, "collect_open_meteo", fake_collect_open_meteo)
    monkeypatch.setattr(collector, "save_results", lambda results: len(results))

    collector.monitor(
        endpoints=["open-meteo"],
        interval=1,
        max_requests=1,
        latitude=35.6762,
        longitude=139.6503,
    )

    assert captured["latitude"] == 35.6762
    assert captured["longitude"] == 139.6503
    assert captured["timeout"] == 10.0
