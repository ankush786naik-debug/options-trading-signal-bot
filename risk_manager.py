from config import (
    STOP_LOSS_PCT,
    TARGET_1_PCT,
    TARGET_2_PCT
)


def calculate_trade(option):

    entry = float(option["ask"])

    if entry <= 0:
        return None

    stop_loss = entry * (
        1 - STOP_LOSS_PCT / 100
    )

    target_1 = entry * (
        1 + TARGET_1_PCT / 100
    )

    target_2 = entry * (
        1 + TARGET_2_PCT / 100
    )

    return {
        **option,
        "entry": round(entry, 2),
        "stop_loss": round(stop_loss, 2),
        "target_1": round(target_1, 2),
        "target_2": round(target_2, 2)
    }


def entry_activated(option, live_ltp):

    return float(live_ltp) >= float(option["entry"])
