"""Invoice → feature vector. Used by BOTH training and the API, so they can never disagree."""

import math

from ml.data import STANDARD_VAT_RATES

FEATURE_NAMES = [
    "n_lines",
    "log_total_excl_vat",
    "log_max_unit_price",
    "log_max_quantity",
    "n_nonstandard_vat_rates",
]


def invoice_features(lines: list[dict]) -> list[float]:
    quantities = [float(line["quantity"]) for line in lines]
    prices = [float(line["unit_price"]) for line in lines]
    rates = [round(float(line["vat_rate"]), 4) for line in lines]
    total = sum(q * p for q, p in zip(quantities, prices))
    return [
        len(lines),
        math.log1p(total),
        math.log1p(max(prices)),
        math.log1p(max(quantities)),
        sum(rate not in STANDARD_VAT_RATES for rate in rates),
    ]
