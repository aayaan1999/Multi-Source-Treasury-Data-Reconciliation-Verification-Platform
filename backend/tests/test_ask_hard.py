"""Questions Ask a Question can't answer as asked (specs/ask-a-question.md section 6.7).

Each case in ask_questions_hard.json replays what the real model answered when probed, and checks the
panel now either explains why it can't answer (no table) or answers with a notice of what wasn't
applied - never a silent table that answers a different question."""
import json
import pathlib
from datetime import date

import pytest

from app.ask import service, vocab
from app.ask.extract import extract

HERE = pathlib.Path(__file__).parent
HARD = json.loads((HERE / "ask_questions_hard.json").read_text(encoding="utf-8"))
NAMES = json.loads((HERE / "ask_questions.json").read_text(encoding="utf-8"))["names"]
TODAY = date.fromisoformat(HARD["today"])
PLACE_FILTERS = ("countries", "regions", "branches", "segments", "products")


@pytest.fixture(autouse=True)
def names(monkeypatch):
    monkeypatch.setattr(vocab, "names", lambda: NAMES)


def answer(case):
    return service.merge(case["model"], extract(case["q"], TODAY, NAMES))


@pytest.mark.parametrize("case", HARD["cases"], ids=[c["q"] for c in HARD["cases"]])
def test_a_hard_question_is_explained_or_answered_with_a_notice(case):
    result = answer(case)
    assert result["status"] == case["status"], result
    if case["status"] == "unsupported":
        e = result["explanation"]
        assert e["code"] == case["code"]
        assert e["title"] and e["why"] and e["how"].startswith("How this works")
        assert e["suggestions"], "an explanation always says what to ask instead"
    else:
        assert case["code"] in [n["code"] for n in result["notices"]], result["notices"]
        for key, value in case.get("filters", {}).items():
            assert result["filters"].get(key) == value, (key, result["filters"])


@pytest.mark.parametrize("case", [c for c in HARD["cases"] if c["category"] == "negation"], ids=lambda c: c["q"])
def test_an_exclusion_is_never_applied_as_a_filter(case):
    result = answer(case)
    assert "filters" not in result      # no table at all: applying "Beirut" would show exactly what was excluded
    for option in result["explanation"]["suggestions"]:
        assert not set(option.get("filters", {})) & set(PLACE_FILTERS)


def test_every_runnable_suggestion_is_a_valid_query():
    for case in HARD["cases"]:
        result = answer(case)
        for option in (result.get("explanation") or {}).get("suggestions", []):
            if "query" in option:
                service.validate(option["query"], option["filters"])        # raises on anything invalid
            else:
                assert option.get("question") or option.get("href", "").startswith("/")


def test_an_unknown_measure_is_not_read_as_part_of_it():
    # "return on assets" used to become total assets, and "Tier 1 capital ratio" the total CAR
    for question in ("what is our return on assets", "Tier 1 capital ratio"):
        assert extract(question, TODAY, NAMES).metrics in ([], ["car"])
        assert answer({"q": question, "model": {"query": "kpi_value"}})["explanation"]["code"] == "unknown_measure"


def test_a_misspelt_measure_is_read_and_the_correction_shown():
    ex = extract("cost to incme by branch", TODAY, NAMES)
    assert ex.metrics == ["cost_to_income"] and ex.typos == [("cost to incme", "cost to income")]
    assert extract("net profits by branch", TODAY, NAMES).typos == []         # a plural isn't a typo


def test_the_explanation_names_what_it_does_know():
    e = answer({"q": "profit at Tyre branch", "model": {"query": "branch_ranking"}})["explanation"]
    assert "Tyre" in e["why"] and "Riyadh Central" in e["why"] and "Saudi Arabia" in e["why"]
    e = answer({"q": "EBITDA by branch", "model": {"query": "branch_ranking"}})["explanation"]
    assert "“EBITDA”" in e["why"]


def test_a_threshold_puts_the_rows_that_meet_it_first():
    below = answer({"q": "branches with cost to income below 50%", "model": {"query": "branch_ranking"}})
    above = answer({"q": "branches with profit above 1 million", "model": {"query": "branch_ranking"}})
    assert below["filters"]["order"] == "asc" and above["filters"]["order"] == "desc"


def test_words_that_look_like_problems_in_normal_questions_are_not_flagged():
    for question in ("NPL over the last 7 days", "compare Lebanon and Qatar loans", "most profitable branch",
                     "profit at Riyad central branch", "which branch has the most staff", "net income q3 2026"):
        codes = [p["code"] for p in extract(question, TODAY, NAMES).problems]
        assert codes == [], (question, codes)


def test_two_checks_do_not_read_across_each_other():
    # Found by the live held-out run: the threshold used up "more than 90", and the split check then read
    # "by ... days" as "split by day" and refused a question it can answer.
    result = answer({"q": "loans overdue by more than 90 days", "model": {"query": "loan_ageing"}})
    assert result["status"] == "answer" and [n["code"] for n in result["notices"]] == ["threshold"]
