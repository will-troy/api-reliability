# API Reliability Analyzer

A Python tool that monitors public APIs, collects performance metrics, and analyzes their reliability over time.

## Features

- **API monitoring:** Collects response times, HTTP status codes, response sizes, and success or failure results.
- **Multiple APIs:** Supports GitHub, JSONPlaceholder, and Open-Meteo.
- **Data storage:** Saves observations to a CSV file for later analysis.
- **Reliability analysis:** Calculates success rates, error rates, and response-time statistics, including median and 95th-percentile latency.
- **Time-based analysis:** Groups results by hour and time window.
- **Failure detection:** Identifies consecutive API failures.
- **Visualizations:** Generates charts showing latency trends, hourly performance, error rates, and response-size distributions.
- **Testing:** Uses pytest to test project functionality.

## Requirements

- Python 3.11 or later
- pip

## Installation

Clone the repository and navigate into the project directory:

```bash
git clone https://github.com/will-troy/api-reliability
cd api-reliability
```

Create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

Install the project and development dependencies:

```bash
python -m pip install -e ".[dev]"
```

## Usage

### 1. Collect API observations

Run the collector:

```bash
python -m api_reliability.collector
```

By default, the collector monitors all supported APIs every 60 seconds until stopped with `Ctrl+C`.

To limit the number of collection cycles:

```bash
python -m api_reliability.collector --max-requests 10
```

To monitor specific endpoints:

```bash
python -m api_reliability.collector --endpoints github jsonplaceholder
```

Observations are saved to `data/observations.csv`.

### 2. Analyze the collected data

Run the analysis module:

```bash
python -m api_reliability.analysis
```

To analyze timestamps in a different time zone:

```bash
python -m api_reliability.analysis --timezone Asia/Tokyo
```

The analysis produces summary CSV files in `reports/` and charts in `reports/charts/`.

**Tip:** Collect data before running the analysis to produce meaningful results.

### 3. Run tests

Run the test suite with:

```bash
python -m pytest -v
```

## Project Structure

```text
api-reliability/
├── src/
│   └── api_reliability/
│       ├── collector.py   # API requests and monitoring
│       ├── storage.py     # CSV data storage
│       └── analysis.py    # Metrics, reports, and charts
├── tests/                 # Automated tests
├── data/                  # Collected observations
├── reports/               # Analysis outputs
├── pyproject.toml         # Project configuration
└── README.md
```

## Technologies

- **Python** — application logic and monitoring
- **Requests** — HTTP requests
- **Pandas** — data processing and analysis
- **Matplotlib** — visualizations
- **pytest** — automated testing

## Project Goals

This project demonstrates practical Python development, HTTP API integration, data collection, statistical analysis, visualization, automated testing, and Git-based version control.
