import logging
import requests

from datetime import datetime, time
from zoneinfo import ZoneInfo

from config import (
    UNDERLYINGS,
    OPTION_EXPIRY,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID
)

from upstox_client import UpstoxClient
from strategy import generate_signal


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

IST = ZoneInfo("Asia/Kolkata")


def market_is_open():

    now = datetime.now(IST)

    return (
        now.weekday() < 5
        and time(9, 15) <= now.time() <= time(15, 30)
    )


def send_telegram(message):

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logging.warning("Telegram configuration missing")
        return

    response = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message
        },
        timeout=15
    )

    response.raise_for_status()


def format_signal(signal):

    return f"""
📊 OPTIONS TRADING SIGNAL

Index: {signal['symbol']}
Direction: {signal['side']}

Time: {signal['timestamp']}

Strike: {signal['strike']}
Expiry: {signal['expiry']}

Option LTP: ₹{signal['ltp']}

Entry: ₹{signal['entry']}
Stop Loss: ₹{signal['stop_loss']}

Target 1: ₹{signal['target_1']}
Target 2: ₹{signal['target_2']}

Spot: {signal['spot']}
RSI: {signal['rsi']:.2f}

Signal Score: {signal['score']}/5

Spread: {signal['spread']:.2f}%

MODE: PAPER SIGNAL ONLY

No order has been placed.
"""


def main():

    if not market_is_open():

        logging.info("Market is closed")
        return

    if not OPTION_EXPIRY:
        raise RuntimeError(
            "OPTION_EXPIRY must be set to a valid expiry date"
        )

    client = UpstoxClient()

    for name, key in UNDERLYINGS.items():

        try:

            logging.info("Scanning %s", name)

            candles5 = client.intraday_candles(key, 5)

            candles15 = client.intraday_candles(key, 15)

            expiry = client.get_nearest_expiry(key)
            logging.info(
                "%s selected expiry: %s",
                name,
                expiry
            )

chain = client.option_chain(
    key,
    expiry
)

            signal = generate_signal(
                name,
                candles5,
                candles15,
                chain
            )

            if signal:

                message = format_signal(signal)

                logging.info(message)

                send_telegram(message)

            else:

                logging.info(
                    "%s: No qualifying signal",
                    name
                )

        except Exception:

            logging.exception(
                "Error scanning %s",
                name
            )


if __name__ == "__main__":
    main()
  
