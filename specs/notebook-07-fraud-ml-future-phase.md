# Spec: Notebook 7 — ML-Based Fraud/Anomaly Scoring (FUTURE PHASE — not current scope)

**Status:** Architecture design only. **Explicitly not part of `3-WEEK-POC-PLAN.md`.** Documented
so the pipeline's design accommodates this later without rework, not because it's being built now.
**Relationship to Notebook 5:** complements, doesn't replace, `specs/notebook-05-fraud-business-rules.md`'s
threshold rules — see section 5.
**Research grounding:** see sources at the end of this file

---

## 1. Why This Is Deferred, Not Built Now

Covered in detail in this session's earlier analysis (not reproduced fully here); summary:

- **No labeled fraud data** — supervised classification needs historical fraud/non-fraud examples
  we don't have. `bank-data/transactions.csv` is 15 hand-built rows.
- **No customer-level behavioral baseline** — most of the interesting features (deviation from a
  customer's normal pattern) need weeks/months of per-customer volume this POC's data can't
  provide.
- **No device/channel telemetry** — only `channel` (Branch/ATM/Mobile/Online) exists; device
  fingerprinting isn't in the schema.
- **MLOps scope not in the current plan** — feature engineering, model registry, retraining
  cadence, drift monitoring are all new engineering surface, not a small addition.
- **Real-time expectation mismatch** — the illustrative "10 transactions in 5 minutes" pattern
  needs sub-second scoring; the entire current pipeline is nightly-batch. Section 4 below
  addresses this specifically now that research surfaced a concrete path.

Building this against synthetic/tiny sample data now would produce a demo that *looks*
sophisticated but validates nothing — worse than not having it, since it implies rigor that
doesn't exist.

## 2. When to Build It (Trigger Conditions)

- Real historical transaction volume exists (thousands+ transactions per customer segment,
  ideally with some known fraud/non-fraud ground truth, even if imperfect/self-reported)
- The deterministic rules in Notebook 5 have been running long enough to establish which patterns
  they're missing (informs feature selection — don't guess features from first principles when
  real false-negative data will tell you what matters)

## 3. Recommended Approach: Unsupervised, Not Supervised

Per this session's research: anomaly detection typically uses unsupervised learning because
anomalies don't come with predefined labels — the model learns normal patterns and flags
deviations. **Isolation Forest** is well-suited for multi-dimensional anomaly detection (at
roughly 2x the compute cost of simpler statistical methods, an acceptable tradeoff). This sidesteps
the "no labeled data" blocker in section 1 — it doesn't need fraud/non-fraud labels, just enough
normal-behavior volume to learn what "normal" looks like.

If labeled data becomes available later (e.g. from Camunda review outcomes accumulating over
time — `specs/bidirectional-sync.md`'s `review_outcomes` table is, notably, a labeled dataset in
the making), a supervised model (decision trees / gradient boosting) becomes viable and typically
outperforms unsupervised approaches once labels exist.

## 4. Batch Scoring Architecture (MLflow)

- Model trained and registered via **MLflow** (experiment tracking via autologging, model
  registry for versioning)
- Batch inference: the registered model loaded via `mlflow.pyfunc.spark_udf()`, converting it into
  a Spark UDF callable directly against `transactions_clean` — same DataFrame-native pattern as
  every other notebook in this pipeline, no separate serving infrastructure needed for batch
  scoring
- Scheduled retraining via Databricks Workflows, since fraud/anomaly patterns shift over time —
  a model trained once and never refreshed degrades
- Output: a `fraud_ml_score` column (0.0-1.0) alongside `flagged_transactions` from Notebook 5,
  not replacing it

## 5. Combining ML Score with Notebook 5's Deterministic Rules

Per the interview-framing already agreed on: **the model produces a signal, not a decision.**
Concretely:

```
Notebook 5 rules (deterministic)  +  ML anomaly score (behavioral)
                    ↓
         Combined risk assessment
                    ↓
   score/rule combination decides: Normal / Review / Potential Fraud
```

A reasonable POC-stage combination rule (illustrative, needs real tuning once data exists):
`ml_score < 0.3` AND no Notebook 5 flag → `Normal` (no task created). `ml_score ≥ 0.3` OR any
Notebook 5 flag → `Review` or `Potential Fraud` depending on score threshold, routed to Camunda
per `specs/camunda-bpmn-process-design.md`'s existing flow — **the ML score becomes another input
to `flagCategory` derivation, not a parallel system.**

## 6. The Real-Time Sub-Problem: Spark Real-Time Mode + Lakebase

For genuinely time-sensitive patterns (velocity bursts — "10 transactions in 5 minutes"), nightly
batch scoring is architecturally too slow regardless of model quality. Research surfaced a
concrete Databricks-native path for this specific sub-problem: **Spark Real-Time Mode (RTM)** —
an evolution of Structured Streaming delivering sub-300ms processing — paired with **Lakebase**
(Databricks' managed, serverless Postgres, used here as a low-latency feature store) for
maintaining per-account rolling state (e.g. "transactions in the last 5 minutes for this account")
without unbounded memory growth. Demonstrated end-to-end latency in the source material: P50 under
40ms, P99 215-392ms.

**This is separate, additional infrastructure** (a Kafka or equivalent ingestion path feeding RTM,
plus Lakebase) — not something the existing batch pipeline gains for free, and not part of this
spec's current-phase scope either. Documenting it here because it's the concrete answer to "how
would you actually do the real-time part" if/when that becomes a real requirement, not a
recommendation to build it now.

**Caution**: "Lakebase" is Databricks' own managed Postgres offering — don't conflate it with the
project's existing application-layer PostgreSQL (`PLATFORM-BUILD-PLAN.md` Phase 1). If this
real-time path is ever built, whether Lakebase *replaces* or sits *alongside* the existing Postgres
is an infrastructure decision requiring explicit confirmation, not an assumption to make silently.

## 7. Explainability (Regulatory Concern, Not Optional If Built)

A raw anomaly score is much harder to explain to an auditor than a deterministic rule
(`LARGE_AMOUNT: 60,000 > 50,000`). If/when this is built, it needs feature-attribution output
(e.g. SHAP values) alongside the score, in the same spirit as Screen 3's drill-to-source
philosophy already central to this project — "the model flagged this because X, Y, Z contributed
most" needs to be answerable, not just "the model said 0.96."

## 8. Non-Goals (for this future-phase design, not just the current POC)

- No claim that AI directly decides fraud/not-fraud — explicitly a scored signal feeding
  deterministic combination logic and human review, per the agreed framing
- No real-time path built without an explicit trigger (section 6) — batch scoring is the default
  even once this phase starts, real-time is an escalation for a specific proven need

---

**Research sources** (grounding this spec, fetched during this session):
- [Detecting Financial Fraud at Scale with Decision Trees and MLflow on Databricks](https://www.databricks.com/blog/2019/05/02/detecting-financial-fraud-at-scale-with-decision-trees-and-mlflow-on-databricks.html)
- [Azure Databricks data science and ML capabilities - Microsoft Learn](https://learn.microsoft.com/en-us/azure/databricks/machine-learning/concepts/ml-capabilities)
- [How to Build Real-Time Fraud Detection using Spark Real-Time Mode and Lakebase | Databricks Blog](https://www.databricks.com/blog/how-build-real-time-fraud-detection-using-spark-real-time-mode-and-lakebase)
- [Unsupervised Learning in Production: Clustering for Customer Segmentation & Anomaly Detection — The 2026 Playbook](https://www.opodab.com/2026/09/unsupervised-learning-production-clustering-anomaly-detection.html)
