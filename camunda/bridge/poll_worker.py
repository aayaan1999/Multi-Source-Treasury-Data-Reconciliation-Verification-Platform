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

from _env import database_url, zeebe_address

PROCESS_ID = "transaction-review"

# flagCategory derivation - specs/camunda-bpmn-process-design.md section 3. A documented
# assumption, not a verified business rule (see that spec's Open Items).
COMPLIANCE_TABLES = {"capital_positions", "liquidity_daily", "fx_rates"}


def flag_category(flag_type: str, source_table: str) -> str:
    if flag_type == "FRAUD":
        return "FRAUD"
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
            UNION ALL
            SELECT 'fraud' AS record_type, 'transactions' AS source_table, f.transaction_id AS record_key,
                   f.flag_label, f.flag_type, f.description
            FROM flagged_transactions f
            WHERE f.status = 'PENDING_REVIEW'
              AND NOT EXISTS (
                SELECT 1 FROM camunda_process_tracking t
                WHERE t.record_type = 'fraud' AND t.source_table = 'transactions'
                  AND t.record_key = f.transaction_id AND t.flag_label = f.flag_label
            )
        """)
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
    return len(rows)


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
