"""Upstox futures contract discovery and real-volume candle download for research backtests."""
import gzip
import json
from datetime import date, datetime, timedelta
from io import BytesIO
from urllib.parse import quote

import pandas as pd
import requests


INSTRUMENT_FILES = {
    "NSE": "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz",
    "BSE": "https://assets.upstox.com/market-quote/instruments/exchange/BSE.json.gz",
}


def _get_data(client, path, params=None):
    # UpstoxClient.get() already unwraps the top-level data field.
    return client.get(path, params=params)


def load_bod_futures(exchange, underlying_key, symbol):
    """Load active futures from the official Upstox BOD instrument master."""
    url = INSTRUMENT_FILES[exchange]
    response = requests.get(url, timeout=(15, 60))
    response.raise_for_status()
    try:
        records = json.loads(gzip.decompress(response.content).decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Could not parse Upstox {exchange} instrument master") from error

    now = pd.Timestamp.now(tz="Asia/Kolkata")
    contracts = []
    for row in records:
        if not isinstance(row, dict):
            continue
        if row.get("segment") not in ("NSE_FO", "BSE_FO") or row.get("instrument_type") != "FUT":
            continue
        if row.get("underlying_key") != underlying_key:
            continue
        if str(row.get("underlying_symbol", "")).upper() != symbol.upper():
            continue
        expiry_raw = row.get("expiry")
        try:
            expiry = pd.to_datetime(int(expiry_raw), unit="ms", utc=True).tz_convert("Asia/Kolkata").date()
        except (TypeError, ValueError, OverflowError):
            continue
        if expiry < now.date():
            continue
        key = row.get("instrument_key")
        if key:
            contracts.append({
                "symbol": symbol,
                "instrument_key": key,
                "expired_instrument_key": "",
                "expiry": expiry.isoformat(),
                "expired": False,
                "trading_symbol": row.get("trading_symbol", ""),
            })
    return contracts


def resolve_futures_contracts(client, symbol, underlying_key, exchange, start, end):
    """Resolve expired futures via Plus APIs and active futures via BOD master."""
    expiries_payload = _get_data(
        client,
        "/v2/expired-instruments/expiries",
        {"instrument_key": underlying_key},
    )
    expiries = expiries_payload
    if not isinstance(expiries, list):
        raise RuntimeError(f"Invalid expiry list for {symbol}")

    contracts = []
    today = pd.Timestamp.now(tz="Asia/Kolkata").date()
    for expiry_text in expiries:
        try:
            expiry = date.fromisoformat(str(expiry_text))
        except ValueError:
            continue
        if expiry > today or expiry < start - timedelta(days=45) or expiry > end:
            continue
        payload = _get_data(
            client,
            "/v2/expired-instruments/future/contract",
            {"instrument_key": underlying_key, "expiry_date": expiry.isoformat()},
        )
        rows = payload
        if not isinstance(rows, list):
            raise RuntimeError(f"Invalid expired-futures response for {symbol} {expiry}")
        for row in rows:
            if not isinstance(row, dict) or row.get("instrument_type") != "FUT":
                continue
            if str(row.get("underlying_symbol", "")).upper() != symbol.upper():
                continue
            key = row.get("instrument_key")
            if key:
                contracts.append({
                    "symbol": symbol,
                    "instrument_key": key,
                    "expired_instrument_key": key,
                    "expiry": expiry.isoformat(),
                    "expired": True,
                    "trading_symbol": row.get("trading_symbol", ""),
                })

    active = load_bod_futures(exchange, underlying_key, symbol)
    contracts.extend(active)
    # Deduplicate by exact instrument key.
    unique = {item["instrument_key"]: item for item in contracts}
    result = sorted(unique.values(), key=lambda item: (item["expiry"], item["instrument_key"]))
    if not result:
        raise RuntimeError(f"No futures contracts resolved for {symbol}")
    return result


def _fetch_contract_candles(client, contract, start, end):
    expired = bool(contract["expired"])
    instrument_key = contract["instrument_key"]
    encoded_key = quote(instrument_key, safe="")
    candles = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=27), end)
        if expired:
            path = (
                f"/v2/expired-instruments/historical-candle/{encoded_key}/"
                f"5minute/{chunk_end.isoformat()}/{cursor.isoformat()}"
            )
        else:
            path = (
                f"/v3/historical-candle/{encoded_key}/minutes/5/"
                f"{chunk_end.isoformat()}/{cursor.isoformat()}"
            )
        payload = _get_data(client, path)
        rows = payload.get("candles", [])
        if not isinstance(rows, list):
            raise RuntimeError(f"Invalid candle response for {instrument_key}")
        candles.extend(rows)
        cursor = chunk_end + timedelta(days=1)
    return candles


def fetch_continuous_futures(client, contracts, symbol, start, end):
    """Fetch futures OHLCV and select the nearest-expiry contract per timestamp."""
    rows = []
    contract_expiries = {
        item["instrument_key"]: date.fromisoformat(item["expiry"])
        for item in contracts
    }
    for contract in contracts:
        expiry = date.fromisoformat(contract["expiry"])
        # A front-month futures contract is typically active well before expiry.
        contract_start = max(start, expiry - timedelta(days=75))
        contract_end = min(end, expiry)
        if contract_start > contract_end:
            continue
        candles = _fetch_contract_candles(client, contract, contract_start, contract_end)
        print(f"  {symbol} {contract['trading_symbol'] or contract['instrument_key']}: {len(candles)} candles")
        for candle in candles:
            if not isinstance(candle, list) or len(candle) < 6:
                continue
            try:
                timestamp = pd.Timestamp(candle[0])
                timestamp = timestamp.tz_localize("Asia/Kolkata") if timestamp.tzinfo is None else timestamp.tz_convert("Asia/Kolkata")
                if timestamp.date() < start or timestamp.date() > end or timestamp.date() > expiry:
                    continue
                rows.append({
                    "timestamp": timestamp,
                    "open": float(candle[1]), "high": float(candle[2]),
                    "low": float(candle[3]), "close": float(candle[4]),
                    "volume": max(float(candle[5] or 0), 0.0),
                    "contract_key": contract["instrument_key"],
                    "contract_expiry": expiry,
                    "trading_symbol": contract["trading_symbol"],
                })
            except (TypeError, ValueError, OverflowError):
                continue

    if not rows:
        raise RuntimeError(f"No futures candles returned for {symbol}")

    data = pd.DataFrame(rows).drop_duplicates(["timestamp", "contract_key"], keep="last")
    # At each timestamp, use the nearest expiry among contracts with an actual candle.
    data = data.sort_values(["timestamp", "contract_expiry", "contract_key"])
    data = data.drop_duplicates("timestamp", keep="first").sort_values("timestamp").reset_index(drop=True)
    data["session"] = data.timestamp.dt.date

    completed = data[data.timestamp + pd.Timedelta(minutes=5) <= pd.Timestamp.now(tz="Asia/Kolkata")].copy()
    if completed.empty:
        raise RuntimeError(f"No completed futures candles for {symbol}")
    volume = completed.volume.clip(lower=0)
    positive_ratio = float((volume > 0).mean())
    total_volume = float(volume.sum())
    print(
        f"  {symbol} diagnostics: bars={len(completed)}, positive-volume={positive_ratio:.1%}, "
        f"total-volume={total_volume:,.0f}, contracts={completed.contract_key.nunique()}"
    )
    if total_volume <= 0 or positive_ratio < 0.90:
        raise RuntimeError(
            f"{symbol}: futures volume invalid (positive-volume={positive_ratio:.1%}, "
            f"total-volume={total_volume}). Backtest stopped to prevent false results."
        )
    return completed.reset_index(drop=True)
