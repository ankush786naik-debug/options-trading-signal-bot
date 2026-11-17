
from config import (
    STOP_LOSS_PCT,
    TARGET_1_PCT,
    TARGET_2_PCT
)


def safe_float(value):

    try:
        number = float(value)

        if number != number:
            return None

        return number

    except (TypeError, ValueError):
        return None


def calculate_trade(option):

    if not isinstance(option, dict):
        return None

    entry = safe_float(option.get("ask"))

    if entry is None or entry <= 0:
        return None

    sl_pct = safe_float(STOP_LOSS_PCT)
    target1_pct = safe_float(TARGET_1_PCT)
    target2_pct = safe_float(TARGET_2_PCT)

    if any(
        value is None or value <= 0 or value >= 100
        for value in (sl_pct, target1_pct, target2_pct)
    ):
        raise ValueError("Invalid stop-loss or target percentages")

    if target2_pct <= target1_pct:
        raise ValueError(
            "Target 2 percentage must be greater than Target 1"
        )

    stop_loss = entry * (1 - sl_pct / 100)
    target_1 = entry * (1 + target1_pct / 100)
    target_2 = entry * (1 + target2_pct / 100)

    return {
        **option,
        "entry": round(entry, 2),
        "stop_loss": round(stop_loss, 2),
        "target_1": round(target_1, 2),
        "target_2": round(target_2, 2)
    }


def entry_activated(option, live_ltp):

    if not isinstance(option, dict):
        return False

    entry = safe_float(option.get("entry"))
    current_price = safe_float(live_ltp)

    if entry is None or current_price is None:
        return False

    if entry <= 0 or current_price <= 0:
        return False

    return current_price >= entry
    
