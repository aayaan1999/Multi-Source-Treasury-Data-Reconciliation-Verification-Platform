# KPI explanations: why a KPI looks the way it does

**Status:** Built 2026-09-30 — `backend/app/kpi_explain.py`, `GET /api/v1/kpi-summary/{key}/explanation`,
`frontend/src/kpi/KpiExplanation.jsx` ("Why it looks like this" on each KPI's detail page). Backend (pytest,
fake model) and frontend (vitest) tests pass; run live against Neon and Ollama `qwen2.5:3b` on the laptop.
Not yet checked in a browser by a user.

## 1. What was asked, and what the docs say

Asked: a better explanation of why each KPI trend looks the way it does, using the local model if possible.
No spec asked for AI-written explanations. The source-of-truth doc's Screen 1 wants "an alert strip... plain
sentences, not codes", and `specs/ask-a-question.md` lists "a model-written summary sentence" under
*Not in v1*: "every number in the sentence must be checked against the table before it is shown". This
feature follows that rule.

## 2. How it works

1. **Code works out the facts** (`facts()`): the value on the latest calculation date; the move since the
   previous calculation and whether it's better or worse for this KPI; the trend across the loaded history
   (start, overall move, low and high with dates); where it stands against its limits (within, early-warning
   zone, breaching the bank's limit, breaching the regulatory minimum) and when it crossed the limit; and,
   for CAR and LCR only, which part moved (capital and risk-weighted assets month on month; liquid assets
   and 30-day outflows day on day). The other KPIs' source tables keep only today's figures, so the
   explanation says the data can't show which part moved — it never guesses.
2. **Code writes a correct explanation** from those facts (`rules_text()`). Always available.
3. **The local model rewords it** to read more easily (`model_text()`), through the same OpenAI-compatible
   server as Ask a question (`LLM_BASE_URL`, `LLM_MODEL`). Its rewording is **thrown away** unless it:
   - uses only numbers in the correct text, and keeps the key ones (the value, the limit, what moved);
   - keeps each number's unit ("0.02 points" must not become "0.02%");
   - only calls a real start and end a move ("from X to Y": the period's start or the previous calculation to
     now; the low and high only when it says "ranging" or "between"), in the right direction;
   - adds no claim the text doesn't make (causes, forecasts, advice, "last week", "regulatory"...);
   - stays under 110 words.
4. The page shows the correct text at once (`use_model=false`) and swaps in the rewording only if it passes,
   labelled "Reworded by the local AI model (…), checked against the data", with the exact wording a click
   away. A refused rewording shows "Not reworded: <why>".
5. The outcome is kept per KPI and calculation date (once per pipeline run); an unreachable model is tried
   again after 5 minutes.

## 3. Findings from the live run (2026-09-30, qwen2.5:3b on CPU)

- Asked to explain from the raw facts, the model wrote numbers that passed a number-only check but got the
  meaning wrong (a limit called "the regulatory minimum", a fall described as a rise, "last year's" limit
  invented). So the model now only rewords a correct text, and the checks above were added.
- With every check, 2 of 8 KPIs were reworded in the final run; 6 fell back to the exact text, each for a
  real error (a low-to-start pair called a move, "points" changed to "%", key figures dropped, dates
  rewritten as other numbers). Nothing wrong reached the page.
- Each rewording takes 9–45 s on the laptop CPU.

**Recommendation:** keep the code-built text as the main explanation. Expect a larger model on the bank's
vLLM server to pass the checks far more often; measure it before relying on it.

## 4. Open items

1. The checks can't catch every change of meaning (e.g. a sentence that swaps "better" and "worse" without
   numbers); the exact wording is always one click away for that reason.
2. Component history exists only for CAR and LCR; historized loans/accounts/branches tables would let the
   other KPIs say what moved.
3. Limits are placeholders (`limits.is_placeholder`); the explanation inherits them.
