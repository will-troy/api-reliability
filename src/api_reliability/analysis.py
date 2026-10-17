"""Stage 1 and Stage 2 analysis for API Reliability Analyzer observations.

Stage 1 provides per-endpoint reliability and latency summaries. Stage 2 adds
hour-of-day summaries, time-window summaries, and CSV exports.
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd

from api_reliability.storage import DEFAULT_CSV_PATH, load_results

LATENCY_COLUMN = "response_time_ms"
REQUIRED_COLUMNS = {"timestamp", "endpoint", "response_time_ms", "http_status", "response_size_bytes", "success", "error"}


def load_observations(filepath: str | Path = DEFAULT_CSV_PATH) -> pd.DataFrame:
    """Load CSV observations and normalize timestamps, numeric fields, and booleans."""
    path = Path(filepath)
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=sorted(REQUIRED_COLUMNS))
    rows = load_results(path)
    if not rows:
        return pd.DataFrame(columns=sorted(REQUIRED_COLUMNS))
    df = pd.DataFrame(rows)
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"Observation CSV is missing required columns: {', '.join(sorted(missing))}")
    for column in ("response_time_ms", "http_status", "response_size_bytes"):
        df[column] = pd.to_numeric(df[column].replace("", pd.NA), errors="coerce")
    normalized = df["success"].astype("string").str.strip().str.lower()
    df["success"] = normalized.map({"true": True, "1": True, "yes": True, "false": False, "0": False, "no": False}).astype("boolean")
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    df["endpoint"] = df["endpoint"].astype("string")
    df["error"] = df["error"].replace("", pd.NA)
    return df


def summarize_endpoint(observations: pd.DataFrame, endpoint: str) -> dict[str, Any]:
    """Summarize request counts, reliability, latency, and HTTP statuses."""
    subset = observations.loc[observations["endpoint"] == endpoint].copy() if not observations.empty else observations.copy()
    total = len(subset)
    known = subset["success"].dropna()
    successful = int((known == True).sum())  # noqa: E712
    failed = int((known == False).sum())  # noqa: E712
    success_rate = successful / len(known) * 100 if len(known) else None
    error_rate = failed / len(known) * 100 if len(known) else None
    latencies = subset.loc[subset["success"].eq(True).fillna(False), LATENCY_COLUMN].dropna()
    latency = {
        "mean_response_time_ms": round(float(latencies.mean()), 2) if not latencies.empty else None,
        "median_response_time_ms": round(float(latencies.median()), 2) if not latencies.empty else None,
        "p95_response_time_ms": round(float(latencies.quantile(.95)), 2) if not latencies.empty else None,
        "min_response_time_ms": round(float(latencies.min()), 2) if not latencies.empty else None,
        "max_response_time_ms": round(float(latencies.max()), 2) if not latencies.empty else None,
    }
    status_counts = Counter(str(int(s)) if pd.notna(s) else "no_status" for s in subset["http_status"])
    return {
        "endpoint": endpoint, "total_requests": total, "successful_requests": successful,
        "failed_requests": failed,
        "success_rate_percent": round(success_rate, 2) if success_rate is not None else None,
        "error_rate_percent": round(error_rate, 2) if error_rate is not None else None,
        **latency, "status_code_counts": dict(sorted(status_counts.items())),
    }


def summarize_all_endpoints(observations: pd.DataFrame) -> list[dict[str, Any]]:
    """Return one Stage 1 summary for every endpoint in the data."""
    if observations.empty or "endpoint" not in observations.columns:
        return []
    endpoints = sorted(observations["endpoint"].dropna().unique().tolist())
    return [summarize_endpoint(observations, str(endpoint)) for endpoint in endpoints]


def _validate_timezone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, TypeError) as exc:
        raise ValueError(f"Unknown timezone {timezone_name!r}. Use an IANA timezone such as 'UTC' or 'America/New_York'.") from exc


def _group_metrics(group: pd.DataFrame) -> dict[str, Any]:
    """Calculate shared count, error-rate, and successful-latency metrics for a group."""
    known = group["success"].dropna()
    successful = int((known == True).sum())  # noqa: E712
    failed = int((known == False).sum())  # noqa: E712
    error_rate = failed / len(known) * 100 if len(known) else None
    latencies = group.loc[group["success"].eq(True).fillna(False), LATENCY_COLUMN].dropna()
    return {
        "request_count": len(group),
        "successful_requests": successful,
        "failed_requests": failed,
        "error_rate_percent": round(error_rate, 2) if error_rate is not None else None,
        "median_response_time_ms": round(float(latencies.median()), 2) if not latencies.empty else None,
        "p95_response_time_ms": round(float(latencies.quantile(.95)), 2) if not latencies.empty else None,
    }


def analyze_by_hour(observations: pd.DataFrame, timezone_name: str = "UTC") -> pd.DataFrame:
    """Summarize each endpoint by hour-of-day in the selected IANA timezone.

    Rows are emitted only for endpoint/hour combinations represented in the data.
    Latency statistics use successful requests with valid response times.
    """
    _validate_timezone(timezone_name)
    columns = ["endpoint", "hour_of_day", "hour_label", "request_count", "successful_requests", "failed_requests", "error_rate_percent", "median_response_time_ms", "p95_response_time_ms"]
    if observations.empty:
        return pd.DataFrame(columns=columns)
    data = observations.dropna(subset=["timestamp", "endpoint"]).copy()
    if data.empty:
        return pd.DataFrame(columns=columns)
    data["local_timestamp"] = data["timestamp"].dt.tz_convert(timezone_name)
    data["hour_of_day"] = data["local_timestamp"].dt.hour
    rows = []
    for (endpoint, hour), group in data.groupby(["endpoint", "hour_of_day"], sort=True):
        rows.append({"endpoint": str(endpoint), "hour_of_day": int(hour), "hour_label": f"{int(hour):02d}:00", **_group_metrics(group)})
    return pd.DataFrame(rows, columns=columns)


def analyze_over_time(observations: pd.DataFrame, window_minutes: int = 15, timezone_name: str = "UTC") -> pd.DataFrame:
    """Summarize endpoint metrics in clock-aligned windows (for example, 15 minutes)."""
    _validate_timezone(timezone_name)
    if isinstance(window_minutes, bool) or not isinstance(window_minutes, int) or window_minutes < 1:
        raise ValueError("window_minutes must be a positive integer")
    columns = ["endpoint", "window_start", "request_count", "successful_requests", "failed_requests", "error_rate_percent", "median_response_time_ms", "p95_response_time_ms"]
    if observations.empty:
        return pd.DataFrame(columns=columns)
    data = observations.dropna(subset=["timestamp", "endpoint"]).copy()
    if data.empty:
        return pd.DataFrame(columns=columns)
    data["local_timestamp"] = data["timestamp"].dt.tz_convert(timezone_name)
    data["window_start"] = data["local_timestamp"].dt.floor(f"{window_minutes}min")
    rows = []
    for (endpoint, start), group in data.groupby(["endpoint", "window_start"], sort=True):
        rows.append({"endpoint": str(endpoint), "window_start": start.isoformat(), **_group_metrics(group)})
    return pd.DataFrame(rows, columns=columns)


def export_report(data: pd.DataFrame, filepath: str | Path) -> int:
    """Write an analysis DataFrame to CSV, creating parent directories as needed."""
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    data.to_csv(path, index=False)
    return len(data)


def generate_report(filepath: str | Path = DEFAULT_CSV_PATH) -> dict[str, Any]:
    """Load a CSV and return the Stage 1 endpoint summaries."""
    observations = load_observations(filepath)
    return {"source": str(filepath), "observation_count": len(observations), "endpoints": summarize_all_endpoints(observations)}


def _format_percent(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f}%"


def _format_ms(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f} ms"


def main(argv: list[str] | None = None) -> None:
    """Print Stage 1 report and export Stage 2 hourly and time-series CSVs."""
    parser = argparse.ArgumentParser(description="Analyze API reliability observations.")
    parser.add_argument("--input", default=str(DEFAULT_CSV_PATH), help="Input observations CSV.")
    parser.add_argument("--timezone", default="UTC", help="IANA timezone for time-based analysis (default: UTC).")
    parser.add_argument("--window-minutes", type=int, default=15, help="Time-series window size in minutes (default: 15).")
    parser.add_argument("--hourly-output", default="reports/hourly_summary.csv", help="Hourly summary CSV path.")
    parser.add_argument("--timeseries-output", default="reports/timeseries_summary.csv", help="Time-series summary CSV path.")
    # Avoid consuming a test runner's command-line arguments when main() is
    # called directly from a unit test; the module entry point still uses CLI args.
    if argv is None:
        import sys
        argv = sys.argv[1:] if __name__ == "__main__" else []
    args = parser.parse_args(argv)
    try:
        _validate_timezone(args.timezone)
    except ValueError as exc:
        parser.error(str(exc))
    if args.window_minutes < 1:
        parser.error("--window-minutes must be a positive integer")

    observations = load_observations(args.input)
    report = {"source": args.input, "observation_count": len(observations), "endpoints": summarize_all_endpoints(observations)}
    print(f"API Reliability Report: {report['source']}")
    print(f"Total observations: {report['observation_count']}")
    if not report["endpoints"]:
        print("No observations found. Run the collector first.")
    else:
        for item in report["endpoints"]:
            print(f"\nEndpoint: {item['endpoint']}")
            print(f"  Requests: {item['total_requests']}")
            print(f"  Successful: {item['successful_requests']}")
            print(f"  Failed: {item['failed_requests']}")
            print(f"  Success rate: {_format_percent(item['success_rate_percent'])}")
            print(f"  Error rate: {_format_percent(item['error_rate_percent'])}")
            print(f"  Mean latency: {_format_ms(item['mean_response_time_ms'])}")
            print(f"  Median latency: {_format_ms(item['median_response_time_ms'])}")
            print(f"  P95 latency: {_format_ms(item['p95_response_time_ms'])}")
            print(f"  Min latency: {_format_ms(item['min_response_time_ms'])}")
            print(f"  Max latency: {_format_ms(item['max_response_time_ms'])}")
            print(f"  HTTP statuses: {item['status_code_counts']}")

    hourly = analyze_by_hour(observations, timezone_name=args.timezone)
    timeseries = analyze_over_time(observations, window_minutes=args.window_minutes, timezone_name=args.timezone)
    hourly_count = export_report(hourly, args.hourly_output)
    series_count = export_report(timeseries, args.timeseries_output)
    print(f"\nHourly summary ({args.timezone}): {hourly_count} rows -> {args.hourly_output}")
    print(f"Time-series summary ({args.window_minutes}-minute windows): {series_count} rows -> {args.timeseries_output}")


if __name__ == "__main__":
    main()
