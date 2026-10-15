import pandas as pd
import pytest

from api_reliability import analysis
from api_reliability.storage import save_results


def sample_observation(**overrides):
    """Return one valid observation, allowing individual fields to be changed."""
    observation = {
        "timestamp": "2026-10-15T12:00:00+00:00",
        "endpoint": "jsonplaceholder:/posts/1",
        "response_time_ms": 100.0,
        "http_status": 200,
        "response_size_bytes": 250,
        "success": True,
        "error": None,
    }
    observation.update(overrides)
    return observation


def write_observations(filepath, observations):
    save_results(observations, filepath)


def test_load_observations_missing_file_returns_empty_dataframe(tmp_path):
    filepath = tmp_path / "missing.csv"

    result = analysis.load_observations(filepath)

    assert result.empty
    assert set(result.columns) == analysis.REQUIRED_COLUMNS


def test_load_observations_converts_csv_values_to_expected_types(tmp_path):
    filepath = tmp_path / "observations.csv"
    write_observations(
        filepath,
        [sample_observation(), sample_observation(
            endpoint="github:psf/requests",
            response_time_ms=None,
            http_status=None,
            response_size_bytes=None,
            success=False,
            error="Timeout: timed out",
        )],
    )

    result = analysis.load_observations(filepath)

    assert len(result) == 2
    assert pd.api.types.is_datetime64_any_dtype(result["timestamp"])
    assert result.loc[0, "response_time_ms"] == 100.0
    assert result.loc[0, "http_status"] == 200
    assert bool(result.loc[0, "success"]) is True
    assert bool(result.loc[1, "success"]) is False
    assert pd.isna(result.loc[1, "http_status"])
    assert result.loc[1, "error"] == "Timeout: timed out"


def test_load_observations_rejects_missing_required_columns(tmp_path):
    filepath = tmp_path / "incomplete.csv"
    filepath.write_text("timestamp,endpoint\n2026-10-15T12:00:00Z,example\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing required columns"):
        analysis.load_observations(filepath)


def test_summarize_endpoint_calculates_reliability_and_latency_metrics(tmp_path):
    filepath = tmp_path / "observations.csv"
    write_observations(
        filepath,
        [
            sample_observation(response_time_ms=100, http_status=200),
            sample_observation(response_time_ms=200, http_status=200),
            sample_observation(response_time_ms=300, http_status=200),
            sample_observation(response_time_ms=900, http_status=503, success=False,
                               error="HTTP 503"),
            sample_observation(response_time_ms=None, http_status=None, success=False,
                               error="Timeout: timed out"),
        ],
    )
    observations = analysis.load_observations(filepath)

    summary = analysis.summarize_endpoint(observations, "jsonplaceholder:/posts/1")

    assert summary["total_requests"] == 5
    assert summary["successful_requests"] == 3
    assert summary["failed_requests"] == 2
    assert summary["success_rate_percent"] == 60.0
    assert summary["error_rate_percent"] == 40.0
    # Latency uses successful requests only: 100, 200, and 300 ms.
    assert summary["mean_response_time_ms"] == 200.0
    assert summary["median_response_time_ms"] == 200.0
    assert summary["p95_response_time_ms"] == 290.0
    assert summary["min_response_time_ms"] == 100.0
    assert summary["max_response_time_ms"] == 300.0
    assert summary["status_code_counts"] == {"200": 3, "503": 1, "no_status": 1}


def test_summarize_endpoint_returns_none_latency_when_no_requests_succeed(tmp_path):
    filepath = tmp_path / "observations.csv"
    write_observations(
        filepath,
        [
            sample_observation(success=False, http_status=503, response_time_ms=500),
            sample_observation(success=False, http_status=None, response_time_ms=None),
        ],
    )
    observations = analysis.load_observations(filepath)

    summary = analysis.summarize_endpoint(observations, "jsonplaceholder:/posts/1")

    assert summary["total_requests"] == 2
    assert summary["success_rate_percent"] == 0.0
    assert summary["error_rate_percent"] == 100.0
    assert summary["mean_response_time_ms"] is None
    assert summary["median_response_time_ms"] is None
    assert summary["p95_response_time_ms"] is None
    assert summary["min_response_time_ms"] is None
    assert summary["max_response_time_ms"] is None
    assert summary["status_code_counts"] == {"503": 1, "no_status": 1}


def test_summarize_endpoint_returns_none_rates_when_success_value_is_unknown(tmp_path):
    filepath = tmp_path / "observations.csv"
    write_observations(filepath, [sample_observation(success=None, http_status=None)])
    observations = analysis.load_observations(filepath)

    summary = analysis.summarize_endpoint(observations, "jsonplaceholder:/posts/1")

    assert summary["total_requests"] == 1
    assert summary["successful_requests"] == 0
    assert summary["failed_requests"] == 0
    assert summary["success_rate_percent"] is None
    assert summary["error_rate_percent"] is None


def test_summarize_all_endpoints_returns_sorted_endpoint_summaries(tmp_path):
    filepath = tmp_path / "observations.csv"
    write_observations(
        filepath,
        [
            sample_observation(endpoint="jsonplaceholder:/posts/1"),
            sample_observation(endpoint="github:psf/requests"),
        ],
    )

    summaries = analysis.summarize_all_endpoints(analysis.load_observations(filepath))

    assert [summary["endpoint"] for summary in summaries] == [
        "github:psf/requests",
        "jsonplaceholder:/posts/1",
    ]
    assert all(summary["total_requests"] == 1 for summary in summaries)
    assert analysis.summarize_all_endpoints(pd.DataFrame()) == []


def test_generate_report_includes_source_count_and_endpoint_summaries(tmp_path):
    filepath = tmp_path / "observations.csv"
    write_observations(
        filepath,
        [sample_observation(), sample_observation(response_time_ms=200)],
    )

    report = analysis.generate_report(filepath)

    assert report["source"] == str(filepath)
    assert report["observation_count"] == 2
    assert len(report["endpoints"]) == 1
    assert report["endpoints"][0]["endpoint"] == "jsonplaceholder:/posts/1"
    assert report["endpoints"][0]["median_response_time_ms"] == 150.0


def test_main_prints_message_when_no_observations_exist(tmp_path, monkeypatch, capsys):
    filepath = tmp_path / "empty.csv"
    monkeypatch.setattr(analysis, "DEFAULT_CSV_PATH", filepath)
    monkeypatch.setattr(analysis, "generate_report", lambda: {
        "source": str(filepath),
        "observation_count": 0,
        "endpoints": [],
    })

    analysis.main()

    output = capsys.readouterr().out
    assert "Total observations: 0" in output
    assert "No observations found. Run the collector first." in output
