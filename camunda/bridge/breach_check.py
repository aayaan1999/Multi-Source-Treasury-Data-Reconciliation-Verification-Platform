"""Breach alert job (specs/screen-06-report-workflow.md section 2.4): compares the latest
kpi_daily_summary row against limits' thresholds, inserts a breaches row for any new breach, and
starts a transaction-review Camunda process instance for it - reusing the SAME
flagCategory-routed process (the existing 'compliance' candidate group), not a separate alert
system, per the spec's explicit instruction.

    python camunda/bridge/breach_check.py            # one pass, then exit
    python camunda/bridge/breach_check.py --loop 300  # poll every 5 minutes

Levels (early warning / internal appetite / regulatory), the consecutive-days rule, escalation and
due dates: specs/breach-levels.md, implemented in breaches_db.py. Early warnings are notifications
(status WARNING), never tasks.

Run this after each Notebook 3 KPI run (or on the same cadence as poll_worker.py) so a breach in
today's KPIs becomes a task promptly.

Two assumptions, undocumented anywhere upstream, made explicit here rather than guessed silently:
- limits.metric_name -> kpi_daily_summary column: the schema never pinned this mapping down (the
  source doc only named the 8 KPI tiles, and limits.metric_name is free text). KPI_COLUMN (now in breaches_db.py) is
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
from pyzeebe import ZeebeClient, create_insecure_channel

import breaches_db
from _env import database_url, zeebe_address

PROCESS_ID = "transaction-review"


async def run_once(client: ZeebeClient, conn) -> int:
    """Breach levels, the consecutive-days rule, escalation and clearing are decided in
    breaches_db (specs/breach-levels.md); this starts a task for each breach that needs one."""
    for action, metric, level in breaches_db.evaluate(conn):
        print(f"{action}: {metric} at {level}")

    started = 0
    for b in breaches_db.untracked(conn):
        result = await client.run_process(bpmn_process_id=PROCESS_ID, variables=breaches_db.process_variables(b))
        breaches_db.record_tracking(conn, b["breach_id"], b["metric_name"], result.process_instance_key)
        print(f"Breach {b['breach_id']} ({b['level']}) -> instance {result.process_instance_key}")
        started += 1
    return started


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", type=int, default=0, help="poll every N seconds instead of running once")
    args = parser.parse_args()

    channel = create_insecure_channel(grpc_address=zeebe_address())
    client = ZeebeClient(channel)
    # A fresh connection every pass: Neon suspends an idle database and drops open connections, which
    # killed a long-running worker holding one connection (live, 2026-09-24). A failed connect (Neon or the
    # network unreachable, live 2026-09-25) or a dropped connection mid-pass is logged and retried next pass.
    while True:
        conn = None
        try:
            conn = psycopg2.connect(database_url(), connect_timeout=45)
            started = await run_once(client, conn)
            print(f"Check complete: {started} new breach(es).")
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
            if not args.loop:
                raise
            print(f"Database connection lost ({str(e).strip().splitlines()[0]}) - retrying next pass.")
        finally:
            if conn is not None:
                conn.close()
        if not args.loop:
            break
        time.sleep(args.loop)


if __name__ == "__main__":
    asyncio.run(main())
