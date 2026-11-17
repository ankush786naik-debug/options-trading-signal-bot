
import requests
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
            "Authorization": f"Bearer {UPSTOX_TOKEN}"
        })

    def get(self, path, params=None):

        response = self.session.get(
            f"{UPSTOX_BASE_URL}{path}",
            params=params,
            timeout=25
        )

        if response.status_code == 401:
            raise RuntimeError(
                "Invalid or expired Upstox token (401)"
            )

        if response.status_code == 403:
            raise RuntimeError(
                "Upstox API access forbidden (403). "
                "Check token permissions."
            )

        if response.status_code == 429:
            raise RuntimeError(
                "Upstox rate limit reached (429)"
            )

        response.raise_for_status()

        result = response.json()

        if result.get("status") != "success":
            raise RuntimeError(
                f"Upstox API error: {result}"
            )

        return result.get("data", {})

    # Fetch intraday candles
    def intraday_candles(
        self,
        instrument_key,
        interval
    ):

        data = self.get(
            f"/v3/historical-candle/intraday/"
            f"{instrument_key}/minutes/{interval}"
        )

        return data.get("candles", [])

    # Fetch all available option contracts
    def get_expiries(self, instrument_key):

        data = self.get(
            "/v2/option/contract",
            {
                "instrument_key": instrument_key
            }
        )

        if not isinstance(data, list):
            raise RuntimeError(
                f"Unexpected contract response for "
                f"{instrument_key}: {data}"
            )

        today = datetime.now(IST).date()

        expiries = set()

        for contract in data:

            expiry = contract.get("expiry")

            if not expiry:
                continue

            try:

                expiry_date = datetime.strptime(
                    expiry,
                    "%Y-%m-%d"
                ).date()

            except ValueError:

                continue

            if expiry_date >= today:

                expiries.add(expiry)

        if not expiries:
            raise RuntimeError(
                f"No valid option expiry found for "
                f"{instrument_key}"
            )

        return sorted(expiries)

    # Select nearest valid expiry independently
    def get_nearest_expiry(self, instrument_key):

        expiries = self.get_expiries(
            instrument_key
        )

        nearest_expiry = expiries[0]

        return nearest_expiry

    # Fetch option chain for selected expiry
    def option_chain(
        self,
        instrument_key,
        expiry
    ):

        data = self.get(
            "/v2/option/chain",
            {
                "instrument_key": instrument_key,
                "expiry_date": expiry
            }
        )

        if isinstance(data, list):
            return data

        if isinstance(data, dict):
            return data.get("data", [])

        raise RuntimeError(
            "Unexpected option-chain response"
        )
        
