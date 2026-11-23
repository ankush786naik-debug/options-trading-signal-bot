#!/usr/bin/env python3
"""Daily NSE swing setup scanner. Telegram alerts only; no order execution."""
from __future__ import annotations

import gzip
import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

from fundamentals import score_fundamentals

IST = ZoneInfo("Asia/Kolkata")
BASE_URL = "https://api.upstox.com"
NSE_MASTER_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / "scanner_state.json"

TOKEN = os.getenv("UPSTOX_ANALYTICS_TOKEN", "").strip()
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID", "").strip()
ALERTS_ENABLED = os.getenv("ALERTS_ENABLED", "true").lower() == "true"
MIN_AVG_VALUE = float(os.getenv("MIN_AVG_VALUE", "10000000"))  # ₹1 crore
MIN_SCORE = int(os.getenv("MIN_SCORE", "70"))
MAX_WORKERS = max(1, min(int(os.getenv("MAX_WORKERS", "4")), 6))
FUNDAMENTAL_MIN_SCORE = int(os.getenv("FUNDAMENTAL_MIN_SCORE", "50"))
MAX_FUNDAMENTAL_CANDIDATES = max(5, min(int(os.getenv("MAX_FUNDAMENTAL_CANDIDATES", "60")), 100))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("daily_nse_scanner")

# Upstox documents 500 requests/min and 2,000/30 min for standard APIs.
# Keep global spacing below the per-minute ceiling, even with worker threads.
_rate_lock = threading.Lock()
_last_request = 0.0
MIN_REQUEST_GAP = 0.95  # stay below 2,000 standard requests per 30 minutes


def throttled_get(url: str, headers: dict, params: dict | None = None, timeout=30):
    global _last_request
    with _rate_lock:
        now = time.monotonic()
        wait = MIN_REQUEST_GAP - (now - _last_request)
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()
    response = requests.get(url, headers=headers, params=params, timeout=timeout)
    if response.status_code == 429:
        raise RuntimeError("Upstox API rate limit (429); scanner stopped safely.")
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") != "success":
        raise RuntimeError(f"Upstox API returned non-success: {payload}")
    return payload.get("data")


def auth_headers():
    if not TOKEN:
        raise RuntimeError("Missing UPSTOX_ANALYTICS_TOKEN GitHub secret.")
    return {"Accept": "application/json", "Authorization": f"Bearer {TOKEN}"}


def load_nse_equities() -> list[dict]:
    log.info("Downloading Upstox NSE instrument master")
    response = requests.get(NSE_MASTER_URL, timeout=60)
    response.raise_for_status()
    raw = gzip.decompress(response.content).decode("utf-8")
    rows = json.loads(raw)
    equities = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("segment") != "NSE_EQ" or row.get("exchange") != "NSE":
            continue
        if row.get("instrument_type") not in ("EQ", "BE", "BZ", "SM", "ST", "A", "B"):
            continue
        key = row.get("instrument_key")
        symbol = row.get("trading_symbol")
        if not key or not symbol or key in seen:
            continue
        # Exclude non-standard/debt instruments when security type is explicit.
        sec_type = str(row.get("security_type", "NORMAL")).upper()
        if sec_type not in ("NORMAL", ""):
            continue
        seen.add(key)
        equities.append({
            "instrument_key": key,
            "symbol": symbol,
            "name": row.get("name", symbol),
            "isin": row.get("isin") or row.get("isin_code") or "",
        })
    if not equities:
        raise RuntimeError("Instrument master loaded but no NSE EQ instruments matched.")
    log.info("Instrument master contains %d NSE equity instruments", len(equities))
    return equities


def fetch_ltp_batch(instruments: list[dict], headers: dict) -> dict[str, float]:
    """LTP endpoint accepts multiple instrument keys; batch conservatively."""
    result: dict[str, float] = {}
    # Keep URL size manageable and tolerate individual batch errors.
    for start in range(0, len(instruments), 80):
        batch = instruments[start:start + 80]
        keys = ",".join(x["instrument_key"] for x in batch)
        data = throttled_get(
            f"{BASE_URL}/v2/market-quote/ltp",
            headers,
            params={"instrument_key": keys},
        )
        if not isinstance(data, dict):
            log.warning("Unexpected LTP batch response; batch skipped")
            continue
        for response_key, quote_data in data.items():
            if not isinstance(quote_data, dict):
                continue
            price = float(quote_data.get("last_price", 0))
            if price <= 0:
                continue
            # Upstox LTP v2 response object keys are display keys such as
            # "NSE_EQ:NHPC", not the instrument_key supplied in the request.
            # The exact instrument_key is returned in instrument_token.
            instrument_key = quote_data.get("instrument_token")
            if instrument_key:
                result[str(instrument_key)] = price
            else:
                # Compatibility fallback: match by trading symbol after the colon.
                symbol = str(response_key).split(":", 1)[-1]
                for instrument in batch:
                    if instrument["symbol"] == symbol:
                        result[instrument["instrument_key"]] = price
                        break
        log.info("LTP batch %d: received %d quotes", start // 80 + 1, len(data))
    return result


def fetch_daily_candles(instrument: dict, headers: dict) -> pd.DataFrame:
    key = quote(instrument["instrument_key"], safe="")
    end = date.today()
    start = end - timedelta(days=420)
    data = throttled_get(
        f"{BASE_URL}/v3/historical-candle/{key}/days/1/{end.isoformat()}/{start.isoformat()}",
        headers,
    )
    candles = data.get("candles", []) if isinstance(data, dict) else []
    if not candles:
        raise ValueError("No daily candles")
    frame = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume", "oi"][:len(candles[0])])
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    for col in ("open", "high", "low", "close", "volume"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame.dropna(subset=["timestamp", "open", "high", "low", "close", "volume"])
    frame = frame.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    # Historical endpoint can include the current incomplete daily candle; remove it before close.
    today_ist = datetime.now(IST).date()
    frame = frame[frame["timestamp"].dt.date < today_ist].reset_index(drop=True)
    if len(frame) < 120:
        raise ValueError(f"Insufficient daily history ({len(frame)} rows)")
    return frame


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    close, high, low, volume = x["close"], x["high"], x["low"], x["volume"]
    x["ema20"] = close.ewm(span=20, adjust=False).mean()
    x["ema50"] = close.ewm(span=50, adjust=False).mean()
    x["ema200"] = close.ewm(span=200, adjust=False).mean()
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    x["rsi"] = 100 - (100 / (1 + rs))
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    x["macd"] = ema12 - ema26
    x["macd_signal"] = x["macd"].ewm(span=9, adjust=False).mean()
    x["macd_hist"] = x["macd"] - x["macd_signal"]
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    x["atr"] = tr.rolling(14).mean()
    x["vol_avg20"] = volume.rolling(20).mean()
    x["value_avg20"] = (close * volume).rolling(20).mean()
    x["support20"] = low.rolling(20).min()
    x["support50"] = low.rolling(50).min()
    x["high20"] = high.rolling(20).max()
    return x


def evaluate_setup(instrument: dict, candles: pd.DataFrame, ltp: float) -> dict | None:
    x = add_indicators(candles)
    row, prev = x.iloc[-1], x.iloc[-2]
    price = float(row.close)
    avg_value = float(row.value_avg20) if pd.notna(row.value_avg20) else 0
    if avg_value < MIN_AVG_VALUE:
        return None
    atr = float(row.atr) if pd.notna(row.atr) else 0
    if atr <= 0:
        return None

    ema20, ema50, ema200 = float(row.ema20), float(row.ema50), float(row.ema200)
    rsi = float(row.rsi) if pd.notna(row.rsi) else 0
    rsi_prev = float(prev.rsi) if pd.notna(prev.rsi) else 0
    macd_hist = float(row.macd_hist) if pd.notna(row.macd_hist) else 0
    macd_prev = float(prev.macd_hist) if pd.notna(prev.macd_hist) else 0
    vol_avg = float(row.vol_avg20) if pd.notna(row.vol_avg20) else 0
    volume_ratio = float(row.volume / vol_avg) if vol_avg > 0 else 0
    support = max(float(row.support20), float(row.support50))
    nearest_ema = min(abs(price - ema20) / price, abs(price - ema50) / price)
    near_ema = nearest_ema <= 0.035
    near_support = (price - float(row.support20)) / price <= 0.04 or (price - float(row.support50)) / price <= 0.04
    pullback = near_ema or near_support
    trend = price > ema50 and ema20 >= ema50 * 0.97
    long_trend = price > ema200
    rsi_recovery = 38 <= rsi <= 67 and rsi > rsi_prev
    macd_improving = macd_hist > macd_prev or (macd_hist > 0 and macd_prev <= 0)
    bullish_candle = float(row.close) > float(row.open) or float(row.close) >= float(prev.close)
    volume_confirm = volume_ratio >= 1.15
    breakout = price >= float(row.high20) * 0.985 and volume_ratio >= 1.3

    score = 0
    reasons = []
    if pullback:
        score += 20
        reasons.append("near EMA/support")
    if trend:
        score += 15
        reasons.append("trend above 50 EMA")
    if long_trend:
        score += 10
        reasons.append("above 200 EMA")
    if rsi_recovery:
        score += 15
        reasons.append(f"RSI recovery ({rsi:.0f})")
    if macd_improving:
        score += 15
        reasons.append("MACD momentum improving")
    if volume_confirm:
        score += 15
        reasons.append(f"volume {volume_ratio:.1f}x avg")
    if bullish_candle:
        score += 5
        reasons.append("bullish price action")
    if breakout:
        score += 10
        reasons.append("20-day breakout")
    if not (pullback or breakout) or score < MIN_SCORE:
        return None

    stop = max(float(row.support20) - 0.5 * atr, price - 1.8 * atr)
    if stop >= price:
        stop = price - 1.5 * atr
    risk_pct = (price - stop) / price * 100
    if risk_pct <= 0 or risk_pct > 10:
        return None
    target1 = price * 1.05
    target2 = price * 1.10
    stretch = min(price * 1.15, price + 3 * atr)
    return {
        "symbol": instrument["symbol"],
        "name": instrument["name"],
        "price": price,
        "score": min(score, 100),
        "rsi": rsi,
        "volume_ratio": volume_ratio,
        "stop": stop,
        "risk_pct": risk_pct,
        "target1": target1,
        "target2": target2,
        "stretch": stretch,
        "reasons": reasons,
        "asof": str(row.timestamp)[:10],
    }


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"sent": {}}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def telegram_send(text: str):
    if not ALERTS_ENABLED:
        log.info("Telegram alerts disabled; message not sent")
        return
    if not TG_TOKEN or not TG_CHAT:
        raise RuntimeError("Telegram enabled but TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID is missing")
    response = requests.post(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        data={"chat_id": TG_CHAT, "text": text, "disable_web_page_preview": True},
        timeout=25,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram API returned error: {payload}")


def format_signal(s: dict) -> str:
    why = ", ".join(s["reasons"])
    fundamental_why = ", ".join(s.get("fundamental_reasons", [])) or "Not available"
    return (
        f"🟢 NSE SWING BUY SETUP — {s['symbol']}\n"
        f"{s['name']} | Combined: {s['score']}/100 (Tech {s.get('technical_score', s['score'])}, Fund {s.get('fundamental_score', 0)})\n"
        f"Close: ₹{s['price']:.2f} | RSI: {s['rsi']:.1f} | Vol: {s['volume_ratio']:.2f}x\n"
        f"Entry zone: ₹{s['price'] * 0.995:.2f}–₹{s['price'] * 1.005:.2f}\n"
        f"Stop-loss: ₹{s['stop']:.2f} ({s['risk_pct']:.1f}% risk)\n"
        f"Target 1 (+5%): ₹{s['target1']:.2f}\n"
        f"Target 2 (+10%): ₹{s['target2']:.2f}\n"
        f"Stretch (+up to 15%): ₹{s['stretch']:.2f}\n"
        f"Fundamentals: {fundamental_why}\n"
        f"Technical setup: {why}\n"
        f"Data date: {s['asof']}\n"
        f"Signal only — verify chart/news and manage risk."
    )


def send_batched(messages: list[str]):
    batch = ""
    for message in messages:
        if len(batch) + len(message) + 2 > 3800:
            if batch:
                telegram_send(batch)
            batch = message
        else:
            batch = f"{batch}\n\n{message}" if batch else message
    if batch:
        telegram_send(batch)


def main():
    headers = auth_headers()
    universe = load_nse_equities()
    ltp_map = fetch_ltp_batch(universe, headers)
    if not ltp_map:
        raise RuntimeError(
            "Upstox LTP endpoint returned no usable prices. "
            "Check API access and LTP response mapping; scanner will not report this as zero eligible stocks."
        )
    # No price boundary: include every NSE equity with a valid positive LTP.
    price_candidates = [
        item for item in universe
        if ltp_map.get(item["instrument_key"], 0) > 0
    ]
    log.info("No price boundary: %d / %d NSE EQ stocks have valid LTP",
             len(price_candidates), len(universe))
    if not price_candidates:
        telegram_send("Daily NSE Stock Scanner: no NSE equities returned a valid LTP.")
        return

    results = []
    failures = 0
    log.info("Fetching daily candles for %d candidates using %d workers", len(price_candidates), MAX_WORKERS)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(fetch_daily_candles, item, headers): item for item in price_candidates}
        for future in as_completed(futures):
            item = futures[future]
            try:
                candles = future.result()
                signal = evaluate_setup(item, candles, ltp_map.get(item["instrument_key"], 0))
                if signal:
                    results.append(signal)
            except Exception as exc:
                failures += 1
                log.warning("Skip %s: %s", item["symbol"], str(exc)[:180])

    results.sort(key=lambda item: (-item["score"], item["risk_pct"], item["symbol"]))
    technical_pool = results[:MAX_FUNDAMENTAL_CANDIDATES]
    ranked = []
    fundamental_failures = 0
    log.info("Fundamental analysis for top %d technical candidates", len(technical_pool))
    for signal in technical_pool:
        instrument = next((x for x in price_candidates if x["symbol"] == signal["symbol"]), None)
        if not instrument:
            continue
        try:
            fundamentals = score_fundamentals(instrument.get("isin", ""), headers)
            if not fundamentals:
                fundamental_failures += 1
                log.info("Skip %s: insufficient fundamental coverage", signal["symbol"])
                continue
            signal.update(fundamentals)
            if signal["fundamental_score"] < FUNDAMENTAL_MIN_SCORE:
                log.info("Skip %s: fundamental score %d below minimum %d",
                         signal["symbol"], signal["fundamental_score"], FUNDAMENTAL_MIN_SCORE)
                continue
            signal["technical_score"] = signal["score"]
            signal["score"] = round(0.45 * signal["technical_score"] + 0.55 * signal["fundamental_score"])
            ranked.append(signal)
        except Exception as exc:
            fundamental_failures += 1
            log.warning("Fundamentals unavailable for %s: %s", signal["symbol"], str(exc)[:180])

    ranked.sort(key=lambda item: (-item["score"], -item["fundamental_score"],
                                  -item["technical_score"], item["risk_pct"], item["symbol"]))
    results = ranked[:5]

    state = load_state()
    today_key = datetime.now(IST).date().isoformat()
    sent = state.setdefault("sent", {})
    already = set(sent.get(today_key, []))
    new_signals = [s for s in results if s["symbol"] not in already]

    log.info("Final Top 5: %d stocks; %d new alerts; %d candle failures; %d fundamental failures",
             len(results), len(new_signals), failures, fundamental_failures)
    header = (
        f"🏆 TOP NSE SWING STOCKS — {today_key}\n"
        f"Universe: {len(universe)} NSE EQ | Price candidates: {len(price_candidates)}\n"
        f"Technical setups: {len(technical_pool)} screened with Upstox fundamentals\n"
        f"Top stocks passing fundamental score ≥ {FUNDAMENTAL_MIN_SCORE}: {len(results)} (max 5)\n"
        f"Price boundary: NONE | Fundamental/technical blend: 55%/45%\n"
        f"Fundamental data: Upstox financials, ratios, cash flow and balance sheet\n"
        f"Signal-only research; no orders placed. Targets are not guaranteed."
    )
    messages = [header]
    messages.extend(format_signal(s) for s in new_signals)
    if not results:
        messages.append("No stocks met the combined fundamental + technical quality threshold today. No forced picks.")
    send_batched(messages)

    sent[today_key] = sorted(already | {s["symbol"] for s in new_signals})
    for old_day in sorted(sent)[:-10]:
        sent.pop(old_day, None)
    save_state(state)

if __name__ == "__main__":
    main()
