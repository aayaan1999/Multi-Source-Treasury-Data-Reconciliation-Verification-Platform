"""scripts/seed_loans_api.py: the loan system gets our loans with exactly the planted differences."""
import importlib.util
import pathlib
from decimal import Decimal

ROOT = pathlib.Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("seed_loans_api", ROOT / "scripts" / "seed_loans_api.py")
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)

LOANS = [{"loan_id": f"L{i:03}", "customer_id": f"C{i:03}", "product": "Mortgage" if i % 2 else "Corporate",
          "principal": Decimal("100000"), "outstanding": Decimal("50000.00"), "currency": "USD", "interest_rate": 6.5,
          "origination_date": None, "maturity_date": None} for i in range(1, 15)]


def test_every_loan_is_copied_and_only_the_planted_ones_differ():
    rows, notes = seed.plan(LOANS)
    by_id = {r["loan_id"]: r for r in rows}
    assert "L009" not in by_id and seed.EXTRA_LOAN_ID in by_id                 # one left out, one extra
    assert len(rows) == len(LOANS)
    changed = {l["loan_id"]: {c for c in seed.COLUMNS if str(by_id[l["loan_id"]][c]) != str(l[c])}
               for l in LOANS if l["loan_id"] in by_id}
    assert {k: v for k, v in changed.items() if v} == {
        "L001": {"outstanding"}, "L002": {"outstanding"}, "L003": {"outstanding"}, "L004": {"outstanding"},
        "L005": {"interest_rate"}, "L006": {"product"}, "L007": {"currency"}, "L008": {"product"}}
    assert by_id["L001"]["outstanding"] == 50015 and by_id["L004"]["outstanding"] == 75000
    assert by_id["L005"]["interest_rate"] == 7.25 and by_id["L007"]["currency"] == "EUR"
    assert by_id["L008"]["product"] == "CORPORATE"                             # formatting only: cleared automatically
    assert len(notes) == 8 and all(LOANS[0]["loan_id"] not in n or "+15" in n for n in notes)


def test_too_few_loans_is_refused():
    try:
        seed.plan(LOANS[:5])
    except SystemExit as e:
        assert "Only" in str(e)
    else:
        raise AssertionError("expected SystemExit")


def test_the_password_is_taken_as_typed_and_never_echoed():
    url = "postgresql://postgres.abcd:p%4&x$!Q@aws-0-eu-central-1.pooler.supabase.com:5432/postgres"
    assert seed.parse_url(url) == {"user": "postgres.abcd", "password": "p%4&x$!Q",
                                   "host": "aws-0-eu-central-1.pooler.supabase.com", "port": 5432, "dbname": "postgres"}
    for bad, says in [(url.replace("p%4&x$!Q", "[p%4&x$!Q]"), "inside [ ]"), ("https://abcd.supabase.co", "isn't a connection string")]:
        try:
            seed.parse_url(bad)
        except SystemExit as e:
            assert says in str(e) and "p%4&x$!Q" not in str(e)
        else:
            raise AssertionError("expected SystemExit")
