"""Download 1m/5m/15m index candles from Upstox V3 into research/data.

Environment:
  UPSTOX_ANALYTICS_TOKEN (required)
  RESEARCH_LOOKBACK_DAYS (optional, default 365)
"""
from __future__ import annotations

import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import pandas as pd
import requests

IST = ZoneInfo("Asia/Kolkata")
TOKEN = os.getenv("UPSTOX_ANALYTICS_TOKEN", "").strip()
LOOKBACK_DAYS = int(os.getenv("RESEARCH_LOOKBACK_DAYS", "365"))
OUT_DIR = Path("data/backtest/underlying")

INSTRUMENTS = {
    "NIFTY": "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "SENSEX": "BSE_INDEX|SENSEX",
}
INTERVALS = (1, 5, 15)
API_ROOT = "https://api.upstox.com/v3/historical-candle"


def fetch_chunk(session: requests.Session, key: str, minutes: int,
                start: date, end: date) -> list[list]:
    encoded_key = quote(key, safe="")
    url = (
        f"{API_ROOT}/{encoded_key}/minutes/{minutes}/"
        f"{end.isoformat()}/{start.isoformat()}"
    )
    for attempt in range(6):
        response = session.get(url, timeout=(15, 60))
        if response.status_code == 200:
            payload = response.json()
            if payload.get("status") != "success":
                raise RuntimeError(f"Upstox API returned: {payload}")
            return payload.get("data", {}).get("candles", [])

        if response.status_code == 429 or response.status_code >= 500:
            delay = min(2 ** attempt, 30)
            print(f"Retry HTTP {response.status_code}; waiting {delay}s")
            time.sleep(delay)
            continue

        raise RuntimeError(
            f"Upstox HTTP {response.status_code}: {response.text[:500]}"
        )

    raise RuntimeError(f"Failed after retries: {key}, {minutes}m, {start}-{end}")


def download_one(session: requests.Session, symbol: str, key: str,
                minutes: int, start: date, end: date) -> Path:
    print(f"\n{symbol} {minutes}m: {start} through {end}")
    records: list[list] = []
    cursor = start

    # V3 minute candle endpoints allow at most one month per request.
    # 28-day chunks avoid boundary/range-limit problems.
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=27), end)
        chunk = fetch_chunk(session, key, minutes, cursor, chunk_end)
        print(f"  {cursor} - {chunk_end}: {len(chunk):,} candles")
        records.extend(chunk)
        cursor = chunk_end + timedelta(days=1)
        time.sleep(0.25)

    if not records:
        raise RuntimeError(f"No candles returned for {symbol} {minutes}m")

    columns = ["timestamp", "open", "high", "low", "close", "volume", "open_interest"]
    rows = []
    for row in records:
        if not isinstance(row, list) or len(row) < 6:
            continue
        values = list(row[:7])
        if len(values) == 6:
            values.append(None)
        rows.append(values)
    df = pd.DataFrame(rows, columns=columns)

    # Upstox timestamps include an IST offset. Preserve that timestamp string
    # in the CSV and use UTC-normalized values only for deduplication/sorting.
    ts = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.loc[ts.notna()].copy()
    df["_sort_ts"] = ts.loc[ts.notna()]
    df = df.drop_duplicates("_sort_ts").sort_values("_sort_ts")
    df = df.drop(columns="_sort_ts").reset_index(drop=True)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    output = OUT_DIR / f"{symbol}_{minutes}m.csv"
    df.to_csv(output, index=False)
    print(f"Saved {output} ({len(df):,} rows)")
    return output


def main() -> None:
    if not TOKEN:
        raise SystemExit(
            "Missing UPSTOX_ANALYTICS_TOKEN. Set it as an environment secret; "
            "do not hard-code or commit the token."
        )
    if LOOKBACK_DAYS < 30 or LOOKBACK_DAYS > 365:
        raise SystemExit("RESEARCH_LOOKBACK_DAYS must be between 30 and 365.")

    # Use yesterday as end date to avoid an incomplete current trading day.
    end = datetime.now(IST).date() - timedelta(days=1)
    start = end - timedelta(days=LOOKBACK_DAYS - 1)

    session = requests.Session()
    session.headers.update({
        "Accept": "application/json",
        "Authorization": f"Bearer {TOKEN}",
    })

    print(f"Downloading {LOOKBACK_DAYS} calendar days: {start} to {end}")
    print("Symbols:", ", ".join(INSTRUMENTS))
    print("Intervals:", INTERVALS)

    outputs = []
    for symbol, instrument_key in INSTRUMENTS.items():
        for minutes in INTERVALS:
            outputs.append(
                download_one(session, symbol, instrument_key, minutes, start, end)
            )

    print("\nDOWNLOAD FINISHED")
    for path in outputs:
        print(f"{path} | {path.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
