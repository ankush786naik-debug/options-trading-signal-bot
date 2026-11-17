import requests
from config import UPSTOX_BASE_URL, UPSTOX_TOKEN


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
            UPSTOX_BASE_URL + path,
            params=params,
            timeout=20
        )

        if response.status_code == 401:
            raise RuntimeError("Invalid or expired Upstox token")

        if response.status_code == 429:
            raise RuntimeError("Upstox API rate limit reached")

        response.raise_for_status()

        result = response.json()

        if result.get("status") != "success":
            raise RuntimeError(str(result))

        return result.get("data", {})

    def intraday_candles(self, instrument_key, interval):

        data = self.get(
            f"/v3/historical-candle/intraday/"
            f"{instrument_key}/minutes/{interval}"
        )

        return data.get("candles", [])

    def option_chain(self, instrument_key, expiry):

        data = self.get(
            "/v2/option/chain",
            {
                "instrument_key": instrument_key,
                "expiry_date": expiry
            }
        )

        return data if isinstance(data, list) else data.get("data", [])
      
