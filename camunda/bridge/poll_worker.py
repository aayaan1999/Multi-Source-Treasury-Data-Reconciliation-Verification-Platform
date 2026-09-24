"""Bridge worker: Postgres -> Zeebe (specs/camunda-bpmn-process-design.md section 4).

Polls data_quality_exceptions and flagged_transactions for rows with no camunda_process_tracking
entry yet, derives flagCategory per the spec's table-based assumption (section 3), starts one
transaction-review process instance per row, and records the resulting process_instance_key so
the next poll doesn't start it twice.

    python camunda/bridge/poll_worker.py            # one pass, then exit
    python camunda/bridge/poll_worker.py --loop 300  # poll every 300s, matching the nightly
                                                       # Databricks->Postgres import job's cadence

Recommendation in the spec is a polling worker over LISTEN/NOTIFY, since a real-time trigger
doesn't match the rest of the pipeline's nightly-batch freshness guarantees.
"""
import argparse
import asyncio
import time

import _env  # sets the Windows event-loop policy - must be imported before pyzeebe/grpc.aio, see _env.py
import psycopg2
import psycopg2.extras
from pyzeebe import ZeebeClient, create_insecure_channel

import cases_db
import duplicates_db
import recon_groups_db
import reconciliation_db
from _env import cfo_email, database_url, zeebe_address

PROCESS_ID = "transaction-review"

# flagCategory derivation - specs/camunda-bpmn-process-design.md section 3. A documented
# assumption, not a verified business rule (see that spec's Open Items).
COMPLIANCE_TABLES = {"capital_positions", "liquidity_daily", "fx_rates"}

# Notebook 5's flag_type (FRD-1: THRESHOLD / SUSPICIOUS / OPERATIONAL) -> team. A suspicious
# pattern goes to investigators; a threshold crossing is a reporting matter for Compliance, not an
# investigation; an operational fault falls through to the table-based rule (Operations).
TRANSACTION_FLAG_CATEGORY = {"SUSPICIOUS": "FRAUD", "THRESHOLD": "COMPLIANCE"}


def flag_category(flag_type: str, source_table: str) -> str:
    if flag_type in TRANSACTION_FLAG_CATEGORY:
        return TRANSACTION_FLAG_CATEGORY[flag_type]
    if source_table in COMPLIANCE_TABLES:
        return "COMPLIANCE"
    return "OPERATIONS"


def fetch_unstarted(conn) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT 'data_quality' AS record_type, d.source_table, d.record_key, d.flag_label,
                   'FAULT' AS flag_type, d.description
            FROM data_quality_exceptions d
            WHERE NOT EXISTS (
                SELECT 1 FROM camunda_process_tracking t
                WHERE t.record_type = 'data_quality' AND t.source_table = d.source_table
                  AND t.record_key = d.record_key AND t.flag_label = d.flag_label
            )
        """)
        # Transaction flags are no longer started one by one: they're grouped into cases
        # (specs/task-cases.md) by start_fraud_cases below.
        return cur.fetchall()


def record_tracking(conn, row: dict, process_instance_key: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO camunda_process_tracking
               (record_type, source_table, record_key, flag_label, process_instance_key)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (record_type, source_table, record_key, flag_label) DO NOTHING""",
            (row["record_type"], row["source_table"], row["record_key"], row["flag_label"], process_instance_key),
        )
    conn.commit()


async def start_fraud_cases(client: ZeebeClient, conn) -> int:
    """Groups pending transaction flags into cases (one per account + day + flag type) and starts
    one transaction-review per High/Medium case; Low cases wait in the digest (specs/task-cases.md)."""
    cases_db.create_cases(conn, flag_category)
    cases = cases_db.fetch_unstarted(conn)
    for case in cases:
        result = await client.run_process(bpmn_process_id=PROCESS_ID, variables=cases_db.process_variables(case))
        cases_db.record_started(conn, case["case_id"], result.process_instance_key)
        print(f"Started instance {result.process_instance_key} for case {case['case_id']} "
              f"({case['flag_count']} flag(s), {case['severity']}) -> {case['team']}")
    return len(cases)


async def start_duplicate_reviews(client: ZeebeClient, conn) -> int:
    """Finds possible duplicate customers and starts one review task per new pair: a person
    decides "same company" or "different" - nothing is merged automatically (specs/entity-matching.md)."""
    duplicates_db.find_candidates(conn)
    due_days = duplicates_db.settings(conn)["task.due_days"].get("DUPLICATE", 10)
    candidates = duplicates_db.fetch_unstarted(conn)
    for c in candidates:
        result = await client.run_process(bpmn_process_id=PROCESS_ID, variables=duplicates_db.process_variables(c, due_days))
        duplicates_db.record_started(conn, c["candidate_id"], result.process_instance_key)
        print(f"Started instance {result.process_instance_key} for possible duplicate {c['customer_a']}/{c['customer_b']} -> OPERATIONS")
    return len(candidates)


async def start_recon_group_reviews(client: ZeebeClient, conn) -> int:
    """Groups open core-system reconciliation breaks by cause and starts one group review per
    group; important breaks are groups of one (specs/reconciliation-groups.md)."""
    recon_groups_db.create_groups(conn)
    groups = recon_groups_db.fetch_unstarted(conn)
    for g in groups:
        result = await client.run_process(bpmn_process_id=recon_groups_db.PROCESS_ID, variables=recon_groups_db.process_variables(g))
        recon_groups_db.record_started(conn, g["group_id"], result.process_instance_key)
        print(f"Started instance {result.process_instance_key} for reconciliation group {g['group_id']} "
              f"({g['break_count']} break(s){', important' if g['important'] else ''}) -> {g['team']}")
    return len(groups)


async def start_reconciliation_reviews(client: ZeebeClient, conn) -> int:
    """One reconciliation-review (specs/cfo-reconciliation-workflow.md) per OPEN pipeline
    reconciliation item with a gap, handed to the CFO. Tracked like the flags above, so never twice."""
    items = reconciliation_db.fetch_unstarted(conn)
    if not items:
        return 0
    cfo_id = reconciliation_db.cfo_user_id(conn, cfo_email())
    for item in items:
        result = await client.run_process(
            bpmn_process_id=reconciliation_db.PROCESS_ID,
            variables=reconciliation_db.process_variables(item, cfo_id),
        )
        reconciliation_db.record_started(conn, item["recon_id"], result.process_instance_key)
        print(f"Started instance {result.process_instance_key} for reconciliation item {item['recon_id']} -> CFO")
    return len(items)


async def run_once(client: ZeebeClient, conn) -> int:
    rows = fetch_unstarted(conn)
    for row in rows:
        category = flag_category(row["flag_type"], row["source_table"])
        result = await client.run_process(
            bpmn_process_id=PROCESS_ID,
            variables={
                "recordType": row["record_type"],
                "sourceTable": row["source_table"],
                "recordKey": row["record_key"],
                "flagLabel": row["flag_label"],
                "flagType": row["flag_type"],
                "flagCategory": category,
                "description": row["description"] or "",
            },
        )
        record_tracking(conn, row, result.process_instance_key)
        print(f"Started instance {result.process_instance_key} for "
              f"{row['record_type']}/{row['source_table']}/{row['record_key']}/{row['flag_label']} "
              f"-> {category}")
    return (len(rows) + await start_fraud_cases(client, conn) + await start_reconciliation_reviews(client, conn)
            + await start_duplicate_reviews(client, conn) + await start_recon_group_reviews(client, conn))


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", type=int, default=0, help="poll every N seconds instead of running once")
    args = parser.parse_args()

    channel = create_insecure_channel(grpc_address=zeebe_address())
    client = ZeebeClient(channel)
    conn = psycopg2.connect(database_url(), connect_timeout=45)
    try:
        while True:
            started = await run_once(client, conn)
            print(f"Poll complete: {started} new process instance(s) started.")
            if not args.loop:
                break
            time.sleep(args.loop)
    finally:
        conn.close()


if __name__ == "__main__":
    asyncio.run(main())
