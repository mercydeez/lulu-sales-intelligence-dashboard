#!/usr/bin/env python3
"""Flywheel churn & uplift training — the honest deep-learning comparison.

    docker exec sales_backend python scripts/flywheel_train.py --tenant 1
    docker exec sales_backend python scripts/flywheel_train.py --tenant 1 --models all

WHAT THIS SCRIPT IS FOR (§8). It trains four things and reports which actually
wins, including when the answer is "the trees did":

  1. LightGBM + isotonic calibration   — the reference baseline
  2. GRU over the ordered event sequence — where DL legitimately earns its place
  3. FT-Transformer on the tabular snapshot — the fashionable comparison
  4. T-learner for uplift              — a different question entirely

THE FRAMING, STATED UP FRONT. On static tabular features, tuned gradient-boosted
trees remain the strongest and most reliable churn learners; neural nets on
flattened snapshots frequently underperform them. We therefore do NOT dress an
MLP up as deep learning. The sequence model gets the ordered event history —
recency ordering and inter-purchase timing — which is exactly the structure a
tabular snapshot discards, and is the only place here where DL has a principled
claim. If the trees still win, that is the finding, and it gets written down.

EVERY RUN IS REPRODUCIBLE: fixed seed, explicit feature/outcome windows, and the
resulting metrics are persisted onto `flywheel_model_versions` alongside the exact
feature list used.

Dependencies are already pinned in requirements.txt (lightgbm, scikit-learn,
torch, pandas, numpy) — this script adds none.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger("flywheel.train")

SEED = 42
ARTIFACT_DIR = Path(os.environ.get("FLYWHEEL_ARTIFACT_DIR", "/app/artifacts/flywheel"))

#: How much worse than the best Brier score a model's calibration may be and
#: still be eligible to win on ranking. 20% is deliberately permissive — the
#: gate exists to catch a model that is badly miscalibrated, not to force a tie.
CALIBRATION_TOLERANCE = 0.20


def _set_seeds() -> None:
    """Pin every RNG a model might touch. Without this the 'reproducible
    training command' promised in §8.5 is not reproducible."""
    import random
    import numpy as np
    random.seed(SEED)
    np.random.seed(SEED)
    try:
        import torch
        torch.manual_seed(SEED)
        torch.use_deterministic_algorithms(False)  # CPU convs need this off
    except ImportError:
        pass


# ---------------------------------------------------------------------------
# Metrics — chosen for the question, not for the flattering number
# ---------------------------------------------------------------------------

def evaluate(y_true, y_prob) -> dict:
    """PR-AUC leads because churn is imbalanced and ROC-AUC flatters on
    imbalanced data. Brier is reported because the optimizer MULTIPLIES this
    probability by customer value — a model that ranks well but is
    systematically overconfident will systematically overspend."""
    import numpy as np
    from sklearn.metrics import (
        average_precision_score, brier_score_loss, confusion_matrix,
        precision_score, recall_score, roc_auc_score,
    )

    y_true = np.asarray(y_true)
    y_prob = np.asarray(y_prob)
    y_pred = (y_prob >= 0.5).astype(int)

    metrics = {
        "pr_auc": float(average_precision_score(y_true, y_prob)),
        "brier": float(brier_score_loss(y_true, y_prob)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "base_rate": float(y_true.mean()),
        "n": int(len(y_true)),
    }
    # ROC-AUC is undefined with a single class present — report it as absent
    # rather than crashing or silently substituting 0.5.
    if len(set(y_true.tolist())) > 1:
        metrics["roc_auc"] = float(roc_auc_score(y_true, y_prob))
        tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
        metrics["confusion"] = {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)}
    return metrics


# ---------------------------------------------------------------------------
# 1. Baseline — calibrated LightGBM
# ---------------------------------------------------------------------------

def train_lightgbm(X_train, y_train, X_test, y_test):
    import numpy as np
    from lightgbm import LGBMClassifier
    from sklearn.calibration import CalibratedClassifierCV

    base = LGBMClassifier(
        n_estimators=300, learning_rate=0.05, num_leaves=31,
        min_child_samples=20, subsample=0.85, subsample_freq=1,
        colsample_bytree=0.85, random_state=SEED, n_jobs=2, verbose=-1,
    )

    # Isotonic calibration needs enough positives per fold to be stable; below
    # that it overfits badly and produces WORSE probabilities than no
    # calibration at all. Fall back to sigmoid (Platt) on small data.
    n_positive = int(np.sum(y_train))
    method = "isotonic" if n_positive >= 150 else "sigmoid"
    model = CalibratedClassifierCV(base, method=method, cv=3)
    model.fit(X_train, y_train)

    probabilities = model.predict_proba(X_test)[:, 1]
    metrics = evaluate(y_test, probabilities)
    metrics["calibration_method"] = method
    return model, metrics


# ---------------------------------------------------------------------------
# 2. Sequence model — where deep learning genuinely earns its place
# ---------------------------------------------------------------------------

def train_sequence(seq_train, y_train, seq_test, y_test, epochs: int = 30):
    """A GRU over each customer's ORDERED event history.

    The input per event is (days_before_cutoff, log1p(units), log1p(value),
    event_type). The ORDER and the GAPS are the signal — flatten them into means
    and you have thrown away exactly the thing that distinguishes a customer
    winding down from one who simply shops infrequently.
    """
    import numpy as np
    import torch
    import torch.nn as nn

    device = torch.device("cpu")  # requirements pin CPU-only torch

    class ChurnGRU(nn.Module):
        def __init__(self, n_features=4, hidden=48):
            super().__init__()
            self.norm = nn.LayerNorm(n_features)
            self.gru = nn.GRU(n_features, hidden, batch_first=True, num_layers=1)
            self.head = nn.Sequential(
                nn.Linear(hidden, 24), nn.ReLU(), nn.Dropout(0.2), nn.Linear(24, 1),
            )

        def forward(self, x):
            _, h = self.gru(self.norm(x))
            # The final hidden state is the learned customer embedding — §8.5
            # calls for embedding-based attribution, and this is that vector.
            return self.head(h[-1]).squeeze(-1)

    model = ChurnGRU().to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=2e-3, weight_decay=1e-4)

    # Class imbalance: weight the positive class by its inverse frequency so the
    # model cannot win by predicting "nobody churns".
    positive_rate = float(np.mean(y_train)) or 0.5
    pos_weight = torch.tensor([(1 - positive_rate) / positive_rate], device=device)
    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)

    Xtr = torch.tensor(np.asarray(seq_train), dtype=torch.float32, device=device)
    ytr = torch.tensor(np.asarray(y_train), dtype=torch.float32, device=device)
    Xte = torch.tensor(np.asarray(seq_test), dtype=torch.float32, device=device)

    batch_size = 64
    n = len(Xtr)
    for epoch in range(epochs):
        model.train()
        permutation = torch.randperm(n)
        total_loss = 0.0
        for start in range(0, n, batch_size):
            idx = permutation[start:start + batch_size]
            optimizer.zero_grad()
            loss = criterion(model(Xtr[idx]), ytr[idx])
            loss.backward()
            # Recurrent nets blow up without this; a single exploded batch
            # otherwise poisons the whole run.
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            total_loss += float(loss) * len(idx)
        if epoch % 10 == 0:
            logger.info("  GRU epoch %02d loss %.4f", epoch, total_loss / n)

    model.eval()
    with torch.no_grad():
        probabilities = torch.sigmoid(model(Xte)).cpu().numpy()
    return model, evaluate(y_test, probabilities)


# ---------------------------------------------------------------------------
# 3. FT-Transformer — tabular deep learning, for an honest comparison
# ---------------------------------------------------------------------------

def train_ft_transformer(X_train, y_train, X_test, y_test, epochs: int = 40):
    """Feature tokenization + self-attention over the tabular snapshot.

    Each scalar feature becomes a token with its own learned embedding; a
    transformer encoder attends across them. This is the architecture usually
    cited when someone claims deep learning beats trees on tabular data — so we
    implement it properly and let the numbers decide rather than asserting.
    """
    import numpy as np
    import torch
    import torch.nn as nn

    device = torch.device("cpu")
    n_features = X_train.shape[1]

    class FTTransformer(nn.Module):
        def __init__(self, n_feat, d_model=32, n_heads=4, n_layers=2):
            super().__init__()
            # One embedding vector + bias per feature: this is the "feature
            # tokenizer" that gives the architecture its name.
            self.weight = nn.Parameter(torch.randn(n_feat, d_model) * 0.02)
            self.bias = nn.Parameter(torch.zeros(n_feat, d_model))
            self.cls = nn.Parameter(torch.randn(1, 1, d_model) * 0.02)
            layer = nn.TransformerEncoderLayer(
                d_model=d_model, nhead=n_heads, dim_feedforward=d_model * 2,
                dropout=0.1, batch_first=True, activation="gelu",
            )
            self.encoder = nn.TransformerEncoder(layer, num_layers=n_layers)
            self.head = nn.Sequential(nn.LayerNorm(d_model), nn.Linear(d_model, 1))

        def forward(self, x):
            tokens = x.unsqueeze(-1) * self.weight + self.bias   # (B, F, d)
            cls = self.cls.expand(x.size(0), -1, -1)
            encoded = self.encoder(torch.cat([cls, tokens], dim=1))
            return self.head(encoded[:, 0]).squeeze(-1)          # CLS token

    # Standardize: attention over raw features with wildly different scales
    # (recency in days vs monetary in thousands) trains extremely poorly.
    mean, std = X_train.mean(axis=0), X_train.std(axis=0) + 1e-8
    Xtr = torch.tensor((X_train - mean) / std, dtype=torch.float32, device=device)
    Xte = torch.tensor((X_test - mean) / std, dtype=torch.float32, device=device)
    ytr = torch.tensor(np.asarray(y_train), dtype=torch.float32, device=device)

    model = FTTransformer(n_features).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    positive_rate = float(np.mean(y_train)) or 0.5
    criterion = nn.BCEWithLogitsLoss(
        pos_weight=torch.tensor([(1 - positive_rate) / positive_rate], device=device))

    batch_size = 64
    n = len(Xtr)
    for epoch in range(epochs):
        model.train()
        permutation = torch.randperm(n)
        total_loss = 0.0
        for start in range(0, n, batch_size):
            idx = permutation[start:start + batch_size]
            optimizer.zero_grad()
            loss = criterion(model(Xtr[idx]), ytr[idx])
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            total_loss += float(loss) * len(idx)
        if epoch % 10 == 0:
            logger.info("  FT-Transformer epoch %02d loss %.4f", epoch, total_loss / n)

    model.eval()
    with torch.no_grad():
        probabilities = torch.sigmoid(model(Xte)).cpu().numpy()
    return model, evaluate(y_test, probabilities)


# ---------------------------------------------------------------------------
# 4. Uplift — a T-learner, judged by Qini and NOT by outcome AUC
# ---------------------------------------------------------------------------

def train_uplift(X, y, treated):
    """Separate treatment and control models; uplift is their difference.

    THE EVALUATION POINT (§8.6): a T-learner is NOT judged by how well either
    arm predicts the outcome. A model can predict outcomes perfectly and rank
    uplift terribly, because uplift is a difference of two predictions and the
    errors need not cancel. Qini on a holdout is the correct measure.
    """
    import numpy as np
    from lightgbm import LGBMClassifier
    from sklearn.model_selection import train_test_split

    from app.services.flywheel.uplift import qini_curve

    X = np.asarray(X)
    y = np.asarray(y)
    treated = np.asarray(treated)

    X_train, X_test, y_train, y_test, t_train, t_test = train_test_split(
        X, y, treated, test_size=0.3, random_state=SEED, stratify=treated)

    def fit(mask):
        if mask.sum() < 20 or len(set(y_train[mask].tolist())) < 2:
            return None
        model = LGBMClassifier(n_estimators=150, learning_rate=0.05, num_leaves=15,
                               random_state=SEED, n_jobs=2, verbose=-1)
        model.fit(X_train[mask], y_train[mask])
        return model

    treatment_model = fit(t_train == 1)
    control_model = fit(t_train == 0)
    if treatment_model is None or control_model is None:
        return None, {"error": "insufficient data in one arm to fit a T-learner"}

    scores = (treatment_model.predict_proba(X_test)[:, 1]
              - control_model.predict_proba(X_test)[:, 1])
    qini = qini_curve(scores.tolist(), y_test.tolist(), t_test.tolist())

    return (
        {"treatment": treatment_model, "control": control_model},
        {
            "qini": qini["qini_coefficient"],
            "qini_points": qini["points"],
            "n_test": int(len(y_test)),
            "treated_share": float(t_test.mean()),
            "note": "Judged by Qini on a holdout, not outcome AUC — a model can "
                    "predict outcomes well and rank uplift badly.",
        },
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

async def main(tenant_id: int, which: str, as_of_arg: str | None) -> int:
    import numpy as np
    from sklearn.model_selection import train_test_split

    from app.services.database import async_session
    from app.services.flywheel import features as feature_service

    _set_seeds()
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

    async with async_session() as db:
        # The cutoff must leave a full outcome window in the past, or every
        # label would be "not yet churned" — the classic silent labelling bug.
        as_of = (date.fromisoformat(as_of_arg) if as_of_arg
                 else date.today() - timedelta(days=feature_service.OUTCOME_WINDOW_DAYS))
        logger.info("Building features as of %s (outcome window %sd)",
                    as_of, feature_service.OUTCOME_WINDOW_DAYS)

        await feature_service.build_snapshots(db, tenant_id=tenant_id, as_of=as_of)
        await db.commit()

        frame = await feature_service.build_training_frame(
            db, tenant_id=tenant_id, as_of=as_of)

        if frame["n_rows"] < 80:
            logger.error("Only %s labelled rows — seed more customers first "
                         "(POST /api/flywheel/seed)", frame["n_rows"])
            return 1
        if frame["n_positive"] < 15 or frame["n_positive"] == frame["n_rows"]:
            logger.error("Degenerate labels (%s positive of %s). Adjust the "
                         "outcome window or regenerate customers.",
                         frame["n_positive"], frame["n_rows"])
            return 1

        logger.info("Training frame: %s rows, %s positive (%.1f%% base rate)",
                    frame["n_rows"], frame["n_positive"], frame["base_rate"] * 100)

        X = np.asarray(frame["features"], dtype=float)
        y = np.asarray(frame["labels"], dtype=int)
        customer_ids = frame["customer_ids"]

        idx_train, idx_test = train_test_split(
            np.arange(len(y)), test_size=0.3, random_state=SEED, stratify=y)

        results: dict[str, dict] = {}
        artifacts: dict[str, object] = {}

        # 1. Baseline
        logger.info("Training LightGBM baseline…")
        lgbm, results["lightgbm"] = train_lightgbm(
            X[idx_train], y[idx_train], X[idx_test], y[idx_test])
        artifacts["lightgbm"] = lgbm
        logger.info("  PR-AUC %.4f · Brier %.4f (%s calibration)",
                    results["lightgbm"]["pr_auc"], results["lightgbm"]["brier"],
                    results["lightgbm"]["calibration_method"])

        if which in ("all", "deep"):
            # 2. Sequence model
            logger.info("Training GRU sequence model…")
            sequences = await feature_service.build_sequences(
                db, tenant_id=tenant_id, as_of=as_of)
            seq_by_customer = dict(zip(sequences["customer_ids"], sequences["sequences"]))
            empty = [[0.0] * 4] * sequences["max_len"]
            seq = np.asarray([seq_by_customer.get(c, empty) for c in customer_ids])
            try:
                gru, results["sequence_gru"] = train_sequence(
                    seq[idx_train], y[idx_train], seq[idx_test], y[idx_test])
                artifacts["sequence_gru"] = gru
                logger.info("  PR-AUC %.4f · Brier %.4f",
                            results["sequence_gru"]["pr_auc"], results["sequence_gru"]["brier"])
            except Exception as exc:
                logger.warning("  GRU training failed (%s) — reporting it rather "
                               "than hiding it", exc)
                results["sequence_gru"] = {"error": str(exc)}

            # 3. FT-Transformer
            logger.info("Training FT-Transformer…")
            try:
                ft, results["ft_transformer"] = train_ft_transformer(
                    X[idx_train], y[idx_train], X[idx_test], y[idx_test])
                artifacts["ft_transformer"] = ft
                logger.info("  PR-AUC %.4f · Brier %.4f",
                            results["ft_transformer"]["pr_auc"], results["ft_transformer"]["brier"])
            except Exception as exc:
                logger.warning("  FT-Transformer training failed (%s)", exc)
                results["ft_transformer"] = {"error": str(exc)}

        # 4. Uplift
        if which in ("all", "uplift"):
            logger.info("Training uplift T-learner…")
            # Treatment assignment from the synthetic randomized log: customers
            # who were actually presented an offer.
            from sqlalchemy import text
            treated_rows = (await db.execute(
                text("""SELECT DISTINCT customer_id FROM flywheel_customer_events
                         WHERE tenant_id = :t
                           AND event_type IN ('offer_seen','offer_redeemed','offer_ignored')
                           AND occurred_at < :as_of"""),
                {"t": tenant_id, "as_of": as_of},
            )).fetchall()
            treated_set = {int(r[0]) for r in treated_rows}
            treated = np.asarray([1 if c in treated_set else 0 for c in customer_ids])

            if treated.sum() < 30 or (len(treated) - treated.sum()) < 30:
                results["uplift_t_learner"] = {
                    "error": f"arms too small (treated={int(treated.sum())}, "
                             f"control={int(len(treated) - treated.sum())})"}
            else:
                # Response = did NOT churn.
                t_model, results["uplift_t_learner"] = train_uplift(X, 1 - y, treated)
                if t_model:
                    artifacts["uplift_t_learner"] = t_model
                    logger.info("  Qini %.5f", results["uplift_t_learner"]["qini"])

        # ── Persist artifacts + register versions ───────────────────────────
        import joblib
        from sqlalchemy import text

        # ── Model selection: ranking, GATED ON CALIBRATION ──────────────────
        #
        # Selecting purely by PR-AUC is the obvious rule and it is wrong for
        # THIS system. The optimizer MULTIPLIES this probability by customer
        # value to get expected retained value, so a model that ranks better but
        # is systematically overconfident produces systematically larger spend
        # on every customer it touches. The model card says exactly this; the
        # first version of this script then ignored it and activated the
        # worse-calibrated model (GRU, Brier 0.0737) over the better-calibrated
        # baseline (LightGBM, Brier 0.0656) purely on PR-AUC.
        #
        # So: ranking decides the winner, but only among models whose
        # calibration is within a tolerance of the best. A model that ranks
        # brilliantly and is badly calibrated is disqualified rather than
        # silently trusted with the budget.
        churn_results = {k: v for k, v in results.items()
                         if k != "uplift_t_learner" and "pr_auc" in v}
        winner = None
        if churn_results:
            best_brier = min(v["brier"] for v in churn_results.values())
            tolerance = best_brier * (1 + CALIBRATION_TOLERANCE)
            eligible = {k: v for k, v in churn_results.items()
                        if v["brier"] <= tolerance}
            disqualified = sorted(set(churn_results) - set(eligible))
            winner = max(eligible, key=lambda k: eligible[k]["pr_auc"], default=None)
            if disqualified:
                logger.info("Calibration gate excluded %s (Brier worse than "
                            "%.4f, the best %.4f + %.0f%% tolerance)",
                            ", ".join(disqualified), tolerance, best_brier,
                            CALIBRATION_TOLERANCE * 100)

        for name, metrics in results.items():
            if "error" in metrics:
                continue
            artifact = artifacts.get(name)
            path = None
            if artifact is not None and name in ("lightgbm", "uplift_t_learner"):
                # Only sklearn-compatible artifacts are persisted for serving —
                # the torch models are research comparisons, and loading them at
                # request time would need the model class in the serving path.
                path = str(ARTIFACT_DIR / f"{tenant_id}_{name}.joblib")
                joblib.dump(artifact, path)

            kind = "uplift" if name == "uplift_t_learner" else (
                "sequence" if name == "sequence_gru"
                else "tabular_dl" if name == "ft_transformer" else "churn")
            algorithm = {"lightgbm": "lightgbm", "sequence_gru": "gru",
                         "ft_transformer": "ft_transformer",
                         "uplift_t_learner": "t_learner"}[name]

            # Only the winning CHURN model is activated for serving; the others
            # are registered with their metrics for honest comparison.
            is_active = (name == winner and kind == "churn" and path is not None) \
                or (kind == "uplift" and path is not None)

            if is_active:
                await db.execute(
                    text("""UPDATE flywheel_model_versions SET is_active = FALSE
                             WHERE tenant_id = :t AND model_kind = :k"""),
                    {"t": tenant_id, "k": kind})

            await db.execute(
                text("""INSERT INTO flywheel_model_versions
                           (tenant_id, model_kind, algorithm, version_label, random_seed,
                            feature_window_days, outcome_window_days, feature_list,
                            metrics, artifact_path, trained_at, is_active, notes)
                        VALUES (:t, :k, :alg, :v, :seed, :fw, :ow, CAST(:fl AS JSONB),
                                CAST(:m AS JSONB), :path, now(), :active, :notes)
                        ON CONFLICT (tenant_id, model_kind, version_label) DO UPDATE
                            SET metrics = EXCLUDED.metrics,
                                artifact_path = EXCLUDED.artifact_path,
                                trained_at = EXCLUDED.trained_at,
                                is_active = EXCLUDED.is_active"""),
                {"t": tenant_id, "k": kind, "alg": algorithm,
                 "v": f"{algorithm}-{as_of.isoformat()}", "seed": SEED,
                 "fw": feature_service.FEATURE_WINDOW_DAYS,
                 "ow": feature_service.OUTCOME_WINDOW_DAYS,
                 "fl": json.dumps(frame["feature_names"]),
                 "m": json.dumps({k: v for k, v in metrics.items()
                                  if k != "qini_points"}),
                 "path": path, "active": is_active,
                 "notes": f"Trained on synthetic data as of {as_of}. "
                          f"No production accuracy is claimed."},
            )

        await db.commit()

    # ── The honest report ───────────────────────────────────────────────────
    print("\n" + "=" * 74)
    print("FLYWHEEL MODEL COMPARISON — synthetic data, no production accuracy claimed")
    print("=" * 74)
    print(f"{'model':<22}{'PR-AUC':>10}{'ROC-AUC':>10}{'Brier':>10}{'recall':>10}")
    print("-" * 74)
    for name, metrics in results.items():
        if "error" in metrics:
            print(f"{name:<22}{'— ' + metrics['error'][:44]:>42}")
        elif "pr_auc" in metrics:
            print(f"{name:<22}{metrics['pr_auc']:>10.4f}"
                  f"{metrics.get('roc_auc', float('nan')):>10.4f}"
                  f"{metrics['brier']:>10.4f}{metrics['recall']:>10.4f}")
        elif "qini" in metrics:
            print(f"{name:<22}{'Qini':>10}{metrics['qini']:>10.5f}")
    print("-" * 74)

    if winner:
        print(f"\nBest churn model by PR-AUC: {winner}")
        if winner == "lightgbm":
            print(
                "The gradient-boosted baseline won. This is the expected and\n"
                "well-documented result on tabular features, and it is reported\n"
                "as a finding rather than buried: the sequence model has a\n"
                "principled claim on the ORDERED event history, but with this\n"
                "volume of synthetic data it did not overturn the trees."
            )
        else:
            print(
                f"{winner} beat the calibrated tree baseline. On this synthetic\n"
                "dataset that is a real result, but note the data is generated\n"
                "and the margin should be re-checked on a larger sample before\n"
                "any general claim is made."
            )
    print(f"\nArtifacts: {ARTIFACT_DIR}")
    print("Registered on flywheel_model_versions — visible at /flywheel/models.\n")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train Flywheel churn & uplift models")
    parser.add_argument("--tenant", type=int, default=1)
    parser.add_argument("--models", choices=["baseline", "deep", "uplift", "all"],
                        default="all")
    parser.add_argument("--as-of", type=str, default=None,
                        help="Feature cutoff (YYYY-MM-DD). Defaults to today minus "
                             "the outcome window, so labels are observable.")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.tenant, args.models, args.as_of)))
