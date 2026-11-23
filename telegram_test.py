from datetime import datetime
from zoneinfo import ZoneInfo

from telegram_bot import send_message

IST = ZoneInfo("Asia/Kolkata")

message = (
    "✅ TELEGRAM CONNECTION TEST\n\n"
    "Your Options Signal Bot can send Telegram messages.\n"
    f"Test time: {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S IST')}\n\n"
    "This is a connectivity test only. No trade was placed."
)

if not send_message(message):
    raise SystemExit("Telegram test message was not sent. Check ALERTS_ENABLED.")

print("Telegram connectivity test delivered successfully.")
