"""
fetch_folsom.py
---------------
Fetches current Folsom Lake reservoir data from the CDEC CSV web service
and appends a row to reslevels.csv.

Columns written to CSV:
    fetched_at              – timestamp of this run (Pacific time)
    data_date               – date of the most recent observation
    capacity_af             – total reservoir capacity (fixed: 977,000 AF)
    elevation_ft            – water surface elevation (sensor 6)
    storage_af              – current storage in acre-feet (sensor 15)
    storage_change_af       – change vs previous day's storage (computed)
    pct_capacity            – storage as % of capacity (sensor 23)
    average_storage_af      – historical average storage for this date (sensor 116)
    pct_of_average          – current storage as % of historical average (computed)
    outflow_cfs             – outflow in cubic feet per second (sensor 23 / outflow)
    inflow_cfs              – inflow in cubic feet per second (sensor 76)
    storage_year_ago_af     – storage one year ago on this date (computed from API)

CDEC sensor reference for FOL:
    6   – reservoir elevation (feet)
    15  – storage (acre-feet)
    23  – percent of capacity
    24  – outflow (cfs)
    76  – inflow (cfs)
    116 – historical average storage (acre-feet)

Notes:
    We use the homebrew version of python 3.11.15 which does not use the
    semi-broken / lame libressl which has problems.  So instead of downgrading
    my ssl lib I went with the newer version of python installed via homebrew.
    Also had to upgrade pip.  Created aliases for python and pip to use these.
    This new version of python uses openSSL which does NOT have these problems.
    C'mon Apple, what were you thinking???

Version History:
    4-18-26 - Created by Claude :-)
    4-20-26 - Updated python and pip and then installed required python packages
    4-20-26 - Cleanup: removed get_stats() stub, fixed timestamp to Pacific time,
              anchored CSV path to script directory, added duplicate-date guard
    4-20-26 - Rewrote data fetch to use CDEC CSV API instead of scraping the
              javareports page (which only returned the HTML shell, not data)
    4-20-26 - Expanded to full column set: capacity, elevation, storage,
              storage change, pct capacity, avg storage, pct of average,
              inflow, outflow, year-ago storage
"""

import csv
import io
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL  = "https://cdec.water.ca.gov/dynamicapp/req/CSVDataServlet"
STATION   = "FOL"
DUR_CODE  = "D"   # daily

# Folsom Lake total capacity (acre-feet) – fixed design value
FOLSOM_CAPACITY_AF = 977_000

# CDEC sensor numbers for FOL
SENSORS = {
    6:   "elevation_ft",
    15:  "storage_af",
    23:  "pct_capacity",
    24:  "outflow_cfs",
    76:  "inflow_cfs",
    116: "average_storage_af",
}

OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reslevels.csv")

OUTPUT_COLS = [
    "fetched_at",
    "data_date",
    "capacity_af",
    "elevation_ft",
    "storage_af",
    "storage_change_af",
    "pct_capacity",
    "average_storage_af",
    "pct_of_average",
    "outflow_cfs",
    "inflow_cfs",
    "storage_year_ago_af",
]

PACIFIC = ZoneInfo("America/Los_Angeles")
MISSING_SENTINELS = {"---", "ART", "BRT", "m", "-9998", "-9997", ""}


# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------

def fetch_sensor(sensor_num: int, start: str, end: str) -> str:
    """Call CDEC CSV servlet for one sensor; return raw CSV text."""
    params = {
        "Stations":   STATION,
        "SensorNums": sensor_num,
        "dur_code":   DUR_CODE,
        "Start":      start,
        "End":        end,
    }
    headers = {"User-Agent": "Mozilla/5.0 (compatible; reservoir-monitor/1.0)"}
    resp = requests.get(BASE_URL, params=params, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.text


def parse_value_for_date(csv_text: str, target_date: str) -> str | None:
    """
    Parse CDEC CSV and return the value for the given target_date (YYYY-MM-DD).
    Falls back to the most recent non-missing value if an exact match isn't found.
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    latest_date  = None
    latest_value = None

    for row in reader:
        raw_value = row.get("VALUE", "").strip()
        raw_date  = row.get("OBS DATE", "").strip()   # format: "2026-04-20 0000"

        if raw_value in MISSING_SENTINELS:
            continue
        try:
            float(raw_value)
        except ValueError:
            continue

        # Exact date match wins immediately
        if raw_date.startswith(target_date):
            return raw_value

        latest_date  = raw_date
        latest_value = raw_value

    return latest_value   # best available if exact date not found


def fetch_latest(sensor_num: int, today: str) -> str | None:
    """Fetch sensor value for today (with 2-day window for safety)."""
    start = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    csv_text = fetch_sensor(sensor_num, start, today)
    return parse_value_for_date(csv_text, today)


def fetch_for_date(sensor_num: int, date: str) -> str | None:
    """Fetch sensor value for a specific historical date."""
    start = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    csv_text = fetch_sensor(sensor_num, start, date)
    return parse_value_for_date(csv_text, date)


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def already_logged_today(filepath: str, today: str) -> bool:
    """Return True if a row for today already exists in the CSV."""
    if not os.path.isfile(filepath):
        return False
    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("fetched_at", "").startswith(today):
                return True
    return False


def append_to_csv(data: dict, filepath: str):
    """Append one row; write header first if file is new."""
    file_exists = os.path.isfile(filepath)
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(data)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    now_pt = datetime.now(PACIFIC)
    today  = now_pt.strftime("%Y-%m-%d")

    if already_logged_today(OUTPUT_FILE, today):
        print(f"WARNING: Entry for {today} already exists in '{OUTPUT_FILE}'. Skipping.")
        sys.exit(0)

    row = {col: None for col in OUTPUT_COLS}
    row["fetched_at"]  = now_pt.strftime("%Y-%m-%d %H:%M:%S %Z")
    row["capacity_af"] = FOLSOM_CAPACITY_AF

    # --- Fetch each sensor ---
    for sensor_num, col_name in SENSORS.items():
        print(f"Fetching sensor {sensor_num:3d} ({col_name}) …", end=" ", flush=True)
        value = fetch_latest(sensor_num, today)
        if value is None:
            print("NO DATA")
        else:
            print(value)
            row[col_name] = value

        # Capture the observation date from storage (sensor 15)
        if sensor_num == 15 and value is not None:
            row["data_date"] = today

    # --- Fetch year-ago storage (sensor 15, date = today minus 365 days) ---
    year_ago = (now_pt - timedelta(days=365)).strftime("%Y-%m-%d")
    print(f"Fetching sensor  15 (storage_year_ago_af, date={year_ago}) …", end=" ", flush=True)
    year_ago_val = fetch_for_date(15, year_ago)
    if year_ago_val is None:
        print("NO DATA")
    else:
        print(year_ago_val)
        row["storage_year_ago_af"] = year_ago_val

    # --- Fetch yesterday's storage to compute daily change ---
    yesterday = (now_pt - timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"Fetching sensor  15 (yesterday storage, date={yesterday}) …", end=" ", flush=True)
    yesterday_val = fetch_for_date(15, yesterday)
    if yesterday_val is None:
        print("NO DATA")
    else:
        print(yesterday_val)

    # --- Compute derived fields ---
    try:
        storage = float(row["storage_af"])

        # storage_change_af
        if yesterday_val is not None:
            row["storage_change_af"] = round(storage - float(yesterday_val), 1)

        # pct_of_average (storage / average_storage * 100)
        if row["average_storage_af"] is not None:
            avg = float(row["average_storage_af"])
            if avg > 0:
                row["pct_of_average"] = round(storage / avg * 100, 1)

    except (TypeError, ValueError):
        pass   # leave derived fields as None if source data is missing

    # --- Replace any missing values with "---" before writing ---
    for col in OUTPUT_COLS:
        if row[col] is None:
            row[col] = "---"

    # --- Write to CSV ---
    append_to_csv(row, OUTPUT_FILE)

    print(f"\nAppended to '{OUTPUT_FILE}':")
    for col in OUTPUT_COLS:
        print(f"  {col:30s}: {row[col]}")
    print("\nDone.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
