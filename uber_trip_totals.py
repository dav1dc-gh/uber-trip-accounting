#!/usr/bin/env python3
"""
 ██╗   ██╗██████╗ ███████╗██████╗
 ██║   ██║██╔══██╗██╔════╝██╔══██╗
 ██║   ██║██████╔╝█████╗  ██████╔╝
 ██║   ██║██╔══██╗██╔══╝  ██╔══██╗
 ╚██████╔╝██████╔╝███████╗██║  ██║
  ╚═════╝ ╚═════╝ ╚══════╝╚═╝  ╚═╝
 ╔╦╗╦═╗╦╔═╗  ╔═╗╔═╗╔═╗╔═╗╦ ╦╔╗╔╔╦╗╦╔╗╔╔═╗
  ║ ╠╦╝║╠═╝  ╠═╣║  ║  ║ ║║ ║║║║ ║ ║║║║║ ╦
  ╩ ╩╚═╩╩    ╩ ╩╚═╝╚═╝╚═╝╚═╝╝╚╝ ╩ ╩╝╚╝╚═╝

Calculate total Uber trip spend for a given year, converting all currencies to a target currency.
"""

import argparse
import json
import sys
import urllib.request

import pandas as pd

# Fare component fields shown in the per-trip summary CSV.
# Verified against an actual Uber receipt (Jan 4 2025, CA$12.39):
#   - fare_amount already includes booking_fee_local, surcharges, and tax
#   - toll_amount_local is separate and must be added
#   - client_upfront_fare_local = fare_amount minus discounts (Uber One credits, etc.)
#   - Tip is NOT present in the CSV export
#
# Trip cost formula:
#   ride_cost = client_upfront_fare_local + toll_amount_local   (post-discount)
#   If client_upfront_fare is missing, fall back to fare_amount + toll_amount_local
FARE_DETAIL_FIELDS = ["fare_amount", "client_upfront_fare_local", "toll_amount_local"]


def fetch_exchange_rates(currencies, target_currency):
    """Fetch current exchange rates to target_currency using open.er-api.com (free, no API key)."""
    non_target = [c for c in currencies if c != target_currency]
    rates = {target_currency: 1.0}
    if not non_target:
        return rates

    # One call gets all rates relative to the target currency
    url = f"https://open.er-api.com/v6/latest/{target_currency}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode())
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"Error fetching exchange rates: {e}", file=sys.stderr)
        sys.exit(1)

    if data.get("result") != "success":
        print("Error: exchange rate API returned unexpected response", file=sys.stderr)
        sys.exit(1)

    # data["rates"] gives: 1 target_currency = X foreign currency
    # To convert foreign -> target: amount_foreign / X
    for currency in non_target:
        if currency in data["rates"]:
            rates[currency] = 1.0 / data["rates"][currency]
        else:
            print(f"Warning: no exchange rate found for {currency}, those trips will be skipped",
                  file=sys.stderr)

    return rates


def main():
    parser = argparse.ArgumentParser(
        description="Calculate total Uber trip spend for a given year.",
        epilog=(
            "How trip cost is calculated:\n"
            "  ride_cost = client_upfront_fare_local + toll_amount_local\n"
            "  (falls back to fare_amount + toll when upfront fare is missing)\n\n"
            "  fare_amount includes base fare, booking fees, surcharges, and tax.\n"
            "  client_upfront_fare_local reflects discounts (e.g. Uber One credits).\n"
            "  Tip is NOT included (not present in the Uber CSV export).\n\n"
            "Currency conversion:\n"
            "  Trips in other currencies are converted to the target currency\n"
            "  (default: CAD) using live exchange rates from open.er-api.com\n"
            "  (free, no API key required).\n\n"
            "Examples:\n"
            "  %(prog)s --year 2024\n"
            "  %(prog)s --year 2025 --csv my_trips.csv\n"
            "  %(prog)s --year 2024 --currency USD\n"
            "  %(prog)s --year 2024 --output 2024_summary.csv\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--year", type=int, required=True,
                        help="Year to process — only completed trips from this year are included")
    parser.add_argument("--csv", default="trips_data-0.csv",
                        help="Path to the Uber trips CSV export (default: %(default)s)")
    parser.add_argument("--currency", default="CAD",
                        help="Target currency for the total spend calculation "
                             "(default: %(default)s)")
    parser.add_argument("--output",
                        help="Write a per-trip summary CSV to this path, with date, addresses, "
                             "fare components, and total cost in both local and target currency")
    args = parser.parse_args()
    args.currency = args.currency.upper()

    df = pd.read_csv(args.csv)

    # Filter to completed trips only
    df = df[df["status"] == "completed"]

    # Extract year from the local request timestamp
    df["year"] = pd.to_datetime(df["request_timestamp_local"]).dt.year
    df = df[df["year"] == args.year]

    if df.empty:
        print(f"No completed trips found for {args.year}.")
        sys.exit(0)

    # Convert cost columns to numeric (handles blanks / missing values)
    for col in FARE_DETAIL_FIELDS:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # Total cost per trip in local currency
    # Use client_upfront_fare (post-discount) when available, else fare_amount (pre-discount)
    # Tolls are always added separately since they are not included in either field
    df["ride_fare"] = df["client_upfront_fare_local"].where(
        df["client_upfront_fare_local"] > 0, df["fare_amount"]
    )
    df["trip_cost_local"] = df["ride_fare"] + df["toll_amount_local"]

    # Currency conversion
    target = args.currency
    currencies = df["currency_code"].unique().tolist()
    rates = fetch_exchange_rates(currencies, target)

    df["rate_to_target"] = df["currency_code"].map(rates)

    # Drop trips whose currency couldn't be converted
    missing = df["rate_to_target"].isna()
    if missing.any():
        skipped = df[missing]
        for cur in skipped["currency_code"].unique():
            print(f"Skipping {len(skipped[skipped['currency_code'] == cur])} trip(s) "
                  f"in {cur} (no exchange rate)")
        df = df[~missing]

    df["trip_cost_target"] = df["trip_cost_local"] * df["rate_to_target"]

    # Print summary
    total_target = df["trip_cost_target"].sum()
    trip_count = len(df)

    print(f"\nUber Trip Spend — {args.year}")
    print("=" * 40)
    print(f"Completed trips: {trip_count}")

    for currency in sorted(currencies):
        subset = df[df["currency_code"] == currency]
        if subset.empty:
            continue
        local_total = subset["trip_cost_local"].sum()
        target_total = subset["trip_cost_target"].sum()
        count = len(subset)
        if currency == target:
            print(f"  {count:>4} trip(s) in {currency}:  ${local_total:>10.2f} {target}")
        else:
            rate = rates[currency]
            print(f"  {count:>4} trip(s) in {currency}:  {local_total:>10.2f} {currency}"
                  f"  →  ${target_total:>10.2f} {target}  (1 {currency} = {rate:.4f} {target})")

    print(f"{'':>28}{'─' * 16}")
    print(f"  Total spend:{' ' * 14}${total_target:>10.2f} {target}\n")

    # Write per-trip summary CSV if requested
    if args.output:
        output_cols = [
            "request_timestamp_local",
            "city_name",
            "product_type_name",
            "begintrip_address",
            "dropoff_address",
            "currency_code",
        ] + FARE_DETAIL_FIELDS + [
            "trip_cost_local",
            "trip_cost_target",
        ]
        out_df = df[output_cols].copy()
        out_df = out_df.rename(columns={
            "request_timestamp_local": "date",
            "trip_cost_target": f"trip_cost_{target.lower()}",
        })
        out_df["date"] = pd.to_datetime(out_df["date"]).dt.strftime("%Y-%m-%d %H:%M")
        out_df = out_df.sort_values("date")
        out_df.to_csv(args.output, index=False, float_format="%.2f")
        print(f"Trip summary written to {args.output}")


if __name__ == "__main__":
    main()
