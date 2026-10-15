"""Analysis for API Reliability Analyzer observations.

This module reads observations saved by :mod:`api_reliability.storage` and
calculates per-endpoint reliability and latency summaries. It does not make
HTTP requests or modify the source CSV.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from api_reliability.storage import DEFAULT_CSV_PATH, load_results


LATENCY_COLUMN = "response_time_ms"
REQUIRED_COLUMNS = {
    "timestamp",
    "endpoint",
    "response_time_ms",
    "http_status",
    "response_size_bytes",
    "success",
    "error",
}


def load_observations(
    filepath: str | Path = DEFAULT_CSV_PATH,
) -> pd.DataFrame:
    """Load observations into a DataFrame and normalize common CSV values.

    CSV values are strings, so this converts numeric fields and the ``success``
    field to appropriate types. Invalid or missing numeric values become NaN.
    Missing files and empty CSVs produce an empty DataFrame.
    """
    path = Path(filepath)
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=sorted(REQUIRED_COLUMNS))

    rows = load_results(path)
    if not rows:
        return pd.DataFrame(columns=sorted(REQUIRED_COLUMNS))

    df = pd.DataFrame(rows)
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        missing_columns = ", ".join(sorted(missing))
        raise ValueError(f"Observation CSV is missing required columns: {missing_columns}")

    for column in ("response_time_ms", "http_status", "response_size_bytes"):
        df[column] = pd.to_numeric(df[column].replace("", pd.NA), errors="coerce")

    # CSV DictReader reads booleans as strings; handle common true/false forms.
    normalized_success = df["success"].astype("string").str.strip().str.lower()
    df["success"] = normalized_success.map(
        {"true": True, "1": True, "yes": True, "false": False, "0": False, "no": False}
    ).astype("boolean")

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    df["endpoint"] = df["endpoint"].astype("string")
    df["error"] = df["error"].replace("", pd.NA)
    return df


def summarize_endpoint(observations: pd.DataFrame, endpoint: str) -> dict[str, Any]:
    """Summarize request counts, reliability, latency, and HTTP statuses.

    Latency statistics are calculated from successful requests with valid
    response times. Success/error rates use observations with a known success
    value as the denominator. The returned ``status_code_counts`` maps status
    code strings (for example ``"200"`` or ``"503"``) to request counts; rows
    without an HTTP status are counted under ``"no_status"``.
    """
    if observations.empty:
        subset = observations.copy()
    else:
        subset = observations.loc[observations["endpoint"] == endpoint].copy()

    total_requests = len(subset)
    known_success = subset["success"].dropna()
    measured_requests = len(known_success)
    successful_requests = int((known_success == True).sum())  # noqa: E712
    failed_requests = int((known_success == False).sum())  # noqa: E712

    success_rate = (
        successful_requests / measured_requests * 100 if measured_requests else None
    )
    error_rate = failed_requests / measured_requests * 100 if measured_requests else None

    successful_latencies = subset.loc[
        subset["success"].eq(True).fillna(False), LATENCY_COLUMN
    ].dropna()

    if successful_latencies.empty:
        latency_summary = {
            "mean_response_time_ms": None,
            "median_response_time_ms": None,
            "p95_response_time_ms": None,
            "min_response_time_ms": None,
            "max_response_time_ms": None,
        }
    else:
        latency_summary = {
            "mean_response_time_ms": round(float(successful_latencies.mean()), 2),
            "median_response_time_ms": round(float(successful_latencies.median()), 2),
            "p95_response_time_ms": round(
                float(successful_latencies.quantile(0.95)), 2
            ),
            "min_response_time_ms": round(float(successful_latencies.min()), 2),
            "max_response_time_ms": round(float(successful_latencies.max()), 2),
        }

    status_codes = subset["http_status"]
    status_counts = Counter(
        str(int(status)) if pd.notna(status) else "no_status"
        for status in status_codes
    )

    return {
        "endpoint": endpoint,
        "total_requests": total_requests,
        "successful_requests": successful_requests,
        "failed_requests": failed_requests,
        "success_rate_percent": round(success_rate, 2) if success_rate is not None else None,
        "error_rate_percent": round(error_rate, 2) if error_rate is not None else None,
        **latency_summary,
        "status_code_counts": dict(sorted(status_counts.items())),
    }


def summarize_all_endpoints(observations: pd.DataFrame) -> list[dict[str, Any]]:
    """Return one Stage 1 summary for every endpoint found in the data."""
    if observations.empty or "endpoint" not in observations.columns:
        return []

    endpoints = sorted(observations["endpoint"].dropna().unique().tolist())
    return [summarize_endpoint(observations, str(endpoint)) for endpoint in endpoints]


def generate_report(
    filepath: str | Path = DEFAULT_CSV_PATH,
) -> dict[str, Any]:
    """Load a CSV and return a report containing all endpoint summaries."""
    observations = load_observations(filepath)
    return {
        "source": str(filepath),
        "observation_count": len(observations),
        "endpoints": summarize_all_endpoints(observations),
    }


def main() -> None:
    """Print a readable Stage 1 report for the default observations CSV."""
    report = generate_report()
    print(f"API Reliability Report: {report['source']}")
    print(f"Total observations: {report['observation_count']}")

    if not report["endpoints"]:
        print("No observations found. Run the collector first.")
        return

    for summary in report["endpoints"]:
        print(f"\nEndpoint: {summary['endpoint']}")
        print(f"  Requests: {summary['total_requests']}")
        print(f"  Successful: {summary['successful_requests']}")
        print(f"  Failed: {summary['failed_requests']}")
        print(f"  Success rate: {_format_percent(summary['success_rate_percent'])}")
        print(f"  Error rate: {_format_percent(summary['error_rate_percent'])}")
        print(f"  Mean latency: {_format_ms(summary['mean_response_time_ms'])}")
        print(f"  Median latency: {_format_ms(summary['median_response_time_ms'])}")
        print(f"  P95 latency: {_format_ms(summary['p95_response_time_ms'])}")
        print(f"  Min latency: {_format_ms(summary['min_response_time_ms'])}")
        print(f"  Max latency: {_format_ms(summary['max_response_time_ms'])}")
        print(f"  HTTP statuses: {summary['status_code_counts']}")


def _format_percent(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f}%"


def _format_ms(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f} ms"


if __name__ == "__main__":
    main()
