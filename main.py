import logging

from datetime import datetime, time
from zoneinfo import ZoneInfo

from config import UNDERLYINGS

from upstox_client import UpstoxClient
from strategy import generate_signal
from option_selector import select_option
from risk_manager import calculate_trade
from telegram_bot import send_message, format_signal
from trade_manager import signal_exists, record_signal


IST = ZoneInfo("Asia/Kolkata")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)


def market_is_open():

    now = datetime.now(IST)

    return (
        now.weekday() < 5
        and time(9, 15) <= now.time() <= time(15, 30)
    )


def main():

    if not market_is_open():
        logging.info("Market is closed")
        return

    client = UpstoxClient()

    for name, instrument_key in UNDERLYINGS.items():

        try:

            logging.info("Scanning %s", name)

            candles5 = client.intraday_candles(
                instrument_key, 5
            )

            candles15 = client.intraday_candles(
                instrument_key, 15
            )

            signal = generate_signal(
                name,
                candles5,
                candles15
            )

            if not signal:
                logging.info("%s: NO TRADE", name)
                continue

            expiry = client.get_nearest_expiry(
                instrument_key
            )

            chain = client.option_chain(
                instrument_key,
                expiry
            )

            option = select_option(
                chain,
                signal["side"]
            )

            if not option:
                logging.info("%s: No liquid option found", name)
                continue

            trade = calculate_trade(option)

            if not trade:
                continue

            final_signal = {
                **signal,
                **trade,
                "expiry": expiry
            }

            if signal_exists(
                trade["instrument_key"],
                signal["timestamp"]
            ):
                logging.info("Duplicate signal ignored")
                continue

            message = format_signal(final_signal)

            logging.info(message)

            send_message(message)

            record_signal(final_signal)

        except Exception:

            logging.exception(
                "Failed scanning %s",
                name
            )


if __name__ == "__main__":
    main()
