```
 ██╗   ██╗██████╗ ███████╗██████╗
 ██║   ██║██╔══██╗██╔════╝██╔══██╗
 ██║   ██║██████╔╝█████╗  ██████╔╝
 ██║   ██║██╔══██╗██╔══╝  ██╔══██╗
 ╚██████╔╝██████╔╝███████╗██║  ██║
  ╚═════╝ ╚═════╝ ╚══════╝╚═╝  ╚═╝
 ╔╦╗╦═╗╦╔═╗  ╔═╗╔═╗╔═╗╔═╗╦ ╦╔╗╔╔╦╗╦╔╗╔╔═╗
  ║ ╠╦╝║╠═╝  ╠═╣║  ║  ║ ║║ ║║║║ ║ ║║║║║ ╦
  ╩ ╩╚═╩╩    ╩ ╩╚═╝╚═╝╚═╝╚═╝╝╚╝ ╩ ╩╝╚╝╚═╝
```

# Uber Trip Accounting

A Python script that processes Uber's CSV trip data export and calculates total spend for a given year, with all amounts converted to a target currency (defaults to CAD).

## Features

- Filters to **completed trips only** (ignores cancelled rides)
- Processes **one year at a time** via the `--year` flag
- **Currency-aware**: automatically converts trips to a target currency (default: CAD) using live exchange rates from [open.er-api.com](https://open.er-api.com) — free, no API key required. Use the `--currency` flag to choose any supported currency (USD, EUR, GBP, KRW, etc.)
- Optional **per-trip summary CSV** output with fare breakdown
- Built with **pandas** for robust CSV handling that tolerates future column changes in Uber's export format

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install pandas
```

## Usage

```bash
# Total spend for 2024
python3 uber_trip_totals.py --year 2024

# Use a different CSV file
python3 uber_trip_totals.py --year 2025 --csv my_trips.csv

# Convert totals to USD instead of CAD
python3 uber_trip_totals.py --year 2024 --currency USD

# Also write a per-trip summary CSV
python3 uber_trip_totals.py --year 2024 --output 2024_summary.csv
```

### Command-line options

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--year` | Yes | — | Year to process (only completed trips from this year) |
| `--csv` | No | `trips_data-0.csv` | Path to the Uber trips CSV export |
| `--currency` | No | `CAD` | Target currency for the total spend calculation |
| `--output` | No | — | Write a per-trip summary CSV to this path |

### Example output

```
Uber Trip Spend — 2024
========================================
Completed trips: 124
   113 trip(s) in CAD:  $   2200.86 CAD
    11 trip(s) in USD:      331.40 USD  →  $    454.02 CAD  (1 USD = 1.3700 CAD)
                            ────────────────
  Total spend:              $   2654.88 CAD
```

### Output CSV columns

When `--output` is specified, the summary CSV contains:

| Column | Description |
|--------|-------------|
| `date` | Trip date and time (YYYY-MM-DD HH:MM) |
| `city_name` | City where the trip took place |
| `product_type_name` | Uber product type (e.g. uberX) |
| `begintrip_address` | Pickup address |
| `dropoff_address` | Drop-off address |
| `currency_code` | Original trip currency |
| `fare_amount` | Pre-discount ride total (includes all fees, surcharges, tax) |
| `client_upfront_fare_local` | Post-discount ride total (after Uber One credits, etc.) |
| `toll_amount_local` | Toll charges (separate from fare) |
| `trip_cost_local` | Computed trip cost in local currency |
| `trip_cost_<currency>` | Computed trip cost converted to target currency (e.g. `trip_cost_cad`, `trip_cost_usd`) |

## How trip cost is calculated

Uber's CSV export provides no documentation, so the formula was reverse-engineered by cross-referencing CSV field values against an actual Uber email receipt (a CA$12.39 trip on January 4, 2025).

### The formula

```
trip_cost = client_upfront_fare_local + toll_amount_local
```

If `client_upfront_fare_local` is zero or missing (some older trips), it falls back to:

```
trip_cost = fare_amount + toll_amount_local
```

### Why this formula — a worked example

The January 4, 2025 Uber receipt breaks down a **CA$12.39** charge as follows:

| Receipt line item | Amount |
|---|---|
| Trip fare | CA$5.68 |
| **Subtotal** | **CA$5.68** |
| Uber One Credits | -CA$0.47 |
| Est. insurance and payments costs | CA$0.84 |
| Toronto Fee Recovery Surcharges | CA$0.34 |
| Toronto Accessibility Fee Recovery Surcharges | CA$0.10 |
| Tip | CA$5.00 |
| HST | CA$0.90 |
| **Total charged** | **CA$12.39** |

The corresponding CSV row (line 390) has these relevant fields:

| CSV field | Value | What it represents |
|---|---|---|
| `fare_amount` | 7.86 | **Pre-discount total**: trip fare ($5.68) + insurance ($0.84) + surcharges ($0.44) + HST ($0.90) |
| `client_upfront_fare_local` | 7.39 | **Post-discount total**: `fare_amount` ($7.86) minus Uber One Credits ($0.47) |
| `booking_fee_local` | 0.84 | Insurance and payments costs — already included inside `fare_amount` |
| `toll_amount_local` | 0.00 | Tolls — NOT included in `fare_amount`, must be added separately |
| `base_fare_local` | 3.04 | Base fare component — already included inside `fare_amount` |
| `per_mile_fare_local` | 0.79 | Per-km charge — already included inside `fare_amount` |
| `per_minute_fare_local` | 0.39 | Per-minute charge — already included inside `fare_amount` |
| `service_fee_local` | -1.47 | Internal service fee (negative) — driver/platform split, not rider-facing |

### Key findings

1. **`fare_amount` already includes** base fare, booking fees, surcharges, and tax — adding `booking_fee_local` on top would double-count
2. **`client_upfront_fare_local`** = `fare_amount` minus any discounts (Uber One credits, etc.) — this is what was actually charged for the ride portion
3. **`toll_amount_local`** is the only cost component stored separately that needs to be added
4. **Tip is not present** in the CSV export at all — there is no tip field, so computed totals reflect the ride cost only (excluding tip)
5. **`promotion_local`** and **`credits_local`** capture some promotional discounts but do **not** capture Uber One membership credits — those are only reflected in the difference between `fare_amount` and `client_upfront_fare_local`
6. For ~21 older trips (pre-2018) where `client_upfront_fare_local` is missing, the script falls back to `fare_amount` (pre-discount), which may slightly overstate the cost if discounts were applied

### Visual summary

```
                                    ┌─────────────────────────────┐
                                    │       fare_amount           │
                                    │  (pre-discount ride total)  │
                                    │                             │
                                    │  Includes:                  │
                                    │   • base_fare_local         │
                                    │   • per_mile_fare_local     │
                                    │   • per_minute_fare_local   │
                                    │   • surge_fare_local        │
                                    │   • booking_fee_local       │
                                    │   • surcharges              │
                                    │   • tax (HST)               │
                                    └──────────┬──────────────────┘
                                               │
                                    subtract discounts
                                  (Uber One credits, etc.)
                                               │
                                               ▼
                                    ┌─────────────────────────────┐
                                    │ client_upfront_fare_local   │
                                    │  (post-discount ride total) │
                                    └──────────┬──────────────────┘
                                               │
                                          + toll_amount_local
                                               │
                                               ▼
                                    ┌─────────────────────────────┐
                                    │      trip_cost_local        │
                                    │   (total ride cost in       │
                                    │    local currency)          │
                                    │                             │
                                    │   Note: excludes tip        │
                                    │   (not in CSV export)       │
                                    └─────────────────────────────┘
```

## Currency conversion

Trips taken in a currency different from the target are converted automatically. The script fetches live exchange rates from [open.er-api.com](https://open.er-api.com) — a free API that requires no API key or authentication — and converts all amounts to the target currency (default: CAD) for the final total.

If a currency cannot be converted (rate not found), those trips are skipped with a warning.

## Obtaining your Uber trip data

1. Go to [privacy.uber.com](https://privacy.uber.com)
2. Request a download of your data
3. Uber will email you a link to download a ZIP file
4. Extract the CSV file (e.g. `trips_data-0.csv`) and place it in this directory
