"""KPI explanations (specs/kpi-explanations.md): code works out the facts and writes a correct explanation;
the local model may only reword it, and a rewording is thrown away if it adds a number, drops a key one,
changes a unit, pairs two numbers as a move the data doesn't show, or adds a claim. The model server is
always faked here; scripts/eval_kpi_explain.py (or a live run) covers the real one."""
import pytest

from app import kpi_explain
from app.ask import llm

API = "/api/v1"
CAR_RULES = ("The capital ratio (CAR) is 13.50% on 21 Sep 2026, 1.00 points above the 12.50% limit: inside the "
             "early-warning zone (warning level 15.00%). It went up 1.50 points since 20 Sep 2026 (12.00%), which is better. "
             "From Jun 2026 to Jul 2026, capital (tier 1 + tier 2) rose by USD 4.0 million (1.7%), which helped the ratio; "
             "risk-weighted assets rose by USD 35.0 million (1.8%), which pulled the ratio down.")
GOOD = ("The capital ratio is 13.50% on 21 Sep 2026, 1.00 points above its 12.50% limit, in the early-warning zone "
        "below 15.00%. It rose 1.50 points from 12.00% on 20 Sep 2026, which is better. From Jun 2026 to Jul 2026 capital "
        "rose by USD 4.0 million, which helped, while risk-weighted assets rose by USD 35.0 million, which pulled it down.")


@pytest.fixture
def model(monkeypatch):
    """A fake model: `reply` is what it answers (an exception to fail); `calls` counts requests."""
    fake = {"reply": GOOD, "calls": 0}

    def chat(messages, **_):
        fake["calls"] += 1
        if isinstance(fake["reply"], Exception):
            raise fake["reply"]
        return fake["reply"]

    monkeypatch.setenv("LLM_BASE_URL", "http://model.test/v1")
    monkeypatch.setenv("LLM_MODEL", "fake-3b")
    monkeypatch.setattr(llm, "chat", chat)
    kpi_explain._cache.clear()
    return fake


def test_the_code_works_out_the_facts_and_writes_a_correct_explanation(client):
    f = kpi_explain.facts("car_pct")
    assert f["limits"]["status"] == "inside the early-warning zone"
    assert f["since_previous"]["better_or_worse"] == "better"
    # 2026-08's risk-weighted assets are 0 (unusable), so the capital comparison is Jun -> Jul
    assert f["what_moved"]["period"] == "from Jun 2026 to Jul 2026"
    assert kpi_explain.rules_text(f) == CAR_RULES


def test_a_kpi_with_no_data_says_so(client):
    assert kpi_explain.facts("total_assets_usd") == {}
    assert kpi_explain.explain("total_assets_usd", use_model=False)["text"] == "No KPI data is loaded yet."


def test_a_faithful_rewording_is_shown_and_written_once_per_calculation(client, model):
    first = kpi_explain.explain("car_pct")
    assert (first["source"], first["text"], first["model"]) == ("model", GOOD, "fake-3b")
    assert first["rules_text"] == CAR_RULES
    kpi_explain.explain("car_pct")
    assert model["calls"] == 1


@pytest.mark.parametrize("reply, why", [
    (GOOD.replace("13.50%", "13.5%"), "the model used numbers that aren't in the data (13.5)"),
    (GOOD.replace(", which helped, while risk-weighted assets rose by USD 35.0 million", ""), "the model left out 35.0"),
    (GOOD.replace("rose 1.50 points", "rose 1.50%"), "the model changed the unit of 1.50"),
    (GOOD.replace("It rose 1.50 points from 12.00% on 20 Sep 2026", "It moved from 12.00% to 15.00%"),
     "the model paired 12.00 and 15.00 as a move, which the data doesn't"),
    (GOOD.replace("It rose 1.50 points from", "It fell 1.50 points from"), "the model got the direction of 12.00 to 13.50 wrong"),
    (GOOD + " It has been rising steadily since last week.", 'the model added "last week", which isn\'t in the data'),
    (GOOD + " Capital is strong" + " and strong" * 60 + ".", "the model's text was too long"),
    ("", "the model returned nothing"),
])
def test_a_rewording_that_changes_the_facts_is_thrown_away(client, model, reply, why):
    model["reply"] = reply
    result = kpi_explain.explain("car_pct")
    assert (result["source"], result["text"], result["note"]) == ("rules", CAR_RULES, why)
    kpi_explain.explain("car_pct")
    assert model["calls"] == 1                                    # a refused rewording isn't asked for again


def test_an_unreachable_model_falls_back_and_is_tried_again_later(client, model, monkeypatch):
    model["reply"] = llm.Unavailable("model server unreachable: timed out")
    assert kpi_explain.explain("car_pct")["note"] == "model server unreachable: timed out"
    kpi_explain.explain("car_pct")
    assert model["calls"] == 1                                    # not every page view
    monkeypatch.setattr(kpi_explain, "RETRY_UNAVAILABLE_SECONDS", 0)
    kpi_explain._cache.clear()
    kpi_explain.explain("car_pct")
    model["reply"] = GOOD
    assert kpi_explain.explain("car_pct")["source"] == "model"


def test_without_a_model_the_code_built_explanation_is_used(client, monkeypatch):
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    kpi_explain._cache.clear()
    result = kpi_explain.explain("car_pct")
    assert (result["source"], result["note"]) == ("rules", "no local model is configured")


def test_the_endpoint_answers_at_once_without_the_model_then_with_it(client, auth, model):
    fast = client.get(f"{API}/kpi-summary/car_pct/explanation", headers=auth, params={"use_model": False}).json()
    assert (fast["source"], fast["text"]) == ("rules", CAR_RULES) and model["calls"] == 0
    full = client.get(f"{API}/kpi-summary/car_pct/explanation", headers=auth).json()
    assert full["source"] == "model" and full["facts"]["value"] == "13.50%"
    assert client.get(f"{API}/kpi-summary/nope/explanation", headers=auth).status_code == 404
