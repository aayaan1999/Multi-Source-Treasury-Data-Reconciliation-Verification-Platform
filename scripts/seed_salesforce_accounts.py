"""Fill the demo Salesforce org with the bank's business customers, so the CRM describes the same companies
as core banking (specs/screen-data-ingestion.md 3b).

    python scripts/seed_salesforce_accounts.py            # show what would be created
    python scripts/seed_salesforce_accounts.py --apply    # create them

Every Corporate and SME customer in the app's database becomes a Salesforce Account with the same name
and country, and its customer_id in Account Number (the key to match CRM and core banking on later).
Segment, risk rating and branch go in Description; Industry is guessed from the company name. Runs again
safely: an Account whose Account Number already exists is left alone, so nothing is duplicated or changed.

Signs in the same way the pipeline does (OAuth client credentials, settings from the Databricks secret
scope bank-data-sources that the app's Connect & Save fills), so Salesforce must be connected in the app
first. Only reads the app's database; never prints a credential.
"""
import base64
import json
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

import psycopg2
from dotenv import dotenv_values

ROOT = pathlib.Path(__file__).resolve().parent.parent
API = "v60.0"
BATCH = 200                                  # the most records one sObject Collections request takes

# First matching word in the company name -> a value from Salesforce's standard Industry list.
INDUSTRY = [
    ("Pharma", "Healthcare"), ("Contracting", "Construction"), ("Capital", "Finance"), ("Ventures", "Finance"),
    ("Holdings", "Finance"), ("Freight", "Transportation"), ("Logistics", "Transportation"), ("Motors", "Retail"),
    ("Foods", "Food & Beverage"), ("Retail", "Retail"), ("Trad", "Retail"), ("Industries", "Manufacturing"),
    ("Textiles", "Apparel"), ("Consultancy", "Consulting"),
]


def industry(name: str) -> str:
    return next((value for word, value in INDUSTRY if word in name), "Other")


def databricks_secret(env: dict, key: str) -> str:
    host = env["DATABRICKS_HOST"].rstrip("/")
    request = urllib.request.Request(f"{host}/api/2.0/secrets/get?scope=bank-data-sources&key=salesforce-{key}",
                                     headers={"Authorization": f"Bearer {env['DATABRICKS_TOKEN']}"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return base64.b64decode(json.loads(response.read())["value"]).decode()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Couldn't read salesforce-{key} from Databricks ({e.code}) - connect Salesforce in the app first")


class Salesforce:
    def __init__(self, env: dict):
        base = databricks_secret(env, "instance_url").rstrip("/")
        body = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": databricks_secret(env, "client_id"),
                                       "client_secret": databricks_secret(env, "client_secret")}).encode()
        auth = self._send(urllib.request.Request(f"{base}/services/oauth2/token", data=body))
        self.base, self.headers = auth["instance_url"], {"Authorization": f"Bearer {auth['access_token']}",
                                                         "Content-Type": "application/json"}

    @staticmethod
    def _send(request):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as e:
            raise SystemExit(f"Salesforce refused {request.get_method()} {urllib.parse.urlparse(request.full_url).path} ({e.code}): {e.read()[:300]!r}")

    def query(self, soql: str) -> list:
        url, records = f"{self.base}/services/data/{API}/query?{urllib.parse.urlencode({'q': soql})}", []
        while url:
            page = self._send(urllib.request.Request(url, headers=self.headers))
            records += page["records"]
            url = f"{self.base}{page['nextRecordsUrl']}" if not page.get("done", True) else None
        return records

    def create(self, records: list) -> list:
        body = json.dumps({"allOrNone": False, "records": [{"attributes": {"type": "Account"}, **r} for r in records]}).encode()
        return self._send(urllib.request.Request(f"{self.base}/services/data/{API}/composite/sobjects", data=body,
                                                 headers=self.headers, method="POST"))


def main():
    apply = "--apply" in sys.argv
    env = dotenv_values(ROOT / "backend" / ".env")
    with psycopg2.connect(env["DATABASE_URL"], connect_timeout=45) as conn, conn.cursor() as cur:
        cur.execute("""SELECT customer_id, name, segment, risk_rating, branch_id, country FROM customers
                       WHERE segment IN ('Corporate', 'SME') ORDER BY customer_id""")
        customers = cur.fetchall()

    salesforce = Salesforce(env)
    existing = {r["AccountNumber"] for r in salesforce.query("SELECT AccountNumber FROM Account WHERE AccountNumber != null")}
    wanted = [{
        "Name": name, "AccountNumber": customer_id, "Type": "Customer - Direct", "Industry": industry(name),
        "BillingCountry": country,
        "Description": f"{segment} customer · risk rating {risk_rating} · branch {branch_id} · core banking id {customer_id}",
    } for customer_id, name, segment, risk_rating, branch_id, country in customers if customer_id not in existing]

    print(f"{len(customers)} business customers in the app; {len(customers) - len(wanted)} already in Salesforce; {len(wanted)} to create")
    for r in wanted[:5]:
        print(f"  {r['AccountNumber']}  {r['Name']:<32} {r['Industry']:<16} {r['BillingCountry']}")
    if not apply:
        print("Dry run - nothing created. Add --apply to create them.")
        return
    created, failed = 0, []
    for start in range(0, len(wanted), BATCH):
        batch = wanted[start:start + BATCH]
        for record, result in zip(batch, salesforce.create(batch)):
            if result.get("success"):
                created += 1
            else:
                failed.append((record["AccountNumber"], [e.get("message") for e in result.get("errors", [])]))
    print(f"Created {created} Accounts.")
    for customer_id, errors in failed:
        print(f"  not created {customer_id}: {errors}")


if __name__ == "__main__":
    main()
