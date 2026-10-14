import argparse
import json
import time
from datetime import datetime, timezone

import requests

from api_reliability.storage import save_results


GITHUB_API_URL = "https://api.github.com/repos"


def collect_once(
    session: requests.Session,
    repo: str = "psf/requests",
    timeout: float = 10.0,
) -> dict:
    """Make one GitHub API request and collect its performance metrics."""
    url = f"{GITHUB_API_URL}/{repo}"
    timestamp = datetime.now(timezone.utc).isoformat()
    start = time.perf_counter()

    try:
        response = session.get(url, timeout=timeout)
        elapsed = time.perf_counter() - start

        return {
            "timestamp": timestamp,
            "repository": repo,
            "response_time_ms": round(elapsed * 1000, 2),
            "http_status": response.status_code,
            "response_size_bytes": len(response.content),
            "success": 200 <= response.status_code < 300,
            "error": None
            if 200 <= response.status_code < 300
            else f"HTTP {response.status_code}",
        }

    except requests.RequestException as exc:
        elapsed = time.perf_counter() - start

        return {
            "timestamp": timestamp,
            "repository": repo,
            "response_time_ms": round(elapsed * 1000, 2),
            "http_status": None,
            "response_size_bytes": None,
            "success": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def monitor(
    repo: str = "psf/requests",
    interval: float = 60.0,
    timeout: float = 10.0,
    max_requests: int | None = None,
) -> list[dict]:
    """Periodically query GitHub and collect the results."""
    if interval <= 0:
        raise ValueError("interval must be greater than zero")
    if timeout <= 0:
        raise ValueError("timeout must be greater than zero")
    if max_requests is not None and max_requests < 1:
        raise ValueError("max_requests must be at least 1")

    results = []

    with requests.Session() as session:
        session.headers.update({
            "Accept": "application/vnd.github+json",
            "User-Agent": "api-reliability-analyzer",
        })

        print(f"Monitoring GitHub repository: {repo}")
        print(f"Polling interval: {interval} seconds")
        print("Press Ctrl+C to stop.\n")

        try:
            while max_requests is None or len(results) < max_requests:
                result = collect_once(session, repo, timeout)
                results.append(result)
                save_results([result])

                # Print each observation as a JSON record.
                print(json.dumps(result))

                if max_requests is not None and len(results) >= max_requests:
                    break

                # Keep approximately the configured interval between
                # request start times, including request duration.
                elapsed_seconds = result["response_time_ms"] / 1000
                time.sleep(max(0, interval - elapsed_seconds))

        except KeyboardInterrupt:
            print("\nMonitoring stopped by user.")

    print(f"Collected {len(results)} observations.")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect GitHub API reliability measurements."
    )
    parser.add_argument(
        "--repo",
        default="psf/requests",
        help="GitHub repository in owner/name format.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=60,
        help="Seconds between request start times (default: 60).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10,
        help="Maximum seconds to wait for each request (default: 10).",
    )
    parser.add_argument(
        "--max-requests",
        type=int,
        default=None,
        help="Stop after this many requests; run indefinitely if omitted.",
    )

    args = parser.parse_args()
    monitor(
        repo=args.repo,
        interval=args.interval,
        timeout=args.timeout,
        max_requests=args.max_requests,
    )


if __name__ == "__main__":
    main()
