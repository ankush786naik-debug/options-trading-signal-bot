
import json
import os
import logging

from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

STATE_FILE = "trade_state.json"
MAX_RECORDS = 500


def empty_state():
    return {"signals": []}


def load_state():

    if not os.path.exists(STATE_FILE):
        return empty_state()

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            state = json.load(file)

        if not isinstance(state, dict):
            raise ValueError("State must be a JSON object")

        if not isinstance(state.get("signals"), list):
            raise ValueError("Signals must be a list")

        return state

    except (json.JSONDecodeError, OSError, ValueError) as error:
        logging.error("Unable to read trade state: %s", error)
        raise RuntimeError(
            "Trade state file is invalid. Refusing to reset signal history."
        ) from error


def save_state(state):

    if not isinstance(state, dict):
        raise ValueError("Invalid state object")

    if not isinstance(state.get("signals"), list):
        raise ValueError("Invalid signals list")

    temporary = STATE_FILE + ".tmp"

    try:
        with open(temporary, "w", encoding="utf-8") as file:
            json.dump(state, file, indent=2)

        os.replace(temporary, STATE_FILE)

    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def signal_exists(instrument_key, timestamp):

    if not instrument_key or not timestamp:
        raise ValueError("Instrument key and timestamp are required")

    state = load_state()

    return any(
        item.get("instrument_key") == instrument_key
        and item.get("timestamp") == timestamp
        for item in state["signals"]
        if isinstance(item, dict)
    )



def signal_in_cooldown(symbol, side, timestamp, cooldown_minutes=15):
    """Prevent repeat same-direction alerts for the same index during cooldown."""
    if not symbol or side not in ("CALL", "PUT") or not timestamp:
        raise ValueError("Symbol, side and timestamp are required")
    try:
        current = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        if current.tzinfo is None:
            current = current.replace(tzinfo=IST)
        current = current.astimezone(IST)
    except ValueError:
        return False

    state = load_state()
    for item in state["signals"]:
        if not isinstance(item, dict):
            continue
        if item.get("symbol") != symbol or item.get("side") != side:
            continue
        recorded = item.get("timestamp")
        if not recorded:
            continue
        try:
            previous = datetime.fromisoformat(str(recorded).replace("Z", "+00:00"))
            if previous.tzinfo is None:
                previous = previous.replace(tzinfo=IST)
            previous = previous.astimezone(IST)
        except ValueError:
            continue
        elapsed = (current - previous).total_seconds() / 60
        if 0 <= elapsed < cooldown_minutes:
            return True
    return False

def record_signal(signal):

    required = [
        "symbol",
        "side",
        "instrument_key",
        "strike",
        "expiry",
        "entry",
        "stop_loss",
        "target_1",
        "target_2",
        "timestamp"
    ]

    missing = [
        field for field in required
        if field not in signal
    ]

    if missing:
        raise ValueError(
            f"Missing signal fields: {', '.join(missing)}"
        )

    if signal_exists(
        signal["instrument_key"],
        signal["timestamp"]
    ):
        logging.info("Duplicate signal not recorded")
        return False

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

    state["signals"] = state["signals"][-MAX_RECORDS:]

    save_state(state)

    return True
    
