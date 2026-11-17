
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
            "Authorization": f"Bearer {UPSTOX_TOKEN}"
        })

    def get(self, path, params=None):

        url = f"{UPSTOX_BASE_URL}{path}"

        try:
            response = self.session.get(
                url,
                params=params,
                timeout=(10, 30)
            )

        except requests.exceptions.Timeout as error:
            raise RuntimeError(
                f"Upstox API request timed out: {path}"
            ) from error

        except requests.exceptions.RequestException as error:
            raise RuntimeError(
                f"Upstox connection failed: {error}"
            ) from error

        if response.status_code == 401:
            raise RuntimeError(
                "Upstox authentication failed. Check API token."
            )

        if response.status_code == 403:
            raise RuntimeError(
                "Upstox access forbidden. Check token permissions."
            )

        if response.status_code == 429:
            raise RuntimeError(
                "Upstox API rate limit reached."
            )

        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as error:
            raise RuntimeError(
                f"Upstox HTTP error {response.status_code}: "
                f"{response.text[:500]}"
            ) from error

        try:
            result = response.json()
        except ValueError as error:
            raise RuntimeError(
                "Upstox returned an invalid JSON response."
            ) from error

        if not isinstance(result, dict):
            raise RuntimeError(
                "Unexpected Upstox response format."
            )

        if result.get("status") != "success":
            raise RuntimeError(
                f"Upstox API error: {result}"
            )

        return result.get("data")

    def intraday_candles(self, instrument_key, interval):

        if interval not in (5, 15):
            raise ValueError(
                "Only 5 and 15 minute candles are supported."
            )

        key = quote(instrument_key, safe="")

        data = self.get(
            f"/v3/historical-candle/intraday/"
            f"{key}/minutes/{interval}"
        )

        if not isinstance(data, dict):
            raise RuntimeError(
                "Unexpected candle response from Upstox."
            )

        candles = data.get("candles", [])

        if not isinstance(candles, list):
            raise RuntimeError(
                "Invalid candle data received from Upstox."
            )

        return candles

    def get_expiries(self, instrument_key):

        data = self.get(
            "/v2/option/contract",
            {"instrument_key": instrument_key}
        )

        if not isinstance(data, list):
            raise RuntimeError(
                "Unexpected option contract response."
            )

        today = datetime.now(IST).date()
        expiries = set()

        for contract in data:

            if not isinstance(contract, dict):
                continue

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

        expiries = self.get_expiries(instrument_key)

        return expiries[0]

    def option_chain(self, instrument_key, expiry):

        data = self.get(
            "/v2/option/chain",
            {
                "instrument_key": instrument_key,
                "expiry_date": expiry
            }
        )

        if not isinstance(data, list):
            raise RuntimeError(
                "Unexpected option chain response."
            )

        return data
        
