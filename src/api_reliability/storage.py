import csv
from pathlib import Path
from typing import Iterable, Mapping

DEFAULT_CSV_PATH = Path("data/observations.csv")
FIELDNAMES = [
    "timestamp",
    "endpoint",
    "response_time_ms",
    "http_status",
    "response_size_bytes",
    "success",
    "error",
]


def save_results(results: Iterable[Mapping[str, object]],
                 filepath: str | Path = DEFAULT_CSV_PATH) -> int:
    """Append observations to CSV and return how many rows were written."""
    results = list(results)
    if not results:
        return 0
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(
            csvfile, fieldnames=FIELDNAMES, extrasaction="raise"
        )
        if write_header:
            writer.writeheader()
        writer.writerows(results)
    return len(results)


def load_results(filepath: str | Path = DEFAULT_CSV_PATH) -> list[dict[str, str]]:
    """Load CSV observations; values are returned as strings."""
    path = Path(filepath)
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as csvfile:
        return list(csv.DictReader(csvfile))
