
import os
from dotenv import load_dotenv

load_dotenv()

# Upstox API
UPSTOX_BASE_URL = "https://api.upstox.com"
UPSTOX_TOKEN = os.getenv("UPSTOX_ANALYTICS_TOKEN", "").strip()

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

ALERTS_ENABLED = (
    os.getenv("ALERTS_ENABLED", "false").strip().lower() == "true"
)

# Timezone
IST = "Asia/Kolkata"

# Supported index instruments
UNDERLYINGS = {
    "NIFTY": "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "SENSEX": "BSE_INDEX|SENSEX",
}

# Signal settings
MIN_SIGNAL_SCORE = 75
MAX_SPREAD_PCT = 2.0

# Option premium risk settings
STOP_LOSS_PCT = 20
TARGET_1_PCT = 20
TARGET_2_PCT = 35

# Candle settings
CANDLE_INTERVALS = [5, 15]
MIN_CANDLES = 50

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


def validate_config():
    """Validate required configuration before scanning."""

    if not UPSTOX_TOKEN:
        raise RuntimeError(
            "Missing UPSTOX_ANALYTICS_TOKEN GitHub Secret"
        )

    if ALERTS_ENABLED:
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            raise RuntimeError(
                "Telegram is enabled but bot token or chat ID is missing"
            )
            
