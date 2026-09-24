"""Prepare the demo core-banking database (the SECOND Neon project, db/multi_source_demo.env) for a
core-system reconciliation demo (specs/reconciliation-groups.md): first make it match the app's
current customers and accounts exactly, then plant known differences - one per feature to show.

    python scripts/plant_core_system_breaks.py

Never touches the app's own database (it only reads from it). Every changed row gets
updated_at = now(), because the core-system ingestion (notebooks/multi_source_neon_ingestion.py)
only pulls rows changed since its last run - which is also why a planted "missing record" leaves a
row out rather than deleting one (a deletion would never be seen). Then run, in Databricks:
multi_source_neon_ingestion (customers, then accounts) -> multi_source_reconciliation -> load_to_postgres.
"""
import pathlib

import psycopg2
from dotenv import dotenv_values

ROOT = pathlib.Path(__file__).resolve().parent.parent
LEFT_OUT = "ACNDEMO2"              # our account core banking won't have -> "missing in the source system"
EXTRA_CUSTOMER = ("CNCORE01", "Harbour Freight SAL", "Corporate", "B", None)   # only in core -> "missing in our data"


def main():
    app_url = dotenv_values(ROOT / "backend" / ".env")["DATABASE_URL"]
    core_url = dotenv_values(ROOT / "db" / "multi_source_demo.env")["NEON_SOURCE_URL"]
    if not core_url or core_url == app_url:
        raise SystemExit("db/multi_source_demo.env must point at the separate demo core-banking database")

    with psycopg2.connect(app_url, connect_timeout=45) as app, app.cursor() as cur:
        cur.execute("SELECT customer_id, name, segment, risk_rating, branch_id FROM customers ORDER BY customer_id")
        customers = cur.fetchall()
        cur.execute("SELECT account_id, customer_id, type, currency, balance FROM accounts ORDER BY account_id")
        accounts = [a for a in cur.fetchall() if a[0] != LEFT_OUT]

    by_id = {a[0]: a for a in accounts}
    ordinary = [a[0] for a in accounts if a[0].startswith("ACN0") and float(a[4] or 0) > 20000]
    plus15, second_approval, band, big = ordinary[:4], ordinary[4:16], ordinary[16:18], ordinary[18]
    cust_ids = [c[0] for c in customers if c[0].startswith("CN0")]
    segment_cust, caps_cust = cust_ids[50], cust_ids[51]
    customer_by_id = {c[0]: c for c in customers}

    core = psycopg2.connect(core_url, connect_timeout=45)
    with core, core.cursor() as cur:
        # 1. Match the app exactly (upsert every customer and account, stamp updated_at).
        for c in customers:
            cur.execute("""UPDATE customers SET name = %s, segment = %s, risk_rating = %s, branch_id = %s, updated_at = now()
                           WHERE customer_id = %s""", (c[1], c[2], c[3], c[4], c[0]))
            if cur.rowcount == 0:
                cur.execute("""INSERT INTO customers (customer_id, name, segment, risk_rating, branch_id, updated_at)
                               VALUES (%s, %s, %s, %s, %s, now())""", c)
        for a in accounts:
            cur.execute("""UPDATE accounts SET customer_id = %s, type = %s, currency = %s, balance = %s, updated_at = now()
                           WHERE account_id = %s""", (a[1], a[2], a[3], a[4], a[0]))
            if cur.rowcount == 0:
                cur.execute("""INSERT INTO accounts (account_id, customer_id, type, currency, balance, updated_at)
                               VALUES (%s, %s, %s, %s, %s, now())""", a)

        # 2. Plant the differences (core banking is the "source" side).
        def shift(account_id, amount):
            cur.execute("UPDATE accounts SET balance = balance + %s, updated_at = now() WHERE account_id = %s", (amount, account_id))

        for acc in plus15:
            shift(acc, 15)
        for acc in second_approval:
            shift(acc, -9000)
        shift(band[0], 240)
        shift(band[1], -610)
        shift(big, 48000)
        new_segment = "SME" if customer_by_id[segment_cust][2] != "SME" else "Retail"
        cur.execute("UPDATE customers SET segment = %s, updated_at = now() WHERE customer_id = %s", (new_segment, segment_cust))
        cur.execute("UPDATE customers SET name = upper(name), updated_at = now() WHERE customer_id = %s", (caps_cust,))
        cur.execute("DELETE FROM customers WHERE customer_id = %s", (EXTRA_CUSTOMER[0],))
        cur.execute("""INSERT INTO customers (customer_id, name, segment, risk_rating, branch_id, updated_at)
                       VALUES (%s, %s, %s, %s, %s, now())""",
                    (*EXTRA_CUSTOMER[:4], customer_by_id[cust_ids[0]][4]))

    print("Core banking now matches the app, except these planted differences:")
    print(f"  balance +15.00 on {', '.join(plus15)}  -> one group of 4")
    print(f"  balance -9,000.00 on {len(second_approval)} accounts ({second_approval[0]}..{second_approval[-1]}) -> one group, total 108,000: needs a second approval")
    print(f"  balance +240 on {band[0]} and -610 on {band[1]} -> one 'difference 100-1,000' group")
    print(f"  balance +48,000 on {big} -> important, on its own")
    print(f"  segment {customer_by_id[segment_cust][2]} -> {new_segment} on {segment_cust} -> important (key field)")
    print(f"  name in capitals on {caps_cust} ('{customer_by_id[caps_cust][1]}') -> cleared automatically (formatting only)")
    print(f"  {EXTRA_CUSTOMER[0]} only in core banking -> 'missing in our data'")
    print(f"  {LEFT_OUT} not in core banking -> 'missing in the source system'")


if __name__ == "__main__":
    main()
