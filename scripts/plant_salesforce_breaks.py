"""Plant known differences in the demo Salesforce org for the CRM reconciliation demo (the Salesforce section
of the Reconciliation tab; notebooks/multi_source_reconciliation.py with source=salesforce).

    python scripts/plant_salesforce_breaks.py            # show what would change
    python scripts/plant_salesforce_breaks.py --apply    # change it

Run scripts/seed_salesforce_accounts.py --apply first, so Salesforce mirrors the app's business customers.
One difference per case the reconciliation handles; running it again gives the same result:
  1. formatting only  - CN0001's name in capitals with "S.A.L."  -> cleared automatically
  2. name differs     - CN0008 "Haddad Contracting LLC" -> "Haddad Construction LLC"
  3. country differs  - CN0002 Qatar -> United Arab Emirates
  4. missing in CRM   - the first Saudi SME customer's Account deleted
  5. missing in ours  - an Account "Gulf Horizon Trading LLC" (CNCRM01) that core banking doesn't have
To undo: delete CNCRM01 in Salesforce and run seed_salesforce_accounts.py --apply again; fix 1-3 by hand.
Only reads the app's database; never prints a credential.
"""
import json
import sys
import urllib.request

import psycopg2
from dotenv import dotenv_values

from seed_salesforce_accounts import API, ROOT, Salesforce

EXTRA = {"Name": "Gulf Horizon Trading LLC", "AccountNumber": "CNCRM01", "Type": "Customer - Direct", "Industry": "Retail",
         "BillingCountry": "Saudi Arabia", "Description": "Only in the CRM: planted for the reconciliation demo"}


def main():
    apply = "--apply" in sys.argv
    env = dotenv_values(ROOT / "backend" / ".env")
    with psycopg2.connect(env["DATABASE_URL"], connect_timeout=45) as conn, conn.cursor() as cur:
        cur.execute("""SELECT customer_id, name, country FROM customers WHERE customer_id IN ('CN0001', 'CN0002', 'CN0008')
                       ORDER BY customer_id""")
        ours = {r[0]: {"name": r[1], "country": r[2]} for r in cur.fetchall()}
        cur.execute("""SELECT customer_id FROM customers WHERE segment = 'SME' AND country = 'Saudi Arabia'
                       ORDER BY customer_id LIMIT 1""")
        left_out = cur.fetchone()[0]
    if set(ours) != {"CN0001", "CN0002", "CN0008"}:
        raise SystemExit("CN0001, CN0002 and CN0008 must exist in the app's customers")

    sf = Salesforce(env)
    accounts = {r["AccountNumber"]: r for r in sf.query("SELECT Id, AccountNumber, Name, BillingCountry FROM Account WHERE AccountNumber != null")}
    changes = [
        ("CN0001", {"Name": ours["CN0001"]["name"].upper().replace(" SAL", " S.A.L.")}),
        ("CN0008", {"Name": ours["CN0008"]["name"].replace("Contracting", "Construction")}),
        ("CN0002", {"BillingCountry": "United Arab Emirates"}),
    ]
    print(f"Salesforce has {len(accounts)} Accounts with a customer number")
    for customer_id, fields in changes:
        now = accounts.get(customer_id)
        print(f"  {customer_id}: {({k: now.get(k) for k in fields} if now else 'missing - run seed_salesforce_accounts.py')} -> {fields}")
    print(f"  {left_out}: delete (missing in the CRM){'' if left_out in accounts else ' - already gone'}")
    print(f"  CNCRM01: create {EXTRA['Name']}{' - already there' if 'CNCRM01' in accounts else ''}")
    if not apply:
        print("Dry run - nothing changed. Add --apply to change Salesforce.")
        return

    for customer_id, fields in changes:
        if customer_id in accounts:
            sf._send(urllib.request.Request(f"{sf.base}/services/data/{API}/sobjects/Account/{accounts[customer_id]['Id']}",
                                            data=json.dumps(fields).encode(), headers=sf.headers, method="PATCH"))
    if left_out in accounts:
        sf._send(urllib.request.Request(f"{sf.base}/services/data/{API}/sobjects/Account/{accounts[left_out]['Id']}",
                                        headers=sf.headers, method="DELETE"))
    if "CNCRM01" not in accounts:
        result = sf.create([EXTRA])[0]
        if not result.get("success"):
            raise SystemExit(f"Couldn't create CNCRM01: {result.get('errors')}")
    print(f"Planted 5 differences. Salesforce now has {len(sf.query('SELECT Id FROM Account'))} Accounts.")


if __name__ == "__main__":
    main()
