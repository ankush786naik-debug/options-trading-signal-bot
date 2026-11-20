
import logging
from time import sleep
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from config import (
    UNDERLYINGS,
    validate_config,
    LOG_LEVEL
)

from upstox_client import UpstoxClient
from strategy import generate_signal
from option_selector import select_option
from risk_manager import calculate_trade
from telegram_bot import send_message, format_signal
from trade_manager import signal_exists, record_signal


IST = ZoneInfo("Asia/Kolkata")

SCAN_INTERVAL_SECONDS = 60

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(message)s"
)


def market_is_open():
    now = datetime.now(IST)

    return (
        now.weekday() < 5
        and time(9, 15) <= now.time() <= time(15, 30)
    )


def parse_candle_time(candle):
    timestamp = datetime.fromisoformat(
        str(candle[0]).replace("Z", "+00:00")
    )

    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=IST)

    return timestamp.astimezone(IST)


def get_completed_candles(candles, interval):
    if not candles:
        return []

    now = datetime.now(IST)
    completed = []
    seen = set()

    for candle in candles:
        try:
            if not isinstance(candle, list) or len(candle) < 6:
                continue

            candle_time = parse_candle_time(candle)
            candle_end = candle_time + timedelta(minutes=interval)

            if candle_end <= now:
                completed.append((candle_time, candle))

        except (ValueError, TypeError, IndexError):
            logging.warning("Skipping invalid candle timestamp")

    completed.sort(key=lambda item: item[0])

    result = []

    for candle_time, candle in completed:
        if candle_time not in seen:
            result.append(candle)
            seen.add(candle_time)

    return result


def candle_data_is_fresh(candles, interval):
    if not candles:
        return False

    try:
        latest_time = parse_candle_time(candles[-1])
        latest_end = latest_time + timedelta(minutes=interval)

        age = datetime.now(IST) - latest_end

        return (
            timedelta(0) <= age
            <= timedelta(minutes=interval * 2)
        )

    except (ValueError, TypeError, IndexError):
        return False


def scan_underlying(client, name, instrument_key):

    logging.info("Scanning %s", name)

    raw_5m = client.intraday_candles(instrument_key, 5)
    raw_15m = client.intraday_candles(instrument_key, 15)

    candles5 = get_completed_candles(raw_5m, 5)
    candles15 = get_completed_candles(raw_15m, 15)

    logging.info(
        "%s candle counts: 5m=%d, 15m=%d",
        name,
        len(candles5),
        len(candles15)
    )

    if len(candles5) < 50 or len(candles15) < 50:
        logging.warning(
            "%s: Insufficient completed candles. 5m=%d, 15m=%d",
            name,
            len(candles5),
            len(candles15)
        )
        return

    if not candle_data_is_fresh(candles5, 5):
        logging.warning("%s: 5-minute data is stale", name)
        return

    if not candle_data_is_fresh(candles15, 15):
        logging.warning("%s: 15-minute data is stale", name)
        return

    # Generate signal using both timeframes.
    signal = generate_signal(
        name,
        candles5,
        candles15
    )

    if not signal:
        logging.info("%s: NO TRADE", name)
        return

    # Get nearest expiry.
    expiry = client.get_nearest_expiry(instrument_key)

    # Fetch option chain.
    chain = client.option_chain(
        instrument_key,
        expiry
    )

    # Select suitable option.
    option = select_option(
        chain,
        signal["side"]
    )

    if not option:
        logging.info("%s: No liquid option found", name)
        return

    # Calculate entry, stop loss and targets.
    trade = calculate_trade(option)

    if not trade:
        logging.info("%s: Invalid option premium", name)
        return

    final_signal = {
        **signal,
        **trade,
        "expiry": expiry
    }

    # Prevent duplicate alerts.
    if signal_exists(
        trade["instrument_key"],
        signal["timestamp"]
    ):
        logging.info("%s: Duplicate signal ignored", name)
        return

    message = format_signal(final_signal)

    logging.info(message)

    # Send Telegram alert.
    delivered = send_message(message)

    # Record only after successful Telegram delivery.
    if delivered:
        record_signal(final_signal)

        logging.info(
            "%s: Signal sent and recorded",
            name
        )
    else:
        logging.warning(
            "%s: Telegram delivery failed; signal not recorded",
            name
        )


def main():

    validate_config()

    client = UpstoxClient()

    logging.info("OPTIONS TRADING SIGNAL BOT STARTED")

    try:

        while True:

            now = datetime.now(IST)

            # Stop on weekends.
            if now.weekday() >= 5:
                logging.info("Weekend. Scanner stopped.")
                break

            # Stop after market closing.
            if now.time() > time(15, 30):
                logging.info("Market closed. Scanner stopped.")
                break

            # Wait until market opens.
            if now.time() < time(9, 15):
                logging.info("Waiting for market to open.")
                sleep(30)
                continue

            cycle_started = datetime.now(IST)

            logging.info("Starting market scan cycle")

            for name, instrument_key in UNDERLYINGS.items():

                try:
                    scan_underlying(
                        client,
                        name,
                        instrument_key
                    )

                except Exception:
                    logging.exception(
                        "Failed scanning %s",
                        name
                    )

            elapsed = (
                datetime.now(IST) - cycle_started
            ).total_seconds()

            wait_time = max(
                1,
                SCAN_INTERVAL_SECONDS - elapsed
            )

            if datetime.now(IST).time() <= time(15, 30):
                logging.info(
                    "Scan completed. Next scan in %.1f seconds",
                    wait_time
                )
                sleep(wait_time)

    except KeyboardInterrupt:
        logging.info("Scanner stopped manually")

    except Exception:
        logging.exception("Fatal scanner error")

    finally:
        logging.info("OPTIONS TRADING SIGNAL BOT STOPPED")


if __name__ == "__main__":
    main()
    
