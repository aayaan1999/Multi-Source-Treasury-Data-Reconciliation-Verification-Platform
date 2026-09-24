"""Write-back service task worker for the `write-review-outcome` job type
(specs/camunda-bpmn-process-design.md section 3's "Service Task: Write outcome back to Postgres").

Runs as a long-lived Zeebe job worker: subscribes to `write-review-outcome` jobs, which Zeebe
creates when a reviewer completes one of the three user tasks (Fraud Investigation / Compliance
Review / Operations Review) via Tasklist with the review-outcome-form's `outcome`,
`correctedValue` and `reviewedByUserId` fields.

    python camunda/bridge/outcome_worker.py

Writes one row to review_outcomes (specs/bidirectional-sync.md's Direction 2 - Databricks reads
this back over JDBC on Notebook 3's next run). For fraud records, also updates
flagged_transactions.status so the record stops showing as PENDING_REVIEW immediately in the
application layer, without waiting for the next Databricks sync - CLAUDE.md's Databricks/Postgres
split has flagged_transactions.status as the one notebook output the app layer, not Databricks,
owns. For breach records (camunda/bridge/breach_check.py), updates the breaches row instead -
Approved/Rejected/Corrected map onto ACKNOWLEDGED/DISMISSED/ACTION_PLANNED, since the review form
is the same three-button vocabulary shared across every flagCategory, not breach-specific.
"""
import asyncio
import json

import _env  # sets the Windows event-loop policy - must be imported before pyzeebe/grpc.aio, see _env.py
import psycopg2
from pyzeebe import ZeebeWorker, Job, create_insecure_channel

import cases_db
import duplicates_db
import recon_groups_db
import reconciliation_db
from _env import database_url, zeebe_address


BREACH_STATUS = {"APPROVED": "ACKNOWLEDGED", "REJECTED": "DISMISSED", "CORRECTED": "ACTION_PLANNED"}


async def write_review_outcome(job: Job) -> dict:
    v = job.variables
    if v["recordType"] == duplicates_db.RECORD_TYPE:
        # A possible duplicate (specs/entity-matching.md): Approved = same company, Rejected =
        # different; the customer groups are rebuilt from every confirmed pair.
        conn = psycopg2.connect(database_url(), connect_timeout=45)
        try:
            duplicates_db.decide(conn, int(v["recordKey"]), v["outcome"], v["reviewedByUserId"])
        finally:
            conn.close()
        return {}
    if v["recordType"] == cases_db.RECORD_TYPE:
        # A case (specs/task-cases.md): one decision for every flag in it, each with its own
        # review_outcomes row and status update.
        conn = psycopg2.connect(database_url(), connect_timeout=45)
        try:
            cases_db.close_case(conn, int(v["recordKey"]), v["outcome"], v["reviewedByUserId"])
        finally:
            conn.close()
        return {}
    raw_corrected = v.get("correctedValue") or None  # plain text, for breaches.action_plan
    corrected_value = raw_corrected
    if corrected_value:
        try:
            corrected_value = json.dumps(json.loads(corrected_value))
        except (TypeError, ValueError):
            # Reviewer typed a non-JSON string; store it as a JSON string rather than fail the
            # job - specs/camunda-bpmn-process-design.md Open Item 3 flags corrected-value
            # validation as unresolved for the POC.
            corrected_value = json.dumps(corrected_value)

    conn = psycopg2.connect(database_url(), connect_timeout=45)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO review_outcomes
                   (record_type, source_table, record_key, outcome, corrected_value, reviewed_by)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (v["recordType"], v["sourceTable"], v["recordKey"], v["outcome"],
                 corrected_value, v["reviewedByUserId"]),
            )
            if v["recordType"] == "fraud":
                cur.execute(
                    """UPDATE flagged_transactions SET status = %s
                       WHERE transaction_id = %s AND flag_label = %s""",
                    (v["outcome"], v["recordKey"], v["flagLabel"]),
                )
            elif v["recordType"] == "breach":
                cur.execute(
                    """UPDATE breaches SET status = %s, resolved_at = now(), action_plan = %s
                       WHERE breach_id = %s""",
                    (BREACH_STATUS[v["outcome"]], raw_corrected, int(v["recordKey"])),
                )
        conn.commit()
    finally:
        conn.close()

    return {}


async def write_reconciliation_outcome(job: Job) -> dict:
    """reconciliation-review's service task (specs/cfo-reconciliation-workflow.md): the CFO approved,
    so the item and its proposed corrections become APPROVED. The approver is whoever completed the
    last CFO step (approvedByUserId), falling back to the CFO the process was started for."""
    v = job.variables
    conn = psycopg2.connect(database_url(), connect_timeout=45)
    try:
        reconciliation_db.approve(conn, int(v["recordKey"]), int(v.get("approvedByUserId") or v["cfoUserId"]))
    finally:
        conn.close()
    return {}


async def write_recon_group_outcome(job: Job) -> dict:
    """reconciliation-group-review's service task (specs/reconciliation-groups.md): the decision for
    every break in the group except the carve-outs, with the second approver when there was one."""
    v = job.variables
    conn = psycopg2.connect(database_url(), connect_timeout=45)
    try:
        recon_groups_db.decide(conn, int(v["recordKey"]), v["decision"], v.get("excludedIds") or [],
                               v["decidedByUserId"], v.get("approvedByUserId"))
    finally:
        conn.close()
    return {}


async def main() -> None:
    # Built inside main(), not at module scope: a grpc.aio channel created before asyncio.run()
    # starts its loop binds to a throwaway loop instance, distinct from the one main() actually
    # runs in - causes "Task ... got Future ... attached to a different loop" the moment a
    # streaming call (ActivateJobs, used by worker.work()) runs (confirmed live 2026-09-22).
    channel = create_insecure_channel(grpc_address=zeebe_address())
    worker = ZeebeWorker(channel)
    worker.task(task_type="write-review-outcome")(write_review_outcome)
    worker.task(task_type="write-reconciliation-outcome")(write_reconciliation_outcome)
    worker.task(task_type="write-recon-group-outcome")(write_recon_group_outcome)
    print(f"write-review-outcome + write-reconciliation-outcome workers listening on {zeebe_address()}...")
    await worker.work()


if __name__ == "__main__":
    asyncio.run(main())
