# Spec: Real-Time FX Rate Fetching (Inline, Not a Data Source)

**Status:** Spec only — not yet implemented
**New for:** the "real-time FX rates" requirement added to `3-WEEK-POC-PLAN.md`
**Corrected:** an earlier version of this spec designed FX as a separately-scheduled polling job
writing to a table (`fx_rates_live`), read like any other ingested data source. **That's wrong.**
The actual requirement: currency conversion logic calls a live FX API directly, at the moment a
notebook runs, not from a pre-populated table. FX is a **live utility call**, not a data source.
**Research grounding:** see sources at the end of this file

---

## 1. Objective

Every place this pipeline converts an amount to USD (Notebook 3's KPI calculations, Notebook 6's
portfolio/branch/scenario aggregates) should use the **actual current rate at the moment the
notebook runs**, fetched live, not a rate read from a table that was populated ahead of time —
whether that table was a static CSV or a periodically-polled Delta table.

## 2. What Changes From the Original (Static CSV) Design

- **`fx_rates.csv`, `raw_fx_rates`, `fx_rates_clean` are no longer the source for live
  conversions.** Notebooks 1-2's ingestion of a static FX file becomes unnecessary for the
  conversion use case — Notebook 1 doesn't need to read an FX CSV at all if nothing consumes it
  for actual conversions. (Keep this in mind when implementing: don't leave the old ingestion path
  half-wired to a table nothing reads from any more.)
- **No `fx_rates_live` polling table.** The earlier design's 5-15-minute scheduled job is removed
  — there's nothing to schedule, because nothing is being pre-fetched and stored for later lookup.
- **Notebook 2's `DUPLICATE_RATE`/`INVALID_RATE` checks on `fx_rates` become moot** — there's no
  more `fx_rates` table being validated as a data-quality subject, since rates aren't ingested as
  data any more, they're fetched inline. Revert the change made to
  `specs/notebook-02-bank-data-quality.md`'s `fx_rates` row (section 5 below covers this
  explicitly).

## 3. Architecture: A Shared Live-Rate Utility Function

A small utility module (e.g. `fx_utils.py`, importable by any notebook), providing:

```python
def get_live_rate(currency_pair: str) -> tuple[float, str]:
    """Calls the live FX API for currency_pair, returns (rate, fetched_at_iso_timestamp).
    Raises if the API call fails — callers must decide how to handle that (see section 4)."""
```

Called directly, inline, wherever Notebook 3/6 currently reads "the most recent valid rate from
`fx_rates_clean`" — replace that table lookup with a call to `get_live_rate(currency_pair)`.

- **API selection**: same candidates as before — ExchangeRate-API or Open Exchange Rates (verify
  actual USD/EUR/LBP/SAR/QAR coverage before committing; free ECB-only feeds like Frankfurter
  don't cover LBP/QAR)
- **Credentials**: API key in a Databricks secret scope, same pattern as every other credential
  in this project
- **Latency honesty, unchanged from the prior version**: even a live API call gets you a rate
  that's typically 1-minute-to-1-hour fresh versus true interbank tick data — "the actual current
  rate as of right now" is the accurate claim, not "trading-desk real-time"

## 4. Failure Handling (new consideration this design introduces)

A pre-populated table never fails at read time — worst case it's stale. **A live API call can
fail** (network issue, rate limit, API downtime) at the exact moment a notebook needs it. This
needs an explicit decision, not an assumption:

- **Recommended for this POC**: if the live call fails, the notebook run fails loudly for that
  conversion step (don't silently fall back to a stale/hardcoded rate and present it as live —
  that would misrepresent what the number actually is)
- Retry with backoff (e.g. 2-3 attempts) before failing, to absorb transient network blips
- Log every fetch attempt (success or failure) — see section 5

## 5. Auditability: Log What Was Actually Used, After the Fact

Even though FX is no longer a pre-populated source table, **the rate used for each calculation
still needs to be recorded** — a regulator asking "what rate did you use for this conversion"
needs an answer. This is a byproduct log, not a source table to read from:

`fx_rate_usage_log(notebook_run_id, currency_pair, rate, fetched_at, used_in_calculation)` — one
row written *after* each live fetch, capturing what was actually returned and where it was used
(e.g. `"NPL_ratio_calc"`, `"cost_to_income_calc"`). This preserves the audit-trail principle from
the original design without reintroducing a pre-populated lookup table.

## 6. Acceptance Criteria

- [x] Written: `notebooks/fx_utils.py` (`get_live_rate`, `log_fx_usage`,
      `get_live_rate_and_log`). **Not yet run against a live cluster** — none of the below is
      verified by an actual call.
- [x]/[ ] Notebook 3 and Notebook 6 call `get_live_rate()` inline for every USD conversion, not a
      table lookup — implemented in both (`03_kpi_summary.py`, `06_portfolio_branch_scenario_snapshot.py`);
      Notebook 5 also adopted this for its one conversion site, beyond what this criterion asked
      for. Not yet verified against a live cluster.
- [ ] Confirm the chosen FX API's currency coverage includes USD, EUR, LBP, SAR, QAR specifically
      — **not verified**. Implementation picked `open.er-api.com` (free, keyless) over
      ExchangeRate-API/Open Exchange Rates specifically to avoid a manual signup step, but its
      actual LBP/SAR/QAR coverage has not been checked against a live response.
- [x]/[ ] A live API failure causes a loud, explicit error for that calculation step —
      implemented via retry-with-backoff (3 attempts) then `raise RuntimeError`, no silent
      fallback. Not yet verified against an actual failure.
- [x]/[ ] `fx_rate_usage_log` captures every fetch — implemented as an append-only write in
      `log_fx_usage()`, called from every conversion site in Notebooks 3/5/6. Not yet verified.
- [ ] `specs/notebook-02-bank-data-quality.md`'s `fx_rates` DQ row is reverted/removed to reflect
      that `fx_rates` is no longer an ingested data-quality subject (see section 2) — **not done**.
      Notebook 1/2 still ingest and validate `fx_rates.csv` unchanged; this spec's section 2 says
      that path becomes unnecessary once live conversion lands, but the actual removal from
      Notebooks 1-2 hasn't been made, to avoid touching working, already-run code as a side effect
      of this work. Revisit deliberately, not as a byproduct.

## 7. Non-Goals

- No pre-populated FX table of any kind (this is the core correction from the original design)
- No true tick-by-tick/institutional feed
- No multi-provider failover (single API source; document as a production follow-up if needed)

---

**Research sources** (grounding this spec, fetched during this session):
- [10 Best Currency Exchange API Options for Developers in 2026](https://currencyfreaks.com/blog/10-Best-Currency-Exchange-API)
- [ExchangeRate-API - Free & Pro Currency Converter API](https://www.exchangerate-api.com/)
- [Open Exchange Rates](https://openexchangerates.org/)
