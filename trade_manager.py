import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

STATE_FILE = "trade_state.json"


def load_state():

    if not os.path.exists(STATE_FILE):
        return {"signals": []}

    try:
        with open(STATE_FILE, "r") as file:
            return json.load(file)
    except (json.JSONDecodeError, OSError):
        return {"signals": []}


def save_state(state):

    temporary = STATE_FILE + ".tmp"

    with open(temporary, "w") as file:
        json.dump(state, file, indent=2)

    os.replace(temporary, STATE_FILE)


def signal_exists(instrument_key, timestamp):

    state = load_state()

    return any(
        item["instrument_key"] == instrument_key
        and item["timestamp"] == timestamp
        for item in state["signals"]
    )


def record_signal(signal):

    state = load_state()

    state["signals"].append({
        "symbol": signal["symbol"],
        "side": signal["side"],
        "instrument_key": signal["instrument_key"],
        "strike": signal["strike"],
        "expiry": signal["expiry"],
        "entry": signal["entry"],
        "stop_loss": signal["stop_loss"],
        "target_1": signal["target_1"],
        "target_2": signal["target_2"],
        "timestamp": signal["timestamp"],
        "recorded_at": datetime.now(IST).isoformat()
    })

    # Retain the most recent 500 records.
    state["signals"] = state["signals"][-500:]

    save_state(state)
