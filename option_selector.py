from config import MAX_SPREAD_PCT


def select_option(chain, side):

    field = (
        "call_options"
        if side == "CALL"
        else "put_options"
    )

    candidates = []

    for row in chain:

        option = row.get(field) or {}
        market = option.get("market_data") or {}

        ltp = float(market.get("ltp") or 0)
        bid = float(market.get("bid_price") or 0)
        ask = float(market.get("ask_price") or 0)
        volume = float(market.get("volume") or 0)

        spot = float(
            row.get("underlying_spot_price") or 0
        )

        strike = float(row.get("strike_price") or 0)

        if min(ltp, bid, ask, spot, strike) <= 0:
            continue

        if ask < bid:
            continue

        spread = ((ask - bid) / ltp) * 100

        if spread > MAX_SPREAD_PCT:
            continue

        candidates.append({
            "strike": strike,
            "expiry": row.get("expiry"),
            "instrument_key": option.get("instrument_key"),
            "spot": spot,
            "ltp": ltp,
            "bid": bid,
            "ask": ask,
            "volume": volume,
            "oi": float(market.get("oi") or 0),
            "spread": spread,
            "distance": abs(strike - spot)
        })

    if not candidates:
        return None

    # Prefer the closest strike; use volume and spread as tie-breakers.
    candidates.sort(
        key=lambda x: (
            x["distance"],
            -x["volume"],
            x["spread"]
        )
    )

    return candidates[0]
