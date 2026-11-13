"""Train the invoice anomaly model, evaluate it, and enforce the quality gate.

Usage: python -m ml.train [--out model] [--min-f1 0.80]
"""

import argparse
import json
import sys
from pathlib import Path

import joblib
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import f1_score, precision_score, recall_score

from ml.data import generate
from ml.features import invoice_features

SEED = 42


def train(out_dir: Path, n_train: int = 5000, n_test: int = 1500) -> dict:
    train_rows = generate(n_train, seed=SEED)
    test_rows = generate(n_test, seed=SEED + 1)  # different seed = unseen invoices

    x_train = [invoice_features(lines) for lines, _ in train_rows]
    y_train = [label for _, label in train_rows]
    x_test = [invoice_features(lines) for lines, _ in test_rows]
    y_test = [label for _, label in test_rows]

    model = RandomForestClassifier(n_estimators=100, random_state=SEED)
    model.fit(x_train, y_train)
    predicted = model.predict(x_test)

    metrics = {
        "precision": round(precision_score(y_test, predicted), 4),
        "recall": round(recall_score(y_test, predicted), 4),
        "f1": round(f1_score(y_test, predicted), 4),
        "n_train": n_train,
        "n_test": n_test,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, out_dir / "model.joblib")
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("model"))
    parser.add_argument("--min-f1", type=float, default=0.80)
    args = parser.parse_args()

    metrics = train(args.out)
    print(json.dumps(metrics))
    if metrics["f1"] < args.min_f1:
        print(
            f"Quality gate FAILED: f1 {metrics['f1']} < {args.min_f1}", file=sys.stderr
        )
        sys.exit(1)
    print(f"Quality gate passed: f1 {metrics['f1']} >= {args.min_f1}")


if __name__ == "__main__":
    main()
