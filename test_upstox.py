import logging

from config import UNDERLYINGS
from upstox_client import UpstoxClient

logging.basicConfig(level=logging.INFO)


def main():

    client = UpstoxClient()

    for name, key in UNDERLYINGS.items():

        print(f"\nTesting {name}")

        try:

            candles5 = client.intraday_candles(key, 5)
            candles15 = client.intraday_candles(key, 15)

            print("5-minute candles:", len(candles5))
            print("15-minute candles:", len(candles15))

            expiry = client.get_nearest_expiry(key)

            print("Nearest expiry:", expiry)

            chain = client.option_chain(key, expiry)

            print("Option chain records:", len(chain))

            print("SUCCESS")

        except Exception as error:

            print("FAILED:", error)


if __name__ == "__main__":
    main()
