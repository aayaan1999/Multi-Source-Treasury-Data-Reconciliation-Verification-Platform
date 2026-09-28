"""Ask a Question (specs/ask-a-question.md). The model server is always faked here: these tests cover
everything around the model - extraction, the merge rules that catch a wrong model answer, the
approved queries, clarify / unsupported, audit, export and the limits. scripts/eval_ask.py measures
the real model against the same golden questions."""
import io
import json
import pathlib
from datetime import date

import pytest
from openpyxl import load_workbook

from app.ask import llm, service, vocab
from app.ask.extract import extract
from app.routers import ask as ask_router

API = "/api/v1"
GOLDEN = json.loads((pathlib.Path(__file__).parent / "ask_questions.json").read_text(encoding="utf-8"))
TODAY = date.fromisoformat(GOLDEN["today"])
STRICT = ("countries", "regions", "branches", "segments", "products", "stages", "tables", "date_from", "date_to", "top_n")


def ideal_model(case: dict) -> dict:
    """What a perfect model would answer: the expected entry and metric, nothing else."""
    if case["status"] == "unsupported":
        return {"query": "unsupported", "metric": None, "dimension": None, "sort": None}
    return {"query": case["query"], "metric": case.get("filters", {}).get("metric"), "dimension": None, "sort": None}


@pytest.fixture
def golden_names(monkeypatch):
    monkeypatch.setattr(vocab, "names", lambda: GOLDEN["names"])


def check(result: dict, case: dict) -> None:
    assert result["status"] == case["status"], result
    if case["status"] == "unsupported":
        return
    assert result["query"] == case["query"]
    if case["status"] == "answer":
        got, want = result["filters"], case["filters"]
        for key, value in want.items():
            assert (sorted(got.get(key) or []) if isinstance(value, list) else got.get(key)) == \
                   (sorted(value) if isinstance(value, list) else value), (key, got)
        for key in STRICT:
            if key not in want:
                assert key not in got, f"{key} was not in the question but came out as {got[key]}"


@pytest.mark.parametrize("case", GOLDEN["cases"], ids=[c["q"] for c in GOLDEN["cases"]])
def test_golden_questions_with_a_perfect_model(case, golden_names):
    check(service.merge(ideal_model(case), extract(case["q"], TODAY, GOLDEN["names"])), case)


# ---- a wrong model answer is caught, never shown (section 6.3) -----------------------------------------
def merge(question, model):
    return service.merge({"metric": None, "dimension": None, "sort": None, **model}, extract(question, TODAY, GOLDEN["names"]))


def test_a_country_the_model_invents_is_dropped(golden_names):
    result = merge("NPL ratio by country", {"query": "country_breakdown", "metric": "npl_ratio"})
    assert "countries" not in result["filters"]     # the 3B model added "KSA" to 5 of 8 questions in the probe


def test_the_text_decides_the_metric_when_it_names_one(golden_names):
    assert merge("top 5 branches by profit", {"query": "branch_ranking", "metric": "deposits"})["filters"]["metric"] == "profit"


def test_the_model_cannot_set_dates_or_top_n(golden_names):
    result = merge("IFRS 9 staging as of 2026-09-25", {"query": "ifrs9_stages", "metric": "npl_ratio"})
    assert result["filters"] == {"date_from": "2026-09-25", "date_to": "2026-09-25", "period_label": "25 Sep 2026"}


def test_an_unknown_query_or_metric_from_the_model_is_not_used(golden_names):
    assert merge("anything", {"query": "DROP TABLE loans"})["status"] == "unsupported"
    assert merge("show me all the KPIs", {"query": "kpi_value", "metric": "bogus"})["filters"] == {}


def test_a_kpi_asked_for_one_country_becomes_the_country_breakdown(golden_names):
    result = merge("NPL ratio in Lebanon", {"query": "kpi_value", "metric": "npl_ratio"})
    assert result["query"] == "country_breakdown" and result["filters"]["countries"] == ["Lebanon"]


def test_a_place_the_question_type_cannot_use_is_reported_as_ignored(golden_names):
    result = merge("IFRS 9 staging in Lebanon", {"query": "ifrs9_stages"})
    assert result["query"] == "ifrs9_stages" and result["ignored"] == ["Lebanon"]


# Each of these is a wrong table the real model produced in the first evaluation (2026-09-28).
@pytest.mark.parametrize("question, model_said, expected", [
    ("NPL ratio by country", "loan_breakdown", "country_breakdown"),
    ("NPL ratio in Lebanon", "loan_breakdown", "country_breakdown"),
    ("deposits in Saudi", "segment_performance", "country_breakdown"),
    ("LCR today", "limit_breaches", "kpi_value"),
    ("total assets as of 25 Sep", "top_exposures", "kpi_value"),
    ("NPL over the last 7 days", "loan_ageing", "kpi_value"),
    ("stage 3 loans", "loan_ageing", "ifrs9_stages"),
    ("NPL ratio by loan product", "loan_breakdown", "product_performance"),
    ("IFRS 9 staging", "unsupported", "ifrs9_stages"),
    ("how many records were rejected", "unsupported", "data_quality"),
])
def test_the_question_words_decide_the_type_over_the_model(question, model_said, expected, golden_names):
    result = merge(question, {"query": model_said})
    assert result["query"] == expected and result["overridden"] is True


# Gaps found by the held-out questions (backend/tests/ask_questions_holdout.json), 2026-09-28.
def test_a_count_before_what_is_listed_is_a_top_n(golden_names):
    result = merge("Which 3 branches have the lowest profit?", {"query": "branch_ranking"})
    assert result["filters"] == {"metric": "profit", "top_n": 3, "order": "asc"}


def test_most_profitable_means_profit(golden_names):
    assert merge("most profitable branch", {"query": "branch_ranking"})["filters"] == {"metric": "profit", "order": "desc"}


def test_a_request_to_change_anything_is_refused_whatever_the_model_says(golden_names):
    for question in ("delete all the loans", "please send the NPL report to the regulator", "update the CAR limit"):
        result = merge(question, {"query": "loan_breakdown", "metric": "loans"})
        assert result["status"] == "unsupported" and "only reads" in result["reason"]


def test_the_model_does_not_add_a_measure_or_a_split_to_an_english_question(golden_names):
    assert merge("show me all the KPIs", {"query": "kpi_value", "metric": "car"})["filters"] == {}
    assert merge("loan breakdown", {"query": "loan_breakdown", "dimension": "product"})["status"] == "clarify"
    assert merge("cost to income in Beirut branches", {"query": "branch_ranking", "sort": "best"})["filters"]["order"] == "desc"


def test_for_a_question_the_word_lists_cant_read_the_model_may_name_the_measure(golden_names):
    arabic = "ما هي نسبة القروض المتعثرة حسب الدولة"
    assert merge(arabic, {"query": "country_breakdown", "metric": "npl_ratio"})["filters"]["metric"] == "npl_ratio"
    # ...but its wrong guess of the type still can't produce a table: loan_breakdown needs a split the text doesn't give
    assert merge(arabic, {"query": "loan_breakdown", "metric": "npl_ratio"})["status"] == "clarify"


def test_worst_means_highest_for_cost_to_income_and_lowest_for_profit(golden_names):
    assert merge("worst branches by cost to income", {"query": "branch_ranking"})["filters"]["order"] == "desc"
    assert merge("worst branches by profit", {"query": "branch_ranking"})["filters"]["order"] == "asc"


# ---- the API against the test database -------------------------------------------------------------
@pytest.fixture
def model(monkeypatch):
    """A fake model: set `answer` to what it should return; `calls` counts questions sent to it."""
    fake = {"answer": {"query": "unsupported"}, "calls": 0}

    def classify(question):
        fake["calls"] += 1
        if isinstance(fake["answer"], Exception):
            raise fake["answer"]
        return {"metric": None, "dimension": None, "sort": None, **fake["answer"]}

    monkeypatch.setattr(llm, "classify", classify)
    monkeypatch.setattr(llm, "model_name", lambda: "fake-model")
    vocab.clear_cache()
    ask_router._recent.clear()
    return fake


@pytest.fixture
def extra_rows(db):
    """Country, data-quality and breach rows only these tests need; removed afterwards so other test
    files still see an empty country table."""
    d = date(2026, 9, 21)
    db.executemany("INSERT INTO country_performance_summary (calculation_date, country, customer_count, deposits_usd, loans_usd, "
                   "npl_loans_usd, npl_ratio_pct) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                   [(d, "Lebanon", 3, 300.0, 900.0, 90.0, 10.0), (d, "Saudi Arabia", 2, 500.0, 400.0, 8.0, 2.0)])
    db.execute("INSERT INTO exception_summary_by_table VALUES (%s, 'transactions', 100, 4, 4.0), (%s, 'loans', 10, 0, 0.0)", (d, d))
    db.execute("INSERT INTO breaches (limit_id, actual_value, level, due_date) SELECT limit_id, 9.5, 'REGULATORY', %s "
               "FROM limits WHERE metric_name = 'capital_adequacy_ratio' RETURNING breach_id", (d,))
    breach_id = db.fetchone()[0]
    yield
    db.execute("DELETE FROM country_performance_summary")
    db.execute("DELETE FROM exception_summary_by_table")
    db.execute("DELETE FROM breaches WHERE breach_id = %s", (breach_id,))


def ask(client, auth, **body):
    return client.post(f"{API}/ask", headers=auth, json=body)


def test_a_question_returns_the_table_with_what_was_understood_and_is_audited(client, auth, db, model):
    model["answer"] = {"query": "branch_ranking", "metric": "profit"}
    body = ask(client, auth, question="top 1 branch by profit").json()
    assert body["status"] == "answer"
    assert [(r["branch_name"], r["profit_usd"]) for r in body["rows"]] == [("Riyadh", 90.0)]
    assert body["source"] == {"table": "branch_performance_summary", "as_of": "2026-09-21"}
    chips = {c["key"]: c["text"] for c in body["understood"]["chips"]}
    assert chips["metric"] == "Profit" and chips["top_n"] == "Top 1" and chips["order"] == "Highest first"
    db.execute("SELECT action, object_id, new_value FROM audit_log WHERE log_id = %s", (body["audit_id"],))
    action, object_id, details = db.fetchone()
    details = json.loads(details)
    assert (action, object_id) == ("ASK_QUESTION", "branch_ranking")
    assert details["question"] == "top 1 branch by profit" and details["model"]["metric"] == "profit" and details["rows"] == 1


def test_a_country_question(client, auth, model, extra_rows):
    model["answer"] = {"query": "country_breakdown", "metric": "npl_ratio"}
    body = ask(client, auth, question="NPL ratio in KSA").json()
    assert [(r["country"], r["npl_ratio_pct"]) for r in body["rows"]] == [("Saudi Arabia", 2.0)]


def test_branches_filtered_by_country(client, auth, model):
    model["answer"] = {"query": "branch_ranking", "metric": "profit"}
    assert [r["branch_name"] for r in ask(client, auth, question="profit of branches in Lebanon").json()["rows"]] == ["Beirut"]


def test_a_missing_measure_is_asked_back_and_the_button_runs_without_the_model(client, auth, model):
    model["answer"] = {"query": "branch_ranking"}
    body = ask(client, auth, question="rank the branches").json()
    assert body["status"] == "clarify" and "Which measure" in body["clarify"]["question"]
    profit = next(o for o in body["clarify"]["options"] if o["label"] == "Profit")
    calls = model["calls"]
    answer = ask(client, auth, question="rank the branches", query=profit["query"], filters=profit["filters"]).json()
    assert answer["status"] == "answer" and answer["rows"][0]["branch_name"] == "Riyadh"
    assert model["calls"] == calls


def test_a_period_with_no_data_says_so_instead_of_showing_another_date(client, auth, model):
    model["answer"] = {"query": "ifrs9_stages"}
    body = ask(client, auth, question="IFRS 9 staging in August 2026").json()
    assert body["status"] == "clarify"
    assert body["clarify"]["question"].startswith("No data for August 2026") and "21 Sep 2026" in body["clarify"]["question"]
    latest = ask(client, auth, question="IFRS 9 staging", **{k: body["clarify"]["options"][0][k] for k in ("query", "filters")}).json()
    assert [r["stage"] for r in latest["rows"]] == [1, 2, 3]


def test_a_kpi_trend_over_a_range(client, auth, model):
    body = ask(client, auth, question="", query="kpi_value",
               filters={"metric": "car", "date_from": "2026-09-20", "date_to": "2026-09-21"}).json()
    assert [(r["calculation_date"], r["car_pct"]) for r in body["rows"]] == [("2026-09-20", 12.0), ("2026-09-21", 13.5)]


def test_all_kpis_carry_the_placeholder_note(client, auth, model):
    model["answer"] = {"query": "kpi_value"}
    body = ask(client, auth, question="show me the KPIs").json()
    assert {r["kpi"] for r in body["rows"]} >= {"Capital adequacy ratio (CAR)", "Net interest margin (NIM)"}
    assert any("placeholder" in n for n in body["notes"])


def test_data_quality_and_breaches(client, auth, model, extra_rows):
    body = ask(client, auth, question="", query="data_quality", filters={}).json()
    assert [r["source_table"] for r in body["rows"]] == ["transactions", "loans"]
    body = ask(client, auth, question="", query="limit_breaches", filters={"metric": "car"}).json()
    assert body["rows"][0]["level"] == "Regulatory limit" and body["rows"][0]["actual_value"] == 9.5


def test_unsupported_questions_get_examples_and_are_audited(client, auth, db, model):
    body = ask(client, auth, question="what's the weather in Dubai").json()
    assert body["status"] == "unsupported" and body["examples"]
    db.execute("SELECT object_id FROM audit_log WHERE log_id = %s", (body["audit_id"],))
    assert db.fetchone()[0] == "unsupported"


def test_the_model_being_down_is_a_clear_503_and_audited(client, auth, db, model):
    model["answer"] = llm.Unavailable("connection refused")
    r = ask(client, auth, question="NPL ratio by country")
    assert r.status_code == 503 and "isn't available" in r.json()["detail"]
    db.execute("SELECT object_id FROM audit_log WHERE action = 'ASK_QUESTION' ORDER BY log_id DESC LIMIT 1")
    assert db.fetchone()[0] == "unavailable"


def test_filters_from_the_browser_are_checked_like_model_output(client, auth, model):
    for query, filters in [("branch_ranking", {"metric": "profit; DROP TABLE loans"}),
                           ("branch_ranking", {"metric": "profit", "regions": ["x' OR '1'='1"]}),
                           ("branch_ranking", {"metric": "profit", "sql": "SELECT 1"}),
                           ("branch_ranking", {}),
                           ("kpi_value", {"date_from": "2026-09-21", "date_to": "2026-09-01"}),
                           ("no_such_query", {})]:
        assert ask(client, auth, question="", query=query, filters=filters).status_code == 422, (query, filters)


def test_limits_on_the_question(client, auth, model):
    assert ask(client, auth, question="").status_code == 422
    assert ask(client, auth, question="x" * 301).status_code == 422
    for _ in range(ask_router.RATE_LIMIT):
        assert ask(client, auth, question="tell me a joke").status_code == 200
    assert ask(client, auth, question="tell me a joke").status_code == 429


def test_export_reruns_the_query_and_describes_it(client, auth, db, model):
    r = client.post(f"{API}/ask/export", headers=auth, json={"question": "top branches by profit", "query": "branch_ranking",
                                                             "filters": {"metric": "profit", "order": "desc"}})
    assert r.status_code == 200 and "ask_branch_ranking_2026-09-21.xlsx" in r.headers["content-disposition"]
    wb = load_workbook(io.BytesIO(r.content))
    rows = list(wb.worksheets[0].values)
    assert rows[0] == ("Rank", "Branch", "Region", "Profit (USD)") and rows[1][1] == "Riyadh"
    about = dict(list(wb.worksheets[1].values)[1:])
    assert about["Question"] == "top branches by profit" and about["Source table"] == "branch_performance_summary"
    db.execute("SELECT action FROM audit_log ORDER BY log_id DESC LIMIT 1")
    assert db.fetchone()[0] == "ASK_EXPORT"


def test_the_model_client_needs_configuration_and_parses_structured_output(monkeypatch):
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    with pytest.raises(llm.Unavailable):
        llm.classify("anything")

    class Reply(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    sent = {}

    def urlopen(request, timeout):
        sent.update(url=request.full_url, body=json.loads(request.data), auth=request.headers.get("Authorization"))
        content = json.dumps({"query": "kpi_value", "metric": "car", "dimension": None, "sort": None})
        return Reply(json.dumps({"choices": [{"message": {"content": content}}]}).encode())

    monkeypatch.setenv("LLM_BASE_URL", "http://model:8000/v1/")
    monkeypatch.setenv("LLM_MODEL", "qwen2.5:3b")
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    assert llm.classify("what is our CAR")["metric"] == "car"
    assert sent["url"] == "http://model:8000/v1/chat/completions" and sent["auth"] == "Bearer k"
    assert sent["body"]["temperature"] == 0 and sent["body"]["response_format"]["type"] == "json_schema"
    assert "unsupported" in sent["body"]["response_format"]["json_schema"]["schema"]["properties"]["query"]["enum"]
