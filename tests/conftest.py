import os
import tempfile
from pathlib import Path

from ml.train import train


def pytest_configure(config):
    # The API loads its model at import time, so train a small one before tests import it.
    model_dir = Path(tempfile.mkdtemp())
    train(model_dir, n_train=1000, n_test=200)
    os.environ["MODEL_PATH"] = str(model_dir / "model.joblib")
