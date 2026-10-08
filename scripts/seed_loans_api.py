"""Fill the demo loan origination system (a Supabase project, db/loans_api_demo.env) with the app's loans, then
plant known differences - one per feature to show - so the loan reconciliation has something real to find
(specs/screen-data-ingestion.md section 3d, specs/multi-source-reconciliation.md).

    python scripts/seed_loans_api.py            # show what would be planted
    python scripts/seed_loans_api.py --apply    # replace the loans table in Supabase and plant them

Supabase serves the `loans` table as a REST API (https://<project>.supabase.co/rest/v1/loans), which the app's
Data ingestion tab connects as "REST API" and notebooks/multi_source_rest_api_ingestion.py reads. This script
writes to Supabase's Postgres directly, creates the table if needed, and lets the project's publishable (anon)
key read it, read-only: row-level security on, one SELECT policy, no write access through the API.

Never touches the app's own database (it only reads its loans). Running it again starts over from the app's
current loans, so the planted differences are always exactly the ones listed. Never prints a credential.
"""
import pathlib
import re
import sys

import psycopg2
import psycopg2.extras
from dotenv import dotenv_values

ROOT = pathlib.Path(__file__).resolve().parent.parent
COLUMNS = ["loan_id", "customer_id", "product", "principal", "outstanding", "currency", "interest_rate",
           "origination_date", "maturity_date"]
EXTRA_LOAN_ID = "LNLOS01"                      # only in the loan system -> "missing in our data"

CREATE = """
CREATE TABLE IF NOT EXISTS public.loans (
    loan_id          text PRIMARY KEY,
    customer_id      text NOT NULL,
    product          text NOT NULL,
    principal        numeric(20,2),
    outstanding      numeric(20,2),
    currency         text NOT NULL,
    interest_rate    numeric(8,4),
    origination_date date,
    maturity_date    date,
    updated_at       timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.loans ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS loans_read ON public.loans;
CREATE POLICY loans_read ON public.loans FOR SELECT TO anon USING (true);
REVOKE ALL ON public.loans FROM anon, authenticated;
GRANT SELECT ON public.loans TO anon;
"""


def plan(loans: list) -> tuple:
    """The loan system's rows (ours, changed as planted) and a line per planted difference."""
    rows = {l["loan_id"]: dict(l) for l in loans}
    ordinary = [l["loan_id"] for l in loans
                if l["interest_rate"] is not None and float(l["outstanding"] or 0) > 30000 and l["currency"]]
    if len(ordinary) < 10:
        raise SystemExit(f"Only {len(ordinary)} loans to plant differences in; the app needs its loans loaded first.")
    plus15, big, rate, product, currency, caps, left_out = ordinary[:3], ordinary[3], ordinary[4], ordinary[5], ordinary[6], ordinary[7], ordinary[8]
    notes = []
    for loan_id in plus15:
        rows[loan_id]["outstanding"] = float(rows[loan_id]["outstanding"]) + 15
    notes.append(f"outstanding +15.00 on {', '.join(plus15)} -> one group of 3")
    rows[big]["outstanding"] = float(rows[big]["outstanding"]) + 25000
    notes.append(f"outstanding +25,000.00 on {big} -> important, on its own")
    old_rate = float(rows[rate]["interest_rate"])
    rows[rate]["interest_rate"] = round(old_rate + 0.75, 4)
    notes.append(f"interest rate {old_rate:g}% -> {old_rate + 0.75:g}% on {rate}")
    products = sorted({l["product"] for l in loans})
    old_product = rows[product]["product"]
    new_product = next((p for p in products if p != old_product), old_product + " (LOS)")
    rows[product]["product"] = new_product
    notes.append(f"product {old_product} -> {new_product} on {product}")
    old_currency = rows[currency]["currency"]
    rows[currency]["currency"] = "EUR" if old_currency != "EUR" else "USD"
    notes.append(f"currency {old_currency} -> {rows[currency]['currency']} on {currency} -> important (key field)")
    ours = rows[caps]["product"]
    if ours.upper() != ours:
        rows[caps]["product"] = ours.upper()
        notes.append(f"product '{ours}' in capitals on {caps} -> cleared automatically (formatting only)")
    else:
        notes.append(f"product already in capitals on {caps}: no formatting-only difference planted")
    del rows[left_out]
    notes.append(f"{left_out} not in the loan system -> 'missing in the source system'")
    template = dict(rows[ordinary[9]])
    rows[EXTRA_LOAN_ID] = {**template, "loan_id": EXTRA_LOAN_ID, "outstanding": 120000, "principal": 150000}
    notes.append(f"{EXTRA_LOAN_ID} only in the loan system -> 'missing in our data'")
    return list(rows.values()), notes


def parse_url(url: str) -> dict:
    """The connection string's parts, taken apart by hand rather than by the driver: a password exactly as
    Supabase shows it (with %, &, $, ! ...) needs no percent-encoding, and a driver parse error would echo
    the part it choked on, which can be the password."""
    match = re.match(r"^postgres(?:ql)?://([^:@/]+):(.*)@([^:/@]+):(\d+)/([^?\s]+)", url or "")
    if not match:
        raise SystemExit("SUPABASE_DB_URL isn't a connection string like "
                         "postgresql://postgres.<project-ref>:PASSWORD@aws-0-<region>.pooler.supabase.com:5432/postgres")
    user, password, host, port, dbname = match.groups()
    if password.startswith("[") and password.endswith("]"):
        raise SystemExit("The password in SUPABASE_DB_URL is still inside [ ]: remove the brackets from [YOUR-PASSWORD].")
    return {"user": user, "password": password, "host": host, "port": int(port), "dbname": dbname}


def connect_supabase(url: str):
    try:
        return psycopg2.connect(**parse_url(url), sslmode="require", connect_timeout=45)
    except psycopg2.OperationalError as e:
        # The server's own first line (e.g. "password authentication failed for user ..."), never the password.
        raise SystemExit(f"Couldn't sign in to Supabase: {(str(e).strip().splitlines() or ['no reason given'])[0]}")


def main():
    apply = "--apply" in sys.argv[1:]
    app_url = dotenv_values(ROOT / "backend" / ".env").get("DATABASE_URL")
    los_url = dotenv_values(ROOT / "db" / "loans_api_demo.env").get("SUPABASE_DB_URL")
    if apply and not los_url:                      # the preview only reads the app's loans
        raise SystemExit("Put the Supabase connection string in db/loans_api_demo.env as SUPABASE_DB_URL "
                         "(copy db/loans_api_demo.env.example)")
    if los_url and los_url == app_url:
        raise SystemExit("db/loans_api_demo.env must point at the Supabase project, not the app's own database")

    with psycopg2.connect(app_url, connect_timeout=45) as app, app.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"SELECT {', '.join(COLUMNS)} FROM loans ORDER BY loan_id")
        loans = cur.fetchall()
    rows, notes = plan(loans)

    print(f"The loan system will hold {len(rows)} loans: the app's {len(loans)}, with these planted differences:")
    for note in notes:
        print(f"  {note}")
    if not apply:
        print("\nNothing written. Run again with --apply to replace the loans table in Supabase.")
        return

    los = connect_supabase(los_url)
    with los, los.cursor() as cur:
        cur.execute(CREATE)
        cur.execute("TRUNCATE public.loans")
        psycopg2.extras.execute_values(
            cur, f"INSERT INTO public.loans ({', '.join(COLUMNS)}) VALUES %s",
            [tuple(r[c] for c in COLUMNS) for r in rows],
        )
    los.close()
    print(f"\nWritten: {len(rows)} loans in Supabase, readable through its REST API with the publishable key.")


if __name__ == "__main__":
    main()
