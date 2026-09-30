"""Puts reconciliation tasks back to a clean start for a demo (specs/reconciliation-approvals.md):
every pipeline gap in each source's newest delivery and every core-system break is undecided again,
the old tasks are cancelled in Camunda, and the next poll starts fresh tasks for the team.

    python camunda/bridge/reset_reconciliation_demo.py            # dry run: says what it would do
    python camunda/bridge/reset_reconciliation_demo.py --apply    # does it

Stop the poll worker first (it would start tasks halfway through) and start it again afterwards: its
first pass creates the groups, the tasks and the runs. What it changes:

  * backs up the reconciliation tables to backup_recon_<timestamp>_<table> first
  * cancels every open reconciliation task and run sign-off process in Camunda
  * pipeline gaps in each source's newest delivery -> OPEN, decisions cleared; older deliveries'
    undecided items -> SUPERSEDED
  * breaks people decided (accepted / corrected / dismissed) -> OPEN; groups and runs are deleted
    and rebuilt by the next poll; cleared-automatically breaks are left alone
  * an item's fixes not yet applied by Databricks are withdrawn; a break group's are deleted with its group
  * one DEMO_RESET audit row. The audit log itself is never touched.
"""
import argparse
import asyncio
from datetime import datetime

import _env  # sets the Windows event-loop policy - must be imported before pyzeebe/grpc.aio, see _env.py
import psycopg2
from pyzeebe import ZeebeClient, create_insecure_channel
from pyzeebe.errors import ProcessInstanceNotFoundError

from _env import database_url, zeebe_address

TABLES = ("pipeline_reconciliation", "reconciliation_groups", "reconciliation_exceptions", "reconciliation_corrections",
          "reconciliation_runs", "camunda_process_tracking")
LATEST = """(source_system, ingest_batch_id) IN (SELECT DISTINCT ON (source_system) source_system, ingest_batch_id
             FROM pipeline_reconciliation ORDER BY source_system, detected_at DESC)"""


def plan(cur) -> dict:
    counts = {}
    for name, sql in {
        "processes to cancel": """SELECT count(*) FROM (
            SELECT process_instance_key FROM camunda_process_tracking WHERE record_type IN ('reconciliation', 'recon_group')
            UNION SELECT process_instance_key FROM reconciliation_groups WHERE process_instance_key IS NOT NULL
            UNION SELECT process_instance_key FROM reconciliation_runs WHERE process_instance_key IS NOT NULL AND status = 'IN_SIGNOFF') k""",
        "pipeline gaps reset to open": f"SELECT count(*) FROM pipeline_reconciliation WHERE has_gap AND {LATEST}",
        "older undecided pipeline items superseded": f"""SELECT count(*) FROM pipeline_reconciliation
            WHERE NOT ({LATEST}) AND status NOT IN ('MATCHED', 'SUPERSEDED')""",
        "decided breaks reopened": "SELECT count(*) FROM reconciliation_exceptions WHERE status IN ('ACCEPTED', 'CORRECTED', 'DISMISSED')",
        "open breaks (regrouped by the next poll)": "SELECT count(*) FROM reconciliation_exceptions WHERE status IN ('OPEN', 'ACCEPTED', 'CORRECTED', 'DISMISSED')",
        "groups deleted": "SELECT count(*) FROM reconciliation_groups",
        "runs deleted": "SELECT count(*) FROM reconciliation_runs",
        "unapplied fixes withdrawn or deleted": "SELECT count(*) FROM reconciliation_corrections WHERE status <> 'WITHDRAWN' AND synced_at IS NULL",
    }.items():
        cur.execute(sql)
        counts[name] = cur.fetchone()[0]
    return counts


async def cancel(keys) -> int:
    client = ZeebeClient(create_insecure_channel(grpc_address=zeebe_address()))
    cancelled = 0
    for key in keys:
        try:
            await client.cancel_process_instance(int(key))
            cancelled += 1
        except ProcessInstanceNotFoundError:
            pass  # already finished or cancelled
    return cancelled


def reset(conn) -> None:
    stamp = datetime.now().strftime("%Y%m%d%H%M")
    with conn.cursor() as cur:
        for t in TABLES:
            cur.execute(f"CREATE TABLE backup_recon_{stamp}_{t} AS SELECT * FROM {t}")
        cur.execute("""SELECT process_instance_key FROM camunda_process_tracking WHERE record_type IN ('reconciliation', 'recon_group')
                       UNION SELECT process_instance_key FROM reconciliation_groups WHERE process_instance_key IS NOT NULL
                       UNION SELECT process_instance_key FROM reconciliation_runs WHERE process_instance_key IS NOT NULL AND status = 'IN_SIGNOFF'""")
        keys = [k for (k,) in cur.fetchall()]
    conn.commit()
    print(f"Backed up {len(TABLES)} tables as backup_recon_{stamp}_*.")
    print(f"Cancelled {asyncio.run(cancel(keys))} of {len(keys)} Camunda processes (the rest had already ended).")

    with conn.cursor() as cur:
        # A group's fixes go with the group (the backup keeps them); an item's unapplied ones are withdrawn.
        cur.execute("DELETE FROM reconciliation_corrections WHERE group_id IS NOT NULL")
        cur.execute("UPDATE reconciliation_corrections SET status = 'WITHDRAWN' WHERE status <> 'WITHDRAWN' AND synced_at IS NULL")
        cur.execute("DELETE FROM camunda_process_tracking WHERE record_type IN ('reconciliation', 'recon_group')")
        cur.execute(f"""UPDATE pipeline_reconciliation SET status = CASE WHEN has_gap THEN 'OPEN' ELSE 'MATCHED' END,
                           decision = NULL, decided_by = NULL, decided_at = NULL, approved_by = NULL, approved_at = NULL,
                           assigned_to = NULL, cfo_required = false, cfo_reason = NULL, title = NULL, run_id = NULL
                        WHERE {LATEST}""")
        cur.execute(f"""UPDATE pipeline_reconciliation SET status = 'SUPERSEDED', run_id = NULL
                        WHERE NOT ({LATEST}) AND status NOT IN ('MATCHED', 'SUPERSEDED')""")
        cur.execute("UPDATE pipeline_reconciliation SET run_id = NULL WHERE run_id IS NOT NULL")
        cur.execute("""UPDATE reconciliation_exceptions SET status = 'OPEN', resolved_by = NULL, resolved_at = NULL, resolution_note = NULL
                       WHERE status IN ('ACCEPTED', 'CORRECTED', 'DISMISSED')""")
        cur.execute("UPDATE reconciliation_exceptions SET group_id = NULL, carved_out = false WHERE group_id IS NOT NULL OR carved_out")
        cur.execute("DELETE FROM reconciliation_groups")
        cur.execute("DELETE FROM reconciliation_runs")
        cur.execute("""INSERT INTO audit_log (user_id, action, object_type, object_id, old_value, new_value)
                       VALUES (NULL, 'DEMO_RESET', 'reconciliation', 'all', NULL, %s)""", (f"backup_recon_{stamp}_*",))
    conn.commit()
    print("Reconciliation is back to a clean start. Start the poll worker: its first pass creates the tasks and runs.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true", help="make the changes (default: dry run)")
    args = parser.parse_args()
    conn = psycopg2.connect(database_url(), connect_timeout=45)
    try:
        with conn.cursor() as cur:
            for what, n in plan(cur).items():
                print(f"  {n:>5}  {what}")
        conn.rollback()
        if not args.apply:
            print("Dry run: nothing changed. Run again with --apply (stop the poll worker first).")
            return
        reset(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
