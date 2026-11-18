import requests
from urllib.parse import quote
from datetime import datetime, timedelta
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
                "Upstox returned invalid JSON."
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

        today = datetime.now(IST).date()

        # Fetch the previous 7 calendar days.
        from_date = (
            today - timedelta(days=7)
        ).isoformat()

        to_date = (
            today - timedelta(days=1)
        ).isoformat()

        historical_path = (
            f"/v3/historical-candle/"
            f"{key}/minutes/{interval}/"
            f"{to_date}/{from_date}"
        )

        historical_data = self.get(historical_path)

        if not isinstance(historical_data, dict):
            raise RuntimeError(
                "Invalid historical candle response."
            )

        historical_candles = (
            historical_data.get("candles", [])
        )

        if not isinstance(historical_candles, list):
            raise RuntimeError(
                "Invalid historical candle list."
            )

        # Fetch today's intraday candles.
        intraday_path = (
            f"/v3/historical-candle/intraday/"
            f"{key}/minutes/{interval}"
        )

        intraday_data = self.get(intraday_path)

        if not isinstance(intraday_data, dict):
            raise RuntimeError(
                "Invalid intraday candle response."
            )

        today_candles = intraday_data.get(
            "candles", []
        )

        if not isinstance(today_candles, list):
            raise RuntimeError(
                "Invalid intraday candle list."
            )

        # Combine historical and today's candles.
        combined = (
            historical_candles + today_candles
        )

        # Validate records and remove duplicate timestamps.
        unique_candles = {}

        for candle in combined:

            if (
                not isinstance(candle, list)
                or len(candle) < 6
            ):
                continue

            timestamp = candle[0]

            if not isinstance(timestamp, str):
                continue

            try:
                parsed_time = datetime.fromisoformat(
                    timestamp
                )
            except ValueError:
                continue

            unique_candles[parsed_time] = candle

        # Sort oldest to newest.
        sorted_candles = [
            unique_candles[timestamp]
            for timestamp in sorted(unique_candles)
        ]

        if not sorted_candles:
            raise RuntimeError(
                f"No candles received for {instrument_key}"
            )

        print(
            f"{instrument_key} {interval}m: "
            f"{len(historical_candles)} historical + "
            f"{len(today_candles)} intraday = "
            f"{len(sorted_candles)} combined candles"
        )

        return sorted_candles

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
