"""Synthetic invoice data with labelled anomalies (seeded, so every run is identical)."""

import random

STANDARD_VAT_RATES = (0.0, 0.07, 0.13, 0.19)  # Tunisian VAT rates


def _normal_invoice(rng: random.Random) -> list[dict]:
    return [
        {
            "quantity": rng.randint(1, 20),
            "unit_price": round(rng.lognormvariate(4, 1), 3),
            "vat_rate": rng.choice(STANDARD_VAT_RATES),
        }
        for _ in range(rng.randint(1, 8))
    ]


def _anomalous_invoice(rng: random.Random) -> list[dict]:
    lines = _normal_invoice(rng)
    line = rng.choice(lines)
    kind = rng.choice(["vat", "price", "quantity"])
    if kind == "vat":  # a rate that does not exist, sometimes close to a real one
        line["vat_rate"] = rng.choice([0.05, 0.1, 0.17, 0.18, 0.2, 0.25])
    elif kind == "price":  # overlaps with legitimately expensive lines
        line["unit_price"] = round(line["unit_price"] * rng.uniform(5, 30), 3)
    else:
        line["quantity"] *= rng.randint(10, 50)
    return lines


def generate(
    n: int, seed: int, anomaly_rate: float = 0.1
) -> list[tuple[list[dict], int]]:
    """Return n (lines, label) pairs; label 1 = anomaly."""
    rng = random.Random(seed)
    rows = []
    for _ in range(n):
        is_anomaly = rng.random() < anomaly_rate
        lines = _anomalous_invoice(rng) if is_anomaly else _normal_invoice(rng)
        rows.append((lines, int(is_anomaly)))
    return rows
