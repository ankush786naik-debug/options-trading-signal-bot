
import logging

from config import UNDERLYINGS, validate_config
from upstox_client import UpstoxClient


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)


def test_candles(client, name, key, interval):

    print(f"\nTesting {name} {interval}-minute candles")

    candles = client.intraday_candles(key, interval)

    if not candles:
        raise RuntimeError("No candles returned")

    valid_candles = [
        candle for candle in candles
        if isinstance(candle, list) and len(candle) >= 6
    ]

    if not valid_candles:
        raise RuntimeError("No valid candle records found")

    print("Total candles:", len(candles))
    print("Valid candles:", len(valid_candles))
    print("Latest candle timestamp:", valid_candles[0][0])

    return True


def test_options(client, name, key):

    print(f"\nTesting {name} option contracts")

    expiry = client.get_nearest_expiry(key)

    print("Nearest expiry:", expiry)

    chain = client.option_chain(key, expiry)

    if not chain:
        raise RuntimeError("Empty option chain")

    print("Option chain records:", len(chain))

    calls = 0
    puts = 0

    for row in chain:

        if not isinstance(row, dict):
            continue

        if row.get("call_options"):
            calls += 1

        if row.get("put_options"):
            puts += 1

    print("Call contracts:", calls)
    print("Put contracts:", puts)

    if calls == 0 or puts == 0:
        raise RuntimeError(
            "Call or put contracts missing from option chain"
        )

    return True


def main():

    try:
        validate_config()
    except Exception as error:
        print("CONFIGURATION FAILED:", error)
        return

    client = UpstoxClient()

    results = {}

    for name, key in UNDERLYINGS.items():

        print("\n" + "=" * 45)
        print("TESTING:", name)
        print("=" * 45)

        results[name] = {}

        for interval in (5, 15):

            try:
                test_candles(
                    client,
                    name,
                    key,
                    interval
                )

                results[name][f"{interval}m candles"] = "PASS"

            except Exception as error:
                print("CANDLE TEST FAILED:", error)
                results[name][f"{interval}m candles"] = "FAIL"

        try:
            test_options(client, name, key)

            results[name]["option chain"] = "PASS"

        except Exception as error:
            print("OPTION TEST FAILED:", error)
            results[name]["option chain"] = "FAIL"

    print("\n\nFINAL TEST SUMMARY")
    print("=" * 45)

    for name, tests in results.items():

        print(f"\n{name}")

        for test_name, status in tests.items():
            print(f"{test_name}: {status}")


if __name__ == "__main__":
    main()
    
