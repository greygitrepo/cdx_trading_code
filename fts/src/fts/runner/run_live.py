import os
import sys


def main() -> None:
    if not os.getenv("BYBIT_API_KEY"):
        print("BYBIT credentials missing. Use simulator.")
        sys.exit(2)
    print("Live mode not implemented.")


if __name__ == "__main__":
    main()
