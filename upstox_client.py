import requests
from urllib.parse import quote
from datetime import datetime
from zoneinfo import ZoneInfo

from config import UPSTOX_BASE_URL, UPSTOX_TOKEN


IST = ZoneInfo("Asia/Kolkata")


class UpstoxClient:

    def __init__(self):

        if not UPSTOX_TOKEN:
            raise RuntimeError(
                "Missing UPSTOX_ANALYTICS_TOKEN"
            )

        self.session = requests.Session()

        self.session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {UPSTOX_TOKEN}"
        })

    def get(self, path, params=None):

        response = self.session.get(
            f"{UPSTOX_BASE_URL}{path}",
            params=params,
            timeout=25
        )

        if response.status_code == 401:
            raise RuntimeError("Invalid Upstox token")

        if response.status_code == 403:
            raise RuntimeError(
                "Upstox access forbidden. Check token permissions."
            )

        if response.status_code == 429:
            raise RuntimeError("Upstox API rate limit reached")

        response.raise_for_status()

        result = response.json()

        if result.get("status") != "success":
            raise RuntimeError(f"Upstox error: {result}")

        return result.get("data", {})

    def intraday_candles(self, instrument_key, interval):

        if interval not in (5, 15):
            raise ValueError("Only 5 and 15 minute candles supported")

        key = quote(instrument_key, safe="")

        data = self.get(
            f"/v3/historical-candle/intraday/"
            f"{key}/minutes/{interval}"
        )

        return data.get("candles", [])

    def get_expiries(self, instrument_key):

        data = self.get(
            "/v2/option/contract",
            {"instrument_key": instrument_key}
        )

        today = datetime.now(IST).date()

        expiries = set()

        if not isinstance(data, list):
            raise RuntimeError("Unexpected option contract response")

        for contract in data:

            expiry = contract.get("expiry")

            if not expiry:
                continue

            try:
                expiry_date = datetime.strptime(
                    expiry, "%Y-%m-%d"
                ).date()
            except ValueError:
                continue

            if expiry_date >= today:
                expiries.add(expiry)

        if not expiries:
            raise RuntimeError(
                f"No valid expiry found for {instrument_key}"
            )

        return sorted(expiries)

    def get_nearest_expiry(self, instrument_key):

        return self.get_expiries(instrument_key)[0]

    def option_chain(self, instrument_key, expiry):

        data = self.get(
            "/v2/option/chain",
            {
                "instrument_key": instrument_key,
                "expiry_date": expiry
            }
        )

        if not isinstance(data, list):
            raise RuntimeError("Unexpected option chain response")

        return data
