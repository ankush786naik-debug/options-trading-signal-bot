
from config import MAX_SPREAD_PCT


def safe_float(value, default=0.0):

    try:
        number = float(value)

        if number != number:
            return default

        return number

    except (TypeError, ValueError):
        return default


def select_option(chain, side):

    if side not in ("CALL", "PUT"):
        raise ValueError("Side must be CALL or PUT")

    if not isinstance(chain, list):
        return None

    field = (
        "call_options"
        if side == "CALL"
        else "put_options"
    )

    candidates = []

    for row in chain:

        if not isinstance(row, dict):
            continue

        option = row.get(field) or {}

        if not isinstance(option, dict):
            continue

        market = option.get("market_data") or {}

        if not isinstance(market, dict):
            continue

        instrument_key = option.get("instrument_key")

        if not instrument_key:
            continue

        ltp = safe_float(market.get("ltp"))
        bid = safe_float(market.get("bid_price"))
        ask = safe_float(market.get("ask_price"))
        volume = safe_float(market.get("volume"))
        oi = safe_float(market.get("oi"))

        spot = safe_float(
            row.get("underlying_spot_price")
        )

        strike = safe_float(
            row.get("strike_price")
        )

        # Reject invalid or missing prices.
        if min(ltp, bid, ask, spot, strike) <= 0:
            continue

        # Reject invalid bid/ask prices.
        if ask < bid:
            continue

        # Reject options without trading activity.
        if volume <= 0:
            continue

        # Calculate spread against mid-price.
        mid_price = (bid + ask) / 2

        if mid_price <= 0:
            continue

        spread = (
            (ask - bid) / mid_price
        ) * 100

        if spread > MAX_SPREAD_PCT:
            continue

        # For option buying, prefer ATM or one-step ITM; reject OTM contracts.\n        if side == "CALL" and strike > spot:\n            continue\n        if side == "PUT" and strike < spot:\n            continue\n\n        candidates.append({
            "strike": strike,
            "expiry": row.get("expiry"),
            "instrument_key": instrument_key,
            "spot": spot,
            "ltp": ltp,
            "bid": bid,
            "ask": ask,
            "volume": volume,
            "oi": oi,
            "spread": spread,
            "distance": abs(strike - spot)
        })

    if not candidates:
        return None

    # Rank by strike proximity, then liquidity and spread.
    candidates.sort(
        key=lambda x: (
            x["distance"],
            -x["volume"],
            -x["oi"],
            x["spread"]
        )
    )

    return candidates[0]
    
