import argparse
import json
import time
from datetime import datetime, timezone

import requests

from api_reliability.storage import save_results

GITHUB_API_URL = "https://api.github.com/repos"
JSONPLACEHOLDER_URL = "https://jsonplaceholder.typicode.com/posts/1"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


def _request_metrics(session, endpoint, url, timeout, params=None):
    """Request an endpoint and return a common set of reliability metrics."""
    timestamp = datetime.now(timezone.utc).isoformat()
    start = time.perf_counter()
    try:
        response = session.get(url, params=params, timeout=timeout)
        elapsed = time.perf_counter() - start
        status = response.status_code
        return {
            "timestamp": timestamp,
            "endpoint": endpoint,
            "response_time_ms": round(elapsed * 1000, 2),
            "http_status": status,
            "response_size_bytes": len(response.content),
            "success": 200 <= status < 300,
            "error": None if 200 <= status < 300 else f"HTTP {status}",
        }
    except requests.RequestException as exc:
        elapsed = time.perf_counter() - start
        return {
            "timestamp": timestamp,
            "endpoint": endpoint,
            "response_time_ms": round(elapsed * 1000, 2),
            "http_status": None,
            "response_size_bytes": None,
            "success": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def collect_github(session, repo="psf/requests", timeout=10.0):
    """Measure GitHub's repository endpoint."""
    return _request_metrics(
        session, f"github:{repo}", f"{GITHUB_API_URL}/{repo}", timeout
    )


def collect_jsonplaceholder(session, timeout=10.0):
    """Measure JSONPlaceholder's sample post endpoint."""
    return _request_metrics(
        session, "jsonplaceholder:/posts/1", JSONPLACEHOLDER_URL, timeout
    )


def collect_open_meteo(
    session, latitude=40.7128, longitude=-74.0060, timeout=10.0
):
    """Measure Open-Meteo's forecast endpoint for a location."""
    return _request_metrics(
        session,
        f"open-meteo:current-weather:{latitude},{longitude}",
        OPEN_METEO_URL,
        timeout,
        params={
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,wind_speed_10m",
        },
    )


COLLECTORS = {
    "github": collect_github,
    "jsonplaceholder": collect_jsonplaceholder,
    "open-meteo": collect_open_meteo,
}


def collect_endpoint(session, endpoint, timeout=10.0):
    """Collect one named endpoint; raise ValueError for unknown names."""
    if endpoint not in COLLECTORS:
        raise ValueError(
            f"Unknown endpoint {endpoint!r}. Choose from: {', '.join(COLLECTORS)}"
        )
    return COLLECTORS[endpoint](session, timeout=timeout)


def monitor(endpoints=None, interval=60.0, timeout=10.0, max_requests=None):
    """Poll each selected endpoint once per cycle and save each observation.

    max_requests counts cycles, not individual endpoint calls.
    """
    if interval <= 0:
        raise ValueError("interval must be greater than zero")
    if timeout <= 0:
        raise ValueError("timeout must be greater than zero")
    if max_requests is not None and max_requests < 1:
        raise ValueError("max_requests must be at least 1")

    selected = list(COLLECTORS) if endpoints is None else list(endpoints)
    if not selected:
        raise ValueError("Select at least one endpoint")
    unknown = set(selected) - set(COLLECTORS)
    if unknown:
        raise ValueError(f"Unknown endpoint(s): {', '.join(sorted(unknown))}")

    results = []
    with requests.Session() as session:
        session.headers.update({
            "User-Agent": "api-reliability-analyzer/0.1",
            "Accept": "application/json",
        })
        print(f"Monitoring endpoints: {', '.join(selected)}")
        print(f"Polling interval: {interval} seconds per cycle")
        print("Press Ctrl+C to stop.\n")
        try:
            cycles = 0
            while max_requests is None or cycles < max_requests:
                cycle_start = time.perf_counter()
                for endpoint in selected:
                    result = collect_endpoint(session, endpoint, timeout)
                    results.append(result)
                    save_results([result])
                    print(json.dumps(result))
                cycles += 1
                if max_requests is not None and cycles >= max_requests:
                    break
                elapsed = time.perf_counter() - cycle_start
                time.sleep(max(0, interval - elapsed))
        except KeyboardInterrupt:
            print("\nMonitoring stopped by user.")

    print(f"Collected {len(results)} observations across {len(selected)} endpoint(s).")
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Collect API reliability measurements."
    )
    parser.add_argument(
        "--endpoints",
        nargs="+",
        choices=sorted(COLLECTORS),
        default=list(COLLECTORS),
        help="Endpoints to monitor (default: all).",
    )
    parser.add_argument("--interval", type=float, default=60)
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument(
        "--max-requests",
        type=int,
        default=None,
        help="Number of cycles; each cycle calls each selected endpoint once.",
    )
    args = parser.parse_args()
    monitor(args.endpoints, args.interval, args.timeout, args.max_requests)


if __name__ == "__main__":
    main()
