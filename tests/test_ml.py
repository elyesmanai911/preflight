import json

import pytest

from ml import train as train_module
from ml.data import STANDARD_VAT_RATES, generate
from ml.features import FEATURE_NAMES, invoice_features


def test_data_is_reproducible():
    assert generate(50, seed=1) == generate(50, seed=1)
    assert generate(50, seed=1) != generate(50, seed=2)


def test_anomaly_rate_is_roughly_as_requested():
    labels = [label for _, label in generate(2000, seed=1, anomaly_rate=0.1)]
    assert 0.07 < sum(labels) / len(labels) < 0.13


def test_features_match_names_and_flag_bad_vat():
    good = [{"quantity": 2, "unit_price": 10, "vat_rate": STANDARD_VAT_RATES[-1]}]
    bad = [{"quantity": 2, "unit_price": 10, "vat_rate": 0.18}]
    assert len(invoice_features(good)) == len(FEATURE_NAMES)
    assert invoice_features(good)[-1] == 0
    assert invoice_features(bad)[-1] == 1


def test_train_writes_model_and_metrics(tmp_path):
    metrics = train_module.train(tmp_path, n_train=500, n_test=200)
    assert (tmp_path / "model.joblib").exists()
    assert json.loads((tmp_path / "metrics.json").read_text()) == metrics
    assert 0 <= metrics["f1"] <= 1


def test_quality_gate_fails_below_threshold(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "sys.argv", ["train", "--out", str(tmp_path), "--min-f1", "1.01"]
    )
    with pytest.raises(SystemExit) as exit_info:
        train_module.main()
    assert exit_info.value.code == 1
