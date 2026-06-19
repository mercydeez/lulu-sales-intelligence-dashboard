"""
Deep-learning forecasters — the DL tier of the registry.

Three architectures share one trainer (windowed, standardized, recursive
multi-step forecast), so they all plug into the same backtest as the classical
and ML tiers:
  - lstm : LSTM recurrent net
  - gru  : GRU recurrent net (RNN family)
  - cnn  : 1D convolutional net over the input window

torch is imported lazily and guarded, so the app + other tiers run fine without
it. Everything is seeded for determinism (no randomness). Configs are kept small
so request-time training stays bounded; scheduled training is the production path.
"""
from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

WINDOW = 28


class _TorchSeqForecaster:
    """Base: standardize -> sliding windows -> train -> recursive forecast."""
    name = "torch"
    tier = "dl"

    def __init__(self, window: int = WINDOW, hidden: int = 24, epochs: int = 60):
        self.window = window
        self.hidden = hidden
        self.epochs = epochs
        try:
            import torch  # noqa: F401
            self.available = True
        except Exception:
            self.available = False

    def _build_net(self, hidden: int):  # pragma: no cover - overridden
        raise NotImplementedError

    def fit(self, series: pd.Series) -> "_TorchSeqForecaster":
        import torch
        import torch.nn as nn

        torch.manual_seed(42)
        np.random.seed(42)
        try:
            torch.use_deterministic_algorithms(True)
        except Exception:
            pass
        torch.set_num_threads(1)

        vals = series.values.astype("float32")
        if len(vals) <= self.window + 8:
            raise ValueError("not enough history for the window")

        self._mu = float(vals.mean())
        self._sd = float(vals.std()) or 1.0
        scaled = (vals - self._mu) / self._sd

        W = self.window
        xs, ys = [], []
        for i in range(len(scaled) - W):
            xs.append(scaled[i : i + W])
            ys.append(scaled[i + W])
        X = torch.tensor(np.array(xs, dtype="float32"))   # [N, W]
        Y = torch.tensor(np.array(ys, dtype="float32"))   # [N]

        self.net = self._build_net(self.hidden)
        opt = torch.optim.Adam(self.net.parameters(), lr=0.01)
        loss_fn = nn.MSELoss()
        self.net.train()
        for _ in range(self.epochs):
            opt.zero_grad()
            out = self.net(X).squeeze(-1)
            loss = loss_fn(out, Y)
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
                x = torch.tensor(np.array(window[-W:], dtype="float32")).reshape(1, W)
                yhat = float(self.net(x).squeeze().item())
                preds.append(yhat)
                window.append(yhat)
        arr = np.array(preds, dtype=float) * self._sd + self._mu
        return np.clip(arr, 0, None)


class LSTMForecaster(_TorchSeqForecaster):
    name = "lstm"

    def _build_net(self, hidden: int):
        import torch.nn as nn

        class Net(nn.Module):
            def __init__(self):
                super().__init__()
                self.rnn = nn.LSTM(1, hidden, num_layers=1, batch_first=True)
                self.fc = nn.Linear(hidden, 1)

            def forward(self, x):
                out, _ = self.rnn(x.unsqueeze(-1))   # [B, W, 1]
                return self.fc(out[:, -1, :])

        return Net()


class GRUForecaster(_TorchSeqForecaster):
    name = "gru"

    def _build_net(self, hidden: int):
        import torch.nn as nn

        class Net(nn.Module):
            def __init__(self):
                super().__init__()
                self.rnn = nn.GRU(1, hidden, num_layers=1, batch_first=True)
                self.fc = nn.Linear(hidden, 1)

            def forward(self, x):
                out, _ = self.rnn(x.unsqueeze(-1))
                return self.fc(out[:, -1, :])

        return Net()


class CNNForecaster(_TorchSeqForecaster):
    name = "cnn"

    def _build_net(self, hidden: int):
        import torch.nn as nn

        class Net(nn.Module):
            def __init__(self):
                super().__init__()
                self.conv1 = nn.Conv1d(1, hidden, kernel_size=3, padding=1)
                self.conv2 = nn.Conv1d(hidden, hidden, kernel_size=3, padding=1)
                self.act = nn.ReLU()
                self.pool = nn.AdaptiveAvgPool1d(1)
                self.fc = nn.Linear(hidden, 1)

            def forward(self, x):
                z = x.unsqueeze(1)                  # [B, 1, W]
                z = self.act(self.conv1(z))
                z = self.act(self.conv2(z))
                z = self.pool(z).squeeze(-1)        # [B, hidden]
                return self.fc(z)

        return Net()
