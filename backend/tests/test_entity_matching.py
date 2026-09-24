"""Duplicate companies (specs/entity-matching.md, client point 3): name cleaning, candidate pairs,
a person's decision, and the groups exposure rolls up by. Tests run in file order."""
import os
import pathlib
import sys
from datetime import date

import psycopg2
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "camunda" / "bridge"))
import duplicates_db  # noqa: E402

API = "/api/v1"
CFG = {"min_score": 0.85, "legal_words": ["SAL", "LTD", "LLC", "INC"], "abbreviations": {"TCS": "TATA CONSULTANCY SERVICES"}}
NEW_CUSTOMERS = [
    ("C8", "Tata Consultancy Services Ltd.", "Corporate", "B1"),
    ("C9", "TCS", "Corporate", "B1"),
    ("C10", "Aoun Industries SAL", "SME", "B1"),
    ("C11", "Aoun Capital LLC", "SME", "B1"),
    ("C12", "Khalil Trading SAL", "Corporate", "B2"),
    ("C13", "Khalil Trdg", "Corporate", "B2"),
]


def test_names_are_compared_without_legal_words_and_with_known_abbreviations():
    assert duplicates_db.clean_name("Tata Consultancy Services Ltd.", CFG) == "TATA CONSULTANCY SERVICES"
    assert duplicates_db.clean_name("TCS", CFG) == "TATA CONSULTANCY SERVICES"
    assert duplicates_db.clean_name("Khalil Trading S.A.L.", CFG) == "KHALIL TRADING"            # dotted legal words too
    assert duplicates_db.clean_name("Al-Rashid & Sons, LLC", CFG) == "AL RASHID SONS"


def test_a_shared_family_name_is_not_a_match_but_a_typo_or_an_acronym_is():
    score = lambda a, b: duplicates_db.score_pair({"name": a}, {"name": b}, CFG)[0]
    assert score("Aoun Industries SAL", "Aoun Capital LLC") < 0.85
    assert score("Khalil Trading SAL", "Khalil Trdg") >= 0.85
    assert score("Gulf Petroleum Services", "GPS") == 0.95                                   # initials
    assert score("Abed Haddad", "Reem Haddad") < 0.85


@pytest.fixture(scope="module")
def customers(db):
    db.executemany("INSERT INTO customers (customer_id, name, segment, branch_id, risk_rating) VALUES (%s, %s, %s, %s, 'B')", NEW_CUSTOMERS)
    db.execute("INSERT INTO loans (loan_id, customer_id, product, currency, principal, outstanding) VALUES ('L8', 'C8', 'Corporate Loan', 'USD', 1000, 800)")
    yield
    db.execute("DELETE FROM camunda_process_tracking WHERE record_type = 'entity_match'")
    db.execute("DELETE FROM customer_entity")
    db.execute("DELETE FROM entity_match_candidates")
    db.execute("DELETE FROM loans WHERE loan_id = 'L8'")
    db.execute("DELETE FROM customers WHERE customer_id = ANY(%s)", ([c[0] for c in NEW_CUSTOMERS],))


@pytest.fixture(scope="module")
def conn(db):
    c = psycopg2.connect(os.environ["DATABASE_URL"])
    yield c
    c.close()


def _pairs(db):
    db.execute("SELECT customer_a, customer_b, status FROM entity_match_candidates ORDER BY customer_a, customer_b")
    return db.fetchall()


def test_likely_duplicates_become_candidates_once(db, conn, customers):
    assert duplicates_db.find_candidates(conn) == 2
    assert _pairs(db) == [("C12", "C13", "PENDING"), ("C8", "C9", "PENDING")]
    assert duplicates_db.find_candidates(conn) == 0


def test_each_candidate_becomes_a_review_task_with_a_plain_title(conn, customers):
    first = duplicates_db.fetch_unstarted(conn)[0]                          # highest score first: TCS (1.0)
    v = duplicates_db.process_variables(first, 10, date(2026, 9, 24))
    assert v["title"] == "Same company? Tata Consultancy Services Ltd. (C8) / TCS (C9) · 100%"
    assert v["flagCategory"] == "OPERATIONS" and v["dueDate"] == "2026-10-04"
    duplicates_db.record_started(conn, first["candidate_id"], 2251799813685400)
    assert [c["customer_a"] for c in duplicates_db.fetch_unstarted(conn)] == ["C12"]


def test_the_review_shows_both_records_with_loans_per_currency(client, auth, db, customers):
    db.execute("SELECT candidate_id FROM entity_match_candidates WHERE customer_a = 'C8'")
    body = client.get(f"{API}/workflow/entity-matches/{db.fetchone()[0]}", headers=auth).json()
    assert [c["customer_id"] for c in body["customers"]] == ["C8", "C9"]
    assert body["customers"][0]["loans"] == [{"currency": "USD", "loan_count": 1, "outstanding": 800.0}]
    assert body["customers"][1]["loans"] == []


def test_same_company_links_the_records_and_different_never_asks_again(db, conn, customers):
    db.execute("SELECT candidate_id, customer_a FROM entity_match_candidates")
    ids = {a: cid for cid, a in db.fetchall()}
    duplicates_db.decide(conn, ids["C8"], "APPROVED", 1)
    duplicates_db.decide(conn, ids["C8"], "REJECTED", 1)                    # a retried job changes nothing
    duplicates_db.decide(conn, ids["C12"], "REJECTED", 1)
    assert _pairs(db) == [("C12", "C13", "REJECTED"), ("C8", "C9", "CONFIRMED")]
    db.execute("SELECT customer_id, master_customer_id FROM customer_entity ORDER BY customer_id")
    assert db.fetchall() == [("C8", "C8"), ("C9", "C8")]                   # one group, led by the lower id
    assert duplicates_db.find_candidates(conn) == 0                         # a rejected pair isn't raised again
    db.execute("SELECT action FROM audit_log WHERE object_type = 'entity_match' ORDER BY log_id")
    assert [a for (a,) in db.fetchall()] == ["SAME_ENTITY", "DIFFERENT_ENTITIES"]
