"""Download actual historical 5-minute option-contract candles from Upstox V3.

Requires a contracts manifest containing historical (including expired) instrument keys:
underlying_symbol,instrument_key,option_type,strike,expiry,lot_size

Set UPSTOX_ANALYTICS_TOKEN in the environment. Historical minute data is fetched in
calendar-month chunks because the Upstox V3 minute API limits each request to one month.
If Upstox does not retain a particular expired contract, it will be logged and skipped.
"""

import argparse
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import requests


BASE_URL = "https://api.upstox.com"


def month_chunks(start, end):
    cursor = start
    while cursor <= end:
        next_month = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        chunk_end = min(end, next_month - timedelta(days=1))
        yield cursor, chunk_end
        cursor = chunk_end + timedelta(days=1)


def fetch_contract(session, instrument_key, start, end):
    key = quote(str(instrument_key), safe="")
    records = []
    for chunk_start, chunk_end in month_chunks(start, end):
        url = (
            f"{BASE_URL}/v3/historical-candle/{key}/minutes/5/"
            f"{chunk_end.isoformat()}/{chunk_start.isoformat()}"
        )
        response = session.get(url, timeout=(10, 45))
        if response.status_code == 404:
            raise RuntimeError("contract history not found (expired contract may not be retained)")
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") != "success":
            raise RuntimeError(f"Upstox API returned {payload}")
        candles = (payload.get("data") or {}).get("candles") or []
        records.extend(candles)
        time.sleep(0.15)
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--contracts", default="data/backtest/options/option_contracts.csv")
    parser.add_argument("--from-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--to-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--out", default="data/backtest/options/options_5m.csv")
    args = parser.parse_args()

    token = os.getenv("UPSTOX_ANALYTICS_TOKEN", "").strip()
    if not token:
        raise SystemExit("Set UPSTOX_ANALYTICS_TOKEN in your environment; do not hardcode it.")

    start, end = date.fromisoformat(args.from_date), date.fromisoformat(args.to_date)
    if end < start:
        raise SystemExit("--to-date must be on/after --from-date")

    contracts = pd.read_csv(args.contracts)
    required = {"underlying_symbol", "instrument_key", "option_type", "strike", "expiry"}
    if not required.issubset(contracts.columns):
        raise SystemExit(f"Contracts CSV requires columns: {sorted(required)}")

    session = requests.Session()
    session.headers.update({
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    })

    output = []
    total = len(contracts)
    for n, contract in contracts.iterrows():
        expiry = date.fromisoformat(str(contract["expiry"])[:10])
        contract_start = max(start, date.fromisoformat(str(contract.get("listing_date", start))[:10]))
        contract_end = min(end, expiry)
        if contract_end < contract_start:
            continue

        key = str(contract["instrument_key"]).strip()
        try:
            candles = fetch_contract(session, key, contract_start, contract_end)
            for candle in candles:
                if len(candle) < 6:
                    continue
                output.append({
                    "timestamp": candle[0],
                    "underlying_symbol": str(contract["underlying_symbol"]).upper(),
                    "instrument_key": key,
                    "option_type": str(contract["option_type"]).upper(),
                    "strike": float(contract["strike"]),
                    "expiry": expiry.isoformat(),
                    "open": candle[1], "high": candle[2], "low": candle[3],
                    "close": candle[4], "volume": candle[5],
                    "lot_size": contract.get("lot_size", 1),
                })
            print(f"[{n + 1}/{total}] {key}: {len(candles)} candles")
        except Exception as exc:
            print(f"[{n + 1}/{total}] SKIP {key}: {exc}")
        time.sleep(0.2)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "timestamp", "underlying_symbol", "instrument_key", "option_type",
        "strike", "expiry", "open", "high", "low", "close", "volume", "lot_size"
    ]
    pd.DataFrame(output, columns=columns).drop_duplicates(
        ["timestamp", "instrument_key"]
    ).sort_values(["underlying_symbol", "timestamp", "expiry", "strike"]).to_csv(out, index=False)
    print(f"Saved {len(output):,} option candles to {out}")
    print("Verify coverage: the manifest must include contracts and expiries across the requested test period.")


if __name__ == "__main__":
    main()
