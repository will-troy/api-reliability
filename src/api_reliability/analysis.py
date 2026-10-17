"""Stage 1–3 analysis for API Reliability Analyzer observations.

Includes endpoint summaries, time-window and hourly analysis, visualizations,
failure-streak detection, and response-size analysis.
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd

# Use a non-interactive backend so plots can be generated on a server or in CI.
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

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



def analyze_response_sizes(observations: pd.DataFrame) -> pd.DataFrame:
    """Summarize observed response payload sizes by endpoint.

    Only known, non-negative sizes are included. This measures bytes returned
    by the collector, not total network transfer size or server-side payloads.
    """
    columns = ["endpoint", "responses_with_size", "mean_response_size_bytes",
               "median_response_size_bytes", "p95_response_size_bytes",
               "min_response_size_bytes", "max_response_size_bytes"]
    if observations.empty or not {"endpoint", "response_size_bytes"}.issubset(observations.columns):
        return pd.DataFrame(columns=columns)
    data = observations.dropna(subset=["endpoint"]).copy()
    data["response_size_bytes"] = pd.to_numeric(data["response_size_bytes"], errors="coerce")
    data = data[data["response_size_bytes"].ge(0)]
    rows = []
    for endpoint, group in data.groupby("endpoint", sort=True):
        sizes = group["response_size_bytes"].dropna()
        if sizes.empty:
            continue
        rows.append({
            "endpoint": str(endpoint),
            "responses_with_size": int(sizes.count()),
            "mean_response_size_bytes": round(float(sizes.mean()), 2),
            "median_response_size_bytes": round(float(sizes.median()), 2),
            "p95_response_size_bytes": round(float(sizes.quantile(.95)), 2),
            "min_response_size_bytes": int(sizes.min()),
            "max_response_size_bytes": int(sizes.max()),
        })
    return pd.DataFrame(rows, columns=columns)


def detect_failure_streaks(observations: pd.DataFrame, min_length: int = 2) -> pd.DataFrame:
    """Find consecutive failed observations per endpoint.

    Observations are ordered by timestamp. A successful or unknown result
    breaks a streak. Each returned row represents one streak of at least
    ``min_length`` consecutive explicit failures.
    """
    if isinstance(min_length, bool) or not isinstance(min_length, int) or min_length < 1:
        raise ValueError("min_length must be a positive integer")
    columns = ["endpoint", "start_timestamp", "end_timestamp", "failure_count", "errors"]
    if observations.empty or not {"timestamp", "endpoint", "success"}.issubset(observations.columns):
        return pd.DataFrame(columns=columns)
    data = observations.dropna(subset=["timestamp", "endpoint"]).copy()
    data = data.sort_values(["endpoint", "timestamp"], kind="stable")
    rows = []
    for endpoint, group in data.groupby("endpoint", sort=True):
        streak = []
        def emit_streak(items):
            if len(items) >= min_length:
                error_values = []
                if "error" in items.columns:
                    error_values = sorted({str(value) for value in items["error"].dropna() if str(value).strip()})
                rows.append({
                    "endpoint": str(endpoint),
                    "start_timestamp": items.iloc[0]["timestamp"].isoformat(),
                    "end_timestamp": items.iloc[-1]["timestamp"].isoformat(),
                    "failure_count": len(items),
                    "errors": "; ".join(error_values),
                })
        for _, observation in group.iterrows():
            success = observation["success"]
            is_failure = pd.notna(success) and not bool(success)
            if is_failure:
                streak.append(observation)
            else:
                if streak:
                    emit_streak(pd.DataFrame(streak))
                    streak = []
        if streak:
            emit_streak(pd.DataFrame(streak))
    return pd.DataFrame(rows, columns=columns)


def _save_figure(fig, filepath: str | Path) -> Path:
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_latency_over_time(observations: pd.DataFrame, filepath: str | Path,
                           timezone_name: str = "UTC") -> Path:
    """Plot successful response latency over time, with one line per endpoint."""
    _validate_timezone(timezone_name)
    fig, ax = plt.subplots(figsize=(10, 5))
    data = observations.copy()
    if not data.empty:
        data = data.dropna(subset=["timestamp", "endpoint", LATENCY_COLUMN])
        data = data.loc[data["success"].eq(True).fillna(False)].copy()
        if not data.empty:
            data["local_timestamp"] = data["timestamp"].dt.tz_convert(timezone_name)
            for endpoint, group in data.groupby("endpoint", sort=True):
                group = group.sort_values("local_timestamp")
                ax.plot(group["local_timestamp"], group[LATENCY_COLUMN], marker=".", linewidth=1.2, label=str(endpoint))
            ax.legend(loc="best", fontsize="small")
    ax.set_title("Successful Response Latency Over Time")
    ax.set_xlabel(f"Time ({timezone_name})")
    ax.set_ylabel("Response time (ms)")
    ax.grid(True, alpha=0.3)
    fig.autofmt_xdate()
    return _save_figure(fig, filepath)


def plot_hourly_metrics(observations: pd.DataFrame, latency_filepath: str | Path,
                        error_rate_filepath: str | Path, timezone_name: str = "UTC") -> tuple[Path, Path]:
    """Create separate endpoint comparison charts for hourly latency and error rate."""
    hourly = analyze_by_hour(observations, timezone_name=timezone_name)
    fig_latency, ax_latency = plt.subplots(figsize=(10, 5))
    if not hourly.empty:
        for endpoint, group in hourly.groupby("endpoint", sort=True):
            group = group.sort_values("hour_of_day")
            ax_latency.plot(group["hour_of_day"], group["median_response_time_ms"], marker="o", label=str(endpoint))
        ax_latency.legend(loc="best", fontsize="small")
    ax_latency.set_title("Median Successful Latency by Hour of Day")
    ax_latency.set_xlabel(f"Hour of day ({timezone_name})")
    ax_latency.set_ylabel("Median response time (ms)")
    ax_latency.set_xticks(range(0, 24, 2))
    ax_latency.grid(True, alpha=0.3)
    latency_path = _save_figure(fig_latency, latency_filepath)

    fig_error, ax_error = plt.subplots(figsize=(10, 5))
    if not hourly.empty:
        for endpoint, group in hourly.groupby("endpoint", sort=True):
            group = group.sort_values("hour_of_day")
            ax_error.plot(group["hour_of_day"], group["error_rate_percent"], marker="o", label=str(endpoint))
        ax_error.legend(loc="best", fontsize="small")
    ax_error.set_title("Observed Error Rate by Hour of Day")
    ax_error.set_xlabel(f"Hour of day ({timezone_name})")
    ax_error.set_ylabel("Error rate (%)")
    ax_error.set_ylim(bottom=0)
    ax_error.set_xticks(range(0, 24, 2))
    ax_error.grid(True, alpha=0.3)
    error_path = _save_figure(fig_error, error_rate_filepath)
    return latency_path, error_path


def plot_response_sizes(observations: pd.DataFrame, filepath: str | Path) -> Path:
    """Plot response-size distributions by endpoint using boxplots."""
    fig, ax = plt.subplots(figsize=(10, 5))
    data = observations.copy()
    groups, labels = [], []
    if not data.empty and {"endpoint", "response_size_bytes"}.issubset(data.columns):
        data["response_size_bytes"] = pd.to_numeric(data["response_size_bytes"], errors="coerce")
        data = data.dropna(subset=["endpoint", "response_size_bytes"])
        data = data[data["response_size_bytes"].ge(0)]
        for endpoint, group in data.groupby("endpoint", sort=True):
            values = group["response_size_bytes"].dropna().tolist()
            if values:
                groups.append(values)
                labels.append(str(endpoint))
    if groups:
        ax.boxplot(groups, tick_labels=labels, showfliers=True)
        ax.tick_params(axis="x", labelrotation=20)
    else:
        ax.text(0.5, 0.5, "No response-size measurements available", ha="center", va="center", transform=ax.transAxes)
    ax.set_title("Response Size Distribution by Endpoint")
    ax.set_xlabel("Endpoint")
    ax.set_ylabel("Response size (bytes)")
    ax.grid(True, axis="y", alpha=0.3)
    return _save_figure(fig, filepath)


def main(argv: list[str] | None = None) -> None:
    """Print summaries, export Stage 2/3 CSVs, and generate charts."""
    parser = argparse.ArgumentParser(description="Analyze API reliability observations.")
    parser.add_argument("--input", default=str(DEFAULT_CSV_PATH), help="Input observations CSV.")
    parser.add_argument("--timezone", default="UTC", help="IANA timezone for time-based analysis (default: UTC).")
    parser.add_argument("--window-minutes", type=int, default=15, help="Time-series window size in minutes (default: 15).")
    parser.add_argument("--hourly-output", default="reports/hourly_summary.csv", help="Hourly summary CSV path.")
    parser.add_argument("--timeseries-output", default="reports/timeseries_summary.csv", help="Time-series summary CSV path.")
    parser.add_argument("--response-size-output", default="reports/response_size_summary.csv", help="Response-size summary CSV path.")
    parser.add_argument("--failure-streaks-output", default="reports/failure_streaks.csv", help="Detected failure streaks CSV path.")
    parser.add_argument("--min-failure-streak", type=int, default=2, help="Minimum consecutive failures to report (default: 2).")
    parser.add_argument("--charts-dir", default="reports/charts", help="Directory for generated PNG charts.")
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
    if args.min_failure_streak < 1:
        parser.error("--min-failure-streak must be a positive integer")

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
    response_sizes = analyze_response_sizes(observations)
    failure_streaks = detect_failure_streaks(observations, min_length=args.min_failure_streak)
    print(f"\nHourly summary ({args.timezone}): {export_report(hourly, args.hourly_output)} rows -> {args.hourly_output}")
    print(f"Time-series summary ({args.window_minutes}-minute windows): {export_report(timeseries, args.timeseries_output)} rows -> {args.timeseries_output}")
    print(f"Response-size summary: {export_report(response_sizes, args.response_size_output)} rows -> {args.response_size_output}")
    print(f"Failure streaks (minimum {args.min_failure_streak}): {export_report(failure_streaks, args.failure_streaks_output)} -> {args.failure_streaks_output}")

    charts_dir = Path(args.charts_dir)
    latency_path = plot_latency_over_time(observations, charts_dir / "latency_over_time.png", args.timezone)
    hourly_latency_path, hourly_error_path = plot_hourly_metrics(
        observations, charts_dir / "hourly_latency.png", charts_dir / "hourly_error_rate.png", args.timezone
    )
    response_size_path = plot_response_sizes(observations, charts_dir / "response_size_distribution.png")
    print("\nCharts generated:")
    for chart_path in (latency_path, hourly_latency_path, hourly_error_path, response_size_path):
        print(f"  {chart_path}")


if __name__ == "__main__":
    main()
