"""Breach alert job (specs/screen-06-report-workflow.md section 2.4): compares the latest
kpi_daily_summary row against limits' thresholds, inserts a breaches row for any new breach, and
starts a transaction-review Camunda process instance for it - reusing the SAME
flagCategory-routed process (the existing 'compliance' candidate group), not a separate alert
system, per the spec's explicit instruction.

    python camunda/bridge/breach_check.py            # one pass, then exit
    python camunda/bridge/breach_check.py --loop 300  # poll every 5 minutes

Run this after each Notebook 3 KPI run (or on the same cadence as poll_worker.py) so a breach in
today's KPIs becomes a task promptly.

Two assumptions, undocumented anywhere upstream, made explicit here rather than guessed silently:
- limits.metric_name -> kpi_daily_summary column: the schema never pinned this mapping down (the
  source doc only named the 8 KPI tiles, and limits.metric_name is free text). KPI_COLUMN below is
  that mapping; a limit whose metric_name isn't in it is skipped, not guessed at.
- flagCategory is always "COMPLIANCE": every one of the 8 KPIs (CAR, LCR, NPL, NIM,
  cost-to-income, ROE, total assets, dollarization) is a regulatory/board-level ratio, matching
  the same rationale specs/camunda-bpmn-process-design.md section 3 already uses for
  capital_positions/liquidity_daily/fx_rates data-quality flags.
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

KPI_COLUMN = {
    "capital_adequacy_ratio": "car_pct",
    "liquidity_coverage_ratio": "lcr_pct",
    "npl_ratio": "npl_ratio_pct",
    "dollarization_ratio": "dollarization_ratio_pct",
    "net_interest_margin": "nim_pct",
    "cost_to_income_ratio": "cost_to_income_pct",
    "return_on_equity": "roe_pct",
    "total_assets": "total_assets_usd",
}


def latest_kpis(conn) -> dict | None:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM kpi_daily_summary ORDER BY calculation_date DESC LIMIT 1")
        return cur.fetchone()


def find_new_breaches(conn, kpis: dict) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM limits")
        limits = cur.fetchall()

    new_breaches = []
    for limit in limits:
        col = KPI_COLUMN.get(limit["metric_name"])
        if col is None or kpis.get(col) is None:
            continue  # unmapped metric_name, or that KPI hasn't been calculated yet - skip, don't guess
        actual = kpis[col]
        breached = actual < limit["threshold_value"] if limit["direction"] == "BELOW" else actual > limit["threshold_value"]
        if not breached:
            continue
        with conn.cursor() as cur:
            # An unresolved row already covers this breach - a re-run on still-broken data
            # shouldn't spam a second task while the first is still being worked. Once resolved
            # (resolved_at set), a still-breaching next run creates a fresh breach + task, same as
            # a Databricks re-run re-flagging a still-bad record.
            cur.execute("SELECT 1 FROM breaches WHERE limit_id = %s AND resolved_at IS NULL", (limit["limit_id"],))
            if cur.fetchone():
                continue
        new_breaches.append({**limit, "actual_value": actual})
    return new_breaches


def insert_breach(conn, breach: dict) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO breaches (limit_id, actual_value) VALUES (%s, %s) RETURNING breach_id",
            (breach["limit_id"], breach["actual_value"]),
        )
        breach_id = cur.fetchone()[0]
    conn.commit()
    return breach_id


def untracked_breaches(conn) -> list[dict]:
    """Breach rows with no camunda_process_tracking entry yet - deliberately separate from
    detection (find_new_breaches/insert_breach) so a Zeebe outage between "insert the breach row"
    and "start its process instance" doesn't strand that row forever: the next run finds it here
    and retries, the same NOT EXISTS pattern poll_worker.py already uses.

    Known gap, confirmed live 2026-09-22: a client-side ProcessTimeoutError doesn't mean the
    CreateProcessInstance command actually failed on the broker - it can still have succeeded,
    just too slowly for this client's deadline. A retry in that case creates a second, duplicate
    process instance/task for the same breach (observed: two live "Compliance Review" tasks from
    one breach after a timeout+retry). pyzeebe's client doesn't expose idempotency keys for this
    call, so avoiding it cleanly needs either a longer deadline, checking Operate/Tasklist for an
    existing instance with matching variables before retrying, or accepting the rare duplicate as
    a POC-scale tradeoff. Not fixed here - flagging it rather than leaving it silently possible."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """SELECT b.breach_id, b.actual_value, l.metric_name, l.threshold_value, l.direction
               FROM breaches b JOIN limits l ON l.limit_id = b.limit_id
               WHERE NOT EXISTS (
                   SELECT 1 FROM camunda_process_tracking t
                   WHERE t.record_type = 'breach' AND t.source_table = 'breaches'
                     AND t.record_key = b.breach_id::text AND t.flag_label = l.metric_name
               )"""
        )
        return cur.fetchall()


def record_tracking(conn, breach_id: int, metric_name: str, process_instance_key: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO camunda_process_tracking
               (record_type, source_table, record_key, flag_label, process_instance_key)
               VALUES ('breach', 'breaches', %s, %s, %s)
               ON CONFLICT (record_type, source_table, record_key, flag_label) DO NOTHING""",
            (str(breach_id), metric_name, process_instance_key),
        )
    conn.commit()


async def run_once(client: ZeebeClient, conn) -> int:
    kpis = latest_kpis(conn)
    if kpis is None:
        print("No kpi_daily_summary rows yet - nothing to check.")
        return 0
    for b in find_new_breaches(conn, kpis):
        breach_id = insert_breach(conn, b)
        print(f"Breach {breach_id} ({b['metric_name']}): actual {b['actual_value']:.2f} vs "
              f"threshold {b['threshold_value']:.2f} ({b['direction']})")

    started = 0
    for b in untracked_breaches(conn):
        description = (
            f"{b['metric_name']} breached: actual {b['actual_value']:.2f} vs threshold "
            f"{b['threshold_value']:.2f} ({b['direction']})"
        )
        result = await client.run_process(
            bpmn_process_id=PROCESS_ID,
            variables={
                "recordType": "breach",
                "sourceTable": "breaches",
                "recordKey": str(b["breach_id"]),
                "flagLabel": b["metric_name"],
                "flagType": "FAULT",
                "flagCategory": "COMPLIANCE",
                "description": description,
            },
        )
        record_tracking(conn, b["breach_id"], b["metric_name"], result.process_instance_key)
        print(f"Breach {b['breach_id']} -> instance {result.process_instance_key}")
        started += 1
    return started


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
            print(f"Check complete: {started} new breach(es).")
            if not args.loop:
                break
            time.sleep(args.loop)
    finally:
        conn.close()


if __name__ == "__main__":
    asyncio.run(main())
