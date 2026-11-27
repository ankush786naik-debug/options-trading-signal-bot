import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, ALERTS_ENABLED

TELEGRAM_API = "https://api.telegram.org"
MAX_MESSAGE_LENGTH = 4000


def send_message(message):
    if not ALERTS_ENABLED:
        print("Telegram alerts disabled")
        return False
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("Telegram credentials missing")
    if not isinstance(message, str) or not message.strip():
        raise ValueError("Telegram message cannot be empty")
    if len(message) > MAX_MESSAGE_LENGTH:
        message = message[:MAX_MESSAGE_LENGTH - 20] + "\n\n[Message truncated]"
    url = f"{TELEGRAM_API}/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        response = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=(10, 20))
        response.raise_for_status()
        result = response.json()
    except requests.exceptions.Timeout as error:
        raise RuntimeError("Telegram request timed out") from error
    except requests.exceptions.RequestException as error:
        raise RuntimeError(f"Telegram delivery failed: {error}") from error
    except ValueError as error:
        raise RuntimeError("Telegram returned invalid JSON") from error
    if not result.get("ok"):
        raise RuntimeError(f"Telegram API error: {result}")
    return True


def format_signal(signal):
    required_fields = [
        "symbol", "side", "strike", "expiry", "spot", "entry", "stop_loss",
        "target_1", "target_2", "score", "spread", "reasons", "ltp",
        "underlying_stop", "underlying_target", "higher_timeframe_trend",
        "ema20", "ema50", "atr", "dtp_state",
    ]
    missing = [field for field in required_fields if field not in signal]
    if missing:
        raise ValueError(f"Missing signal fields: {', '.join(missing)}")
    if signal["side"] not in ("CALL", "PUT"):
        raise ValueError("Invalid signal direction")
    if not isinstance(signal["reasons"], list):
        raise ValueError("Signal reasons must be a list")
    return f"""
🚨 OPTIONS BUYING SIGNAL — PAPER

Index: {signal['symbol']}
Direction: BUY {signal['side']}

Strike: {signal['strike']}
Expiry: {signal['expiry']}

Underlying spot: ₹{float(signal['spot']):.2f}
Underlying invalidation: ₹{float(signal['underlying_stop']):.2f}
Underlying 3x ATR target: ₹{float(signal['underlying_target']):.2f}
15m trend: {signal['higher_timeframe_trend']}
EMA20: {float(signal['ema20']):.2f}
EMA50: {float(signal['ema50']):.2f}
DTP state: {'Bullish' if int(signal['dtp_state']) == 1 else 'Bearish'}
ATR14: {float(signal['atr']):.2f}

Option premium (ask entry): ₹{float(signal['entry']):.2f}
Option LTP: ₹{float(signal['ltp']):.2f}
Stop Loss: ₹{float(signal['stop_loss']):.2f}
Target 1: ₹{float(signal['target_1']):.2f}
Target 2: ₹{float(signal['target_2']):.2f}

Strategy score: {signal['score']}/100
Spread: {float(signal['spread']):.2f}%

Signal reasons:
{chr(10).join(str(reason) for reason in signal['reasons'])}

OI: {int(float(signal.get('oi', 0)))} | Volume: {int(float(signal.get('volume', 0)))}

MODE: PAPER SIGNAL ONLY
No live order placed.
"""
