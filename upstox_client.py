
import requests
from datetime import date

from config import UPSTOX_BASE_URL, UPSTOX_TOKEN


class UpstoxClient:

    def __init__(self):

        if not UPSTOX_TOKEN:
            raise RuntimeError("Missing Upstox token")

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

    def get_expiries(self, instrument_key):

        data = self.get(
            "/v2/option/contract",
            {
                "instrument_key": instrument_key
            }
        )

        contracts = data if isinstance(data, list) else []

        expiries = sorted({
            item.get("expiry")
            for item in contracts
            if item.get("expiry")
            and item.get("expiry") >= date.today().isoformat()
        })

        if not expiries:
            raise RuntimeError(
                f"No valid expiries found for {instrument_key}"
            )

        return expiries

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

        return data if isinstance(data, list) else data.get("data", [])
        
