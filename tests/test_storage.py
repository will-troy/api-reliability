import csv

from api_reliability.storage import FIELDNAMES, load_results, save_results


def sample_result(**overrides):
    result = {
        "timestamp": "2026-10-14T18:00:00+00:00",
        "endpoint": "jsonplaceholder:/posts/1",
        "response_time_ms": 124.51,
        "http_status": 200,
        "response_size_bytes": 6850,
        "success": True,
        "error": None,
    }
    result.update(overrides)
    return result


def test_save_results_writes_header_and_row(tmp_path):
    filepath = tmp_path / "observations.csv"
    assert save_results([sample_result()], filepath) == 1
    with filepath.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == FIELDNAMES
        rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["endpoint"] == "jsonplaceholder:/posts/1"
    assert rows[0]["http_status"] == "200"


def test_save_results_empty_list_does_not_create_file(tmp_path):
    filepath = tmp_path / "observations.csv"
    assert save_results([], filepath) == 0
    assert not filepath.exists()


def test_save_results_appends_without_duplicate_header(tmp_path):
    filepath = tmp_path / "observations.csv"
    save_results([sample_result()], filepath)
    save_results([sample_result(endpoint="github:psf/requests")], filepath)
    with filepath.open("r", newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows[0] == FIELDNAMES
    assert len(rows) == 3
    assert rows[1][1] == "jsonplaceholder:/posts/1"
    assert rows[2][1] == "github:psf/requests"


def test_save_results_creates_parent_directories(tmp_path):
    filepath = tmp_path / "nested" / "data" / "observations.csv"
    assert save_results([sample_result()], filepath) == 1
    assert filepath.exists()


def test_load_results_missing_file_returns_empty_list(tmp_path):
    assert load_results(tmp_path / "missing.csv") == []


def test_load_results_reads_saved_rows_as_strings(tmp_path):
    filepath = tmp_path / "observations.csv"
    save_results([sample_result()], filepath)
    rows = load_results(filepath)
    assert len(rows) == 1
    assert rows[0]["endpoint"] == "jsonplaceholder:/posts/1"
    assert rows[0]["response_time_ms"] == "124.51"
    assert rows[0]["http_status"] == "200"
    assert rows[0]["response_size_bytes"] == "6850"
    assert rows[0]["success"] == "True"
    assert rows[0]["error"] == ""
