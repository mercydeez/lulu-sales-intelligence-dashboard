"""
Deep-learning forecaster (LSTM) — the DL tier of the registry.

Heavy/optional: `torch` is imported lazily and guarded, so the rest of the app
(and the classical/ML tiers) run fine even if torch isn't installed. Everything
is seeded for determinism — given the same history the forecast is identical, no
randomness.

NOTE on serving: training an LSTM on CPU at request time is acceptable for an
on-demand forecast but not for hot paths. Production should train on a schedule
and cache the forecast (see roadmap: per-tenant model registry). Epochs/size are
kept modest here so a single-series forecast returns in a few seconds.
"""
from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

WINDOW = 28


class LSTMForecaster:
    name = "lstm"
    tier = "dl"

    def __init__(self, window: int = WINDOW, hidden: int = 32, epochs: int = 80):
        self.window = window
        self.hidden = hidden
        self.epochs = epochs
        try:
            import torch  # noqa: F401
            self.available = True
        except Exception:
            self.available = False

    def fit(self, series: pd.Series) -> "LSTMForecaster":
        import torch
        import torch.nn as nn

        # Determinism
        torch.manual_seed(42)
        np.random.seed(42)
        try:
            torch.use_deterministic_algorithms(True)
        except Exception:
            pass
        torch.set_num_threads(1)

        vals = series.values.astype("float32")
        if len(vals) <= self.window + 8:
            raise ValueError("not enough history for the LSTM window")

        # Standardize (store stats to invert later)
        self._mu = float(vals.mean())
        self._sd = float(vals.std()) or 1.0
        scaled = (vals - self._mu) / self._sd

        W = self.window
        xs, ys = [], []
        for i in range(len(scaled) - W):
            xs.append(scaled[i : i + W])
            ys.append(scaled[i + W])
        X = torch.tensor(np.array(xs, dtype="float32")).unsqueeze(-1)  # [N, W, 1]
        Y = torch.tensor(np.array(ys, dtype="float32")).unsqueeze(-1)  # [N, 1]

        class _Net(nn.Module):
            def __init__(self, hidden: int):
                super().__init__()
                self.lstm = nn.LSTM(input_size=1, hidden_size=hidden, num_layers=1, batch_first=True)
                self.fc = nn.Linear(hidden, 1)

            def forward(self, x):
                out, _ = self.lstm(x)
                return self.fc(out[:, -1, :])

        self.net = _Net(self.hidden)
        opt = torch.optim.Adam(self.net.parameters(), lr=0.01)
        loss_fn = nn.MSELoss()

        self.net.train()
        for _ in range(self.epochs):
            opt.zero_grad()
            pred = self.net(X)
            loss = loss_fn(pred, Y)
            loss.backward()
            opt.step()
        self.net.eval()

        self._scaled = scaled
        self._last_date = series.index[-1]
        return self

    def predict(self, horizon: int) -> np.ndarray:
        import torch

        W = self.window
        window = list(self._scaled[-W:])
        preds = []
        with torch.no_grad():
            for _ in range(horizon):
                x = torch.tensor(np.array(window[-W:], dtype="float32")).reshape(1, W, 1)
                yhat = float(self.net(x).item())
                preds.append(yhat)
                window.append(yhat)
        arr = np.array(preds, dtype=float) * self._sd + self._mu
        return np.clip(arr, 0, None)
