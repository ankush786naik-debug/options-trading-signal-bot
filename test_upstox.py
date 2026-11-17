import logging

from config import UNDERLYINGS
from upstox_client import UpstoxClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)


def main():

    client = UpstoxClient()

    print("\n========== UPSTOX API TEST ==========\n")

    for name, instrument_key in UNDERLYINGS.items():

        print(f"\nTesting: {name}")
        print(f"Instrument: {instrument_key}")

        try:

            expiries = client.get_expiries(
                instrument_key
            )

            print("Expiry API: SUCCESS")

            print("Available expiries:")

            for expiry in expiries:
                print(f"  - {expiry}")

            nearest = client.get_nearest_expiry(
                instrument_key
            )

            print(f"Nearest expiry: {nearest}")

            chain = client.option_chain(
                instrument_key,
                nearest
            )

            print(f"Option chain records: {len(chain)}")

            if chain:
                print("Option chain: SUCCESS")
            else:
                print("WARNING: Empty option chain")

        except Exception as error:

            print(f"FAILED: {error}")

    print("\n========== TEST COMPLETED ==========\n")


if __name__ == "__main__":
    main()
  
