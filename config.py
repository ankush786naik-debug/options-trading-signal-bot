import os
from dotenv import load_dotenv

load_dotenv()

UPSTOX_BASE_URL = "https://api.upstox.com"

UPSTOX_TOKEN = os.getenv("UPSTOX_ANALYTICS_TOKEN", "")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

ALERTS_ENABLED = os.getenv("ALERTS_ENABLED", "false").lower() == "true"

IST = "Asia/Kolkata"

UNDERLYINGS = {
    "NIFTY": "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "SENSEX": "BSE_INDEX|SENSEX",
}

MIN_SIGNAL_SCORE = 75
MAX_SPREAD_PCT = 2.0

# These are signal-management defaults, not a capital requirement.
STOP_LOSS_PCT = 20
TARGET_1_PCT = 20
TARGET_2_PCT = 35

CANDLE_INTERVALS = [5, 15]
MIN_CANDLES = 50

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
