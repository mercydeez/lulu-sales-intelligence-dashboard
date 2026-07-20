# Flywheel — Model Card

**Module:** Retention & Commercial Orchestration (Flywheel) · **Owner:** Krishna Mathur
**Last updated:** 2026-07-20 · **Status:** synthetic-data prototype

---

## 1. The headline, stated first

**All customer data, treatment histories and campaign outcomes are synthetic.
No production accuracy is claimed, and none of the metrics below transfer to a
real retailer.** The underlying dataset (Kaggle store-item demand) is
store×item×day aggregates with no customer identity, so the customer layer is
generated with a fixed seed. What the numbers demonstrate is that the *pipeline*
is correct and honestly evaluated — not that churn has been solved.

## 2. What is modelled, and what is decided

Two different things, deliberately kept apart:

| | Question | Produced by | Can it move money? |
|---|---|---|---|
| **Churn model** | How likely is this customer to leave? | `services/flywheel/churn.py` | **No** |
| **Uplift model** | Would an offer actually change that? | `services/flywheel/uplift.py` | **No** |
| **Optimizer** | Which action maximises incremental value? | `services/flywheel/optimizer.py` | **No** — proposes |
| **Budget / inventory services** | May this action actually execute? | `budget.py`, `inventory_atp.py`, `decisioning.py` | **Yes**, under row locks |

Models emit scores. Money and stock move only through deterministic services
inside row-locked transactions with an audit trail. This is architectural, not a
policy: `optimizer.py` contains no model and `churn.py` executes no writes to
any financial table.

## 3. Why a high churn score never buys a discount

The objective function is:

```
EIV = expected retained value      (× uplift)
    + expected incremental margin  (× redemption probability)
    − expected discount cost
    − communication cost
    − fulfilment cost
    − incremental procurement cost
    − stockout-risk penalty
```

Every **benefit** term multiplies **uplift**, never churn probability. A customer
at 92% churn risk with zero uplift produces `expected_retained_value = 0`, so the
best action is `NO_ACTION` — enforced by the shape of the objective, not by a
guard clause that could be bypassed. Tested in
`tests/test_flywheel_decisioning.py::test_high_churn_with_zero_uplift_yields_no_discount`.

## 4. Features and leakage control

**Feature window:** 180 days before the cutoff. **Outcome window:** 60 days after.
The two are disjoint by construction — every feature query in `features.py`
carries `occurred_at < :as_of`, and the label query carries `occurred_at >= :as_of`.
They are written adjacently in the same file so a reviewer can verify they cannot
overlap.

**Label:** a customer is churned (1) if they made **no purchase** in
`[as_of, as_of + 60 days)`.

**The twelve features** — all behavioural:

`recency_days · frequency_90d · monetary_90d_aed · avg_basket_aed ·
spend_drift_ratio · interpurchase_gap_days · gap_volatility ·
category_diversity · return_ratio · promo_response_rate · tenure_days · events_90d`

**Deliberately excluded:** the generator's `archetype` column. It is stored for
evaluation but never selected as a feature — a model given it would score near
1.0 AUC and prove nothing.

## 5. Fairness

No sensitive attribute — gender, ethnicity, religion, nationality — is generated,
stored, or used as a model feature or offer-decision input. The `flywheel_customers`
table has no column for any of them. `loyalty_tier` is derived from spending
behaviour, not demographics.

Contact-frequency caps and consent are enforced as hard gates before any offer,
so a customer cannot be over-contacted because a model found them interesting.

## 6. The deep-learning strategy, and its honest framing

On *static tabular* features, tuned gradient-boosted trees remain the strongest
and most reliable churn learners; neural networks on flattened snapshots
frequently underperform them. We therefore do **not** dress an MLP up as deep
learning. Four models are trained by `scripts/flywheel_train.py`:

### 6.1 Baseline — calibrated LightGBM (the reference)
300 trees, isotonic calibration (Platt fallback below 150 positives, where
isotonic overfits). This is the model to beat.

### 6.2 Sequence model — GRU (where DL has a principled claim)
A GRU over each customer's **ordered** event history: `(days_before_cutoff,
log1p(units), log1p(value), event_type)`, right-aligned and left-padded to 32
events. The final hidden state is a learned customer embedding.

**Rationale:** sequence order and inter-purchase timing are *exactly* the
structure a tabular snapshot discards when it collapses history into means. A
customer winding down and a customer who simply shops infrequently can have
identical feature vectors and completely different event sequences. This is the
one place in the module where deep learning earns its place on the merits.

### 6.3 FT-Transformer — the fashionable comparison
Feature tokenization (one learned embedding + bias per feature) plus a 2-layer
transformer encoder with a CLS token. Implemented properly rather than strawmanned,
because it is the architecture usually cited when someone claims DL beats trees on
tabular data.

### 6.4 Selection rule — ranking, GATED ON CALIBRATION
Selecting purely by PR-AUC is wrong for this system, and the first version of
the training script did exactly that. The optimizer **multiplies** the churn
probability by customer value, so a model that ranks better while being
systematically overconfident produces systematically larger spend on every
customer it touches. It activated the worse-calibrated model on its first run.

The rule is now: **highest PR-AUC among models whose Brier is within 20% of the
best Brier.** A model that ranks brilliantly and is badly calibrated is
disqualified rather than quietly trusted with the budget.

### 6.5 MEASURED RESULTS (2026-07-20, 300 synthetic customers)

Two runs, on two regenerations of the same fixed-seed population:

| Model | Run A PR-AUC | Run A Brier | Run B PR-AUC | Run B Brier |
|---|---|---|---|---|
| LightGBM (baseline) | 0.8515 | **0.0656** | 0.8937 | 0.0792 |
| GRU (sequence) | **0.8961** | 0.0737 | 0.8073 | 0.1238 |
| FT-Transformer | 0.8145 | 0.0833 | **0.9197** | **0.0603** |
| T-learner (uplift) | *failed to fit* | — | Qini **1.1296** | — |

**THE MOST IMPORTANT FINDING IS THE INSTABILITY, NOT THE WINNER.** The GRU won
run A; the FT-Transformer won run B; the ranking of all three reordered
completely between two regenerations of the same distribution. At n=300 with
~18% base rate — roughly 55 positive cases, ~16 in the test split — the
differences between these architectures are **not distinguishable from noise**.

So the honest conclusion is not "the sequence model beats trees" or the
reverse. It is: **this dataset cannot support any claim about which
architecture is better.** Anyone quoting a single run of this table as evidence
for one architecture is over-reading it. A defensible comparison needs
thousands of customers and repeated seeds with confidence intervals.

What the runs *do* establish: the pipeline trains, calibrates, evaluates and
registers four model families reproducibly, and the honest-reporting machinery
works — including printing a result that contradicts the fashionable answer.

### 6.6 The uplift T-learner needed a real control arm
Run A failed outright: **297 treated vs 3 control.** The synthetic
"randomized-treatment log" was not randomized — offer exposure was rolled per
*purchase*, so a customer with 20 purchases was treated with ~99.9% probability
and essentially everyone counted as treated. Uplift is a *difference* between
two arms; with no control arm there is nothing to difference.

Fixed by deciding treatment **once per customer** (60/40), giving 170/130 and a
Qini of 1.1296 in run B. Reported with the same caveat as above: directional on
this sample size.

## 7. Metrics, and why these ones

| Metric | Why it is here |
|---|---|
| **PR-AUC** | The headline. Churn is imbalanced; ROC-AUC flatters on imbalanced data |
| **Brier score** | Calibration. The optimizer *multiplies* probability by customer value, so an overconfident model systematically overspends. Calibration matters more than ranking here |
| **ROC-AUC** | Reported for comparability, read second |
| **Precision / recall @ 0.5** | Operational meaning at the acting threshold |
| **Confusion matrix** | Absolute counts, so a good-looking rate on 12 customers is visible as such |
| **Qini / AUUC** | **Uplift only.** See below |

### Uplift is not judged by outcome AUC
A T-learner can predict outcomes almost perfectly and rank *uplift* terribly,
because uplift is a **difference** of two predictions and their errors need not
cancel. The correct measure is the Qini coefficient on a holdout, implemented in
`uplift.qini_curve()` with the treated/control size correction
(`resp_c × N_t/N_c`) — without which a larger treatment arm looks better
regardless of model quality.

A **negative** Qini is reported as-is: it means targeting the top decile would be
worse than targeting at random, which is a finding, not a bug to hide.

## 6.7 Purchase timing is now drawn from the real dataset

Customer purchase dates originally came from a bare `gauss(gap_days, sigma)`
draw. Statistically tidy, and blind to the business: the generated population
had no weekday rhythm, no seasonality and no store-level trend, because none of
those exist in a gaussian. Measured, the generated weekday profile was flat
(13.8-14.8%) against a real profile spanning 11.3% Monday to 17.0% Sunday.

The gap process still PROPOSES each date - that cadence is the churn signal the
model must learn, and sampling dates straight from the demand curve would give
every customer one shared arrival process and destroy it. Real demand only
NUDGES the proposal, choosing among neighbouring days weighted by that store's
actual daily volume from `sales_historical`.

| Generator | Correlation with real weekday profile | Mean abs deviation |
|---|---|---|
| Gaussian (flat) | ~0.00 | 1.51 pts |
| Forward-slide (first attempt) | +0.657 | 1.36 pts |
| **Symmetric window (shipped)** | **+0.980** | **0.54 pts** |

The middle row is kept deliberately. Sliding a rejected day only FORWARD drained
mass off the weekly trough onto its successor and invented a +2.0-point Tuesday
surplus that exists in no real store. A symmetric window has no preferred
direction. The artefact was found by measuring against the real profile, not by
inspection - which is the argument for measuring generator output at all.

**Cadence survived**, which was the binding constraint: mean interpurchase gap
still separates cleanly by archetype (loyal_frequent 5.5d -> declining 13.5d ->
seasonal 25.1d -> lapsed 37.1d), with volatility tracking it. The persuadable
middle improved from 80 to 96 of 300.

Normalisation is per-store against that store's own 95th percentile. Store
volumes here differ by roughly an order of magnitude, so a global scale would
pin smaller stores near the floor and effectively exclude them; p95 rather than
the max stops one freak trading day flattening the year.

**Still synthetic.** This imports *when the business is busy* into the customer
layer. It does not make the customers real - `train.csv` is
`date,store,item,sales` with no customer column, so customer-level churn cannot
be derived from it, only layered on top of it.

## 6.8 A third reshuffle, and a negative Qini

Retraining after this change produced a THIRD different winner (LightGBM;
earlier runs gave GRU then FT-Transformer), and the uplift Qini swung from
**+1.1296 to -3.80** - from informative to actively anti-informative.

This is not evidence that demand-weighted timing harmed the models. It is
further evidence for the instability in the results table above: at n=300 with
~16 positives in the test split, none of these metrics are stable enough to
support a claim in either direction. A negative Qini is reported rather than
suppressed precisely because suppressing it would leave the impression the
uplift model is dependable. It is not, at this sample size.

## 7.1 The rule tier was bimodal, and that broke targeting

Measured on 300 live customers, the uncalibrated rule scorer put **195 in the
bottom two deciles and 48 in the top, leaving only 27 across the entire 30–80%
middle.**

That is not merely an ugly histogram — it is functionally fatal for this
product. Uplift peaks at p ≈ 0.5 and vanishes at both extremes, so a bimodal
risk score starves the persuadable middle the campaign exists to reach. The
optimizer correctly refused almost everyone and the engine did nothing.

Fixed with **temperature scaling** (divide the deviation from the base-rate
anchor by 2.4). Hand-set weights carry no claim to calibration, so this is
honest rather than a fudge: it is a *monotone* transform, so every ranking the
audience builder depends on is unchanged, while the probabilities the optimizer
multiplies by are pulled back toward plausible base rates.

Result: the persuadable middle went from **27 to 80 customers** and the
saturated top decile disappeared. The band thresholds were re-cut to match
(0.65/0.45/0.28) — the old 0.75 `critical` cut left that band permanently
empty, and a band nobody can enter is worse than no band, because an operator
reads "0 critical" as good news rather than as a broken scale.

## 8. The always-available fallback tier

If no trained artifact is registered — a fresh clone, an unmounted volume, a
corrupted pickle — scoring falls back to a **deterministic rule-based scorer**
(`churn.rule_based_score`). This is a requirement, not a stub: the system must
never hard-depend on a trained model being present and loadable.

The rule tier is transparent (hand-set weights from retail domain reasoning,
inspectable line by line), monotone in the correct directions, and emits the same
reason codes the trained model does, so the UI is identical either way. Its most
important property: **recency is judged against the customer's own cadence**, not
an absolute threshold — 30 days quiet means nothing for a quarterly shopper and
everything for a weekly one.

It is registered as a real `flywheel_model_versions` row (`algorithm='rule_based'`,
`artifact_path=NULL`), so every prediction — including fallback predictions —
references a version and the Decision Trace can always answer "which model said
this?".

## 9. Reproducibility

- Fixed seed (42) across `random`, `numpy` and `torch`.
- Feature/outcome windows stored on every `flywheel_model_versions` row.
- Exact feature list stored as JSON alongside the metrics.
- Training command: `python scripts/flywheel_train.py --tenant 1 --models all`
- The cutoff defaults to `today − outcome_window`, so labels are always
  observable — a naive `today` cutoff would label every customer "not yet
  churned" and silently train on nothing.

Every **decision** is separately reproducible: `flywheel_decisions` stores each EIV
term, and `GET /api/flywheel/decisions/{id}` recomputes the total from the stored
terms and reports whether it still matches.

## 10. Known limitations

1. **Synthetic data.** The generative process is our own, so the models are, in
   part, recovering assumptions we encoded. Metrics are not transferable.
2. **Uplift ground truth is weak.** Treatment assignment in the synthetic log is
   correlated with archetype rather than perfectly randomized, so Qini is
   directional at best.
3. **Small samples.** With ~600 customers the deep models are data-starved; the
   comparison would need a far larger sample to support a general claim.
4. **The GRU and FT-Transformer are not served.** They are registered and
   compared, but only sklearn-compatible artifacts are loaded at request time —
   serving a torch model would put the model class in the request path.
5. **Cost fallback.** Where `item_costs` has no row, unit cost is assumed at 70%
   of price. This is recorded on the decision so a reader knows margin was
   estimated rather than known.
6. **Measurement window is fixed** at 60 days and must match the churn label's
   outcome window, or the campaign is measured against a different question than
   the model was trained on.

## 11. Intended use

A demonstration of a production-*shaped* closed-loop retention system: how
churn, uplift, pricing, inventory, procurement, budget, approval, execution and
causal measurement fit together safely. **Not** a production churn predictor, and
not a source of real commercial advice.
