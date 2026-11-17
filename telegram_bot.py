import requests

from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    ALERTS_ENABLED
)


def send_message(message):

    if not ALERTS_ENABLED:
        print("Telegram alerts disabled")
        return False

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("Telegram credentials missing")

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    response = requests.post(
        url,
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message
        },
        timeout=20
    )

    response.raise_for_status()

    return True


def format_signal(signal):

    return f"""
🚨 OPTIONS BUYING SIGNAL

Index: {signal['symbol']}
Direction: BUY {signal['side']}

Strike: {signal['strike']}
Expiry: {signal['expiry']}

Spot: ₹{signal['spot']}

Entry above: ₹{signal['entry']}
Stop Loss: ₹{signal['stop_loss']}

Target 1: ₹{signal['target_1']}
Target 2: ₹{signal['target_2']}

Confidence score: {signal['score']}/100

RSI: {signal['rsi']:.2f}
ADX: {signal['adx']:.2f}

VWAP: {signal['vwap']:.2f}

Spread: {signal['spread']:.2f}%

Reasons:
{chr(10).join(signal['reasons'])}

MODE: PAPER TRADING ONLY

Wait for entry confirmation.
No live order placed.
"""
