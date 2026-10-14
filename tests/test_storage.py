import csv

import pytest

from api_reliability.storage import FIELDNAMES, load_results, save_results


def sample_result(**overrides):
    """Return one observation using the collector's field names."""
    result = {
        "timestamp": "2026-10-14T18:00:00+00:00",
        "repository": "psf/requests",
        "response_time_ms": 124.51,
        "http_status": 200,
        "response_size_bytes": 6850,
        "success": True,
        "error": None,
    }
    result.update(overrides)
    return result


def test_save_results_writes_header_and_row(tmp_path):
    """Saving observations should create a CSV with the expected columns."""
    filepath = tmp_path / "observations.csv"

    saved_count = save_results([sample_result()], filepath)

    assert saved_count == 1
    with filepath.open("r", newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        assert reader.fieldnames == FIELDNAMES
        rows = list(reader)

    assert len(rows) == 1
    assert rows[0]["repository"] == "psf/requests"
    assert rows[0]["http_status"] == "200"
    assert rows[0]["success"] == "True"


def test_save_results_empty_list_does_not_create_file(tmp_path):
    """An empty collection should save zero rows and create no file."""
    filepath = tmp_path / "observations.csv"

    saved_count = save_results([], filepath)

    assert saved_count == 0
    assert not filepath.exists()


def test_save_results_appends_without_duplicate_header(tmp_path):
    """Subsequent saves should append rows without repeating the header."""
    filepath = tmp_path / "observations.csv"

    first_count = save_results([sample_result()], filepath)
    second_count = save_results(
        [sample_result(repository="python/cpython")],
        filepath,
    )

    assert first_count == 1
    assert second_count == 1

    with filepath.open("r", newline="", encoding="utf-8") as csvfile:
        rows = list(csv.reader(csvfile))

    assert rows[0] == FIELDNAMES
    assert len(rows) == 3  # one header and two observations
    assert rows[1][1] == "psf/requests"
    assert rows[2][1] == "python/cpython"


def test_save_results_creates_parent_directories(tmp_path):
    """The storage function should create missing parent directories."""
    filepath = tmp_path / "nested" / "data" / "observations.csv"

    saved_count = save_results([sample_result()], filepath)

    assert saved_count == 1
    assert filepath.exists()


def test_load_results_missing_file_returns_empty_list(tmp_path):
    """Loading a path that does not exist should return an empty list."""
    filepath = tmp_path / "missing.csv"

    assert load_results(filepath) == []


def test_load_results_reads_saved_rows_as_strings(tmp_path):
    """Loading a CSV should return row dictionaries with string values."""
    filepath = tmp_path / "observations.csv"
    save_results([sample_result()], filepath)

    rows = load_results(filepath)

    assert len(rows) == 1
    assert rows[0]["repository"] == "psf/requests"
    assert rows[0]["response_time_ms"] == "124.51"
    assert rows[0]["http_status"] == "200"
    assert rows[0]["response_size_bytes"] == "6850"
    assert rows[0]["success"] == "True"
    assert rows[0]["error"] == ""
