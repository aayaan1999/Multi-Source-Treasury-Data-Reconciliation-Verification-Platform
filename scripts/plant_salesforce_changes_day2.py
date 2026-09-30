"""A second day of CRM activity in the demo Salesforce org, so the next pipeline run finds new differences
between the CRM and core banking (the Salesforce section of the Reconciliation tab).

    python scripts/plant_salesforce_changes_day2.py            # show what would change
    python scripts/plant_salesforce_changes_day2.py --apply    # change it

Run after scripts/seed_salesforce_accounts.py and scripts/plant_salesforce_breaks.py (day 1). Four changes,
on customers day 1 didn't touch (the first Corporate customers after CN0010 with a plain name), nothing deleted:
  1. new prospect      - an Account "Cedar Bay Shipping SAL" (CNCRM02) core banking doesn't have
                         -> missing in our data (important: goes to the CFO)
  2. rebrand           - customer A's name "... LLC/SAL" -> "... Group"            -> name differs (key field)
  3. relocation        - customer B's country -> United Arab Emirates                -> country differs
  4. formatting only   - customer C's name in capitals with "S.A.L." / "L.L.C."     -> cleared automatically
Running it again changes nothing. To undo: delete CNCRM02 in Salesforce and set A, B and C back to the
app's values (the dry run prints them). Only reads the app's database; never prints a credential.
"""
import json
import sys
import urllib.request

import psycopg2
from dotenv import dotenv_values

from seed_salesforce_accounts import API, ROOT, Salesforce

DAY1 = {"CN0001", "CN0002", "CN0008"}
NEW = {"Name": "Cedar Bay Shipping SAL", "AccountNumber": "CNCRM02", "Type": "Prospect", "Industry": "Transportation",
       "BillingCountry": "Lebanon", "Description": "Only in the CRM: a new prospect, planted for the day-2 reconciliation demo"}


def formatted(name: str) -> str:
    """The same name as a CRM user might type it: capitals, "S.A.L." / "L.L.C." (cleared as formatting only)."""
    return name.upper().replace(" SAL", " S.A.L.").replace(" LLC", " L.L.C.")


def rebranded(name: str) -> str:
    for suffix in (" SAL", " LLC", " WLL", " Ltd"):
        if name.endswith(suffix):
            return name[: -len(suffix)] + " Group"
    return name + " Group"


def main():
    apply = "--apply" in sys.argv
    env = dotenv_values(ROOT / "backend" / ".env")
    with psycopg2.connect(env["DATABASE_URL"], connect_timeout=45) as conn, conn.cursor() as cur:
        cur.execute("""SELECT customer_id, name, country FROM customers
                       WHERE segment = 'Corporate' AND customer_id > 'CN0010' AND customer_id LIKE 'CN0%%'
                         AND (name LIKE '%% SAL' OR name LIKE '%% LLC') ORDER BY customer_id""")
        ours = [r for r in cur.fetchall() if r[0] not in DAY1]
    if len(ours) < 3:
        raise SystemExit("Need three Corporate customers with a plain SAL/LLC name")
    (a_id, a_name, _), (b_id, _, b_country), (c_id, c_name, _) = ours[:3]
    new_country = "United Arab Emirates" if b_country != "United Arab Emirates" else "Qatar"

    sf = Salesforce(env)
    accounts = {r["AccountNumber"]: r for r in sf.query("SELECT Id, AccountNumber, Name, BillingCountry FROM Account WHERE AccountNumber != null")}
    changes = [(a_id, "rebrand", {"Name": rebranded(a_name)}),
               (b_id, "relocation", {"BillingCountry": new_country}),
               (c_id, "formatting only", {"Name": formatted(c_name)})]
    print(f"Salesforce has {len(accounts)} Accounts with a customer number")
    todo = []
    for customer_id, why, fields in changes:
        now = accounts.get(customer_id)
        if not now:
            print(f"  {customer_id} ({why}): missing in Salesforce - run seed_salesforce_accounts.py first")
            continue
        before = {k: now.get(k) for k in fields}
        done = before == fields
        print(f"  {customer_id} ({why}): {before} -> {fields}{' - already done' if done else ''}")
        if not done:
            todo.append((now["Id"], fields))
    print(f"  CNCRM02 (new prospect): create {NEW['Name']}{' - already there' if 'CNCRM02' in accounts else ''}")
    if not apply:
        print("Dry run - nothing changed. Add --apply to change Salesforce.")
        return

    for record_id, fields in todo:
        sf._send(urllib.request.Request(f"{sf.base}/services/data/{API}/sobjects/Account/{record_id}",
                                        data=json.dumps(fields).encode(), headers=sf.headers, method="PATCH"))
    if "CNCRM02" not in accounts:
        result = sf.create([NEW])[0]
        if not result.get("success"):
            raise SystemExit(f"Couldn't create CNCRM02: {result.get('errors')}")
    print(f"Changed {len(todo)} Account(s){', created CNCRM02' if 'CNCRM02' not in accounts else ''}. "
          f"Salesforce now has {len(sf.query('SELECT Id FROM Account'))} Accounts.")


if __name__ == "__main__":
    main()
